from __future__ import annotations

import json
import re
from html import escape
from typing import Any, Iterable

import streamlit as st

from earnings_call_graph.gemini import GeminiApiError, GeminiClient
from earnings_call_graph.graph import graph_from_env, relation_rows_to_graph

ONTOLOGY_CLICK_BRIDGE = st.components.v2.component(
    "ontology_click_bridge",
    html='<span id="ontology-click-bridge" aria-hidden="true"></span>',
    js="""
export default function(component) {
  const { data, setTriggerValue } = component
  const channel = (data && data.channel) || "earnings_call_graph:ontologyNodeClick"
  if (window.__earnings_call_graphOntologyClickBridge) {
    window.removeEventListener("message", window.__earnings_call_graphOntologyClickBridge)
  }
  window.__earnings_call_graphOntologyClickBridge = (event) => {
    const payload = event && event.data ? event.data : {}
    if (payload.type !== channel || !payload.nodeId) return
    setTriggerValue("selected_node_id", payload.nodeId)
    setTriggerValue("selection", {
      node_id: payload.nodeId,
      scale: payload.scale,
      position: payload.position || null,
    })
  }
  window.addEventListener("message", window.__earnings_call_graphOntologyClickBridge)
}
""",
)

GRAPH_LABELS = [
    "Company",
    "EarningsCall",
    "SourceDocument",
    "MarkdownChunk",
    "Entity",
    "RelationFact",
    "OntologyConcept",
]

APP_CSS = """
<style>
:root {
  --cf-bg: #14161A;
  --cf-bg-1: #1A1D22;
  --cf-bg-2: #20242B;
  --cf-bg-3: #282D35;
  --cf-line: #343A45;
  --cf-line-2: #49515F;
  --cf-fg: #F4F6F8;
  --cf-muted: #C6CBD3;
  --cf-dim: #9098A4;
  --cf-accent: #E5484D;
  --cf-accent-soft: rgba(229, 72, 77, 0.14);
}
.stApp {
  background: var(--cf-bg);
  color: var(--cf-fg);
}
.stApp [data-testid="stHeader"] {
  background: rgba(11, 11, 13, 0.88);
  border-bottom: 1px solid var(--cf-line);
}
.block-container {
  padding-top: 4.25rem;
  padding-bottom: 2rem;
  max-width: 1500px;
}
[data-testid="stSidebar"] {
  background: var(--cf-bg-1);
  border-right: 1px solid var(--cf-line);
}
[data-testid="stSidebar"] * {
  color: var(--cf-fg);
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {
  color: var(--cf-muted);
}
h1, h2, h3, h4, h5, h6 {
  color: var(--cf-fg);
  letter-spacing: 0;
}
.stTabs [data-baseweb="tab-list"] {
  gap: 0.25rem;
  border-bottom: 1px solid var(--cf-line);
}
.stTabs [data-baseweb="tab"] {
  background: transparent;
  border-radius: 0;
  border-bottom: 2px solid transparent;
  color: var(--cf-muted);
  padding: 0.75rem 1.1rem;
}
.stTabs [aria-selected="true"] {
  color: var(--cf-fg);
  border-bottom-color: var(--cf-accent);
}
[data-testid="stMetric"] {
  background: var(--cf-bg-1);
  border: 1px solid var(--cf-line);
  border-radius: 8px;
  padding: 0.45rem 0.7rem;
}
[data-testid="stMetricValue"] {
  color: var(--cf-fg);
  font-size: 1.35rem;
}
[data-testid="stMetricLabel"] {
  color: var(--cf-muted);
  font-size: 0.74rem;
}
.stDataFrame {
  border: 1px solid var(--cf-line);
  border-radius: 8px;
  overflow: hidden;
}
.stAlert {
  background: var(--cf-bg-2);
  border: 1px solid var(--cf-line);
  color: var(--cf-fg);
}
.stButton button,
[data-testid="stBaseButton-secondary"] {
  background: var(--cf-bg-2);
  border: 1px solid var(--cf-line-2);
  color: var(--cf-fg);
  border-radius: 8px;
}
.stButton button:hover,
[data-testid="stBaseButton-secondary"]:hover {
  border-color: var(--cf-accent);
  color: var(--cf-accent);
}
.cf-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  padding: 0.55rem 1rem;
  margin-bottom: 0.7rem;
  background: linear-gradient(180deg, #111114 0%, #0B0B0D 100%);
  border: 1px solid var(--cf-line);
  border-radius: 10px;
}
.cf-brand {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
}
.cf-glyph {
  color: var(--cf-accent);
  font-size: 1.25rem;
  line-height: 1;
}
.cf-title {
  color: var(--cf-fg);
  font-size: 1.05rem;
  font-weight: 750;
}
.cf-subtitle {
  color: var(--cf-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
}
.cf-header-stats {
  display: flex;
  gap: 0.8rem;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.cf-stat {
  display: flex;
  flex-direction: column;
  line-height: 1.1;
  min-width: 3.5rem;
  text-align: right;
}
.cf-stat-v {
  color: var(--cf-fg);
  font-size: 1rem;
  font-weight: 750;
}
.cf-stat-k {
  color: var(--cf-muted);
  font-size: 0.68rem;
}
.cf-context-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: -0.25rem 0 0.9rem;
}
.cf-context-pill {
  border: 1px solid var(--cf-line);
  border-radius: 6px;
  background: var(--cf-bg-1);
  color: var(--cf-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.68rem;
  padding: 0.28rem 0.5rem;
}
.cf-context-pill strong {
  color: var(--cf-fg);
  font-family: Inter, Arial, sans-serif;
  font-size: 0.78rem;
  margin-right: 0.28rem;
}
.cf-section-title {
  color: var(--cf-fg);
  font-size: 1rem;
  font-weight: 700;
  margin: 0.1rem 0 0.1rem;
}
.cf-section-sub {
  color: var(--cf-muted);
  font-size: 0.78rem;
  margin-bottom: 0.55rem;
}
.cf-side-title {
  color: var(--cf-fg);
  font-size: 0.82rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.35rem;
}
.cf-side-help {
  color: var(--cf-dim);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  margin-bottom: 1rem;
}
.cf-panel {
  background: var(--cf-bg-1);
  border: 1px solid var(--cf-line);
  border-radius: 10px;
  padding: 1rem;
}
.cf-answer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.8rem;
}
.cf-answer-card {
  background: var(--cf-bg-1);
  border: 1px solid var(--cf-line);
  border-left: 3px solid var(--cf-accent);
  border-radius: 8px;
  padding: 0.9rem 1rem;
  color: var(--cf-fg);
}
.cf-answer-card.risk {
  border-left-color: #F97316;
}
.cf-answer-label {
  color: var(--cf-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.35rem;
}
.cf-answer-text {
  color: var(--cf-fg);
  font-size: 0.9rem;
  line-height: 1.5;
}
.cf-chunk-text {
  background: var(--cf-bg-2);
  border: 1px solid var(--cf-line);
  border-radius: 8px;
  color: var(--cf-fg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  line-height: 1.55;
  padding: 0.85rem 0.95rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.cf-muted {
  color: var(--cf-muted);
}
div[data-baseweb="input"] input,
div[data-baseweb="select"] div,
div[data-baseweb="base-input"] input {
  background: var(--cf-bg-2);
  color: var(--cf-fg);
}
</style>
"""

BULLISH_RELATIONS = {"DRIVES", "INCREASES", "OFFSETS", "GUIDES_TO", "CONVERTS_TO"}
RISK_RELATIONS = {"PRESSURES", "RISKS", "CONSTRAINS", "EXPOSED_TO", "REDUCES", "AFFECTS"}
QUESTION_STOPWORDS = {
    "what",
    "does",
    "how",
    "why",
    "which",
    "the",
    "and",
    "with",
    "from",
    "that",
    "this",
    "graph",
    "affect",
    "affects",
    "impact",
    "impacts",
    "ontology",
    "concept",
}

ASK_QUESTION_PRESETS = [
    "What does AI demand affect?",
    "How does AI demand affect capex across companies?",
    "What pressures operating margin?",
    "How does cloud backlog convert to revenue?",
    "Which risks are connected to infrastructure investment?",
]
CUSTOM_QUESTION_LABEL = "Custom question"
ONTOLOGY_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "company_differences": {"type": "array", "items": {"type": "string"}},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_points", "company_differences", "evidence_gaps"],
}
ONTOLOGY_SUMMARY_SYSTEM = (
    "You summarize earnings-call evidence chunks for an investment research graph. "
    "Be concise, source-grounded, and avoid claiming more than the chunks support."
)
GRAPH_CHUNK_SUMMARY_SYSTEM = (
    "You summarize earnings-call source chunks for an investment research graph. "
    "Use only the provided chunks and graph paths. Keep the answer concise, source-grounded, "
    "and explicit about differences across companies when present."
)
CONNECTED_NODE_SUMMARY_SYSTEM = (
    "You write a concise top-of-dashboard overview for an earnings-call graph. "
    "Use only the provided high-connectivity node evidence chunks and graph paths. "
    "Emphasize what the most connected nodes suggest, but do not infer beyond the chunks."
)
ONTOLOGY_HIERARCHY_RELATIONS = {"IS_A", "PART_OF"}
TEXT2CYPHER_MAX_LIMIT = 50
TEXT2CYPHER_SCHEMA = {
    "type": "object",
    "properties": {
        "cypher": {"type": "string"},
        "rationale": {"type": "string"},
        "expected_columns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["cypher", "rationale", "expected_columns"],
}
TEXT2CYPHER_SYSTEM = (
    "You generate read-only Neo4j Cypher for an earnings-call graph. "
    "Return only JSON matching the schema. Do not use markdown. "
    "The query must be read-only, must include RETURN, and must include LIMIT. "
    "Avoid range(); use direct UNWIND over lists instead so missing values cannot break the query."
)
TEXT2CYPHER_FORBIDDEN_PATTERN = re.compile(
    r"\b("
    r"CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH|CALL|"
    r"CREATE\s+INDEX|CREATE\s+CONSTRAINT|DROP\s+INDEX|DROP\s+CONSTRAINT|"
    r"GRANT|DENY|REVOKE|START\s+DATABASE|STOP\s+DATABASE|ALTER|USE"
    r")\b",
    re.IGNORECASE,
)
TEXT2CYPHER_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)

TEXT2CYPHER_GRAPH_SCHEMA = """
Node labels and key properties:
- Company: id, name, ticker, sector
- EarningsCall: id, call_id, fiscal_quarter, call_date, title
- FiscalPeriod: id, label, fiscal_year, quarter
- SourceDocument: id, title, source_url, source_kind, markdown_path
- MarkdownChunk: id, text, chunk_index, heading
- Entity: id, name, entity_type, aliases, value, context, confidence
- RelationFact: id, relation_type, evidence_text, confidence, properties
- OntologyConcept: id, name, concept_type, description, aliases

Core relationships:
- (:Company)-[:HELD_CALL]->(:EarningsCall)
- (:EarningsCall)-[:IN_PERIOD]->(:FiscalPeriod)
- (:SourceDocument)-[:SOURCE_FOR]->(:EarningsCall)
- (:SourceDocument)-[:ABOUT_COMPANY]->(:Company)
- (:SourceDocument)-[:HAS_CHUNK]->(:MarkdownChunk)
- (:MarkdownChunk)-[:MENTIONS_ENTITY]->(:Entity)
- (:RelationFact)-[:FROM_ENTITY]->(:Entity)
- (:RelationFact)-[:TO_ENTITY]->(:Entity)
- (:RelationFact)-[:SUPPORTED_BY]->(:MarkdownChunk)
- (:Entity)-[:RELATED_TO {relation_type}]->(:Entity)
- (:Entity)-[:MAPS_TO {confidence, method, matched_alias}]->(:OntologyConcept)
- (:OntologyConcept)-[:IS_A|PART_OF|HAS_METRIC|DRIVES_SCHEMA|FUNDS|CAN_PRESSURE]->(:OntologyConcept)

Recommended evidence path:
MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
      (fact)-[:TO_ENTITY]->(dst:Entity)
OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
OPTIONAL MATCH (src)-[:MAPS_TO]->(sourceConcept:OntologyConcept)
OPTIONAL MATCH (dst)-[:MAPS_TO]->(targetConcept:OntologyConcept)
RETURN company.ticker AS ticker, company.name AS company, src.name AS source,
       fact.relation_type AS relation, dst.name AS target,
       fact.evidence_text AS evidence, chunk.id AS chunk_id,
       collect(DISTINCT sourceConcept.name) AS source_concepts,
       collect(DISTINCT targetConcept.name) AS target_concepts
LIMIT 25
""".strip()


@st.cache_data(ttl=60)
def neo4j_query(cypher: str, params: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    graph = None
    try:
        graph = graph_from_env()
        graph.verify_connectivity()
        with graph.driver.session(database=graph.database) as session:
            return session.run(cypher, params or {}).data(), None
    except Exception as exc:
        return [], str(exc)
    finally:
        if graph is not None:
            graph.close()


def build_text2cypher_prompt(question: str, *, max_limit: int = TEXT2CYPHER_MAX_LIMIT) -> str:
    return f"""
User question:
{question}

Graph schema:
{TEXT2CYPHER_GRAPH_SCHEMA}

Generate one read-only Cypher query for Neo4j.

Rules:
- Use only the labels, relationship types, and properties listed above.
- Prefer RelationFact -> Entity -> MarkdownChunk paths when the question asks for evidence.
- Include source chunks and evidence text when useful for explaining why an answer is true.
- Do not write or mutate the graph.
- Do not use procedures or CALL.
- Do not use range(); if you need to expand a list, UNWIND the list itself.
- Include a LIMIT no larger than {max_limit}.
- Return readable column aliases for display in a Streamlit table.
""".strip()


def validate_text2cypher(cypher: str, *, max_limit: int = TEXT2CYPHER_MAX_LIMIT) -> tuple[str, list[str]]:
    """Return a safe query or raise ValueError with a user-displayable reason."""

    cleaned = cypher.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:cypher)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    cleaned = cleaned.rstrip(";").strip()
    compact = re.sub(r"\s+", " ", cleaned)
    if not compact:
        raise ValueError("Generated Cypher was empty.")
    if ";" in compact:
        raise ValueError("Generated Cypher must contain only one statement.")
    if "//" in compact or "/*" in compact or "*/" in compact:
        raise ValueError("Generated Cypher must not contain comments.")
    if TEXT2CYPHER_FORBIDDEN_PATTERN.search(compact):
        raise ValueError("Generated Cypher used a forbidden write/admin/procedure clause.")
    if re.search(r"\brange\s*\(", compact, re.IGNORECASE):
        raise ValueError("Generated Cypher must not use range(); UNWIND lists directly instead.")
    if not re.search(r"\b(MATCH|OPTIONAL\s+MATCH|WITH)\b", compact, re.IGNORECASE):
        raise ValueError("Generated Cypher must include MATCH, OPTIONAL MATCH, or WITH.")
    if not re.search(r"\bRETURN\b", compact, re.IGNORECASE):
        raise ValueError("Generated Cypher must include RETURN.")
    limit_match = TEXT2CYPHER_LIMIT_PATTERN.search(compact)
    if not limit_match:
        raise ValueError("Generated Cypher must include LIMIT.")

    warnings: list[str] = []
    limit_value = int(limit_match.group(1))
    if limit_value > max_limit:
        compact = TEXT2CYPHER_LIMIT_PATTERN.sub(f"LIMIT {max_limit}", compact, count=1)
        warnings.append(f"LIMIT was capped from {limit_value} to {max_limit}.")
    return compact, warnings


