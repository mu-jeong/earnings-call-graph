from earnings_call_graph.ui.graph_app import (
    APP_CSS,
    ASK_QUESTION_PRESETS,
    add_company_context_node,
    answer_question_from_relations,
    build_connected_node_summary_prompt,
    build_graph_chunk_summary_prompt,
    build_ontology_chunk_summary_prompt,
    build_text2cypher_prompt,
    connected_node_summary_rows,
    edge_table_rows,
    filter_payload_by_min_node_degree,
    graph_counts,
    interactive_graph_html,
    key_node_explanation,
    node_select_options,
    ontology_concept_select_options,
    graph_result_count,
    query_terms,
    referenced_chunk_rows,
    result_limit_slider_config,
    result_limit_slider_enabled,
    truncate,
    unique_chunk_rows,
    validate_text2cypher,
)
import earnings_call_graph.ui.graph_app as graph_app


def test_result_limit_slider_config_uses_available_count_as_max():
    assert result_limit_slider_config(347) == (1, 347, 80, 10)
    assert result_limit_slider_config(8) == (1, 8, 8, 1)
    assert result_limit_slider_config(0) == (1, 1, 1, 1)


def test_graph_counts_reports_distinct_period_labels_and_quarters(monkeypatch):
    captured = {}

    def fake_neo4j_query(cypher, params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [], None

    graph_app.graph_counts.clear()
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    rows, error = graph_counts()

    assert rows == []
    assert error is None
    assert "MATCH (call:EarningsCall)" in captured["cypher"]
    assert "RETURN 'FiscalPeriod' AS label" in captured["cypher"]
    assert "RETURN 'Quarter' AS label" in captured["cypher"]
    assert "count(DISTINCT quarter)" in captured["cypher"]
    assert "FiscalPeriod" not in captured["params"]["labels"]


def test_result_limit_slider_enabled_requires_at_least_two_rows():
    assert result_limit_slider_enabled(0) is False
    assert result_limit_slider_enabled(1) is False
    assert result_limit_slider_enabled(2) is True


def test_filter_payload_by_min_node_degree_keeps_dense_relation_core():
    payload = {
        "nodes": [
            {"id": "a", "label": "AI Demand", "type": "Theme"},
            {"id": "b", "label": "Revenue", "type": "Metric"},
            {"id": "c", "label": "CapEx", "type": "Metric"},
            {"id": "leaf", "label": "One-off", "type": "Theme"},
        ],
        "edges": [
            {"id": "a-b", "source": "a", "target": "b", "label": "DRIVES"},
            {"id": "b-c", "source": "b", "target": "c", "label": "PRESSURES"},
            {"id": "c-a", "source": "c", "target": "a", "label": "AFFECTS"},
            {"id": "a-leaf", "source": "a", "target": "leaf", "label": "DISCUSSES"},
        ],
    }

    filtered = filter_payload_by_min_node_degree(payload, min_degree=2)

    assert {node["id"] for node in filtered["nodes"]} == {"a", "b", "c"}
    assert {edge["id"] for edge in filtered["edges"]} == {"a-b", "b-c", "c-a"}


def test_filter_payload_by_min_node_degree_supports_custom_thresholds():
    payload = {
        "nodes": [
            {"id": "hub", "label": "AI Demand", "type": "Theme"},
            {"id": "a", "label": "Revenue", "type": "Metric"},
            {"id": "b", "label": "CapEx", "type": "Metric"},
            {"id": "c", "label": "Margins", "type": "Metric"},
        ],
        "edges": [
            {"id": "hub-a", "source": "hub", "target": "a", "label": "DRIVES"},
            {"id": "hub-b", "source": "hub", "target": "b", "label": "DRIVES"},
            {"id": "hub-c", "source": "hub", "target": "c", "label": "PRESSURES"},
            {"id": "a-b", "source": "a", "target": "b", "label": "AFFECTS"},
        ],
    }

    filtered = filter_payload_by_min_node_degree(payload, min_degree=3)

    assert {node["id"] for node in filtered["nodes"]} == {"hub"}
    assert filtered["edges"] == []


def test_filter_payload_by_min_node_degree_preserves_company_context_for_retained_nodes():
    payload = {
        "nodes": [
            {"id": "company:NVDA", "label": "NVIDIA", "type": "Company"},
            {"id": "a", "label": "AI Demand", "type": "Theme"},
            {"id": "b", "label": "Revenue", "type": "Metric"},
            {"id": "c", "label": "CapEx", "type": "Metric"},
        ],
        "edges": [
            {"id": "a-b", "source": "a", "target": "b", "label": "DRIVES"},
            {"id": "b-c", "source": "b", "target": "c", "label": "PRESSURES"},
            {"id": "c-a", "source": "c", "target": "a", "label": "AFFECTS"},
            {"id": "ctx-a", "source": "company:NVDA", "target": "a", "label": "HAS_CONTEXT", "layer": "company_scope"},
        ],
    }

    filtered = filter_payload_by_min_node_degree(payload, min_degree=2)

    assert "company:NVDA" in {node["id"] for node in filtered["nodes"]}
    assert any(edge["id"] == "ctx-a" for edge in filtered["edges"])


def test_graph_result_count_uses_current_search(monkeypatch):
    calls = []

    def fake_relation_count(search="", company_ticker=""):
        calls.append(("relations", search, company_ticker))
        return 12, None

    def fake_ontology_count(search="", company_ticker=""):
        calls.append(("ontology", search, company_ticker))
        return 7, None

    monkeypatch.setattr(graph_app, "relation_fact_count", fake_relation_count)
    monkeypatch.setattr(graph_app, "ontology_relation_count", fake_ontology_count)

    assert graph_result_count("Company entities", "Blackwell", "NVDA") == (12, None)
    assert graph_result_count("Ontology concepts", "capex", "MSFT") == (7, None)
    assert calls == [
        ("relations", "Blackwell", "NVDA"),
        ("ontology", "capex", "MSFT"),
    ]


def test_balanced_relation_fact_rows_uses_company_round_robin_query(monkeypatch):
    captured = {}

    def fake_neo4j_query(cypher, params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [], None

    graph_app.balanced_relation_fact_rows.clear()
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    rows, error = graph_app.balanced_relation_fact_rows("AI", 13)

    assert rows == []
    assert error is None
    assert captured["params"] == {"terms": ["ai"], "limit": 13}
    assert "company_bucket" in captured["cypher"]
    assert "coalesce(max(size(company_rows)), 0) AS max_row_count" in captured["cypher"]
    assert "WHERE max_row_count > 0" in captured["cypher"]
    assert "UNWIND range(0, max_row_count - 1)" in captured["cypher"]


def test_company_scoped_relation_rows_apply_global_company_filter(monkeypatch):
    captured = {}

    def fake_neo4j_query(cypher, params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [], None

    graph_app.relation_fact_rows.clear()
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    rows, error = graph_app.relation_fact_rows("", 25, "MSFT")

    assert rows == []
    assert error is None
    assert captured["params"]["company_ticker"] == "MSFT"
    assert "WITH fact, src, dst, source_concepts, target_concepts, matched_terms, chunk, source_doc, company" in captured["cypher"]
    assert "WHERE $company_ticker = '' OR company.ticker = $company_ticker" in captured["cypher"]


def test_connected_node_summary_rows_uses_two_high_degree_nodes_per_company(monkeypatch):
    captured = {}

    def fake_neo4j_query(cypher, params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [], None

    graph_app.connected_node_summary_rows.clear()
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    rows, error = connected_node_summary_rows(
        "AI demand",
        limit=15,
        company_ticker="NVDA",
        nodes_per_company=2,
        chunks_per_node=1,
    )

    assert rows == []
    assert error is None
    assert captured["params"] == {
        "terms": ["ai", "demand", "ai demand"],
        "limit": 15,
        "company_ticker": "NVDA",
        "nodes_per_company": 2,
        "chunks_per_node": 1,
    }
    assert "UNWIND [src, dst] AS focus_node" in captured["cypher"]
    assert "count(DISTINCT fact) AS node_degree" in captured["cypher"]
    assert "WITH company," in captured["cypher"]
    assert "collect(node_summary)[0..$nodes_per_company] AS top_nodes" in captured["cypher"]
    assert "node_summary.rows[0..$chunks_per_node] AS selected_rows" in captured["cypher"]
    assert "coalesce(focus_node.entity_type, '') <> 'Company'" in captured["cypher"]
    assert "company.name AS focus_company" in captured["cypher"]
    assert "LIMIT $limit" in captured["cypher"]


def test_ontology_graph_payload_accepts_company_scope(monkeypatch):
    calls = []

    def fake_ontology_rows(search, limit, company_ticker=""):
        calls.append((search, limit, company_ticker))
        return [
            {
                "fact_id": "schema-1",
                "source_id": "concept-ai-demand",
                "source": "AI Workload Demand",
                "source_type": "OntologyConcept",
                "relation": "IS_A",
                "relation_layer": "ontology_schema",
                "target_id": "concept-growth-demand",
                "target": "Growth / Demand Driver",
                "target_type": "OntologyConcept",
            }
        ], None

    graph_app.ontology_graph_payload.clear()
    monkeypatch.setattr(graph_app, "ontology_relation_rows", fake_ontology_rows)

    payload, error = graph_app.ontology_graph_payload("AI", 10, "MSFT")

    assert error is None
    assert calls == [("AI", 10, "MSFT")]
    assert payload["edges"][0]["label"] == "IS_A"


def test_graph_payload_balances_all_companies_but_keeps_company_scope(monkeypatch):
    calls = []

    def fake_balanced_rows(search, limit):
        calls.append(("balanced", search, limit))
        return [
            {
                "fact_id": "f1",
                "company": "Amazon",
                "source_id": "amzn-ai",
                "source": "AI Demand",
                "source_type": "Theme",
                "relation": "DRIVES",
                "target_id": "amzn-capex",
                "target": "CapEx",
                "target_type": "Metric",
            }
        ], None

    def fake_scoped_rows(search, limit, company_ticker=""):
        calls.append(("scoped", search, limit, company_ticker))
        return [
            {
                "fact_id": "f2",
                "company": "NVIDIA",
                "ticker": company_ticker,
                "source_id": "nvda-ai",
                "source": "AI Demand",
                "source_type": "Theme",
                "relation": "DRIVES",
                "target_id": "nvda-revenue",
                "target": "Revenue",
                "target_type": "Metric",
            }
        ], None

    graph_app.graph_payload.clear()
    monkeypatch.setattr(graph_app, "balanced_relation_fact_rows", fake_balanced_rows)
    monkeypatch.setattr(graph_app, "relation_fact_rows", fake_scoped_rows)

    all_payload, all_error = graph_app.graph_payload("AI all", 10)
    scoped_payload, scoped_error = graph_app.graph_payload("AI scoped", 10, "NVDA")

    assert all_error is None
    assert scoped_error is None
    assert ("balanced", "AI all", 10) in calls
    assert ("scoped", "AI scoped", 10, "NVDA") in calls
    assert not any(node["id"] == "company:NVDA" for node in all_payload["nodes"])
    assert any(node["id"] == "company:NVDA" for node in scoped_payload["nodes"])


def test_interactive_graph_html_exposes_zoom_pan_and_drag_controls():
    payload = {
        "nodes": [
            {"id": "theme-ai", "label": "AI demand", "type": "Theme"},
            {"id": "metric-capex", "label": "Infrastructure capex", "type": "Metric"},
        ],
        "edges": [{"source": "theme-ai", "target": "metric-capex", "label": "DRIVES"}],
    }

    html = interactive_graph_html(payload, height=500)

    assert "wheel=zoom" in html
    assert "drag background=pan" in html
    assert "drag node=move" in html
    assert "vis-network" in html
    assert "new vis.Network" in html
    assert "network.fit" in html
    assert "click node=chunks" in html
    assert "details-title" in html
    assert "showNodeDetails" in html
    assert "activeDetailsNode === nodeId" in html
    assert "doubleClick" not in html
    assert "window.open" not in html


def test_interactive_graph_html_can_render_hierarchical_ontology_layout():
    payload = {
        "nodes": [
            {"id": "concept-cloud", "label": "Cloud Platform Segment", "type": "OntologyConcept"},
            {"id": "concept-segment", "label": "Business Segment", "type": "OntologyConcept"},
        ],
        "edges": [
            {
                "source": "concept-cloud",
                "target": "concept-segment",
                "label": "IS_A",
                "layer": "ontology_schema",
            }
        ],
    }

    html = interactive_graph_html(payload, height=500, hierarchical=True)

    assert '"shape": "box"' in html
    assert '"hierarchical": {"enabled": true' in html
    assert '"direction": "DU"' in html
    assert '"physics": false' not in html
    assert '"enabled": false' in html
    assert "stabilizationIterationsDone" not in html


def test_hierarchical_ontology_layout_uses_only_taxonomy_edges():
    payload = {
        "nodes": [
            {"id": "concept-demand", "label": "AI Workload Demand", "type": "OntologyConcept"},
            {"id": "concept-growth", "label": "Growth / Demand Driver", "type": "OntologyConcept"},
            {"id": "concept-capex", "label": "Infrastructure CapEx", "type": "OntologyConcept"},
        ],
        "edges": [
            {
                "source": "concept-demand",
                "target": "concept-growth",
                "label": "IS_A",
                "layer": "ontology_schema",
            },
            {
                "source": "concept-demand",
                "target": "concept-capex",
                "label": "DRIVES_SCHEMA",
                "layer": "ontology_schema",
            },
        ],
    }

    html = interactive_graph_html(payload, height=500, hierarchical=True)

    assert '"label": "IS_A"' in html
    assert "DRIVES_SCHEMA" not in html


def test_interactive_graph_html_can_sync_selected_ontology_node_to_query_param():
    payload = {
        "nodes": [
            {"id": "concept-cloud", "label": "Cloud Platform Segment", "type": "OntologyConcept"},
            {"id": "concept-segment", "label": "Business Segment", "type": "OntologyConcept"},
        ],
        "edges": [
            {
                "source": "concept-cloud",
                "target": "concept-segment",
                "label": "IS_A",
                "layer": "ontology_schema",
            }
        ],
    }

    html = interactive_graph_html(
        payload,
        height=500,
        hierarchical=True,
        selected_node_id="concept-cloud",
        sync_ontology_selection=True,
        open_selected_details=True,
    )

    assert 'const selectedNodeId = "concept-cloud"' in html
    assert "const syncOntologySelection = true" in html
    assert "const openSelectedDetails = true" in html
    assert "const preservedViewport" in html
    assert "window.parent.postMessage" in html
    assert "network.getScale()" in html
    assert "network.getViewPosition()" in html
    assert "network.selectNodes([selectedNodeId])" in html
    assert "network.focus(selectedNodeId" not in html
    assert "network.moveTo" in html
    assert "showNodeDetails(selectedNodeId)" in html


def test_interactive_graph_html_keeps_metric_values_out_of_node_labels():
    payload = {
        "nodes": [
            {
                "id": "metric-backlog",
                "label": "Cloud backlog",
                "type": "MetricValue",
                "properties": {"value": "$460B+", "context": "future visibility"},
            }
        ],
        "edges": [],
    }

    html = interactive_graph_html(payload, height=500)

    assert '"label": "Cloud backlog"' in html
    assert '"label": "Cloud backlog\\n$460B+"' not in html
    assert "value: ${nodeProps.value}" in html


def test_interactive_graph_html_labels_ontology_schema_edges():
    payload = {
        "nodes": [
            {"id": "concept-cloud", "label": "Cloud Platform Segment", "type": "OntologyConcept"},
            {"id": "concept-segment", "label": "Business Segment", "type": "OntologyConcept"},
        ],
        "edges": [
            {
                "source": "concept-cloud",
                "target": "concept-segment",
                "label": "IS_A",
                "layer": "ontology_schema",
                "evidence": "Cloud platforms are business segments.",
            }
        ],
    }

    html = interactive_graph_html(payload, height=500)

    assert '"label": "IS_A"' in html
    assert '"layer": "ontology_schema"' in html
    assert "Cloud platforms are business segments." in html


def test_add_company_context_node_adds_company_hub_edges():
    payload = {
        "nodes": [
            {"id": "entity-ai", "label": "AI demand", "type": "Theme"},
            {"id": "entity-capex", "label": "CapEx", "type": "Metric"},
        ],
        "edges": [{"source": "entity-ai", "target": "entity-capex", "label": "DRIVES"}],
    }
    rows = [
        {
            "company": "NVIDIA",
            "ticker": "NVDA",
            "source_id": "entity-ai",
            "target_id": "entity-capex",
        }
    ]

    scoped = add_company_context_node(payload, rows, "NVDA")

    assert {"id": "company:NVDA", "label": "NVIDIA", "type": "Company", "properties": {"ticker": "NVDA", "context": "Selected company graph scope"}} in scoped["nodes"]
    assert any(edge["source"] == "company:NVDA" and edge["label"] == "HAS_CONTEXT" for edge in scoped["edges"])


def test_interactive_graph_html_can_show_full_chunk_text_in_details():
    payload = {
        "nodes": [
            {"id": "src", "label": "AI demand", "type": "Theme"},
            {"id": "dst", "label": "CapEx", "type": "MetricValue"},
        ],
        "edges": [
            {
                "source": "src",
                "target": "dst",
                "label": "DRIVES",
                "evidence": "short evidence",
                "chunk_preview": "short preview",
                "chunk_text": "Full referenced chunk text with management commentary.",
            }
        ],
    }

    html = interactive_graph_html(payload, height=500)

    assert '"chunk_text": "Full referenced chunk text with management commentary."' in html
    assert "edge.chunk_text || edge.evidence || edge.chunk_preview" in html
    assert "edge.chunk_id" not in html
    assert "white-space:pre-wrap" in html


def test_interactive_graph_html_hides_confidence_from_node_details():
    payload = {
        "nodes": [
            {"id": "src", "label": "AI demand", "type": "Theme"},
            {"id": "dst", "label": "CapEx", "type": "MetricValue"},
        ],
        "edges": [
            {
                "source": "src",
                "target": "dst",
                "label": "DRIVES",
                "confidence": 0.91,
                "evidence": "AI demand drives capex.",
            }
        ],
    }

    html = interactive_graph_html(payload, height=500)

    assert "edge.confidence.toFixed" not in html
    assert "<span class=\"pill\">conf" not in html


def test_app_css_wraps_referenced_chunk_text_to_viewport():
    assert ".cf-chunk-text" in APP_CSS
    assert "white-space: pre-wrap" in APP_CSS
    assert "overflow-wrap: anywhere" in APP_CSS
    assert "word-break: break-word" in APP_CSS


def test_edge_table_rows_maps_node_labels():
    payload = {
        "nodes": [
            {"id": "src", "label": "pricing power", "type": "Theme"},
            {"id": "dst", "label": "gross margin", "type": "Metric"},
        ],
        "edges": [{"source": "src", "target": "dst", "label": "SUPPORTS", "company": "ExampleCo"}],
    }

    assert edge_table_rows(payload) == [
        {
            "source": "pricing power",
            "edge": "SUPPORTS",
            "target": "gross margin",
            "company": "ExampleCo",
            "ticker": None,
            "confidence": None,
            "document": None,
            "evidence": None,
        }
    ]


def test_edge_table_rows_normalizes_list_values_for_streamlit_arrow():
    payload = {
        "nodes": [
            {"id": "src", "label": "AI Demand", "type": "OntologyConcept"},
            {"id": "dst", "label": "Infrastructure CapEx", "type": "OntologyConcept"},
        ],
        "edges": [
            {
                "source": "src",
                "target": "dst",
                "label": "DRIVES",
                "company": ["Alphabet", "Microsoft"],
                "document": ["alphabet-doc", "microsoft-doc"],
            },
            {
                "source": "src",
                "target": "dst",
                "label": "IS_A",
                "layer": "ontology_schema",
                "company": [],
                "document": [],
            },
        ],
    }

    rows = edge_table_rows(payload)

    assert rows[0]["company"] == "Alphabet, Microsoft"
    assert rows[0]["document"] == "alphabet-doc, microsoft-doc"
    assert rows[1]["company"] == ""
    assert rows[1]["document"] == ""


def test_node_select_options_and_truncate_are_stable():
    rows = [
        {"node_id": "n1", "name": "AI infrastructure demand", "entity_type": "Theme"},
        {"name": "missing id", "entity_type": "Risk"},
    ]

    assert node_select_options(rows) == {"AI infrastructure demand (Theme)": "n1"}
    assert truncate("a  b\nc", 10) == "a b c"
    assert truncate("x" * 70, 10).startswith("xxxxxxxxx")
    assert len(truncate("x" * 70, 10)) == 10


def test_ontology_concept_select_options_include_type_and_mapping_count():
    options = ontology_concept_select_options(
        [
            {
                "concept_id": "concept-ai-demand",
                "name": "AI Workload Demand",
                "concept_type": "Theme",
                "mapped_entities": 15,
            }
        ]
    )

    assert options == {"AI Workload Demand (Theme) · 15 mapped": "concept-ai-demand"}


def test_unique_chunk_rows_deduplicates_by_chunk_id_before_summary():
    rows = [
        {
            "chunk_id": "chunk-1",
            "company": "NVIDIA",
            "document": "nvda-q2",
            "chunk_text": "AI infrastructure demand increased.",
            "relation_types": ["DRIVES"],
            "matched_entities": ["AI infrastructure demand"],
            "relation_count": 2,
        },
        {
            "chunk_id": "chunk-1",
            "company": "NVIDIA",
            "document": "nvda-q2",
            "chunk_text": "AI infrastructure demand increased.",
            "relation_types": ["INCREASES"],
            "matched_entities": ["Revenue"],
            "relation_count": 1,
        },
        {
            "chunk_id": "chunk-2",
            "company": "AMD",
            "document": "amd-q2",
            "chunk_text": "Data center demand remained strong.",
            "relation_types": ["SUPPORTS"],
            "matched_entities": ["Data center demand"],
            "relation_count": 1,
        },
    ]

    chunks = unique_chunk_rows(rows)

    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-1", "chunk-2"]
    assert chunks[0]["chunk_text"] == "AI infrastructure demand increased."


def test_ontology_summary_prompt_uses_each_chunk_once():
    prompt = build_ontology_chunk_summary_prompt(
        {"name": "AI Infrastructure Demand", "concept_type": "Demand"},
        [
            {"chunk_id": "chunk-1", "company": "NVIDIA", "document": "nvda-q2", "chunk_text": "same"},
            {"chunk_id": "chunk-1", "company": "NVIDIA", "document": "nvda-q2", "chunk_text": "same duplicate"},
        ],
    )

    assert prompt.count("chunk_id=chunk-1") == 1
    assert "Each chunk_id is included at most once" in prompt


def test_graph_chunk_summary_prompt_uses_referenced_chunks_once_with_paths():
    prompt = build_graph_chunk_summary_prompt(
        context_title="Ask: What does AI demand affect?",
        context_description="Answer using matched chunks.",
        rows=[
            {
                "company": "Alphabet",
                "document": "alphabet-q1",
                "chunk_id": "chunk-1",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "CapEx",
                "evidence": "AI demand drove technical infrastructure investment.",
                "chunk_text": "Management said AI demand drove technical infrastructure investment.",
            },
            {
                "company": "Alphabet",
                "document": "alphabet-q1",
                "chunk_id": "chunk-1",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "CapEx",
                "chunk_text": "duplicate should be ignored",
            },
        ],
    )

    assert "Context: Ask: What does AI demand affect?" in prompt
    assert "AI demand --DRIVES--> CapEx" in prompt
    assert prompt.count("Chunk 1") == 1
    assert "duplicate should be ignored" not in prompt
    assert "Each source chunk is included at most once" in prompt


def test_connected_node_summary_prompt_uses_top_nodes_and_15_chunk_context():
    prompt = build_connected_node_summary_prompt(
        search="AI",
        company_ticker="NVDA",
        graph_view="Company entities",
        limit=15,
        rows=[
            {
                "focus_node_id": "node-ai",
                "focus_node": "AI demand",
                "focus_node_type": "Theme",
                "node_degree": 12,
                "company_count": 3,
                "evidence_count": 9,
                "focus_company": "NVIDIA",
                "focus_ticker": "NVDA",
                "company": "NVIDIA",
                "document": "nvda-q2",
                "chunk_id": "chunk-1",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "Data center revenue",
                "evidence": "AI demand drove data center revenue.",
                "chunk_text": "Management said AI demand drove data center revenue.",
            },
            {
                "focus_node_id": "node-ai",
                "focus_node": "AI demand",
                "focus_node_type": "Theme",
                "node_degree": 12,
                "company_count": 3,
                "evidence_count": 9,
                "focus_company": "NVIDIA",
                "focus_ticker": "NVDA",
                "company": "NVIDIA",
                "document": "nvda-q2",
                "chunk_id": "chunk-1",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "Data center revenue",
                "chunk_text": "duplicate should be ignored",
            },
        ],
    )

    assert "Graph view: Company entities" in prompt
    assert "Company scope: NVDA" in prompt
    assert "Graph search: AI" in prompt
    assert "NVIDIA: AI demand (Theme; degree=12; chunks=9)" in prompt
    assert "each company's two highest-degree entity nodes" in prompt
    assert "Focus the visible answer on key points and company differences" in prompt
    assert "AI demand --DRIVES--> Data center revenue" in prompt
    assert prompt.count("Chunk 1") == 1
    assert "duplicate should be ignored" not in prompt


def test_query_terms_extracts_question_keywords():
    assert "ai demand" in query_terms("What does AI demand affect?")
    assert "backlog" in query_terms("How does Cloud backlog convert to revenue?")


def test_ask_question_presets_cover_common_graph_queries():
    assert "What does AI demand affect?" in ASK_QUESTION_PRESETS
    assert "How does AI demand affect capex across companies?" in ASK_QUESTION_PRESETS
    assert "What pressures operating margin?" in ASK_QUESTION_PRESETS
    assert len(ASK_QUESTION_PRESETS) >= 5


def test_text2cypher_prompt_includes_schema_and_read_only_rules():
    prompt = build_text2cypher_prompt("Which companies connect AI demand to capex?")

    assert "User question:" in prompt
    assert "RelationFact" in prompt
    assert "OntologyConcept" in prompt
    assert "read-only Cypher" in prompt
    assert "Do not use procedures or CALL" in prompt
    assert "Do not use range()" in prompt
    assert "Include a LIMIT" in prompt


def test_validate_text2cypher_accepts_and_caps_read_only_query():
    cypher, warnings = validate_text2cypher(
        """
        MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity)
        RETURN src.name AS source
        LIMIT 500
        """
    )

    assert cypher.endswith("LIMIT 50")
    assert warnings == ["LIMIT was capped from 500 to 50."]


def test_validate_text2cypher_rejects_write_or_unbounded_query():
    try:
        validate_text2cypher("MATCH (n) DELETE n RETURN count(n) LIMIT 10")
    except ValueError as exc:
        assert "forbidden" in str(exc)
    else:
        raise AssertionError("write query should have been rejected")

    try:
        validate_text2cypher("MATCH (n) RETURN n")
    except ValueError as exc:
        assert "LIMIT" in str(exc)
    else:
        raise AssertionError("unbounded query should have been rejected")

    try:
        validate_text2cypher("MATCH (n) WITH collect(n) AS rows UNWIND range(0, size(rows) - 1) AS i RETURN rows[i] LIMIT 10")
    except ValueError as exc:
        assert "range()" in str(exc)
    else:
        raise AssertionError("range query should have been rejected")


def test_run_text2cypher_question_executes_valid_generated_query(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def generate_json(self, *args, **kwargs):
            return {
                "cypher": "MATCH (c:Company) RETURN c.ticker AS ticker LIMIT 5",
                "rationale": "List companies.",
                "expected_columns": ["ticker"],
            }

    captured = {}

    def fake_neo4j_query(cypher, params=None):
        captured["cypher"] = cypher
        captured["params"] = params
        return [{"ticker": "MSFT"}], None

    monkeypatch.setattr(graph_app, "GeminiClient", FakeClient)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_text2cypher_question("Which companies are loaded?")

    assert error is None
    assert captured["cypher"] == "MATCH (c:Company) RETURN c.ticker AS ticker LIMIT 5"
    assert result["rows"] == [{"ticker": "MSFT"}]
    assert result["rationale"] == "List companies."


def test_answer_question_from_relations_summarizes_core_graph_signals():
    answer = answer_question_from_relations(
        "What does AI demand affect?",
        [
            {
                "company": "Alphabet",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "Cloud revenue growth",
                "target_type": "MetricValue",
                "target_properties": {"value": "+63%", "context": "exceeding $20 billion"},
                "evidence": "Cloud accelerated due to strong demand for AI products.",
            },
            {
                "company": "Alphabet",
                "source": "Depreciation expense",
                "relation": "PRESSURES",
                "target": "Operating margin",
                "evidence": "Depreciation expense pressures operating margin.",
            },
        ],
    )

    assert "Found 2 graph relation" in answer["summary"]
    assert "AI demand --DRIVES--> Cloud revenue growth (+63%) [exceeding $20 billion]" in answer["bull_case"]
    assert "Depreciation expense --PRESSURES--> Operating margin" in answer["risk_case"]
    assert "Alphabet" in answer["basis"]


def test_answer_question_from_relations_surfaces_properties_and_ontology():
    answer = answer_question_from_relations(
        "How does AI demand affect capex across companies?",
        [
            {
                "company": "Alphabet",
                "source": "AI demand",
                "source_type": "Theme",
                "source_concepts": ["AI Demand"],
                "relation": "DRIVES",
                "target": "Technical infrastructure capex",
                "target_type": "MetricValue",
                "target_properties": {
                    "value": "$35.7B",
                    "context": "quarterly technical infrastructure spend",
                },
                "target_concepts": ["Infrastructure CapEx"],
                "evidence": "Capex was driven by technical infrastructure investment for AI.",
            },
            {
                "company": "Microsoft",
                "source": "AI demand",
                "source_type": "Theme",
                "source_concepts": ["AI Demand"],
                "relation": "DRIVES",
                "target": "Cloud and AI capex",
                "target_type": "MetricValue",
                "target_properties": {
                    "value": "$21.4B",
                    "context": "cloud and AI infrastructure",
                },
                "target_concepts": ["Infrastructure CapEx"],
                "evidence": "Cloud and AI demand required higher infrastructure investment.",
            },
        ],
    )

    assert "Concepts: AI Demand, Infrastructure CapEx" in answer["property_insights"]
    assert "Technical infrastructure capex ($35.7B)" in answer["property_insights"]
    assert "Cloud and AI capex ($21.4B)" in answer["property_insights"]
    assert "Alphabet:" in answer["property_insights"]
    assert "Microsoft:" in answer["property_insights"]
    assert "value/context properties" in answer["basis"]


def test_referenced_chunk_rows_preserves_full_chunk_text_and_dedupes():
    chunks = referenced_chunk_rows(
        [
            {
                "company": "Alphabet",
                "document": "alphabet-q1",
                "source_url": "https://example.com/transcript.pdf",
                "chunk_id": "chunk-001",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "CapEx",
                "evidence": "short extracted evidence",
                "chunk_preview": "preview only",
                "chunk_text": "Full referenced chunk text that should be visible to the user.",
            },
            {
                "company": "Alphabet",
                "chunk_id": "chunk-001",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "CapEx",
                "chunk_text": "duplicate should be ignored",
            },
            {
                "company": "Microsoft",
                "source": "Azure AI",
                "relation": "INCREASES",
                "target": "Revenue growth",
                "evidence": "fallback evidence without stored chunk text",
            },
        ],
        limit=8,
    )

    assert len(chunks) == 2
    assert "chunk_id" not in chunks[0]
    assert chunks[0]["chunk_text"] == "Full referenced chunk text that should be visible to the user."
    assert chunks[0]["evidence"] == "short extracted evidence"
    assert "source_url" not in chunks[0]
    assert chunks[1]["chunk_text"] == "fallback evidence without stored chunk text"


def test_key_node_explanation_uses_context_rows():
    explanation = key_node_explanation(
        {"name": "AI demand"},
        [
            {
                "company": "Alphabet",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "Cloud revenue growth",
                "target_type": "MetricValue",
                "target_properties": {"value": "+63%", "context": "exceeding $20 billion"},
                "evidence": "Cloud accelerated due to strong demand for AI products.",
            }
        ],
    )

    assert "AI demand is connected" in explanation["why_it_matters"]
    assert "Cloud revenue growth (+63%) [exceeding $20 billion]" in explanation["why_it_matters"]
    assert "AI demand --DRIVES--> Cloud revenue growth (+63%)" in explanation["main_connections"]
    assert "Cloud accelerated" in explanation["evidence"]


def test_key_node_explanation_uses_node_properties_and_ontology():
    explanation = key_node_explanation(
        {
            "name": "Technical infrastructure capex",
            "properties": {
                "value": "$35.7B",
                "context": "quarterly technical infrastructure spend",
            },
            "concepts": ["Infrastructure CapEx"],
        },
        [
            {
                "company": "Alphabet",
                "node_name": "Technical infrastructure capex",
                "node_properties": {
                    "value": "$35.7B",
                    "context": "quarterly technical infrastructure spend",
                },
                "node_concepts": ["Infrastructure CapEx"],
                "source": "AI demand",
                "source_type": "Theme",
                "source_concepts": ["AI Demand"],
                "relation": "DRIVES",
                "target": "Technical infrastructure capex",
                "target_type": "MetricValue",
                "target_properties": {
                    "value": "$35.7B",
                    "context": "quarterly technical infrastructure spend",
                },
                "target_concepts": ["Infrastructure CapEx"],
                "evidence": "Capex was driven by technical infrastructure investment for AI.",
            }
        ],
    )

    assert "Ontology concepts: Infrastructure CapEx" in explanation["why_it_matters"]
    assert "Node properties: value=$35.7B" in explanation["why_it_matters"]
    assert "quarterly technical infrastructure spend" in explanation["why_it_matters"]
    assert "Key metric/property values: Technical infrastructure capex ($35.7B)" in explanation["why_it_matters"]
    assert "[concepts: AI Demand -> Infrastructure CapEx]" in explanation["main_connections"]
