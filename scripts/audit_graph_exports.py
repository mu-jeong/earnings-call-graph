"""Audit generated graph JSON files for hackathon demo curation.

The audit is intentionally conservative: it flags files that may still be valid
official results pages but should be reviewed before a public demo. It does not
modify graph data.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


POSITIVE_SOURCE_TERMS = (
    "transcript",
    "earnings",
    "prepared-remarks",
    "prepared_remarks",
    "results",
    "quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "call",
)

OFF_TOPIC_SOURCE_TERMS = (
    "supply-chain",
    "transparency",
    "sustainability",
    "annual-report",
    "annual_report",
    "proxy",
    "code-of-conduct",
    "privacy",
)


@dataclass(frozen=True)
class AuditRow:
    path: Path
    ticker: str
    company: str
    quarter: str
    chunks: int
    entities: int
    relations: int
    url: str
    warnings: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def audit_file(path: Path) -> AuditRow:
    payload = _read_json(path)
    document = payload.get("document") or {}
    if not isinstance(document, dict):
        document = {}

    url = str(document.get("source_url") or "")
    title = str(document.get("title") or "")
    source_kind = str(document.get("source_kind") or "")
    source_text = f"{url} {title} {source_kind}".lower()

    warnings: list[str] = []
    if not any(term in source_text for term in POSITIVE_SOURCE_TERMS):
        warnings.append("source does not include an earnings/transcript/call keyword")
    matched_off_topic = [term for term in OFF_TOPIC_SOURCE_TERMS if term in source_text]
    if matched_off_topic:
        warnings.append(f"off-topic source keyword(s): {', '.join(matched_off_topic)}")

    chunks = len(payload.get("chunks") or [])
    entities = len(payload.get("entities") or [])
    relations = len(payload.get("relations") or [])
    if chunks == 0:
        warnings.append("no chunks")
    if entities == 0:
        warnings.append("no entities")
    if relations == 0:
        warnings.append("no relations")

    return AuditRow(
        path=path,
        ticker=str(document.get("ticker") or ""),
        company=str(document.get("company_name") or ""),
        quarter=str(document.get("fiscal_quarter") or ""),
        chunks=chunks,
        entities=entities,
        relations=relations,
        url=url,
        warnings=tuple(warnings),
    )


def discover_graph_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*graph.json") if path.is_file())


def print_audit(rows: list[AuditRow]) -> None:
    if not rows:
        print("No *graph.json files found.")
        return

    flagged = 0
    for row in rows:
        status = "WARN" if row.warnings else "OK"
        if row.warnings:
            flagged += 1
        print(
            f"{status:4} {row.path} | {row.ticker or '-'} {row.quarter or '-'} | "
            f"chunks={row.chunks} entities={row.entities} relations={row.relations}"
        )
        if row.warnings:
            for warning in row.warnings:
                print(f"     - {warning}")
            if row.url:
                print(f"       url: {row.url}")

    print()
    print(f"Audited {len(rows)} graph file(s); {flagged} need review.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default="exports",
        type=Path,
        help="Directory to scan for *graph.json files. Defaults to exports/.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 when any file needs review.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = [audit_file(path) for path in discover_graph_files(args.root)]
    print_audit(rows)
    if args.strict and any(row.warnings for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
