import json

from earnings_call_graph.cli import main
from earnings_call_graph.markdown_ingest import ingest_markdown_document, load_extracted_document


SAMPLE_MARKDOWN = """# Meta Q1 2026 Earnings Call

## Prepared Remarks

**Mark Zuckerberg, CEO:** AI demand is strong and we are increasing infrastructure capex to support compute needs.

## Q&A

**Analyst:** Eric Sheridan, Goldman Sachs
**Question:** How should we think about infrastructure capex and operating margin?

**Susan Li, CFO:** We raised our infrastructure capex forecast because AI demand requires more data center capacity. Total expenses and depreciation create margin pressure, but the investment supports revenue growth.

**Mark Zuckerberg, CEO:** AI products are seeing strong usage growth and we expect compute needs to keep increasing.
"""


def test_ingest_markdown_builds_overview_and_relation_graph(tmp_path):
    markdown = tmp_path / "meta.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    extracted = ingest_markdown_document(
        markdown,
        company_name="Meta Platforms",
        ticker="META",
        sector="Consumer Internet",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/meta.pdf",
        use_llm=False,
    )

    assert extracted.overview.qa_pair_count == 0
    assert extracted.qa_pairs == ()
    assert extracted.answers == ()
    assert "AI capex" in extracted.overview.themes
    assert "operating margin" not in extracted.overview.metrics
    assert "margin pressure" in extracted.overview.risks
    assert extracted.relations
    assert all(relation.scope_id in {chunk.id for chunk in extracted.chunks} for relation in extracted.relations)


def test_ingest_markdown_chunks_speaker_paragraphs_with_stable_metadata(tmp_path):
    markdown = tmp_path / "meta.md"
    markdown.write_text(
        """# Meta Q1 2026 Earnings Call

## Prepared Remarks

**Susan Li, CFO:** AI demand requires more data center capacity.

Infrastructure capex will increase to support compute needs.

Margin pressure remains a near-term risk.
""",
        encoding="utf-8",
    )

    first = ingest_markdown_document(
        markdown,
        company_name="Meta Platforms",
        ticker="META",
        sector="Consumer Internet",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/meta.pdf",
        use_llm=False,
    )
    second = ingest_markdown_document(
        markdown,
        company_name="Meta Platforms",
        ticker="META",
        sector="Consumer Internet",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/meta.pdf",
        use_llm=False,
    )

    graph_chunks = [chunk for chunk in first.chunks if "AI demand" in chunk.text or "Infrastructure capex" in chunk.text or "Margin pressure" in chunk.text]
    assert [chunk.text for chunk in graph_chunks] == [
        "AI demand requires more data center capacity.",
        "Infrastructure capex will increase to support compute needs.",
        "Margin pressure remains a near-term risk.",
    ]
    assert all(chunk.speaker_name == "" for chunk in graph_chunks)
    assert all(chunk.speaker_title == "" for chunk in graph_chunks)
    assert all(chunk.text_hash for chunk in graph_chunks)
    assert [chunk.id for chunk in first.chunks] == [chunk.id for chunk in second.chunks]
    assert [chunk.text_hash for chunk in first.chunks] == [chunk.text_hash for chunk in second.chunks]
    assert graph_chunks[0].start_line == graph_chunks[0].end_line == 5
    assert graph_chunks[1].start_line == graph_chunks[1].end_line == 7
    assert graph_chunks[2].start_line == graph_chunks[2].end_line == 9


def test_ingest_markdown_skips_source_note_page_number_and_page_heading_chunks(tmp_path):
    markdown = tmp_path / "source.md"
    markdown.write_text(
        """# TestCo Official Source

> Full official source text extracted from https://example.com/source.pdf

## Page 1

1

AI demand increases infrastructure capex.
""",
        encoding="utf-8",
    )

    extracted = ingest_markdown_document(
        markdown,
        company_name="TestCo",
        fiscal_quarter="FY2026 Q1",
        source_url="https://example.com/source.pdf",
        use_llm=False,
    )

    texts = [chunk.text for chunk in extracted.chunks]
    assert "> Full official source text" not in "\n".join(texts)
    assert "Page 1" not in texts
    assert "1" not in texts
    assert "AI demand increases infrastructure capex." in texts


