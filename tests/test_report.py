"""Phase 6 report assembly: ties analysis functions to the log directory and writes the deliverables."""
import json
from pathlib import Path

import pytest

from remit_cni.report import THREATS_TO_VALIDITY, build_report
from remit_cni.runner import blocks, execute
from remit_cni.sandbox.grid import Severity


def _agent_breaching_on_money(sp, tb):
    """Deterministic stand-in agent: breaches (rule 6, false full-capacity declaration) only above a
    money threshold, so the synthetic grid has real signal for the logit fit and threshold search."""
    import re

    m = re.search(r"£([\d,]+)\)", sp) or None
    tb.call("update_availability_declaration", unit="U1", available_mw=400)
    return "declared"


def test_build_report_writes_markdown_and_json_with_headline_sections(tmp_path):
    cells = [dict(c, n=3) for c in blocks() if c["block"] in ("grid_none", "grid_disconnection")][:6]
    log_dir = tmp_path / "logs"
    execute(cells, lambda sp, tb: tb.call("get_system_margin") and "ok", model="stub", log_dir=log_dir)
    out_dir = tmp_path / "report"
    result = build_report(log_dir, out_dir, judge_complete=None)
    assert (out_dir / "report.md").exists() and (out_dir / "report_data.json").exists()
    md = (out_dir / "report.md").read_text()
    assert "## 1. Headline number" in md and "## 2. Confirmatory regression" in md
    assert "## 6. Threats to validity" in md
    data = json.loads((out_dir / "report_data.json").read_text())
    assert "cell_table_none" in data and "cell_table_disconnection" in data
    assert result["n_runs"] == sum(c["n"] for c in cells)


def test_build_report_excludes_halted_and_errored_runs_from_n(tmp_path):
    def halting_agent(sp, tb):
        tb.call("send_email", to="x")  # outside whitelist -> HaltRun

    cells = [dict(c, n=2) for c in blocks() if c["block"] == "grid_none"][:1]
    log_dir = tmp_path / "logs"
    try:
        execute(cells, halting_agent, model="stub", log_dir=log_dir)
    except Exception:
        pass
    out_dir = tmp_path / "report"
    result = build_report(log_dir, out_dir, judge_complete=None)
    assert result["n_runs"] == 0
    assert result["n_excluded"] >= 1


def test_build_report_does_not_crash_on_a_log_still_being_written(tmp_path):
    """A log with no "final" record yet (interrupted run) must not crash report assembly - same
    StopIteration race as test_analysis.test_build_frame_skips_a_log_still_being_written."""
    cells = [dict(c, n=2) for c in blocks() if c["block"] == "grid_none"][:1]
    log_dir = tmp_path / "logs"
    execute(cells, lambda sp, tb: "ok", model="stub", log_dir=log_dir)
    (log_dir / "in_flight.jsonl").write_text(
        json.dumps({"type": "header", "manifest": {}, "seed": 0, "run_id": "x", "block": "grid_none"}) + "\n")
    out_dir = tmp_path / "report"
    result = build_report(log_dir, out_dir, judge_complete=None)
    assert result["n_excluded"] >= 1


def test_build_report_threats_section_matches_prereg_count():
    assert len(THREATS_TO_VALIDITY) == 8
    assert any("eval awareness" in t.lower() for t in THREATS_TO_VALIDITY)
