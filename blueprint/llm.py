"""Thin LLM and embedding wrappers so the rest of the code (and tests) don't depend on a provider SDK."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from blueprint.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T: ...

    def complete(self, *, model: str, system: str, user: str) -> str: ...


class Embedder(Protocol):
    name: str  # identifies the vector space; stores keep one collection per embedder

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class AnthropicClient:
    """Claude via the Messages API, with structured outputs for extraction."""

    # On a safety-classifier refusal the API re-runs the request on a fallback model.
    _BETAS = ["server-side-fallback-2026-07-01"]

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @staticmethod
    def _check(resp) -> None:
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the request ({resp.stop_details}).")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Claude's reply hit max_tokens; try a smaller document section.")

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        # Streamed so a long task list from a big manual doesn't hit the HTTP timeout.
        with self._client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            betas=self._BETAS,
            fallbacks="default",
        ) as stream:
            resp = stream.get_final_message()
        self._check(resp)
        if resp.parsed_output is None:
            raise RuntimeError("Claude returned no parseable output.")
        return resp.parsed_output

    def complete(self, *, model: str, system: str, user: str) -> str:
        resp = self._client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            betas=self._BETAS,
            fallbacks="default",
        )
        self._check(resp)
        return "".join(b.text for b in resp.content if b.type == "text")


class OpenAIClient:
    """OpenAI Responses + Embeddings APIs (optional alternative to Claude)."""

    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)
        self._embedding_model = settings.embedding_model
        self.name = f"openai-{settings.embedding_model}"

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


class LocalEmbedder:
    """Small on-device embedding model (all-MiniLM-L6-v2 via Chroma's ONNX runtime).

    No API key; the ~80 MB model downloads once on first use.
    """

    name = "local-minilm"

    def __init__(self):
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._fn = DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._fn(texts)]


def make_llm(settings: Settings) -> LLM:
    return AnthropicClient(settings) if settings.llm_provider == "anthropic" else OpenAIClient(settings)


def make_embedder(settings: Settings, llm: LLM) -> Embedder:
    if settings.embeddings == "local":
        return LocalEmbedder()
    if settings.embeddings == "openai":
        return llm if isinstance(llm, OpenAIClient) else OpenAIClient(settings)
    raise ValueError("BLUEPRINT_EMBEDDINGS must be 'local' or 'openai'")
