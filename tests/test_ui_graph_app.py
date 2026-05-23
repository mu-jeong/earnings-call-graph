from pathlib import Path

from earnings_call_graph.ui.graph_app import (
    APP_CSS,
    APP_TAB_LABELS,
    ASK_QUESTION_PRESETS,
    add_company_context_node,
    answer_question_from_relations,
    ask_relation_cards_html,
    ask_relation_card_items,
    build_aura_text2cypher_execution_repair_prompt,
    build_aura_text2cypher_prompt,
    build_aura_text2cypher_diversity_repair_prompt,
    build_aura_text2cypher_repair_prompt,
    build_aura_tool_router_prompt,
    aura_answer_rows_for_prompt,
    aura_company_filter_terms,
    aura_tool_limit,
    aura_tool_option_labels,
    aura_tool_parameters,
    build_aura_tool_answer_prompt,
    build_local_aura_tool_answer,
    aura_text2cypher_fallback,
    build_connected_node_summary_prompt,
    build_graph_chunk_summary_prompt,
    build_ontology_chunk_summary_prompt,
    build_text2cypher_prompt,
    connected_node_summary_rows,
    edge_table_rows,
    filter_payload_by_min_node_degree,
    frequent_entities_markdown,
    frequent_entity_rows,
    friendly_agent_error,
    graph_counts,
    interactive_graph_html,
    is_cypher_execution_error,
    is_query_timeout_error,
    key_node_explanation,
    aura_agent_progress_messages,
    loaded_company_universe_rows,
    node_select_options,
    ontology_concept_select_options,
    graph_result_count,
    query_terms,
    referenced_chunk_rows,
    result_limit_slider_config,
    result_limit_slider_enabled,
    company_balanced_rows,
    distinct_company_keys,
    deterministic_aura_tool_route,
    strip_evidence_gap_sections,
    strip_aura_redundant_signal_columns,
    summarize_aura_tool_output,
    truncate,
    unique_chunk_rows,
    validate_aura_tool_route,
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


def test_loaded_company_universe_rows_uses_loaded_company_inventory_query(monkeypatch):
    captured = {}

    def fake_neo4j_query(cypher, params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [], None

    graph_app.loaded_company_universe_rows.clear()
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    rows, error = loaded_company_universe_rows(25)

    assert rows == []
    assert error is None
    assert captured["params"] == {"limit": 25}
    assert "MATCH (company:Company)" in captured["cypher"]
    assert "count(DISTINCT source_doc) AS source_documents" in captured["cypher"]
    assert "count(DISTINCT fact) AS relation_facts" in captured["cypher"]


def test_frequent_entity_rows_ranks_mentions_with_template_query(monkeypatch):
    captured = {}

    def fake_neo4j_query(cypher, params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [], None

    graph_app.frequent_entity_rows.clear()
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    rows, error = frequent_entity_rows(20)

    assert rows == []
    assert error is None
    assert captured["params"] == {"limit": 20}
    assert "MATCH (entity:Entity)" in captured["cypher"]
    assert "direct_chunk_mentions + relation_mentions AS mention_count" in captured["cypher"]
    assert "ORDER BY mention_count DESC" in captured["cypher"]


def test_aura_tool_metadata_exposes_web_testable_tool_names():
    labels = aura_tool_option_labels()

    assert labels == [
        "loaded_company_universe",
        "frequent_entities",
        "ai_positive_demand_by_company",
        "ai_risks_constraints_by_company",
        "company_ai_deep_dive",
        "product_category_evidence_map",
    ]
    assert aura_tool_parameters("loaded_company_universe", question="ignored", limit=10) == {
        "limit": 10,
        "tool_type": "cypher_template",
    }
    assert aura_tool_parameters("frequent_entities", question="ignored", limit=10) == {
        "limit": 10,
        "tool_type": "cypher_template",
    }
    assert aura_tool_parameters("company_ai_deep_dive", question="What affects AI?", limit=30) == {
        "limit": 30,
        "tool_type": "text2cypher",
        "question": "What affects AI?",
    }


def test_aura_tool_limit_caps_text2cypher_rows_but_not_template_rows():
    assert aura_tool_limit("text2cypher", max_company_rows=999, max_relation_rows=2327) == 250
    assert aura_tool_limit("text2cypher", max_company_rows=999, max_relation_rows=30) == 30
    assert aura_tool_limit("cypher_template", max_company_rows=2327, max_relation_rows=9999) == 2327


def test_app_tab_labels_place_aura_next_to_ask():
    assert APP_TAB_LABELS == ["Graph", "Ask", "Ask (Aura)", "Key Nodes"]


def test_run_app_copy_keeps_text2cypher_out_of_ask_tab():
    source = Path(__file__).parents[1] / "src" / "earnings_call_graph" / "ui" / "graph_app.py"
    text = source.read_text(encoding="utf-8")

    assert "Experimental Text2Cypher" not in text
    assert "Generate and run Text2Cypher" not in text
    assert "Use Ask (Aura) for routed Text2Cypher tool workflows." in text


def test_aura_tab_exposes_debug_log_without_manual_tool_override():
    source = Path(__file__).parents[1] / "src" / "earnings_call_graph" / "ui" / "graph_app.py"
    text = source.read_text(encoding="utf-8")

    assert 'st.expander("Aura debug log"' in text
    assert "debug_placeholder = st.empty()" not in text
    assert "st.status(" not in text
    assert "st.container(border=True)" in text
    assert "render_debug_log(expanded=True)" in text
    assert "Stage-by-stage local logs" in text
    assert "question_received" in text
    assert "router_start" in text
    assert "tool_result" in text
    assert "answer_writer_start" in text


def test_aura_tab_does_not_expose_manual_tool_override():
    source = Path(__file__).parents[1] / "src" / "earnings_call_graph" / "ui" / "graph_app.py"
    text = source.read_text(encoding="utf-8")

    assert "Override tool selection for debugging" not in text
    assert "Tool override" not in text
    assert "aura_tool_manual_override" not in text


def test_cypher_uses_property_maps_for_optional_entity_properties():
    source = Path(__file__).parents[1] / "src" / "earnings_call_graph" / "ui" / "graph_app.py"
    text = source.read_text(encoding="utf-8")

    assert "entity.value" not in text
    assert "entity.context" not in text
    assert "src.value" not in text
    assert "src.context" not in text
    assert "dst.value" not in text
    assert "dst.context" not in text
    assert "properties(entity)['value']" in text


def test_cypher_call_subqueries_use_variable_scope_clause():
    source = Path(__file__).parents[1] / "src" / "earnings_call_graph" / "ui" / "graph_app.py"
    text = source.read_text(encoding="utf-8")

    assert "\n        CALL {\n" not in text
    assert "\n          CALL {\n" not in text
    assert "WITH $labels AS allowed_labels" in text
    assert "CALL (allowed_labels) {" in text
    assert "CALL (terms, company_ticker) {" in text
    assert "CALL (concept) {" in text


def test_aura_text2cypher_prompt_is_tool_specific():
    prompt = build_aura_text2cypher_prompt(
        "company_ai_deep_dive",
        "For NVIDIA, what does the graph show about AI demand and Blackwell?",
        max_limit=2327,
    )

    assert "Aura tool:" in prompt
    assert "company_ai_deep_dive" in prompt
    assert "Find source-backed graph paths for the company named in the question" in prompt
    assert "no larger than 2327" in prompt
    assert "Text2Cypher" not in prompt
    assert "Do not use procedures or CALL" in prompt


def test_aura_text2cypher_prompt_requires_complete_query():
    prompt = build_aura_text2cypher_prompt(
        "ai_positive_demand_by_company",
        "What positive AI demand signals are loaded?",
    )

    assert "complete executable query" in prompt
    assert "containing MATCH or OPTIONAL MATCH, RETURN, and LIMIT" in prompt
    assert "partial query fragment" in prompt
    assert "company-balanced chunks" in prompt
    assert "referenced_chunk" in prompt
    assert "Apply LIMIT only after this company balancing" in prompt


def test_aura_text2cypher_repair_prompt_includes_validation_failure():
    prompt = build_aura_text2cypher_repair_prompt(
        "product_category_evidence_map",
        "Map AI accelerator evidence.",
        "MATCH (fact:RelationFact) LIMIT 10",
        "Generated Cypher must include RETURN.",
        max_limit=123,
    )

    assert "failed validation" in prompt
    assert "Generated Cypher must include RETURN." in prompt
    assert "MATCH (fact:RelationFact) LIMIT 10" in prompt
    assert "Include RETURN" in prompt
    assert "no larger than 123" in prompt


def test_validate_text2cypher_normalizes_reversed_list_comprehension():
    cypher, warnings = validate_text2cypher(
        "MATCH (fact:RelationFact) WITH [sc.name | sc IN sourceConcepts] AS source_concepts RETURN source_concepts LIMIT 10"
    )

    assert "[sc IN sourceConcepts | sc.name]" in cypher
    assert "Normalized Cypher list-comprehension syntax." in warnings


def test_aura_text2cypher_execution_repair_prompt_mentions_neo4j_syntax():
    prompt = build_aura_text2cypher_execution_repair_prompt(
        "ai_positive_demand_by_company",
        "Across the graph, what positive AI demand signals are companies reporting?",
        "MATCH (n) WITH [sc.name | sc IN sourceConcepts] AS names RETURN names LIMIT 10",
        "{neo4j_code: Neo.ClientError.Statement.SyntaxError} Invalid input '|'",
        max_limit=100,
    )

    assert "failed when Neo4j executed it" in prompt
    assert "Invalid input '|'" in prompt
    assert "[item IN list | item.property]" in prompt
    assert "never `[item.property | item IN list]`" in prompt
    assert "no larger than 100" in prompt


def test_aura_text2cypher_diversity_repair_prompt_requests_company_balancing():
    prompt = build_aura_text2cypher_diversity_repair_prompt(
        "ai_positive_demand_by_company",
        "Across the graph, what positive AI demand signals are companies reporting?",
        "MATCH (company:Company {ticker: 'CSCO'}) RETURN company.name AS company LIMIT 10",
        ["Cisco"],
        max_limit=100,
    )

    assert "too few companies" in prompt
    assert "Cisco" in prompt
    assert "company-balanced referenced chunks" in prompt
    assert "collect(row)[0..2]" in prompt
    assert "Apply LIMIT no larger than 100 only after company balancing" in prompt


def test_generate_aura_text2cypher_repairs_incomplete_query(monkeypatch):
    class FakeClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def generate_json(self, prompt, *args, **kwargs):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return {
                    "cypher": "MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity) LIMIT 10",
                    "rationale": "Initial incomplete query.",
                    "expected_columns": [],
                }
            return {
                "cypher": "MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity) RETURN src.name AS source LIMIT 10",
                "rationale": "Repaired query.",
                "expected_columns": ["source"],
            }

    monkeypatch.setattr(graph_app, "GeminiClient", FakeClient)

    result = graph_app.generate_aura_text2cypher(
        "ai_positive_demand_by_company",
        "What positive AI demand signals are loaded?",
        max_limit=10,
    )

    assert result["cypher"] == "MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity) RETURN src.name AS source LIMIT 10"
    assert result["rationale"] == "Repaired query."
    assert any("repaired automatically" in warning for warning in result["warnings"])
    assert len(FakeClient.calls) == 2


def test_aura_text2cypher_fallback_is_complete_positive_demand_query():
    fallback = aura_text2cypher_fallback("ai_positive_demand_by_company", max_limit=77)

    assert fallback is not None
    cypher, warnings = validate_text2cypher(fallback["cypher"], max_limit=77)
    assert "RETURN row.company AS company" in cypher
    assert "row.referenced_chunk AS referenced_chunk" in cypher
    assert "LIMIT 77" in cypher
    assert "collect(row)[0..2]" in cypher
    assert warnings == []


def test_aura_text2cypher_fallback_is_complete_product_category_query():
    fallback = aura_text2cypher_fallback("product_category_evidence_map", max_limit=42)

    assert fallback is not None
    cypher, warnings = validate_text2cypher(fallback["cypher"], max_limit=42)
    assert "RETURN row.company AS company" in cypher
    assert "row.referenced_chunk AS referenced_chunk" in cypher
    assert "ai accelerator" in cypher
    assert "LIMIT 42" in cypher
    assert "collect(row)[0..2]" in cypher
    assert fallback["rationale"] == "Safe fallback query for cross-company AI accelerator product-category evidence chunks."
    assert warnings == []


def test_aura_text2cypher_fallback_is_complete_risk_constraint_query():
    fallback = aura_text2cypher_fallback("ai_risks_constraints_by_company", max_limit=55)

    assert fallback is not None
    cypher, warnings = validate_text2cypher(fallback["cypher"], max_limit=55)
    assert "RETURN row.company AS company" in cypher
    assert "row.referenced_chunk AS referenced_chunk" in cypher
    assert "constraint" in cypher
    assert "pressure" in cypher
    assert "LIMIT 55" in cypher
    assert fallback["rationale"] == "Safe fallback query for cross-company AI infrastructure risk and constraint chunks."
    assert warnings == []


def test_aura_text2cypher_fallback_is_complete_company_deep_dive_query():
    fallback = aura_text2cypher_fallback(
        "company_ai_deep_dive",
        "For NVIDIA, what does the earnings-call graph show about AI demand, Blackwell, and data center revenue growth?",
        max_limit=33,
    )

    assert aura_company_filter_terms("For NVIDIA and NVDA") == ["nvidia", "nvda"]
    assert fallback is not None
    cypher, warnings = validate_text2cypher(fallback["cypher"], max_limit=33)
    assert "company_terms" in cypher
    assert "blackwell" in cypher
    assert "data center revenue" in cypher
    assert "RETURN company.name AS company" in cypher
    assert "LIMIT 25" in cypher
    assert fallback["rationale"] == "Safe fallback query for one-company AI demand, Blackwell, and data-center evidence chunks."
    assert warnings == []


def test_generate_aura_text2cypher_uses_fallback_when_repair_is_incomplete(monkeypatch):
    class FakeClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def generate_json(self, prompt, *args, **kwargs):
            self.calls.append(prompt)
            return {
                "cypher": "MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity) LIMIT 10",
                "rationale": "Still incomplete.",
                "expected_columns": [],
            }

    monkeypatch.setattr(graph_app, "GeminiClient", FakeClient)

    result = graph_app.generate_aura_text2cypher(
        "ai_positive_demand_by_company",
        "Across the loaded earnings-call graph, what positive demand signals are companies reporting for the AI infrastructure industry?",
        max_limit=25,
    )

    assert "RETURN row.company AS company" in result["cypher"]
    assert "LIMIT 25" in result["cypher"]
    assert result["rationale"] == "Safe fallback query for cross-company positive AI infrastructure demand chunks."
    assert any("used a safe fallback query" in warning for warning in result["warnings"])
    assert len(FakeClient.calls) == 2


def test_generate_aura_text2cypher_uses_product_fallback_when_repair_is_incomplete(monkeypatch):
    class FakeClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def generate_json(self, prompt, *args, **kwargs):
            self.calls.append(prompt)
            return {
                "cypher": "MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity) LIMIT 10",
                "rationale": "Still incomplete.",
                "expected_columns": [],
            }

    monkeypatch.setattr(graph_app, "GeminiClient", FakeClient)

    result = graph_app.generate_aura_text2cypher(
        "product_category_evidence_map",
        "Across the loaded graph, summarize company evidence for the AI accelerator product category.",
        max_limit=25,
    )

    assert "RETURN row.company AS company" in result["cypher"]
    assert "ai accelerator" in result["cypher"]
    assert "LIMIT 25" in result["cypher"]
    assert result["rationale"] == "Safe fallback query for cross-company AI accelerator product-category evidence chunks."
    assert any("used a safe fallback query" in warning for warning in result["warnings"])
    assert len(FakeClient.calls) == 2


def test_run_aura_text2cypher_tool_uses_deterministic_product_query_without_llm(monkeypatch):
    calls = []

    def fail_generate(*args, **kwargs):
        raise AssertionError("product category tool should not call Gemini Text2Cypher")

    def fake_neo4j_query(cypher, params=None, timeout_seconds=None):
        calls.append(("query", cypher, timeout_seconds))
        return [
            {"company": "Cisco", "referenced_chunk": "AI infrastructure drives networking growth."},
            {"company": "NVIDIA", "referenced_chunk": "Blackwell accelerator demand is strong."},
        ], None

    monkeypatch.setattr(graph_app, "generate_aura_text2cypher", fail_generate)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_aura_text2cypher_tool(
        "product_category_evidence_map",
        "Across the loaded graph, summarize company evidence for the AI accelerator product category.",
        max_limit=2327,
    )

    assert error is None
    assert result["rationale"] == "Safe fallback query for cross-company AI accelerator product-category evidence chunks."
    assert result["rows"] == [
        {"company": "Cisco", "referenced_chunk": "AI infrastructure drives networking growth."},
        {"company": "NVIDIA", "referenced_chunk": "Blackwell accelerator demand is strong."},
    ]
    assert any("deterministic cross-company query" in warning for warning in result["warnings"])
    assert calls[0][2] == graph_app.AURA_TEXT2CYPHER_QUERY_TIMEOUT_SECONDS


def test_run_aura_text2cypher_tool_repairs_neo4j_syntax_error(monkeypatch):
    calls = []

    def fake_generate(tool_name, question, *, max_limit):
        calls.append(("generate", tool_name, question, max_limit))
        return {"cypher": "invalid", "rationale": "initial", "expected_columns": [], "warnings": []}

    def fake_execution_repair(tool_name, question, cypher, execution_error, *, max_limit):
        calls.append(("execution_repair", tool_name, question, cypher, execution_error, max_limit))
        return {"cypher": "fixed", "rationale": "fixed", "expected_columns": [], "warnings": []}

    def fake_neo4j_query(cypher, params=None, timeout_seconds=None):
        calls.append(("query", cypher))
        if cypher == "invalid":
            return [], "{neo4j_code: Neo.ClientError.Statement.SyntaxError} Invalid input '|'"
        return [{"company": "Cisco", "evidence": "fixed row"}], None

    monkeypatch.setattr(graph_app, "generate_aura_text2cypher", fake_generate)
    monkeypatch.setattr(graph_app, "repair_aura_text2cypher_for_execution_error", fake_execution_repair)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_aura_text2cypher_tool(
        "company_ai_deep_dive",
        "For FictionalCo, what AI demand evidence is available?",
        max_limit=50,
    )

    assert error is None
    assert result["cypher"] == "fixed"
    assert result["rows"] == [{"company": "Cisco", "evidence": "fixed row"}]
    assert any("syntax issue; repaired automatically" in warning for warning in result["warnings"])
    assert calls[1][0] == "query"
    assert calls[2][0] == "execution_repair"


def test_run_aura_text2cypher_tool_uses_deterministic_company_deep_dive_without_llm(monkeypatch):
    calls = []

    def fail_generate(*args, **kwargs):
        raise AssertionError("known company deep-dive tool should not call Gemini Text2Cypher")

    def fake_neo4j_query(cypher, params=None, timeout_seconds=None):
        calls.append(("query", cypher, timeout_seconds))
        return [
            {"company": "NVIDIA", "referenced_chunk": "Blackwell and AI demand drove data center revenue growth."},
        ], None

    monkeypatch.setattr(graph_app, "generate_aura_text2cypher", fail_generate)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_aura_text2cypher_tool(
        "company_ai_deep_dive",
        "For NVIDIA, what does the earnings-call graph show about AI demand, Blackwell, and data center revenue growth?",
        max_limit=2327,
    )

    assert error is None
    assert result["rationale"] == "Safe fallback query for one-company AI demand, Blackwell, and data-center evidence chunks."
    assert result["rows"] == [
        {"company": "NVIDIA", "referenced_chunk": "Blackwell and AI demand drove data center revenue growth."},
    ]
    assert any("deterministic company deep-dive query" in warning for warning in result["warnings"])
    assert all(call[2] == graph_app.AURA_TEXT2CYPHER_QUERY_TIMEOUT_SECONDS for call in calls if call[0] == "query")


def test_run_aura_text2cypher_tool_uses_deterministic_positive_demand_query_without_llm(monkeypatch):
    calls = []

    def fail_generate(*args, **kwargs):
        raise AssertionError("positive demand tool should not call Gemini Text2Cypher")

    def fake_neo4j_query(cypher, params=None, timeout_seconds=None):
        calls.append(("query", cypher, timeout_seconds))
        return [
            {"company": "Cisco", "referenced_chunk": "AI demand is strong"},
            {"company": "NVIDIA", "referenced_chunk": "AI demand is strong"},
        ], None

    monkeypatch.setattr(graph_app, "generate_aura_text2cypher", fail_generate)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_aura_text2cypher_tool(
        "ai_positive_demand_by_company",
        "What positive demand signals are companies reporting for AI infrastructure?",
        max_limit=2327,
    )

    assert error is None
    assert result["rationale"] == "Safe fallback query for cross-company positive AI infrastructure demand chunks."
    assert result["rows"] == [
        {"company": "Cisco", "referenced_chunk": "AI demand is strong"},
        {"company": "NVIDIA", "referenced_chunk": "AI demand is strong"},
    ]
    assert any("deterministic cross-company query" in warning for warning in result["warnings"])
    assert all(call[2] == graph_app.AURA_TEXT2CYPHER_QUERY_TIMEOUT_SECONDS for call in calls if call[0] == "query")
    assert is_query_timeout_error("transaction timed out") is True


def test_run_aura_text2cypher_tool_uses_deterministic_risk_constraint_query_without_llm(monkeypatch):
    calls = []

    def fail_generate(*args, **kwargs):
        raise AssertionError("risk constraints tool should not call Gemini Text2Cypher")

    def fake_neo4j_query(cypher, params=None, timeout_seconds=None):
        calls.append(("query", cypher, timeout_seconds))
        return [
            {"company": "Cisco", "referenced_chunk": "AI infrastructure growth is constrained by power availability."},
            {"company": "NVIDIA", "referenced_chunk": "Supply constraints limit Blackwell ramp timing."},
        ], None

    monkeypatch.setattr(graph_app, "generate_aura_text2cypher", fail_generate)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_aura_text2cypher_tool(
        "ai_risks_constraints_by_company",
        "Across the loaded earnings-call graph, what risks or constraints are companies reporting for AI infrastructure growth?",
        max_limit=2327,
    )

    assert error is None
    assert result["rationale"] == "Safe fallback query for cross-company AI infrastructure risk and constraint chunks."
    assert result["rows"] == [
        {"company": "Cisco", "referenced_chunk": "AI infrastructure growth is constrained by power availability."},
        {"company": "NVIDIA", "referenced_chunk": "Supply constraints limit Blackwell ramp timing."},
    ]
    assert any("deterministic cross-company query" in warning for warning in result["warnings"])
    assert all(call[2] == graph_app.AURA_TEXT2CYPHER_QUERY_TIMEOUT_SECONDS for call in calls if call[0] == "query")


def test_company_balanced_rows_round_robins_company_evidence():
    rows = [
        {"company": "Cisco", "evidence": "c1"},
        {"company": "Cisco", "evidence": "c2"},
        {"company": "Cisco", "evidence": "c3"},
        {"company": "Microsoft", "evidence": "m1"},
        {"company": "Microsoft", "evidence": "m2"},
        {"company": "NVIDIA", "evidence": "n1"},
    ]

    balanced = company_balanced_rows(rows, limit=5, rows_per_company=2)

    assert [row["evidence"] for row in balanced] == ["c1", "c2", "m1", "m2", "n1"]
    assert distinct_company_keys(balanced) == ["Cisco", "Microsoft", "NVIDIA"]


def test_run_aura_text2cypher_tool_does_not_repair_deterministic_cross_company_result(monkeypatch):
    calls = []

    def fail_generate(*args, **kwargs):
        raise AssertionError("cross-company deterministic tools should not call Gemini Text2Cypher")

    def fail_repair(*args, **kwargs):
        raise AssertionError("cross-company deterministic tools should not call diversity repair")

    def fake_neo4j_query(cypher, params=None, timeout_seconds=None):
        calls.append(("query", cypher))
        return [{"company": "Cisco", "evidence": "cisco-only"}], None

    monkeypatch.setattr(graph_app, "generate_aura_text2cypher", fail_generate)
    monkeypatch.setattr(graph_app, "repair_aura_text2cypher_for_company_diversity", fail_repair)
    monkeypatch.setattr(graph_app, "neo4j_query", fake_neo4j_query)

    result, error = graph_app.run_aura_text2cypher_tool(
        "ai_positive_demand_by_company",
        "Across the graph, what positive AI demand signals are companies reporting?",
        max_limit=100,
    )

    assert error is None
    assert distinct_company_keys(result["rows"]) == ["Cisco"]
    assert any("deterministic cross-company query" in warning for warning in result["warnings"])
    assert calls and calls[0][0] == "query"


def test_aura_tool_router_prompt_lists_tools_and_routing_rules():
    prompt = build_aura_tool_router_prompt("Which companies are loaded?")

    assert "loaded_company_universe" in prompt
    assert "frequent_entities" in prompt
    assert "company_ai_deep_dive" in prompt
    assert "product_category_evidence_map" in prompt
    assert "ai_positive_demand_by_company" in prompt
    assert "Choose `frequent_entities`" in prompt
    assert "ai_risks_constraints_by_company" in prompt
    assert "Choose `loaded_company_universe`" in prompt
    assert "prefer the most specific tool" in prompt


def test_deterministic_aura_tool_route_handles_common_questions_without_llm():
    positive_route = deterministic_aura_tool_route(
        "Across the loaded earnings-call graph, what positive demand signals are companies reporting for the AI infrastructure industry?"
    )
    product_route = deterministic_aura_tool_route(
        "Across the loaded graph, summarize company evidence for the AI accelerator product category."
    )
    risk_route = deterministic_aura_tool_route(
        "Across the loaded earnings-call graph, what risks or constraints are companies reporting for AI infrastructure growth?"
    )
    frequent_route = deterministic_aura_tool_route(
        "What are the most frequently mentioned entities across the loaded earnings-call graph?"
    )
    loaded_route = deterministic_aura_tool_route("Which companies are currently loaded in the graph?")
    company_route = deterministic_aura_tool_route("For NVIDIA, what does the graph show about AI demand and Blackwell?")

    assert positive_route["tool_name"] == "ai_positive_demand_by_company"
    assert product_route["tool_name"] == "product_category_evidence_map"
    assert risk_route["tool_name"] == "ai_risks_constraints_by_company"
    assert frequent_route["tool_name"] == "frequent_entities"
    assert loaded_route["tool_name"] == "loaded_company_universe"
    assert company_route["tool_name"] == "company_ai_deep_dive"


def test_route_aura_tool_uses_deterministic_route_before_gemini(monkeypatch):
    class FailingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("deterministic route should avoid Gemini router")

    monkeypatch.setattr(graph_app, "GeminiClient", FailingClient)

    route = graph_app.route_aura_tool(
        "Across the loaded earnings-call graph, what positive demand signals are companies reporting for the AI infrastructure industry?"
    )

    assert route["tool_name"] == "ai_positive_demand_by_company"
    assert route["normalized_question"].startswith("Across the loaded earnings-call graph")

    risk_route = graph_app.route_aura_tool(
        "Across the loaded earnings-call graph, what risks or constraints are companies reporting for AI infrastructure growth?"
    )

    assert risk_route["tool_name"] == "ai_risks_constraints_by_company"

    frequent_route = graph_app.route_aura_tool(
        "What are the most frequently mentioned entities across the loaded earnings-call graph?"
    )

    assert frequent_route["tool_name"] == "frequent_entities"


def test_validate_aura_tool_route_accepts_known_tool_and_normalizes_question():
    route = validate_aura_tool_route(
        {
            "tool_name": "product_category_evidence_map",
            "rationale": "The question asks for product evidence.",
            "normalized_question": "Map AI accelerator evidence across companies.",
        },
        "original",
    )

    assert route == {
        "tool_name": "product_category_evidence_map",
        "rationale": "The question asks for product evidence.",
        "normalized_question": "Map AI accelerator evidence across companies.",
    }


def test_validate_aura_tool_route_rejects_unknown_tool():
    try:
        validate_aura_tool_route({"tool_name": "unknown_tool"}, "question")
    except ValueError as exc:
        assert "unknown Aura tool" in str(exc)
    else:
        raise AssertionError("unknown router tool should be rejected")


def test_result_limit_slider_enabled_requires_at_least_two_rows():
    assert result_limit_slider_enabled(0) is False
    assert result_limit_slider_enabled(1) is False
    assert result_limit_slider_enabled(2) is True


def test_friendly_agent_error_hides_raw_gemini_timeout_message():
    message = friendly_agent_error("Gemini API timed out after 60s", stage="tool path")

    assert "tool path is taking longer than expected" in message
    assert "Gemini API timed out" not in message
    assert "60s" not in message


def test_friendly_agent_error_keeps_non_llm_validation_details():
    assert friendly_agent_error("Generated Cypher must include RETURN.", stage="tool path") == "Generated Cypher must include RETURN."


def test_friendly_agent_error_hides_raw_neo4j_syntax_details():
    message = friendly_agent_error(
        "{neo4j_code: Neo.ClientError.Statement.SyntaxError} Invalid input '|'",
        stage="tool path",
    )

    assert "Neo4j syntax issue" in message
    assert "Invalid input" not in message
    assert "Neo.ClientError" not in message
    assert is_cypher_execution_error("{neo4j_code: Neo.ClientError.Statement.SyntaxError}") is True


def test_aura_agent_progress_messages_show_router_tool_and_answer_steps():
    text2cypher_steps = aura_agent_progress_messages("text2cypher")
    template_steps = aura_agent_progress_messages("cypher_template")

    assert text2cypher_steps == [
        "1/3 Routing the question to the best tool...",
        "2/3 Generating and running the Text2Cypher tool...",
        "3/3 Writing the answer from tool rows...",
    ]
    assert template_steps == [
        "1/3 Routing the question to the best tool...",
        "2/3 Running the Cypher template...",
        "3/3 Rendering template results...",
    ]


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


def test_app_css_keeps_markdown_tables_within_viewport():
    assert 'div[data-testid="stMarkdown"] table' in APP_CSS
    assert "table-layout: fixed" in APP_CSS
    assert 'div[data-testid="stMarkdown"] th' in APP_CSS
    assert 'div[data-testid="stMarkdown"] td' in APP_CSS
    assert 'div[data-testid="stMarkdown"] table code' in APP_CSS
    assert "white-space: normal" in APP_CSS


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


def test_aura_tool_answer_prompt_grounds_llm_in_tool_output():
    prompt = build_aura_tool_answer_prompt(
        tool_name="ai_positive_demand_by_company",
        question="What does AI demand affect?",
        params={"question": "What does AI demand affect?", "limit": 5},
        rows=[
            {
                "company": "NVIDIA",
                "source": "AI demand",
                "relation": "DRIVES",
                "target": "Data center revenue",
                "evidence": "AI demand drove data center revenue.",
            }
        ],
    )

    assert "Tool: ai_positive_demand_by_company" in prompt
    assert "Question: What does AI demand affect?" in prompt
    assert "AI demand drove data center revenue" in prompt
    assert "Do not invent companies" in prompt
    assert "Company-by-company referenced chunks" in prompt
    assert "Referenced chunk" in prompt
    assert "A Markdown table with columns: Company, Positive signal, Graph reasoning path, Evidence, Why it matters." not in prompt
    assert '"evidence"' not in prompt
    assert '"positive_signal"' not in prompt
    assert '"signal"' not in prompt
    assert "referenced_chunk" in prompt
    assert "Do not include a section or heading named Evidence gaps" in prompt
    assert "# Evidence gaps" not in prompt
    assert "# Evidence Gaps" not in prompt


def test_aura_answer_rows_drop_redundant_signal_and_clean_chunk_ellipsis():
    rows = aura_answer_rows_for_prompt(
        [
            {
                "company": "NVIDIA",
                "positive_signal": "AI demand",
                "signal": "AI demand",
                "graph_reasoning_path": "AI demand --DRIVES--> Revenue",
                "referenced_chunk": "Management cited stronger data center demand...",
                "evidence": "short evidence",
            }
        ]
    )

    assert rows == [
        {
            "company": "NVIDIA",
            "graph_reasoning_path": "AI demand --DRIVES--> Revenue",
            "referenced_chunk": "Management cited stronger data center demand",
        }
    ]


def test_aura_answer_rows_clean_chunk_trailing_question_artifacts():
    rows = aura_answer_rows_for_prompt(
        [
            {
                "company": "NVIDIA",
                "referenced_chunk": "NVIDIA® Management cited stronger data center demand??",
            }
        ]
    )

    assert rows[0]["referenced_chunk"] == "NVIDIA Management cited stronger data center demand"


def test_local_aura_tool_answer_renders_cross_company_rows_without_llm():
    answer = build_local_aura_tool_answer(
        "ai_positive_demand_by_company",
        [
            {
                "company": "NVIDIA",
                "graph_reasoning_path": "AI demand --DRIVES--> Data center revenue",
                "referenced_chunk": "Management cited stronger data center demand...",
            },
            {
                "company": "Cisco",
                "graph_reasoning_path": "AI infrastructure --SUPPORTS--> Networking orders",
                "referenced_chunk": "Customers are investing in AI infrastructure networking.",
            },
        ],
    )

    markdown = answer["markdown"]
    assert answer["source"] == "local"
    assert "# Company-by-company referenced chunks" in markdown
    assert "| Company | Graph reasoning path | Referenced chunk |" in markdown
    assert "NVIDIA" in markdown
    assert "Cisco" in markdown
    assert "stronger data center demand" in markdown
    assert "demand..." not in markdown


def test_local_aura_tool_answer_writes_contentful_company_executive_summary():
    answer = build_local_aura_tool_answer(
        "company_ai_deep_dive",
        [
            {
                "company": "NVIDIA",
                "graph_reasoning_path": "Blackwell --SUPPORTS--> AI infrastructure",
                "referenced_chunk": "NVIDIA Blackwell AI infrastructure",
            },
            {
                "company": "NVIDIA",
                "graph_reasoning_path": "NVIDIA --DISCUSSES--> Data Center revenue",
                "referenced_chunk": "Data Center Second-quarter revenue was $41.1 billion",
            },
        ],
    )

    markdown = answer["markdown"]
    summary = markdown.split("# Company AI Deep Dive", 1)[0]
    assert "Blackwell appears as a central product/platform signal" in summary
    assert "Data Center revenue is connected to growth evidence" in summary
    assert "The graph returned" not in summary


def test_frequent_entities_markdown_renders_ranked_entity_table():
    markdown = frequent_entities_markdown(
        [
            {
                "entity": "AI infrastructure",
                "entity_type": "Theme",
                "mention_count": 12,
                "sample_companies": ["NVIDIA", "Microsoft"],
                "evidence_count": 8,
                "concepts": ["AI Infrastructure"],
            }
        ]
    )

    assert "# Most frequently mentioned entities" in markdown
    assert "AI infrastructure" in markdown
    assert "| Rank | Entity | Type | Mentions | Companies | Evidence chunks | Concepts |" in markdown
    assert "NVIDIA, Microsoft" in markdown


def test_summarize_aura_tool_output_skips_gemini_for_deterministic_tools(monkeypatch):
    class FailGeminiClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("deterministic Aura tools should render locally")

    monkeypatch.setattr(graph_app, "GeminiClient", FailGeminiClient)

    answer = summarize_aura_tool_output(
        "ai_positive_demand_by_company",
        "Across the graph, what positive AI demand signals are present?",
        {"limit": 2},
        [{"company": "NVIDIA", "graph_reasoning_path": "AI demand --DRIVES--> Revenue", "referenced_chunk": "AI demand is strong."}],
    )

    assert answer["source"] == "local"
    assert "NVIDIA" in answer["markdown"]


def test_strip_aura_redundant_signal_columns_removes_llm_extra_columns():
    markdown = """
# Company-by-company referenced chunks
| Company | Positive signal | Graph reasoning path | Referenced chunk | Why it matters |
| --- | --- | --- | --- | --- |
| NVIDIA | AI demand | AI demand --DRIVES--> Revenue | Management cited data center demand... | Important |
""".strip()

    stripped = strip_aura_redundant_signal_columns(markdown)

    assert "Positive signal" not in stripped
    assert "Why it matters" not in stripped
    assert "| Company | Graph reasoning path | Referenced chunk |" in stripped
    assert "Management cited data center demand..." not in stripped
    assert "Management cited data center demand" in stripped


def test_strip_evidence_gap_sections_removes_result_section():
    markdown = """# Executive summary
Demand is broad.

# Company-by-company evidence
| Company | Evidence |
| --- | --- |
| NVIDIA | Strong demand |

# Evidence gaps or caveats
- Missing one company.
- Another caveat.
"""

    stripped = strip_evidence_gap_sections(markdown)

    assert "Executive summary" in stripped
    assert "Company-by-company evidence" in stripped
    assert "Evidence gaps" not in stripped
    assert "Missing one company" not in stripped


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

    assert "Ontology: AI Demand, Infrastructure CapEx" in answer["property_insights"]
    assert "Technical infrastructure capex ($35.7B)" in answer["property_insights"]
    assert "Cloud and AI capex ($21.4B)" in answer["property_insights"]
    assert "Alphabet:" in answer["property_insights"]
    assert "Microsoft:" in answer["property_insights"]
    assert "value/context properties" in answer["basis"]


def test_ask_relation_card_items_render_one_relation_per_item():
    items = ask_relation_card_items(
        [
            {
                "company": "Microsoft",
                "ticker": "MSFT",
                "source": "AI demand",
                "source_concepts": ["AI Demand"],
                "relation": "DRIVES",
                "target": "Cloud revenue growth",
                "target_type": "MetricValue",
                "target_properties": {"value": "+20%", "context": "Azure growth"},
                "target_concepts": ["Cloud Infrastructure"],
                "matched_terms": ["ai", "demand"],
                "confidence": 0.91,
                "chunk_id": "msft-chunk-001",
                "evidence": "Azure AI demand exceeded available capacity.",
            },
            {
                "company": "Seagate Technology",
                "ticker": "STX",
                "source": "Supply constraints",
                "relation": "PRESSURES",
                "target": "Nearline demand",
                "matched_terms": ["demand"],
                "chunk_id": "stx-chunk-001",
                "chunk_preview": "Supply remained tight.",
            },
        ],
        limit=2,
    )

    assert [item["signal_label"] for item in items] == ["Support", "Risk / pressure"]
    assert items[0]["company"] == "Microsoft MSFT"
    assert items[0]["path"] == "AI demand --DRIVES--> Cloud revenue growth (+20%) [Azure growth]"
    assert items[0]["ontology"] == "AI Demand -> Cloud Infrastructure"
    assert items[0]["evidence"] == "Azure AI demand exceeded available capacity."
    assert "matched: ai, demand" in items[0]["foot"]
    assert "confidence: 0.91" in items[0]["foot"]
    assert items[1]["evidence"] == "Supply remained tight."


def test_ask_relation_cards_html_is_not_indented_as_markdown_code_block():
    html = ask_relation_cards_html(
        [
            {
                "index": "1",
                "signal_class": "support",
                "signal_label": "Support",
                "company": "Microsoft MSFT",
                "path": "AI demand --DRIVES--> Azure",
                "ontology": "AI Demand -> Cloud Infrastructure",
                "evidence": "Strong demand.",
                "foot": "matched: ai, demand",
            },
            {
                "index": "2",
                "signal_class": "risk",
                "signal_label": "Risk / pressure",
                "company": "Microsoft MSFT",
                "path": "AI demand --REDUCES--> Gross margin",
                "evidence": "AI usage increased cost pressure.",
                "foot": "matched: ai, demand",
            },
            {
                "index": "3",
                "signal_class": "neutral",
                "signal_label": "Relation",
                "company": "Microsoft MSFT",
                "path": "AI demand --ASSOCIATED_WITH--> Platform usage",
                "evidence": "Platform usage was discussed.",
                "foot": "matched: ai, demand",
            },
        ]
    )

    assert html.startswith('<div class="cf-relation-list">')
    assert "\n    <div" not in html
    assert '<div class="cf-relation-signal-grid">' in html
    assert html.index("Support / upside") < html.index("Risk / pressure")
    assert html.index("Risk / pressure") < html.index("Other relation paths")
    assert "1 relation(s)" in html
    assert "AI demand --DRIVES--&gt; Azure" in html
    assert "Ontology:</strong> AI Demand -&gt; Cloud Infrastructure" in html
    assert html.index("AI demand --DRIVES--&gt; Azure") < html.index("Ontology:</strong>")
    assert "AI demand --REDUCES--&gt; Gross margin" in html


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
    assert "[ontology: AI Demand -> Infrastructure CapEx]" in explanation["main_connections"]
