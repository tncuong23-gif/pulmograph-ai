export type AttachmentType = "medical_record" | "xray";
export type AttachmentStatus =
  "pending" | "uploading" | "uploaded" | "processing" | "processed" | "error";
export interface Attachment {
  id: string;
  type: AttachmentType;
  fileName: string;
  fileSize: number;
  mimeType: string;
  status: AttachmentStatus;
  progress: number;
  url?: string;
  serverId?: string;
  width?: number;
  height?: number;
  error?: string;
  analysisAnswer?: string;
  sources?: EvidenceSource[];
  isDicom?: boolean;
}
export interface SelectedRecord {
  file: File;
  attachment: Attachment;
}
export interface ChatMessage {
  metadata?: {
    route?: string; assessment_id?: string; snapshot_id?: string;
    sources?: EvidenceSource[];
    kg_query?: { mode?: "one_hop" | "multi_hop" | "path" | "compare" | "common" | "difference"; status?: string; warnings?: string[]; fact_count?: number } | null;
    kg_comparison?: KGComparison | null;
    kg_clarification?: KGClarification;
    kg_confirmation?: KGConfirmation;
    kg_confirmation_used?: boolean;
  };
  kind?: "medical_record";
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  createdAt: string;
  feedback?: "up" | "down";
}
export interface ConversationSummary {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}
export interface Conversation extends ConversationSummary {
  assessment?: Assessment | null;
  messages: ChatMessage[];
}
export interface ChatRequest {
  conversationId: string;
  message: ChatMessage;
  regenerateMessageId?: string;
  kg_confirmation?: KGConfirmation;
}
export interface EvidenceSource {
  number?: number; title?: string; section?: string; kind?: string; module?: string;
  origins?: {doc_id?: string; document_id?: string; evidence_id?: string; chunk_id?: string; proposition_id?: string}[];
  doc_id?: string; evidence_id?: string; text?: string;
  document_id?: string; chunk_id?: string; proposition_id?: string;
}
export interface KGConfirmation { message_id: string; entity_ids: string[] }
export interface KGEntity { id: string; name: string; type: string }
export interface KGComparisonFact {
  subject: KGEntity; predicate: string; object: KGEntity;
  evidence: EvidenceSource[]; doc_ids: string[];
  assertions: { relation_id?: string; document_id?: string; evidence_ids?: string[];
    properties: Record<string, unknown>; properties_valid: boolean }[];
}
export interface KGComparison {
  mode: "compare" | "common" | "difference";
  entities: KGEntity[];
  notice: string; truncated: boolean; complete: boolean;
  criteria: { id: string; label: string }[];
  rows: { criterion: string; criterion_label: string; feature: KGEntity;
    predicate: string; direction: "in" | "out";
    classification: "common" | "left_only" | "right_only" | "assertion_difference" | "needs_review";
    label: string;
    cells: { entity_id: string; status: string; fact_indices: number[] }[];
  }[];
  facts: KGComparisonFact[];
}
export interface KGClarification {
  message: string;
  can_confirm: boolean;
  groups: { mention: string; candidate_count?: number;
    candidates: { id: string; name: string; type: string; matched_by: string }[] }[];
}
export interface ChatResponse {
  assessment?: Assessment | null;
  conversation?: Conversation;
  message: ChatMessage;
}
export interface SystemStatus {
  online: boolean;
  model: string;
  knowledgeBase: string;
  mode: "mock" | "live";
}
export type Theme = "light" | "dark";

export interface AssessmentFact {
  id?: string;
  fact_id?: string;
  display: string;
  fact_type: "symptom" | "condition" | "medication" | "allergy" | "observation" | "lab_result" | "procedure" | "family_history" | "lifestyle";
  presence: "present" | "absent" | "unknown" | "exclude";
  timeframe: "current" | "history";
  details: string;
  experiencer: "patient" | "family";
  origin?: string;
  source_text?: string;
  recorded_at?: string;
  source_refs?: { source_id?: string; source_text?: string; recorded_at?: string }[];
  timeframe_needs_review?: boolean;
}
export interface Assessment {
  id: string;
  version: number;
  status: "confirming" | "confirming_history" | "questioning" | "ready" | "running" | "failed" | "completed" | "cancelled";
  drafts: AssessmentFact[];
  history_drafts?: AssessmentFact[];
  workflow_version?: number;
  question?: string;
  facts: AssessmentFact[];
  warnings: string[];
  error?: string;
  graph_sync: string;
  question_proposal?: {
    question_id: string;
    question_text: string;
    basis: { evidence: { doc_id?: string; evidence_id?: string; text?: string }[] }[];
  } | null;
}
export interface AssessmentAction {
  action: "confirm" | "confirm_history" | "answer" | "finish_questions" | "diagnose" | "cancel" | "retry_graph_sync";
  same_patient?: boolean;
  facts?: AssessmentFact[];
  question_id?: string;
  answer?: "present" | "absent" | "unknown" | "skip";
  reviewed?: boolean;
}
