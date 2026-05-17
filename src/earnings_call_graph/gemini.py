from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .config import load_dotenv

DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
ProgressCallback = Callable[[str], None]


GRAPH_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview_summary": {"type": "string"},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type": {
                        "type": "string",
                        "enum": [
                            "Company",
                            "Theme",
                            "Metric",
                            "Risk",
                            "BusinessSegment",
                            "Product",
                            "Geography",
                            "TimePeriod",
                            "BusinessTerm",
                        ],
                    },
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "entity_type", "confidence"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_entity": {"type": "string"},
                    "relation_type": {
                        "type": "string",
                        "enum": [
                            "DISCUSSES",
                            "DRIVES",
                            "INCREASES",
                            "REDUCES",
                            "PRESSURES",
                            "CONSTRAINS",
                            "SUPPORTS",
                            "OFFSETS",
                            "DEPENDS_ON",
                            "EXPOSED_TO",
                            "AFFECTS",
                            "GUIDES_TO",
                            "RISKS",
                        ],
                    },
                    "target_entity": {"type": "string"},
                    "scope_id": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "source_entity",
                    "relation_type",
                    "target_entity",
                    "scope_id",
                    "evidence_text",
                    "confidence",
                ],
            },
        },
    },
    "required": ["overview_summary", "entities", "relations"],
}

CHUNK_GRAPH_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "string"},
        "entities": GRAPH_EXTRACTION_SCHEMA["properties"]["entities"],
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_entity": {"type": "string"},
                    "relation_type": GRAPH_EXTRACTION_SCHEMA["properties"]["relations"]["items"]["properties"]["relation_type"],
                    "target_entity": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "source_entity",
                    "relation_type",
                    "target_entity",
                    "evidence_text",
                    "confidence",
                ],
            },
        },
        "quality_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["chunk_id", "entities", "relations"],
}

BATCH_CHUNK_GRAPH_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunks": {
            "type": "array",
            "items": CHUNK_GRAPH_EXTRACTION_SCHEMA,
        }
    },
    "required": ["chunks"],
}

DOCUMENT_ONTOLOGY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_summary": {"type": "string"},
        "entities": GRAPH_EXTRACTION_SCHEMA["properties"]["entities"],
        "themes": {"type": "array", "items": {"type": "string"}},
        "metrics": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "company_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["document_summary", "entities"],
}


