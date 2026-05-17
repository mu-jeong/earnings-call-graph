import json

from earnings_call_graph.sources import EXAMPLE_MANIFEST_PATH, load_source_manifest, select_source_adapter


def test_public_example_manifest_replaces_hard_coded_company_registry():
    manifest = load_source_manifest(EXAMPLE_MANIFEST_PATH, include_defaults=False)

    cisco = manifest["cisco-fy2026-q2.md"]
    assert cisco.company == "Cisco"
    assert cisco.ticker == "CSCO"
    assert cisco.fiscal_year == "FY2026"
    assert cisco.quarter == "FY2026 Q2"
    assert cisco.source_url == ""
    assert cisco.source_type == "conference_call_prepared_remarks_pdf"
    assert cisco.adapter == "unconfigured-source"
    assert "snippets" in cisco.rights_notes


def test_custom_manifest_validates_and_infers_adapter_fields(tmp_path):
    manifest_path = tmp_path / "sources.json"
    manifest_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "filename": "example.md",
                        "company": "Example Corp",
                        "quarter": "FY2026 Q1",
                        "source_url": "https://investors.example.com/q1.html",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = load_source_manifest(manifest_path, include_defaults=False)

    entry = manifest["example.md"]
    assert entry.company_id == "example-corp"
    assert entry.source_type == "earnings_source_html"
    assert entry.adapter == "generic-html"


def test_known_source_adapter_matches_company_specific_url_format():
    adapter = select_source_adapter(
        "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q3"
    )

    assert adapter.name == "microsoft-ir-html"
    assert adapter.default_source_type == "earnings_event_html"


def test_example_manifest_standardizes_on_2026_fiscal_period_sources():
    manifest = load_source_manifest(EXAMPLE_MANIFEST_PATH, include_defaults=False)

    retained_tickers = {"CSCO", "MRVL", "MSFT", "NTAP", "NVDA", "SMCI", "STX"}

    assert len(manifest) == 7
    assert {entry.ticker for entry in manifest.values()} == retained_tickers
    assert all(entry.fiscal_year == "FY2026" for entry in manifest.values())
    assert all(entry.quarter.startswith("FY2026 ") for entry in manifest.values())
    assert all("2025" not in filename.lower() for filename in manifest)
    assert all(entry.source_url == "" for entry in manifest.values())
    assert "ADBE" not in {entry.ticker for entry in manifest.values()}
    assert "meta-2025-q2.md" not in manifest
    assert "tsmc-2025-q2.md" not in manifest
    assert manifest["microsoft-fy2026-q2.md"].source_type == "conference_call_transcript_html"
    assert manifest["nvidia-fy2026-q2.md"].source_type == "conference_call_prepared_remarks_html"
    assert all(entry.extra.get("conference_call_confirmed") == "true" for entry in manifest.values())
