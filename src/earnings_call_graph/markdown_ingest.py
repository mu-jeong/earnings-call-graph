from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ALLOWED_THEMES = (
    "AI demand",
    "AI capex",
    "cloud growth",
    "data center capacity",
    "semiconductor supply",
    "component cost",
    "FX headwind",
    "consumer demand",
    "pricing power",
    "margin pressure",
    "regulatory risk",
)

THEME_ALIASES: dict[str, tuple[str, ...]] = {
    "AI demand": ("ai demand", "ai workload", "ai usage", "ai products", "agentic ai", "compute needs"),
    "AI capex": ("ai capex", "capex", "capital expenditures", "infrastructure capex", "infrastructure spend"),
    "cloud growth": ("cloud", "azure", "microsoft cloud", "creative cloud"),
    "data center capacity": ("data center", "capacity", "compute", "power", "inference capacity"),
    "semiconductor supply": ("semiconductor", "leading-edge", "advanced nodes", "3-nanometer", "n3", "hpc"),
    "component cost": ("memory pricing", "component pricing", "higher component costs"),
    "FX headwind": ("fx", "foreign exchange", "currency"),
    "consumer demand": ("consumer", "unit case volume", "nartd"),
    "pricing power": ("pricing", "price/mix", "revenue growth management"),
    "margin pressure": ("margin", "gross margin", "operating margin", "cost pressure", "expense"),
    "regulatory risk": ("regulatory", "legal", "eu", "scrutiny"),
}

METRIC_TERMS = (
    "ARR",
    "MAU",
    "N3 capacity",
    "AI credit consumption",
    "Azure growth",
    "CapEx",
    "capital expenditures",
    "cloud revenue",
    "compute needs",
    "cost of revenue",
    "gross margin",
    "inference capacity",
    "infrastructure capex forecast",
    "monthly active users",
    "operating margin",
    "price/mix",
    "revenue",
    "total expenses",
    "unit case volume",
)

RISK_TERMS = (
    "capacity constraint",
    "capacity tightness",
    "component costs",
    "data center operating costs",
    "depreciation",
    "execution timing",
    "foreign exchange",
    "gross margin pressure",
    "investment efficiency",
    "margin dilution",
    "margin pressure",
    "memory pricing",
    "near-term ARR impact",
    "regulatory scrutiny",
)

CLAIM_KEYWORDS = (
    "expect",
    "forecast",
    "growth",
    "increase",
    "increased",
    "raising",
    "raised",
    "demand",
    "cost",
    "expense",
    "margin",
    "capacity",
    "risk",
    "pressure",
    "investment",
    "capex",
    "revenue",
)


@dataclass(frozen=True)
class ExtractedEntity:
    id: str
    name: str
    entity_type: str
    source: str = "heuristic"
    properties: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ExtractedRelation:
    id: str
    source_entity_id: str
    relation_type: str
    target_entity_id: str
    scope_id: str
    evidence_text: str
    confidence: float = 0.7
    properties: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class MarkdownChunk:
    id: str
    document_id: str
    index: int
    chunk_type: str
    heading: str
    text: str
    start_line: int
    end_line: int
    speaker_name: str = ""
    speaker_title: str = ""
    text_hash: str = ""
    paragraph_index: int = 0


@dataclass(frozen=True)
class ExtractedClaim:
    id: str
    qa_pair_id: str
    answer_id: str
    speaker_name: str
    text: str
    stance: str
    claim_type: str
    themes: tuple[str, ...]
    metrics: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    confidence: float = 0.72


@dataclass(frozen=True)
class ExtractedAnswer:
    id: str
    chunk_id: str
    speaker_name: str
    speaker_title: str
    text: str
    claims: tuple[ExtractedClaim, ...] = ()


@dataclass(frozen=True)
class ExtractedQAPair:
    id: str
    document_id: str
    sequence: int
    question_chunk_id: str
    question_text: str
    analyst_name: str = "Unknown Analyst"
    firm: str = ""
    answer_ids: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentOverview:
    id: str
    document_id: str
    summary: str
    themes: tuple[str, ...]
    metrics: tuple[str, ...]
    risks: tuple[str, ...]
    chunk_count: int
    qa_pair_count: int
    entity_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedDocument:
    document: dict[str, Any]
    overview: DocumentOverview
    chunks: tuple[MarkdownChunk, ...]
    qa_pairs: tuple[ExtractedQAPair, ...]
    answers: tuple[ExtractedAnswer, ...]
    entities: tuple[ExtractedEntity, ...]
    relations: tuple[ExtractedRelation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "overview": asdict(self.overview),
            "chunks": [asdict(item) for item in self.chunks],
            "qa_pairs": [asdict(item) for item in self.qa_pairs],
            "answers": [
                {**asdict(answer), "claims": [asdict(claim) for claim in answer.claims]}
                for answer in self.answers
            ],
            "entities": [asdict(item) for item in self.entities],
            "relations": [asdict(item) for item in self.relations],
        }

    def write_json(self, path: str | Path) -> None:
        rendered = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")


