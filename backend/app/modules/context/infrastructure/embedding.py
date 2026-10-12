from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class EmbeddingService(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed(self, text: str) -> list[float]: ...


class HashEmbeddingService:
    """Deterministic offline embedding for local development and tests.

    This is intentionally simple. It preserves the vector-retrieval code path without
    requiring a model endpoint. Production should use a semantic embedding model.
    """

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 32:
            raise ValueError("dimensions must be >= 32")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
        if not tokens:
            vector[0] = 1.0
            return vector

        # Include unigrams and bigrams so short Vietnamese questions retain some context.
        features = list(tokens)
        features.extend(f"{a}::{b}" for a, b in zip(tokens, tokens[1:]))
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class OpenAIEmbeddingService:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        return list(response.data[0].embedding)


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
