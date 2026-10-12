from __future__ import annotations

from typing import Any
import asyncio

import httpx


class ModuleClient:
    def __init__(self, *, context_url: str, clinical_url: str, kg_url: str, rag_url: str, timeout: float, clinical_timeout: float = 240.0, embedded_apps: dict | None = None) -> None:
        self.context_url = context_url
        self.clinical_url = clinical_url
        self.kg_url = kg_url
        self.rag_url = rag_url
        self.timeout = timeout
        self.clinical_timeout = clinical_timeout
        self.embedded_apps = embedded_apps or {}

    def _client(self, url: str, timeout: float):
        kwargs = {"timeout": httpx.Timeout(timeout, connect=10.0)}
        if url in self.embedded_apps:
            kwargs["transport"] = httpx.ASGITransport(app=self.embedded_apps[url], raise_app_exceptions=False)
        return httpx.AsyncClient(**kwargs)

    async def _post(self, url: str, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        async with self._client(url, timeout if timeout is not None else self.timeout) as client:
            response = await asyncio.wait_for(client.post(f"{url}{path}", json=payload), timeout=timeout or self.timeout)
            response.raise_for_status()
            return response.json()

    async def context_resolve(self, *, conversation_id: str, message_id: str, question: str, timestamp: str) -> dict[str, Any]:
        return await self._post(
            self.context_url,
            "/v1/context/resolve",
            {
                # Conversation-scoped identity prevents facts from unrelated chats being merged.
                "patient_id": conversation_id,
                "session_id": conversation_id,
                "message_id": message_id,
                "question": question,
                "persist_patient_facts": False,
                "timestamp": timestamp,
            },
        )

    async def append_assistant_turn(self, *, conversation_id: str, message_id: str, text: str, timestamp: str) -> None:
        payload = {
            "patient_id": conversation_id,
            "session_id": conversation_id,
            "message_id": message_id,
            "role": "assistant",
            "text": text,
            "timestamp": timestamp,
        }
        async with self._client(self.context_url, self.timeout) as client:
            response = await asyncio.wait_for(client.post(f"{self.context_url}/v1/history/turns", json=payload), timeout=self.timeout)
            response.raise_for_status()

    async def clinical_query(self, question: str) -> dict[str, Any]:
        result = await self._post(self.clinical_url, "/api/v1/ask-symptoms", {"text": question}, timeout=self.clinical_timeout)
        return self._validate_clinical(result)

    @staticmethod
    def _validate_clinical(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("data"), (dict, list)) or not result["data"] or (isinstance(result["data"], dict) and "raw_output_file" in result["data"]):
            raise ValueError("Clinical IE không trả kết quả JSON hợp lệ")
        return result

    async def clinical_analyze_file(self, filename: str, content: bytes, mime_type: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.clinical_timeout, connect=10.0)) as client:
            response = await client.post(
                f"{self.clinical_url}/api/v1/analyze-file",
                files={"file": (filename, content, mime_type)},
            )
            response.raise_for_status()
            return self._validate_clinical(response.json())

    async def clinical_analyze(self, *, text=None, image=None, same_case=False):
        data = {"same_case": "true" if same_case else "false"}
        if text is not None: data["text"] = text
        files = {"image": ("xray.png" if image.startswith(b"\x89PNG") else "xray.jpg", image,
                              "image/png" if image.startswith(b"\x89PNG") else "image/jpeg")} if image is not None else None
        async with self._client(self.clinical_url, self.clinical_timeout) as client:
            response = await client.post(f"{self.clinical_url}/api/v1/analyze", data=data, files=files)
            response.raise_for_status()
            return self._validate_clinical(response.json())

    async def kg_query(self, question: str, mentions: list[str] | None = None,
                       *, entity_ids: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question, "limit": 30, "include_evidence": True}
        if mentions:
            payload["context_mentions"] = mentions[:2]
        if entity_ids:
            payload['entity_ids'] = entity_ids
        return await self._post(self.kg_url, "/api/v1/kg/query", payload)

    async def rag_search(self, question: str) -> dict[str, Any]:
        return await self._post(
            self.rag_url,
            "/api/v1/rag/search",
            {"query": question, "kind": "all", "top_k": 5, "filters": {}},
        )

    async def health(self) -> dict[str, bool]:
        checks = {
            "context": (self.context_url, "/health"),
            "clinical_ie": (self.clinical_url, "/health"),
            "kg": (self.kg_url, "/health/ready"),
            "rag": (self.rag_url, "/api/v1/rag/health"),
        }
        async def check(base, path):
            try:
                async with self._client(base, 5.0) as client:
                    response = await asyncio.wait_for(client.get(f"{base}{path}"), timeout=6.0)
                    return response.is_success
            except Exception:
                return False
        values = await asyncio.gather(*(check(base, path) for base, path in checks.values()))
        return dict(zip(checks, values))