def load_extracted_document(path: str | Path) -> ExtractedDocument:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    answers: list[ExtractedAnswer] = []
    for answer in raw.get("answers", []):
        claims = tuple(ExtractedClaim(**claim) for claim in answer.get("claims", []))
        answer_copy = dict(answer)
        answer_copy["claims"] = claims
        answers.append(ExtractedAnswer(**answer_copy))
    return ExtractedDocument(
        document=raw["document"],
        overview=DocumentOverview(**raw["overview"]),
        chunks=tuple(MarkdownChunk(**item) for item in raw.get("chunks", [])),
        qa_pairs=tuple(ExtractedQAPair(**item) for item in raw.get("qa_pairs", [])),
        answers=tuple(answers),
        entities=tuple(ExtractedEntity(**item) for item in raw.get("entities", [])),
        relations=tuple(ExtractedRelation(**item) for item in raw.get("relations", [])),
    )


def ingest_markdown_document(
    markdown_path: str | Path,
    *,
    company_name: str,
    company_id: str | None = None,
    ticker: str = "",
    sector: str = "",
    fiscal_quarter: str,
    call_id: str | None = None,
    call_date: str = "",
    source_url: str,
    source_kind: str = "official_ir_transcript_markdown",
    allowed_themes: Iterable[str] = DEFAULT_ALLOWED_THEMES,
    use_llm: bool = True,
    llm_chunk_batch_size: int = 8,
    progress_callback: Any | None = None,
) -> ExtractedDocument:
    path = Path(markdown_path)
    markdown = path.read_text(encoding="utf-8-sig")
    document_id = _slug(f"{company_name}-{fiscal_quarter}-{path.stem}")
    company_id = company_id or _slug(company_name)
    call_id = call_id or _slug(f"{company_name}-{fiscal_quarter}")
    document = {
        "id": document_id,
        "title": _first_heading(markdown) or path.stem,
        "company_id": company_id,
        "company_name": company_name,
        "ticker": ticker,
        "sector": sector,
        "fiscal_quarter": fiscal_quarter,
        "call_id": call_id,
        "call_date": call_date,
        "source_url": source_url,
        "source_kind": source_kind,
        "markdown_path": str(path),
    }

    raw_chunks = _chunk_markdown(markdown, document_id)
    allowed = tuple(allowed_themes)
    if use_llm:
        return _ingest_with_llm(
            markdown,
            document,
            raw_chunks,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            source_url=source_url,
            allowed_themes=allowed,
            llm_chunk_batch_size=llm_chunk_batch_size,
            progress_callback=progress_callback,
        )
    return _ingest_deterministic(
        document,
        raw_chunks,
        company_name=company_name,
        fiscal_quarter=fiscal_quarter,
        allowed_themes=allowed,
        progress_callback=progress_callback,
    )

    chunks, qa_pairs, answers = _extract_qa(raw_chunks, document_id)
    entity_index: dict[tuple[str, str], ExtractedEntity] = {}
    relations: list[ExtractedRelation] = []

    company_entity = _entity(entity_index, company_name, "Company")

    enriched_answers: list[ExtractedAnswer] = []
    enriched_qa_pairs: list[ExtractedQAPair] = []
    relation_seq = 1
    claim_seq = 1
    answers_by_id = {answer.id: answer for answer in answers}
    chunks_by_id = {chunk.id: chunk for chunk in chunks}

    for qa in qa_pairs:
        qa_text = qa.question_text + "\n" + "\n".join(answers_by_id[answer_id].text for answer_id in qa.answer_ids)
        scoped_entities = _extract_entities(qa_text, allowed, entity_index, company_name=company_name)
        themes = tuple(entity.name for entity in scoped_entities if entity.entity_type == "Theme")
        scoped_relations, relation_seq = _relations_for_scope(
            company_entity,
            scoped_entities,
            qa.id,
            _short_evidence(qa_text),
            relation_seq,
        )
        relations.extend(scoped_relations)
        enriched_qa_pairs.append(
            ExtractedQAPair(
                id=qa.id,
                document_id=qa.document_id,
                sequence=qa.sequence,
                question_chunk_id=qa.question_chunk_id,
                question_text=qa.question_text,
                analyst_name=qa.analyst_name,
                firm=qa.firm,
                answer_ids=qa.answer_ids,
                themes=themes,
                entity_ids=tuple(entity.id for entity in scoped_entities),
                relation_ids=tuple(relation.id for relation in scoped_relations),
            )
        )
        for answer_id in qa.answer_ids:
            answer = answers_by_id[answer_id]
            answer_entities = _extract_entities(answer.text, allowed, entity_index, company_name=company_name)
            claims: list[ExtractedClaim] = []
            for sentence in _claim_sentences(answer.text):
                sentence_entities = _extract_entities(sentence, allowed, entity_index, company_name=company_name)
                sentence_themes = tuple(entity.name for entity in sentence_entities if entity.entity_type == "Theme")
                if not sentence_themes:
                    continue
                metrics = tuple(entity.name for entity in sentence_entities if entity.entity_type == "Metric")
                risks = tuple(entity.name for entity in sentence_entities if entity.entity_type == "Risk")
                claim = ExtractedClaim(
                    id=f"{document_id}-claim-{claim_seq:03d}",
                    qa_pair_id=qa.id,
                    answer_id=answer.id,
                    speaker_name=answer.speaker_name,
                    text=sentence,
                    stance=_infer_stance(sentence),
                    claim_type=_infer_claim_type(sentence),
                    themes=sentence_themes,
                    metrics=metrics,
                    risks=risks,
                    confidence=0.72,
                )
                claim_seq += 1
                claims.append(claim)
            enriched_answers.append(
                ExtractedAnswer(
                    id=answer.id,
                    chunk_id=answer.chunk_id,
                    speaker_name=answer.speaker_name,
                    speaker_title=answer.speaker_title,
                    text=answer.text,
                    claims=tuple(claims),
                )
            )

    answer_ids_with_qa = {answer.id for qa in qa_pairs for answer in [answers_by_id[item] for item in qa.answer_ids]}
    for answer in answers:
        if answer.id not in answer_ids_with_qa:
            enriched_answers.append(answer)

    all_text = "\n".join(chunk.text for chunk in chunks)
    overview_entities = _extract_entities(all_text, allowed, entity_index, company_name=company_name)
    overview_relations, relation_seq = _relations_for_scope(
        company_entity,
        overview_entities,
        f"{document_id}-overview",
        _short_evidence(all_text),
        relation_seq,
    )
    relations.extend(overview_relations)
    overview = DocumentOverview(
        id=f"{document_id}-overview",
        document_id=document_id,
        summary=_build_overview_summary(company_name, fiscal_quarter, overview_entities, len(chunks), len(enriched_qa_pairs)),
        themes=tuple(entity.name for entity in overview_entities if entity.entity_type == "Theme"),
        metrics=tuple(entity.name for entity in overview_entities if entity.entity_type == "Metric"),
        risks=tuple(entity.name for entity in overview_entities if entity.entity_type == "Risk"),
        chunk_count=len(chunks),
        qa_pair_count=len(enriched_qa_pairs),
        entity_ids=tuple(entity.id for entity in overview_entities),
        relation_ids=tuple(relation.id for relation in overview_relations),
    )

    extracted = ExtractedDocument(
        document=document,
        overview=overview,
        chunks=tuple(chunks),
        qa_pairs=tuple(enriched_qa_pairs),
        answers=tuple(enriched_answers),
        entities=tuple(entity_index.values()),
        relations=tuple(relations),
    )
    _progress(progress_callback, f"{document_id}: deterministic extraction complete")
    return extracted