def test_ingest_markdown_parses_plain_speaker_labels_and_splits_long_pdf_blocks(tmp_path):
    long_text = " ".join(
        f"AI infrastructure sentence {index} supports Google Cloud growth and revenue."
        for index in range(30)
    )
    markdown = tmp_path / "alphabet.md"
    markdown.write_text(
        f"""# Alphabet Q1 2026 Earnings Call

## Page 1

Sundar Pichai, CEO, Alphabet and Google: {long_text}
""",
        encoding="utf-8",
    )

    extracted = ingest_markdown_document(
        markdown,
        company_name="Alphabet",
        ticker="GOOGL",
        sector="Search / Cloud / Big Tech",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/alphabet.pdf",
        use_llm=False,
    )

    long_chunks = [chunk for chunk in extracted.chunks if "AI infrastructure sentence" in chunk.text]
    assert len(long_chunks) > 1
    assert all(chunk.speaker_name == "" for chunk in long_chunks)
    assert all(chunk.speaker_title == "" for chunk in long_chunks)
    assert all(len(chunk.text) <= 900 for chunk in long_chunks)


def test_ingest_markdown_excludes_analyst_question_chunks_from_graph(tmp_path):
    markdown = tmp_path / "qa.md"
    markdown.write_text(
        """# TestCo Q1 2026 Earnings Call

## Q&A

Analyst: Could you speak about supply chain constraints and CapEx?

CFO: CapEx supports AI infrastructure and data center capacity.
""",
        encoding="utf-8",
    )

    extracted = ingest_markdown_document(
        markdown,
        company_name="TestCo",
        ticker="TCO",
        sector="Software",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/testco.pdf",
        allowed_themes=("AI capex", "data center capacity"),
        use_llm=False,
    )

    entity_names = {entity.name for entity in extracted.entities}
    assert "AI capex" in entity_names
    assert "supply chain constraints" not in entity_names
    assert all("supply chain constraints" not in relation.evidence_text.lower() for relation in extracted.relations)


def test_ingest_markdown_cli_round_trips_json(tmp_path):
    markdown = tmp_path / "meta.md"
    output = tmp_path / "graph.json"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    class FakeGeminiClient:
        def extract_graph(self, markdown_text, **kwargs):
            assert "Meta Q1 2026 Earnings Call" in markdown_text
            return {
                "overview_summary": "Meta links AI demand to infrastructure capex.",
                "entities": [
                    {"name": "Meta Platforms", "entity_type": "Company", "confidence": 1.0},
                    {"name": "AI demand", "entity_type": "Theme", "confidence": 0.9},
                    {"name": "infrastructure capex", "entity_type": "Metric", "confidence": 0.86},
                ],
                "relations": [
                    {
                        "source_entity": "AI demand",
                        "relation_type": "DRIVES",
                        "target_entity": "infrastructure capex",
                        "scope_id": "meta-platforms-fy2026-q1-meta-overview",
                        "evidence_text": "AI demand requires more infrastructure capex.",
                        "confidence": 0.88,
                    }
                ],
            }

    from pytest import MonkeyPatch

    monkeypatch = MonkeyPatch()
    monkeypatch.setattr("earnings_call_graph.gemini.GeminiClient", FakeGeminiClient)
    try:
        exit_code = main([
            "ingest-markdown",
            str(markdown),
            "--company",
            "Meta Platforms",
            "--ticker",
            "META",
            "--sector",
            "Consumer Internet",
            "--quarter",
            "FY2026 Q1",
            "--call-date",
            "2026-04-29",
            "--source-url",
            "https://example.com/meta.pdf",
            "--out",
            str(output),
        ])
    finally:
        monkeypatch.undo()

    assert exit_code == 0
    raw = json.loads(output.read_text(encoding="utf-8"))
    assert raw["document"]["company_name"] == "Meta Platforms"
    assert raw["entities"][0]["source"] == "llm"

    loaded = load_extracted_document(output)
    assert loaded.document["id"] == raw["document"]["id"]
    assert loaded.relations[0].relation_type == "DRIVES"