def generate_text2cypher(question: str) -> dict[str, Any]:
    client = GeminiClient(timeout=60, max_retries=1, retry_delay=1.0)
    generated = client.generate_json(
        build_text2cypher_prompt(question),
        TEXT2CYPHER_SCHEMA,
        system_instruction=TEXT2CYPHER_SYSTEM,
        temperature=0.0,
        operation="Gemini Text2Cypher",
    )
    cypher, warnings = validate_text2cypher(str(generated.get("cypher") or ""))
    return {
        "cypher": cypher,
        "rationale": str(generated.get("rationale") or ""),
        "expected_columns": list(generated.get("expected_columns") or []),
        "warnings": warnings,
    }


def run_text2cypher_question(question: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        generated = generate_text2cypher(question)
    except (GeminiApiError, ValueError) as exc:
        return None, str(exc)
    rows, error = neo4j_query(generated["cypher"])
    if error:
        return {**generated, "rows": []}, error
    return {**generated, "rows": rows}, None


@st.cache_data(ttl=60)
def graph_counts() -> tuple[list[dict[str, Any]], str | None]:
    return neo4j_query(
        """
        CALL {
        MATCH (n)
        WHERE any(label IN labels(n) WHERE label IN $labels)
        UNWIND labels(n) AS label
        WITH label, count(*) AS count
        WHERE label IN $labels
        RETURN label, count
        UNION ALL
        MATCH (call:EarningsCall)
        WITH DISTINCT coalesce(call.fiscal_quarter, '') AS period
        WHERE period <> ''
        RETURN 'FiscalPeriod' AS label, count(*) AS count
        UNION ALL
        MATCH (call:EarningsCall)
        WITH DISTINCT toUpper(coalesce(call.fiscal_quarter, '')) AS period
        WITH CASE
               WHEN period CONTAINS 'Q1' THEN 'Q1'
               WHEN period CONTAINS 'Q2' THEN 'Q2'
               WHEN period CONTAINS 'Q3' THEN 'Q3'
               WHEN period CONTAINS 'Q4' THEN 'Q4'
               ELSE ''
             END AS quarter
        WHERE quarter <> ''
        RETURN 'Quarter' AS label, count(DISTINCT quarter) AS count
        }
        RETURN label, count
        ORDER BY label
        """,
        {"labels": GRAPH_LABELS},
    )


@st.cache_data(ttl=60)
def source_document_rows() -> tuple[list[dict[str, Any]], str | None]:
    return neo4j_query(
        """
        MATCH (source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
        OPTIONAL MATCH (source_doc)-[:HAS_CHUNK]->(chunk:MarkdownChunk)
        OPTIONAL MATCH (fact:RelationFact)-[:SUPPORTED_BY]->(chunk)
        RETURN company.name AS company,
               company.ticker AS ticker,
               source_doc.id AS document,
               source_doc.source_url AS source_url,
               count(DISTINCT chunk) AS chunks,
               count(DISTINCT fact) AS relations
        ORDER BY company.name, source_doc.id
        """,
        {},
    )


@st.cache_data(ttl=60)
def company_options() -> tuple[list[dict[str, Any]], str | None]:
    return neo4j_query(
        """
        MATCH (company:Company)-[:HELD_CALL]->(call:EarningsCall)<-[:SOURCE_FOR]-(source_doc:SourceDocument)
        RETURN company.name AS company,
               company.ticker AS ticker,
               call.fiscal_quarter AS quarter,
               count(DISTINCT source_doc) AS documents
        ORDER BY company.name
        """,
        {},
    )


@st.cache_data(ttl=60)
def relation_fact_rows(search: str = "", limit: int = 100, company_ticker: str = "") -> tuple[list[dict[str, Any]], str | None]:
    terms = query_terms(search)
    return neo4j_query(
        """
        MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
              (fact)-[:TO_ENTITY]->(dst:Entity)
        OPTIONAL MATCH (src)-[:MAPS_TO]->(src_concept:OntologyConcept)
        OPTIONAL MATCH (dst)-[:MAPS_TO]->(dst_concept:OntologyConcept)
        WITH fact, src, dst,
             collect(DISTINCT src_concept.name) AS source_concepts,
             collect(DISTINCT dst_concept.name) AS target_concepts,
             collect(DISTINCT coalesce(src_concept.description, '')) AS source_concept_descriptions,
             collect(DISTINCT coalesce(dst_concept.description, '')) AS target_concept_descriptions
        WITH fact, src, dst, source_concepts, target_concepts, source_concept_descriptions, target_concept_descriptions,
             [term IN $terms WHERE
                toLower(src.name) CONTAINS term
             OR toLower(coalesce(src.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(src.value, '')) CONTAINS term
             OR toLower(coalesce(src.context, '')) CONTAINS term
             OR toLower(dst.name) CONTAINS term
             OR toLower(coalesce(dst.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(dst.value, '')) CONTAINS term
             OR toLower(coalesce(dst.context, '')) CONTAINS term
             OR any(name IN source_concepts WHERE toLower(name) CONTAINS term)
             OR any(name IN target_concepts WHERE toLower(name) CONTAINS term)
             OR any(description IN source_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR any(description IN target_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR toLower(coalesce(fact.evidence_text, '')) CONTAINS term
             OR toLower(fact.relation_type) CONTAINS term] AS matched_terms
        WHERE size($terms) = 0 OR size(matched_terms) > 0
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)
        OPTIONAL MATCH (source_doc:SourceDocument)-[:HAS_CHUNK]->(chunk)
        OPTIONAL MATCH (source_doc)-[:ABOUT_COMPANY]->(company:Company)
        WITH fact, src, dst, source_concepts, target_concepts, matched_terms, chunk, source_doc, company
        WHERE $company_ticker = '' OR company.ticker = $company_ticker
        RETURN fact.id AS fact_id,
               source_doc.id AS document,
               source_doc.source_url AS source_url,
               company.name AS company,
               company.ticker AS ticker,
               src.id AS source_id,
               src.name AS source,
               src.entity_type AS source_type,
               CASE WHEN src.value IS NULL AND src.context IS NULL THEN {} ELSE src { .value, .context } END AS source_properties,
               source_concepts AS source_concepts,
               fact.relation_type AS relation,
               coalesce(fact.layer, 'coverage') AS relation_layer,
               dst.id AS target_id,
               dst.name AS target,
               dst.entity_type AS target_type,
               CASE WHEN dst.value IS NULL AND dst.context IS NULL THEN {} ELSE dst { .value, .context } END AS target_properties,
               target_concepts AS target_concepts,
               matched_terms AS matched_terms,
               fact.evidence_text AS evidence,
               fact.confidence AS confidence,
               chunk.id AS chunk_id,
               coalesce(chunk.text_preview, chunk.text) AS chunk_preview,
               chunk.text AS chunk_text
        ORDER BY CASE coalesce(fact.layer, 'coverage') WHEN 'insight' THEN 1 ELSE 0 END DESC,
                 size(matched_terms) DESC, coalesce(fact.confidence, 0.0) DESC, company, source, relation, target
        LIMIT $limit
        """,
        {"terms": terms, "limit": limit, "company_ticker": company_ticker},
    )



@st.cache_data(ttl=60)
def balanced_relation_fact_rows(search: str = "", limit: int = 100) -> tuple[list[dict[str, Any]], str | None]:
    """Return relation rows in company round-robin order for the Graph tab.

    Ask keeps using relevance-first ordering, but the visual graph should not let one
    company consume the whole limit just because it has many high-confidence matches.
    """

    terms = query_terms(search)
    return neo4j_query(
        """
        MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
              (fact)-[:TO_ENTITY]->(dst:Entity)
        OPTIONAL MATCH (src)-[:MAPS_TO]->(src_concept:OntologyConcept)
        OPTIONAL MATCH (dst)-[:MAPS_TO]->(dst_concept:OntologyConcept)
        WITH fact, src, dst,
             collect(DISTINCT src_concept.name) AS source_concepts,
             collect(DISTINCT dst_concept.name) AS target_concepts,
             collect(DISTINCT coalesce(src_concept.description, '')) AS source_concept_descriptions,
             collect(DISTINCT coalesce(dst_concept.description, '')) AS target_concept_descriptions
        WITH fact, src, dst, source_concepts, target_concepts, source_concept_descriptions, target_concept_descriptions,
             [term IN $terms WHERE
                toLower(src.name) CONTAINS term
             OR toLower(coalesce(src.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(src.value, '')) CONTAINS term
             OR toLower(coalesce(src.context, '')) CONTAINS term
             OR toLower(dst.name) CONTAINS term
             OR toLower(coalesce(dst.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(dst.value, '')) CONTAINS term
             OR toLower(coalesce(dst.context, '')) CONTAINS term
             OR any(name IN source_concepts WHERE toLower(name) CONTAINS term)
             OR any(name IN target_concepts WHERE toLower(name) CONTAINS term)
             OR any(description IN source_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR any(description IN target_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR toLower(coalesce(fact.evidence_text, '')) CONTAINS term
             OR toLower(fact.relation_type) CONTAINS term] AS matched_terms
        WHERE size($terms) = 0 OR size(matched_terms) > 0
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)
        OPTIONAL MATCH (source_doc:SourceDocument)-[:HAS_CHUNK]->(chunk)
        OPTIONAL MATCH (source_doc)-[:ABOUT_COMPANY]->(company:Company)
        WITH coalesce(company.name, 'Unknown') AS company_bucket,
             {
               fact_id: fact.id,
               document: source_doc.id,
               source_url: source_doc.source_url,
               company: company.name,
               ticker: company.ticker,
               source_id: src.id,
               source: src.name,
               source_type: src.entity_type,
               source_properties: CASE WHEN src.value IS NULL AND src.context IS NULL THEN {} ELSE src { .value, .context } END,
               source_concepts: source_concepts,
               relation: fact.relation_type,
               relation_layer: coalesce(fact.layer, 'coverage'),
               target_id: dst.id,
               target: dst.name,
               target_type: dst.entity_type,
               target_properties: CASE WHEN dst.value IS NULL AND dst.context IS NULL THEN {} ELSE dst { .value, .context } END,
               target_concepts: target_concepts,
               matched_terms: matched_terms,
               evidence: fact.evidence_text,
               confidence: fact.confidence,
               chunk_id: chunk.id,
               chunk_preview: coalesce(chunk.text_preview, chunk.text),
               chunk_text: chunk.text,
               layer_rank: CASE coalesce(fact.layer, 'coverage') WHEN 'insight' THEN 1 ELSE 0 END,
               match_rank: size(matched_terms),
               confidence_rank: coalesce(fact.confidence, 0.0)
             } AS row
        ORDER BY company_bucket, row.layer_rank DESC, row.match_rank DESC, row.confidence_rank DESC,
                 row.source, row.relation, row.target
        WITH company_bucket, collect(row) AS company_rows
        ORDER BY company_bucket
        WITH collect(company_rows) AS grouped_rows, coalesce(max(size(company_rows)), 0) AS max_row_count
        WHERE max_row_count > 0
        UNWIND range(0, max_row_count - 1) AS row_index
        UNWIND grouped_rows AS company_rows
        WITH company_rows[row_index] AS row
        WHERE row IS NOT NULL
        RETURN row.fact_id AS fact_id,
               row.document AS document,
               row.source_url AS source_url,
               row.company AS company,
               row.ticker AS ticker,
               row.source_id AS source_id,
               row.source AS source,
               row.source_type AS source_type,
               row.source_properties AS source_properties,
               row.source_concepts AS source_concepts,
               row.relation AS relation,
               row.relation_layer AS relation_layer,
               row.target_id AS target_id,
               row.target AS target,
               row.target_type AS target_type,
               row.target_properties AS target_properties,
               row.target_concepts AS target_concepts,
               row.matched_terms AS matched_terms,
               row.evidence AS evidence,
               row.confidence AS confidence,
               row.chunk_id AS chunk_id,
               row.chunk_preview AS chunk_preview,
               row.chunk_text AS chunk_text
        LIMIT $limit
        """,
        {"terms": terms, "limit": limit},
    )


@st.cache_data(ttl=60)
def relation_fact_count(search: str = "", company_ticker: str = "") -> tuple[int, str | None]:
    terms = query_terms(search)
    rows, error = neo4j_query(
        """
        MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
              (fact)-[:TO_ENTITY]->(dst:Entity)
        OPTIONAL MATCH (src)-[:MAPS_TO]->(src_concept:OntologyConcept)
        OPTIONAL MATCH (dst)-[:MAPS_TO]->(dst_concept:OntologyConcept)
        WITH fact, src, dst,
             collect(DISTINCT src_concept.name) AS source_concepts,
             collect(DISTINCT dst_concept.name) AS target_concepts,
             collect(DISTINCT coalesce(src_concept.description, '')) AS source_concept_descriptions,
             collect(DISTINCT coalesce(dst_concept.description, '')) AS target_concept_descriptions
        WITH fact, src, dst, source_concepts, target_concepts, source_concept_descriptions, target_concept_descriptions,
             [term IN $terms WHERE
                toLower(src.name) CONTAINS term
             OR toLower(coalesce(src.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(src.value, '')) CONTAINS term
             OR toLower(coalesce(src.context, '')) CONTAINS term
             OR toLower(dst.name) CONTAINS term
             OR toLower(coalesce(dst.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(dst.value, '')) CONTAINS term
             OR toLower(coalesce(dst.context, '')) CONTAINS term
             OR any(name IN source_concepts WHERE toLower(name) CONTAINS term)
             OR any(name IN target_concepts WHERE toLower(name) CONTAINS term)
             OR any(description IN source_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR any(description IN target_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR toLower(coalesce(fact.evidence_text, '')) CONTAINS term
             OR toLower(fact.relation_type) CONTAINS term] AS matched_terms
        WHERE size($terms) = 0 OR size(matched_terms) > 0
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)
        OPTIONAL MATCH (source_doc:SourceDocument)-[:HAS_CHUNK]->(chunk)
        OPTIONAL MATCH (source_doc)-[:ABOUT_COMPANY]->(company:Company)
        WITH fact, company
        WHERE $company_ticker = '' OR company.ticker = $company_ticker
        RETURN count(DISTINCT fact) AS count
        """,
        {"terms": terms, "company_ticker": company_ticker},
    )
    if error:
        return 0, error
    return int(rows[0].get("count", 0)) if rows else 0, None


@st.cache_data(ttl=60)
def connected_node_summary_rows(
    search: str = "",
    limit: int = 15,
    company_ticker: str = "",
    nodes_per_company: int = 2,
    chunks_per_node: int = 1,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return source chunk rows from each company's highest-degree nodes in scope."""

    terms = query_terms(search)
    return neo4j_query(
        """
        MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
              (fact)-[:TO_ENTITY]->(dst:Entity)
        OPTIONAL MATCH (src)-[:MAPS_TO]->(src_concept:OntologyConcept)
        OPTIONAL MATCH (dst)-[:MAPS_TO]->(dst_concept:OntologyConcept)
        WITH fact, src, dst,
             collect(DISTINCT src_concept.name) AS source_concepts,
             collect(DISTINCT dst_concept.name) AS target_concepts,
             collect(DISTINCT coalesce(src_concept.description, '')) AS source_concept_descriptions,
             collect(DISTINCT coalesce(dst_concept.description, '')) AS target_concept_descriptions
        WITH fact, src, dst, source_concepts, target_concepts, source_concept_descriptions, target_concept_descriptions,
             [term IN $terms WHERE
                toLower(src.name) CONTAINS term
             OR toLower(coalesce(src.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(src.value, '')) CONTAINS term
             OR toLower(coalesce(src.context, '')) CONTAINS term
             OR toLower(dst.name) CONTAINS term
             OR toLower(coalesce(dst.canonical_name, '')) CONTAINS term
             OR toLower(coalesce(dst.value, '')) CONTAINS term
             OR toLower(coalesce(dst.context, '')) CONTAINS term
             OR any(name IN source_concepts WHERE toLower(name) CONTAINS term)
             OR any(name IN target_concepts WHERE toLower(name) CONTAINS term)
             OR any(description IN source_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR any(description IN target_concept_descriptions WHERE toLower(description) CONTAINS term)
             OR toLower(coalesce(fact.evidence_text, '')) CONTAINS term
             OR toLower(fact.relation_type) CONTAINS term] AS matched_terms
        WHERE size($terms) = 0 OR size(matched_terms) > 0
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)
        OPTIONAL MATCH (source_doc:SourceDocument)-[:HAS_CHUNK]->(chunk)
        OPTIONAL MATCH (source_doc)-[:ABOUT_COMPANY]->(company:Company)
        WITH fact, src, dst, source_concepts, target_concepts, matched_terms, chunk, source_doc, company
        WHERE $company_ticker = '' OR company.ticker = $company_ticker
        UNWIND [src, dst] AS focus_node
        WITH company, focus_node, fact, src, dst, source_concepts, target_concepts, matched_terms, chunk, source_doc
        ORDER BY company.name, focus_node.id,
                 CASE coalesce(fact.layer, 'coverage') WHEN 'insight' THEN 1 ELSE 0 END DESC,
                 coalesce(fact.confidence, 0.0) DESC,
                 src.name, fact.relation_type, dst.name
        WITH company,
             focus_node,
             count(DISTINCT fact) AS node_degree,
             count(DISTINCT chunk) AS evidence_count,
             collect(DISTINCT {
               fact_id: fact.id,
               document: source_doc.id,
               source_url: source_doc.source_url,
               company: company.name,
               ticker: company.ticker,
               source_id: src.id,
               source: src.name,
               source_type: src.entity_type,
               source_properties: CASE WHEN src.value IS NULL AND src.context IS NULL THEN {} ELSE src { .value, .context } END,
               source_concepts: source_concepts,
               relation: fact.relation_type,
               relation_layer: coalesce(fact.layer, 'coverage'),
               target_id: dst.id,
               target: dst.name,
               target_type: dst.entity_type,
               target_properties: CASE WHEN dst.value IS NULL AND dst.context IS NULL THEN {} ELSE dst { .value, .context } END,
               target_concepts: target_concepts,
               matched_terms: matched_terms,
               evidence: fact.evidence_text,
               confidence: fact.confidence,
               chunk_id: chunk.id,
               chunk_preview: coalesce(chunk.text_preview, chunk.text),
               chunk_text: chunk.text
             }) AS rows
        WHERE company IS NOT NULL
          AND node_degree > 0
          AND coalesce(focus_node.entity_type, '') <> 'Company'
        WITH company,
             {
               focus_node: focus_node,
               node_degree: node_degree,
               evidence_count: evidence_count,
               rows: rows
             } AS node_summary
        ORDER BY company.name, node_summary.node_degree DESC, node_summary.evidence_count DESC,
                 toLower(coalesce(node_summary.focus_node.name, ''))
        WITH company, collect(node_summary)[0..$nodes_per_company] AS top_nodes
        UNWIND top_nodes AS node_summary
        WITH company,
             node_summary.focus_node AS focus_node,
             node_summary.node_degree AS node_degree,
             node_summary.evidence_count AS evidence_count,
             node_summary.rows[0..$chunks_per_node] AS selected_rows
        UNWIND selected_rows AS row
        WITH company, focus_node, node_degree, evidence_count, row
        WHERE coalesce(row.chunk_text, row.chunk_preview, row.evidence, '') <> ''
        RETURN company.name AS focus_company,
               company.ticker AS focus_ticker,
               focus_node.id AS focus_node_id,
               focus_node.name AS focus_node,
               focus_node.entity_type AS focus_node_type,
               node_degree,
               1 AS company_count,
               evidence_count,
               row.fact_id AS fact_id,
               row.document AS document,
               row.source_url AS source_url,
               row.company AS company,
               row.ticker AS ticker,
               row.source_id AS source_id,
               row.source AS source,
               row.source_type AS source_type,
               row.source_properties AS source_properties,
               row.source_concepts AS source_concepts,
               row.relation AS relation,
               row.relation_layer AS relation_layer,
               row.target_id AS target_id,
               row.target AS target,
               row.target_type AS target_type,
               row.target_properties AS target_properties,
               row.target_concepts AS target_concepts,
               row.matched_terms AS matched_terms,
               row.evidence AS evidence,
               row.confidence AS confidence,
               row.chunk_id AS chunk_id,
               row.chunk_preview AS chunk_preview,
               row.chunk_text AS chunk_text
        ORDER BY company.name, node_degree DESC, evidence_count DESC,
                 row.source, row.relation, row.target
        LIMIT $limit
        """,
        {
            "terms": terms,
            "limit": limit,
            "company_ticker": company_ticker,
            "nodes_per_company": nodes_per_company,
            "chunks_per_node": chunks_per_node,
        },
    )


def result_limit_slider_config(available_count: int, default: int = 80) -> tuple[int, int, int, int]:
    """Return Streamlit slider min/max/default/step from available graph rows."""

    max_value = max(1, int(available_count or 0))
    value = min(default, max_value)
    step = 1 if max_value <= 20 else 10
    return 1, max_value, value, step


def result_limit_slider_enabled(available_count: int) -> bool:
    """Return whether Streamlit can render a meaningful Result limit slider."""

    return int(available_count or 0) > 1


def filter_payload_by_min_node_degree(
    payload: dict[str, list[dict[str, Any]]],
    min_degree: int = 1,
) -> dict[str, list[dict[str, Any]]]:
    """Return a graph payload containing only nodes with enough graph connections.

    Degree is calculated from the currently fetched relation/schema edges. Company
    context hub edges are preserved for retained nodes, but they do not make an
    otherwise one-hop relation node pass the filter.
    """

    if min_degree <= 1:
        return payload

    nodes = [node for node in payload.get("nodes", []) if node.get("id")]
    node_ids = {node.get("id") for node in nodes}
    relation_edges = [
        edge
        for edge in payload.get("edges", [])
        if edge.get("source") in node_ids
        and edge.get("target") in node_ids
        and edge.get("layer") != "company_scope"
    ]
    degree: dict[str, int] = {}
    for edge in relation_edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target:
            continue
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1

    retained_relation_node_ids = {node_id for node_id, count in degree.items() if count >= min_degree}
    retained_edges = [
        edge
        for edge in relation_edges
        if edge.get("source") in retained_relation_node_ids and edge.get("target") in retained_relation_node_ids
    ]
    displayed_ids = set(retained_relation_node_ids)

    context_edges = [
        edge
        for edge in payload.get("edges", [])
        if edge.get("layer") == "company_scope"
        and (edge.get("source") in displayed_ids or edge.get("target") in displayed_ids)
    ]
    for edge in context_edges:
        displayed_ids.add(edge.get("source"))
        displayed_ids.add(edge.get("target"))

    return {
        "nodes": [node for node in nodes if node.get("id") in displayed_ids],
        "edges": retained_edges + context_edges,
    }


@st.cache_data(ttl=60)
def graph_payload(search: str = "", limit: int = 100, company_ticker: str = "") -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    if company_ticker:
        rows, error = relation_fact_rows(search, limit, company_ticker)
    else:
        rows, error = balanced_relation_fact_rows(search, limit)
    if error:
        return {"nodes": [], "edges": []}, error
    payload = relation_rows_to_graph(rows)
    if company_ticker:
        payload = add_company_context_node(payload, rows, company_ticker)
    return payload, None


def add_company_context_node(
    payload: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
    company_ticker: str,
) -> dict[str, list[dict[str, Any]]]:
    company_name = next((str(row.get("company") or "") for row in rows if row.get("company")), company_ticker)
    company_node_id = f"company:{company_ticker}"
    nodes = list(payload.get("nodes", []))
    edges = list(payload.get("edges", []))
    node_ids = {node.get("id") for node in nodes}
    if company_node_id not in node_ids:
        nodes.append(
            {
                "id": company_node_id,
                "label": company_name,
                "type": "Company",
                "properties": {"ticker": company_ticker, "context": "Selected company graph scope"},
            }
        )
    connected_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in ("source_id", "target_id"):
            node_id = row.get(key)
            if node_id and node_id in node_ids and node_id not in seen:
                seen.add(node_id)
                connected_ids.append(str(node_id))
    for node_id in connected_ids[:24]:
        edges.append(
            {
                "id": f"{company_node_id}->HAS_CONTEXT->{node_id}",
                "source": company_node_id,
                "target": node_id,
                "label": "HAS_CONTEXT",
                "layer": "company_scope",
                "company": company_name,
                "ticker": company_ticker,
                "evidence": f"{company_name} company-specific graph context.",
            }
        )
    return {"nodes": nodes, "edges": edges}




@st.cache_data(ttl=60)
def ontology_relation_rows(search: str = "", limit: int = 100, company_ticker: str = "") -> tuple[list[dict[str, Any]], str | None]:
    terms = query_terms(search)
    return neo4j_query(
        """
        CALL {
          WITH $terms AS terms, $company_ticker AS company_ticker
          MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity)-[:MAPS_TO]->(src_concept:OntologyConcept),
                (fact)-[:TO_ENTITY]->(dst:Entity)-[:MAPS_TO]->(dst_concept:OntologyConcept)
          WITH fact, src, dst, src_concept, dst_concept, company_ticker,
               [term IN terms WHERE
                  toLower(src_concept.name) CONTAINS term
               OR toLower(dst_concept.name) CONTAINS term
               OR toLower(coalesce(src_concept.description, '')) CONTAINS term
               OR toLower(coalesce(dst_concept.description, '')) CONTAINS term
               OR toLower(src.name) CONTAINS term
               OR toLower(dst.name) CONTAINS term
               OR toLower(coalesce(fact.evidence_text, '')) CONTAINS term
               OR toLower(fact.relation_type) CONTAINS term] AS matched_terms
          WHERE src_concept.id <> dst_concept.id
            AND (size(terms) = 0 OR size(matched_terms) > 0)
          OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
          WITH src_concept, dst_concept, src, dst, fact, matched_terms, chunk, source_doc, company, company_ticker
          WHERE company_ticker = '' OR company.ticker = company_ticker
          WITH src_concept, dst_concept, fact.relation_type AS relation,
               collect(DISTINCT company.name) AS companies,
               collect(DISTINCT source_doc.id) AS documents,
               collect(DISTINCT src.name)[0..6] AS source_entities,
               collect(DISTINCT dst.name)[0..6] AS target_entities,
               count(DISTINCT fact) AS fact_count,
               count(DISTINCT chunk) AS evidence_count,
               avg(coalesce(fact.confidence, 0.0)) AS confidence,
               collect(DISTINCT fact.evidence_text)[0] AS evidence
          RETURN 'ontology-' + src_concept.id + '-' + relation + '-' + dst_concept.id AS fact_id,
                 src_concept.id AS source_id,
                 src_concept.name AS source,
                 'OntologyConcept' AS source_type,
                 {concept_type: src_concept.concept_type, description: src_concept.description, aliases: src_concept.aliases, entities: source_entities, entity_count: size(source_entities)} AS source_properties,
                 relation AS relation,
                 'ontology' AS relation_layer,
                 dst_concept.id AS target_id,
                 dst_concept.name AS target,
                 'OntologyConcept' AS target_type,
                 {concept_type: dst_concept.concept_type, description: dst_concept.description, aliases: dst_concept.aliases, entities: target_entities, entity_count: size(target_entities)} AS target_properties,
                 evidence AS evidence,
                 confidence AS confidence,
                 companies AS company,
                 documents AS document,
                 fact_count AS fact_count,
                 evidence_count AS evidence_count,
                 '' AS ticker,
                 '' AS source_url,
                 '' AS chunk_id,
                 '' AS chunk_preview,
                 '' AS chunk_text
          UNION
          WITH $terms AS terms, $company_ticker AS company_ticker
          MATCH (src_concept:OntologyConcept)-[schema_rel]->(dst_concept:OntologyConcept)
          WHERE coalesce(schema_rel.layer, '') = 'ontology_schema'
          OPTIONAL MATCH (company:Company {ticker: company_ticker})<-[:ABOUT_COMPANY]-(:SourceDocument)-[:HAS_CHUNK]->(:MarkdownChunk)<-[:SUPPORTED_BY]-(:RelationFact)-[:FROM_ENTITY|TO_ENTITY]->(:Entity)-[:MAPS_TO]->(mapped_concept:OntologyConcept)
          WITH src_concept, dst_concept, schema_rel, type(schema_rel) AS relation, terms, company_ticker,
               collect(DISTINCT mapped_concept.id) AS directly_mapped_concept_ids
          OPTIONAL MATCH path = (mapped_concept:OntologyConcept)-[*0..4]->(ancestor:OntologyConcept)
          WHERE mapped_concept.id IN directly_mapped_concept_ids
            AND all(rel IN relationships(path) WHERE coalesce(rel.layer, '') = 'ontology_schema')
          WITH src_concept, dst_concept, schema_rel, relation, terms, company_ticker,
               directly_mapped_concept_ids,
               collect(DISTINCT ancestor.id) AS ancestor_concept_ids
          WITH src_concept, dst_concept, schema_rel, relation, terms, company_ticker,
               directly_mapped_concept_ids + ancestor_concept_ids AS relevant_concept_ids
          WHERE company_ticker = ''
             OR (src_concept.id IN relevant_concept_ids AND dst_concept.id IN relevant_concept_ids)
          WITH src_concept, dst_concept, schema_rel, relation, terms,
               [term IN terms WHERE
                  toLower(src_concept.name) CONTAINS term
               OR toLower(dst_concept.name) CONTAINS term
               OR toLower(coalesce(src_concept.description, '')) CONTAINS term
               OR toLower(coalesce(dst_concept.description, '')) CONTAINS term
               OR toLower(coalesce(schema_rel.description, '')) CONTAINS term
               OR toLower(type(schema_rel)) CONTAINS term] AS matched_terms
          RETURN 'ontology-schema-' + src_concept.id + '-' + relation + '-' + dst_concept.id AS fact_id,
                 src_concept.id AS source_id,
                 src_concept.name AS source,
                 'OntologyConcept' AS source_type,
                 {concept_type: src_concept.concept_type, description: src_concept.description, aliases: src_concept.aliases, entities: [], entity_count: 0} AS source_properties,
                 relation AS relation,
                 'ontology_schema' AS relation_layer,
                 dst_concept.id AS target_id,
                 dst_concept.name AS target,
                 'OntologyConcept' AS target_type,
                 {concept_type: dst_concept.concept_type, description: dst_concept.description, aliases: dst_concept.aliases, entities: [], entity_count: 0} AS target_properties,
                 schema_rel.description AS evidence,
                 null AS confidence,
                 [] AS company,
                 [] AS document,
                 null AS fact_count,
                 null AS evidence_count,
                 '' AS ticker,
                 '' AS source_url,
                 '' AS chunk_id,
                 '' AS chunk_preview,
                 '' AS chunk_text
        }
        RETURN *
        ORDER BY CASE
                   WHEN relation_layer = 'ontology_schema' AND relation IN ['IS_A', 'PART_OF'] THEN 2
                   WHEN relation_layer = 'ontology_schema' THEN 1
                   ELSE 0
                 END DESC,
                 coalesce(fact_count, 0) DESC, coalesce(evidence_count, 0) DESC,
                 coalesce(confidence, 0.0) DESC, source, relation, target
        LIMIT $limit
        """,
        {"terms": terms, "limit": limit, "company_ticker": company_ticker},
    )


@st.cache_data(ttl=60)
def ontology_relation_count(search: str = "", company_ticker: str = "") -> tuple[int, str | None]:
    rows, error = ontology_relation_rows(search, limit=10000, company_ticker=company_ticker)
    if error:
        return 0, error
    return len(rows), None


def graph_result_count(graph_view: str, search: str = "", company_ticker: str = "") -> tuple[int, str | None]:
    """Return the current graph search/scope's maximum renderable relation-row count."""

    if graph_view == "Ontology concepts":
        return ontology_relation_count(search, company_ticker)
    return relation_fact_count(search, company_ticker)

@st.cache_data(ttl=60)
def ontology_graph_payload(search: str = "", limit: int = 100, company_ticker: str = "") -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    rows, error = ontology_relation_rows(search, limit, company_ticker)
    if error:
        return {"nodes": [], "edges": []}, error
    return relation_rows_to_graph(rows), None


@st.cache_data(ttl=60)
def ontology_concept_options() -> tuple[list[dict[str, Any]], str | None]:
    return neo4j_query(
        """
        MATCH (concept:OntologyConcept)
        OPTIONAL MATCH (entity:Entity)-[:MAPS_TO]->(concept)
        OPTIONAL MATCH (source:OntologyConcept)-[incoming]->(concept)
        WHERE incoming.layer = 'ontology_schema' OR incoming IS NULL
        OPTIONAL MATCH (concept)-[outgoing]->(target:OntologyConcept)
        WHERE outgoing.layer = 'ontology_schema' OR outgoing IS NULL
        RETURN concept.id AS concept_id,
               concept.name AS name,
               concept.concept_type AS concept_type,
               coalesce(concept.description, '') AS description,
               count(DISTINCT entity) AS mapped_entities,
               count(DISTINCT source) + count(DISTINCT target) AS linked_concepts
        ORDER BY mapped_entities DESC, linked_concepts DESC, name
        """,
        {},
    )


@st.cache_data(ttl=60)
def ontology_concept_context(concept_id: str, limit: int = 80) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    rows, error = neo4j_query(
        """
        MATCH (concept:OntologyConcept {id: $concept_id})
        CALL {
          WITH concept
          OPTIONAL MATCH (concept)-[outgoing]->(target:OntologyConcept)
          WHERE outgoing.layer = 'ontology_schema'
          RETURN collect({
            direction: 'out',
            relation: type(outgoing),
            concept: target.name,
            concept_type: target.concept_type,
            description: coalesce(outgoing.description, '')
          }) AS outgoing_rows
        }
        CALL {
          WITH concept
          OPTIONAL MATCH (source:OntologyConcept)-[incoming]->(concept)
          WHERE incoming.layer = 'ontology_schema'
          RETURN collect({
            direction: 'in',
            relation: type(incoming),
            concept: source.name,
            concept_type: source.concept_type,
            description: coalesce(incoming.description, '')
          }) AS incoming_rows
        }
        CALL {
          WITH concept
          OPTIONAL MATCH (entity:Entity)-[mapped:MAPS_TO]->(concept)
          OPTIONAL MATCH (entity)<-[:FROM_ENTITY|TO_ENTITY]-(fact:RelationFact)
          OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
          WITH entity, mapped, count(DISTINCT fact) AS relation_count, collect(DISTINCT company.name)[0..5] AS companies
          WHERE entity IS NOT NULL
          RETURN collect({
            entity: entity.name,
            entity_type: entity.entity_type,
            confidence: mapped.confidence,
            matched_alias: mapped.matched_alias,
            relation_count: relation_count,
            companies: companies
          })[0..$limit] AS entity_rows
        }
        CALL {
          WITH concept
          OPTIONAL MATCH (entity:Entity)-[:MAPS_TO]->(concept)
          OPTIONAL MATCH (fact:RelationFact)-[:FROM_ENTITY|TO_ENTITY]->(entity)
          OPTIONAL MATCH (fact)-[:FROM_ENTITY]->(src:Entity)
          OPTIONAL MATCH (fact)-[:TO_ENTITY]->(dst:Entity)
          OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
          WITH fact, src, dst, chunk, source_doc, company
          WHERE fact IS NOT NULL
          RETURN collect({
            company: company.name,
            ticker: company.ticker,
            source: src.name,
            relation: fact.relation_type,
            target: dst.name,
            evidence: fact.evidence_text,
            chunk_preview: coalesce(chunk.text_preview, chunk.text),
            document: source_doc.id
          })[0..$limit] AS relation_rows
        }
        RETURN concept.id AS concept_id,
               concept.name AS name,
               concept.concept_type AS concept_type,
               coalesce(concept.description, '') AS description,
               outgoing_rows + incoming_rows AS linked_concepts,
               entity_rows AS entities,
               relation_rows AS relations
        """,
        {"concept_id": concept_id, "limit": limit},
    )
    if error:
        return {"concept": [], "linked_concepts": [], "entities": [], "relations": []}, error
    if not rows:
        return {"concept": [], "linked_concepts": [], "entities": [], "relations": []}, None
    row = rows[0]
    return {
        "concept": [
            {
                "name": row.get("name"),
                "concept_type": row.get("concept_type"),
                "description": row.get("description"),
            }
        ],
        "linked_concepts": [item for item in row.get("linked_concepts", []) if item.get("concept")],
        "entities": [item for item in row.get("entities", []) if item.get("entity")],
        "relations": [item for item in row.get("relations", []) if item.get("source") or item.get("target")],
    }, None


@st.cache_data(ttl=60)
def ontology_concept_chunks(concept_id: str, limit: int = 16, company_ticker: str = "") -> tuple[dict[str, Any], str | None]:
    rows, error = neo4j_query(
        """
        MATCH (concept:OntologyConcept {id: $concept_id})
        OPTIONAL MATCH (entity:Entity)-[:MAPS_TO]->(concept)
        OPTIONAL MATCH (fact:RelationFact)-[:FROM_ENTITY|TO_ENTITY]->(entity)
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
        WITH concept, entity, fact, chunk, source_doc, company
        WHERE $company_ticker = '' OR company.ticker = $company_ticker
        WITH concept,
             chunk,
             source_doc,
             company,
             collect(DISTINCT entity.name)[0..6] AS matched_entities,
             collect(DISTINCT fact.relation_type)[0..6] AS relation_types,
             count(DISTINCT fact) AS relation_count
        WHERE chunk IS NOT NULL
        RETURN concept.id AS concept_id,
               concept.name AS name,
               concept.concept_type AS concept_type,
               coalesce(concept.description, '') AS description,
               chunk.id AS chunk_id,
               chunk.index AS chunk_index,
               chunk.text AS chunk_text,
               coalesce(chunk.text_preview, chunk.text) AS chunk_preview,
               source_doc.id AS document,
               company.name AS company,
               company.ticker AS ticker,
               matched_entities,
               relation_types,
               relation_count
        ORDER BY relation_count DESC, company.name, source_doc.id, chunk.index
        LIMIT $limit
        """,
        {"concept_id": concept_id, "limit": limit, "company_ticker": company_ticker},
    )
    if error:
        return {"concept": {}, "chunks": []}, error
    concept = {}
    if rows:
        first = rows[0]
        concept = {
            "concept_id": first.get("concept_id"),
            "name": first.get("name"),
            "concept_type": first.get("concept_type"),
            "description": first.get("description"),
        }
    return {"concept": concept, "chunks": unique_chunk_rows(rows, limit=limit)}, None


def ontology_concept_select_options(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {
        f"{row.get('name')} ({row.get('concept_type')}) · {row.get('mapped_entities', 0)} mapped": str(row.get("concept_id"))
        for row in rows
        if row.get("concept_id") and row.get("name")
    }


def selected_query_param(name: str) -> str:
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def synced_ontology_concept_selection(concept_options: dict[str, str]) -> tuple[str, str, int]:
    """Return the Streamlit/query-param synchronized ontology concept selection."""

    if not concept_options:
        return "", "", 0
    concept_labels = list(concept_options)
    concept_id_to_label = {concept_id: label for label, concept_id in concept_options.items()}
    query_concept_id = selected_query_param("ontology_concept")
    last_query_concept_id = str(st.session_state.get("_ontology_concept_query", ""))
    session_label = str(st.session_state.get("ontology_concept_inspector", ""))
    session_concept_id = concept_options.get(session_label, "")

    selected_concept_id = ""
    if query_concept_id in concept_id_to_label and query_concept_id != last_query_concept_id:
        selected_concept_id = query_concept_id
        st.session_state["_ontology_concept_query"] = query_concept_id
        st.session_state["ontology_concept_inspector"] = concept_id_to_label[query_concept_id]
    elif session_concept_id:
        selected_concept_id = session_concept_id
    elif query_concept_id in concept_id_to_label:
        selected_concept_id = query_concept_id
        st.session_state["_ontology_concept_query"] = query_concept_id
    else:
        selected_concept_id = concept_options[concept_labels[0]]

    selected_label = concept_id_to_label[selected_concept_id]
    selected_index = concept_labels.index(selected_label)
    return selected_concept_id, selected_label, selected_index


def ontology_click_bridge_value() -> dict[str, Any]:
    result = ONTOLOGY_CLICK_BRIDGE(
        key="ontology_click_bridge",
        data={"channel": "earnings_call_graph:ontologyNodeClick"},
        default={},
        height=0,
        on_selected_node_id_change=lambda: None,
        on_selection_change=lambda: None,
    )
    selection = getattr(result, "selection", None)
    if isinstance(selection, dict):
        return selection
    node_id = str(getattr(result, "selected_node_id", "") or "")
    return {"node_id": node_id} if node_id else {}


@st.cache_data(ttl=60)
def key_node_rows(limit: int = 30) -> tuple[list[dict[str, Any]], str | None]:
    return neo4j_query(
        """
        MATCH (entity:Entity)
        WHERE coalesce(entity.entity_type, '') <> 'Company'
        OPTIONAL MATCH (entity)<-[:FROM_ENTITY|TO_ENTITY]-(fact:RelationFact)
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
        OPTIONAL MATCH (entity)-[:MAPS_TO]->(concept:OntologyConcept)
        WITH entity,
             count(DISTINCT fact) AS relation_count,
             count(DISTINCT CASE WHEN fact.layer = 'insight' THEN fact END) AS insight_count,
             count(DISTINCT company) AS company_count,
             count(DISTINCT chunk) AS evidence_count,
             avg(coalesce(fact.confidence, 0.0)) AS avg_confidence,
             collect(DISTINCT concept.name) AS concepts
        WHERE relation_count > 0
        WITH entity, relation_count, insight_count, company_count, evidence_count, coalesce(avg_confidence, 0.0) AS avg_confidence, concepts,
             CASE entity.entity_type
               WHEN 'Theme' THEN 8
               WHEN 'MetricValue' THEN 8
               WHEN 'Metric' THEN 7
               WHEN 'BusinessOutcome' THEN 7
               WHEN 'Risk' THEN 7
               WHEN 'Product' THEN 6
               WHEN 'BusinessSegment' THEN 5
               ELSE 1
             END AS type_weight,
             CASE WHEN entity.value IS NULL THEN 0 ELSE 3 END +
             CASE WHEN entity.context IS NULL THEN 0 ELSE 1 END +
             (size(concepts) * 2) AS property_weight
        RETURN entity.id AS node_id,
               entity.name AS name,
               entity.entity_type AS entity_type,
               CASE WHEN entity.value IS NULL AND entity.context IS NULL THEN {} ELSE entity { .value, .context } END AS properties,
               concepts,
               relation_count,
               insight_count,
               company_count,
               evidence_count,
               avg_confidence,
               ((insight_count * 6) + relation_count + (company_count * 3) + evidence_count + type_weight + property_weight + avg_confidence) AS score
        ORDER BY score DESC, insight_count DESC, company_count DESC, relation_count DESC, name ASC
        LIMIT $limit
        """,
        {"limit": limit},
    )

@st.cache_data(ttl=60)
def node_context_rows(node_id: str, limit: int = 30) -> tuple[list[dict[str, Any]], str | None]:
    return neo4j_query(
        """
        MATCH (entity:Entity {id: $node_id})
        OPTIONAL MATCH (entity)-[:MAPS_TO]->(node_concept:OntologyConcept)
        WITH entity, collect(DISTINCT node_concept.name) AS node_concepts
        MATCH (fact:RelationFact)-[:FROM_ENTITY|TO_ENTITY]->(entity)
        MATCH (fact)-[:FROM_ENTITY]->(src:Entity)
        MATCH (fact)-[:TO_ENTITY]->(dst:Entity)
        OPTIONAL MATCH (src)-[:MAPS_TO]->(src_concept:OntologyConcept)
        OPTIONAL MATCH (dst)-[:MAPS_TO]->(dst_concept:OntologyConcept)
        WITH entity, node_concepts, fact, src, dst,
             collect(DISTINCT src_concept.name) AS source_concepts,
             collect(DISTINCT dst_concept.name) AS target_concepts
        OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
        RETURN entity.id AS node_id,
               entity.name AS node_name,
               entity.entity_type AS node_type,
               CASE WHEN entity.value IS NULL AND entity.context IS NULL THEN {} ELSE entity { .value, .context } END AS node_properties,
               node_concepts,
               src.name AS source,
               src.entity_type AS source_type,
               CASE WHEN src.value IS NULL AND src.context IS NULL THEN {} ELSE src { .value, .context } END AS source_properties,
               source_concepts,
               fact.relation_type AS relation,
               coalesce(fact.layer, 'coverage') AS relation_layer,
               dst.name AS target,
               dst.entity_type AS target_type,
               CASE WHEN dst.value IS NULL AND dst.context IS NULL THEN {} ELSE dst { .value, .context } END AS target_properties,
               target_concepts,
               fact.evidence_text AS evidence,
               fact.confidence AS confidence,
               chunk.id AS chunk_id,
               coalesce(chunk.text_preview, chunk.text) AS chunk_preview,
               chunk.text AS chunk_text,
               company.name AS company,
               company.ticker AS ticker,
               source_doc.id AS document,
               source_doc.source_url AS source_url
        ORDER BY CASE coalesce(fact.layer, 'coverage') WHEN 'insight' THEN 1 ELSE 0 END DESC,
                 coalesce(fact.confidence, 0.0) DESC, company, source, relation, target
        LIMIT $limit
        """,
        {"node_id": node_id, "limit": limit},
    )

def truncate(value: Any, limit: int = 64) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "."


def _vis_graph_data(
    payload: dict[str, list[dict[str, Any]]],
    *,
    max_edges: int = 120,
    hierarchical: bool = False,
    min_node_degree: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = filter_payload_by_min_node_degree(payload, min_node_degree)
    raw_nodes = [node for node in payload.get("nodes", []) if node.get("id")]
    node_ids = {node["id"] for node in raw_nodes}
    candidate_edges = [
        edge
        for edge in payload.get("edges", [])[:max_edges]
        if edge.get("source") in node_ids and edge.get("target") in node_ids
    ]
    schema_edges = [
        edge
        for edge in candidate_edges
        if edge.get("layer") == "ontology_schema" and str(edge.get("label") or "") in ONTOLOGY_HIERARCHY_RELATIONS
    ]
    raw_edges = schema_edges if hierarchical and schema_edges else candidate_edges
    if hierarchical and schema_edges:
        schema_node_ids = {edge.get("source") for edge in raw_edges} | {edge.get("target") for edge in raw_edges}
        raw_nodes = [node for node in raw_nodes if node.get("id") in schema_node_ids]
    degree: dict[str, int] = {}
    for edge in raw_edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    nodes = []
    for node in raw_nodes:
        node_id = node["id"]
        node_type = node.get("type") or "Entity"
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        value = properties.get("value")
        context = properties.get("context")
        label = str(node.get("label") or node_id)
        nodes.append(
            {
                "id": node_id,
                "label": truncate(label, 34),
                "group": node_type,
                "shape": "box" if node_type == "OntologyConcept" else "dot",
                "size": min(42, 18 + degree.get(node_id, 0) * 5),
                "color": {
                    "background": _node_fill(node_type),
                    "border": _border_color(node_type),
                    "highlight": {"background": "#1C1C20", "border": "#E5484D"},
                },
                "properties": properties,
                "title": _node_tooltip(label, node_type, value=value, context=context, degree=degree.get(node_id, 0), properties=properties),
            }
        )

    edges = []
    for edge in raw_edges:
        relation = edge.get("label") or "RELATED_TO"
        layer = edge.get("layer") or "coverage"
        source_url = edge.get("source_url") or ""
        evidence = edge.get("evidence") or edge.get("chunk_preview") or ""
        edges.append(
            {
                "id": edge.get("id") or f"{edge.get('source')}->{relation}->{edge.get('target')}",
                "from": edge.get("source"),
                "to": edge.get("target"),
                "label": relation if relation in {"DRIVES", "INCREASES", "PRESSURES", "REDUCES", "CONVERTS_TO", "AFFECTS", "DISCUSSES", "ASSOCIATED_WITH", "EXPOSED_TO", "IS_A", "PART_OF", "FUNDS", "DRIVES_SCHEMA", "HAS_METRIC", "CAN_PRESSURE", "HAS_CONTEXT"} else "",
                "color": {"color": _edge_color(relation, bool(source_url), layer), "highlight": "#E5484D"},
                "width": 3.0 if layer in {"insight", "ontology_schema"} else 1.5,
                "dashes": layer == "coverage",
                "source_url": source_url,
                "layer": layer,
                "evidence": evidence,
                "chunk_preview": edge.get("chunk_preview") or "",
                "chunk_text": edge.get("chunk_text") or "",
                "chunk_id": edge.get("chunk_id") or "",
                "document": edge.get("document") or "",
                "company": edge.get("company") or "",
                "confidence": edge.get("confidence"),
                "fact_count": edge.get("fact_count"),
                "evidence_count": edge.get("evidence_count"),
                "title": _edge_tooltip(relation, evidence=evidence, source_url=source_url, confidence=edge.get("confidence")),
            }
        )
    return nodes, edges


def _node_tooltip(label: str, node_type: str, *, value: Any = "", context: Any = "", degree: int = 0, properties: dict[str, Any] | None = None) -> str:
    props = properties or {}
    lines = [f"<b>{escape(label)}</b>", f"Type: {escape(node_type)}", f"Connections: {degree}"]
    if props.get("concept_type"):
        lines.append(f"Concept type: {escape(str(props.get('concept_type')))}")
    if value:
        lines.append(f"Value: {escape(str(value))}")
    if context:
        lines.append(f"Context: {escape(str(context))}")
    if props.get("description"):
        lines.append(escape(truncate(props.get("description"), 180)))
    if props.get("entities"):
        lines.append("Entities: " + escape(truncate(", ".join(map(str, props.get("entities") or [])), 160)))
    return "<br>".join(lines)


def _node_fill(node_type: str) -> str:
    if node_type == "OntologyConcept":
        return "#252A32"
    if node_type in {"Theme", "Risk", "BusinessOutcome"}:
        return "#22262E"
    return "#1E2229"


def _edge_tooltip(relation: str, *, evidence: Any = "", source_url: str = "", confidence: Any = None) -> str:
    lines = [f"<b>{escape(relation)}</b>"]
    if isinstance(confidence, int | float):
        lines.append(f"Confidence: {confidence:.2f}")
    if evidence:
        lines.append(escape(truncate(evidence, 260)))
    if source_url:
        lines.append("<br><i>Source URL is stored; node click shows linked chunks here.</i>")
    return "<br>".join(lines)


def _border_color(node_type: str) -> str:
    return {
        "Theme": "#E5484D",
        "Metric": "#7C8CFF",
        "MetricValue": "#38BDF8",
        "BusinessOutcome": "#F5C542",
        "Risk": "#F97316",
        "BusinessSegment": "#A78BFA",
        "Product": "#22D3EE",
        "Company": "#27B884",
        "OntologyConcept": "#E5484D",
    }.get(node_type, "#8A8A90")


def _edge_color(relation: str, has_source: bool, layer: str = "coverage") -> str:
    if layer == "ontology_schema":
        return "#E5484D"
    if layer == "ontology":
        return "#A78BFA"
    if layer == "company_scope":
        return "#27B884"
    if layer == "coverage":
        return "#5A5A60"
    if relation in RISK_RELATIONS:
        return "#F97316"
    if relation in BULLISH_RELATIONS:
        return "#27B884" if has_source else "#5EEAD4"
    return "#A0A0A8"


def interactive_graph_html(
    payload: dict[str, list[dict[str, Any]]],
    *,
    height: int = 620,
    max_edges: int = 120,
    hierarchical: bool = False,
    min_node_degree: int = 1,
    selected_node_id: str = "",
    sync_ontology_selection: bool = False,
    open_selected_details: bool = False,
    viewport: dict[str, Any] | None = None,
) -> str:
    nodes, edges = _vis_graph_data(
        payload,
        max_edges=max_edges,
        hierarchical=hierarchical,
        min_node_degree=min_node_degree,
    )
    layout_options = (
        {
            "hierarchical": {
                "enabled": True,
                "direction": "DU",
                "sortMethod": "directed",
                "levelSeparation": 155,
                "nodeSpacing": 220,
                "treeSpacing": 280,
                "blockShifting": True,
                "edgeMinimization": True,
                "parentCentralization": True,
            }
        }
        if hierarchical
        else {"improvedLayout": True}
    )
    physics_options = (
        {"enabled": False}
        if hierarchical
        else {
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -52,
                "centralGravity": 0.018,
                "springLength": 175,
                "springConstant": 0.075,
                "damping": 0.62,
            },
            "stabilization": {"iterations": 180, "updateInterval": 20},
        }
    )
    stabilization_script = "" if hierarchical else "network.once('stabilizationIterationsDone', () => network.setOptions({ physics: false }));"
    return f"""
<!doctype html>
<html><head><meta charset="utf-8" />
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
html, body {{ margin:0; padding:0; font-family: Inter, Arial, sans-serif; background:#14161A; color:#F4F6F8; }}
#graph-wrap {{ position:relative; height:{height - 8}px; border:1px solid #4B5563; border-radius:10px; overflow:hidden; background:radial-gradient(900px 500px at 58% 34%, rgba(229,72,77,.10), transparent 62%), linear-gradient(180deg, #2A3038 0%, #242A32 100%); }}
#graph {{ width:100%; height:100%; }}
#toolbar {{ position:absolute; top:12px; left:12px; z-index:10; display:flex; gap:8px; align-items:center; background:rgba(32,36,43,.94); border:1px solid #49515F; border-radius:8px; padding:7px 10px; box-shadow:0 10px 30px rgba(0,0,0,.30); backdrop-filter: blur(8px); }}
#toolbar button {{ border:1px solid #5A6372; background:#282D35; color:#F4F6F8; border-radius:6px; padding:5px 10px; cursor:pointer; font-weight:650; }}
#toolbar button:hover {{ border-color:#E5484D; color:#E5484D; }}
#hint {{ color:#C6CBD3; font-size:11px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
#details {{ position:absolute; top:0; right:0; z-index:20; width:min(430px, 44%); height:100%; background:rgba(26,29,34,.98); border-left:1px solid #343A45; box-shadow:-18px 0 40px rgba(0,0,0,.40); transform:translateX(105%); transition:transform .22s ease; display:flex; flex-direction:column; }}
#details.open {{ transform:translateX(0); }}
#details-header {{ padding:16px 16px 10px; border-bottom:1px solid #343A45; }}
#details-title {{ font-size:17px; font-weight:750; color:#F4F6F8; margin-right:28px; }}
#details-subtitle {{ color:#C6CBD3; font-size:12px; margin-top:4px; }}
#details-close {{ position:absolute; top:12px; right:12px; border:1px solid #49515F; background:#20242B; color:#C6CBD3; border-radius:6px; width:28px; height:28px; cursor:pointer; font-weight:700; }}
#details-close:hover {{ color:#EDEDEF; border-color:#E5484D; }}
#details-body {{ overflow:auto; padding:12px 16px 18px; }}
.chunk-card {{ border:1px solid #343A45; border-left:3px solid #E5484D; border-radius:8px; padding:11px 12px; margin-bottom:10px; background:#20242B; box-shadow:0 10px 26px rgba(0,0,0,.22); }}
.chunk-path {{ font-weight:700; color:#F4F6F8; font-size:13px; margin-bottom:7px; }}
.chunk-meta {{ color:#9098A4; font-size:11px; margin-bottom:7px; }}
.chunk-evidence {{ color:#E4E7EB; line-height:1.45; font-size:13px; white-space:pre-wrap; overflow-wrap:anywhere; word-break:break-word; }}
.pill {{ display:inline-block; border-radius:4px; padding:2px 7px; margin-right:4px; background:rgba(229,72,77,.14); color:#FCA5A5; font-size:11px; font-weight:650; }}
.vis-tooltip {{ position:absolute; max-width:420px; white-space:normal !important; line-height:1.35; padding:10px 12px !important; border-radius:10px !important; border:1px solid #49515F !important; background:#20242B !important; color:#F4F6F8 !important; box-shadow:0 10px 30px rgba(0,0,0,.45); font-family:Inter,Arial,sans-serif !important; }}
</style></head>
<body>
<div id="graph-wrap">
  <div id="toolbar"><button id="fit">Fit</button><button id="physics">Freeze</button><span id="hint">wheel=zoom · drag background=pan · drag node=move · click node=chunks</span></div>
  <aside id="details" aria-live="polite">
    <button id="details-close" title="Close">×</button>
    <div id="details-header">
      <div id="details-title">Select a node</div>
      <div id="details-subtitle">Click a graph node to inspect linked chunks.</div>
    </div>
    <div id="details-body"></div>
  </aside>
  <div id="graph"></div>
</div>
<script>
const nodes = {json.dumps(nodes, ensure_ascii=False)};
const edges = {json.dumps(edges, ensure_ascii=False)};
const selectedNodeId = {json.dumps(selected_node_id)};
const syncOntologySelection = {json.dumps(sync_ontology_selection)};
const openSelectedDetails = {json.dumps(open_selected_details)};
const preservedViewport = {json.dumps(viewport or {})};
const ontologyClickChannel = 'earnings_call_graph:ontologyNodeClick';
const container = document.getElementById('graph');
const network = new vis.Network(container, {{nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges)}}, {{
  layout: {json.dumps(layout_options)},
  autoResize: true,
  interaction: {{ hover: true, tooltipDelay: 80, navigationButtons: false, keyboard: false }},
  nodes: {{
    shape: 'dot',
    borderWidth: 1.5,
    shadow: {{ enabled: true, color: 'rgba(0,0,0,.42)', size: 10, x: 2, y: 3 }},
    font: {{ face: 'Inter, Arial', size: 17, color: '#FFFFFF', strokeWidth: 5, strokeColor: '#242A32' }},
    margin: 12
  }},
  edges: {{
    arrows: {{ to: {{ enabled: true, scaleFactor: .7 }} }},
    smooth: {{ type: 'dynamic', roundness: .35 }},
    font: {{ face: 'Inter, Arial', size: 12, color: '#FFFFFF', strokeWidth: 5, strokeColor: '#242A32', align: 'middle' }}
  }},
  physics: {json.dumps(physics_options)}
}});
{stabilization_script}
document.getElementById('fit').onclick = () => network.fit({{ animation: {{ duration: 450, easingFunction: 'easeInOutQuad' }} }});
let physics = false;
document.getElementById('physics').onclick = (e) => {{
  physics = !physics;
  network.setOptions({{ physics }});
  e.target.textContent = physics ? 'Freeze' : 'Physics';
}};
const details = document.getElementById('details');
const detailsTitle = document.getElementById('details-title');
const detailsSubtitle = document.getElementById('details-subtitle');
const detailsBody = document.getElementById('details-body');
let activeDetailsNode = null;
document.getElementById('hint').textContent = 'wheel=zoom | drag background=pan | drag node=move | click node=chunks';
document.getElementById('details-close').textContent = 'x';
document.getElementById('details-close').onclick = () => {{
  details.classList.remove('open');
  activeDetailsNode = null;
}};
function escHtml(value) {{
  return String(value || '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function nodeLabel(node) {{
  return node ? String(node.label || node.id || '').replace(/\\n/g, ' · ') : 'Selected node';
}}
function syncSelectedOntologyConcept(nodeId) {{
  if (!syncOntologySelection || !nodeId) return;
  const node = nodes.find(n => n.id === nodeId);
  if (!node || node.group !== 'OntologyConcept') return;
  window.parent.postMessage({{
    type: ontologyClickChannel,
    nodeId,
    scale: network.getScale(),
    position: network.getViewPosition()
  }}, '*');
  return;
  let url = null;
  try {{
    url = new URL(window.top.location.href);
  }} catch (error) {{
    try {{
      url = new URL(document.referrer || '/', window.location.href);
    }} catch (fallbackError) {{
      console.warn('Unable to build ontology concept URL', fallbackError);
      return;
    }}
  }}
  if (url.searchParams.get('ontology_concept') === nodeId) return;
  url.searchParams.set('ontology_concept', nodeId);
  const link = document.createElement('a');
  link.href = url.toString();
  link.target = '_top';
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
}}
function edgePath(edge) {{
  const from = nodes.find(n => n.id === edge.from);
  const to = nodes.find(n => n.id === edge.to);
  return `${{nodeLabel(from)}} --${{edge.label || 'RELATED_TO'}}--> ${{nodeLabel(to)}}`;
}}
function showNodeDetails(nodeId) {{
  if (details.classList.contains('open') && activeDetailsNode === nodeId) {{
    details.classList.remove('open');
    activeDetailsNode = null;
    return;
  }}
  activeDetailsNode = nodeId;
  const node = nodes.find(n => n.id === nodeId);
  const linked = edges.filter(e => e.from === nodeId || e.to === nodeId);
  detailsTitle.textContent = nodeLabel(node);
  const nodeProps = node && node.properties ? node.properties : {{}};
  const valueText = nodeProps.value ? ` · value: ${{nodeProps.value}}` : '';
  const contextText = nodeProps.context ? ` · ${{nodeProps.context}}` : '';
  detailsSubtitle.textContent = `${{node && node.group ? node.group : 'Entity'}} · ${{linked.length}} linked relation chunk(s)${{valueText}}${{contextText}}`;
  if (!linked.length) {{
    detailsBody.innerHTML = '<div class="chunk-card"><div class="chunk-evidence">No linked chunks found for this node.</div></div>';
  }} else {{
    detailsBody.innerHTML = linked.map(edge => `
      <div class="chunk-card">
        <div class="chunk-path">${{escHtml(edgePath(edge))}}</div>
        <div class="chunk-meta">
          ${{edge.company ? `<span class="pill">${{escHtml(edge.company)}}</span>` : ''}}
          ${{edge.document ? `<span class="pill">${{escHtml(edge.document)}}</span>` : ''}}
        </div>
        <div class="chunk-evidence">${{escHtml(edge.chunk_text || edge.evidence || edge.chunk_preview || 'No evidence text stored.')}}</div>
      </div>
    `).join('');
  }}
  details.classList.add('open');
}}
network.on('click', params => {{
  if (params.nodes && params.nodes.length) {{
    showNodeDetails(params.nodes[0]);
    syncSelectedOntologyConcept(params.nodes[0]);
  }}
}});
if (selectedNodeId && nodes.some(n => n.id === selectedNodeId)) {{
  network.once('afterDrawing', () => {{
    if (preservedViewport && typeof preservedViewport.scale === 'number' && preservedViewport.position) {{
      network.moveTo({{
        position: preservedViewport.position,
        scale: preservedViewport.scale,
        animation: false
      }});
    }}
    network.selectNodes([selectedNodeId]);
    if (openSelectedDetails) {{
      setTimeout(() => showNodeDetails(selectedNodeId), 120);
    }}
  }});
}}
</script></body></html>
"""


def render_interactive_graph(
    payload: dict[str, list[dict[str, Any]]],
    *,
    height: int = 620,
    max_edges: int = 120,
    hierarchical: bool = False,
    min_node_degree: int = 1,
    selected_node_id: str = "",
    sync_ontology_selection: bool = False,
    open_selected_details: bool = False,
    viewport: dict[str, Any] | None = None,
) -> str:
    st.components.v1.html(
        interactive_graph_html(
            payload,
            height=height,
            max_edges=max_edges,
            hierarchical=hierarchical,
            min_node_degree=min_node_degree,
            selected_node_id=selected_node_id,
            sync_ontology_selection=sync_ontology_selection,
            open_selected_details=open_selected_details,
            viewport=viewport,
        ),
        height=height,
    )
    return selected_node_id


def edge_table_rows(payload: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    labels = {node.get("id"): node.get("label") for node in payload.get("nodes", [])}
    nodes = {node.get("id"): node for node in payload.get("nodes", [])}
    rows = []
    for edge in payload.get("edges", []):
        row = {
            "source": labels.get(edge.get("source"), edge.get("source")),
            "edge": edge.get("label"),
            "target": labels.get(edge.get("target"), edge.get("target")),
            "company": _display_value(edge.get("company")),
            "ticker": _display_value(edge.get("ticker")),
            "confidence": edge.get("confidence"),
            "document": _display_value(edge.get("document")),
            "evidence": _display_value(edge.get("evidence")),
        }
        if edge.get("fact_count"):
            row["fact_count"] = edge.get("fact_count")
        if edge.get("evidence_count"):
            row["evidence_count"] = edge.get("evidence_count")
        if edge.get("source_url"):
            row["source_url"] = edge.get("source_url")
        source_properties = _property_summary(nodes.get(edge.get("source"), {}).get("properties"))
        target_properties = _property_summary(nodes.get(edge.get("target"), {}).get("properties"))
        if source_properties:
            row["source_properties"] = source_properties
        if target_properties:
            row["target_properties"] = target_properties
        rows.append(row)
    return rows


def _display_value(value: Any) -> Any:
    if isinstance(value, list | tuple | set):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    return value


def node_select_options(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {
        f"{row.get('name')} ({row.get('entity_type') or 'Entity'})": row["node_id"]
        for row in rows
        if row.get("node_id") and row.get("name")
    }


def query_terms(question: str) -> list[str]:
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z0-9$%+.]+|[가-힣]+", question)
        if len(word) >= 2
    ]
    terms = [word for word in words if word not in QUESTION_STOPWORDS]
    if "ai" in terms and "demand" in terms:
        terms.append("ai demand")
    if "cloud" in terms and "backlog" in terms:
        terms.append("backlog")
    return terms[:10]


def answer_question_from_relations(question: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {
            "summary": "No matching graph relations were found. Try a broader keyword such as AI, capex, Cloud, revenue, margin, backlog, or an ontology concept.",
            "bull_case": "No graph-backed upside signal found.",
            "risk_case": "No graph-backed risk signal found.",
            "property_insights": "No metric values or ontology concepts matched.",
            "basis": "0 RelationFact rows matched the question text.",
        }
    companies = _unique_display(row.get("company") for row in rows)
    ranked = sorted(rows, key=lambda row: _insight_rank(row, query_terms(question)))
    bullish = [row for row in ranked if row.get("relation") in BULLISH_RELATIONS]
    risks = [row for row in ranked if row.get("relation") in RISK_RELATIONS]
    top_paths = "; ".join(_fact_path(row, include_concepts=True) for row in ranked[:3])
    concepts = _unique_display(
        concept
        for row in ranked
        for concept in [*_as_list(row.get("source_concepts")), *_as_list(row.get("target_concepts"))]
    )[:6]
    values = _metric_value_summaries(ranked)[:8]
    company_focus = _company_breakdown(ranked)
    property_bits = []
    if concepts:
        property_bits.append(f"Concepts: {', '.join(concepts)}")
    if values:
        property_bits.append(f"Metric/property values: {', '.join(values)}")
    if company_focus:
        property_bits.append(f"Company breakdown: {company_focus}")
    return {
        "summary": f"Found {len(rows)} graph relation(s) relevant to '{question}'. Main paths: {top_paths}.",
        "bull_case": _summarize_side(bullish, "upside/support"),
        "risk_case": _summarize_side(risks, "risk/pressure"),
        "property_insights": " | ".join(property_bits) if property_bits else "No explicit metric values or ontology mappings were present in the matched rows.",
        "basis": f"Companies: {', '.join(companies) if companies else 'n/a'}. Ranking uses insight layer, matched terms, MetricValue/BusinessOutcome nodes, entity value/context properties, and ontology concept mappings.",
    }

def key_node_explanation(node: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, str]:
    name = node.get("name") or (rows[0].get("node_name") if rows else "Selected node")
    if not rows:
        return {
            "why_it_matters": f"{name} has no loaded relation context.",
            "main_connections": "No relation paths found.",
            "evidence": "No evidence snippets found.",
        }
    companies = _unique_display(row.get("company") for row in rows)
    ranked = sorted(rows, key=_insight_rank)
    paths = [_fact_path(row, include_concepts=True) for row in ranked[:5]]
    node_properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    if not node_properties:
        node_properties = next((row.get("node_properties") for row in rows if isinstance(row.get("node_properties"), dict)), {})
    concepts = _unique_display(
        [*(_as_list(node.get("concepts"))), *[concept for row in rows for concept in _as_list(row.get("node_concepts"))]]
    )
    if not concepts:
        concepts = _unique_display(
            concept
            for row in ranked
            for concept in [*_as_list(row.get("source_concepts")), *_as_list(row.get("target_concepts"))]
            if row.get("source") == name or row.get("target") == name
        )
    values = _metric_value_summaries(ranked)
    value_note = f" Key metric/property values: {', '.join(values[:8])}." if values else ""
    concept_note = f" Ontology concepts: {', '.join(concepts[:6])}." if concepts else ""
    property_note = f" Node properties: {_property_summary(node_properties)}." if _property_summary(node_properties) else ""
    evidence = next((row.get("evidence") or row.get("chunk_preview") for row in ranked if row.get("evidence") or row.get("chunk_preview")), "No evidence text stored.")
    return {
        "why_it_matters": f"{name} is connected to {len(rows)} relation fact(s) across {len(companies)} company/document context(s).{concept_note}{property_note}{value_note}",
        "main_connections": "; ".join(paths),
        "evidence": str(evidence),
    }

def _insight_rank(row: dict[str, Any], terms: list[str] | None = None) -> tuple[int, int, str]:
    haystack = " ".join(
        str(value).lower()
        for value in [
            row.get("source"),
            row.get("target"),
            row.get("relation"),
            row.get("evidence"),
            row.get("chunk_preview"),
            _property_summary(row.get("source_properties")),
            _property_summary(row.get("target_properties")),
            _display_value(row.get("source_concepts")),
            _display_value(row.get("target_concepts")),
        ]
        if value
    )
    relevance = sum(1 for term in terms or [] if term.lower() in haystack)
    type_bonus = 0
    if row.get("target_type") == "MetricValue" or row.get("source_type") == "MetricValue":
        type_bonus += 4
    if row.get("target_type") == "BusinessOutcome" or row.get("source_type") == "BusinessOutcome":
        type_bonus += 2
    if row.get("source_properties") or row.get("target_properties"):
        type_bonus += 2
    if row.get("source_concepts") or row.get("target_concepts"):
        type_bonus += 2
    relation_bonus = 2 if row.get("relation") in {"CONVERTS_TO", "PRESSURES", "REDUCES", "DRIVES", "INCREASES"} else 0
    layer_bonus = 6 if row.get("relation_layer") == "insight" else 0
    return (-(relevance * 4 + type_bonus + relation_bonus + layer_bonus), -relevance, str(row.get("source") or ""))

def _summarize_side(rows: list[dict[str, Any]], label: str) -> str:
    if not rows:
        return f"No clear {label} relation in the matched graph rows."
    return "; ".join(_fact_path(row, include_concepts=True) for row in rows[:3])


def _fact_path(row: dict[str, Any], *, include_concepts: bool = False) -> str:
    source = _entity_display(row.get("source"), row.get("source_properties"))
    target = _entity_display(row.get("target"), row.get("target_properties"))
    path = f"{source} --{row.get('relation') or ''}--> {target}".strip()
    if include_concepts:
        source_concepts = _unique_display(_as_list(row.get("source_concepts")))[:2]
        target_concepts = _unique_display(_as_list(row.get("target_concepts")))[:2]
        if source_concepts and target_concepts:
            path += f" [concepts: {', '.join(source_concepts)} -> {', '.join(target_concepts)}]"
        elif source_concepts or target_concepts:
            path += f" [concepts: {', '.join([*source_concepts, *target_concepts])}]"
    return path


def _entity_display(name: Any, properties: Any) -> str:
    props = properties if isinstance(properties, dict) else {}
    value = props.get("value")
    context = props.get("context")
    if name and value and context:
        return f"{name} ({value}) [{truncate(context, 42)}]"
    if name and value:
        return f"{name} ({value})"
    if name and context:
        return f"{name} ({truncate(context, 42)})"
    return str(name or "")


def _metric_value_summaries(rows: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for side in ("source", "target"):
            if row.get(f"{side}_type") == "MetricValue" or _has_property_value(row.get(f"{side}_properties")):
                rendered = _entity_display(row.get(side), row.get(f"{side}_properties"))
                if rendered:
                    values.append(rendered)
    return _unique_display(values)


def _company_breakdown(rows: Iterable[dict[str, Any]], limit: int = 4) -> str:
    by_company: dict[str, list[str]] = {}
    for row in rows:
        company = _display_value(row.get("company")) or "n/a"
        by_company.setdefault(str(company), [])
        if len(by_company[str(company)]) < 2:
            by_company[str(company)].append(_fact_path(row))
    return "; ".join(
        f"{company}: {', '.join(paths)}"
        for company, paths in list(by_company.items())[:limit]
        if paths
    )


def _has_property_value(properties: Any) -> bool:
    return isinstance(properties, dict) and any(properties.get(key) for key in ("value", "context"))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _unique_display(values: Iterable[Any]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, list | tuple | set):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text not in seen:
                seen.add(text)
                unique.append(text)
    return unique


def _property_summary(properties: Any) -> str:
    if not isinstance(properties, dict) or not properties:
        return ""
    parts = []
    for key, value in properties.items():
        if key in {"id", "name", "entity_type"} or not value:
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value[:6])
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return "; ".join(parts)


def _table_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "company": row.get("company"),
            "source": row.get("source"),
            "source_properties": _property_summary(row.get("source_properties")),
            "source_concepts": _display_value(row.get("source_concepts")),
            "relation": row.get("relation"),
            "target": row.get("target"),
            "target_properties": _property_summary(row.get("target_properties")),
            "target_concepts": _display_value(row.get("target_concepts")),
            "confidence": row.get("confidence"),
            "evidence": truncate(row.get("evidence") or row.get("chunk_preview"), 180),
            "chunk_preview": truncate(row.get("chunk_preview") or row.get("chunk_text"), 220),
        }
        for row in rows
    ]


def unique_chunk_rows(rows: Iterable[dict[str, Any]], limit: int = 16) -> list[dict[str, Any]]:
    """Return chunk rows de-duplicated by chunk_id, with text fallback for defensive use."""

    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        chunk_id = str(row.get("chunk_id") or "").strip()
        chunk_text = str(row.get("chunk_text") or row.get("chunk_preview") or "").strip()
        evidence = str(row.get("evidence") or "").strip()
        dedupe_key = chunk_id or chunk_text or evidence
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "company": str(row.get("company") or ""),
                "ticker": str(row.get("ticker") or ""),
                "document": str(row.get("document") or ""),
                "chunk_index": row.get("chunk_index"),
                "chunk_text": chunk_text or evidence,
                "chunk_preview": str(row.get("chunk_preview") or chunk_text or evidence),
                "matched_entities": list(row.get("matched_entities") or []),
                "relation_types": list(row.get("relation_types") or []),
                "relation_count": int(row.get("relation_count") or 0),
            }
        )
        if len(chunks) >= limit:
            break
    return chunks


