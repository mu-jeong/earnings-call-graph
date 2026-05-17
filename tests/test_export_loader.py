from pathlib import Path

import pytest

from earnings_call_graph.export_loader import exported_graph_paths, load_exported_graphs
from earnings_call_graph.markdown_ingest import ingest_markdown_document


SAMPLE_MARKDOWN = """# TestCo Q1 2026 Earnings Call

## Prepared Remarks

AI demand increases infrastructure capex.
"""


class FakeGraph:
    def __init__(self):
        self.verified = False
        self.closed = False
        self.loads = []

    def verify_connectivity(self):
        self.verified = True

    def load_extracted_document(self, extracted, *, reset=False):
        self.loads.append((extracted.document["id"], reset))

    def close(self):
        self.closed = True


def test_exported_graph_paths_requires_matches(tmp_path):
    with pytest.raises(FileNotFoundError):
        exported_graph_paths(tmp_path)


def test_exported_graph_paths_accepts_one_json_file(tmp_path):
    graph_json = tmp_path / "one-graph.json"
    _write_graph_json(graph_json, tmp_path / "one.md", "OneCo")

    assert exported_graph_paths(graph_json) == [graph_json]


def test_load_exported_graphs_loads_all_files_and_resets_once(tmp_path, monkeypatch):
    input_dir = tmp_path / "exports"
    input_dir.mkdir()
    _write_graph_json(input_dir / "b-graph.json", tmp_path / "b.md", "Beta")
    _write_graph_json(input_dir / "a-graph.json", tmp_path / "a.md", "Alpha")
    fake_graph = FakeGraph()
    messages = []

    monkeypatch.setattr("earnings_call_graph.export_loader.graph_from_env", lambda: fake_graph)

    results = load_exported_graphs(input_dir, reset_first=True, progress_callback=messages.append)

    assert [result.input_path.name for result in results] == ["a-graph.json", "b-graph.json"]
    assert fake_graph.verified is True
    assert fake_graph.closed is True
    assert [reset for _, reset in fake_graph.loads] == [True, False]
    assert len(results) == 2
    assert results[0].reset_applied is True
    assert results[1].reset_applied is False
    assert any("Found 2 exported graph JSON" in message for message in messages)


def _write_graph_json(output_path: Path, markdown_path: Path, company_name: str) -> None:
    markdown_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    extracted = ingest_markdown_document(
        markdown_path,
        company_name=company_name,
        fiscal_quarter="FY2026 Q1",
        source_url=f"https://example.com/{company_name.lower()}",
        use_llm=False,
    )
    extracted.write_json(output_path)
