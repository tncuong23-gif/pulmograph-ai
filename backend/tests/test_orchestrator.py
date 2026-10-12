import unittest

from app.services.orchestrator import Orchestrator


class FakeClassifier:
    def __init__(self, label):
        self.label = label

    def predict(self, text):
        return {"label": self.label, "class_id": "4", "decision_margin": 0.5}


class FakeModules:
    def __init__(self):
        self.calls = []

    async def context_resolve(self, **kwargs):
        self.calls.append("context")
        return {
            "normalized_question": "COPD có triệu chứng gì?",
            "resolution_status": "resolved",
            "active_topic": {"canonical_name": "COPD"},
        }

    async def rag_search(self, question):
        self.calls.append("rag")
        return {"results": [{"chunk_id": "c1", "text": "Nguồn kiểm thử."}]}

    async def kg_query(self, question, mentions=None):
        self.calls.append("kg")
        self.mentions = mentions
        return {"status": "ok", "llm_context": {"facts": [], "sources": []}}


class FakeLLM:
    async def generate(self, question, context):
        return "Câu trả lời mẫu."


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_combined_route_queries_rag_and_kg(self):
        modules = FakeModules()
        orchestrator = Orchestrator(FakeClassifier("CLINICAL_EXPLANATION_MANAGEMENT"), modules, FakeLLM())
        result = await orchestrator.answer(
            conversation_id="conv-1", message_id="msg-1", question="Nó có triệu chứng gì?",
            timestamp="2026-09-27T06:00:00Z", attachments=[],
        )
        self.assertEqual(set(modules.calls), {"context", "rag", "kg"})
        self.assertEqual(modules.mentions, ["COPD"])
        self.assertTrue(result["content"].startswith("Câu trả lời mẫu."))

    async def test_out_of_scope_does_not_call_knowledge_modules_or_llm(self):
        modules = FakeModules()
        orchestrator = Orchestrator(FakeClassifier("OUT_OF_SCOPE"), modules, FakeLLM())
        result = await orchestrator.answer(
            conversation_id="conv-1", message_id="msg-2", question="Hỏi ngoài lĩnh vực",
            timestamp="2026-09-27T06:00:00Z", attachments=[],
        )
        self.assertEqual(modules.calls, ["context"])
        self.assertEqual(result["route"], "OUT_OF_SCOPE")


if __name__ == "__main__":
    unittest.main()
