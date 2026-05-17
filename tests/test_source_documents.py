from io import BytesIO
import html
import zipfile

from earnings_call_graph.source_documents import materialize_source_markdown


def _docx_bytes(paragraphs):
    body = "".join(
        f"<w:p><w:r><w:t>{html.escape(text)}</w:t></w:r></w:p>" for text in paragraphs
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>
""".encode("utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_materialize_source_markdown_prefers_transcript_document_link_from_html(tmp_path, monkeypatch):
    html = b"""
    <html><body>
      <a href="https://aka.ms/slidesfy26q3">PowerPoint</a>
      <a href="https://aka.ms/transcriptfy26q3">Transcript</a>
    </body></html>
    """
    docx = _docx_bytes([
        "Satya Nadella, Chairman and CEO: AI demand is increasing Azure consumption.",
        "Amy Hood, EVP & CFO: Capital expenditures support cloud and AI infrastructure.",
    ])

    def fake_download(url):
        if url == "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q3":
            return html, "text/html"
        if url == "https://aka.ms/transcriptfy26q3":
            return b"<html>office viewer</html>", "text/html"
        if url == "https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/TranscriptQandAFY26Q3":
            return docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        raise AssertionError(f"unexpected download {url}")

    monkeypatch.setattr("earnings_call_graph.source_documents._download_source", fake_download)
    monkeypatch.setattr(
        "earnings_call_graph.source_documents._final_url",
        lambda url: "https://view.officeapps.live.com/op/view.aspx?src=https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/TranscriptQandAFY26Q3"
        if url == "https://aka.ms/transcriptfy26q3"
        else url,
    )

    result = materialize_source_markdown(
        source_url="https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q3",
        title="Microsoft FY2026 Q3 Official Source",
        slug="microsoft-fy2026-q3",
        cache_dir=tmp_path,
        refresh=True,
    )

    assert result.raw_path.suffix == ".docx"
    assert result.source_url.endswith("TranscriptQandAFY26Q3")
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "Satya Nadella" in markdown
    assert "Capital expenditures support cloud and AI infrastructure." in markdown
    assert "PowerPoint" not in markdown


def test_docx_transcript_normalization_merges_speaker_label_with_next_paragraph(tmp_path, monkeypatch):
    docx = _docx_bytes([
        "SATYA NADELLA:",
        "Thank you. AI demand is increasing Azure consumption.",
    ])

    monkeypatch.setattr(
        "earnings_call_graph.source_documents._download_source",
        lambda url: (docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    )

    result = materialize_source_markdown(
        source_url="https://example.com/transcript.docx",
        title="Transcript",
        slug="transcript",
        cache_dir=tmp_path,
        refresh=True,
    )

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "SATYA NADELLA: Thank you. AI demand" in markdown


def test_materialize_source_markdown_normalizes_fragmented_html_paragraphs(tmp_path, monkeypatch):
    html = b"""
    <html><body>
      <p>AI demand requires</p>
      <p>more data center capacity.</p>
      <p>Amy Hood, EVP and CFO: Operating margin remains strong.</p>
    </body></html>
    """

    monkeypatch.setattr("earnings_call_graph.source_documents._download_source", lambda url: (html, "text/html"))

    result = materialize_source_markdown(
        source_url="https://example.com/source.html",
        title="Example Source",
        slug="example",
        cache_dir=tmp_path,
        refresh=True,
    )

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "AI demand requires more data center capacity." in markdown
    assert "Amy Hood" in markdown

def test_materialize_source_markdown_rejects_financial_results_pdf_when_transcript_missing(tmp_path, monkeypatch):
    html = b"""
    <html><body>
      <a href="https://investor.example.com/q2-financial-results.pdf">Financial Results PDF</a>
      <p>Q2 earnings conference call webcast replay only.</p>
    </body></html>
    """

    def fake_download(url):
        if url == "https://investor.example.com/q2-event":
            return html, "text/html"
        raise AssertionError(f"financial-results PDF should not be downloaded: {url}")

    monkeypatch.setattr("earnings_call_graph.source_documents._download_source", fake_download)

    result = materialize_source_markdown(
        source_url="https://investor.example.com/q2-event",
        title="Example Q2 Event",
        slug="example-q2",
        cache_dir=tmp_path,
        refresh=True,
    )

    assert result.raw_path.suffix == ".html"
    assert result.source_url == "https://investor.example.com/q2-event"
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "Q2 earnings conference call webcast replay only." in markdown


def test_materialize_source_markdown_prefers_call_transcript_over_financial_pdf(tmp_path, monkeypatch):
    html = b"""
    <html><body>
      <a href="https://investor.example.com/q2-financial-results.pdf">Financial Results PDF</a>
      <a href="https://investor.example.com/q2-earnings-call-transcript.pdf">Earnings Call Transcript PDF</a>
    </body></html>
    """
    pdf = b"%PDF transcript bytes"

    def fake_download(url):
        if url == "https://investor.example.com/q2-event":
            return html, "text/html"
        if url == "https://investor.example.com/q2-earnings-call-transcript.pdf":
            return pdf, "application/pdf"
        raise AssertionError(f"unexpected download {url}")

    monkeypatch.setattr("earnings_call_graph.source_documents._download_source", fake_download)
    monkeypatch.setattr("earnings_call_graph.source_documents._final_url", lambda url: url)
    monkeypatch.setattr("earnings_call_graph.source_documents._extract_pdf_text", lambda raw, **kwargs: "Operator: Welcome to the call.")

    result = materialize_source_markdown(
        source_url="https://investor.example.com/q2-event",
        title="Example Q2 Event",
        slug="example-q2",
        cache_dir=tmp_path,
        refresh=True,
    )

    assert result.raw_path.suffix == ".pdf"
    assert result.source_url.endswith("q2-earnings-call-transcript.pdf")
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "Operator: Welcome to the call." in markdown

