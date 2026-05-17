from earnings_call_graph.graph import (
    CONSTRAINTS,
    _load_extracted_document,
    _refresh_ontology_mappings,
    relation_rows_to_graph,
)
from earnings_call_graph.markdown_ingest import (
    DocumentOverview,
    ExtractedDocument,
    ExtractedEntity,
    ExtractedRelation,
    MarkdownChunk,
)


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, statement, **params):
        self.calls.append((statement, params))
        return self

    def consume(self):
        return None


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def data(self):
        return self._rows

    def consume(self):
        return None


class FakeRefreshTx:
    def __init__(self):
        self.calls = []

    def run(self, statement, **params):
        self.calls.append((statement, params))
        if "RETURN entity.id AS id" in statement:
            return FakeResult(
                [
                    {
                        "id": "entity-component-cost",
                        "name": "component cost",
                        "entity_type": "Theme",
                        "aliases": [],
                        "properties": {},
                    }
                ]
            )
        return FakeResult()


def test_new_graph_schema_constraints_are_declared():
    rendered = "\n".join(CONSTRAINTS)
    assert "RelationFact" in rendered
    assert "FiscalPeriod" in rendered
    assert "OntologyConcept" in rendered


def test_load_extracted_document_writes_relation_fact_supported_by_chunk():
    extracted = ExtractedDocument(
        document={
            "id": "testco-doc",
            "title": "TestCo Q1",
            "company_id": "testco",
            "company_name": "TestCo",
            "ticker": "TCO",
            "sector": "Software",
            "fiscal_quarter": "FY2026 Q1",
            "call_id": "testco-2026q1",
            "call_date": "2026-04-30",
            "source_url": "https://example.com/testco",
            "source_kind": "official_ir",
            "markdown_path": "data/testco.md",
        },
        overview=DocumentOverview(
            id="testco-doc-overview",
            document_id="testco-doc",
            summary="Test overview",
            themes=("AI demand",),
            metrics=("CapEx",),
            risks=(),
            chunk_count=1,
            qa_pair_count=0,
            entity_ids=("entity-theme-ai-demand", "entity-metric-capex"),
            relation_ids=("rel-1",),
        ),
        chunks=(
            MarkdownChunk(
                id="testco-doc-chunk-001",
                document_id="testco-doc",
                index=1,
                chunk_type="paragraph",
                heading="Prepared Remarks",
                text="AI demand increases infrastructure CapEx.",
                start_line=1,
                end_line=2,
            ),
        ),
        qa_pairs=(),
        answers=(),
        entities=(
            ExtractedEntity(id="entity-theme-ai-demand", name="AI demand", entity_type="Theme"),
            ExtractedEntity(id="entity-metric-capex", name="CapEx", entity_type="Metric"),
        ),
        relations=(
            ExtractedRelation(
                id="rel-1",
                source_entity_id="entity-theme-ai-demand",
                relation_type="DRIVES",
                target_entity_id="entity-metric-capex",
                scope_id="testco-doc-chunk-001",
                evidence_text="AI demand increases infrastructure CapEx.",
                confidence=0.91,
            ),
        ),
    )
    tx = FakeTx()

    _load_extracted_document(tx, extracted)

    cypher = "\n".join(call[0] for call in tx.calls)
    params = [call[1] for call in tx.calls]
    assert "MERGE (rf:RelationFact {id: $fact_id})" in cypher
    assert "MERGE (rf)-[:SUPPORTED_BY]->(ch)" in cypher
    assert "MERGE (concept:OntologyConcept {id: $concept_id})" in cypher
    assert "MERGE (e)-[mapped:MAPS_TO]->(concept)" in cypher
    assert "MERGE (source)-[rel:`IS_A`]->(target)" in cypher
    assert "MERGE (q:Quarter {name: $quarter})" in cypher
    assert "MERGE (fp:FiscalPeriod {id: $period_id})" in cypher
    assert "ontology_schema" in cypher
    assert any(item.get("fact_id") == "fact-rel-1" for item in params)
    document_params = next(item for item in params if item.get("document_id") == "testco-doc")
    assert document_params["period_id"] == "fy2026-q1"
    assert document_params["fiscal_year"] == 2026
    assert document_params["quarter"] == "Q1"
    assert document_params["quarter_number"] == 1
    chunk_params = next(item for item in params if item.get("id") == "testco-doc-chunk-001")
    assert chunk_params["text_hash"]
    assert chunk_params["text_preview"] == "AI demand increases infrastructure CapEx."


def test_refresh_ontology_mappings_rebuilds_existing_entity_resolution_edges():
    tx = FakeRefreshTx()

    mapping_count = _refresh_ontology_mappings(tx)

    cypher = "\n".join(call[0] for call in tx.calls)
    params = [call[1] for call in tx.calls]
    assert mapping_count >= 1
    assert "DELETE mapped" in cypher
    assert "RETURN entity.id AS id" in cypher
    assert any(item.get("concept_id") == "concept-component-cost-pressure" for item in params)


def test_relation_rows_to_graph_deduplicates_nodes_and_edges():
    graph = relation_rows_to_graph(
        [
            {
                "fact_id": "fact-1",
                "source_id": "entity-a",
                "source": "AI demand",
                "source_type": "Theme",
                "relation": "DRIVES",
                "target_id": "entity-b",
                "target": "CapEx",
                "target_type": "Metric",
                "confidence": 0.9,
                "company": "TestCo",
                "chunk_id": "chunk-1",
            },
            {
                "fact_id": "fact-1",
                "source_id": "entity-a",
                "source": "AI demand",
                "source_type": "Theme",
                "relation": "DRIVES",
                "target_id": "entity-b",
                "target": "CapEx",
                "target_type": "Metric",
                "confidence": 0.9,
                "company": "TestCo",
                "chunk_id": "chunk-1",
            },
        ]
    )

    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["label"] == "DRIVES"


def test_relation_rows_to_graph_preserves_ontology_aggregate_counts():
    graph = relation_rows_to_graph(
        [
            {
                "fact_id": "ontology-concept-ai-demand-DRIVES-concept-capex",
                "source_id": "concept-ai-demand",
                "source": "AI Demand",
                "source_type": "OntologyConcept",
                "source_properties": {"concept_type": "Theme", "entities": ["AI demand", "AI workloads"]},
                "relation": "DRIVES",
                "relation_layer": "ontology",
                "target_id": "concept-infrastructure-capex",
                "target": "Infrastructure CapEx",
                "target_type": "OntologyConcept",
                "fact_count": 4,
                "evidence_count": 3,
                "company": ["Alphabet", "Meta"],
            }
        ]
    )

    assert graph["nodes"][0]["type"] == "OntologyConcept"
    assert graph["edges"][0]["layer"] == "ontology"
    assert graph["edges"][0]["fact_count"] == 4
    assert graph["edges"][0]["company"] == ["Alphabet", "Meta"]
