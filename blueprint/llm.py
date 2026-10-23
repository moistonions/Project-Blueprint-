"""Thin wrapper around the OpenAI SDK so the rest of the code (and tests) don't depend on it."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from blueprint.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T: ...

    def complete(self, *, model: str, system: str, user: str) -> str: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIClient:
    """Implements both LLM and Embedder using the OpenAI Responses + Embeddings APIs."""

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)
        self._embedding_model = settings.embedding_model

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        resp = self._client.responses.parse(
            model=model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            text_format=schema,
        )
        if resp.output_parsed is None:
            raise RuntimeError("Model returned no parseable output (possibly a refusal).")
        return resp.output_parsed

    def complete(self, *, model: str, system: str, user: str) -> str:
        resp = self._client.responses.create(
            model=model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.output_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 128):
            resp = self._client.embeddings.create(model=self._embedding_model, input=texts[i : i + 128])
            out.extend(d.embedding for d in resp.data)
        return out