def build_ontology_chunk_summary_prompt(concept: dict[str, Any], chunks: Iterable[dict[str, Any]]) -> str:
    unique_chunks = unique_chunk_rows(chunks, limit=16)
    chunk_blocks = []
    for index, chunk in enumerate(unique_chunks, start=1):
        chunk_text = truncate(chunk.get("chunk_text"), 1600)
        context = ", ".join(
            part
            for part in [
                f"company={chunk.get('company') or 'Unknown'}",
                f"document={chunk.get('document') or 'Unknown'}",
                f"chunk_id={chunk.get('chunk_id') or 'Unknown'}",
                f"relations={', '.join(chunk.get('relation_types') or []) or 'n/a'}",
                f"matched_entities={', '.join(chunk.get('matched_entities') or []) or 'n/a'}",
            ]
            if part
        )
        chunk_blocks.append(f"Chunk {index} ({context})\n{chunk_text}")
    return "\n\n".join(
        [
            "Summarize what the evidence chunks say about this ontology concept.",
            f"Concept: {concept.get('name') or 'Unknown'}",
            f"Concept type: {concept.get('concept_type') or 'Unknown'}",
            f"Description: {concept.get('description') or ''}",
            "Use only the chunks below. Each chunk_id is included at most once; do not infer from duplicate relation rows.",
            "Return compact research notes: a short summary, key points, company differences, and evidence gaps.",
            "\n\n".join(chunk_blocks) if chunk_blocks else "No chunks were available.",
        ]
    )


