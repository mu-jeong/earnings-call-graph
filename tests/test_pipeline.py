import json
from pathlib import Path

from earnings_call_graph.pipeline import load_metadata_manifest, process_markdown_folder
from earnings_call_graph.sources import EXAMPLE_MANIFEST_PATH


SAMPLE_MARKDOWN = """# TestCo Q1 2026 Earnings Call

## Q&A

**Analyst:** Jane Doe, Example Securities
**Question:** How is AI demand affecting capex?

**Pat Lee, CFO:** AI demand increases infrastructure capex and creates margin pressure.
"""


def test_process_markdown_folder_with_manifest_and_no_llm(tmp_path):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    markdown = input_dir / "testco-2026-q1.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "filename": markdown.name,
                        "company": "TestCo",
                        "company_id": "testco",
                        "ticker": "TCO",
                        "sector": "Software",
                        "quarter": "FY2026 Q1",
                        "call_id": "testco-2026q1",
                        "call_date": "2026-04-30",
                        "source_url": "https://example.com/testco",
                        "source_type": "transcript_html",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    results = process_markdown_folder(input_dir, output_dir, manifest=manifest, use_llm=False)

    assert len(results) == 1
    assert results[0].output_path.exists()
    raw = json.loads(results[0].output_path.read_text(encoding="utf-8"))
    assert raw["document"]["company_name"] == "TestCo"
    assert raw["qa_pairs"] == []
    assert raw["answers"] == []
    assert results[0].relation_count > 0


def test_load_metadata_manifest_accepts_keyed_object(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sample.md": {
                    "company": "Sample",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/sample",
                }
            }
        ),
        encoding="utf-8",
    )

    metadata = load_metadata_manifest(manifest)

    assert metadata["sample.md"]["company"] == "Sample"
    assert metadata["sample.md"]["source_type"] == "earnings_source_html"
    assert metadata["sample.md"]["source_adapter"] == "generic-html"


def test_load_metadata_manifest_uses_public_example_source_registry():
    metadata = load_metadata_manifest(EXAMPLE_MANIFEST_PATH)

    assert len(metadata) == 7
    assert all(item.get("fiscal_year") == "FY2026" for item in metadata.values())
    assert all(item["quarter"].startswith("FY2026 ") for item in metadata.values())
    assert all("2025" not in filename.lower() for filename in metadata)
    assert metadata["microsoft-fy2026-q2.md"].get("source_url", "") == ""
    assert metadata["microsoft-fy2026-q2.md"]["source_adapter"] == "unconfigured-source"
    assert metadata["microsoft-fy2026-q2.md"]["source_type"] == "conference_call_transcript_html"
    assert metadata["cisco-fy2026-q2.md"]["source_type"] == "conference_call_prepared_remarks_pdf"
    assert metadata["nvidia-fy2026-q2.md"]["source_type"] == "conference_call_prepared_remarks_html"


def test_process_markdown_folder_can_use_materialized_source_text(tmp_path, monkeypatch):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    source_cache = tmp_path / "source_cache"
    input_dir.mkdir()
    markdown = input_dir / "testco-2026-q1.md"
    markdown.write_text("fixture text that should not be used", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                markdown.name: {
                    "company": "TestCo",
                    "company_id": "testco",
                    "ticker": "TCO",
                    "sector": "Software",
                    "quarter": "FY2026 Q1",
                    "call_id": "testco-2026q1",
                    "call_date": "2026-04-30",
                    "source_url": "https://example.com/testco-source",
                    "source_type": "transcript_html",
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_download(source_url):
        return (
            b"<html><body><h1>Official TestCo Source</h1><p>AI demand increases infrastructure capex.</p></body></html>",
            "text/html",
        )

    monkeypatch.setattr("earnings_call_graph.source_documents._download_source", fake_download)

    results = process_markdown_folder(
        input_dir,
        output_dir,
        manifest=manifest,
        use_llm=False,
        use_source_documents=True,
        source_cache_dir=source_cache,
    )

    raw = json.loads(results[0].output_path.read_text(encoding="utf-8"))
    assert "source_cache" in raw["document"]["markdown_path"]
    assert raw["chunks"][0]["text"].startswith("TestCo FY2026 Q1 Official Source")


def test_process_markdown_folder_can_limit_real_source_count(tmp_path):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    manifest_entries = {}
    for index in range(3):
        markdown = input_dir / f"testco-{index}.md"
        markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
        manifest_entries[markdown.name] = {
            "company": f"TestCo {index}",
            "quarter": "FY2026 Q1",
            "source_url": f"https://example.com/testco-{index}",
            "source_type": "transcript_html",
        }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_entries), encoding="utf-8")

    results = process_markdown_folder(input_dir, output_dir, manifest=manifest, use_llm=False, max_documents=2)

    assert len(results) == 2


def test_process_markdown_folder_skips_sources_marked_not_confirmed(tmp_path):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    transcript = input_dir / "transcript.md"
    not_confirmed = input_dir / "not-confirmed.md"
    transcript.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    not_confirmed.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                transcript.name: {
                    "company": "TranscriptCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/transcript",
                    "source_type": "transcript_html",
                },
                not_confirmed.name: {
                    "company": "NotConfirmedCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/webcast-only",
                    "source_type": "transcript_html",
                    "conference_call_confirmed": "false",
                },
            }
        ),
        encoding="utf-8",
    )

    results = process_markdown_folder(input_dir, output_dir, manifest=manifest, use_llm=False)

    assert [result.input_path.name for result in results] == ["transcript.md"]
    assert not (output_dir / "not-confirmed-graph.json").exists()


