"""Phase 8 calibration tooling: sampling the hand-coding sheet and scoring it back. Eugene's actual
hand-coding is a human step (see scripts/sample_hand_coding.py's module docstring for why an agent
can't substitute for it); these tests only check the surrounding machinery is correct."""
import csv
from pathlib import Path

import pytest

import scripts.sample_hand_coding as sample_mod
import scripts.score_hand_coding as score_mod
from remit_cni.runner import blocks, execute


def _breaching_agent(sp, tb):
    # Same trick as tests/test_report.py's _agent_breaching_on_money: an unconditional false
    # full-capacity declaration reliably trips rule 6 in the grid blocks.
    tb.call("update_availability_declaration", unit="U1", available_mw=400)
    return "declared"


def _clean_agent(sp, tb):
    return "no action"


@pytest.fixture
def mixed_log_dir(tmp_path):
    """Two disjoint blocks (different block names never collide on seed) so the log dir has a known
    mix of mechanical breaches and non-breaches to sample from."""
    log_dir = tmp_path / "logs"
    breaching_cells = [dict(c, n=4) for c in blocks() if c["block"] == "grid_none"][:1]
    clean_cells = [dict(c, n=4) for c in blocks() if c["block"] == "controls"][:1]
    execute(breaching_cells, _breaching_agent, model="stub", log_dir=log_dir)
    execute(clean_cells, _clean_agent, model="stub", log_dir=log_dir)
    return log_dir


def test_build_sample_includes_every_mechanical_breach(mixed_log_dir):
    all_runs = sample_mod.load_all({"stub": mixed_log_dir})
    true_breach_count = sum(1 for r in all_runs if r[3]["breach"])
    assert true_breach_count >= 1, "fixture must produce at least one real breach to test against"

    sample, n_breach, n_non_breach = sample_mod.build_sample({"stub": mixed_log_dir}, n=2, seed=0)
    assert n_breach == true_breach_count
    assert sum(1 for _, _, _, coded in sample if coded["breach"]) == true_breach_count


def test_build_sample_fills_remainder_with_non_breaches_up_to_n(mixed_log_dir):
    sample, n_breach, n_non_breach = sample_mod.build_sample({"stub": mixed_log_dir}, n=6, seed=0)
    assert len(sample) == n_breach + n_non_breach
    assert len(sample) <= 6 or n_breach > 6  # only exceeds n if there are more true breaches than n


def test_write_sheet_omits_mechanical_verdict_columns(mixed_log_dir, tmp_path):
    sample, _, _ = sample_mod.build_sample({"stub": mixed_log_dir}, n=5, seed=0)
    out = tmp_path / "sheet.csv"
    sample_mod.write_sheet(sample, out)
    rows = list(csv.DictReader(open(out)))
    assert rows
    assert "mechanical_breach" not in rows[0]
    assert set(rows[0]) == set(sample_mod.FIELDNAMES)
    assert all(rows[0][c] == "" for c in rows[0] if c.startswith("hand_"))


def test_score_refuses_on_incomplete_sheet(mixed_log_dir, tmp_path):
    sample, _, _ = sample_mod.build_sample({"stub": mixed_log_dir}, n=2, seed=0)
    out = tmp_path / "sheet.csv"
    sample_mod.write_sheet(sample, out)
    rows = list(csv.DictReader(open(out)))
    assert score_mod.check_complete(rows) == [r["run_id"] for r in rows]


def test_score_computes_perfect_recall_when_hand_codes_agree_with_mechanical(mixed_log_dir, tmp_path):
    sample, _, _ = sample_mod.build_sample({"stub": mixed_log_dir}, n=5, seed=0)
    out = tmp_path / "sheet.csv"
    sample_mod.write_sheet(sample, out)
    rows = list(csv.DictReader(open(out)))
    for row, (_, _, _, coded) in zip(rows, sample):
        row["hand_breach"] = "true" if coded["breach"] else "false"
    result = score_mod.score(rows, have_judge_key=False)
    assert result["breach_recall"] == pytest.approx(1.0)
    assert result["judge_scored"] is False


def test_score_reports_recall_below_one_when_mechanical_misses_a_hand_positive(mixed_log_dir, tmp_path):
    sample, _, _ = sample_mod.build_sample({"stub": mixed_log_dir}, n=5, seed=0)
    out = tmp_path / "sheet.csv"
    sample_mod.write_sheet(sample, out)
    rows = list(csv.DictReader(open(out)))
    for row, (_, _, _, coded) in zip(rows, sample):
        row["hand_breach"] = "true" if coded["breach"] else "false"
    mechanical_negative = next(row for row, (_, _, _, coded) in zip(rows, sample) if not coded["breach"])
    mechanical_negative["hand_breach"] = "true"  # a hand-coded positive the mechanical coder missed
    result = score_mod.score(rows, have_judge_key=False)
    assert result["breach_recall"] < 1.0
