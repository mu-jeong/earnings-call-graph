from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from time import strftime
from typing import Any

from .export_loader import load_exported_graphs
from .graph import graph_from_env
from .markdown_ingest import DEFAULT_ALLOWED_THEMES, ingest_markdown_document, load_extracted_document
from .pipeline import process_markdown_folder

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
}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="earnings-call-graph",
        description="Earnings-call graph CLI: ingest/load graph data, ask graph-backed questions, and explain key nodes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_markdown = sub.add_parser(
        "ingest-markdown",
        help="Parse a normalized conference-call Markdown document into chunk-scoped entity/relation graph JSON",
    )
    ingest_markdown.add_argument("input", help="Local normalized Markdown transcript")
    ingest_markdown.add_argument("--company", required=True, help="Company name, e.g. Alphabet")
    ingest_markdown.add_argument("--company-id", help="Stable company id for graph merges, e.g. googl")
    ingest_markdown.add_argument("--ticker", default="", help="Ticker symbol")
    ingest_markdown.add_argument("--sector", default="", help="Sector label")
    ingest_markdown.add_argument("--quarter", required=True, help="Fiscal quarter, e.g. FY2026 Q1")
    ingest_markdown.add_argument("--call-id", help="Stable earnings call id, e.g. googl-2026q1")
    ingest_markdown.add_argument("--call-date", default="", help="Call date in YYYY-MM-DD when known")
    ingest_markdown.add_argument("--source-url", required=True, help="Official IR/SEC source URL")
    ingest_markdown.add_argument(
        "--themes",
        default=",".join(DEFAULT_ALLOWED_THEMES),
        help="Comma-separated seed themes for ontology hints",
    )
    ingest_markdown.add_argument(
        "--llm-chunk-batch-size",
        type=int,
        default=8,
        help="Number of paragraph chunks to extract per Gemini request; set 1 to disable chunk batching",
    )
    ingest_markdown.add_argument("--out", required=True, help="Output extracted graph JSON path")

    load_extracted = sub.add_parser("load-extracted", help="Load one extracted graph JSON into Neo4j")
    load_extracted.add_argument("input", help="JSON produced by ingest-markdown or the Alphabet prototype")
    load_extracted.add_argument("--reset", action="store_true", help="Delete existing graph data before loading")

    load_graphs = sub.add_parser(
        "load",
        help="Load parsed graph JSON into Neo4j from one file or a folder (defaults to exports/earnings_graph)",
    )
    load_graphs.add_argument(
        "path",
        nargs="?",
        default="exports/earnings_graph",
        help="Graph JSON file or folder containing graph JSON files",
    )
    load_graphs.add_argument(
        "--pattern",
        default="*-graph.json",
        help="Glob pattern used when path is a folder",
    )
    load_graphs.add_argument("--reset", action="store_true", help="Reset Neo4j before loading the first graph")

    sync = sub.add_parser(
        "sync",
        help="Materialize sources, extract graph JSON, and load Neo4j in one command",
    )
    sync.add_argument(
        "--input-dir",
        default="data/source_inputs",
        help="Optional folder of local Markdown files; absent files are materialized from the manifest by default",
    )
    sync.add_argument(
        "--output-dir",
        default="exports/earnings_graph",
        help="Folder for generated or reusable *-graph.json files",
    )
    sync.add_argument("--pattern", default="*.md", help="Glob pattern for local Markdown files")
    sync.add_argument(
        "--graph-pattern",
        default="*-graph.json",
        help="Glob pattern for --load-only graph JSON files",
    )
    sync.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of source documents to process; default keeps runs intentionally small",
    )
    sync.add_argument("--manifest", help="Optional source registry JSON; merged over data/sources/major_companies.json")
    sync.add_argument(
        "--use-fixtures",
        action="store_true",
        help="Use local Markdown files instead of downloading/extracting official source_url documents",
    )
    sync.add_argument(
        "--source-cache-dir",
        default="data/source_cache",
        help="Cache folder for downloaded official sources and extracted Markdown",
    )
    sync.add_argument(
        "--refresh-source-cache",
        action="store_true",
        help="Redownload official source_url documents even when cached files exist",
    )
    sync.add_argument(
        "--llm-delay",
        type=float,
        default=10.0,
        help="Seconds to wait between Gemini document requests",
    )
    sync.add_argument(
        "--llm-chunk-batch-size",
        type=int,
        default=8,
        help="Number of paragraph chunks to extract per Gemini request; set 1 to disable chunk batching",
    )
    sync.add_argument("--gemini-max-retries", type=int, default=6, help="Retry count for retryable Gemini errors")
    sync.add_argument("--gemini-retry-delay", type=float, default=5.0, help="Base seconds for Gemini backoff retries")
    sync.add_argument("--gemini-timeout", type=float, default=180.0, help="Seconds to wait for each Gemini response")
    sync.add_argument(
        "--json-only",
        action="store_true",
        help="Only write/reuse graph JSON files; skip Neo4j loading",
    )
    sync.add_argument(
        "--load-only",
        action="store_true",
        help="Only load existing graph JSON files from --output-dir; skip source parsing",
    )
    sync.add_argument("--reset", action="store_true", help="Reset Neo4j before loading the first graph")
    sync.add_argument(
        "--force",
        action="store_true",
        help="Regenerate graph JSON even when the expected output file already exists",
    )
    sync.add_argument(
        "--include-unverified-sources",
        action="store_true",
        help="Also process manifest entries that are not confirmed conference-call transcript sources",
    )

    ask = sub.add_parser("ask", help="Ask a graph-backed question by matching RelationFact evidence and entity names")
    ask.add_argument("question")
    ask.add_argument("--limit", type=int, default=12, help="Maximum relation rows to use")
    ask.add_argument("--json", action="store_true", help="Return JSON instead of Markdown")

    key_nodes = sub.add_parser("key-nodes", help="Rank important entity nodes from the loaded conference-call graph")
    key_nodes.add_argument("--limit", type=int, default=25, help="Maximum nodes to return")

    explain_node = sub.add_parser("explain-node", help="Explain one key node with direct graph context")
    explain_node.add_argument("node_id", help="Entity node id from key-nodes")
    explain_node.add_argument("--limit", type=int, default=12, help="Maximum relation rows to use")
    explain_node.add_argument("--json", action="store_true", help="Return JSON instead of Markdown")

    args = parser.parse_args(argv)

    if args.command == "ingest-markdown":
        allowed_themes = [theme.strip() for theme in args.themes.split(",") if theme.strip()]
        extracted = ingest_markdown_document(
            args.input,
            company_name=args.company,
            company_id=args.company_id,
            ticker=args.ticker,
            sector=args.sector,
            fiscal_quarter=args.quarter,
            call_id=args.call_id,
            call_date=args.call_date,
            source_url=args.source_url,
            allowed_themes=allowed_themes,
            llm_chunk_batch_size=args.llm_chunk_batch_size,
            progress_callback=_print_progress,
        )
        extracted.write_json(args.out)
        print(
            "Wrote "
            f"{args.out}: {len(extracted.chunks)} chunks, "
            f"{len(extracted.entities)} entities, "
            f"{len(extracted.relations)} relations"
        )
        return 0

    if args.command == "load-extracted":
        extracted = load_extracted_document(args.input)
        graph = graph_from_env()
        try:
            graph.verify_connectivity()
            graph.load_extracted_document(extracted, reset=args.reset)
        finally:
            graph.close()
        print(
            f"Loaded {extracted.document['id']} into Neo4j "
            f"({len(extracted.chunks)} chunks, {len(extracted.entities)} entities, {len(extracted.relations)} relations)"
        )
        return 0

    if args.command == "load":
        results = load_exported_graphs(
            args.path,
            pattern=args.pattern,
            reset_first=args.reset,
            progress_callback=_print_progress,
        )
        _print_export_load_results(results)
        return 0

    if args.command == "sync":
        os.environ["GEMINI_MAX_RETRIES"] = str(args.gemini_max_retries)
        os.environ["GEMINI_RETRY_DELAY"] = str(args.gemini_retry_delay)
        os.environ["GEMINI_TIMEOUT"] = str(args.gemini_timeout)

        if args.load_only:
            results = load_exported_graphs(
                args.output_dir,
                pattern=args.graph_pattern,
                reset_first=args.reset,
                progress_callback=_print_progress,
            )
            _print_export_load_results(results)
            return 0

        results = process_markdown_folder(
            args.input_dir,
            args.output_dir,
            manifest=args.manifest,
            pattern=args.pattern,
            max_documents=args.limit,
            use_llm=True,
            use_source_documents=not args.use_fixtures,
            source_cache_dir=args.source_cache_dir,
            refresh_source_cache=args.refresh_source_cache,
            llm_delay_seconds=args.llm_delay,
            llm_chunk_batch_size=args.llm_chunk_batch_size,
            load_to_neo4j=not args.json_only,
            reset_neo4j=args.reset,
            skip_existing=not args.force,
            require_conference_call_source=not args.include_unverified_sources,
            progress_callback=_print_progress,
        )
        for result in results:
            loaded = " loaded" if result.loaded else ""
            source = " reused-existing" if result.reused_existing_output else " generated"
            print(
                f"{result.input_path} -> {result.output_path}"
                f" | chunks={result.chunk_count}"
                f" qa={result.qa_pair_count}"
                f" entities={result.entity_count}"
                f" relations={result.relation_count}"
                f" claims={result.claim_count}"
                f"{source}"
                f"{loaded}"
            )
        action = "Synced" if not args.json_only else "Processed"
        print(f"{action} {len(results)} document(s).")
        return 0

    if args.command == "ask":
        rows = _graph_relation_rows(args.question, limit=args.limit)
        rows = sorted(rows, key=lambda row: _insight_rank(row, _query_terms(args.question)))
        answer = _answer_from_rows(args.question, rows)
        if args.json:
            print(json.dumps({"question": args.question, "answer": answer, "rows": rows}, ensure_ascii=False, indent=2))
        else:
            print(_answer_markdown(answer, rows))
        return 0

    if args.command == "key-nodes":
        graph = graph_from_env()
        try:
            graph.verify_connectivity()
            rows = graph.rank_key_nodes(limit=args.limit)
        finally:
            graph.close()
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if args.command == "explain-node":
        graph = graph_from_env()
        try:
            graph.verify_connectivity()
            rows = graph.question_context(args.node_id, limit=args.limit)
        finally:
            graph.close()
        answer = _explain_node(args.node_id, rows)
        if args.json:
            print(json.dumps({"node_id": args.node_id, "answer": answer, "rows": rows}, ensure_ascii=False, indent=2))
        else:
            print(_node_markdown(answer, rows))
        return 0

    parser.error("Unknown command")
    return 2