def _ingest_with_llm(
    markdown: str,
    document: dict[str, str],
    chunks: list[MarkdownChunk],
    *,
    company_name: str,
    fiscal_quarter: str,
    source_url: str,
    allowed_themes: tuple[str, ...],
    llm_chunk_batch_size: int,
    progress_callback: Any | None,
) -> ExtractedDocument:
    from .gemini import GeminiClient

    client = GeminiClient()
    if hasattr(client, "extract_chunk_graph"):
        return _ingest_with_chunk_llm(
            client,
            markdown,
            document,
            chunks,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            source_url=source_url,
            allowed_themes=allowed_themes,
            llm_chunk_batch_size=llm_chunk_batch_size,
            progress_callback=progress_callback,
        )
    return _ingest_with_document_llm(
        client,
        markdown,
        document,
        chunks,
        company_name=company_name,
        fiscal_quarter=fiscal_quarter,
        source_url=source_url,
        allowed_themes=allowed_themes,
        progress_callback=progress_callback,
    )


def _ingest_deterministic(
    document: dict[str, str],
    chunks: list[MarkdownChunk],
    *,
    company_name: str,
    fiscal_quarter: str,
    allowed_themes: tuple[str, ...],
    progress_callback: Any | None,
) -> ExtractedDocument:
    entity_index: dict[tuple[str, str], ExtractedEntity] = {}
    relations: list[ExtractedRelation] = []
    company_entity = _entity(entity_index, company_name, "Company")
    graph_chunks = [chunk for chunk in chunks if _should_use_chunk_for_graph(chunk)]
    relation_seq = 1
    overview_entities: list[ExtractedEntity] = []
    for chunk in graph_chunks:
        scoped_entities = _extract_entities(chunk.text, allowed_themes, entity_index, company_name=company_name)
        overview_entities.extend(scoped_entities)
        scoped_relations, relation_seq = _relations_for_scope(
            company_entity,
            scoped_entities,
            chunk.id,
            _short_evidence(chunk.text),
            relation_seq,
        )
        relations.extend(scoped_relations)
    unique_overview_entities = tuple(dict.fromkeys(overview_entities or [company_entity]))
    overview = DocumentOverview(
        id=f"{document['id']}-overview",
        document_id=document["id"],
        summary=_build_overview_summary(company_name, fiscal_quarter, unique_overview_entities, len(chunks), 0),
        themes=tuple(entity.name for entity in unique_overview_entities if entity.entity_type == "Theme"),
        metrics=tuple(entity.name for entity in unique_overview_entities if entity.entity_type == "Metric"),
        risks=tuple(entity.name for entity in unique_overview_entities if entity.entity_type == "Risk"),
        chunk_count=len(chunks),
        qa_pair_count=0,
        entity_ids=tuple(entity.id for entity in unique_overview_entities),
        relation_ids=tuple(relation.id for relation in relations),
    )
    _progress(progress_callback, f"{document['id']}: deterministic extraction complete")
    return ExtractedDocument(
        document=document,
        overview=overview,
        chunks=tuple(chunks),
        qa_pairs=(),
        answers=(),
        entities=tuple(entity_index.values()),
        relations=tuple(relations),
    )


