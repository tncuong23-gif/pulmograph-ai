"""State, confirmation, integration and failure tests; upstream inference is mocked."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services.assessment import AssessmentAction, AssessmentService
from app.storage import ConversationStore
from app.schemas import iso_now


def choice(name="ho", **kw):
    return dict(display=name, fact_type="symptom", presence="present", timeframe="current", details="", experiencer="patient", **kw)


def action(state, name, **kw):
    return AssessmentAction(action_id=str(uuid4()), version=state["version"], action=name, **kw)


def proposal(properties=None):
    return {"question_id": "q-fever", "target_entity_id": "fever", "target_name": "sốt", "target_type": "Symptom",
            "question_text": "Bạn có sốt không?", "requires_review": True,
            "basis": [{"evidence": [{"doc_id": "test-doc", "evidence_id": "test-e", "text": "Nguồn giả lập cho kiểm thử."}],
                       "assertions": [{"properties_valid": True, "properties": properties or {}}]}]}


@pytest.fixture
def setup(tmp_path):
    modules = SimpleNamespace(kg_url="http://kg", _post=AsyncMock(), clinical_query=AsyncMock(return_value={"ok": True, "data": {"test": True}}), append_assistant_turn=AsyncMock())
    async def post(base, path, body):
        if path.endswith("/map"):
            return {"items": [{"mention": n, "status": "resolved", "kg_entity_id": n} for n in body["mentions"]]}
        return {"status": "proposals", "questions": [proposal()]}
    modules._post.side_effect = post
    llm = SimpleNamespace(generate=AsyncMock(return_value="Kết quả kiểm thử."))
    container = SimpleNamespace(history_repository=SimpleNamespace(add_turn=AsyncMock()),
                                patient_repository=SimpleNamespace(upsert_facts=AsyncMock()),
                                service=SimpleNamespace(add_history_turn=AsyncMock()))
    store = ConversationStore(tmp_path / "db.sqlite")
    service = AssessmentService(store, modules, llm, container)
    state = service.start("conversation-A", "message-A", "Tôi ho, hãy đánh giá", {})
    return service, state, modules, llm, container


@pytest.mark.asyncio
async def test_requires_confirmation_before_clinical_and_graph(setup):
    svc, state, modules, llm, container = setup
    for name in ("diagnose", "answer", "finish_questions"):
        with pytest.raises(HTTPException):
            await svc.action(state["id"], action(state, name, reviewed=True))
    with pytest.raises(HTTPException):
        await svc.action(state["id"], action(state, "confirm", facts=[choice()]))
    modules.clinical_query.assert_not_awaited()
    container.patient_repository.upsert_facts.assert_not_awaited()
    state = await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=[choice()]))
    assert state["status"] == "questioning"
    assert svc.store.get_conversation("conversation-A")["assessment"]["id"] == state["id"]
    modules.clinical_query.assert_not_awaited()
    container.patient_repository.upsert_facts.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["unknown", "skip", "absent"])
async def test_followup_presence_snapshot_and_no_invented_graph_fact(setup, response):
    svc, state, modules, llm, container = setup
    state = await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=[choice()]))
    state = await svc.action(state["id"], action(state, "answer", question_id="q-fever", answer=response, reviewed=True))
    assert state["status"] == "ready"  # Same KG entity is never asked twice.
    assert state["asked_entity_ids"] == ["fever"]
    with pytest.raises(HTTPException):
        await svc.action(state["id"], action(state, "diagnose"))
    state = await svc.action(state["id"], action(state, "diagnose", reviewed=True))
    assert state["status"] == "running"
    await asyncio.gather(svc.run(state["id"]), svc.run(state["id"]))
    final = svc.store.get_assessment(state["id"])
    assert final["status"] == "completed"
    assert final["snapshot"]["facts"] == state["snapshot"]["facts"]
    modules.clinical_query.assert_awaited_once()
    graph_facts = container.patient_repository.upsert_facts.call_args.kwargs["facts"]
    if response in ("unknown", "skip"):
        assert [f.display for f in graph_facts] == ["ho"]
    else:
        assert next(f for f in graph_facts if f.display == "sốt").negated is True
    sent_text = modules.clinical_query.call_args.args[0]
    if response == "unknown":
        assert "sốt: CHƯA BIẾT" in sent_text
    if response == "skip":
        assert "sốt" not in sent_text
    assert len([m for m in svc.store.get_conversation("conversation-A")["messages"] if m["content"] == "Kết quả kiểm thử."]) == 1


@pytest.mark.asyncio
async def test_idempotency_stale_versions_and_conflict(setup):
    svc, state, modules, llm, container = setup
    payload = action(state, "confirm", same_patient=True, facts=[choice()])
    confirmed = await svc.action(state["id"], payload)
    assert await svc.action(state["id"], payload) == confirmed
    with pytest.raises(HTTPException) as err:
        await svc.action(state["id"], action(state, "cancel"))
    assert err.value.status_code == 409
    other = svc.start("another-conversation", "m", "q", {})
    yes = choice()
    no = {**yes, "presence": "absent"}
    with pytest.raises(HTTPException):
        await svc.action(other["id"], action(other, "confirm", same_patient=True, facts=[yes, no]))
    assert svc.store.get_assessment(other["id"])["status"] == "confirming"


@pytest.mark.asyncio
async def test_kg_outage_family_history_and_llm_retry(setup):
    svc, state, modules, llm, container = setup
    modules._post.side_effect = RuntimeError("offline")
    facts = [choice(), {**choice("bệnh cũ"), "timeframe": "history", "experiencer": "family", "details": "mẹ; năm 2020"}]
    state = await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=facts))
    assert state["status"] == "ready" and state["warnings"]
    state = await svc.action(state["id"], action(state, "diagnose", reviewed=True))
    llm.generate.side_effect = RuntimeError("offline")
    await svc.run(state["id"])
    failed = svc.store.get_assessment(state["id"])
    assert failed["status"] == "failed" and failed["clinical_result"]
    llm.generate.side_effect = None
    retry = await svc.action(state["id"], action(failed, "diagnose", reviewed=True))
    await svc.run(state["id"])
    modules.clinical_query.assert_awaited_once()
    assert "tiền sử; người thân; mẹ; năm 2020" in modules.clinical_query.call_args.args[0]
    assert svc.store.get_assessment(state["id"])["snapshot"] == retry["snapshot"]


@pytest.mark.asyncio
async def test_restart_and_cancel(setup):
    svc, state, modules, llm, container = setup
    modules._post.side_effect = RuntimeError("offline")
    state = await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=[choice()]))
    state = await svc.action(state["id"], action(state, "diagnose", reviewed=True))
    reopened = ConversationStore(svc.store.path)
    reopened.recover_assessments()
    recovered = reopened.get_assessment(state["id"])
    assert recovered["status"] == "failed" and recovered["snapshot"] == state["snapshot"]
    state = await svc.action(state["id"], action(recovered, "cancel"))
    await svc.run(state["id"])
    modules.clinical_query.assert_not_awaited()
    assert state["status"] == "cancelled"


@pytest.mark.asyncio
async def test_conditional_kg_proposal_is_not_automatically_shown(setup):
    svc, state, modules, llm, container = setup
    original = modules._post.side_effect
    async def post(base, path, body):
        if path.endswith("/followups"):
            return {"status": "proposals", "questions": [proposal({"population": "special group"})]}
        return await original(base, path, body)
    modules._post.side_effect = post
    state = await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=[choice()]))
    assert state["status"] == "ready" and state["question_proposal"] is None


def test_api_diagnostic_route_stops_and_reload_restores_state():
    from app import main
    with TestClient(main.app) as client:
        classifier = Mock()
        classifier.predict.return_value = {"label": "DIAGNOSTIC_ASSESSMENT", "class_id": "0"}
        main.app.state.orchestrator.classifier = classifier
        main.app.state.modules.clinical_query = AsyncMock(return_value={"ok": True, "data": {"test": True}})
        main.app.state.llm.generate = AsyncMock(return_value="Kết quả thử API.")
        main.app.state.modules._post = AsyncMock(side_effect=RuntimeError("KG disabled in test"))
        # Use actual embedded context independently of fake KG transport.
        main.app.state.orchestrator.modules.context_resolve = AsyncMock(return_value={"normalized_question": "Tôi ho", "resolution_status": "not_needed", "draft_facts": [], "patient_facts": []})
        cid = str(uuid4())
        payload = {"conversationId": cid, "message": {"id": str(uuid4()), "role": "user", "content": "Tôi ho", "createdAt": iso_now()}}
        response = client.post("/api/v1/chat/message", json=payload)
        assert response.status_code == 200, response.text
        state = response.json()["assessment"]
        assert state["status"] == "confirming"
        main.app.state.modules.clinical_query.assert_not_awaited()
        repeat = client.post("/api/v1/chat/message", json=payload)
        assert repeat.json()["assessment"]["id"] == state["id"]
        assert classifier.predict.call_count == 1
        payload["message"]["id"] = str(uuid4())
        assert client.post("/api/v1/chat/message", json=payload).status_code == 409
        confirm = action(state, "confirm", same_patient=True, facts=[choice()])
        response = client.post(f"/api/v1/assessments/{state['id']}/actions", json=confirm.model_dump())
        assert response.status_code == 200, response.text
        state = response.json()["assessment"]
        assert state["status"] == "ready"
        response = client.post(f"/api/v1/assessments/{state['id']}/actions", json=action(state, "diagnose", reviewed=True).model_dump())
        assert response.status_code == 200
        restored = client.get(f"/api/v1/conversations/{cid}").json()
        assert restored["assessment"]["status"] == "completed"
        assert restored["messages"][-1]["content"] == "Kết quả thử API."
        main.app.state.modules.clinical_query.assert_awaited_once()
        assert classifier.predict.call_count == 1

@pytest.mark.asyncio
async def test_graph_failure_can_retry_without_repeating_diagnosis(setup):
    svc, state, modules, llm, container = setup
    modules._post.side_effect = RuntimeError("KG offline")
    container.patient_repository.upsert_facts.side_effect = RuntimeError("Neo4j offline")
    state = await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=[choice()]))
    state = await svc.action(state["id"], action(state, "diagnose", reviewed=True))
    await svc.run(state["id"])
    state = svc.store.get_assessment(state["id"])
    assert state["status"] == "completed" and state["graph_sync"] == "failed"
    container.patient_repository.upsert_facts.side_effect = None
    state = await svc.action(state["id"], action(state, "retry_graph_sync"))
    assert state["status"] == "completed" and state["graph_sync"] == "synced"
    modules.clinical_query.assert_awaited_once()
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_stored_patient_facts_are_drafts_only_and_forged_fact_ids_rejected(setup):
    svc, _, modules, llm, container = setup
    old = {"display": "bệnh cũ", "fact_type": "condition", "source_message_id": "old-source", "recorded_at": iso_now(), "negated": False}
    state = svc.start("other-patient", "new-message", "Câu hỏi mới", {"patient_facts": [old]})
    assert state["facts"] == [] and state["drafts"] == [] and state["history_drafts"][0]["origin"] == "patient_graph"
    with pytest.raises(HTTPException):
        await svc.action(state["id"], action(state, "confirm", same_patient=True, facts=[{**choice(), "id": "forged"}]))
    modules.clinical_query.assert_not_awaited()
    container.patient_repository.upsert_facts.assert_not_awaited()
