from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ONTOLOGY_PATH = Path(__file__).resolve().parents[2] / "data" / "ontology" / "earnings_ontology.json"


@dataclass(frozen=True)
class OntologyConcept:
    id: str
    name: str
    concept_type: str
    aliases: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class OntologyRelation:
    source_id: str
    relation_type: str
    target_id: str
    description: str = ""


@dataclass(frozen=True)
class OntologyMatch:
    concept: OntologyConcept
    confidence: float
    matched_alias: str
    method: str = "alias"


@dataclass(frozen=True)
class EntityResolutionRule:
    concept_id: str
    patterns: tuple[str, ...]
    matched_alias: str
    entity_types: tuple[str, ...] = ()
    confidence: float = 0.96


GENERIC_SINGLE_TOKEN_ALIASES = {
    "ai",
    "business",
    "capacity",
    "cloud",
    "compute",
    "cost",
    "customers",
    "data",
    "demand",
    "growth",
    "margin",
    "memory",
    "nvidia",
    "performance",
    "power",
    "product",
    "products",
    "revenue",
    "risk",
    "sales",
    "search",
    "servers",
    "storage",
    "systems",
}

RESOLUTION_EXCLUDED_ENTITY_TYPES = {"Company", "Geography", "TimePeriod"}

ENTITY_RESOLUTION_RULES: tuple[EntityResolutionRule, ...] = (
    EntityResolutionRule(
        "concept-ai-demand",
        (
            r"\b(ai|genai|generative ai|agentic ai)\s+(demand|workloads?|usage|adoption|orders?|solutions?)\b",
            r"\b(demand|workloads?|usage|adoption|orders?)\s+(for|from)?\s*(ai|genai|generative ai)\b",
            r"\b(frontier|foundation)\s+models?\b",
        ),
        "AI workload demand",
    ),
    EntityResolutionRule(
        "concept-infrastructure-capex",
        (
            r"\b(capex|capital expenditures?|capital intensity)\b",
            r"\b(infrastructure|data center|technical infrastructure|ai)\s+(spend|investment|capex)\b",
            r"\broi\s+on\s+capex\b",
        ),
        "infrastructure CapEx",
    ),
    EntityResolutionRule(
        "concept-revenue-growth",
        (
            r"\b(revenue|sales)\s+(growth|grew|increase|acceleration|run rate)\b",
            r"\b(cloud|azure|data center|gaming|advertising|ads?)\s+revenue\b",
            r"\b(cloud|azure|data center)\s+growth\b",
            r"\b(arr|annual recurring revenue|run rate)\b",
        ),
        "revenue growth",
    ),
    EntityResolutionRule(
        "concept-cloud-platform-segment",
        (
            r"\b(azure|google cloud|gcp|aws|oci|oracle cloud|microsoft cloud)\b",
            r"\bcloud\s+(platform|services?|customers?|migration|infrastructure|subscriptions?|growth)\b",
        ),
        "cloud platform segment",
    ),
    EntityResolutionRule(
        "concept-operating-margin-pressure",
        (
            r"\b(operating|gross)\s+margin\b",
            r"\bmargin\s+(pressure|headwind|dilution|compression|expansion)\b",
            r"\b(operating expenses?|opex|depreciation|cost pressure)\b",
        ),
        "operating margin pressure",
    ),
    EntityResolutionRule(
        "concept-component-cost-pressure",
        (
            r"\b(component|input|supply chain|manufacturing)\s+costs?\b",
            r"\bcost\s+(inflation|variability|pressure|headwind)\b",
        ),
        "component cost pressure",
    ),
    EntityResolutionRule(
        "concept-supply-constraint",
        (
            r"\b(supply|capacity|component|inventory)\s+constraints?\b",
            r"\bstructural supply\b",
            r"\bcompute constrained\b",
        ),
        "supply constraint",
    ),
    EntityResolutionRule(
        "concept-data-center-capacity",
        (
            r"\bdata centers?\b",
            r"\b(compute|inference|gpu|tpu)\s+capacity\b",
            r"\badvanced packaging\b",
        ),
        "data center / compute capacity",
    ),
    EntityResolutionRule(
        "concept-power-cooling",
        (
            r"\b(power|energy)\s+(supply|constraints?|costs?)\b",
            r"\b(liquid )?cooling\b",
        ),
        "power / cooling constraint",
    ),
    EntityResolutionRule(
        "concept-memory-bandwidth",
        (
            r"\b(hbm|high bandwidth memory|dram|nand|ddr5|memory bandwidth)\b",
        ),
        "memory bandwidth / HBM",
    ),
    EntityResolutionRule(
        "concept-storage-capacity",
        (
            r"\b(storage|ssd|hdd|mass-capacity|enterprise storage)\b",
        ),
        "storage capacity",
    ),
    EntityResolutionRule(
        "concept-networking-fabric",
        (
            r"\b(networking fabric|ethernet|nvlink|interconnect|switching|routing)\b",
            r"\bdata center networking\b",
        ),
        "networking fabric",
    ),
    EntityResolutionRule(
        "concept-ai-product-monetization",
        (
            r"\b(ai|cloud|product|ads?|advertising|subscription)\s+moneti[sz]ation\b",
            r"\b(advertising|ads?|subscription|subscriptions|ai services?)\s+(revenue|growth|business)\b",
            r"\b(credit consumption|paid subscriptions?)\b",
        ),
        "AI product monetization",
    ),
    EntityResolutionRule(
        "concept-enterprise-ai-adoption",
        (
            r"\benterprise\s+ai\b",
            r"\b(copilot|gemini enterprise|business process automation|customer adoption|internal ai adoption)\b",
            r"\bautomation\b",
        ),
        "enterprise AI adoption",
    ),
    EntityResolutionRule(
        "concept-ai-efficiency",
        (
            r"\b(engineering|ai|cost|hardware)\s+efficienc(y|ies)\b",
            r"\b(latency|throughput|price performance|cost efficiency|productivity)\b",
        ),
        "AI efficiency",
    ),
    EntityResolutionRule(
        "concept-fx-impact",
        (
            r"\b(fx|foreign exchange|currency|constant currency)\b",
        ),
        "foreign exchange impact",
    ),
    EntityResolutionRule(
        "concept-regulatory-compliance-risk",
        (
            r"\b(regulatory|regulation|compliance|privacy|data governance|digital trust)\b",
            r"\b(tariffs?|trade policy|geopolitical)\b",
        ),
        "regulatory / compliance risk",
    ),
    EntityResolutionRule(
        "concept-consumer-demand",
        (
            r"\bconsumer\s+demand\b",
            r"\bconsumer\s+(market|devices?|engagement)\b",
        ),
        "consumer demand",
    ),
    EntityResolutionRule(
        "concept-pricing-power",
        (
            r"\b(pricing power|pricing strategy|price increases?|asp|average price)\b",
        ),
        "pricing power",
    ),
    EntityResolutionRule(
        "concept-capital-allocation",
        (
            r"\b(capital allocation|shareholder returns?|share repurchases?|buybacks?|dividends?)\b",
        ),
        "capital allocation",
    ),
)


