from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .graph import graph_from_env
from .markdown_ingest import load_extracted_document

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class ExportLoadResult:
    input_path: Path
    document_id: str
    chunk_count: int
    qa_pair_count: int
    entity_count: int
    relation_count: int
    reset_applied: bool = False


def exported_graph_paths(
    input_path: str | Path = "exports/earnings_graph",
    *,
    pattern: str = "*-graph.json",
) -> list[Path]:
    root = Path(input_path)
    if root.is_file():
        if root.suffix.lower() != ".json":
            raise ValueError(f"Expected a graph JSON file, got {root}")
        return [root]

    paths = sorted(root.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"No exported graph JSON files matched {root / pattern}")
    return paths


def load_exported_graphs(
    input_path: str | Path = "exports/earnings_graph",
    *,
    pattern: str = "*-graph.json",
    reset_first: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> list[ExportLoadResult]:
    paths = exported_graph_paths(input_path, pattern=pattern)
    _progress(progress_callback, f"Found {len(paths)} exported graph JSON file(s)")

    graph = graph_from_env()
    results: list[ExportLoadResult] = []
    try:
        _progress(progress_callback, "Connecting to Neo4j")
        graph.verify_connectivity()
        _progress(progress_callback, "Neo4j connectivity verified")
        for index, path in enumerate(paths):
            reset = reset_first and index == 0
            _progress(progress_callback, f"[{index + 1}/{len(paths)}] Loading {path}")
            extracted = load_extracted_document(path)
            graph.load_extracted_document(extracted, reset=reset)
            results.append(
                ExportLoadResult(
                    input_path=path,
                    document_id=extracted.document["id"],
                    chunk_count=len(extracted.chunks),
                    qa_pair_count=len(extracted.qa_pairs),
                    entity_count=len(extracted.entities),
                    relation_count=len(extracted.relations),
                    reset_applied=reset,
                )
            )
            _progress(
                progress_callback,
                f"[{index + 1}/{len(paths)}] Loaded {extracted.document['id']}"
                f" (chunks={len(extracted.chunks)}, entities={len(extracted.entities)},"
                f" relations={len(extracted.relations)}, reset={reset})",
            )
    finally:
        graph.close()
        _progress(progress_callback, "Neo4j connection closed")

    _progress(progress_callback, f"Loaded {len(results)} exported graph JSON file(s)")
    return results


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
