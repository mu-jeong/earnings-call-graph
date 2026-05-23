from __future__ import annotations

import os
import re
import hashlib
from typing import Any, Iterable

from .config import load_dotenv
from .markdown_ingest import ExtractedDocument
from .ontology import (
    OntologyConcept,
    OntologyMatch,
    OntologyRelation,
    load_ontology,
    load_ontology_relations,
    map_entity_to_concepts,
)


CONSTRAINTS = [
    "CREATE CONSTRAINT company_id IF NOT EXISTS FOR (n:Company) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT sector_name IF NOT EXISTS FOR (n:Sector) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT segment_name IF NOT EXISTS FOR (n:BusinessSegment) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT call_id IF NOT EXISTS FOR (n:EarningsCall) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT quarter_name IF NOT EXISTS FOR (n:Quarter) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT fiscal_period_id IF NOT EXISTS FOR (n:FiscalPeriod) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT source_document_id IF NOT EXISTS FOR (n:SourceDocument) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT markdown_chunk_id IF NOT EXISTS FOR (n:MarkdownChunk) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT relation_fact_id IF NOT EXISTS FOR (n:RelationFact) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT extraction_run_id IF NOT EXISTS FOR (n:ExtractionRun) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ontology_concept_id IF NOT EXISTS FOR (n:OntologyConcept) REQUIRE n.id IS UNIQUE",
]



READ_GRAPH_RELATIONS_CYPHER = """
MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
      (fact)-[:TO_ENTITY]->(dst:Entity)
WHERE $theme = ''
   OR toLower(src.name) CONTAINS toLower($theme)
   OR toLower(src.canonical_name) CONTAINS toLower($theme)
   OR toLower(dst.name) CONTAINS toLower($theme)
   OR toLower(dst.canonical_name) CONTAINS toLower($theme)
   OR toLower(fact.evidence_text) CONTAINS toLower($theme)
OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)
OPTIONAL MATCH (source_doc:SourceDocument)-[:HAS_CHUNK]->(chunk)
OPTIONAL MATCH (source_doc)-[:ABOUT_COMPANY]->(company:Company)
RETURN
  fact.id AS fact_id,
  source_doc.id AS document,
  company.name AS company,
  company.ticker AS ticker,
  src.id AS source_id,
  src.name AS source,
  src.entity_type AS source_type,
  CASE WHEN src.value IS NULL AND src.context IS NULL THEN {} ELSE src { .value, .context } END AS source_properties,
  fact.relation_type AS relation,
  coalesce(fact.layer, 'coverage') AS relation_layer,
  dst.id AS target_id,
  dst.name AS target,
  dst.entity_type AS target_type,
  CASE WHEN dst.value IS NULL AND dst.context IS NULL THEN {} ELSE dst { .value, .context } END AS target_properties,
  fact.evidence_text AS evidence,
  fact.confidence AS confidence,
  chunk.id AS chunk_id,
  chunk.text_preview AS chunk_preview
ORDER BY document, company, source, relation, target
LIMIT $limit
""".strip()


KEY_NODE_CYPHER = """
MATCH (entity:Entity)
WHERE coalesce(entity.entity_type, '') <> 'Company'
OPTIONAL MATCH (entity)<-[:FROM_ENTITY|TO_ENTITY]-(fact:RelationFact)
OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
WITH entity,
     count(DISTINCT fact) AS relation_count,
     count(DISTINCT CASE WHEN fact.layer = 'insight' THEN fact END) AS insight_count,
     count(DISTINCT company) AS company_count,
     count(DISTINCT chunk) AS evidence_count,
     avg(coalesce(fact.confidence, 0.0)) AS avg_confidence
WHERE relation_count > 0
WITH entity, relation_count, insight_count, company_count, evidence_count, coalesce(avg_confidence, 0.0) AS avg_confidence,
     CASE entity.entity_type
       WHEN 'Theme' THEN 8
       WHEN 'MetricValue' THEN 8
       WHEN 'Metric' THEN 7
       WHEN 'BusinessOutcome' THEN 7
       WHEN 'Risk' THEN 7
       WHEN 'Product' THEN 6
       WHEN 'BusinessSegment' THEN 5
       ELSE 1
     END AS type_weight
RETURN entity.id AS node_id,
       entity.name AS name,
       entity.entity_type AS entity_type,
       CASE WHEN entity.value IS NULL AND entity.context IS NULL THEN {} ELSE entity { .value, .context } END AS properties,
       relation_count,
       insight_count,
       company_count,
       evidence_count,
       avg_confidence,
       ((insight_count * 6) + relation_count + (company_count * 3) + evidence_count + type_weight + avg_confidence) AS score
ORDER BY score DESC, insight_count DESC, company_count DESC, relation_count DESC, name ASC
LIMIT $limit
""".strip()