def _ingest_with_document_llm(
    client: Any,
    markdown: str,
    document: dict[str, str],
    chunks: list[MarkdownChunk],
    *,
    company_name: str,
    fiscal_quarter: str,
    source_url: str,
    allowed_themes: tuple[str, ...],
    progress_callback: Any | None,
) -> ExtractedDocument:
    result = client.extract_graph(
        markdown,
        company_name=company_name,
        fiscal_quarter=fiscal_quarter,
        allowed_themes=list(allowed_themes),
        source_url=source_url,
        extraction_context={"document_id": document["id"]},
        progress_callback=progress_callback,
    )
    entity_index: dict[tuple[str, str], ExtractedEntity] = {}
    alias_map: dict[str, ExtractedEntity] = {}
    for item in result.get("entities", []):
        _llm_entity_from_item(entity_index, alias_map, item)
    if not entity_index:
        _llm_entity(entity_index, company_name, "Company")

    relations = _llm_relations_from_items(
        result.get("relations", []),
        entity_index,
        alias_map,
        default_scope_id=f"{document['id']}-overview",
    )
    overview = _llm_overview(
        document["id"],
        result.get("overview_summary") or result.get("document_summary"),
        company_name,
        fiscal_quarter,
        tuple(entity_index.values()),
        chunks,
        relations,
    )
    _progress(progress_callback, f"{document['id']}: LLM document extraction complete")
    return ExtractedDocument(
        document=document,
        overview=overview,
        chunks=tuple(chunks),
        qa_pairs=(),
        answers=(),
        entities=tuple(entity_index.values()),
        relations=tuple(relations),
    )


def _ingest_with_chunk_llm(
    client: Any,
    markdown: str,
    document: dict[str, str],
    chunks: list[MarkdownChunk],
    *,
    company_name: str,
    fiscal_quarter: str,
    source_url: str,
    allowed_themes: tuple[str, ...],
    llm_chunk_batch_size: int,
    progress_callback: Any | None,
) -> ExtractedDocument:
    document_ontology = None
    if hasattr(client, "extract_document_ontology"):
        document_ontology = client.extract_document_ontology(
            markdown,
            company_name=company_name,
            fiscal_quarter=fiscal_quarter,
            source_url=source_url,
            seed_themes=list(allowed_themes),
            progress_callback=progress_callback,
        )
    entity_index: dict[tuple[str, str], ExtractedEntity] = {}
    alias_map: dict[str, ExtractedEntity] = {}
    if isinstance(document_ontology, dict):
        for item in document_ontology.get("entities", []):
            _llm_entity_from_item(entity_index, alias_map, item)

    extractable_chunks = [chunk for chunk in chunks if _should_extract_llm_chunk(chunk)]
    responses: list[dict[str, Any]] = []
    if llm_chunk_batch_size > 1 and hasattr(client, "extract_chunk_graph_batch"):
        for batch in _batches(extractable_chunks, llm_chunk_batch_size):
            responses.extend(
                client.extract_chunk_graph_batch(
                    [_chunk_payload(chunk) for chunk in batch],
                    company_name=company_name,
                    fiscal_quarter=fiscal_quarter,
                    allowed_themes=list(_llm_allowed_themes(allowed_themes, document_ontology)),
                    source_url=source_url,
                    document_ontology=document_ontology,
                    progress_callback=progress_callback,
                )
            )
    else:
        for chunk in extractable_chunks:
            responses.append(
                client.extract_chunk_graph(
                    chunk.text,
                    chunk_id=chunk.id,
                    chunk_metadata=_chunk_metadata(chunk),
                    company_name=company_name,
                    fiscal_quarter=fiscal_quarter,
                    allowed_themes=list(_llm_allowed_themes(allowed_themes, document_ontology)),
                    source_url=source_url,
                    document_ontology=document_ontology,
                    progress_callback=progress_callback,
                )
            )

    relations: list[ExtractedRelation] = []
    for response in responses:
        if not isinstance(response, dict):
            continue
        for item in response.get("entities", []):
            _llm_entity_from_item(entity_index, alias_map, item)
        relations.extend(
            _llm_relations_from_items(
                response.get("relations", []),
                entity_index,
                alias_map,
                default_scope_id=str(response.get("chunk_id") or document["id"]),
                start_seq=len(relations) + 1,
            )
        )
    if not entity_index:
        _llm_entity(entity_index, company_name, "Company")

    overview = _llm_overview(
        document["id"],
        document_ontology.get("document_summary") if isinstance(document_ontology, dict) else None,
        company_name,
        fiscal_quarter,
        tuple(entity_index.values()),
        chunks,
        relations,
    )
    _progress(progress_callback, f"{document['id']}: LLM chunk extraction complete")
    return ExtractedDocument(
        document=document,
        overview=overview,
        chunks=tuple(chunks),
        qa_pairs=(),
        answers=(),
        entities=tuple(entity_index.values()),
        relations=tuple(relations),
    )


