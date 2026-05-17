from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .graph import graph_from_env
from .markdown_ingest import ExtractedDocument, ingest_markdown_document, load_extracted_document
from .source_documents import materialize_source_markdown
from .sources import load_manifest_metadata

ProgressCallback = Callable[[str], None]

CONFERENCE_CALL_SOURCE_TYPES = frozenset(
    {
        "transcript_pdf",
        "transcript_html",
        "conference_call_transcript_html",
        "conference_call_event_html",
        "conference_call_prepared_remarks_html",
        "conference_call_prepared_remarks_pdf",
        "earnings_call_transcript_html",
        "seeking_alpha_transcript_html",
        "third_party_transcript_html",
    }
)

@dataclass(frozen=True)
class PipelineResult:
    input_path: Path
    output_path: Path
    document_id: str
    chunk_count: int
    qa_pair_count: int
    entity_count: int
    relation_count: int
    claim_count: int
    loaded: bool = False
    reused_existing_output: bool = False


def load_metadata_manifest(path: str | Path | None) -> dict[str, dict[str, str]]:
    return load_manifest_metadata(path)


def process_markdown_folder(
    input_dir: str | Path = "data/source_inputs",
    output_dir: str | Path = "exports/earnings_graph",
    *,
    manifest: str | Path | None = None,
    pattern: str = "*.md",
    max_documents: int | None = None,
    use_llm: bool = True,
    use_source_documents: bool = False,
    source_cache_dir: str | Path = "data/source_cache",
    refresh_source_cache: bool = False,
    llm_delay_seconds: float = 0.0,
    llm_chunk_batch_size: int = 8,
    load_to_neo4j: bool = False,
    reset_neo4j: bool = False,
    skip_existing: bool = True,
    require_conference_call_source: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> list[PipelineResult]:
    started_at = time.monotonic()
    input_root = Path(input_dir)
    output_root = Path(output_dir)
    _progress(progress_callback, f"Loading metadata manifest: {manifest or 'data/sources/major_companies.json'}")
    metadata = load_metadata_manifest(manifest)
    markdown_files = sorted(input_root.glob(pattern))
    if not markdown_files and use_source_documents:
        markdown_files = sorted(input_root / filename for filename in metadata)
    if require_conference_call_source:
        before_count = len(markdown_files)
        markdown_files = [path for path in markdown_files if _is_conference_call_source(metadata.get(path.name, {}))]
        skipped_count = before_count - len(markdown_files)
        if skipped_count:
            _progress(
                progress_callback,
                f"Skipped {skipped_count} document(s) without a confirmed conference-call transcript source",
            )
    if use_source_documents:
        before_count = len(markdown_files)
        markdown_files = [path for path in markdown_files if metadata.get(path.name, {}).get("source_url", "").strip()]
        skipped_count = before_count - len(markdown_files)
        if skipped_count:
            _progress(
                progress_callback,
                f"Skipped {skipped_count} document(s) without a configured source_url",
            )
        if not markdown_files:
            raise ValueError(
                "No source_url values are configured. Fill the public manifest locally or pass a private manifest with --manifest."
            )
    if max_documents is not None:
        if max_documents < 1:
            raise ValueError("max_documents must be >= 1 when provided.")
        markdown_files = markdown_files[:max_documents]
    if not markdown_files:
        raise FileNotFoundError(f"No Markdown files matched {input_root / pattern}")
    _progress(
        progress_callback,
        f"Queued {len(markdown_files)} document(s) from {input_root} "
        f"(source_documents={use_source_documents}, llm={use_llm}, llm_chunk_batch_size={llm_chunk_batch_size})",
    )

    graph = None
    if load_to_neo4j:
        _progress(progress_callback, "Connecting to Neo4j")
        graph = graph_from_env()
        graph.verify_connectivity()
        _progress(progress_callback, "Neo4j connectivity verified")

    results: list[PipelineResult] = []
    try:
        for index, markdown_path in enumerate(markdown_files):
            doc_started_at = time.monotonic()
            doc_label = f"[{index + 1}/{len(markdown_files)}] {markdown_path.name}"
            _progress(progress_callback, f"{doc_label}: starting")
            doc_metadata = metadata.get(markdown_path.name)
            if doc_metadata is None:
                raise KeyError(
                    f"No metadata for {markdown_path.name}. Add it to data/sources/major_companies.json or pass --manifest."
                )
            output_path = output_root / f"{markdown_path.stem}-graph.json"

            reused_existing_output = False
            extracted = _load_existing_output(output_path, progress_callback, doc_label) if skip_existing else None
            if extracted is not None:
                reused_existing_output = True
            else:
                ingest_path = markdown_path
                if use_source_documents:
                    _progress(progress_callback, f"{doc_label}: materializing official source text")
                    source_text = materialize_source_markdown(
                        source_url=_required(doc_metadata, "source_url", markdown_path.name),
                        title=f"{_required(doc_metadata, 'company', markdown_path.name)} {_required(doc_metadata, 'quarter', markdown_path.name)} Official Source",
                        slug=markdown_path.stem,
                        cache_dir=source_cache_dir,
                        refresh=refresh_source_cache,
                        progress_callback=progress_callback,
                    )
                    ingest_path = source_text.markdown_path
                    doc_metadata = {
                        **doc_metadata,
                        "source_url": getattr(source_text, "source_url", doc_metadata.get("source_url", "")),
                        "source_type": getattr(source_text, "content_type", "") or doc_metadata.get("source_type", ""),
                    }
                    _progress(progress_callback, f"{doc_label}: source Markdown ready at {ingest_path}")

                _progress(progress_callback, f"{doc_label}: extracting graph data")
                extracted = _ingest_with_metadata(
                    ingest_path,
                    doc_metadata,
                    use_llm=use_llm,
                    llm_chunk_batch_size=llm_chunk_batch_size,
                    progress_callback=progress_callback,
                )
                _progress(progress_callback, f"{doc_label}: writing graph JSON to {output_path}")
                extracted.write_json(output_path)

            loaded = False
            if graph is not None:
                _progress(progress_callback, f"{doc_label}: loading graph JSON into Neo4j")
                graph.load_extracted_document(
                    load_extracted_document(output_path),
                    reset=reset_neo4j and index == 0,
                )
                loaded = True
                _progress(progress_callback, f"{doc_label}: Neo4j load complete")

            results.append(
                _pipeline_result(
                    markdown_path,
                    output_path,
                    extracted,
                    loaded=loaded,
                    reused_existing_output=reused_existing_output,
                )
            )
            result = results[-1]
            _progress(
                progress_callback,
                f"{doc_label}: done in {_elapsed(doc_started_at)} "
                f"(chunks={result.chunk_count}, qa={result.qa_pair_count}, "
                f"entities={result.entity_count}, relations={result.relation_count}, "
                f"source={'existing' if result.reused_existing_output else 'generated'})",
            )
            if use_llm and llm_delay_seconds > 0 and index < len(markdown_files) - 1:
                _progress(progress_callback, f"{doc_label}: waiting {llm_delay_seconds:g}s before next Gemini document request")
                time.sleep(llm_delay_seconds)
    finally:
        if graph is not None:
            graph.close()
            _progress(progress_callback, "Neo4j connection closed")

    _progress(progress_callback, f"Processed {len(results)} document(s) in {_elapsed(started_at)}")
    return results


def _ingest_with_metadata(
    markdown_path: Path,
    doc_metadata: dict[str, str],
    *,
    use_llm: bool,
    llm_chunk_batch_size: int = 8,
    progress_callback: ProgressCallback | None = None,
) -> ExtractedDocument:
    return ingest_markdown_document(
        markdown_path,
        company_name=_required(doc_metadata, "company", markdown_path.name),
        company_id=doc_metadata.get("company_id"),
        ticker=doc_metadata.get("ticker", ""),
        sector=doc_metadata.get("sector", ""),
        fiscal_quarter=_required(doc_metadata, "quarter", markdown_path.name),
        call_id=doc_metadata.get("call_id"),
        call_date=doc_metadata.get("call_date", ""),
        source_url=_required(doc_metadata, "source_url", markdown_path.name),
        source_kind=doc_metadata.get("source_type", "official_ir_transcript_markdown"),
        use_llm=use_llm,
        llm_chunk_batch_size=llm_chunk_batch_size,
        progress_callback=progress_callback,
    )


def _pipeline_result(
    input_path: Path,
    output_path: Path,
    extracted: ExtractedDocument,
    *,
    loaded: bool,
    reused_existing_output: bool = False,
) -> PipelineResult:
    return PipelineResult(
        input_path=input_path,
        output_path=output_path,
        document_id=extracted.document["id"],
        chunk_count=len(extracted.chunks),
        qa_pair_count=len(extracted.qa_pairs),
        entity_count=len(extracted.entities),
        relation_count=len(extracted.relations),
        claim_count=sum(len(answer.claims) for answer in extracted.answers),
        loaded=loaded,
        reused_existing_output=reused_existing_output,
    )


def _load_existing_output(
    output_path: Path,
    progress_callback: ProgressCallback | None,
    doc_label: str,
) -> ExtractedDocument | None:
    if not output_path.exists():
        return None
    try:
        extracted = load_extracted_document(output_path)
    except Exception as exc:
        _progress(
            progress_callback,
            f"{doc_label}: existing graph JSON at {output_path} is not reusable ({exc}); regenerating",
        )
        return None
    _progress(progress_callback, f"{doc_label}: existing graph JSON found at {output_path}; skipping extraction")
    return extracted


def _required(metadata: dict[str, str], key: str, filename: str) -> str:
    value = metadata.get(key, "").strip()
    if not value:
        hint = (
            " Fill this value in a private manifest passed with --manifest, or edit the local manifest before running sync."
            if key == "source_url"
            else ""
        )
        raise ValueError(f"Metadata for {filename} is missing required field {key!r}.{hint}")
    return value


def _is_conference_call_source(metadata: dict[str, str]) -> bool:
    confirmed = metadata.get("conference_call_confirmed", "").strip().lower()
    if confirmed in {"false", "no", "0"}:
        return False
    source_type = metadata.get("source_type", "").strip().lower()
    return source_type in CONFERENCE_CALL_SOURCE_TYPES


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _elapsed(started_at: float) -> str:
    return f"{time.monotonic() - started_at:.1f}s"