QUESTION_CONTEXT_CYPHER = """
MATCH (entity:Entity {id: $node_id})
MATCH (fact:RelationFact)-[:FROM_ENTITY|TO_ENTITY]->(entity)
MATCH (fact)-[:FROM_ENTITY]->(src:Entity)
MATCH (fact)-[:TO_ENTITY]->(dst:Entity)
OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
RETURN entity.id AS node_id,
       entity.name AS node_name,
       src.name AS source,
       src.entity_type AS source_type,
       CASE WHEN src.value IS NULL AND src.context IS NULL THEN {} ELSE src { .value, .context } END AS source_properties,
       fact.relation_type AS relation,
       coalesce(fact.layer, 'coverage') AS relation_layer,
       dst.name AS target,
       dst.entity_type AS target_type,
       CASE WHEN dst.value IS NULL AND dst.context IS NULL THEN {} ELSE dst { .value, .context } END AS target_properties,
       fact.evidence_text AS evidence,
       fact.confidence AS confidence,
       chunk.id AS chunk_id,
       chunk.text_preview AS chunk_preview,
       company.name AS company,
       company.ticker AS ticker,
       source_doc.id AS document,
       source_doc.title AS source_title,
       source_doc.source_url AS source_url
ORDER BY CASE coalesce(fact.layer, 'coverage') WHEN 'insight' THEN 1 ELSE 0 END DESC,
         confidence DESC, company, source, relation, target
LIMIT $limit
""".strip()