def _chunk_markdown(markdown: str, document_id: str) -> list[MarkdownChunk]:
    lines = markdown.splitlines()
    heading_stack: list[tuple[int, str]] = []
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def flush(end_line: int) -> None:
        nonlocal current
        if current and current["text_lines"]:
            current["end_line"] = end_line
            blocks.append(current)
        current = None

    for offset, line in enumerate(lines, start=1):
        heading = _parse_heading(line)
        if heading:
            level, title = heading
            flush(offset - 1)
            heading_stack = [(lvl, text) for lvl, text in heading_stack if lvl < level]
            heading_stack.append((level, title))
            if _is_page_heading(title):
                current = None
                continue
            current = {
                "chunk_type": _heading_chunk_type(title, heading_stack),
                "heading": " > ".join(text for _, text in heading_stack),
                "speaker_name": "",
                "speaker_title": "",
                "text_lines": [(offset, title)],
                "start_line": offset,
            }
            continue

        speaker = _parse_speaker_line(line)
        if speaker:
            name, title, remainder = speaker
            flush(offset - 1)
            current = {
                "chunk_type": _speaker_chunk_type(name, heading_stack),
                "heading": " > ".join(text for _, text in heading_stack),
                "speaker_name": name,
                "speaker_title": title,
                "text_lines": [(offset, remainder)] if remainder else [],
                "start_line": offset,
            }
            continue

        if current is None:
            current = {
                "chunk_type": _heading_chunk_type("", heading_stack),
                "heading": " > ".join(text for _, text in heading_stack),
                "speaker_name": "",
                "speaker_title": "",
                "text_lines": [],
                "start_line": offset,
            }
        current["text_lines"].append((offset, line))

    flush(len(lines))

    chunks: list[MarkdownChunk] = []
    for block in blocks:
        chunk_type = block["chunk_type"]
        if chunk_type == "section" and _is_qa_heading(block["heading"]):
            chunk_type = "qa_section"
        for paragraph_text, start_line, end_line in _paragraphs(block["text_lines"]):
            for split_text in _split_long_text(paragraph_text):
                if not split_text:
                    continue
                chunk_id = f"{document_id}-chunk-{len(chunks)+1:03d}"
                chunks.append(
                    MarkdownChunk(
                        id=chunk_id,
                        document_id=document_id,
                        index=len(chunks) + 1,
                        chunk_type=chunk_type,
                        heading=block["heading"],
                        text=split_text,
                        start_line=start_line,
                        end_line=end_line,
                        speaker_name="",
                        speaker_title="",
                        text_hash=_short_hash(split_text),
                    )
                )
    return chunks


def _extract_qa(chunks: list[MarkdownChunk], document_id: str) -> tuple[list[MarkdownChunk], list[ExtractedQAPair], list[ExtractedAnswer]]:
    qa_pairs: list[ExtractedQAPair] = []
    answers: list[ExtractedAnswer] = []
    current_question: MarkdownChunk | None = None
    current_answers: list[ExtractedAnswer] = []
    analyst_name = "Unknown Analyst"
    firm = ""

    def flush() -> None:
        nonlocal current_question, current_answers, analyst_name, firm
        if current_question is not None:
            sequence = len(qa_pairs) + 1
            qa_pairs.append(
                ExtractedQAPair(
                    id=f"{document_id}-qa-{sequence:03d}",
                    document_id=document_id,
                    sequence=sequence,
                    question_chunk_id=current_question.id,
                    question_text=current_question.text,
                    analyst_name=analyst_name,
                    firm=firm,
                    answer_ids=tuple(answer.id for answer in current_answers),
                )
            )
            analyst_name = "Unknown Analyst"
            firm = ""
        current_question = None
        current_answers = []

    qa_mode = False
    for chunk in chunks:
        if _is_qa_heading(chunk.heading) or chunk.chunk_type == "qa_section":
            qa_mode = True
        if qa_mode and chunk.speaker_name.lower() == "analyst":
            analyst_name, firm = _extract_analyst(chunk)
            continue
        if chunk.chunk_type == "analyst_question" or (qa_mode and _looks_like_question_chunk(chunk)):
            flush()
            current_question = chunk
            if chunk.speaker_name.lower() != "question":
                analyst_name, firm = _extract_analyst(chunk)
            continue
        if qa_mode and chunk.chunk_type == "management_answer" and current_question is not None:
            answer_id = f"{document_id}-answer-{len(answers)+1:03d}"
            answer = ExtractedAnswer(
                id=answer_id,
                chunk_id=chunk.id,
                speaker_name=chunk.speaker_name or "Management",
                speaker_title=chunk.speaker_title,
                text=chunk.text,
            )
            answers.append(answer)
            current_answers.append(answer)
            continue
    flush()
    return chunks, qa_pairs, answers


