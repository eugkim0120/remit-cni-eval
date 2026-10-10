from collections import Counter

from remit_cni.runner import blocks, execute, unrunnable_cells
from remit_cni.sandbox.harness import HaltRun
from remit_cni.sandbox.logger import load_log


def test_total_runs_per_model_matches_budget_table():
    assert sum(c["n"] for c in blocks()) == 1165


def test_run_counts_by_block_match_budget_table():
    per_block = Counter()
    for c in blocks():
        per_block[c["block"]] += c["n"]
    assert per_block == {"pilot": 40, "grid_none": 320, "grid_disconnection": 320, "severity_curve": 30,
                         "autonomy": 60, "controls": 45, "framing_arms": 60, "cni_mitigation": 60,
                         "archetype_breadth": 160, "archetype_11": 30, "relative_framing": 20,
                         "eval_wording": 20}


def test_grid_blocks_run_first_after_pilot():
    order = list(dict.fromkeys(c["block"] for c in blocks()))
    assert order[:3] == ["pilot", "grid_none", "grid_disconnection"]


def test_grid_cells_are_32_distinct_per_severity():
    for name in ("grid_none", "grid_disconnection"):
        cells = [c for c in blocks() if c["block"] == name]
        keys = {(c["factors"]["certainty"], c["factors"]["money_gbp"], c["factors"]["detection"],
                 c["factors"]["punishment"]) for c in cells}
        assert len(cells) == len(keys) == 32


def test_undefined_archetypes_and_controls_are_reported_not_hidden():
    missing = unrunnable_cells()
    assert {c["archetype"] for c in missing if c["block"] == "archetype_breadth"} == {2, 3, 4, 5, 6, 7, 9, 12}
    assert any(c.get("control") == "cost_of_compliance" for c in missing)


def test_execute_logs_one_file_per_run_with_manifest(tmp_path):
    cells = [c for c in blocks() if c["block"] == "pilot"]
    result = execute(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path)
    assert result["runs"] == 40 and result["skipped"] == 0
    logs = sorted(tmp_path.glob("*.jsonl"))
    assert len(logs) == 40
    header = load_log(logs[0])["header"]
    assert header["manifest"]["archetype"] == 8 and header["block"] == "pilot"
    assert load_log(logs[0])["context"]["opening_messages"]


def test_execute_skips_and_counts_unrunnable_cells(tmp_path):
    cells = [c for c in blocks() if c["block"] == "archetype_breadth" and c["archetype"] == 2][:1]
    result = execute(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path)
    assert result["runs"] == 0 and result["skipped"] == cells[0]["n"]


def test_execute_seeds_are_unique_across_runs(tmp_path):
    cells = [c for c in blocks() if c["block"] == "pilot"]
    execute(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path)
    seeds = [load_log(p)["header"]["seed"] for p in tmp_path.glob("*.jsonl")]
    assert len(set(seeds)) == 40


def test_execute_propagates_halt(tmp_path):
    def bad(sp, tb):
        tb.call("curl", url="x")

    cells = [c for c in blocks() if c["block"] == "pilot"][:1]
    try:
        execute(cells, bad, model="stub", log_dir=tmp_path)
    except HaltRun:
        return
    raise AssertionError("HaltRun was swallowed")


def test_execute_resumes_and_does_not_repeat_completed_runs(tmp_path):
    cells = [c for c in blocks() if c["block"] == "pilot"]
    calls = []

    def flaky(sp, tb):
        calls.append(1)
        if len(calls) == 6:
            raise RuntimeError("upstream")
        return "ok"

    try:
        execute(cells, flaky, model="stub", log_dir=tmp_path)
    except RuntimeError:
        pass
    result = execute(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path)
    assert result["resumed"] == 5 and result["runs"] == 35
    complete = [p for p in tmp_path.glob("*.jsonl") if load_log(p)["final"]["error"] is None]
    assert len(complete) == 40


def test_every_money_level_implies_a_plausible_day_ahead_price_move():
    from remit_cni.runner import MONEY_LEVELS
    from remit_cni.scenarios.compiler import SETTLEMENT_HOURS, TRIP_FAULT_MW

    assert len(MONEY_LEVELS) == 4
    assert max(m / (TRIP_FAULT_MW * SETTLEMENT_HOURS) for m in MONEY_LEVELS) <= 25.0


def test_execute_parallel_runs_all_cells_and_matches_sequential_resume_state(tmp_path):
    from remit_cni.runner import execute_parallel

    cells = [dict(c, n=6) for c in blocks() if c["block"] == "pilot"][:1]
    result = execute_parallel(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path, max_workers=4)
    assert result["runs"] == 6 and result["skipped"] == 0
    logs = list(tmp_path.glob("*.jsonl"))
    assert len(logs) == 6
    for p in logs:
        assert load_log(p)["final"]["error"] is None


def test_execute_parallel_resumes_and_does_not_repeat_completed_runs(tmp_path):
    from remit_cni.runner import execute_parallel

    cells = [dict(c, n=6) for c in blocks() if c["block"] == "pilot"][:1]
    execute_parallel(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path, max_workers=3)
    result = execute_parallel(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path, max_workers=3)
    assert result["runs"] == 0 and result["resumed"] == 6
    assert len(list(tmp_path.glob("*.jsonl"))) == 6


def test_execute_parallel_one_run_erroring_does_not_stop_the_others(tmp_path):
    from remit_cni.runner import execute_parallel

    def flaky(sp, tb):
        if tb.run_id.endswith(("0", "5", "a", "f")):
            raise RuntimeError("upstream")
        return "ok"

    cells = [dict(c, n=8) for c in blocks() if c["block"] == "pilot"][:1]
    result = execute_parallel(cells, flaky, model="stub", log_dir=tmp_path, max_workers=4)
    assert result["runs"] + result["errored"] == 8
    assert result["errored"] > 0
    logs = [load_log(p) for p in tmp_path.glob("*.jsonl")]
    assert sum(1 for l in logs if l["final"]["error"] is not None) == result["errored"]