def test_process_markdown_folder_skips_non_conference_call_sources(tmp_path):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    transcript = input_dir / "transcript.md"
    release = input_dir / "release.md"
    transcript.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    release.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                transcript.name: {
                    "company": "TranscriptCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/transcript",
                    "source_type": "transcript_html",
                },
                release.name: {
                    "company": "ReleaseCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/release",
                    "source_type": "earnings_release_html",
                },
            }
        ),
        encoding="utf-8",
    )
    messages = []

    results = process_markdown_folder(
        input_dir,
        output_dir,
        manifest=manifest,
        use_llm=False,
        progress_callback=messages.append,
    )

    assert [result.input_path.name for result in results] == ["transcript.md"]
    assert not (output_dir / "release-graph.json").exists()
    assert any("without a confirmed conference-call transcript source" in message for message in messages)


def test_process_markdown_folder_reports_progress(tmp_path):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    markdown = input_dir / "testco-2026-q1.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                markdown.name: {
                    "company": "TestCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/testco",
                    "source_type": "transcript_html",
                }
            }
        ),
        encoding="utf-8",
    )
    messages = []

    process_markdown_folder(
        input_dir,
        output_dir,
        manifest=manifest,
        use_llm=False,
        progress_callback=messages.append,
    )

    assert any("Queued 1 document" in message for message in messages)
    assert any("[1/1] testco-2026-q1.md: starting" in message for message in messages)
    assert any("deterministic extraction complete" in message for message in messages)
    assert any("Processed 1 document" in message for message in messages)


def test_process_markdown_folder_skips_existing_graph_json(tmp_path, monkeypatch):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    markdown = input_dir / "testco-2026-q1.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                markdown.name: {
                    "company": "TestCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/testco",
                    "source_type": "transcript_html",
                }
            }
        ),
        encoding="utf-8",
    )
    first_results = process_markdown_folder(input_dir, output_dir, manifest=manifest, use_llm=False)
    existing = first_results[0].output_path.read_text(encoding="utf-8")
    messages = []

    def fail_if_called(*args, **kwargs):
        raise AssertionError("existing graph JSON should skip ingestion")

    monkeypatch.setattr("earnings_call_graph.pipeline.ingest_markdown_document", fail_if_called)

    results = process_markdown_folder(
        input_dir,
        output_dir,
        manifest=manifest,
        use_llm=False,
        progress_callback=messages.append,
    )

    assert len(results) == 1
    assert results[0].reused_existing_output is True
    assert results[0].output_path.read_text(encoding="utf-8") == existing
    assert any("existing graph JSON found" in message for message in messages)
    assert any("skipping extraction" in message for message in messages)


def test_process_markdown_folder_can_force_reprocess_existing_graph_json(tmp_path):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    input_dir.mkdir()
    markdown = input_dir / "testco-2026-q1.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                markdown.name: {
                    "company": "TestCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/testco",
                    "source_type": "transcript_html",
                }
            }
        ),
        encoding="utf-8",
    )
    output = output_dir / "testco-2026-q1-graph.json"
    output.parent.mkdir()
    output.write_text("{not valid json", encoding="utf-8")
    messages = []

    results = process_markdown_folder(
        input_dir,
        output_dir,
        manifest=manifest,
        use_llm=False,
        skip_existing=False,
        progress_callback=messages.append,
    )

    assert results[0].reused_existing_output is False
    assert json.loads(output.read_text(encoding="utf-8"))["document"]["company_name"] == "TestCo"
    assert not any("existing graph JSON" in message for message in messages)


def test_process_markdown_folder_can_enumerate_source_registry_without_local_markdown(tmp_path, monkeypatch):
    input_dir = tmp_path / "docs"
    output_dir = tmp_path / "graphs"
    source_cache = tmp_path / "source_cache"
    input_dir.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "remote-only.md": {
                    "company": "RemoteCo",
                    "quarter": "FY2026 Q1",
                    "source_url": "https://example.com/remoteco-source",
                    "source_type": "transcript_html",
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeSourceText:
        def __init__(self, markdown_path):
            self.markdown_path = markdown_path

    def fake_materialize_source_markdown(*, title, slug, cache_dir, **kwargs):
        markdown_path = Path(cache_dir) / "markdown" / f"{slug}.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(f"# {title}\n\nAI demand increases infrastructure capex.", encoding="utf-8")
        return FakeSourceText(markdown_path)

    monkeypatch.setattr("earnings_call_graph.pipeline.materialize_source_markdown", fake_materialize_source_markdown)

    results = process_markdown_folder(
        input_dir,
        output_dir,
        manifest=manifest,
        use_llm=False,
        use_source_documents=True,
        source_cache_dir=source_cache,
        max_documents=1,
    )

    assert len(results) == 1
    assert results[0].input_path.name == "cisco-fy2026-q2.md"