def _extract_entities(
    text: str,
    allowed_themes: Iterable[str],
    entity_index: dict[tuple[str, str], ExtractedEntity],
    *,
    company_name: str,
) -> tuple[ExtractedEntity, ...]:
    entities: list[ExtractedEntity] = [_entity(entity_index, company_name, "Company")]
    lower = text.lower()
    for theme in allowed_themes:
        aliases = (theme.lower(), *THEME_ALIASES.get(theme, ()))
        if any(alias in lower for alias in aliases):
            entities.append(_entity(entity_index, theme, "Theme"))
    for metric in METRIC_TERMS:
        if metric.lower() in lower:
            entities.append(_entity(entity_index, metric, "Metric"))
    for risk in RISK_TERMS:
        if risk.lower() in lower:
            entities.append(_entity(entity_index, risk, "Risk"))
    for acronym in sorted(set(re.findall(r"\b[A-Z][A-Z0-9]{1,6}\b", text))):
        if acronym not in {"CEO", "CFO", "Q", "A"}:
            entities.append(_entity(entity_index, acronym, "BusinessTerm"))
    return tuple(dict.fromkeys(entities))


def _relations_for_scope(
    company: ExtractedEntity,
    entities: tuple[ExtractedEntity, ...],
    scope_id: str,
    evidence: str,
    start_seq: int,
) -> tuple[tuple[ExtractedRelation, ...], int]:
    relations: list[ExtractedRelation] = []
    seq = start_seq
    themes = [entity for entity in entities if entity.entity_type == "Theme"]
    metrics = [entity for entity in entities if entity.entity_type == "Metric"]
    risks = [entity for entity in entities if entity.entity_type == "Risk"]
    for theme in themes:
        relations.append(_relation(seq, company, "DISCUSSES", theme, scope_id, evidence)); seq += 1
    for theme in themes:
        for metric in metrics:
            relations.append(_relation(seq, theme, "AFFECTS", metric, scope_id, evidence)); seq += 1
        for risk in risks:
            relations.append(_relation(seq, theme, "EXPOSED_TO", risk, scope_id, evidence)); seq += 1
    for risk in risks:
        for metric in metrics:
            relations.append(_relation(seq, risk, "PRESSURES", metric, scope_id, evidence)); seq += 1
    return tuple(relations), seq


def _llm_relations_from_items(
    items: Any,
    entity_index: dict[tuple[str, str], ExtractedEntity],
    alias_map: dict[str, ExtractedEntity],
    *,
    default_scope_id: str,
    start_seq: int = 1,
) -> list[ExtractedRelation]:
    relations: list[ExtractedRelation] = []
    seq = start_seq
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_entity") or item.get("source") or "").strip()
        target_name = str(item.get("target_entity") or item.get("target") or "").strip()
        if not source_name or not target_name:
            continue
        source = _resolve_llm_entity(entity_index, alias_map, source_name)
        target = _resolve_llm_entity(entity_index, alias_map, target_name)
        if source is None or target is None:
            continue
        relation_type = str(item.get("relation_type") or item.get("relation") or "RELATED_TO").strip() or "RELATED_TO"
        scope_id = str(item.get("scope_id") or item.get("chunk_id") or default_scope_id)
        evidence = str(item.get("evidence_text") or item.get("evidence") or "")
        confidence = _float_or_default(item.get("confidence"), 0.8)
        relations.append(
            ExtractedRelation(
                id=f"rel-{seq:04d}-{_short_hash(source.id + relation_type + target.id + scope_id)}",
                source_entity_id=source.id,
                relation_type=relation_type,
                target_entity_id=target.id,
                scope_id=scope_id,
                evidence_text=evidence,
                confidence=confidence,
            )
        )
        seq += 1
    return relations


def _llm_entity_from_item(
    entity_index: dict[tuple[str, str], ExtractedEntity],
    alias_map: dict[str, ExtractedEntity],
    item: Any,
) -> ExtractedEntity | None:
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    entity = _llm_entity(entity_index, name, str(item.get("entity_type") or "BusinessTerm"))
    alias_map[_norm(name)] = entity
    aliases = item.get("aliases", [])
    if isinstance(aliases, list):
        for alias in aliases:
            alias_text = str(alias).strip()
            if alias_text:
                alias_map[_norm(alias_text)] = entity
    return entity