class Neo4jGraph:
    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - only without optional dependency
            raise RuntimeError("Install dependencies first: pip install -e .") from exc

        load_dotenv()
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")
        uri = uri or os.getenv("NEO4J_URI")
        username = username or os.getenv("NEO4J_USERNAME", "neo4j")
        password = password or os.getenv("NEO4J_PASSWORD")
        if not uri or not password:
            raise RuntimeError("NEO4J_URI and NEO4J_PASSWORD are required. Create .env or set shell environment variables.")
        connection_timeout = float(os.getenv("NEO4J_CONNECTION_TIMEOUT_SECONDS", "10"))
        self.driver = GraphDatabase.driver(uri, auth=(username, password), connection_timeout=connection_timeout)

    def close(self) -> None:
        self.driver.close()

    def verify_connectivity(self) -> None:
        self.driver.verify_connectivity()

    def install_constraints(self) -> None:
        with self.driver.session(database=self.database) as session:
            for statement in CONSTRAINTS:
                session.run(statement).consume()

    def reset(self) -> None:
        with self.driver.session(database=self.database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

    def load_extracted_document(self, extracted: ExtractedDocument, reset: bool = False) -> None:
        self.install_constraints()
        if reset:
            self.reset()
            self.install_constraints()
        with self.driver.session(database=self.database) as session:
            session.execute_write(_load_extracted_document, extracted)

    def read_graph_relations(self, theme: str = "", limit: int = 80) -> dict[str, list[dict[str, Any]]]:
        """Return relation facts as a graph-shaped payload for UI/API callers."""
        with self.driver.session(database=self.database) as session:
            rows = session.run(READ_GRAPH_RELATIONS_CYPHER, {"theme": theme, "limit": limit}).data()
        return relation_rows_to_graph(rows)

    def rank_key_nodes(self, limit: int = 25) -> list[dict[str, Any]]:
        """Rank important entity nodes using relation, company, evidence, and type signals."""
        with self.driver.session(database=self.database) as session:
            return session.run(KEY_NODE_CYPHER, {"limit": limit}).data()

    def question_context(self, node_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """Fetch compact graph/evidence context for one key node."""
        with self.driver.session(database=self.database) as session:
            return session.run(QUESTION_CONTEXT_CYPHER, {"node_id": node_id, "limit": limit}).data()

    def refresh_ontology_mappings(self) -> int:
        """Rebuild Entity -> OntologyConcept mappings for already-loaded entities."""

        self.install_constraints()
        with self.driver.session(database=self.database) as session:
            return session.execute_write(_refresh_ontology_mappings)


def relation_rows_to_graph(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Convert relation query rows into stable node/edge arrays for graph rendering."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = row.get("source_id") or _stable_id("entity", row.get("source_type"), row.get("source"))
        target_id = row.get("target_id") or _stable_id("entity", row.get("target_type"), row.get("target"))
        if row.get("source"):
            nodes[source_id] = {
                "id": source_id,
                "label": row.get("source"),
                "type": row.get("source_type") or "Entity",
                "properties": row.get("source_properties") or {},
            }
        if row.get("target"):
            nodes[target_id] = {
                "id": target_id,
                "label": row.get("target"),
                "type": row.get("target_type") or "Entity",
                "properties": row.get("target_properties") or {},
            }
        edge_id = row.get("fact_id") or _stable_id("edge", source_id, row.get("relation"), target_id, row.get("evidence"))
        if row.get("source") and row.get("target"):
            edges[edge_id] = {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "label": row.get("relation") or "RELATED_TO",
                "layer": row.get("relation_layer") or "coverage",
                "confidence": row.get("confidence"),
                "evidence": row.get("evidence") or "",
                "company": row.get("company") or "",
                "ticker": row.get("ticker") or "",
                "document": row.get("document") or "",
                "source_url": row.get("source_url") or "",
                "chunk_id": row.get("chunk_id") or "",
                "chunk_preview": row.get("chunk_preview") or "",
                "chunk_text": row.get("chunk_text") or "",
                "fact_count": row.get("fact_count"),
                "evidence_count": row.get("evidence_count"),
            }
    return {
        "nodes": sorted(nodes.values(), key=lambda item: (item["type"], item["label"] or "", item["id"])),
        "edges": sorted(edges.values(), key=lambda item: (item["source"], item["label"], item["target"], item["id"])),
    }


def _load_extracted_document(tx, extracted: ExtractedDocument) -> None:
    doc = extracted.document
    _merge_ontology_schema(tx)
    tx.run(
        """
        MERGE (c:Company {id: $company_id})
        SET c.name = $company_name,
            c.ticker = $ticker
        MERGE (s:Sector {name: $sector})
        MERGE (c)-[:BELONGS_TO]->(s)
        MERGE (ec:EarningsCall {id: $call_id})
        SET ec.fiscal_quarter = $fiscal_quarter,
            ec.call_date = $call_date,
            ec.source_url = $source_url,
            ec.source_kind = $source_kind
        MERGE (c)-[:HELD_CALL]->(ec)
        MERGE (q:Quarter {name: $quarter})
        SET q.number = $quarter_number
        MERGE (ec)-[:IN_QUARTER]->(q)
        MERGE (fp:FiscalPeriod {id: $period_id})
        SET fp.label = $fiscal_quarter,
            fp.fiscal_year = $fiscal_year,
            fp.quarter = $quarter
        MERGE (ec)-[:IN_PERIOD]->(fp)
        MERGE (sd:SourceDocument {id: $document_id})
        SET sd.title = $title,
            sd.source_url = $source_url,
            sd.source_kind = $source_kind,
            sd.markdown_path = $markdown_path
        MERGE (sd)-[:SOURCE_FOR]->(ec)
        MERGE (sd)-[:ABOUT_COMPANY]->(c)
        MERGE (run:ExtractionRun {id: $run_id})
        SET run.document_id = $document_id,
            run.extractor = $extractor,
            run.entity_count = $entity_count,
            run.relation_count = $relation_count,
            run.chunk_count = $chunk_count
        MERGE (run)-[:PRODUCED]->(sd)
        """,
        company_id=doc["company_id"],
        company_name=doc["company_name"],
        ticker=doc.get("ticker", ""),
        sector=doc.get("sector", "Unknown"),
        call_id=doc["call_id"],
        fiscal_quarter=doc["fiscal_quarter"],
        call_date=doc.get("call_date", ""),
        source_url=doc["source_url"],
        source_kind=doc.get("source_kind", "official_ir_transcript_markdown"),
        fiscal_year=_fiscal_year(doc["fiscal_quarter"]),
        quarter=_quarter(doc["fiscal_quarter"]),
        quarter_number=_quarter_number(doc["fiscal_quarter"]),
        period_id=_period_id(doc),
        document_id=doc["id"],
        title=doc.get("title", doc["id"]),
        markdown_path=doc.get("markdown_path", ""),
        run_id=f"{doc['id']}-extraction-run",
        extractor=doc.get("source_kind", "earnings-call-graph"),
        entity_count=len(extracted.entities),
        relation_count=len(extracted.relations),
        chunk_count=len(extracted.chunks),
    )

    for entity in extracted.entities:
        aliases = list(getattr(entity, "aliases", ()))
        properties = dict(getattr(entity, "properties", {}) or {})
        tx.run(
            """
            MERGE (e:Entity {id: $id})
            SET e.name = $name,
                e.entity_type = $entity_type,
                e.source = $source,
                e.canonical_name = $canonical_name,
                e.aliases = $aliases
            SET e += $properties
            """,
            id=entity.id,
            name=entity.name,
            entity_type=entity.entity_type,
            source=entity.source,
            canonical_name=getattr(entity, "canonical_name", entity.name),
            aliases=aliases,
            properties=properties,
        )
        for match in map_entity_to_concepts(
            entity.name,
            entity.entity_type,
            aliases=aliases,
            properties=properties,
        ):
            _merge_ontology_mapping(tx, entity.id, match)

    for chunk in extracted.chunks:
        tx.run(
            """
            MATCH (sd:SourceDocument {id: $document_id})
            MATCH (ec:EarningsCall {id: $call_id})
            MERGE (ch:MarkdownChunk {id: $id})
            SET ch.index = $index,
                ch.chunk_type = $chunk_type,
                ch.heading = $heading,
                ch.heading_path = $heading_path,
                ch.text = $text,
                ch.text_preview = $text_preview,
                ch.text_hash = $text_hash,
                ch.paragraph_index = $paragraph_index,
                ch.start_line = $start_line,
                ch.end_line = $end_line
            MERGE (sd)-[:HAS_CHUNK]->(ch)
            MERGE (ch)-[:PART_OF_CALL]->(ec)
            """,
            document_id=chunk.document_id,
            call_id=doc["call_id"],
            id=chunk.id,
            index=chunk.index,
            chunk_type=chunk.chunk_type,
            heading=chunk.heading,
            heading_path=list(getattr(chunk, "heading_path", ()) or ([chunk.heading] if chunk.heading else [])),
            text=chunk.text,
            text_preview=_preview(chunk.text),
            text_hash=_text_hash(chunk.text),
            paragraph_index=getattr(chunk, "paragraph_index", chunk.index),
            start_line=chunk.start_line,
            end_line=chunk.end_line,
        )

    chunks_by_id = {chunk.id: chunk for chunk in extracted.chunks}
    for relation in extracted.relations:
        chunk_id = _relation_chunk_id(relation, chunks_by_id)
        tx.run(
            """
            MATCH (source:Entity {id: $source_entity_id})
            MATCH (target:Entity {id: $target_entity_id})
            MERGE (rf:RelationFact {id: $fact_id})
            SET rf.relation_type = $relation_type,
                rf.scope_id = $scope_id,
                rf.evidence_text = $evidence_text,
                rf.confidence = $confidence,
                rf.extraction_model = $extraction_model,
                rf.extraction_run_id = $extraction_run_id
            SET rf += $properties
            MERGE (rf)-[:FROM_ENTITY]->(source)
            MERGE (rf)-[:TO_ENTITY]->(target)
            MERGE (source)-[projected:RELATED_TO {relation_type: $relation_type}]->(target)
            SET projected.latest_confidence = $confidence
            """,
            fact_id=_relation_fact_id(relation),
            source_entity_id=relation.source_entity_id,
            target_entity_id=relation.target_entity_id,
            relation_type=relation.relation_type,
            scope_id=relation.scope_id,
            evidence_text=relation.evidence_text,
            confidence=relation.confidence,
            extraction_model=getattr(relation, "extraction_model", "unknown"),
            extraction_run_id=getattr(relation, "extraction_run_id", ""),
            properties=dict(getattr(relation, "properties", {}) or {}),
        )
        if chunk_id:
            tx.run(
                """
                MATCH (rf:RelationFact {id: $fact_id})
                MATCH (ch:MarkdownChunk {id: $chunk_id})
                MATCH (source:Entity {id: $source_entity_id})
                MATCH (target:Entity {id: $target_entity_id})
                MERGE (rf)-[:SUPPORTED_BY]->(ch)
                MERGE (ch)-[:MENTIONS_ENTITY]->(source)
                MERGE (ch)-[:MENTIONS_ENTITY]->(target)
                """,
                fact_id=_relation_fact_id(relation),
                chunk_id=chunk_id,
                source_entity_id=relation.source_entity_id,
                target_entity_id=relation.target_entity_id,
            )


def _merge_ontology_mapping(tx, entity_id: str, match: OntologyMatch) -> None:
    concept = match.concept
    _merge_ontology_concept(tx, concept)
    tx.run(
        """
        MATCH (e:Entity {id: $entity_id})
        MATCH (concept:OntologyConcept {id: $concept_id})
        MERGE (e)-[mapped:MAPS_TO]->(concept)
        SET mapped.confidence = $confidence,
            mapped.method = $method,
            mapped.matched_alias = $matched_alias
        """,
        entity_id=entity_id,
        concept_id=concept.id,
        confidence=match.confidence,
        method=match.method,
        matched_alias=match.matched_alias,
    )


def _refresh_ontology_mappings(tx) -> int:
    _merge_ontology_schema(tx)
    tx.run(
        """
        MATCH (:Entity)-[mapped:MAPS_TO]->(:OntologyConcept)
        DELETE mapped
        """
    )
    rows = tx.run(
        """
        MATCH (entity:Entity)
        RETURN entity.id AS id,
               entity.name AS name,
               entity.entity_type AS entity_type,
               coalesce(entity.aliases, []) AS aliases,
               properties(entity) AS properties
        ORDER BY entity.id
        """
    ).data()
    mapping_count = 0
    for row in rows:
        properties = dict(row.get("properties") or {})
        for match in map_entity_to_concepts(
            str(row.get("name") or ""),
            str(row.get("entity_type") or ""),
            aliases=row.get("aliases") or (),
            properties=properties,
        ):
            _merge_ontology_mapping(tx, str(row.get("id") or ""), match)
            mapping_count += 1
    return mapping_count


def _merge_ontology_schema(tx) -> None:
    concepts = {concept.id: concept for concept in load_ontology()}
    tx.run(
        """
        MATCH (:OntologyConcept)-[rel]->(:OntologyConcept)
        WHERE rel.layer = 'ontology_schema'
        DELETE rel
        """
    )
    for concept in concepts.values():
        _merge_ontology_concept(tx, concept)
    for relation in load_ontology_relations():
        if relation.source_id not in concepts or relation.target_id not in concepts:
            continue
        _merge_ontology_relation(tx, relation)


def _merge_ontology_concept(tx, concept: OntologyConcept) -> None:
    tx.run(
        """
        MERGE (concept:OntologyConcept {id: $concept_id})
        SET concept.name = $name,
            concept.concept_type = $concept_type,
            concept.aliases = $aliases,
            concept.description = $description
        """,
        concept_id=concept.id,
        name=concept.name,
        concept_type=concept.concept_type,
        aliases=list(concept.aliases),
        description=concept.description,
    )


def _merge_ontology_relation(tx, relation: OntologyRelation) -> None:
    relation_type = _safe_relationship_type(relation.relation_type)
    tx.run(
        f"""
        MATCH (source:OntologyConcept {{id: $source_id}})
        MATCH (target:OntologyConcept {{id: $target_id}})
        MERGE (source)-[rel:`{relation_type}`]->(target)
        SET rel.description = $description,
            rel.layer = 'ontology_schema'
        """,
        source_id=relation.source_id,
        target_id=relation.target_id,
        description=relation.description,
    )

def _relation_fact_id(relation: Any) -> str:
    relation_id = _attr(relation, "id", "")
    return relation_id if str(relation_id).startswith("fact-") else f"fact-{relation_id}"


def _safe_relationship_type(value: str) -> str:
    relation_type = re.sub(r"[^A-Z0-9_]+", "_", str(value or "").upper()).strip("_")
    return relation_type or "RELATED_TO"


def _relation_chunk_id(relation: Any, chunks_by_id: dict[str, Any]) -> str:
    chunk_id = _attr(relation, "chunk_id", "")
    if chunk_id in chunks_by_id:
        return chunk_id
    scope_id = _attr(relation, "scope_id", "")
    return scope_id if scope_id in chunks_by_id else ""


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _period_id(doc: dict[str, Any]) -> str:
    label = re.sub(r"[^a-z0-9]+", "-", str(doc.get("fiscal_quarter", "period")).lower()).strip("-")
    return label or "period"


def _fiscal_year(label: str) -> int | None:
    match = re.search(r"(?:FY)?(20\d{2})", label, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _quarter(label: str) -> str:
    match = re.search(r"\bQ([1-4])\b", label, re.IGNORECASE)
    return f"Q{match.group(1)}" if match else ""


def _quarter_number(label: str) -> int | None:
    match = re.search(r"\bQ([1-4])\b", label, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _preview(text: str, limit: int = 360) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _stable_id(*parts: Any) -> str:
    text = "|".join(str(part or "") for part in parts)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:80] or "item") + "-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def graph_from_env() -> Neo4jGraph:
    return Neo4jGraph()