def load_ontology(path: str | Path | None = None) -> tuple[OntologyConcept, ...]:
    ontology_path = Path(path) if path is not None else DEFAULT_ONTOLOGY_PATH
    return _load_ontology_cached(str(ontology_path.resolve()))[0]


def load_ontology_relations(path: str | Path | None = None) -> tuple[OntologyRelation, ...]:
    ontology_path = Path(path) if path is not None else DEFAULT_ONTOLOGY_PATH
    return _load_ontology_cached(str(ontology_path.resolve()))[1]


@lru_cache(maxsize=8)
def _load_ontology_cached(path: str) -> tuple[tuple[OntologyConcept, ...], tuple[OntologyRelation, ...]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    concepts = raw.get("concepts", []) if isinstance(raw, dict) else []
    relations = raw.get("relations", []) if isinstance(raw, dict) else []
    return (
        tuple(_concept_from_mapping(item) for item in concepts if isinstance(item, dict)),
        tuple(_relation_from_mapping(item) for item in relations if isinstance(item, dict)),
    )


def map_entity_to_concepts(
    entity_name: str,
    entity_type: str = "",
    *,
    aliases: Iterable[str] = (),
    properties: dict[str, Any] | None = None,
    ontology: Iterable[OntologyConcept] | None = None,
    limit: int = 2,
) -> tuple[OntologyMatch, ...]:
    """Map a company-specific entity to stable cross-company ontology concepts.

    The matcher is intentionally deterministic and conservative: exact/case-insensitive
    alias matches outrank token containment. Company nodes are not mapped because they
    are already cross-document anchors, not semantic concepts.
    """

    if not entity_name or entity_type in RESOLUTION_EXCLUDED_ENTITY_TYPES:
        return ()
    candidates = _entity_candidate_texts(entity_name, aliases=aliases, properties=properties or {})
    concepts = tuple(ontology or load_ontology())
    matches: list[OntologyMatch] = list(_rule_matches(candidates, entity_type, concepts))
    for concept in concepts:
        match = _match_concept(candidates, concept)
        if match is not None:
            matches.append(match)
    deduped = _dedupe_matches(matches)
    deduped.sort(key=lambda item: (-item.confidence, item.concept.name))
    return tuple(deduped[: max(1, limit)])


def _concept_from_mapping(item: dict[str, Any]) -> OntologyConcept:
    name = str(item.get("name") or "").strip()
    concept_id = str(item.get("id") or _stable_concept_id(name)).strip()
    concept_type = str(item.get("concept_type") or item.get("type") or "Concept").strip()
    aliases = tuple(
        _unique(
            str(alias).strip()
            for alias in [name, *item.get("aliases", [])]
            if str(alias).strip()
        )
    )
    return OntologyConcept(
        id=concept_id,
        name=name,
        concept_type=concept_type,
        aliases=aliases,
        description=str(item.get("description") or "").strip(),
    )


def _relation_from_mapping(item: dict[str, Any]) -> OntologyRelation:
    source_id = str(item.get("source") or item.get("source_id") or "").strip()
    target_id = str(item.get("target") or item.get("target_id") or "").strip()
    relation_type = str(item.get("relation_type") or item.get("type") or "RELATED_TO").strip().upper()
    relation_type = re.sub(r"[^A-Z0-9_]+", "_", relation_type).strip("_") or "RELATED_TO"
    return OntologyRelation(
        source_id=source_id,
        relation_type=relation_type,
        target_id=target_id,
        description=str(item.get("description") or "").strip(),
    )


def _entity_candidate_texts(entity_name: str, *, aliases: Iterable[str], properties: dict[str, Any]) -> tuple[str, ...]:
    values = [entity_name, *aliases]
    for key in ("canonical_name", "context", "value"):
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
    return tuple(_unique(value for value in values if isinstance(value, str) and value.strip()))


def _match_concept(candidates: tuple[str, ...], concept: OntologyConcept) -> OntologyMatch | None:
    best: OntologyMatch | None = None
    for candidate in candidates:
        candidate_norm = _norm(candidate)
        if not candidate_norm:
            continue
        for alias in concept.aliases:
            alias_norm = _norm(alias)
            if not alias_norm:
                continue
            confidence = _match_confidence(candidate_norm, alias_norm)
            if confidence <= 0:
                continue
            current = OntologyMatch(concept=concept, confidence=confidence, matched_alias=alias)
            if best is None or current.confidence > best.confidence:
                best = current
    return best


def _match_confidence(candidate_norm: str, alias_norm: str) -> float:
    if candidate_norm == alias_norm:
        return 1.0
    if _contains_phrase(candidate_norm, alias_norm) or _contains_phrase(alias_norm, candidate_norm):
        shorter_tokens = _tokens(candidate_norm if len(candidate_norm) <= len(alias_norm) else alias_norm)
        if len(shorter_tokens) == 1 and shorter_tokens[0] in GENERIC_SINGLE_TOKEN_ALIASES:
            return 0.0
        shorter = min(len(candidate_norm), len(alias_norm))
        if shorter >= 5:
            return 0.88
    candidate_tokens = set(_tokens(candidate_norm))
    alias_tokens = set(_tokens(alias_norm))
    if len(candidate_tokens) >= 2 and len(alias_tokens) >= 2:
        overlap = candidate_tokens & alias_tokens
        coverage = len(overlap) / min(len(candidate_tokens), len(alias_tokens))
        if coverage >= 0.75:
            return 0.74
    return 0.0


def _rule_matches(
    candidates: tuple[str, ...],
    entity_type: str,
    ontology: Iterable[OntologyConcept],
) -> tuple[OntologyMatch, ...]:
    concepts_by_id = {concept.id: concept for concept in ontology}
    candidate_text = " | ".join(_norm(candidate) for candidate in candidates if _norm(candidate))
    if not candidate_text:
        return ()
    matches: list[OntologyMatch] = []
    for rule in ENTITY_RESOLUTION_RULES:
        if rule.entity_types and entity_type not in rule.entity_types:
            continue
        concept = concepts_by_id.get(rule.concept_id)
        if concept is None:
            continue
        for pattern in rule.patterns:
            if re.search(pattern, candidate_text, flags=re.IGNORECASE):
                matches.append(
                    OntologyMatch(
                        concept=concept,
                        confidence=rule.confidence,
                        matched_alias=rule.matched_alias,
                        method="entity_resolution_rule",
                    )
                )
                break
    return tuple(matches)


def _dedupe_matches(matches: Iterable[OntologyMatch]) -> list[OntologyMatch]:
    best_by_concept: dict[str, OntologyMatch] = {}
    for match in matches:
        current = best_by_concept.get(match.concept.id)
        if current is None or (match.confidence, match.method) > (current.confidence, current.method):
            best_by_concept[match.concept.id] = match
    return list(best_by_concept.values())


def _contains_phrase(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in re.findall(r"[a-z0-9]+", value) if len(token) > 1)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _stable_concept_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"concept-{slug or 'unknown'}"


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique
