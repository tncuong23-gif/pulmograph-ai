from fastapi.testclient import TestClient

from app.modules.context.config import get_settings
from app.modules.context.main import app


def test_health_and_context_api(monkeypatch):
    monkeypatch.setenv("CONTEXT_GRAPH_BACKEND", "memory")
    monkeypatch.setenv("CONTEXT_NLP_BACKEND", "rule")
    get_settings.cache_clear()

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        response = client.post(
            "/v1/context/resolve",
            json={
                "patient_id": "p1",
                "session_id": "s1",
                "message_id": "m1",
                "question": "Tôi bị tăng huyết áp.",
                "timestamp": "2026-09-26T03:00:00+07:00",
            },
        )
        assert response.status_code == 200
        assert response.json()["patient_graph_updated"] is False
        assert response.json()["draft_facts"]
        assert not client.get("/v1/patients/p1/context").json()["facts"]
        body = {"patient_id": "p1", "session_id": "s1", "message_id": "m2", "question": "Tôi ho", "timestamp": "2026-09-26T03:00:00+07:00", "persist_patient_facts": True}
        assert client.post("/v1/context/resolve", json=body).status_code == 422
