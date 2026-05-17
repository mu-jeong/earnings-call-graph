from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from earnings_call_graph.config import load_dotenv
from earnings_call_graph.graph import graph_from_env


DEFAULT_INDEX_NAME = "markdown_chunk_embedding"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONS = 768
GEMINI_BATCH_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill Gemini embeddings for loaded MarkdownChunk nodes and create "
            "a Neo4j vector index for Similarity Search tools."
        )
    )
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME)
    parser.add_argument("--model", default=os.getenv("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
    parser.add_argument("--dimensions", type=int, default=int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", DEFAULT_DIMENSIONS)))
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--limit", type=int, default=0, help="Maximum chunks to embed; 0 means all pending chunks.")
    parser.add_argument("--force", action="store_true", help="Recompute embeddings even when matching metadata exists.")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("GEMINI_EMBEDDING_TIMEOUT", "120")))
    parser.add_argument("--max-retries", type=int, default=int(os.getenv("GEMINI_EMBEDDING_MAX_RETRIES", "5")))
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("GEMINI_EMBEDDING_RETRY_DELAY", "3")))
    args = parser.parse_args()

    if args.dimensions < 1 or args.dimensions > 4096:
        raise ValueError("--dimensions must be between 1 and 4096 for Neo4j vector indexes.")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1.")

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required to create chunk embeddings.")

    graph = graph_from_env()
    try:
        graph.verify_connectivity()
        print("Neo4j connectivity verified.", flush=True)
        create_vector_index(graph, args.index_name, args.dimensions)
        chunks = pending_chunks(
            graph,
            model=args.model,
            dimensions=args.dimensions,
            force=args.force,
            limit=args.limit,
        )
        print(
            f"Queued {len(chunks)} MarkdownChunk node(s) for embeddings "
            f"(model={args.model}, dimensions={args.dimensions}).",
            flush=True,
        )
        embedded = 0
        for batch_number, batch in enumerate(_batches(chunks, args.batch_size), start=1):
            print(f"Embedding batch {batch_number}: {len(batch)} chunk(s)", flush=True)
            vectors = embed_batch(
                batch,
                api_key=api_key,
                model=args.model,
                dimensions=args.dimensions,
                timeout=args.timeout,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
            )
            rows = [
                {
                    "id": chunk["id"],
                    "embedding": _normalize(vector),
                }
                for chunk, vector in zip(batch, vectors)
            ]
            write_embeddings(graph, rows, model=args.model, dimensions=args.dimensions)
            embedded += len(rows)
            print(f"Backfilled {embedded}/{len(chunks)} chunk embedding(s).", flush=True)
        print_vector_indexes(graph, args.index_name)
        print("Done.", flush=True)
        return 0
    finally:
        graph.close()


def create_vector_index(graph, index_name: str, dimensions: int) -> None:
    query = f"""
    CREATE VECTOR INDEX `{_safe_identifier(index_name)}` IF NOT EXISTS
    FOR (chunk:MarkdownChunk)
    ON (chunk.embedding)
    OPTIONS {{indexConfig: {{
      `vector.dimensions`: $dimensions,
      `vector.similarity_function`: 'cosine'
    }}}}
    """
    with graph.driver.session(database=graph.database) as session:
        session.run(query, {"dimensions": dimensions}).consume()
        session.run("CALL db.awaitIndexes(300)").consume()
    print(f"Vector index ready: {index_name} on (:MarkdownChunk).embedding", flush=True)


def pending_chunks(
    graph,
    *,
    model: str,
    dimensions: int,
    force: bool,
    limit: int,
) -> list[dict[str, str]]:
    limit_clause = "LIMIT $limit" if limit and limit > 0 else ""
    query = f"""
    MATCH (chunk:MarkdownChunk)
    WHERE $force
       OR chunk.embedding IS NULL
       OR chunk.embedding_model <> $model
       OR chunk.embedding_dimensions <> $dimensions
    OPTIONAL MATCH (chunk)<-[:HAS_CHUNK]-(doc:SourceDocument)-[:ABOUT_COMPANY]->(company:Company)
    RETURN chunk.id AS id,
           coalesce(chunk.text, chunk.text_preview, '') AS text,
           coalesce(chunk.heading, '') AS heading,
           coalesce(company.ticker, '') AS ticker,
           coalesce(company.name, '') AS company,
           coalesce(doc.id, '') AS document_id,
           coalesce(doc.title, '') AS document_title
    ORDER BY document_id, chunk.index, chunk.id
    {limit_clause}
    """
    with graph.driver.session(database=graph.database) as session:
        return session.run(
            query,
            {
                "model": model,
                "dimensions": dimensions,
                "force": force,
                "limit": limit,
            },
        ).data()