class GeminiApiError(RuntimeError):
    """Raised when Gemini API request/response handling fails."""


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | float | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
    ):
        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.timeout = float(timeout) if timeout is not None else _float_from_env("GEMINI_TIMEOUT", 60.0)
        self.max_retries = max(0, int(max_retries)) if max_retries is not None else _int_from_env("GEMINI_MAX_RETRIES", 4)
        self.retry_delay = float(retry_delay) if retry_delay is not None else _float_from_env("GEMINI_RETRY_DELAY", 2.0)
        if not self.api_key:
            raise GeminiApiError("GEMINI_API_KEY is required. Add it to .env or the shell environment.")

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system_instruction: str | None = None,
        temperature: float = 0.1,
        progress_callback: ProgressCallback | None = None,
        operation: str = "Gemini request",
    ) -> dict[str, Any]:
        payload = build_structured_output_payload(prompt, schema, system_instruction, temperature)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            GEMINI_ENDPOINT.format(model=self.model),
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        for attempt in range(self.max_retries + 1):
            _progress(
                progress_callback,
                f"{operation}: attempt {attempt + 1}/{self.max_retries + 1} started "
                f"(timeout={self.timeout:g}s)",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                _progress(progress_callback, f"{operation}: response received")
                return parse_gemini_json_response(raw)
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                if exc.code not in RETRYABLE_HTTP_STATUS or attempt >= self.max_retries:
                    raise GeminiApiError(f"Gemini API HTTP {exc.code}: {details}") from exc
                delay = _retry_delay_seconds(self.retry_delay, attempt)
                _progress(
                    progress_callback,
                    f"{operation}: HTTP {exc.code}; retrying in {delay:g}s",
                )
                _sleep_before_retry(self.retry_delay, attempt)
            except urllib.error.URLError as exc:
                if attempt >= self.max_retries:
                    raise GeminiApiError(f"Gemini API connection failed: {exc}") from exc
                delay = _retry_delay_seconds(self.retry_delay, attempt)
                _progress(
                    progress_callback,
                    f"{operation}: connection error {exc}; retrying in {delay:g}s",
                )
                _sleep_before_retry(self.retry_delay, attempt)
            except (TimeoutError, socket.timeout) as exc:
                if attempt >= self.max_retries:
                    raise GeminiApiError(f"Gemini API timed out after {self.timeout:g}s") from exc
                delay = _retry_delay_seconds(self.retry_delay, attempt)
                _progress(
                    progress_callback,
                    f"{operation}: timed out after {self.timeout:g}s; retrying in {delay:g}s",
                )
                _sleep_before_retry(self.retry_delay, attempt)

        raise GeminiApiError("Gemini API retry loop exited unexpectedly.")

    def extract_graph(
        self,
        markdown_text: str,
        *,
        company_name: str,
        fiscal_quarter: str,
        allowed_themes: list[str],
        source_url: str,
        extraction_context: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        prompt = build_graph_extraction_prompt(
            markdown_text,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            allowed_themes=allowed_themes,
            source_url=source_url,
            extraction_context=extraction_context,
        )
        return self.generate_json(
            prompt,
            GRAPH_EXTRACTION_SCHEMA,
            system_instruction=GRAPH_EXTRACTION_SYSTEM,
            progress_callback=progress_callback,
            operation=f"Gemini full-document graph for {company_name} {fiscal_quarter}",
        )

    def extract_document_ontology(
        self,
        markdown_text: str,
        *,
        company_name: str,
        fiscal_quarter: str,
        source_url: str,
        seed_themes: list[str],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        prompt = build_document_ontology_prompt(
            markdown_text,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            source_url=source_url,
            seed_themes=seed_themes,
        )
        return self.generate_json(
            prompt,
            DOCUMENT_ONTOLOGY_SCHEMA,
            system_instruction=DOCUMENT_ONTOLOGY_SYSTEM,
            progress_callback=progress_callback,
            operation=f"Gemini document ontology for {company_name} {fiscal_quarter}",
        )

    def extract_chunk_graph(
        self,
        chunk_text: str,
        *,
        chunk_id: str,
        chunk_metadata: dict[str, Any],
        company_name: str,
        fiscal_quarter: str,
        allowed_themes: list[str],
        source_url: str,
        document_ontology: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        prompt = build_chunk_graph_extraction_prompt(
            chunk_text,
            chunk_id=chunk_id,
            chunk_metadata=chunk_metadata,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            allowed_themes=allowed_themes,
            source_url=source_url,
            document_ontology=document_ontology,
        )
        return self.generate_json(
            prompt,
            CHUNK_GRAPH_EXTRACTION_SCHEMA,
            system_instruction=CHUNK_GRAPH_EXTRACTION_SYSTEM,
            progress_callback=progress_callback,
            operation=f"Gemini chunk graph {chunk_id}",
        )

    def extract_chunk_graph_batch(
        self,
        chunks: list[dict[str, Any]],
        *,
        company_name: str,
        fiscal_quarter: str,
        allowed_themes: list[str],
        source_url: str,
        document_ontology: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        prompt = build_chunk_graph_batch_extraction_prompt(
            chunks,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            allowed_themes=allowed_themes,
            source_url=source_url,
            document_ontology=document_ontology,
        )
        result = self.generate_json(
            prompt,
            BATCH_CHUNK_GRAPH_EXTRACTION_SCHEMA,
            system_instruction=CHUNK_GRAPH_BATCH_EXTRACTION_SYSTEM,
            progress_callback=progress_callback,
            operation=f"Gemini chunk batch graph ({len(chunks)} chunks)",
        )
        batch = result.get("chunks")
        if not isinstance(batch, list):
            raise GeminiApiError("Gemini batch extraction returned no chunks array.")
        return [item for item in batch if isinstance(item, dict)]


def build_structured_output_payload(
    prompt: str,
    schema: dict[str, Any],
    system_instruction: str | None = None,
    temperature: float = 0.1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    return payload


def _sleep_before_retry(base_delay: float, attempt: int) -> None:
    time.sleep(_retry_delay_seconds(base_delay, attempt))


def _retry_delay_seconds(base_delay: float, attempt: int) -> float:
    return base_delay * (2 ** attempt)


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, value)


def _float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, value)


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def parse_gemini_json_response(raw_response: str) -> dict[str, Any]:
    envelope = json.loads(raw_response)
    try:
        parts = envelope["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiApiError(f"Unexpected Gemini response shape: {raw_response[:500]}") from exc
    if not text.strip():
        raise GeminiApiError("Gemini returned an empty structured-output body.")
    return json.loads(text)


GRAPH_EXTRACTION_SYSTEM = """
You extract a source-grounded business narrative graph from official earnings-call or investor-relations Markdown.
Treat the full document as source material for entity and relation extraction.
Prefer explicit source evidence over broad inference. Do not invent speakers, metrics, risks, or themes.
Evidence text must be a short paraphrase, not a long verbatim transcript quote.
Return concise, normalized entity names that can be reused as graph node names.
This is for analysis, not investment advice.
""".strip()


DOCUMENT_ONTOLOGY_SYSTEM = """
You discover a document-specific business ontology from an official earnings-call or investor-relations Markdown document.
Use the full document to identify canonical entity names, aliases, themes, metrics, risks, products, segments, and company-specific terms.
This ontology is only a vocabulary/canonicalization guide for later chunk-level extraction.
Do not extract relations here, and do not infer unsupported facts.
Prefer terms that are repeatedly or explicitly grounded in the document.
This is for analysis, not investment advice.
""".strip()


CHUNK_GRAPH_EXTRACTION_SYSTEM = """
You extract a source-grounded business narrative graph from exactly one Markdown paragraph chunk.
Use only the supplied chunk text and chunk metadata; do not infer facts from neighboring chunks or outside knowledge.
Return concise, normalized entity names that can be reused as graph node names.
Evidence text must be a short paraphrase, not a long verbatim transcript quote.
This is for analysis, not investment advice.
""".strip()


CHUNK_GRAPH_BATCH_EXTRACTION_SYSTEM = """
You extract source-grounded business narrative graphs from a batch of independent Markdown paragraph chunks.
Treat each chunk as an isolated extraction unit: do not use facts from one chunk to infer relations for another chunk.
Return one result object per input chunk, preserving each exact chunk_id.
Return concise, normalized entity names that can be reused as graph node names.
Evidence text must be a short paraphrase, not a long verbatim transcript quote.
This is for analysis, not investment advice.
""".strip()


def build_document_ontology_prompt(
    markdown_text: str,
    *,
    company_name: str,
    fiscal_quarter: str,
    source_url: str,
    seed_themes: list[str],
) -> str:
    themes = ", ".join(seed_themes)
    return f"""
Company: {company_name}
Fiscal quarter: {fiscal_quarter}
Source URL: {source_url}
Seed themes: {themes}

Task:
Read the full Markdown document and define a document-specific ontology for later paragraph-level graph extraction.

Rules:
- Include the company entity.
- Use seed themes only as hints; add document-specific themes, products, segments, metrics, risks, and business terms when clearly evidenced.
- Return canonical entity names plus aliases when the document uses multiple terms for the same concept.
- Do not extract relations in this step. Relations will be extracted only from individual paragraph chunks later.
- Do not include entities that are not grounded in the document.
- Keep names concise and reusable across companies/quarters where possible.

Markdown source:
---
{markdown_text}
---
""".strip()


def build_graph_extraction_prompt(
    markdown_text: str,
    *,
    company_name: str,
    fiscal_quarter: str,
    allowed_themes: list[str],
    source_url: str,
    extraction_context: dict[str, Any],
) -> str:
    themes = ", ".join(allowed_themes)
    context = json.dumps(extraction_context, ensure_ascii=False, indent=2)
    return f"""
Company: {company_name}
Fiscal quarter: {fiscal_quarter}
Source URL: {source_url}
Allowed themes: {themes}

Task:
Extract a document-level entity/relation graph from the full Markdown document. Keep entity names canonical and reusable.

Rules:
- Include the company entity.
- Prefer allowed themes when they fit; add only clearly evidenced additional entities.
- Use the provided overview_id as every relation scope_id.
- Do not create Q&A pairs or answers. The output is only the document-level entity/relation graph.
- Keep evidence_text short and source-grounded.
- If a relation is not supported by the source text, omit it.

Extraction context:
---
{context}
---

Markdown source:
---
{markdown_text}
---
""".strip()


def build_chunk_graph_extraction_prompt(
    chunk_text: str,
    *,
    chunk_id: str,
    chunk_metadata: dict[str, Any],
    company_name: str,
    fiscal_quarter: str,
    allowed_themes: list[str],
    source_url: str,
    document_ontology: dict[str, Any] | None = None,
) -> str:
    themes = ", ".join(allowed_themes)
    metadata = json.dumps(chunk_metadata, ensure_ascii=False, indent=2)
    ontology = json.dumps(document_ontology or {}, ensure_ascii=False, indent=2)
    return f"""
Company: {company_name}
Fiscal quarter: {fiscal_quarter}
Source URL: {source_url}
Allowed themes from document ontology: {themes}
Chunk id: {chunk_id}

Task:
Extract entities and relations that are supported by this single paragraph chunk only.

Rules:
- Return the exact chunk_id value: {chunk_id}
- Include the company entity when the chunk discusses company-specific facts.
- Prefer canonical names and aliases from the document ontology when they fit this chunk.
- Add a new entity only when it is explicitly evidenced in this chunk.
- Scope every relation to this chunk by making it supported only by the returned chunk_id.
- Do not use facts from other chunks, headings outside the metadata, or outside knowledge.
- Keep evidence_text short and source-grounded.
- If a relation is not supported by this chunk text, omit it.

Document ontology / canonical vocabulary:
---
{ontology}
---

Chunk metadata:
---
{metadata}
---

Chunk text:
---
{chunk_text}
---
""".strip()


def build_chunk_graph_batch_extraction_prompt(
    chunks: list[dict[str, Any]],
    *,
    company_name: str,
    fiscal_quarter: str,
    allowed_themes: list[str],
    source_url: str,
    document_ontology: dict[str, Any] | None = None,
) -> str:
    themes = ", ".join(allowed_themes)
    ontology = json.dumps(document_ontology or {}, ensure_ascii=False, indent=2)
    chunk_payload = json.dumps(chunks, ensure_ascii=False, indent=2)
    chunk_ids = ", ".join(_as_chunk_id(chunk) for chunk in chunks)
    return f"""
Company: {company_name}
Fiscal quarter: {fiscal_quarter}
Source URL: {source_url}
Allowed themes from document ontology: {themes}
Input chunk ids: {chunk_ids}

Task:
Extract entities and relations for every chunk in the input batch.

Rules:
- Return a top-level object with a chunks array.
- Return exactly one result object per input chunk_id, preserving the exact chunk_id values.
- Treat every chunk independently. Do not use facts from one chunk to extract entities or relations for another chunk.
- Include the company entity when a chunk discusses company-specific facts.
- Prefer canonical names and aliases from the document ontology when they fit the chunk.
- Add a new entity only when it is explicitly evidenced in that chunk.
- Scope every relation to its chunk by making it supported only by the returned chunk_id.
- Do not use outside knowledge.
- Keep evidence_text short and source-grounded.
- If a chunk has no supported graph content, return that chunk_id with empty entities and relations arrays.

Document ontology / canonical vocabulary:
---
{ontology}
---

Input chunks JSON:
---
{chunk_payload}
---
""".strip()


def _as_chunk_id(chunk: dict[str, Any]) -> str:
    value = chunk.get("chunk_id")
    return value if isinstance(value, str) else ""