def _llm_entity(
    index: dict[tuple[str, str], ExtractedEntity],
    name: str,
    entity_type: str,
) -> ExtractedEntity:
    key = (entity_type, _norm(name))
    if key not in index:
        index[key] = ExtractedEntity(id=f"entity-{entity_type.lower()}-{_slug(name)}", name=name, entity_type=entity_type, source="llm")
    return index[key]


def _resolve_llm_entity(
    entity_index: dict[tuple[str, str], ExtractedEntity],
    alias_map: dict[str, ExtractedEntity],
    name: str,
) -> ExtractedEntity | None:
    normalized = _norm(name)
    if normalized in alias_map:
        return alias_map[normalized]
    matches = [entity for (_, key), entity in entity_index.items() if key == normalized]
    return matches[0] if matches else None


def _entity(index: dict[tuple[str, str], ExtractedEntity], name: str, entity_type: str) -> ExtractedEntity:
    key = (entity_type, _norm(name))
    if key not in index:
        index[key] = ExtractedEntity(id=f"entity-{entity_type.lower()}-{_slug(name)}", name=name, entity_type=entity_type)
    return index[key]


def _relation(seq: int, source: ExtractedEntity, relation_type: str, target: ExtractedEntity, scope_id: str, evidence: str) -> ExtractedRelation:
    return ExtractedRelation(
        id=f"rel-{seq:04d}-{_short_hash(source.id + relation_type + target.id + scope_id)}",
        source_entity_id=source.id,
        relation_type=relation_type,
        target_entity_id=target.id,
        scope_id=scope_id,
        evidence_text=evidence,
    )


def _llm_overview(
    document_id: str,
    summary: Any,
    company_name: str,
    fiscal_quarter: str,
    entities: tuple[ExtractedEntity, ...],
    chunks: list[MarkdownChunk],
    relations: list[ExtractedRelation],
) -> DocumentOverview:
    overview_id = f"{document_id}-overview"
    return DocumentOverview(
        id=overview_id,
        document_id=document_id,
        summary=str(summary or _build_overview_summary(company_name, fiscal_quarter, entities, len(chunks), 0)),
        themes=tuple(entity.name for entity in entities if entity.entity_type == "Theme"),
        metrics=tuple(entity.name for entity in entities if entity.entity_type == "Metric"),
        risks=tuple(entity.name for entity in entities if entity.entity_type == "Risk"),
        chunk_count=len(chunks),
        qa_pair_count=0,
        entity_ids=tuple(entity.id for entity in entities),
        relation_ids=tuple(relation.id for relation in relations if relation.scope_id == overview_id),
    )


def _should_extract_llm_chunk(chunk: MarkdownChunk) -> bool:
    if chunk.chunk_type in {"analyst_question", "qa_section"}:
        return False
    if chunk.speaker_name.lower() in {"analyst", "question"}:
        return False
    return bool(chunk.text.strip())


def _should_use_chunk_for_graph(chunk: MarkdownChunk) -> bool:
    if chunk.chunk_type in {"analyst_question", "qa_section", "section"}:
        return False
    if _is_page_heading(chunk.text) or _is_page_number(chunk.text):
        return False
    return bool(chunk.text.strip())


def _chunk_metadata(chunk: MarkdownChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "chunk_type": chunk.chunk_type,
        "heading": chunk.heading,
        "speaker_name": chunk.speaker_name,
        "speaker_title": chunk.speaker_title,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
    }


def _chunk_payload(chunk: MarkdownChunk) -> dict[str, Any]:
    return {"chunk_id": chunk.id, "text": chunk.text, "chunk_metadata": _chunk_metadata(chunk)}


def _batches(items: list[MarkdownChunk], size: int) -> Iterable[list[MarkdownChunk]]:
    size = max(1, size)
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _llm_allowed_themes(seed: tuple[str, ...], document_ontology: Any) -> tuple[str, ...]:
    themes = list(seed)
    if isinstance(document_ontology, dict):
        for theme in document_ontology.get("themes", []):
            theme_text = str(theme).strip()
            if theme_text and theme_text not in themes:
                themes.append(theme_text)
    return tuple(themes)


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _progress(callback: Any | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _claim_sentences(text: str) -> tuple[str, ...]:
    sentences = re.split(r"(?<=[.!?])\s+", _clean_text(text))
    claims = [sentence.strip() for sentence in sentences if len(sentence.split()) >= 6 and any(word in sentence.lower() for word in CLAIM_KEYWORDS)]
    return tuple(claims[:8])


def _infer_stance(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("risk", "pressure", "headwind", "cost", "expense", "dilution", "decline")):
        if any(token in lower for token in ("growth", "demand", "offset", "investment", "opportunity")):
            return "mixed"
        return "negative"
    if any(token in lower for token in ("growth", "demand", "opportunity", "strong", "robust", "increase")):
        return "positive"
    return "neutral"


def _infer_claim_type(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("cost", "expense", "capex", "capital expenditure", "margin", "depreciation")):
        return "cost_burden"
    if any(token in lower for token in ("risk", "constraint", "pressure", "headwind")):
        return "risk"
    if any(token in lower for token in ("demand", "growth", "usage", "adoption")):
        return "demand_signal"
    return "operational_update"


def _parse_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), _strip_markdown(match.group(2))