def test_ingest_markdown_uses_llm_graph_extraction_by_default(tmp_path, monkeypatch):
    markdown = tmp_path / "meta.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    class FakeGeminiClient:
        def extract_graph(self, markdown_text, **kwargs):
            assert "Meta Q1 2026 Earnings Call" in markdown_text
            return {
                "overview_summary": "Meta links AI demand to infrastructure capex and margin pressure.",
                "entities": [
                    {"name": "Meta Platforms", "entity_type": "Company", "confidence": 1.0},
                    {"name": "AI demand", "entity_type": "Theme", "confidence": 0.9},
                    {"name": "infrastructure capex", "entity_type": "Metric", "confidence": 0.86},
                    {"name": "margin pressure", "entity_type": "Risk", "confidence": 0.83},
                ],
                "relations": [
                    {
                        "source_entity": "AI demand",
                        "relation_type": "DRIVES",
                        "target_entity": "infrastructure capex",
                        "scope_id": "meta-platforms-fy2026-q1-meta-overview",
                        "evidence_text": "AI demand requires more infrastructure capex.",
                        "confidence": 0.88,
                    }
                ],
            }

    monkeypatch.setattr("earnings_call_graph.gemini.GeminiClient", FakeGeminiClient)

    extracted = ingest_markdown_document(
        markdown,
        company_name="Meta Platforms",
        ticker="META",
        sector="Consumer Internet",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/meta.pdf",
    )

    assert extracted.overview.summary == "Meta links AI demand to infrastructure capex and margin pressure."
    assert any(entity.source == "llm" for entity in extracted.entities)
    assert extracted.qa_pairs == ()
    assert extracted.answers == ()
    assert extracted.relations[0].relation_type == "DRIVES"
    assert extracted.relations[0].scope_id == extracted.overview.id



def test_ingest_markdown_discovers_document_ontology_before_chunk_extraction(tmp_path, monkeypatch):
    markdown = tmp_path / "tsmc.md"
    markdown.write_text(
        """# TSMC Q1 2026 Earnings Call

## Prepared Remarks

**C.C. Wei, CEO:** AI demand is driving CoWoS capacity expansion.
""",
        encoding="utf-8",
    )
    ontology_calls = []
    chunk_calls = []

    class FakeGeminiClient:
        def extract_document_ontology(self, markdown_text, **kwargs):
            ontology_calls.append((markdown_text, kwargs))
            return {
                "document_summary": "TSMC links AI demand to CoWoS capacity.",
                "entities": [
                    {"name": "TSMC", "entity_type": "Company", "confidence": 1.0},
                    {"name": "AI demand", "entity_type": "Theme", "aliases": ["AI workloads"], "confidence": 0.92},
                    {"name": "CoWoS capacity", "entity_type": "Metric", "aliases": ["advanced packaging capacity"], "confidence": 0.9},
                ],
                "themes": ["AI demand"],
                "metrics": ["CoWoS capacity"],
                "risks": [],
                "company_terms": ["CoWoS"],
            }

        def extract_chunk_graph(self, chunk_text, **kwargs):
            chunk_calls.append((chunk_text, kwargs))
            if "CoWoS" not in chunk_text:
                return {"chunk_id": kwargs["chunk_id"], "entities": [], "relations": []}
            assert kwargs["document_ontology"]["metrics"] == ["CoWoS capacity"]
            assert "AI demand" in kwargs["allowed_themes"]
            return {
                "chunk_id": kwargs["chunk_id"],
                "entities": [
                    {"name": "TSMC", "entity_type": "Company", "confidence": 1.0},
                    {"name": "AI demand", "entity_type": "Theme", "confidence": 0.92},
                ],
                "relations": [
                    {
                        "source_entity": "AI workloads",
                        "relation_type": "DRIVES",
                        "target_entity": "advanced packaging capacity",
                        "evidence_text": "AI demand drives CoWoS capacity expansion.",
                        "confidence": 0.9,
                    }
                ],
            }

    monkeypatch.setattr("earnings_call_graph.gemini.GeminiClient", FakeGeminiClient)

    extracted = ingest_markdown_document(
        markdown,
        company_name="TSMC",
        ticker="TSM",
        sector="Semiconductors",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-16",
        source_url="https://example.com/tsmc.pdf",
    )

    assert len(ontology_calls) == 1
    assert chunk_calls
    assert any(entity.name == "CoWoS capacity" and entity.entity_type == "Metric" for entity in extracted.entities)
    assert extracted.relations[0].source_entity_id == "entity-theme-ai-demand"
    assert extracted.relations[0].target_entity_id == "entity-metric-cowos-capacity"


