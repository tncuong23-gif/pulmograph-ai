"""Durable, conversation-scoped diagnostic interview. No client-supplied KG IDs."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..schemas import iso_now
from .evidence import prepare_evidence, validate_answer
from .assessment_facts import make_drafts, consolidate, history_candidates, clean_details, normalized
from ..modules.context.domain.models import ClinicalFact, HistoryTurn, Role

logger = logging.getLogger("uvicorn.error")
TERMINAL = {"completed", "cancelled"}


class FactChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str | None = None
    display: str = Field(min_length=1, max_length=160)
    fact_type: Literal["symptom", "condition", "medication", "allergy", "observation", "lab_result", "procedure", "family_history", "lifestyle"] = "symptom"
    presence: Literal["present", "absent", "unknown", "exclude"]
    timeframe: Literal["current", "history"]
    details: str = Field(default="", max_length=1000)
    experiencer: Literal["patient", "family"] = "patient"


class AssessmentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)
    action: Literal["confirm", "confirm_history", "answer", "finish_questions", "diagnose", "cancel", "retry_graph_sync"]
    same_patient: bool = False
    facts: list[FactChoice] = Field(default_factory=list, max_length=60)
    question_id: str | None = None
    answer: Literal["present", "absent", "unknown", "skip"] | None = None
    reviewed: bool = False


class AssessmentService:
    def __init__(self, store, modules, llm, context_container=None):
        self.store, self.modules, self.llm = store, modules, llm
        self.context_container = context_container
        self.locks: dict[str, asyncio.Lock] = {}
        self.chat_locks: dict[str, asyncio.Lock] = {}

    def chat_lock(self, conversation_id):
        return self.chat_locks.setdefault(conversation_id, asyncio.Lock())

    def start(self, conversation_id, message_id, question, context, messages=()):
        existing = self.store.latest_assessment(conversation_id)
        if existing and existing["message_id"] == message_id:
            return existing
        if existing and existing["status"] not in TERMINAL:
            raise HTTPException(409, "Hãy hoàn tất hoặc hủy lượt đánh giá đang mở.")
        drafts = make_drafts(context.get("draft_facts", []), "current_message", question)
        history = make_drafts(context.get("patient_facts", []), "patient_graph")
        state = {"id": str(uuid4()), "conversation_id": conversation_id, "patient_id": conversation_id,
                 "message_id": message_id, "question": question, "version": 1, "status": "confirming",
                 "created_at": iso_now(), "workflow_version": 2, "drafts": drafts, "history_drafts": history, "facts": [], "asked_entity_ids": [],
                 "answers": [], "question_proposal": None, "warnings": [], "events": [], "action_ids": [],
                 "graph_sync": "pending", "snapshot": None}
        for m in messages:
            if m["role"] == "assistant":
                m.setdefault("metadata", {})["assessment_id"] = state["id"]
        self.store.commit_assessment(state, expected_version=None, messages=messages)
        return state

    @staticmethod
    def _message(state, role, text):
        return {"id": str(uuid4()), "role": role, "content": text, "createdAt": iso_now(),
                "metadata": {"route": "DIAGNOSTIC_ASSESSMENT", "assessment_id": state["id"]}}

    @staticmethod
    def _require_patient_fact(facts):
        if not any(f["experiencer"] == "patient" and f["presence"] in {"present", "absent"} for f in facts):
            raise HTTPException(422, "Cần ít nhất một dữ kiện của bệnh nhân được xác nhận Có hoặc Không.")

    @staticmethod
    def _confirmed_choices(choices, drafts, history=False):
        by_id = {f["id"]: f for f in drafts}
        seen, facts = set(), []
        confirmation_id = str(uuid4())
        for choice in choices:
            if (history and not choice.id) or (choice.id and (choice.id not in by_id or choice.id in seen)):
                raise HTTPException(422, "Mã dữ kiện không hợp lệ, không thuộc bước này hoặc bị lặp.")
            if choice.id: seen.add(choice.id)
            if choice.presence == "exclude": continue
            original = by_id.get(choice.id, {})
            values = choice.model_dump(exclude={"id"})
            values["details"] = clean_details(values["details"])
            canonical = original.get("canonical_display") if normalized(values["display"]) == normalized(original.get("display")) else None
            facts.append({**values, "canonical_display":canonical, "fact_id":str(uuid4()),
                          "source_id":confirmation_id,"confirmed_at":iso_now(),"confirmation_status":"user_confirmed",
                          "origin":original.get("origin","manual"),"original_source_id":original.get("source_id"),
                          "source_refs":copy.deepcopy(original.get("source_refs", [])),
                          "reconfirmed_only":history and all(values[k] == original.get(k) for k in values),
                          "original_fact":copy.deepcopy(original.get("original_fact")) if canonical else None})
        return consolidate(facts), confirmation_id

    @staticmethod
    def _check_conflicts(facts):
        groups = {}
        for fact in facts:
            key = (fact["fact_type"], fact.get("kg_entity_id") or (fact.get("canonical_display") or fact["display"]).casefold(), fact["timeframe"], fact["experiencer"])
            groups.setdefault(key, set()).add(fact["presence"])
        if any({"present", "absent"} <= values for values in groups.values()):
            raise HTTPException(422, "Có dữ kiện vừa Có vừa Không trong cùng thời điểm. Hãy sửa trước khi xác nhận.")

    async def _question(self, state):
        state["question_proposal"] = None
        state["status"] = "ready"
        if len(state["answers"]) >= 5:
            state["kg_status"] = "question_limit"
            return
        relevant = [f for f in state["facts"] if f["experiencer"] == "patient"]
        if not relevant:
            state["kg_status"] = "no_patient_facts"
            return
        try:
            # Chunk requests to respect the KG mapping contract.
            mappings = {}
            names = list(dict.fromkeys(f.get("canonical_display") or f["display"] for f in relevant))
            for offset in range(0, len(names), 30):
                result = await self.modules._post(self.modules.kg_url, "/api/v1/kg/assessment/map", {"mentions": names[offset:offset+30]})
                mappings.update({m["mention"]: m for m in result.get("items", [])})
            mapped = []
            for fact in relevant:
                mapping = mappings.get(fact.get("canonical_display") or fact["display"], {})
                fact["mapping_status"] = mapping.get("status", "not_found")
                fact["kg_entity_id"] = mapping.get("kg_entity_id") if mapping.get("status") == "resolved" else None
                if fact["kg_entity_id"]:
                    mapped.append({k: fact[k] for k in ("fact_id", "kg_entity_id", "presence", "confirmation_status", "confirmed_at", "source_id", "timeframe")})
            if not mapped:
                state["kg_status"] = "no_exact_mapping"
                state["warnings"] = ["KG chưa ánh xạ chắc chắn được các dữ kiện. Có thể tiếp tục với dữ kiện đã xác nhận."]
                return
            self._check_conflicts(state["facts"])
            result = await self.modules._post(self.modules.kg_url, "/api/v1/kg/assessment/followups", {
                "patient_id": state["patient_id"], "assessment_id": state["id"], "facts": mapped,
                "asked_entity_ids": state["asked_entity_ids"], "max_questions": 5})
            state["kg_status"] = result.get("status")
            # Proposals remain reviewable, never interpreted as patient findings.
            for q in result.get("questions", []):
                if q.get("target_entity_id") in state["asked_entity_ids"]:
                    continue
                if q.get("basis") and all(b.get("evidence") and b.get("assertions") and
                    all(a.get("properties_valid") is True and not a.get("properties") for a in b["assertions"])
                    for b in q["basis"]):
                    state["question_proposal"] = q
                    state["status"] = "questioning"
                    break
            if result.get("questions") and not state["question_proposal"]:
                state["warnings"] = ["Các gợi ý KG có điều kiện hoặc thiếu nguồn đủ rõ để hiển thị tự động; đã bỏ qua bước hỏi bổ sung."]
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("assessment.kg_failed assessment_id=%s error_type=%s", state["id"], type(exc).__name__)
            state["kg_status"] = "unavailable"
            state["warnings"] = ["Không truy cập được KG. Bạn có thể tiếp tục với dữ kiện đã xác nhận."]

    async def action(self, assessment_id, payload):
        async with self.locks.setdefault(assessment_id, asyncio.Lock()):
            state = self.store.get_assessment(assessment_id)
            if state is None:
                raise HTTPException(404, "Không tìm thấy lượt đánh giá.")
            if payload.action_id in state["action_ids"]:
                return state
            if state["version"] != payload.version:
                raise HTTPException(409, "Lượt đánh giá đã thay đổi. Giao diện cần tải lại trạng thái mới nhất.")
            version = state["version"]
            messages = []
            if payload.action == "retry_graph_sync" and state["status"] in {"completed", "failed"} and state["snapshot"]:
                try:
                    await self._sync_graph(state)
                    state["graph_sync"] = "synced"
                    state["warnings"] = [w for w in state["warnings"] if "Patient Graph" not in w]
                except Exception as exc:
                    logger.warning("assessment.graph_retry_failed id=%s error_type=%s", state["id"], type(exc).__name__)
                    raise HTTPException(503, "Patient Graph chưa kết nối được. Bản xác nhận vẫn được giữ tại backend.") from exc
            elif payload.action == "cancel" and state["status"] in {"confirming", "confirming_history", "questioning", "ready", "failed"}:
                state["status"] = "cancelled"
                messages.append(self._message(state, "assistant", "Đã hủy lượt đánh giá. Bạn có thể nhập câu hỏi mới."))
            elif payload.action == "confirm" and state["status"] == "confirming":
                if not payload.same_patient:
                    raise HTTPException(422, "Cần xác nhận các dữ kiện thuộc cùng một bệnh nhân.")
                facts, confirmation_id = self._confirmed_choices(payload.facts, state["drafts"])
                if not facts and not state.get("history_drafts"):
                    raise HTTPException(422, "Hãy thêm ít nhất một dữ kiện bạn muốn cung cấp.")
                self._check_conflicts(facts)
                state["facts"] = facts
                state["history_drafts"] = history_candidates(state.get("history_drafts", []), facts)
                text = ("Tôi xác nhận dữ kiện vừa khai:\n" + self.facts_text(facts)) if facts else "Tôi chưa khai thêm dữ kiện mới; chuyển sang kiểm tra dữ kiện cũ."
                user = self._message(state, "user", text)
                user["id"] = confirmation_id
                messages.append(user)
                if state["history_drafts"]:
                    state["status"] = "confirming_history"
                else:
                    self._require_patient_fact(state["facts"])
                    await self._question(state)
            elif payload.action == "confirm_history" and state["status"] == "confirming_history":
                if not payload.reviewed or (any(f.presence != "exclude" for f in payload.facts) and not payload.same_patient):
                    raise HTTPException(422, "Hãy kiểm tra dữ kiện cũ và xác nhận phần được chọn thuộc cùng bệnh nhân.")
                facts, confirmation_id = self._confirmed_choices(payload.facts, state.get("history_drafts", []), history=True)
                merged = consolidate(state["facts"] + facts)
                self._require_patient_fact(merged)
                self._check_conflicts(merged)
                state["facts"] = merged
                state["history_reviewed"] = True
                user = self._message(state, "user", ("Tôi xác nhận dùng thêm dữ kiện Patient Graph:\n" + self.facts_text(facts)) if facts else "Tôi không dùng thêm dữ kiện cũ trong lần đánh giá này.")
                user["id"] = confirmation_id
                messages.append(user)
                await self._question(state)
            elif payload.action == "answer" and state["status"] == "questioning":
                q = state["question_proposal"]
                if payload.question_id != q["question_id"] or payload.answer is None:
                    raise HTTPException(422, "Câu hỏi hoặc câu trả lời không hợp lệ.")
                if payload.answer != "skip" and not payload.reviewed:
                    raise HTTPException(422, "Hãy kiểm tra câu hỏi và nguồn gợi ý trước khi trả lời.")
                state["asked_entity_ids"].append(q["target_entity_id"])
                source_id = str(uuid4())
                state["answers"].append({"question": q, "answer": payload.answer, "source_id": source_id, "answered_at": iso_now()})
                if payload.answer != "skip":
                    state["facts"].append({"fact_id": str(uuid4()), "display": q["target_name"],
                        "fact_type": "symptom" if q["target_type"] == "Symptom" else "lifestyle", "presence": payload.answer,
                        "timeframe": "current", "experiencer": "patient", "details": "",
                        "kg_entity_id": q["target_entity_id"], "confirmation_status": "user_confirmed",
                        "confirmed_at": iso_now(), "source_id": source_id, "origin": "followup"})
                user = self._message(state, "user", q["question_text"] + "\nTrả lời: " + {"present":"Có", "absent":"Không", "unknown":"Không biết", "skip":"Bỏ qua"}[payload.answer])
                user["id"] = source_id
                messages.append(user)
                await self._question(state)
            elif payload.action == "finish_questions" and state["status"] == "questioning":
                state.update(status="ready", question_proposal=None)
                messages.append(self._message(state, "user", "Tôi muốn kết thúc phần hỏi bổ sung và xem lại dữ kiện."))
            elif payload.action == "diagnose" and state["status"] in {"ready", "failed"}:
                if not payload.reviewed:
                    raise HTTPException(422, "Cần xác nhận bản dữ kiện cuối cùng trước khi gửi chẩn đoán.")
                self._check_conflicts(state["facts"])
                # Freeze once. Retry cannot substitute facts after a downstream failure.
                if state["snapshot"] is None:
                    state["snapshot"] = {"id": str(uuid4()), "created_at": iso_now(), "patient_id": state["patient_id"],
                                         "facts": copy.deepcopy(state["facts"])}
                if not state.get("clinical_input"):
                    state["clinical_input"] = "Hỗ trợ đánh giá từ dữ kiện người dùng đã xác nhận dưới đây. Giữ nguyên phủ định, tiền sử, chủ thể và thông tin chưa biết. Không coi bệnh được nhắc tới là chẩn đoán xác định.\n" + self.facts_text(state["snapshot"]["facts"])
                state.update(status="running", error=None)
                messages.append(self._message(state, "user", "Tôi xác nhận gửi bản dữ kiện đã kiểm tra để đánh giá chẩn đoán."))
            else:
                raise HTTPException(409, "Thao tác không phù hợp với bước hiện tại.")
            state["version"] = version + 1
            state["action_ids"].append(payload.action_id)
            state["events"].append({"action": payload.action, "at": iso_now(), "version": state["version"]})
            logger.info("assessment.action id=%s action=%s status=%s version=%s", state["id"], payload.action, state["status"], state["version"])
            if payload.action in {"confirm", "confirm_history", "answer", "finish_questions"}:
                text = "Hãy kiểm tra riêng các dữ kiện Patient Graph; chỉ chọn thông tin còn áp dụng cho lần đánh giá này." if state["status"] == "confirming_history" else state["question_proposal"]["question_text"] if state["question_proposal"] else "Hãy xem lại bản dữ kiện và nhấn Gửi đánh giá khi đã kiểm tra xong."
                messages.append(self._message(state, "assistant", text))
            self.store.commit_assessment(state, expected_version=version, messages=messages)
            if self.context_container:
                for m in messages:
                    try:
                        await self.context_container.service.add_history_turn(patient_id=state["patient_id"],
                            session_id=state["conversation_id"], message_id=m["id"], role=Role(m["role"]),
                            text=m["content"], timestamp=datetime.fromisoformat(m["createdAt"]))
                    except Exception:
                        logger.warning("assessment.history_sync_failed id=%s", state["id"])
            return state

    @staticmethod
    def facts_text(facts):
        return "\n".join(f"- {f['display']}: { {'present':'CÓ', 'absent':'KHÔNG', 'unknown':'CHƯA BIẾT'}[f['presence']]}; "
                         f"{'hiện tại' if f['timeframe']=='current' else 'tiền sử'}; "
                         f"{'bệnh nhân' if f['experiencer']=='patient' else 'người thân'}"
                         + (f"; {f['details']}" if f.get('details') else '') for f in facts)

    async def _sync_graph(self, state):
        if not self.context_container:
            raise RuntimeError("Context unavailable")
        snapshot = state["snapshot"]
        source_id = "assessment:" + snapshot["id"]
        when = datetime.fromisoformat(snapshot["created_at"])
        text = "Dữ kiện do người dùng xác nhận, chưa phải kết luận chẩn đoán:\n" + self.facts_text(snapshot["facts"])
        await self.context_container.history_repository.add_turn(HistoryTurn(
            patient_id=state["patient_id"], session_id=state["conversation_id"], message_id=source_id,
            role=Role.USER, original_text=text, normalized_text=text, created_at=when,
            metadata={"assessment_id": state["id"], "snapshot_id": snapshot["id"], "user_confirmed": True}))
        facts = []
        for f in snapshot["facts"]:
            if f["presence"] == "unknown" or f.get("reconfirmed_only"):
                continue  # Unknown is not a negative assertion.
            facts.append(ClinicalFact(fact_type=f["fact_type"], display=f["display"],
                negated=f["presence"] == "absent", experiencer=f["experiencer"], certainty="unknown",
                status="historical" if f["timeframe"] == "history" else "user_reported",
                recorded_at=when, source_message_id=source_id, source_text=text,
                attributes={"confirmation_status": "user_confirmed", "confirmed_at": f["confirmed_at"],
                            "assessment_id": state["id"], "snapshot_id": snapshot["id"], "timeframe": f["timeframe"],
                            "details": clean_details(f["details"]), "canonical_display": f.get("canonical_display"),
                            "original_source_id": f.get("original_source_id"), "source_refs": f.get("source_refs", []), "clinically_verified": False}))
        await self.context_container.patient_repository.upsert_facts(patient_id=state["patient_id"], facts=facts)

    async def run(self, assessment_id):
        async with self.locks.setdefault(assessment_id, asyncio.Lock()):
            state = self.store.get_assessment(assessment_id)
            if not state or state["status"] != "running":
                return
            try:
                if state.get("graph_sync") != "synced":
                    try:
                        await self._sync_graph(state)
                        state["graph_sync"] = "synced"
                    except Exception as exc:
                        state["graph_sync"] = "failed"
                        state["warnings"].append("Đã lưu bản xác nhận trong backend nhưng chưa đồng bộ được Patient Graph.")
                        logger.warning("assessment.graph_failed id=%s error_type=%s", state["id"], type(exc).__name__)
                text = state["clinical_input"]
                if not state.get("clinical_result"):
                    state["clinical_result"] = await self.modules.clinical_query(text)
                    # Cache Clinical IE before calling LLM so LLM retries do not repeat it.
                    version = state["version"]
                    state["version"] += 1
                    self.store.commit_assessment(state, expected_version=version)
                pack = prepare_evidence({"route": "DIAGNOSTIC_ASSESSMENT", "confirmed_snapshot": state["snapshot"], "module_results": {"clinical_ie": state["clinical_result"]}})
                answer = await self.llm.generate(
                    "Trình bày bằng tiếng Việt kết quả hỗ trợ đánh giá chẩn đoán từ bản dữ kiện đã xác nhận và Clinical IE. Phân biệt dữ kiện người dùng với giả thuyết của mô hình. Không biến giả thuyết thành chẩn đoán xác định, không thêm triệu chứng chưa khai, giữ nguyên KHÔNG/CHƯA BIẾT/tiền sử/người thân. Nếu chưa đủ dữ kiện, nói rõ.",
                    pack.payload)
                if not answer.strip():
                    raise ValueError("Empty LLM answer")
                state.update(status="completed", error=None)
                message = self._message(state, "assistant", validate_answer(answer, pack.sources))
                message["metadata"]["sources"] = pack.sources
                message["metadata"]["snapshot_id"] = state["snapshot"]["id"]
                messages = [message]
            except Exception as exc:
                logger.error("assessment.failed id=%s error_type=%s", state["id"], type(exc).__name__)
                state.update(status="failed", error="Dịch vụ xử lý chưa trả kết quả. Kiểm tra Clinical IE/Ollama rồi thử lại với bản dữ kiện đã xác nhận.")
                messages = []
            version = state["version"]
            state["version"] += 1
            self.store.commit_assessment(state, expected_version=version, messages=messages)
            for m in messages:
                try:
                    await self.modules.append_assistant_turn(conversation_id=state["conversation_id"], message_id=m["id"], text=m["content"], timestamp=m["createdAt"])
                except Exception:
                    logger.warning("assessment.history_sync_failed id=%s", state["id"])