@st.cache_data(ttl=3600, show_spinner=False)
def summarize_ontology_chunks(concept: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = build_ontology_chunk_summary_prompt(concept, chunks)
    client = GeminiClient(timeout=90, max_retries=2, retry_delay=2.0)
    return client.generate_json(
        prompt,
        ONTOLOGY_SUMMARY_SCHEMA,
        system_instruction=ONTOLOGY_SUMMARY_SYSTEM,
        operation=f"Gemini ontology summary for {concept.get('name') or 'concept'}",
    )


def build_graph_chunk_summary_prompt(
    *,
    context_title: str,
    context_description: str,
    rows: Iterable[dict[str, Any]],
    limit: int = 8,
) -> str:
    chunks = referenced_chunk_rows(rows, limit=limit)
    chunk_blocks = []
    for index, chunk in enumerate(chunks, start=1):
        context = ", ".join(
            part
            for part in [
                f"company={chunk.get('company') or 'Unknown'}",
                f"document={chunk.get('document') or 'Unknown'}",
                f"path={truncate(chunk.get('path'), 180)}",
            ]
            if part
        )
        evidence = str(chunk.get("evidence") or "").strip()
        evidence_block = f"\nExtracted evidence: {truncate(evidence, 500)}" if evidence else ""
        chunk_blocks.append(
            f"Chunk {index} ({context}){evidence_block}\n{truncate(chunk.get('chunk_text'), 1800)}"
        )
    return "\n\n".join(
        [
            "Summarize the evidence chunks connected to this graph context.",
            f"Context: {context_title}",
            f"Task: {context_description}",
            "Use only the chunks below. Each source chunk is included at most once; do not infer from duplicate relation rows.",
            "Return compact research notes: a short summary, key points, company differences, and evidence gaps.",
            "\n\n".join(chunk_blocks) if chunk_blocks else "No chunks were available.",
        ]
    )


@st.cache_data(ttl=3600, show_spinner=False)
def summarize_graph_chunks(
    context_title: str,
    context_description: str,
    rows: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    prompt = build_graph_chunk_summary_prompt(
        context_title=context_title,
        context_description=context_description,
        rows=rows,
        limit=limit,
    )
    client = GeminiClient(timeout=90, max_retries=2, retry_delay=2.0)
    return client.generate_json(
        prompt,
        ONTOLOGY_SUMMARY_SCHEMA,
        system_instruction=GRAPH_CHUNK_SUMMARY_SYSTEM,
        operation=f"Gemini chunk summary for {context_title}",
    )


def build_connected_node_summary_prompt(
    *,
    rows: Iterable[dict[str, Any]],
    search: str = "",
    company_ticker: str = "",
    graph_view: str = "Company entities",
    limit: int = 15,
) -> str:
    row_list = list(rows)
    chunks = referenced_chunk_rows(row_list, limit=limit)
    top_nodes: list[str] = []
    seen_nodes: set[str] = set()
    for row in row_list:
        node_id = str(row.get("focus_node_id") or row.get("focus_node") or "").strip()
        node_name = str(row.get("focus_node") or "").strip()
        if not node_id or not node_name or node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        top_nodes.append(
            " - "
            + f"{row.get('focus_company') or row.get('company') or 'Unknown company'}: "
            + node_name
            + f" ({row.get('focus_node_type') or 'Entity'}; degree={int(row.get('node_degree') or 0)}; "
            + f"chunks={int(row.get('evidence_count') or 0)})"
        )
        if len(top_nodes) >= 8:
            break

    chunk_blocks = []
    for index, chunk in enumerate(chunks, start=1):
        row = next(
            (
                source_row
                for source_row in row_list
                if str(source_row.get("chunk_text") or source_row.get("chunk_preview") or source_row.get("evidence") or "").strip()
                == str(chunk.get("chunk_text") or "").strip()
            ),
            {},
        )
        context = ", ".join(
            part
            for part in [
                f"company={chunk.get('company') or 'Unknown'}",
                f"document={chunk.get('document') or 'Unknown'}",
                f"focus_node={row.get('focus_node') or 'Unknown'}",
                f"path={truncate(chunk.get('path'), 180)}",
            ]
            if part
        )
        evidence = str(chunk.get("evidence") or "").strip()
        evidence_block = f"\nExtracted evidence: {truncate(evidence, 500)}" if evidence else ""
        chunk_blocks.append(
            f"Chunk {index} ({context}){evidence_block}\n{truncate(chunk.get('chunk_text'), 1600)}"
        )

    scope = company_ticker or "all loaded companies"
    search_scope = search.strip() or "all graph rows"
    return "\n\n".join(
        [
            "Write a concise overview for the top of the Graph tab.",
            "The evidence chunks were selected from each company's two highest-degree entity nodes in the current graph scope.",
            f"Graph view: {graph_view}",
            f"Company scope: {scope}",
            f"Graph search: {search_scope}",
            "Top connected nodes used by company:",
            "\n".join(top_nodes) if top_nodes else " - No connected nodes were available.",
            "Use only the chunks below. Each source chunk is included at most once.",
            "Focus the visible answer on key points and company differences. "
            "If the JSON schema requires other fields, keep them brief.",
            "\n\n".join(chunk_blocks) if chunk_blocks else "No chunks were available.",
        ]
    )


@st.cache_data(ttl=3600, show_spinner=False)
def summarize_connected_node_chunks(
    search: str,
    company_ticker: str,
    graph_view: str,
    rows: list[dict[str, Any]],
    *,
    limit: int = 15,
) -> dict[str, Any]:
    prompt = build_connected_node_summary_prompt(
        rows=rows,
        search=search,
        company_ticker=company_ticker,
        graph_view=graph_view,
        limit=limit,
    )
    client = GeminiClient(timeout=90, max_retries=2, retry_delay=2.0)
    return client.generate_json(
        prompt,
        ONTOLOGY_SUMMARY_SCHEMA,
        system_instruction=CONNECTED_NODE_SUMMARY_SYSTEM,
        operation="Gemini connected-node graph overview",
    )


def referenced_chunk_rows(rows: Iterable[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    """Return de-duplicated full chunk contexts for Ask/Key Nodes evidence panels."""

    source_rows = list(rows)
    chunk_rows: list[dict[str, str]] = []
    for chunk in unique_chunk_rows(source_rows, limit=limit):
        row = next(
            (
                source_row
                for source_row in source_rows
                if str(source_row.get("chunk_id") or "").strip() == chunk["chunk_id"]
                or str(source_row.get("chunk_text") or source_row.get("chunk_preview") or "").strip() == chunk["chunk_text"]
            ),
            {},
        )
        chunk_rows.append(
            {
                "company": chunk["company"],
                "document": chunk["document"],
                "path": _fact_path(row, include_concepts=True),
                "evidence": str(row.get("evidence") or "").strip(),
                "chunk_text": chunk["chunk_text"],
            }
        )
    return chunk_rows


def render_summary_result(summary: dict[str, Any]) -> None:
    st.markdown("##### LLM chunk summary")
    st.write(summary.get("summary", ""))
    summary_cols = st.columns(3)
    summary_sections = [
        ("Key points", summary.get("key_points", [])),
        ("Company differences", summary.get("company_differences", [])),
        ("Evidence gaps", summary.get("evidence_gaps", [])),
    ]
    for col, (title, items) in zip(summary_cols, summary_sections):
        with col:
            st.markdown(f"**{title}**")
            if items:
                for item in items:
                    st.markdown(f"- {item}")
            else:
                st.caption("None noted.")


def render_connected_node_summary_result(summary: dict[str, Any]) -> None:
    """Render only the two overview sections that matter above the graph."""

    st.markdown("##### LLM graph overview")
    summary_cols = st.columns(2)
    summary_sections = [
        ("Key points", summary.get("key_points", [])),
        ("Company differences", summary.get("company_differences", [])),
    ]
    for col, (title, items) in zip(summary_cols, summary_sections):
        with col:
            st.markdown(f"**{title}**")
            if items:
                for item in items:
                    st.markdown(f"- {item}")
            else:
                st.caption("None noted.")


def render_chunk_summary_action(
    *,
    context_title: str,
    context_description: str,
    rows: Iterable[dict[str, Any]],
    button_key: str,
    limit: int = 8,
) -> None:
    row_list = list(rows)
    chunks = referenced_chunk_rows(row_list, limit=limit)
    st.caption(f"LLM input uses {len(chunks)} de-duplicated referenced chunk(s).")
    if not chunks:
        st.info("No referenced chunk text is available to summarize.")
        return
    if st.button("Summarize referenced chunks with LLM", type="primary", key=button_key):
        try:
            with st.spinner("Summarizing referenced chunks..."):
                summary = summarize_graph_chunks(
                    context_title,
                    context_description,
                    row_list,
                    limit=limit,
                )
            render_summary_result(summary)
        except GeminiApiError as exc:
            st.warning(f"Gemini summary failed: {exc}")


def render_connected_node_summary_action(
    *,
    search: str,
    company_ticker: str,
    graph_view: str,
    rows: Iterable[dict[str, Any]],
    limit: int = 15,
) -> None:
    row_list = list(rows)
    chunks = referenced_chunk_rows(row_list, limit=limit)
    if not row_list or not chunks:
        st.info("No connected-node source chunks are available for a graph overview.")
        return
    top_nodes = []
    seen: set[str] = set()
    for row in row_list:
        node_id = str(row.get("focus_node_id") or row.get("focus_node") or "").strip()
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        top_nodes.append(
            {
                "company": row.get("focus_company") or row.get("company"),
                "ticker": row.get("focus_ticker") or row.get("ticker"),
                "node": row.get("focus_node"),
                "type": row.get("focus_node_type"),
                "degree": row.get("node_degree"),
                "chunks": row.get("evidence_count"),
            }
        )

    st.caption(
        f"LLM input uses {len(chunks)} de-duplicated chunk(s) selected from each company's "
        "two most connected entity nodes in the current graph scope."
    )
    with st.expander("Top connected nodes by company used for summary", expanded=False):
        st.dataframe(top_nodes[:8], width="stretch", hide_index=True)
    try:
        with st.spinner("Summarizing top connected-node evidence chunks..."):
            summary = summarize_connected_node_chunks(
                search,
                company_ticker,
                graph_view,
                row_list,
                limit=limit,
            )
        render_connected_node_summary_result(summary)
    except GeminiApiError as exc:
        st.warning(f"Gemini overview failed: {exc}")


def render_referenced_chunks(rows: Iterable[dict[str, Any]], *, limit: int = 8) -> None:
    chunks = referenced_chunk_rows(rows, limit=limit)
    if not chunks:
        st.info("No referenced chunk text is stored for these rows.")
        return
    for index, chunk in enumerate(chunks, start=1):
        label_parts = [
            f"{index}.",
            chunk["company"] or "Unknown company",
            truncate(chunk["path"], 90),
        ]
        with st.expander(" | ".join(label_parts), expanded=index == 1):
            if chunk["document"]:
                st.caption(f"Document: {chunk['document']}")
            st.markdown("**Referenced chunk**")
            st.markdown(
                f'<div class="cf-chunk-text">{escape(chunk["chunk_text"])}</div>',
                unsafe_allow_html=True,
            )


def show_error_if_any(error: str | None) -> bool:
    if error:
        st.warning(f"Neo4j is not available: {error}")
        return True
    return False


def render_counts(rows: list[dict[str, Any]]) -> None:
    cols = st.columns(min(4, max(1, len(rows))))
    for index, row in enumerate(rows):
        cols[index % len(cols)].metric(row["label"], row["count"])


def _header_stat(count_map: dict[str, Any], label: str, caption: str) -> str:
    return f'<div class="cf-stat"><span class="cf-stat-v">{count_map.get(label, 0)}</span><span class="cf-stat-k">{caption}</span></div>'


def _context_pill(count_map: dict[str, Any], label: str, caption: str) -> str:
    return f'<span class="cf-context-pill"><strong>{count_map.get(label, 0)}</strong>{caption}</span>'


def run_app() -> None:
    st.set_page_config(page_title="Earnings Call Graph Thesis Agent", page_icon="G", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    counts, count_error = graph_counts()
    count_map = {row.get("label"): row.get("count") for row in counts} if not count_error else {}
    st.markdown(
        f"""
        <div class="cf-header">
          <div class="cf-brand">
            <span class="cf-glyph">G</span>
            <span class="cf-title">Earnings Call Graph Thesis Agent</span>
            <span class="cf-subtitle">conference-call ontology | Neo4j evidence-backed analyst agent</span>
          </div>
          <div class="cf-header-stats">
            {_header_stat(count_map, "Company", "companies")}
            {_header_stat(count_map, "EarningsCall", "calls")}
            {_header_stat(count_map, "RelationFact", "relations")}
            {_header_stat(count_map, "MarkdownChunk", "chunks")}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not count_error:
        st.markdown(
            f"""
            <div class="cf-context-bar">
              {_context_pill(count_map, "SourceDocument", "sources")}
              {_context_pill(count_map, "Entity", "entities")}
              {_context_pill(count_map, "OntologyConcept", "ontology concepts")}
              {_context_pill(count_map, "FiscalPeriod", "fiscal periods")}
              {_context_pill(count_map, "Quarter", "quarters")}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.sidebar:
        st.markdown('<div class="cf-side-title">Controls</div>', unsafe_allow_html=True)
        st.markdown('<div class="cf-side-help">Graph-specific filters. Shared graph totals are shown above.</div>', unsafe_allow_html=True)
        search = st.text_input(
            "Graph search only",
            value="AI",
            help="Applies only to the Graph tab. Ask uses its own Question input; Key Nodes are ranked independently.",
        )
        graph_view = st.radio("Graph view", ["Company entities", "Ontology concepts"], horizontal=False)
        graph_scope = st.radio("Graph scope", ["All nodes", "By company"], horizontal=False)
        min_node_degree = st.number_input(
            "Minimum node connections",
            min_value=1,
            max_value=20,
            value=1,
            step=1,
            help="Filters the Graph tab to nodes with at least this many relation/schema connections in the current result set. Set 1 to show all connected nodes. Company context hub edges do not count toward this threshold.",
        )
        min_node_degree = int(min_node_degree)
        selected_company_ticker = ""
        selected_company_label = ""
        if graph_scope == "By company":
            company_rows, company_error = company_options()
            if company_error:
                st.warning(f"Company list is not available: {company_error}")
            elif company_rows:
                company_labels = [
                    f"{row.get('company') or row.get('ticker')} ({row.get('ticker')})"
                    for row in company_rows
                    if row.get("ticker")
                ]
                label_to_ticker = {
                    f"{row.get('company') or row.get('ticker')} ({row.get('ticker')})": row.get("ticker")
                    for row in company_rows
                    if row.get("ticker")
                }
                selected_company_label = st.selectbox("Company", company_labels)
                selected_company_ticker = str(label_to_ticker.get(selected_company_label) or "")
            else:
                st.info("No company nodes are loaded.")
        available_results, available_error = graph_result_count(graph_view, search, selected_company_ticker)
        slider_min, slider_max, slider_default, slider_step = result_limit_slider_config(available_results)
        if result_limit_slider_enabled(available_results):
            limit = st.slider(
                "Result limit",
                min_value=slider_min,
                max_value=slider_max,
                value=slider_default,
                step=slider_step,
                key=f"result_limit:{graph_view}:{selected_company_ticker}:{search.strip().lower()}",
                help="Limits Graph edges/rows and the evidence/context rows shown in Ask and Key Nodes. The maximum is the number of matching relation rows for this graph search/scope, not a fixed 200 cap.",
            )
        else:
            limit = slider_default
            if int(available_results or 0) <= 0:
                st.info("No matching graph rows for this search/scope. Result limit control is hidden.")
            else:
                st.caption("Only one matching graph row. Result limit is fixed at 1.")
        if available_error:
            st.warning(f"Result limit maximum is not available: {available_error}")
        else:
            st.caption(f"Max for this graph search/scope: {available_results} relation row(s).")
        if count_error:
            st.warning("Neo4j is not connected.")

    tabs = st.tabs(["Graph", "Ask", "Key Nodes"])

    with tabs[0]:
        st.markdown('<div class="cf-section-title">Conference-call relation graph</div>', unsafe_allow_html=True)
        st.markdown('<div class="cf-section-sub">Explore source-backed entity relations or the ontology hierarchy projected from Neo4j.</div>', unsafe_allow_html=True)
        st.markdown("#### Graph overview")
        overview_rows, overview_error = connected_node_summary_rows(
            search,
            limit=15,
            company_ticker=selected_company_ticker,
        )
        if not show_error_if_any(overview_error):
            render_connected_node_summary_action(
                search=search,
                company_ticker=selected_company_ticker,
                graph_view=graph_view,
                rows=overview_rows,
                limit=15,
            )
        source_rows, source_error = source_document_rows()
        if not show_error_if_any(source_error) and source_rows:
            with st.expander("Source documents", expanded=False):
                st.dataframe(source_rows, width="stretch", hide_index=True)
        if graph_view == "Ontology concepts":
            st.caption("Ontology concept view renders ontology schema edges as a hierarchy; aggregate fact relations remain available in Relation rows.")
            payload, error = ontology_graph_payload(search, limit, selected_company_ticker)
            concept_options_rows, concept_options_error = ontology_concept_options()
            concept_options = {} if concept_options_error else ontology_concept_select_options(concept_options_rows)
            clicked_ontology_selection = ontology_click_bridge_value()
            clicked_ontology_concept_id = str(clicked_ontology_selection.get("node_id") or "")
            if clicked_ontology_concept_id in set(concept_options.values()):
                st.query_params["ontology_concept"] = clicked_ontology_concept_id
                st.session_state["_ontology_concept_query"] = ""
                st.session_state["_ontology_graph_open_details"] = clicked_ontology_concept_id
                st.session_state["_ontology_graph_viewport"] = {
                    "scale": clicked_ontology_selection.get("scale"),
                    "position": clicked_ontology_selection.get("position"),
                }
            selected_ontology_concept_id, selected_ontology_concept_label, selected_ontology_concept_index = synced_ontology_concept_selection(concept_options)
        else:
            payload, error = graph_payload(search, limit, selected_company_ticker)
            concept_options_error = None
            concept_options = {}
            selected_ontology_concept_id = ""
            selected_ontology_concept_label = ""
            selected_ontology_concept_index = 0
        if not show_error_if_any(error):
            if min_node_degree > 1:
                payload = filter_payload_by_min_node_degree(payload, min_node_degree)
                st.caption(
                    f"Showing only graph nodes with at least {min_node_degree} relation/schema "
                    "connections in the current result set."
                )
            if selected_company_ticker:
                st.caption(f"Company graph: {selected_company_label}. The company node is rendered as a green context hub.")
            cols = st.columns(2)
            cols[0].metric("Nodes", len(payload["nodes"]))
            cols[1].metric("Relations", len(payload["edges"]))
            if payload["nodes"]:
                open_selected_details = (
                    graph_view == "Ontology concepts"
                    and st.session_state.get("_ontology_graph_open_details") == selected_ontology_concept_id
                )
                render_interactive_graph(
                    payload,
                    height=620,
                    max_edges=limit,
                    hierarchical=graph_view == "Ontology concepts",
                    selected_node_id=selected_ontology_concept_id,
                    sync_ontology_selection=graph_view == "Ontology concepts",
                    open_selected_details=open_selected_details,
                    viewport=st.session_state.get("_ontology_graph_viewport") if open_selected_details else None,
                )
                if graph_view == "Ontology concepts":
                    st.markdown("#### Ontology evidence summary")
                    if show_error_if_any(concept_options_error):
                        pass
                    else:
                        if concept_options:
                            concept_labels = list(concept_options)
                            selected_concept_label = st.selectbox(
                                "Concept",
                                concept_labels,
                                index=selected_ontology_concept_index,
                                key="ontology_concept_inspector",
                            )
                            selected_concept_id = concept_options[selected_concept_label]
                            if selected_query_param("ontology_concept") != selected_concept_id:
                                st.query_params["ontology_concept"] = selected_concept_id
                                st.session_state["_ontology_concept_query"] = selected_concept_id
                                if st.session_state.get("_ontology_graph_open_details") != selected_concept_id:
                                    st.session_state["_ontology_graph_open_details"] = ""
                            summary_limit = min(max(limit, 1), 16)
                            concept_context, concept_error = ontology_concept_chunks(selected_concept_id, limit=summary_limit, company_ticker=selected_company_ticker)
                            if not show_error_if_any(concept_error):
                                concept = concept_context["concept"]
                                chunks = concept_context["chunks"]
                                st.caption(f"{concept.get('name', '')} ({concept.get('concept_type', '')}) - {concept.get('description', '')}")
                                st.caption(f"LLM input uses {len(chunks)} de-duplicated chunk(s). Duplicate chunk_ids are used once.")
                                if chunks:
                                    if st.button("Summarize selected concept", type="primary", key=f"ontology_summary_{concept.get('concept_id')}"):
                                        try:
                                            with st.spinner("Summarizing de-duplicated evidence chunks..."):
                                                summary = summarize_ontology_chunks(concept, chunks)
                                            st.markdown("##### Summary")
                                            st.write(summary.get("summary", ""))
                                            summary_cols = st.columns(3)
                                            summary_sections = [
                                                ("Key points", summary.get("key_points", [])),
                                                ("Company differences", summary.get("company_differences", [])),
                                                ("Evidence gaps", summary.get("evidence_gaps", [])),
                                            ]
                                            for col, (title, items) in zip(summary_cols, summary_sections):
                                                with col:
                                                    st.markdown(f"**{title}**")
                                                    if items:
                                                        for item in items:
                                                            st.markdown(f"- {item}")
                                                    else:
                                                        st.caption("None noted.")
                                        except GeminiApiError as exc:
                                            st.warning(f"Gemini summary failed: {exc}")
                                    with st.expander("Deduplicated chunks used for summary", expanded=False):
                                        st.dataframe(
                                            [
                                                {
                                                    "company": chunk["company"],
                                                    "document": chunk["document"],
                                                    "chunk_id": chunk["chunk_id"],
                                                    "relations": ", ".join(chunk["relation_types"]),
                                                    "matched_entities": ", ".join(chunk["matched_entities"]),
                                                    "chunk_preview": truncate(chunk["chunk_text"], 260),
                                                }
                                                for chunk in chunks
                                            ],
                                            width="stretch",
                                            hide_index=True,
                                        )
                                else:
                                    st.info("No source chunks are connected to this ontology concept yet.")
                        else:
                            st.info("No ontology concepts are loaded.")
                with st.expander("Relation rows"):
                    st.dataframe(edge_table_rows(payload), width="stretch", hide_index=True)
            else:
                st.info("No graph nodes matched this search/filter.")

    with tabs[1]:
        st.markdown('<div class="cf-section-title">Ask the graph</div>', unsafe_allow_html=True)
        st.markdown('<div class="cf-section-sub">Ask ignores Graph search. The default answer uses deterministic graph matching against entities, relations, evidence snippets, properties, and ontology concepts. Experimental Text2Cypher can generate a read-only ad-hoc query when the template-like matcher is too narrow.</div>', unsafe_allow_html=True)
        question_choice = st.selectbox(
            "Suggested questions",
            [CUSTOM_QUESTION_LABEL, *ASK_QUESTION_PRESETS],
            index=1,
        )
        question_default = ASK_QUESTION_PRESETS[0] if question_choice == CUSTOM_QUESTION_LABEL else question_choice
        question = st.text_input("Question", value=question_default)
        rows, error = relation_fact_rows(question, limit)
        if not show_error_if_any(error):
            rows = sorted(rows, key=lambda row: _insight_rank(row, query_terms(question)))
            answer = answer_question_from_relations(question, rows)
            st.markdown(
                f"""
                <div class="cf-panel">
                  <div class="cf-answer-label">Answer</div>
                  <div class="cf-answer-text">{escape(answer["summary"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div class="cf-answer-grid">
                  <div class="cf-answer-card">
                    <div class="cf-answer-label">Upside / support</div>
                    <div class="cf-answer-text">{escape(answer["bull_case"])}</div>
                  </div>
                  <div class="cf-answer-card risk">
                    <div class="cf-answer-label">Risk / pressure</div>
                    <div class="cf-answer-text">{escape(answer["risk_case"])}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if answer.get("property_insights"):
                st.info(answer["property_insights"])
            st.caption(answer["basis"])
            with st.expander("Matched evidence"):
                st.dataframe(_table_rows(rows), width="stretch", hide_index=True)
            st.markdown("#### LLM summary from referenced chunks")
            render_chunk_summary_action(
                context_title=f"Ask: {question}",
                context_description="Answer the user's graph question from the matched evidence chunks.",
                rows=rows,
                button_key=f"ask_chunk_summary_{abs(hash(question))}",
                limit=8,
            )
            st.markdown("#### Referenced chunks")
            render_referenced_chunks(rows, limit=8)
            with st.expander("Experimental Text2Cypher", expanded=False):
                st.caption(
                    "Optional ad-hoc path for Aura Agent exploration. The generated query is validated as read-only, "
                    "must include RETURN and LIMIT, and is displayed before/with its result. The deterministic answer above remains the default."
                )
                if st.button("Generate and run Text2Cypher", key=f"text2cypher_{abs(hash(question))}"):
                    result, text2cypher_error = run_text2cypher_question(question)
                    if result:
                        if result.get("rationale"):
                            st.markdown(f"**Rationale:** {escape(str(result['rationale']))}")
                        for warning in result.get("warnings") or []:
                            st.warning(warning)
                        st.code(result.get("cypher") or "", language="cypher")
                        if result.get("rows"):
                            st.dataframe(result["rows"], width="stretch", hide_index=True)
                        else:
                            st.info("Text2Cypher returned no rows.")
                    if text2cypher_error:
                        st.warning(f"Text2Cypher path failed: {text2cypher_error}")

    with tabs[2]:
        st.markdown('<div class="cf-section-title">Key node explanations</div>', unsafe_allow_html=True)
        st.markdown('<div class="cf-section-sub">Key Nodes ignore Graph search. Nodes are ranked from the full loaded graph, with graph paths and referenced source chunks.</div>', unsafe_allow_html=True)
        nodes, error = key_node_rows(limit=30)
        if not show_error_if_any(error):
            if not nodes:
                st.info("No key nodes found. Load an extracted conference-call graph first.")
                return
            options = node_select_options(nodes)
            selected_label = st.selectbox("Key node", list(options))
            selected_id = options[selected_label]
            selected_node = next((row for row in nodes if row.get("node_id") == selected_id), {})
            context, context_error = node_context_rows(selected_id, limit=limit)
            if not show_error_if_any(context_error):
                st.dataframe(_table_rows(context), width="stretch", hide_index=True)
                st.markdown("#### LLM summary from referenced chunks")
                render_chunk_summary_action(
                    context_title=f"Key node: {selected_node.get('name') or selected_label}",
                    context_description="Explain what the connected evidence chunks say about this key node and its main graph paths.",
                    rows=context,
                    button_key=f"key_node_chunk_summary_{selected_id}",
                    limit=8,
                )
                st.markdown("#### Referenced chunks")
                render_referenced_chunks(context, limit=8)


if __name__ == "__main__":  # pragma: no cover
    run_app()
