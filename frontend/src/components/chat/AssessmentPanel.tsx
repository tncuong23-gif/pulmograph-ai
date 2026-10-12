import { useState } from "react";
import type { Assessment, AssessmentAction, AssessmentFact } from "../../types";
import "./assessment.css";
import { SourcesProvider, SourcesList } from "./EvidenceSources";

const presenceNames = { present: "Có", absent: "Không", unknown: "Không biết", exclude: "Không dùng lần này" };
const factTypes = { symptom: "Triệu chứng", condition: "Bệnh đã khai", medication: "Thuốc", allergy: "Dị ứng", observation: "Quan sát", lab_result: "Xét nghiệm", procedure: "Thủ thuật", family_history: "Tiền sử gia đình", lifestyle: "Lối sống / yếu tố nguy cơ" };

type Props = { assessment: Assessment; busy: boolean; onAction: (body: AssessmentAction) => void };
export function AssessmentPanel(props: Props) {
  const seen=new Set<string>();
  const evidence=(props.assessment.question_proposal?.basis.flatMap(b=>b.evidence||[])??[]).filter(e=>{
    const key=JSON.stringify([e.doc_id,e.evidence_id,e.text]);if(seen.has(key))return false;seen.add(key);return !!e.text;
  });
  const sources=evidence.map((e,i)=>({number:i+1,title:"Nguồn gợi ý từ Knowledge Graph",kind:"document",text:e.text,origins:[{doc_id:e.doc_id,evidence_id:e.evidence_id}]}));
  return <SourcesProvider key={`${props.assessment.id}:${props.assessment.version}`} sources={sources}><AssessmentReview key={`${props.assessment.id}:${props.assessment.version}:${props.assessment.status}`} {...props} /></SourcesProvider>;
}
function AssessmentReview({ assessment: a, busy, onAction }: Props) {
  const historyStep = a.status === "confirming_history";
  const reviewDrafts = historyStep ? (a.history_drafts ?? []) : a.drafts.filter(f => f.origin !== "patient_graph");
  const [facts, setFacts] = useState<AssessmentFact[]>(() => reviewDrafts.map(f => ({ ...f, presence: historyStep ? "exclude" : f.presence })));
  const [checked, setChecked] = useState(false);
  const patch = (index: number, value: Partial<AssessmentFact>) => {
    setFacts(items => items.map((f, i) => i === index ? { ...f, ...value } : f));
    setChecked(false);
  };
  if (a.status === "cancelled") return null;
  if (a.status === "completed") return a.graph_sync === "failed" ? <aside className="assessment-panel" role="status">Kết quả đã lưu. Patient Graph chưa đồng bộ; bản dữ kiện xác nhận vẫn được giữ tại backend.<button className="secondary-button" disabled={busy} onClick={() => onAction({ action: "retry_graph_sync" })}>Thử đồng bộ Patient Graph</button></aside> : null;
  const disabled = busy || a.status === "running";
  return <section className="assessment-panel" aria-label="Đánh giá chẩn đoán" aria-busy={disabled}>
    <div className="assessment-heading"><strong>{a.status === "confirming" ? "1. Xác nhận dữ kiện vừa khai" : historyStep ? "2. Kiểm tra dữ kiện Patient Graph" : a.status === "questioning" ? "3. Khai thác thông tin từ KG" : "4. Xác nhận gửi đánh giá"}</strong><span>Lượt v{a.version}</span></div>
    <p>Dữ kiện trong cuộc trò chuyện này phải thuộc cùng một bệnh nhân. Thông tin cũ chỉ được dùng khi bạn chọn lại và xác nhận.</p>
    {a.warnings.map((w, i) => <p className="assessment-note" key={i}>{w}</p>)}
    {a.error && <p role="alert" className="assessment-note">{a.error}</p>}
    <fieldset disabled={disabled}>
      {(a.status === "confirming" || historyStep) && <>
        <p>{historyStep ? "Đây là dữ kiện đã khai trước đây, chưa được dùng cho lần đánh giá này. Chỉ chọn thông tin còn áp dụng; dữ kiện trùng với bước 1 đã được tổng hợp." : "Chỉ kiểm tra dữ kiện trong câu vừa nhập. Sửa nội dung, chủ thể và thời điểm nếu cần; dữ kiện cũ sẽ được hỏi riêng ở bước sau."}</p>
        {!historyStep && a.question && <blockquote aria-label="Câu vừa khai">{a.question}</blockquote>}
        {!facts.length && <p>Chưa trích được dữ kiện chắc chắn. Hãy thêm thông tin bạn muốn cung cấp.</p>}
        {facts.map((f, i) => <div className="assessment-fact" key={f.id || i}>
          <small>{f.origin === "patient_graph" ? "Từ Patient Graph — chưa tự động sử dụng" : f.origin === "current_message" ? "Gợi ý từ câu vừa nhập" : "Bạn bổ sung"}</small>
          {f.timeframe_needs_review && <p className="assessment-note">Hãy kiểm tra thời điểm áp dụng; việc có trong hồ sơ không tự có nghĩa là tiền sử.</p>}
          {((f.source_refs?.length ?? 0) > 0 || f.source_text) && <details><summary>Xem thông tin nguồn{(f.source_refs?.length ?? 0) > 1 ? ` (${f.source_refs!.length} lần ghi nhận)` : ""}</summary>{(f.source_refs ?? [{source_text:f.source_text, recorded_at:f.recorded_at}]).map((source,j) => <div key={j}><p>{source.source_text}</p>{source.recorded_at && <time>{new Date(source.recorded_at).toLocaleString("vi-VN")}</time>}</div>)}</details>}
          <label>Dữ kiện<input aria-label={`Dữ kiện ${i + 1}`} value={f.display} maxLength={160} onChange={e => patch(i, { display: e.target.value })} /></label>
          <div className="assessment-grid">
            <label>Loại<select value={f.fact_type} onChange={e => patch(i, { fact_type: e.target.value as AssessmentFact["fact_type"] })}>{Object.entries(factTypes).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
            <label>Trạng thái<select aria-label={`Trạng thái ${i + 1}`} value={f.presence} onChange={e => patch(i, { presence: e.target.value as AssessmentFact["presence"] })}>{Object.entries(presenceNames).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
            <label>Thời điểm<select value={f.timeframe} onChange={e => patch(i, { timeframe: e.target.value as AssessmentFact["timeframe"] })}><option value="current">Đợt hiện tại</option><option value="history">Tiền sử</option></select></label>
            <label>Thuộc về<select value={f.experiencer} onChange={e => patch(i, { experiencer: e.target.value as AssessmentFact["experiencer"] })}><option value="patient">Bệnh nhân</option><option value="family">Người thân</option></select></label>
          </div>
          <label>Chi tiết (thời gian, giá trị, đơn vị, liều… nếu có)<input value={f.details} maxLength={1000} onChange={e => patch(i, { details: e.target.value })} /></label>
        </div>)}
        {!historyStep && <button className="secondary-button" disabled={facts.length >= 60} onClick={() => { setFacts(items => [...items, { display: "", fact_type: "symptom", presence: "present", timeframe: "current", experiencer: "patient", details: "" }]); setChecked(false); }}>Thêm dữ kiện</button>}
        <label className="assessment-check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />{historyStep ? "Tôi đã kiểm tra và xác nhận các dữ kiện cũ được chọn còn áp dụng cho cùng bệnh nhân trong lần đánh giá này." : "Tôi đã kiểm tra và xác nhận các dữ kiện vừa khai thuộc cùng một bệnh nhân."}</label>
        <button className="primary-button" disabled={!checked || (!historyStep && !facts.some(f => f.presence !== "exclude") && !(a.history_drafts?.length)) || facts.some(f => f.presence !== "exclude" && !f.display.trim())} onClick={() => onAction({ action: historyStep ? "confirm_history" : "confirm", same_patient: true, ...(historyStep ? {reviewed:true} : {}), facts: facts.filter(f => f.display.trim()).map(({ id, display, fact_type, presence, timeframe, details, experiencer }) => ({ id, display, fact_type, presence, timeframe, details, experiencer })) })}>{historyStep ? "Xác nhận dữ kiện cũ đã chọn" : "Xác nhận dữ kiện vừa khai"}</button>
        {historyStep && <button className="secondary-button" onClick={() => onAction({action:"confirm_history", same_patient:true, reviewed:true, facts:[]})}>Không dùng dữ kiện cũ, tiếp tục</button>}
      </>}
      {a.status === "questioning" && a.question_proposal && <>
        <p>Câu hỏi do KG gợi ý, không có nghĩa bạn mắc bệnh hay có triệu chứng này. Chỉ trả lời theo tình trạng thực tế; bạn có thể bỏ qua.</p>
        <h3>{a.question_proposal.question_text}</h3>
        <SourcesList/>
        <label className="assessment-check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />Tôi đã kiểm tra câu hỏi và muốn trả lời cho bệnh nhân trong cuộc trò chuyện này.</label>
        <div className="assessment-actions">{(["present", "absent", "unknown", "skip"] as const).map(answer => <button className="secondary-button" key={answer} disabled={answer !== "skip" && !checked} onClick={() => onAction({ action: "answer", question_id: a.question_proposal!.question_id, answer, reviewed: checked })}>{answer === "skip" ? "Bỏ qua" : presenceNames[answer]}</button>)}</div>
        <button className="secondary-button" onClick={() => onAction({ action: "finish_questions" })}>Kết thúc hỏi bổ sung, xem lại dữ kiện</button>
      </>}
      {["ready", "failed", "running"].includes(a.status) && <>
        <ul>{a.facts.map((f, i) => <li key={i}><strong>{f.display}: {presenceNames[f.presence]}</strong> · {f.timeframe === "current" ? "hiện tại" : "tiền sử"} · {f.experiencer === "patient" ? "bệnh nhân" : "người thân"}{f.details && ` · ${f.details}`}</li>)}</ul>
        {a.status === "running" ? <p role="status">Đang xử lý dữ kiện đã xác nhận… Bạn có thể tải lại trang để xem tiến trình.</p> : <>
          <label className="assessment-check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />Tôi đã kiểm tra bản dữ kiện cuối cùng và đồng ý gửi để đánh giá.</label>
          <button className="primary-button" disabled={!checked} onClick={() => onAction({ action: "diagnose", reviewed: true })}>{a.status === "failed" ? "Thử lại với dữ kiện đã xác nhận" : "Gửi đánh giá"}</button>
          <p>Cần sửa dữ kiện? Hủy lượt này rồi gửi lại câu hỏi để xác nhận lại.</p>
        </>}
      </>}
      {a.status !== "running" && <button className="assessment-cancel" onClick={() => onAction({ action: "cancel" })}>Hủy lượt đánh giá</button>}
    </fieldset>
  </section>;
}
