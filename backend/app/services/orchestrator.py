from __future__ import annotations

import asyncio
import json
import logging
import time
import os
import httpx
from typing import Any
from uuid import uuid4

from .evidence import prepare_evidence, validate_answer, has_evidence, insufficient_answer
from .retrieval_quality import select_kg_evidence
from .classifier import E5SVMClassifier
from .modules import ModuleClient
from .ollama import OllamaClient
from .kg_chat import query_metadata, comparison_metadata, no_facts_text
from app.modules.kg_query.question_analysis import uses_context, comparison_mode, COMPARISON_MODES


OUT_OF_SCOPE_TEXT = "Xin lỗi, câu hỏi này nằm ngoài phạm vi trợ lý thông tin bệnh phổi hiện tại."
logger = logging.getLogger("uvicorn.error")

CLARIFICATION_TEXT = "Bạn đang hỏi về bệnh hoặc chủ thể nào? Tôi chưa xác định chắc chủ thể từ ngữ cảnh hội thoại."


class Orchestrator:
    def __init__(self, classifier: E5SVMClassifier, modules: ModuleClient, llm: OllamaClient) -> None:
        self.classifier = classifier
        self.modules = modules
        self.llm = llm

    async def answer(self, *, conversation_id: str, message_id: str, question: str, timestamp: str, attachments: list[dict[str, Any]], voice: bool = False, on_sentence=None, kg_confirmation=None) -> dict[str, Any]:
        request_id = str(uuid4())
        started = time.monotonic()
        context_result = await self.modules.context_resolve(
            conversation_id=conversation_id,
            message_id=message_id,
            question=kg_confirmation['question'] if kg_confirmation else question,
            timestamp=timestamp,
        )
        logger.info("chat.stage stage=context elapsed=%.1fs", time.monotonic()-started)
        resolved_question = (kg_confirmation['question'] if kg_confirmation else
                             str(context_result.get("normalized_question") or question).strip())
        logger.info("context.resolve message_id=%s status=%s stored_facts=%s history_turns=%s",
                    message_id, context_result.get("resolution_status"), context_result.get("stored_fact_count"),
                    context_result.get("context_turn_ids"))
        if os.getenv("TRACE_PIPELINE", "false").lower() == "true":
            logger.info("context.text message_id=%s original=%r normalized=%r", message_id, question, resolved_question)
        if context_result.get("resolution_status") == "unresolved" and not kg_confirmation:
            return {"content": CLARIFICATION_TEXT, "route": "NEEDS_CLARIFICATION", "request_id": request_id, "sources": []}

        from starlette.concurrency import run_in_threadpool
        classification = (kg_confirmation['classification'] if kg_confirmation else
                          await run_in_threadpool(self.classifier.predict, resolved_question))
        label = classification["label"]
        # Preserve the model prediction for audit. Comparison words select a KG
        # operation, while KG itself still validates both names and the criterion.
        # Diagnostic and out-of-scope routes retain their existing gates.
        if (not kg_confirmation and label == 'GENERAL_MEDICAL_QUERY'
                and comparison_mode(question)):
            classification = {**classification, 'original_label': label,
                              'label': 'RELATIONAL_QUERY', 'routing_override': 'kg_comparison_cue'}
            label = 'RELATIONAL_QUERY'
        logger.info("chat.stage stage=classification route=%s elapsed=%.1fs", label, time.monotonic()-started)
        if label == "OUT_OF_SCOPE":
            return {"content": OUT_OF_SCOPE_TEXT, "route": label, "request_id": request_id, "sources": []}

        if label in ('RELATIONAL_QUERY', 'CLINICAL_EXPLANATION_MANAGEMENT') and not uses_context(question) and not kg_confirmation:
            # Explicit names in the current question outrank a stale active topic.
            resolved_question = question.strip()

        active_topic = context_result.get("active_topic") or {}
        mentions = []
        if isinstance(active_topic, dict) and active_topic.get("canonical_name"):
            mentions.append(str(active_topic["canonical_name"]))
        if not mentions:
            for candidate in context_result.get("candidate_entities") or []:
                if isinstance(candidate, dict) and candidate.get("canonical_name"):
                    mentions.append(str(candidate["canonical_name"]))
                    break

        module_results: dict[str, Any] = {}
        kg_args = {'entity_ids': kg_confirmation['entity_ids']} if kg_confirmation else {}
        warnings: list[str] = []
        record_attachments = [a for a in attachments if a.get("type") == "medical_record"]

        # Use only server-stored analyses. Never trust client-supplied analysis fields.
        for index, attachment in enumerate(record_attachments):
            lookup = getattr(self, "attachment_lookup", None)
            file_id = attachment.get("serverId") or attachment.get("id")
            record = lookup(str(file_id)) if lookup else None
            if record and record.get("status") == "processed" and record.get("analysis_json"):
                module_results[f"clinical_file_{index}"] = json.loads(record["analysis_json"])
            else:
                warnings.append("Bệnh án chưa xử lý thành công; vui lòng chờ hoặc tải lại tệp.")

        if label == "DIAGNOSTIC_ASSESSMENT":
            return {"content": "Vui lòng kiểm tra dữ kiện bên dưới và xác nhận trước khi đánh giá chẩn đoán.",
                    "route": label, "request_id": request_id, "sources": [],
                    "classifier": classification, "resolved_question": resolved_question,
                    "context_resolution": context_result}
        elif label == "GENERAL_MEDICAL_QUERY":
            try:
                module_results["rag"] = await self.modules.rag_search(resolved_question)
            except Exception:
                warnings.append("Medical RAG không phản hồi thành công.")
        elif label == "RELATIONAL_QUERY":
            try:
                module_results["kg"] = await self.modules.kg_query(resolved_question, mentions or None, **kg_args)
            except Exception:
                warnings.append("KG retrieval không phản hồi thành công.")
        elif label == "CLINICAL_EXPLANATION_MANAGEMENT":
            results = await asyncio.gather(
                self.modules.rag_search(resolved_question),
                self.modules.kg_query(resolved_question, mentions or None, **kg_args),
                return_exceptions=True,
            )
            for name, result in zip(("rag", "kg"), results):
                if isinstance(result, Exception):
                    if isinstance(result, httpx.TimeoutException):
                        warnings.append(f"Module {name} vượt thời gian chờ xử lý.")
                    elif isinstance(result, httpx.HTTPStatusError):
                        warnings.append(f"Module {name} trả HTTP {result.response.status_code}.")
                    else:
                        warnings.append(f"Module {name} không phản hồi thành công.")
                    logger.error("chat.module_failed module=%s error_type=%s", name, type(result).__name__)
                else:
                    module_results[name] = result
        else:
            raise RuntimeError(f"Unsupported classifier label: {label}")

        logger.info("chat.stage stage=retrieval elapsed=%.1fs", time.monotonic()-started)
        kg = module_results.get('kg')
        kg_info = query_metadata(kg) if isinstance(kg, dict) else None
        kg_comparison = comparison_metadata(kg) if isinstance(kg, dict) else None
        if kg_info:
            logger.info('kg.query mode=%s preset=%s status=%s facts=%s elapsed_ms=%s',
                        kg_info.get('mode'), kg_info.get('preset'), kg_info.get('status'),
                        kg_info.get('fact_count'), kg_info.get('elapsed_ms'))
        if (isinstance(kg, dict) and kg.get('status') == 'needs_clarification'
                and (kg_confirmation or (kg.get('clarification') or {}).get('reason') not in ('duplicate_entities', 'missing_entity', 'dictionary_limit'))):
            clarification = kg.get('clarification') or {'message': CLARIFICATION_TEXT}
            return {'content': clarification['message'], 'route': 'NEEDS_CLARIFICATION',
                    'kg_route': label, 'request_id': request_id, 'sources': [], 'kg_query': kg_info,
                    'kg_clarification': clarification, 'classifier': classification,
                    'resolved_question': resolved_question}
        rag_attempted = label in ('GENERAL_MEDICAL_QUERY', 'CLINICAL_EXPLANATION_MANAGEMENT')
        initial_route = label
        routing = {'classified_route': initial_route, 'kg_evidence': 'not_requested', 'reasons': []}
        if label in ('RELATIONAL_QUERY', 'CLINICAL_EXPLANATION_MANAGEMENT'):
            try:
                selected, quality, reasons = select_kg_evidence(kg)
            except (TypeError, AttributeError, ValueError, KeyError):
                selected, quality, reasons = None, 'empty', ['invalid_kg_response']
            routing.update(kg_evidence=quality, reasons=reasons)
            if selected is None:
                module_results.pop('kg', None)
                kg_comparison = None
            else:
                module_results['kg'] = selected
                kg_comparison = comparison_metadata(selected)
            if quality != 'sufficient':
                warnings.append('KG chưa có bằng chứng sử dụng được; chuyển sang tìm tài liệu RAG.' if quality == 'empty'
                                else 'Bằng chứng KG chưa đầy đủ theo cấu trúc truy vấn; bổ sung tài liệu RAG.')
                if not rag_attempted:
                    rag_attempted = True
                    try:
                        module_results['rag'] = await self.modules.rag_search(resolved_question)
                    except Exception as exc:
                        warnings.append('RAG dự phòng chưa phản hồi; chỉ sử dụng bằng chứng hợp lệ đã có.')
                        logger.warning('chat.fallback_failed error_type=%s', type(exc).__name__)
                label = 'GENERAL_MEDICAL_QUERY' if quality == 'empty' else 'CLINICAL_EXPLANATION_MANAGEMENT'
            elif initial_route == 'CLINICAL_EXPLANATION_MANAGEMENT':
                label = initial_route
        routing['effective_route'] = label

        for name, result in module_results.items():
            items = result.get("results", []) if isinstance(result, dict) else []
            logger.info("retrieval.result message_id=%s module=%s count=%s sources=%s", message_id, name, len(items),
                        [{"id": item.get("chunk_id") or item.get("proposition_id"), "document": item.get("document_id"), "score": item.get("score")} for item in items])
        llm_input = {
            "request_id": request_id,
            "route": label,
            "module_results": module_results,
            "warnings": warnings,
            "context_resolution": {
                "resolution_status": context_result.get("resolution_status"),
                "resolution_confidence": context_result.get("resolution_confidence"),
            },
        }
        pack = prepare_evidence(llm_input)
        # A group may be rejected by the final byte/reference filter. Try RAG once if not already attempted.
        if ('kg' in module_results and 'kg' not in pack.payload['module_results']
                and not rag_attempted):
            rag_attempted = True
            try:
                module_results['rag'] = await self.modules.rag_search(resolved_question)
            except Exception:
                warnings.append('RAG dự phòng chưa phản hồi sau khi lọc bằng chứng KG.')
            module_results.pop('kg', None)
            label = 'GENERAL_MEDICAL_QUERY'
            routing.update(effective_route=label, kg_evidence='empty', reasons=['kg_filtered_out'])
            llm_input.update(route=label, module_results=module_results, warnings=warnings)
            pack = prepare_evidence(llm_input)
        llm_input = pack.payload
        if not has_evidence(llm_input):
            return {'content': insufficient_answer(llm_input), 'route': label, 'request_id': request_id,
                    'sources': [], 'warnings': warnings, 'classifier': classification,
                    'resolved_question': resolved_question, 'retrieval_routing': routing, 'kg_query': kg_info}
        if 'kg' not in pack.payload['module_results']:kg_comparison=None
        warnings.extend(w for w in pack.payload['warnings'] if w not in warnings)
        speech = {}
        if voice:
            speech = await self.llm.generate_voice(resolved_question, llm_input, on_sentence)
            answer = speech.pop('content')
        else:
            answer = await self.llm.generate(resolved_question, llm_input)
        logger.info("chat.stage stage=llm elapsed=%.1fs", time.monotonic()-started)
        answer = validate_answer(answer, pack.sources)
        sources = pack.sources
        if warnings:
            answer += "\n\nLưu ý: " + " ".join(warnings)
            if voice:
                warning = 'Lưu ý: ' + ' '.join(warnings)
                speech['speech_chunks'].append(warning)
                speech['spoken_text'] += ' ' + warning
                if on_sentence:
                    await on_sentence(warning)
        return {
            "content": answer,
            "route": label,
            "request_id": request_id,
            "sources": sources,
            "warnings": warnings,
            "classifier": classification,
            "retrieval_routing": routing,
            "resolved_question": resolved_question,
            "context_resolution": context_result,
            "kg_query": kg_info,
            "kg_comparison": kg_comparison,
            "kg_confirmation_used": bool(kg_confirmation),
            **speech,
        }

    @staticmethod
    def _sources(results: dict[str, Any]) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for result in results.values():
            if not isinstance(result, dict):
                continue
            llm_context = result.get("llm_context")
            if isinstance(llm_context, dict):
                for source in llm_context.get("sources", []):
                    if isinstance(source, dict):
                        key = f"{source.get('doc_id')}:{source.get('evidence_id')}"
                        found[key] = source
            for item in result.get("results", []):
                if isinstance(item, dict):
                    key = str(item.get("chunk_id") or item.get("proposition_id") or item.get("document_id") or len(found))
                    found[key] = item
        return list(found.values())
