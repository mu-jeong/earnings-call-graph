from pathlib import Path

from earnings_call_graph.cli import main
from earnings_call_graph.export_loader import ExportLoadResult
from earnings_call_graph.pipeline import PipelineResult


def test_sync_processes_and_loads_by_default(monkeypatch, capsys):
    calls = []

    def fake_process_markdown_folder(*args, **kwargs):
        calls.append((args, kwargs))
        return [
            PipelineResult(
                input_path=Path("data/source_inputs/example.md"),
                output_path=Path("exports/earnings_graph/example-graph.json"),
                document_id="example-doc",
                chunk_count=2,
                qa_pair_count=0,
                entity_count=3,
                relation_count=4,
                claim_count=0,
                loaded=True,
            )
        ]

    monkeypatch.setattr("earnings_call_graph.cli.process_markdown_folder", fake_process_markdown_folder)

    exit_code = main(["sync", "--reset", "--limit", "1"])

    assert exit_code == 0
    assert calls[0][1]["load_to_neo4j"] is True
    assert calls[0][1]["reset_neo4j"] is True
    assert calls[0][1]["max_documents"] == 1
    assert calls[0][1]["use_source_documents"] is True
    assert "Synced 1 document(s)." in capsys.readouterr().out


def test_sync_can_skip_neo4j_loading(monkeypatch):
    calls = []

    def fake_process_markdown_folder(*args, **kwargs):
        calls.append((args, kwargs))
        return [
            PipelineResult(
                input_path=Path("data/source_inputs/example.md"),
                output_path=Path("exports/earnings_graph/example-graph.json"),
                document_id="example-doc",
                chunk_count=1,
                qa_pair_count=0,
                entity_count=1,
                relation_count=1,
                claim_count=0,
            )
        ]

    monkeypatch.setattr("earnings_call_graph.cli.process_markdown_folder", fake_process_markdown_folder)

    exit_code = main(["sync", "--json-only"])

    assert exit_code == 0
    assert calls[0][1]["load_to_neo4j"] is False


def test_sync_load_only_uses_export_loader(monkeypatch, capsys):
    calls = []

    def fake_load_exported_graphs(*args, **kwargs):
        calls.append((args, kwargs))
        return [
            ExportLoadResult(
                input_path=Path("exports/earnings_graph/example-graph.json"),
                document_id="example-doc",
                chunk_count=2,
                qa_pair_count=0,
                entity_count=3,
                relation_count=4,
                reset_applied=True,
            )
        ]

    monkeypatch.setattr("earnings_call_graph.cli.load_exported_graphs", fake_load_exported_graphs)

    exit_code = main(["sync", "--load-only", "--reset", "--output-dir", "exports/earnings_graph"])

    assert exit_code == 0
    assert calls == [(("exports/earnings_graph",), {"pattern": "*-graph.json", "reset_first": True, "progress_callback": main.__globals__["_print_progress"]})]
    assert "Loaded 1 exported graph JSON file(s)." in capsys.readouterr().out


def test_load_command_loads_default_or_given_path(monkeypatch, capsys):
    calls = []

    def fake_load_exported_graphs(*args, **kwargs):
        calls.append((args, kwargs))
        return [
            ExportLoadResult(
                input_path=Path("exports/earnings_graph/example-graph.json"),
                document_id="example-doc",
                chunk_count=2,
                qa_pair_count=0,
                entity_count=3,
                relation_count=4,
                reset_applied=True,
            )
        ]

    monkeypatch.setattr("earnings_call_graph.cli.load_exported_graphs", fake_load_exported_graphs)

    exit_code = main(["load", "exports/earnings_graph/example-graph.json", "--reset"])

    assert exit_code == 0
    assert calls == [
        (
            ("exports/earnings_graph/example-graph.json",),
            {"pattern": "*-graph.json", "reset_first": True, "progress_callback": main.__globals__["_print_progress"]},
        )
    ]
    assert "Loaded 1 exported graph JSON file(s)." in capsys.readouterr().out