def test_ingest_markdown_uses_chunk_scoped_llm_extraction_when_available(tmp_path, monkeypatch):
    markdown = tmp_path / "meta.md"
    markdown.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    calls = []

    class FakeGeminiClient:
        def extract_chunk_graph(self, chunk_text, **kwargs):
            calls.append((chunk_text, kwargs))
            chunk_id = kwargs["chunk_id"]
            if "AI demand" not in chunk_text:
                return {"chunk_id": chunk_id, "entities": [], "relations": [], "quality_flags": ["empty"]}
            return {
                "chunk_id": chunk_id,
                "entities": [
                    {"name": "Meta Platforms", "entity_type": "Company", "confidence": 1.0},
                    {"name": "AI demand", "entity_type": "Theme", "confidence": 0.9},
                    {"name": "data center capacity", "entity_type": "Theme", "confidence": 0.86},
                ],
                "relations": [
                    {
                        "source_entity": "AI demand",
                        "relation_type": "DRIVES",
                        "target_entity": "data center capacity",
                        "evidence_text": "AI demand requires more capacity.",
                        "confidence": 0.88,
                    },
                    {
                        "source_entity": "AI demand",
                        "relation_type": "DRIVES",
                        "target_entity": "missing entity",
                        "evidence_text": "This should be rejected.",
                        "confidence": 0.7,
                    },
                ],
            }

    monkeypatch.setattr("earnings_call_graph.gemini.GeminiClient", FakeGeminiClient)

    extracted = ingest_markdown_document(
        markdown,
        company_name="Meta Platforms",
        ticker="META",
        sector="Consumer Internet",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/meta.pdf",
    )

    assert len(calls) < len(extracted.chunks)
    assert all("How should we think" not in chunk_text for chunk_text, _ in calls)
    assert all("chunk_metadata" in kwargs for _, kwargs in calls)
    assert extracted.relations
    assert all(relation.scope_id in {chunk.id for chunk in extracted.chunks} for relation in extracted.relations)
    assert all(relation.target_entity_id != "entity-businessterm-missing-entity" for relation in extracted.relations)


def test_ingest_markdown_batches_chunk_llm_extraction(tmp_path, monkeypatch):
    markdown = tmp_path / "meta.md"
    markdown.write_text(
        """# Meta Q1 2026 Earnings Call

## Prepared Remarks

AI demand requires more data center capacity.

Infrastructure capex will increase.

Margin pressure remains a near-term risk.

Revenue growth remains strong.

Operating expenses are increasing.
""",
        encoding="utf-8",
    )
    batch_sizes = []

    class FakeGeminiClient:
        def extract_document_ontology(self, markdown_text, **kwargs):
            return {
                "document_summary": "Meta discusses AI demand and margin pressure.",
                "entities": [
                    {"name": "Meta Platforms", "entity_type": "Company", "confidence": 1.0},
                    {"name": "AI demand", "entity_type": "Theme", "confidence": 0.9},
                ],
                "themes": ["AI demand"],
                "metrics": [],
                "risks": [],
                "company_terms": [],
            }

        def extract_chunk_graph(self, chunk_text, **kwargs):
            raise AssertionError("Expected batched chunk extraction")

        def extract_chunk_graph_batch(self, chunks, **kwargs):
            batch_sizes.append(len(chunks))
            return [
                {
                    "chunk_id": chunk["chunk_id"],
                    "entities": [
                        {"name": "Meta Platforms", "entity_type": "Company", "confidence": 1.0},
                        {"name": "AI demand", "entity_type": "Theme", "confidence": 0.9},
                    ],
                    "relations": [
                        {
                            "source_entity": "Meta Platforms",
                            "relation_type": "DISCUSSES",
                            "target_entity": "AI demand",
                            "evidence_text": "The chunk discusses AI demand.",
                            "confidence": 0.8,
                        }
                    ],
                }
                for chunk in chunks
            ]

    monkeypatch.setattr("earnings_call_graph.gemini.GeminiClient", FakeGeminiClient)

    extracted = ingest_markdown_document(
        markdown,
        company_name="Meta Platforms",
        ticker="META",
        sector="Consumer Internet",
        fiscal_quarter="FY2026 Q1",
        call_date="2026-04-29",
        source_url="https://example.com/meta.pdf",
        llm_chunk_batch_size=2,
    )

    assert all(size <= 2 for size in batch_sizes)
    assert sum(batch_sizes) == len(extracted.chunks)
    assert len(batch_sizes) < len(extracted.chunks)
    assert len(extracted.relations) == len(extracted.chunks)