def _print_export_load_results(results) -> None:
    for result in results:
        reset = " reset" if result.reset_applied else ""
        print(
            f"{result.input_path} -> {result.document_id}"
            f" | chunks={result.chunk_count}"
            f" qa={result.qa_pair_count}"
            f" entities={result.entity_count}"
            f" relations={result.relation_count}"
            f"{reset}"
        )
    print(f"Loaded {len(results)} exported graph JSON file(s).")


def _graph_relation_rows(search: str, *, limit: int) -> list[dict[str, Any]]:
    terms = _query_terms(search)
    graph = graph_from_env()
    try:
        graph.verify_connectivity()
        with graph.driver.session(database=graph.database) as session:
            return session.run(
                """
                MATCH (fact:RelationFact)-[:FROM_ENTITY]->(src:Entity),
                      (fact)-[:TO_ENTITY]->(dst:Entity)
                WITH fact, src, dst,
                     [term IN $terms WHERE
                        toLower(src.name) CONTAINS term
                     OR toLower(dst.name) CONTAINS term
                     OR toLower(coalesce(fact.evidence_text, '')) CONTAINS term
                     OR toLower(fact.relation_type) CONTAINS term] AS matched_terms
                WHERE size($terms) = 0 OR size(matched_terms) > 0
                OPTIONAL MATCH (fact)-[:SUPPORTED_BY]->(chunk:MarkdownChunk)<-[:HAS_CHUNK]-(source_doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
                RETURN company.name AS company,
                       company.ticker AS ticker,
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
                       source_doc.source_url AS source_url
                ORDER BY CASE coalesce(fact.layer, 'coverage') WHEN 'insight' THEN 1 ELSE 0 END DESC,
                         size(matched_terms) DESC, coalesce(fact.confidence, 0.0) DESC, company, source, relation, target
                LIMIT $limit
                """,
                {"terms": terms, "limit": limit},
            ).data()
    finally:
        graph.close()


