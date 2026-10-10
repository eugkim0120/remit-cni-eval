"""Stopping rule (prereg section 9): run blocks in order, stop at the budget ceiling; grid blocks always run."""
from remit_cni.runner import blocks


def test_estimate_cost_gbp_scales_with_tokens():
    from remit_cni.budget import PRICE_PER_1K_TOKENS_GBP, estimate_cost_gbp

    assert estimate_cost_gbp(prompt_tokens=1000, completion_tokens=0) == PRICE_PER_1K_TOKENS_GBP["input"]
    assert estimate_cost_gbp(prompt_tokens=0, completion_tokens=1000) == PRICE_PER_1K_TOKENS_GBP["output"]
    assert estimate_cost_gbp(prompt_tokens=2000, completion_tokens=1000) == pytest_approx(
        2 * PRICE_PER_1K_TOKENS_GBP["input"] + PRICE_PER_1K_TOKENS_GBP["output"])


def pytest_approx(x):
    import pytest
    return pytest.approx(x)


def test_execute_within_budget_stops_before_the_ceiling_and_reports_skipped_blocks(tmp_path):
    from remit_cni.budget import execute_within_budget

    def costly_agent(sp, tb):
        tb.usage(100_000, 100_000)  # far above any realistic per-run cost, forces an early stop
        return "ok"

    cells = [c for c in blocks() if c["block"] in ("pilot", "severity_curve")]
    result = execute_within_budget(cells, costly_agent, model="stub", log_dir=tmp_path, ceiling_gbp=0.01)
    assert result["stopped_on_budget"] is True
    assert result["blocks_run"] == ["pilot"] and result["blocks_skipped"] == ["severity_curve"]


def test_execute_within_budget_never_skips_the_confirmatory_grid_blocks(tmp_path):
    from remit_cni.budget import PROTECTED_BLOCKS, execute_within_budget

    assert PROTECTED_BLOCKS == ("pilot", "grid_none", "grid_disconnection")

    def costly_agent(sp, tb):
        tb.usage(100_000, 100_000)
        return "ok"

    cells = [c for c in blocks() if c["block"] in PROTECTED_BLOCKS or c["block"] == "framing_arms"]
    result = execute_within_budget(cells, costly_agent, model="stub", log_dir=tmp_path, ceiling_gbp=0.0001)
    assert set(result["blocks_run"]) >= set(PROTECTED_BLOCKS) & {c["block"] for c in cells}
    assert "framing_arms" in result["blocks_skipped"]


def test_execute_within_budget_completes_normally_under_the_ceiling(tmp_path):
    from remit_cni.budget import execute_within_budget

    cells = [dict(c, n=2) for c in blocks() if c["block"] == "pilot"][:1]
    result = execute_within_budget(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path, ceiling_gbp=700)
    assert result["stopped_on_budget"] is False and result["blocks_skipped"] == []


def test_spent_gbp_ignores_a_log_still_being_written(tmp_path):
    from remit_cni.budget import _spent_gbp

    partial = tmp_path / "inflight.jsonl"
    partial.write_text('{"type": "header", "run_id": "x"}\n{"type": "usage", "prompt_tokens": 100, "completion_tokens": 50}\n')
    assert _spent_gbp(tmp_path) == 0.0


def test_execute_within_budget_can_run_a_block_in_parallel(tmp_path):
    from remit_cni.budget import execute_within_budget

    cells = [dict(c, n=6) for c in blocks() if c["block"] == "pilot"][:1]
    result = execute_within_budget(cells, lambda sp, tb: "ok", model="stub", log_dir=tmp_path,
                                   ceiling_gbp=700, max_workers=4)
    assert result["stopped_on_budget"] is False
    assert len(list(tmp_path.glob("*.jsonl"))) == 6
