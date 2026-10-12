import { useEffect, useRef, useState } from "react";
import { AudioLines, Mic, Square, Volume2, VolumeX } from "lucide-react";
import { Modal } from "../common/Modal";
import { AssessmentPanel } from "../chat/AssessmentPanel";
import { useChat } from "../../context/ChatContext";
import { ApiError, errorMessage } from "../../api/client";
import { voiceApi } from "../../api/voiceApi";
import type { VoiceReply } from "../../api/voiceApi";
import type { Assessment } from "../../types";
import "./voice.css";
import { SpeechPlayer, speechSentences } from "./SpeechPlayer";

type Speakable = Pick<VoiceReply, "spoken_text" | "conversation_action" | "expects_reply" | "speech_chunks"> & { assessment?: Assessment | null };
type Phase = "idle" | "listening" | "transcribing" | "review" | "processing" | "speaking";
const labels: Record<Phase, string> = { idle: "Sẵn sàng trò chuyện", listening: "Đang nghe", transcribing: "Đang nhận dạng", review: "Kiểm tra lời vừa nói", processing: "Đang xử lý", speaking: "Đang trả lời" };
export function VoiceAssistant({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const { conversations, ingestConversation, assessmentAction, busyIds } = useChat();
  const assessment = conversations[conversationId]?.assessment;
  const [phase, setPhase] = useState<Phase>("idle");
  const [transcript, setTranscript] = useState("");
  const [sttWarnings, setSttWarnings] = useState<string[]>([]);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const lastRecording = useRef<Blob | null>(null);
  const [spoken, setSpoken] = useState("");
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [externalTts, setExternalTts] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [autoListen, setAutoListen] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [sending, setSending] = useState(false);
  const pcmPlayer = useRef<SpeechPlayer | null>(null);
  const audioEpoch = useRef(0);
  const mounted = useRef(true);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const audioUrl = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const maxTimer = useRef<number | null>(null);
  const requestId = useRef<string | null>(null);
  const spokenVersion = useRef<number | undefined>(undefined);
  const currentAssessment = useRef<Assessment | null | undefined>(assessment);
  currentAssessment.current = assessment;
  const preferences = useRef({ muted, autoListen });
  preferences.current = { muted, autoListen };
  const activeReply = useRef<Speakable | null>(null);
  const lastAssessment = useRef<string | null>(null);
  const turnInFlight = useRef(false);
  const clearAudio = () => {
    audioEpoch.current += 1;
    pcmPlayer.current?.stop(); pcmPlayer.current = null;
    if (audio.current) { audio.current.onended = null; audio.current.onerror = null; audio.current.pause(); audio.current = null; }
    if (audioUrl.current) { URL.revokeObjectURL(audioUrl.current); audioUrl.current = null; }
  };
  const releaseMic = () => {
    if (maxTimer.current !== null) clearTimeout(maxTimer.current);
    maxTimer.current = null;
    stream.current?.getTracks().forEach(track => track.stop()); stream.current = null;
  };
  const cancel = () => {
    controller.current?.abort(); clearAudio();
    if (recorder.current) { recorder.current.onstop = null; if (recorder.current.state !== "inactive") recorder.current.stop(); }
    recorder.current = null; releaseMic();
  };
  useEffect(() => {
    mounted.current = true;
    const configController = new AbortController();
    voiceApi.config(configController.signal).then(config => {
      if (!mounted.current) return;
      setExternalTts(config.external_tts);
      setStreaming(Boolean(config.streaming) && typeof AudioContext !== "undefined");
      if (config.greeting && !currentAssessment.current && !activeReply.current) {
        setSpoken(config.greeting);
        activeReply.current = { spoken_text: config.greeting, conversation_action: "greeting", expects_reply: true };
      }
      setInstalled(config.stt_installed && config.tts_installed);
      if (!config.stt_installed || !config.tts_installed) setError(config.detail || "Chưa cài thành phần giọng nói. Xem hướng dẫn cài requirements-voice.txt.");
    }).catch(e => { if (mounted.current && !configController.signal.aborted) setError(errorMessage(e)); });
    return () => { mounted.current = false; configController.abort(); lastRecording.current = null; cancel(); };
    // Resources belong to this dialog lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const play = async (reply: Speakable) => {
    activeReply.current = reply;
    spokenVersion.current = reply.assessment?.version;
    if (reply.assessment) lastAssessment.current = `${reply.assessment.id}:${reply.assessment.version}`;
    setSpoken(reply.spoken_text);
    if (preferences.current.muted) { setPhase("idle"); return; }
    clearAudio();
    const epoch = audioEpoch.current;
    if (streaming) {
      try {
        setPhase("processing");
        const player = new SpeechPlayer(() => { if (mounted.current) setPhase("speaking"); }, e => { if (mounted.current) setError(errorMessage(e)); });
        pcmPlayer.current = player;
        for (const sentence of reply.speech_chunks || speechSentences(reply.spoken_text)) player.enqueue(sentence);
        await player.finish();
        if (!mounted.current || pcmPlayer.current !== player) return;
        pcmPlayer.current = null; setPhase("idle");
        if (preferences.current.autoListen && reply.expects_reply && reply.conversation_action === "answer") void start();
      } catch (e) { if (mounted.current && audioEpoch.current === epoch) { clearAudio(); setError(errorMessage(e)); setPhase("idle"); } }
      return;
    }
    const playbackController = new AbortController(); controller.current = playbackController;
    const chunks: string[] = [];
    let remaining = reply.spoken_text;
    while (remaining.length > 14000) {
      const boundary = remaining.lastIndexOf(" ", 14000);
      const cut = boundary > 0 ? boundary + 1 : 14000;
      chunks.push(remaining.slice(0, cut)); remaining = remaining.slice(cut);
    }
    if (remaining.trim()) chunks.push(remaining);
    const playChunk = async (index: number): Promise<void> => {
      try {
        if (!mounted.current || playbackController.signal.aborted) return;
        if (preferences.current.muted) { setPhase("idle"); return; }
        setPhase("processing");
        const blob = await voiceApi.speak(chunks[index].trim(), playbackController.signal);
        if (!mounted.current || playbackController.signal.aborted) return;
        if (preferences.current.muted) { setPhase("idle"); return; }
        const url = URL.createObjectURL(blob); audioUrl.current = url;
        const player = new Audio(url); audio.current = player;
        player.onended = () => {
          clearAudio();
          if (index + 1 < chunks.length) { void playChunk(index + 1); return; }
          setPhase("idle");
          if (preferences.current.autoListen && reply.expects_reply && reply.conversation_action === "answer") void start();
        };
        player.onerror = () => { clearAudio(); setPhase("idle"); setError("Không phát được âm thanh. Bạn có thể thử phát lại."); };
        setPhase("speaking"); await player.play();
      } catch (e) {
        if (mounted.current && !playbackController.signal.aborted) { clearAudio(); setPhase("idle"); setError(errorMessage(e)); }
      }
    };
    await playChunk(0);
  };
  const fetchReply = async () => {
    const replyController = new AbortController(); controller.current = replyController;
    try {
      setPhase("processing");
      const reply = await voiceApi.reply(conversationId, replyController.signal);
      if (!mounted.current || replyController.signal.aborted) return;
      ingestConversation(reply.conversation); await play(reply);
    } catch (e) {
      if (mounted.current && !replyController.signal.aborted) { setPhase("idle"); setError(errorMessage(e)); }
    }
  };
  useEffect(() => {
    if (!assessment || turnInFlight.current || ["review", "listening", "transcribing", "speaking"].includes(phase)) return;
    const key = `${assessment.id}:${assessment.version}`;
    if (lastAssessment.current === key) return;
    lastAssessment.current = key;
    void fetchReply();
    // An assessment transition (including background completion) gets one spoken prompt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assessment?.id, assessment?.version, phase]);

  async function start() {
    if (!installed || currentAssessment.current?.status === "running" || turnInFlight.current) return;
    cancel(); setError(""); setSuggestion(null); setSttWarnings([]); lastRecording.current = null; requestId.current = null;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("Micro cần trình duyệt hỗ trợ thu âm và địa chỉ HTTPS hoặc localhost."); return;
    }
    setPhase("listening");
    try {
      const input = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      if (!mounted.current) { input.getTracks().forEach(t => t.stop()); return; }
      stream.current = input;
      const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find(m => MediaRecorder.isTypeSupported(m));
      const recording = new MediaRecorder(input, mime ? { mimeType: mime, audioBitsPerSecond: 96000 } : undefined);
      recorder.current = recording;
      const chunks: BlobPart[] = [];
      recording.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recording.onerror = () => { cancel(); setPhase("idle"); setError("Thu âm bị gián đoạn. Hãy thử lại."); };
      recording.onstop = async () => {
        releaseMic(); recorder.current = null;
        const sttController = new AbortController(); controller.current = sttController;
        try {
          setPhase("transcribing");
          lastRecording.current = new Blob(chunks, { type: recording.mimeType });
          const result = await voiceApi.transcribe(lastRecording.current, sttController.signal);
          if (mounted.current && !sttController.signal.aborted) { setTranscript(result.transcript); setSttWarnings(result.warnings || []); setSuggestion(result.suggested_transcript || null); setPhase("review"); }
        } catch (e) { if (mounted.current && !sttController.signal.aborted) { setPhase("idle"); setError(errorMessage(e)); } }
      };
      recording.start(250);
      maxTimer.current = window.setTimeout(() => { if (recording.state === "recording") recording.stop(); }, 90000);
    } catch (e) { releaseMic(); if (mounted.current) { setPhase("idle"); setError(e instanceof DOMException && e.name === "NotAllowedError" ? "Bạn chưa cho phép dùng micro. Hãy cấp quyền trong trình duyệt rồi thử lại." : errorMessage(e)); } }
  }
  async function recognizeAgain() {
    if (!lastRecording.current) return;
    const retryController = new AbortController(); controller.current = retryController;
    setPhase("transcribing"); setError("");
    try {
      const result = await voiceApi.transcribe(lastRecording.current, retryController.signal, "careful");
      if (!mounted.current || retryController.signal.aborted) return;
      setTranscript(result.transcript); setSttWarnings(result.warnings || []);
      setSuggestion(result.suggested_transcript || null); requestId.current = null;
    } catch (e) { if (mounted.current && !retryController.signal.aborted) setError(errorMessage(e)); }
    finally { if (mounted.current && !retryController.signal.aborted) setPhase("review"); }
  }
  async function send() {
    if (!transcript.trim() || turnInFlight.current) return;
    turnInFlight.current = true; setSending(true); setPhase("processing"); setError("");
    const turnController = new AbortController(); controller.current = turnController;
    const id = requestId.current ?? crypto.randomUUID(); requestId.current = id;
    let player: SpeechPlayer | null = null;
    const received: string[] = [];
    try {
      if (streaming && !preferences.current.muted) {
        clearAudio();
        player = new SpeechPlayer(() => { if (mounted.current) setPhase("speaking"); }, e => { if (mounted.current) setError(errorMessage(e)); });
        pcmPlayer.current = player;
      }
      const reply = streaming
        ? await voiceApi.turnStream(conversationId, transcript.trim(), id, spokenVersion.current, turnController.signal, sentence => {
          if (!mounted.current || turnController.signal.aborted) return;
          received.push(sentence); setSpoken(received.join(" "));
          if (!preferences.current.muted) player?.enqueue(sentence);
        })
        : await voiceApi.turn(conversationId, transcript.trim(), id, spokenVersion.current, turnController.signal);
      if (!mounted.current || turnController.signal.aborted) return;
      ingestConversation(reply.conversation); setTranscript(""); setSuggestion(null); lastRecording.current = null; requestId.current = null;
      turnInFlight.current = false; setSending(false);
      if (!streaming) await play(reply);
      else {
        activeReply.current = reply; spokenVersion.current = reply.assessment?.version;
        if (reply.assessment) lastAssessment.current = `${reply.assessment.id}:${reply.assessment.version}`;
        setSpoken(reply.spoken_text);
        if (player && !preferences.current.muted) {
          const chunks = reply.speech_chunks || speechSentences(reply.spoken_text);
          for (const sentence of chunks.slice(received.length)) player.enqueue(sentence);
          try { await player.finish(); }
          catch (e) { if (mounted.current) setError(errorMessage(e)); }
        } else player?.stop();
        if (!mounted.current || turnController.signal.aborted || (pcmPlayer.current && pcmPlayer.current !== player)) return;
        if (pcmPlayer.current === player) pcmPlayer.current = null;
        setPhase("idle");
        if (preferences.current.autoListen && reply.expects_reply && reply.conversation_action === "answer" && !preferences.current.muted) void start();
      }
    } catch (e) {
      if (mounted.current && !turnController.signal.aborted) {
        player?.stop();
        setError(errorMessage(e));
        if (e instanceof ApiError && e.status === 409) {
          setTranscript(""); requestId.current = null; await fetchReply();
        } else setPhase("review");
      }
    } finally { turnInFlight.current = false; if (mounted.current) setSending(false); }
  }
  const working = phase === "processing" || phase === "transcribing";
  const activeAssessment = assessment && !["completed", "cancelled"].includes(assessment.status);
  return <Modal open onOpenChange={open => { if (!open) onClose(); }} title="Trò chuyện bằng giọng nói" description="Nói câu hỏi, kiểm tra lời nhận dạng và nghe trợ lý trả lời." className="voice-dialog">
    <div className={`voice-orb ${phase}`} aria-hidden="true"><AudioLines size={48} /></div>
    <h2 className="voice-status" role="status">{labels[phase]}</h2>
    <p className="voice-hint">Micro chỉ hoạt động khi bạn bắt đầu nghe. Nhấn kết thúc lượt nói khi đã nói xong.</p>
    {turnInFlight.current && <p className="voice-hint">Đang hoàn tất câu trả lời. Đóng bảng sẽ ngắt lượt phản hồi đang truyền.</p>}
    {externalTts && <p className="voice-disclosure">Giọng đọc hiện dùng dịch vụ trực tuyến. Nội dung lời đọc được gửi tới dịch vụ tạo giọng nói.</p>}
    {spoken && <div className="voice-script" aria-label="Lời nói của trợ lý">{spoken}</div>}
    {conversations[conversationId]?.messages.at(-1)?.metadata?.kg_clarification?.can_confirm &&
      <p className="voice-hint">Tên cần tra cứu chưa rõ. Hãy kết thúc trò chuyện giọng nói để chọn tên và xác nhận trong khung chat.</p>}
    {error && <p role="alert" className="voice-error">{error}</p>}
    {phase === "review" && sttWarnings.map((warning, index) => <p key={index} role="status" className="voice-caption">{warning}</p>)}
    {phase === "review" && <div className="voice-review"><label htmlFor="voice-transcript">Lời nhận dạng — kiểm tra tên bệnh, phủ định, con số và đơn vị</label><textarea id="voice-transcript" value={transcript} maxLength={6000} onChange={e => { setTranscript(e.target.value); setSuggestion(null); requestId.current = null; }} />
      {suggestion && <div><p>Cách viết phổ thông: {suggestion}</p><button className="secondary-button" onClick={() => { setTranscript(suggestion); setSuggestion(null); requestId.current = null; }}>Dùng cách viết này</button></div>}
      {lastRecording.current && <button className="secondary-button" onClick={() => void recognizeAgain()}>Nhận dạng lại kỹ hơn</button>}
      <button className="primary-button" disabled={!transcript.trim()} onClick={() => void send()}>Xác nhận lời nói và gửi</button></div>}
    <div className="voice-controls">
      {phase === "idle" && lastRecording.current && error && <button className="secondary-button" onClick={() => void recognizeAgain()}>Nhận dạng lại kỹ hơn</button>}
      {phase === "listening" ? <button className="primary-button" onClick={() => recorder.current?.stop()}><Square size={17} /> Kết thúc lượt nói</button> : <button className="primary-button" disabled={working || sending || !installed || assessment?.status === "running"} onClick={() => void start()}><Mic size={17} />{spoken ? "Nói tiếp" : "Bắt đầu nghe"}</button>}
      {(phase === "speaking" || working) && <button className="secondary-button" onClick={() => { if (turnInFlight.current) { clearAudio(); setMuted(true); setPhase("processing"); } else { cancel(); setPhase("idle"); } }}>Dừng âm thanh</button>}
      <button className="secondary-button" onClick={() => { const value = !muted; setMuted(value); if (value) { clearAudio(); if (phase === "speaking") setPhase("idle"); } }}>{muted ? <VolumeX size={17} /> : <Volume2 size={17} />}{muted ? "Bật tiếng" : "Tắt tiếng"}</button>
      {activeReply.current && !working && !sending && phase !== "listening" && <button className="secondary-button" onClick={() => void play(activeReply.current!)}>Phát lại</button>}
    </div>
    <label className="voice-auto"><input type="checkbox" checked={autoListen} onChange={e => setAutoListen(e.target.checked)} />Tự nghe lượt tiếp theo sau câu trả lời thông thường</label>
    {activeAssessment && <AssessmentPanel key={`${assessment.id}:${assessment.version}`} assessment={assessment} busy={busyIds.has(conversationId) || working || phase === "speaking" || phase === "listening"} onAction={body => { cancel(); setPhase("idle"); void assessmentAction(conversationId, body); }} />}
    <button className="voice-exit secondary-button" onClick={onClose}>Kết thúc trò chuyện giọng nói</button>
  </Modal>;
}