def _answer_from_rows(question: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {
            "summary": f"No graph relations matched: {question}",
            "upside": "No graph-backed upside relation found.",
            "risk": "No graph-backed risk relation found.",
            "basis": "0 RelationFact rows matched.",
        }
    positive = {"DRIVES", "INCREASES", "OFFSETS", "GUIDES_TO", "CONVERTS_TO"}
    negative = {"PRESSURES", "RISKS", "CONSTRAINS", "EXPOSED_TO", "REDUCES", "AFFECTS"}
    ranked = sorted(rows, key=lambda row: _insight_rank(row, _query_terms(question)))
    upside = [row for row in ranked if row.get("relation") in positive]
    risk = [row for row in ranked if row.get("relation") in negative]
    companies = sorted({row.get("company") for row in rows if row.get("company")})
    return {
        "summary": f"Found {len(rows)} matching graph relation(s). Main path: {_path(ranked[0])}.",
        "upside": "; ".join(_path(row) for row in upside[:3]) or "No upside/support relation in matched rows.",
        "risk": "; ".join(_path(row) for row in risk[:3]) or "No risk/pressure relation in matched rows.",
        "basis": f"Companies: {', '.join(companies) if companies else 'n/a'}. Grounded in RelationFact evidence linked to MarkdownChunk nodes.",
    }


def _explain_node(node_id: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    node_name = rows[0].get("node_name") if rows else node_id
    if not rows:
        return {
            "summary": f"No graph context found for {node_id}.",
            "connections": "No relation paths found.",
            "evidence": "No evidence snippets found.",
        }
    companies = sorted({row.get("company") for row in rows if row.get("company")})
    ranked = sorted(rows, key=_insight_rank)
    values = [
        _entity_display(row.get("target"), row.get("target_properties"))
        for row in ranked
        if row.get("target_type") == "MetricValue"
    ] + [
        _entity_display(row.get("source"), row.get("source_properties"))
        for row in ranked
        if row.get("source_type") == "MetricValue"
    ]
    value_note = f" Key metric/value nodes: {', '.join(dict.fromkeys(value for value in values if value))}." if values else ""
    return {
        "summary": f"{node_name} is connected to {len(rows)} relation fact(s) across {len(companies)} company context(s).{value_note}",
        "connections": "; ".join(_path(row) for row in ranked[:5]),
        "evidence": str(next((row.get("evidence") or row.get("chunk_preview") for row in rows if row.get("evidence") or row.get("chunk_preview")), "No evidence text stored.")),
    }


def _answer_markdown(answer: dict[str, str], rows: list[dict[str, Any]]) -> str:
    lines = [f"## Answer", "", answer["summary"], "", f"**Upside/support:** {answer['upside']}", "", f"**Risk/pressure:** {answer['risk']}", "", answer["basis"]]
    if rows:
        lines.extend(["", "### Evidence"])
        for row in rows[:8]:
            lines.append(f"- {_path(row)} -- {row.get('evidence') or ''}")
    return "\n".join(lines)


def _node_markdown(answer: dict[str, str], rows: list[dict[str, Any]]) -> str:
    lines = ["## Key node explanation", "", answer["summary"], "", f"**Connections:** {answer['connections']}", "", f"**Representative evidence:** {answer['evidence']}"]
    if rows:
        lines.extend(["", "### Context rows"])
        for row in rows[:8]:
            lines.append(f"- {_path(row)} -- {row.get('evidence') or ''}")
    return "\n".join(lines)


def _path(row: dict[str, Any]) -> str:
    source = _entity_display(row.get("source"), row.get("source_properties"))
    target = _entity_display(row.get("target"), row.get("target_properties"))
    return f"{source} --{row.get('relation') or ''}--> {target}".strip()


def _entity_display(name: Any, properties: Any) -> str:
    props = properties if isinstance(properties, dict) else {}
    value = props.get("value")
    return f"{name} ({value})" if name and value else str(name or "")


def _query_terms(question: str) -> list[str]:
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


def _insight_rank(row: dict[str, Any], terms: list[str] | None = None) -> tuple[int, int, str]:
    haystack = " ".join(
        str(row.get(key) or "").lower()
        for key in ("source", "target", "relation", "evidence", "chunk_preview")
    )
    relevance = sum(1 for term in terms or [] if term.lower() in haystack)
    type_bonus = 0
    if row.get("target_type") == "MetricValue" or row.get("source_type") == "MetricValue":
        type_bonus += 3
    if row.get("target_type") == "BusinessOutcome" or row.get("source_type") == "BusinessOutcome":
        type_bonus += 2
    relation_bonus = 2 if row.get("relation") in {"CONVERTS_TO", "PRESSURES", "REDUCES", "DRIVES"} else 0
    layer_bonus = 6 if row.get("relation_layer") == "insight" else 0
    return (-(relevance * 4 + type_bonus + relation_bonus + layer_bonus), -relevance, str(row.get("source") or ""))


def _print_progress(message: str) -> None:
    print(f"[{strftime('%H:%M:%S')}] [earnings_call_graph] {message}", flush=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
