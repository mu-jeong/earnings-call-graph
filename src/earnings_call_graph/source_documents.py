from __future__ import annotations

import html
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from xml.etree import ElementTree

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class SourceDocumentText:
    markdown_path: Path
    raw_path: Path
    source_url: str
    content_type: str


@dataclass(frozen=True)
class SourceCandidate:
    url: str
    label: str
    priority: int


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n\n")
        elif tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return _normalize_extracted_text(html.unescape("".join(self.parts)))


class _LinkHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[SourceCandidate] = []
        self._active_href = ""
        self._active_label: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs}
        for value in attrs_dict.values():
            self._add_embedded_urls(value, attrs_dict.get("aria-label", ""))
        if tag.lower() == "a" and attrs_dict.get("href"):
            self._active_href = urljoin(self.base_url, html.unescape(attrs_dict["href"]))
            self._active_label = [attrs_dict.get("aria-label", ""), attrs_dict.get("title", "")]

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._active_label.append(data)
        self._add_embedded_urls(data, "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._active_href:
            label = _clean_inline_text(" ".join(self._active_label))
            self.links.append(SourceCandidate(self._active_href, label, _candidate_priority(self._active_href, label)))
            self._active_href = ""
            self._active_label = []

    def _add_embedded_urls(self, value: str, label: str) -> None:
        decoded = html.unescape(value or "")
        decoded = decoded.replace("\\/", "/")
        for match in re.finditer(r"https?://[^\s'\"<>}]+", decoded):
            url = match.group(0).rstrip(".,;)\\]")
            local_label = label or _nearby_text(decoded, match.start())
            self.links.append(SourceCandidate(url, _clean_inline_text(local_label), _candidate_priority(url, local_label)))


def materialize_source_markdown(
    *,
    source_url: str,
    title: str,
    slug: str,
    cache_dir: str | Path = "data/source_cache",
    refresh: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> SourceDocumentText:
    cache_root = Path(cache_dir)
    raw_dir = cache_root / "raw"
    markdown_dir = cache_root / "markdown"
    raw_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / f"{slug}{_source_suffix(source_url)}"
    markdown_path = markdown_dir / f"{slug}.md"
    cached_raw_path = _cached_raw_path(raw_dir, slug, fallback=raw_path)
    if markdown_path.exists() and cached_raw_path.exists() and not refresh:
        _progress(progress_callback, f"{slug}: using cached source Markdown {markdown_path}")
        return SourceDocumentText(markdown_path, cached_raw_path, source_url, _content_type_from_suffix(cached_raw_path))

    _progress(progress_callback, f"{slug}: downloading official source {source_url}")
    raw_bytes, content_type = _download_source(source_url)
    selected_url = source_url
    selected_bytes = raw_bytes
    selected_content_type = content_type
    if _is_html(source_url, content_type, raw_bytes):
        candidate = _select_preferred_source_candidate(
            source_url,
            raw_bytes,
            progress_callback=progress_callback,
        )
        if candidate is not None:
            selected_url, selected_bytes, selected_content_type = candidate
            _progress(
                progress_callback,
                f"{slug}: preferred transcript source selected {selected_url} ({selected_content_type or 'unknown content type'})",
            )
    _progress(progress_callback, f"{slug}: downloaded {len(selected_bytes):,} bytes ({selected_content_type or 'unknown content type'})")
    raw_path = raw_dir / f"{slug}{_source_suffix(selected_url, selected_content_type)}"
    raw_path.write_bytes(selected_bytes)
    _progress(progress_callback, f"{slug}: cached raw source at {raw_path}")

    if _is_pdf(selected_url, selected_content_type, selected_bytes):
        _progress(progress_callback, f"{slug}: extracting text from PDF")
        text = _extract_pdf_text(selected_bytes, progress_callback=progress_callback)
    elif _is_docx(selected_url, selected_content_type, selected_bytes):
        _progress(progress_callback, f"{slug}: extracting text from DOCX transcript")
        text = _extract_docx_text(selected_bytes)
    else:
        _progress(progress_callback, f"{slug}: extracting text from HTML")
        text = _extract_html_text(selected_bytes)
    text = _normalize_extracted_text(text)
    _progress(progress_callback, f"{slug}: extracted {len(text):,} characters")

    rendered = _render_source_markdown(title=title, source_url=selected_url, text=text)
    markdown_path.write_text(rendered, encoding="utf-8")
    _progress(progress_callback, f"{slug}: wrote source Markdown {markdown_path}")
    return SourceDocumentText(markdown_path, raw_path, selected_url, selected_content_type)


def _cached_raw_path(raw_dir: Path, slug: str, *, fallback: Path) -> Path:
    for suffix in (".pdf", ".docx", ".html", ".htm"):
        candidate = raw_dir / f"{slug}{suffix}"
        if candidate.exists():
            return candidate
    return fallback


def _download_source(source_url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": "EarningsCallGraph/0.1 source ingestion",
            "Accept": "text/html,application/pdf,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        return response.read(), content_type



def _select_preferred_source_candidate(
    page_url: str,
    raw_html: bytes,
    *,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str, bytes, str] | None:
    parser = _LinkHTMLParser(page_url)
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    candidates = sorted(
        (candidate for candidate in parser.links if candidate.priority > 0),
        key=lambda item: (-item.priority, item.label, item.url),
    )
    seen: set[str] = set()
    for candidate in candidates[:12]:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        try:
            resolved_url, raw_bytes, content_type = _download_resolved_source(candidate.url)
        except Exception as exc:  # pragma: no cover - network variability fallback
            _progress(progress_callback, f"Skipping candidate {candidate.url}: {exc}")
            continue
        if _is_pdf(resolved_url, content_type, raw_bytes) or _is_docx(resolved_url, content_type, raw_bytes):
            return resolved_url, raw_bytes, content_type
    return None


def _download_resolved_source(url: str) -> tuple[str, bytes, str]:
    raw_bytes, content_type = _download_source(url)
    final_url = _final_url(url)
    office_src = _office_viewer_src(final_url) or _office_viewer_src_from_html(raw_bytes)
    if office_src:
        raw_bytes, content_type = _download_source(office_src)
        return office_src, raw_bytes, content_type
    return final_url, raw_bytes, content_type


def _final_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "EarningsCallGraph/0.1 source ingestion"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.url


def _office_viewer_src(url: str) -> str:
    parsed = urlparse(url)
    if "view.officeapps.live.com" not in parsed.netloc.lower():
        return ""
    src = parse_qs(parsed.query).get("src", [""])[0]
    return unquote(src)


def _office_viewer_src_from_html(raw_html: bytes) -> str:
    text = raw_html.decode("utf-8", errors="replace")
    match = re.search(r"[?&]src=(https?[^'\"&<>]+)", text)
    return unquote(html.unescape(match.group(1))) if match else ""


def _extract_pdf_text(raw_bytes: bytes, *, progress_callback: ProgressCallback | None = None) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency should be installed.
        raise RuntimeError('Install PDF support with: pip install -e ".[dev]"') from exc

    reader = PdfReader(BytesIO(raw_bytes))
    pages: list[str] = []
    page_count = len(reader.pages)
    _progress(progress_callback, f"PDF has {page_count} page(s)")
    for index, page in enumerate(reader.pages, start=1):
        _progress(progress_callback, f"Extracting PDF page {index}/{page_count}")
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(f"\n\n## Page {index}\n\n{page_text}")
    return _normalize_extracted_text("\n".join(pages))


def _extract_docx_text(raw_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(raw_bytes)) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        text = _clean_inline_text("".join(parts))
        if text:
            paragraphs.append(text)
    return _normalize_extracted_text("\n\n".join(paragraphs))


def _extract_html_text(raw_bytes: bytes) -> str:
    raw = raw_bytes.decode("utf-8", errors="replace")
    parser = _TextHTMLParser()
    parser.feed(raw)
    return parser.text()


def _render_source_markdown(*, title: str, source_url: str, text: str) -> str:
    return f"""# {title}

> Full official source text extracted from {source_url}

{text}
"""


def _source_suffix(source_url: str, content_type: str = "") -> str:
    path_suffix = Path(urlparse(source_url).path).suffix.lower()
    if path_suffix in {".pdf", ".docx", ".html", ".htm"}:
        return path_suffix
    if "pdf" in content_type:
        return ".pdf"
    if _docx_content_type(content_type):
        return ".docx"
    return ".html"


def _content_type_from_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/html"


def _is_pdf(source_url: str, content_type: str, raw_bytes: bytes) -> bool:
    return (
        "pdf" in content_type
        or Path(urlparse(source_url).path).suffix.lower() == ".pdf"
        or raw_bytes.startswith(b"%PDF")
    )


def _is_docx(source_url: str, content_type: str, raw_bytes: bytes) -> bool:
    return (
        _docx_content_type(content_type)
        or Path(urlparse(source_url).path).suffix.lower() == ".docx"
        or raw_bytes.startswith(b"PK") and b"word/document.xml" in raw_bytes[:20000]
    )


def _is_html(source_url: str, content_type: str, raw_bytes: bytes) -> bool:
    suffix = Path(urlparse(source_url).path).suffix.lower()
    return "html" in content_type or suffix in {"", ".html", ".htm"} or raw_bytes.lstrip().lower().startswith(b"<!doctype html") or raw_bytes.lstrip().lower().startswith(b"<html")


def _docx_content_type(content_type: str) -> bool:
    return "wordprocessingml.document" in content_type or "msword" in content_type


def _candidate_priority(url: str, label: str) -> int:
    lower = f"{url} {label}".lower()
    if (
        "slide" in lower
        or "powerpoint" in lower
        or "annual-report" in lower
        or "download-center" in lower
        or "presentation" in lower
    ):
        return 0
    transcript_bonus = 50 if "transcript" in lower or "q&a" in lower or "qanda" in lower or "qanda" in url.lower() else 0
    call_material_bonus = 30 if "prepared remark" in lower or "conference call" in lower or "earnings call" in lower else 0
    is_call_material = transcript_bonus > 0 or call_material_bonus > 0
    if not is_call_material:
        return 0
    if (
        "press release" in lower
        or "earnings release" in lower
        or "financial statement" in lower
        or "financial result" in lower
        or "financial and business result" in lower
    ):
        return 0
    if ".pdf" in lower:
        return 100 + transcript_bonus + call_material_bonus
    if ".docx" in lower or "officeapps.live.com" in lower or "aka.ms/transcript" in lower or "transcript" in lower:
        return 70 + transcript_bonus + call_material_bonus
    return transcript_bonus + call_material_bonus


def _nearby_text(text: str, index: int, radius: int = 80) -> str:
    return text[max(0, index - radius) : min(len(text), index + radius)]


def _normalize_extracted_text(value: str) -> str:
    text = value.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    paragraphs = [_clean_inline_text(part) for part in re.split(r"\n{2,}", text) if _clean_inline_text(part)]
    merged: list[str] = []
    for paragraph in paragraphs:
        if merged and _should_merge_paragraphs(merged[-1], paragraph):
            merged[-1] = f"{merged[-1]} {paragraph}"
        else:
            merged.append(paragraph)
    return "\n\n".join(merged).strip()


def _should_merge_paragraphs(previous: str, current: str) -> bool:
    if _looks_like_speaker_only(previous):
        return True
    if _looks_like_heading(previous) or _looks_like_heading(current) or _looks_like_speaker(current):
        return False
    if len(previous) < 90 and not re.search(r"[.!?:]$", previous):
        return True
    if len(current) < 55 and current[:1].islower():
        return True
    return False


def _looks_like_heading(value: str) -> bool:
    return len(value) <= 90 and (value.startswith("Page ") or value.isupper())


def _looks_like_speaker(value: str) -> bool:
    return re.match(r"^[A-Z][A-Za-z .'-]{1,80},? (CEO|CFO|Chief|EVP|President|Chairman)\b", value) is not None or re.match(r"^[A-Z][A-Za-z .'-]{1,80}:\s", value) is not None


def _looks_like_speaker_only(value: str) -> bool:
    stripped = value.strip()
    if not stripped.endswith(":") or len(stripped) > 90:
        return False
    name = stripped[:-1].strip()
    return bool(re.match(r"^[A-Z][A-Z .'-]{2,80}$", name) or re.match(r"^[A-Z][A-Za-z .'-]{2,80}$", name))


def _clean_inline_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _clean_text(value: str) -> str:
    return _normalize_extracted_text(value)


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