def embed_batch(
    chunks: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    dimensions: int,
    timeout: float,
    max_retries: int,
    retry_delay: float,
) -> list[list[float]]:
    requests = []
    for chunk in chunks:
        text = _embedding_text(chunk)
        requests.append(
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
                "taskType": "RETRIEVAL_DOCUMENT",
                "title": _title(chunk),
                "outputDimensionality": dimensions,
            }
        )
    payload = json.dumps({"requests": requests}).encode("utf-8")
    url = GEMINI_BATCH_ENDPOINT.format(model=model)
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            envelope = json.loads(raw)
            vectors = [
                item.get("values", [])
                for item in envelope.get("embeddings", [])
                if isinstance(item, dict)
            ]
            if len(vectors) != len(chunks):
                raise RuntimeError(f"Gemini returned {len(vectors)} embedding(s) for {len(chunks)} chunk(s).")
            return [[float(value) for value in vector] for vector in vectors]
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRYABLE_HTTP_STATUS or attempt >= max_retries:
                raise RuntimeError(f"Gemini embedding HTTP {exc.code}: {details}") from exc
            delay = retry_delay * (2**attempt)
            print(f"Gemini HTTP {exc.code}; retrying in {delay:g}s", flush=True)
            time.sleep(delay)
        except urllib.error.URLError as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"Gemini embedding connection failed: {exc}") from exc
            delay = retry_delay * (2**attempt)
            print(f"Gemini connection error; retrying in {delay:g}s", flush=True)
            time.sleep(delay)
    raise RuntimeError("Gemini embedding retry loop exited unexpectedly.")


def write_embeddings(graph, rows: list[dict[str, Any]], *, model: str, dimensions: int) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with graph.driver.session(database=graph.database) as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (chunk:MarkdownChunk {id: row.id})
            SET chunk.embedding = row.embedding,
                chunk.embedding_model = $model,
                chunk.embedding_dimensions = $dimensions,
                chunk.embedding_created_at = $created_at,
                chunk.embedding_source = 'gemini'
            """,
            {
                "rows": rows,
                "model": model,
                "dimensions": dimensions,
                "created_at": created_at,
            },
        ).consume()


def print_vector_indexes(graph, index_name: str) -> None:
    with graph.driver.session(database=graph.database) as session:
        rows = session.run(
            """
            SHOW VECTOR INDEXES
            YIELD name, state, populationPercent, entityType, labelsOrTypes, properties, indexProvider
            WHERE name = $name
            RETURN name, state, populationPercent, entityType, labelsOrTypes, properties, indexProvider
            """,
            {"name": index_name},
        ).data()
        embedded = session.run(
            """
            MATCH (chunk:MarkdownChunk)
            RETURN count(chunk) AS chunks,
                   count(chunk.embedding) AS embedded_chunks
            """
        ).single()
    for row in rows:
        print(
            "Vector index: "
            f"{row['name']} state={row['state']} population={row['populationPercent']} "
            f"entityType={row['entityType']} labels={row['labelsOrTypes']} "
            f"properties={row['properties']} provider={row['indexProvider']}",
            flush=True,
        )
    print(
        f"Embedded chunks: {embedded['embedded_chunks']}/{embedded['chunks']}",
        flush=True,
    )


def _embedding_text(chunk: dict[str, str]) -> str:
    parts = [
        f"Company: {chunk.get('company') or chunk.get('ticker')}",
        f"Ticker: {chunk.get('ticker')}",
        f"Document: {chunk.get('document_title') or chunk.get('document_id')}",
        f"Heading: {chunk.get('heading')}",
        "Text:",
        chunk.get("text") or "",
    ]
    return "\n".join(part for part in parts if part and part.strip())[:8000]


def _title(chunk: dict[str, str]) -> str:
    title = " | ".join(
        part
        for part in (
            chunk.get("ticker"),
            chunk.get("document_title") or chunk.get("document_id"),
            chunk.get("heading"),
        )
        if part
    )
    return title[:512] or chunk.get("id", "MarkdownChunk")


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]


def _safe_identifier(value: str) -> str:
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in value)
    return safe or DEFAULT_INDEX_NAME


def _batches(items: list[dict[str, str]], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


if __name__ == "__main__":
    raise SystemExit(main())

