import json
import urllib.error

from earnings_call_graph.gemini import (
    BATCH_CHUNK_GRAPH_EXTRACTION_SCHEMA,
    CHUNK_GRAPH_EXTRACTION_SCHEMA,
    DOCUMENT_ONTOLOGY_SCHEMA,
    GeminiApiError,
    GeminiClient,
    GRAPH_EXTRACTION_SCHEMA,
    build_chunk_graph_batch_extraction_prompt,
    build_chunk_graph_extraction_prompt,
    build_document_ontology_prompt,
    build_graph_extraction_prompt,
    build_structured_output_payload,
    parse_gemini_json_response,
)


def test_structured_output_payload_uses_json_schema():
    payload = build_structured_output_payload("hello", GRAPH_EXTRACTION_SCHEMA, "system")
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseJsonSchema"] == GRAPH_EXTRACTION_SCHEMA
    assert payload["systemInstruction"]["parts"][0]["text"] == "system"


def test_parse_gemini_json_response():
    raw = json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": json.dumps({"entities": [], "relations": [], "overview_summary": "ok"})}
                        ]
                    }
                }
            ]
        }
    )
    assert parse_gemini_json_response(raw) == {"entities": [], "relations": [], "overview_summary": "ok"}



def test_document_ontology_prompt_discovers_document_specific_terms_before_chunking():
    prompt = build_document_ontology_prompt(
        "# TSMC Q1\n\nCoWoS capacity and N2 ramp are repeatedly discussed.",
        company_name="TSMC",
        fiscal_quarter="FY2026 Q1",
        source_url="https://example.com/tsmc.pdf",
        seed_themes=["AI demand"],
    )

    assert "document-specific ontology" in prompt
    assert "Seed themes: AI demand" in prompt
    assert "Do not extract relations in this step" in prompt
    assert "CoWoS capacity" in prompt


def test_graph_prompt_contains_extraction_context():
    context = {
        "overview_id": "meta-overview",
        "chunks": [{"id": "meta-chunk-001", "heading": "Q&A"}],
    }
    prompt = build_graph_extraction_prompt(
        "# Meta Q1 2026 Earnings Call",
        company_name="Meta",
        fiscal_quarter="FY2026 Q1",
        allowed_themes=["AI demand", "AI capex"],
        source_url="https://example.com/source.pdf",
        extraction_context=context,
    )

    assert "meta-overview" in prompt
    assert "meta-chunk-001" in prompt
    assert "Use the provided overview_id as every relation scope_id" in prompt


def test_chunk_graph_prompt_scopes_extraction_to_one_chunk():
    prompt = build_chunk_graph_extraction_prompt(
        "AI demand requires more data center capacity.",
        chunk_id="meta-chunk-002",
        chunk_metadata={
            "id": "meta-chunk-002",
            "heading": "Prepared Remarks",
            "speaker_name": "Susan Li",
            "paragraph_index": 2,
        },
        company_name="Meta",
        fiscal_quarter="FY2026 Q1",
        allowed_themes=["AI demand", "AI capex", "CoWoS capacity"],
        source_url="https://example.com/source.pdf",
        document_ontology={
            "entities": [
                {"name": "CoWoS capacity", "entity_type": "Metric", "aliases": ["advanced packaging capacity"]}
            ]
        },
    )

    assert "CoWoS capacity" in prompt
    assert "Document ontology / canonical vocabulary" in prompt
    assert "Return the exact chunk_id value: meta-chunk-002" in prompt
    assert "this single paragraph chunk only" in prompt
    assert "Do not use facts from other chunks" in prompt


def test_chunk_graph_batch_prompt_preserves_chunk_isolation():
    prompt = build_chunk_graph_batch_extraction_prompt(
        [
            {
                "chunk_id": "meta-chunk-001",
                "metadata": {"heading": "Prepared Remarks"},
                "text": "AI demand requires more capacity.",
            },
            {
                "chunk_id": "meta-chunk-002",
                "metadata": {"heading": "Q&A"},
                "text": "Margin pressure remains a risk.",
            },
        ],
        company_name="Meta",
        fiscal_quarter="FY2026 Q1",
        allowed_themes=["AI demand"],
        source_url="https://example.com/source.pdf",
        document_ontology={"themes": ["AI demand"]},
    )

    assert "Return exactly one result object per input chunk_id" in prompt
    assert "Treat every chunk independently" in prompt
    assert "meta-chunk-001" in prompt
    assert "meta-chunk-002" in prompt


def test_graph_schema_requires_graph_fields():
    assert GRAPH_EXTRACTION_SCHEMA["required"] == ["overview_summary", "entities", "relations"]


def test_chunk_graph_schema_requires_chunk_scoped_fields():
    assert CHUNK_GRAPH_EXTRACTION_SCHEMA["required"] == ["chunk_id", "entities", "relations"]
    relation_fields = CHUNK_GRAPH_EXTRACTION_SCHEMA["properties"]["relations"]["items"]["required"]
    assert "scope_id" not in relation_fields


def test_batch_chunk_graph_schema_wraps_chunk_results():
    assert BATCH_CHUNK_GRAPH_EXTRACTION_SCHEMA["required"] == ["chunks"]
    item_schema = BATCH_CHUNK_GRAPH_EXTRACTION_SCHEMA["properties"]["chunks"]["items"]
    assert item_schema["required"] == ["chunk_id", "entities", "relations"]


def test_document_ontology_schema_requires_entities():
    assert DOCUMENT_ONTOLOGY_SCHEMA["required"] == ["document_summary", "entities"]


def test_generate_json_retries_retryable_http_errors(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("earnings_call_graph.gemini._sleep_before_retry", lambda *args: None)

    client = GeminiClient(api_key="test-key", max_retries=2)

    try:
        client.generate_json("hello", GRAPH_EXTRACTION_SCHEMA)
    except GeminiApiError as exc:
        assert "HTTP 503" in str(exc)
    else:
        raise AssertionError("Expected GeminiApiError")

    assert calls["count"] == 3


def test_generate_json_retries_timeouts(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise TimeoutError("read timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("earnings_call_graph.gemini._sleep_before_retry", lambda *args: None)

    client = GeminiClient(api_key="test-key", max_retries=1, timeout=3)

    try:
        client.generate_json("hello", GRAPH_EXTRACTION_SCHEMA)
    except GeminiApiError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("Expected GeminiApiError")

    assert calls["count"] == 2


def test_generate_json_reports_attempt_and_retry_progress(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("earnings_call_graph.gemini._sleep_before_retry", lambda *args: None)

    messages = []
    client = GeminiClient(api_key="test-key", max_retries=1, retry_delay=7)

    try:
        client.generate_json(
            "hello",
            GRAPH_EXTRACTION_SCHEMA,
            progress_callback=messages.append,
            operation="test operation",
        )
    except GeminiApiError:
        pass
    else:
        raise AssertionError("Expected GeminiApiError")

    assert calls["count"] == 2
    assert "test operation: attempt 1/2 started" in messages[0]
    assert any("HTTP 503; retrying in 7s" in message for message in messages)
