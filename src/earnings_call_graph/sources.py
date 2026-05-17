from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


DEFAULT_MANIFEST_PATH = Path("data/sources/major_companies.json")
EXAMPLE_MANIFEST_PATH = Path("data/sources/major_companies.example.json")

REQUIRED_MANIFEST_FIELDS = ("filename", "company", "quarter")
OPTIONAL_STRING_FIELDS = (
    "company_id",
    "ticker",
    "sector",
    "fiscal_year",
    "call_id",
    "call_date",
    "source_type",
    "rights_notes",
)


@dataclass(frozen=True)
class SourceAdapter:
    """Describes source-site defaults without hard-coding documents in code."""

    name: str
    domains: tuple[str, ...]
    default_source_type: str
    notes: str = ""

    def matches(self, source_url: str) -> bool:
        host = urlparse(source_url).netloc.lower()
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)


SOURCE_ADAPTERS: tuple[SourceAdapter, ...] = (
    SourceAdapter("adobe-ir-pdf", ("adobe.com",), "transcript_pdf", "Adobe IR PDF transcript/source document."),
    SourceAdapter("q4cdn-pdf", ("q4cdn.com",), "transcript_pdf", "Q4 CDN-hosted investor-relations PDF."),
    SourceAdapter("amazon-ir-html", ("ir.aboutamazon.com",), "earnings_release_html", "Amazon IR HTML release page."),
    SourceAdapter("apple-newsroom-pdf", ("apple.com",), "earnings_release_pdf", "Apple newsroom financial PDF."),
    SourceAdapter("microsoft-ir-html", ("microsoft.com",), "earnings_event_html", "Microsoft investor event page."),
    SourceAdapter("tsmc-ir-pdf", ("investor.tsmc.com",), "transcript_pdf", "TSMC IR-hosted PDF transcript."),
)


@dataclass(frozen=True)
class SourceManifestEntry:
    filename: str
    company: str
    quarter: str
    source_url: str
    company_id: str = ""
    ticker: str = ""
    sector: str = ""
    fiscal_year: str = ""
    call_id: str = ""
    call_date: str = ""
    source_type: str = ""
    rights_notes: str = ""
    adapter: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, item: dict[str, Any], *, default_filename: str = "") -> "SourceManifestEntry":
        filename = str(
            item.get("filename")
            or item.get("file")
            or item.get("markdown_path")
            or default_filename
            or ""
        )
        filename = Path(filename).name
        normalized: dict[str, str] = {
            key: str(value).strip()
            for key, value in item.items()
            if value is not None and key not in {"filename", "file", "markdown_path"}
        }
        if filename:
            normalized["filename"] = filename

        missing = [key for key in REQUIRED_MANIFEST_FIELDS if not normalized.get(key)]
        if missing:
            raise ValueError(f"Manifest entry {filename or item!r} is missing required field(s): {', '.join(missing)}")

        source_url = normalized.get("source_url", "")
        adapter = select_source_adapter(source_url)
        source_type = normalized.get("source_type") or infer_source_type(source_url, adapter)
        company_id = normalized.get("company_id") or _slugify(normalized["company"])

        known = set(REQUIRED_MANIFEST_FIELDS) | set(OPTIONAL_STRING_FIELDS) | {"adapter"}
        extra = {key: value for key, value in normalized.items() if key not in known}

        return cls(
            filename=normalized["filename"],
            company=normalized["company"],
            quarter=normalized["quarter"],
            source_url=source_url,
            company_id=company_id,
            ticker=normalized.get("ticker", ""),
            sector=normalized.get("sector", ""),
            fiscal_year=normalized.get("fiscal_year", ""),
            call_id=normalized.get("call_id", ""),
            call_date=normalized.get("call_date", ""),
            source_type=source_type,
            rights_notes=normalized.get("rights_notes", ""),
            adapter=normalized.get("adapter") or adapter.name,
            extra=extra,
        )

    def to_metadata(self) -> dict[str, str]:
        metadata = {
            "company": self.company,
            "company_id": self.company_id,
            "ticker": self.ticker,
            "sector": self.sector,
            "quarter": self.quarter,
            "fiscal_year": self.fiscal_year,
            "call_id": self.call_id,
            "call_date": self.call_date,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "rights_notes": self.rights_notes,
            "source_adapter": self.adapter,
        }
        metadata.update(self.extra)
        return {key: value for key, value in metadata.items() if value != ""}


def select_source_adapter(source_url: str) -> SourceAdapter:
    if not source_url.strip():
        return SourceAdapter("unconfigured-source", (), "")
    for adapter in SOURCE_ADAPTERS:
        if adapter.matches(source_url):
            return adapter
    return SourceAdapter("generic-pdf" if _url_looks_pdf(source_url) else "generic-html", (), infer_source_type(source_url))


def infer_source_type(source_url: str, adapter: SourceAdapter | None = None) -> str:
    if adapter is not None and adapter.default_source_type:
        return adapter.default_source_type
    return "transcript_pdf" if _url_looks_pdf(source_url) else "earnings_source_html"


def load_source_manifest(
    path: str | Path | None = None,
    *,
    include_defaults: bool = True,
) -> dict[str, SourceManifestEntry]:
    entries: dict[str, SourceManifestEntry] = {}
    if include_defaults:
        entries.update(_read_manifest(DEFAULT_MANIFEST_PATH, required=False))
        if not entries and path is None:
            entries.update(_read_manifest(EXAMPLE_MANIFEST_PATH, required=False))
    if path is not None:
        entries.update(_read_manifest(Path(path), required=True))
    if not entries:
        raise FileNotFoundError(
            f"No source manifest entries found. Create {DEFAULT_MANIFEST_PATH} or pass --manifest."
        )
    return entries


def load_manifest_metadata(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    return {filename: entry.to_metadata() for filename, entry in load_source_manifest(path).items()}


def _read_manifest(path: Path, *, required: bool) -> dict[str, SourceManifestEntry]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Manifest not found: {path}")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        entry.filename: entry
        for entry in (
            SourceManifestEntry.from_mapping(item, default_filename=default_filename)
            for default_filename, item in _manifest_items(raw)
        )
    }


def _manifest_items(raw: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(raw, dict) and isinstance(raw.get("documents"), list):
        for item in raw["documents"]:
            if not isinstance(item, dict):
                raise ValueError(f"Manifest documents entries must be objects: {item!r}")
            yield "", item
        return
    if isinstance(raw, dict):
        for filename, values in raw.items():
            if not isinstance(values, dict):
                raise ValueError(f"Manifest entry for {filename!r} must be an object.")
            yield str(filename), values
        return
    raise ValueError("Manifest must be an object keyed by filename or {'documents': [...]} list.")


def _url_looks_pdf(source_url: str) -> bool:
    return Path(urlparse(source_url).path).suffix.lower() == ".pdf"


def _slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in slug.split("-") if part)