def _parse_speaker_line(line: str) -> tuple[str, str, str] | None:
    stripped = line.strip()
    patterns = (
        r"^\*\*(?P<label>[^*:\n]{2,120})\*\*\s*:\s*(?P<text>.*)$",
        r"^\*\*(?P<label>[^*:\n]{2,120}):\*\*\s*(?P<text>.*)$",
        r"^(?P<label>[A-Z][^:\n]{1,120})\s*:\s*(?P<text>.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, stripped)
        if match:
            label = _strip_markdown(match.group("label"))
            text = match.group("text").strip()
            name, title = _split_person_label(label)
            return name, title, text
    return None


def _paragraphs(lines: list[tuple[int, str]]) -> list[tuple[str, int, int]]:
    paragraphs: list[tuple[str, int, int]] = []
    current: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = _clean_text("\n".join(line for _, line in current))
        if text and not _is_page_number(text) and not _is_page_heading(text):
            paragraphs.append((text, current[0][0], current[-1][0]))
        current = []

    for line_no, line in lines:
        if _skip_source_line(line):
            continue
        if not line.strip():
            flush()
            continue
        current.append((line_no, line))
    flush()
    return paragraphs


def _split_long_text(text: str, *, max_chars: int = 900) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def _skip_source_line(line: str) -> bool:
    return line.strip().startswith("> Full official source text extracted from")


def _is_page_heading(text: str) -> bool:
    return bool(re.fullmatch(r"Page\s+\d+", text.strip(), flags=re.IGNORECASE))


def _is_page_number(text: str) -> bool:
    return bool(re.fullmatch(r"\d{1,4}", text.strip()))


def _split_person_label(label: str) -> tuple[str, str]:
    if "," in label:
        name, title = label.split(",", 1)
        return name.strip(), title.strip()
    if " - " in label:
        name, title = label.split(" - ", 1)
        return name.strip(), title.strip()
    return label.strip(), ""


def _speaker_chunk_type(name: str, heading_stack: list[tuple[int, str]]) -> str:
    lower_name = name.lower()
    if lower_name in {"question", "analyst"} or "question" in lower_name or "analyst" in lower_name:
        return "analyst_question"
    if _is_qa_heading(" > ".join(text for _, text in heading_stack)):
        return "management_answer"
    return "speaker_statement"


def _heading_chunk_type(title: str, heading_stack: list[tuple[int, str]]) -> str:
    text = " ".join([title, *[item for _, item in heading_stack]]).lower()
    if "overview" in text or "summary" in text:
        return "document_overview"
    if _is_qa_heading(text):
        return "qa_section"
    if "prepared" in text or "remarks" in text:
        return "prepared_remarks"
    return "section"


def _is_qa_heading(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in ("q&a", "qa", "question-and-answer", "questions and answers", "질의", "질문"))


def _looks_like_question_chunk(chunk: MarkdownChunk) -> bool:
    lower = (chunk.speaker_name + " " + chunk.heading + " " + chunk.text).lower()
    return "question" in lower or "analyst" in lower or lower.strip().endswith("?")


def _is_question_chunk(chunk: MarkdownChunk) -> bool:
    return _looks_like_question_chunk(chunk)


def _extract_analyst(chunk: MarkdownChunk) -> tuple[str, str]:
    if chunk.speaker_name.lower() == "analyst" and chunk.text:
        return _split_person_label(chunk.text)
    if chunk.speaker_name and chunk.speaker_name.lower() not in {"question", "analyst"}:
        return chunk.speaker_name, chunk.speaker_title
    match = re.search(r"analyst\s*:\s*([^\n,]+)(?:,\s*([^\n]+))?", chunk.text, re.IGNORECASE)
    if match:
        return match.group(1).strip(), (match.group(2) or "").strip()
    return "Unknown Analyst", ""


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        heading = _parse_heading(line)
        if heading:
            return heading[1]
    return ""


def _build_overview_summary(company_name: str, fiscal_quarter: str, entities: tuple[ExtractedEntity, ...], chunk_count: int, qa_count: int) -> str:
    themes = [entity.name for entity in entities if entity.entity_type == "Theme"]
    theme_text = ", ".join(themes[:6]) or "no configured themes detected"
    return f"{company_name} {fiscal_quarter} call parsed into {chunk_count} markdown chunks and {qa_count} Q&A pairs; detected themes: {theme_text}."


def _short_evidence(text: str, limit: int = 260) -> str:
    clean = _clean_text(text)
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_markdown(text)).strip()


def _strip_markdown(text: str) -> str:
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    return text.strip()


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or _short_hash(value)


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
