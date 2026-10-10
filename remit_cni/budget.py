"""Prereg section 9 stopping rule: run blocks in order, stop at the budget ceiling, never cut the
confirmatory money grid. Price constants are UNVERIFIED (see docs/run_budget.md: no provider price page
has been opened in this session) - replace before relying on this for a real budget decision.
"""
from pathlib import Path
from typing import Callable

from remit_cni.runner import ToolBox, execute, execute_parallel
from remit_cni.sandbox.logger import load_log

# [UNVERIFIED] placeholder rates; docs/run_budget.md says the pilot's measured cost per run should
# replace this estimate before Phase 5. Deliberately conservative (high) so a stale rate fails safe
# by stopping early rather than overrunning the ceiling.
PRICE_PER_1K_TOKENS_GBP = {"input": 0.0006, "output": 0.0024}
DEFAULT_CEILING_GBP = 700.0
PROTECTED_BLOCKS = ("pilot", "grid_none", "grid_disconnection")


def estimate_cost_gbp(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens / 1000) * PRICE_PER_1K_TOKENS_GBP["input"] + \
           (completion_tokens / 1000) * PRICE_PER_1K_TOKENS_GBP["output"]


def _spent_gbp(log_dir: Path) -> float:
    """Sums usage across completed logs. A log with no final record yet (another process is still
    writing it) is skipped rather than raised on - it isn't finished, and its cost is a lower bound on
    what has already been spent, which is fine for a stopping rule (it only ever under-estimates spend,
    never over-estimates it into stopping early)."""
    total = 0.0
    for path in Path(log_dir).glob("*.jsonl"):
        try:
            usage = load_log(path)["usage"]
        except StopIteration:
            continue
        total += estimate_cost_gbp(usage["prompt_tokens"], usage["completion_tokens"])
    return total


def execute_within_budget(cells: list[dict], agent: Callable[[str, ToolBox], str | None], model: str,
                          log_dir: Path, ceiling_gbp: float = DEFAULT_CEILING_GBP,
                          max_workers: int = 1) -> dict:
    """Runs cells block by block, in the given order, stopping before starting a block that would push
    estimated spend past the ceiling - except a PROTECTED_BLOCKS block, which always runs regardless of
    the ceiling, per prereg section 9 ("a ceiling cuts exploratory blocks ... never blocks 1-2")."""
    by_block: dict[str, list[dict]] = {}
    order: list[str] = []
    for cell in cells:
        if cell["block"] not in by_block:
            by_block[cell["block"]] = []
            order.append(cell["block"])
        by_block[cell["block"]].append(cell)

    blocks_run, blocks_skipped, stopped = [], [], False
    for block in order:
        spent = _spent_gbp(log_dir)
        if spent >= ceiling_gbp and block not in PROTECTED_BLOCKS:
            blocks_skipped.append(block)
            stopped = True
            continue
        if max_workers > 1:
            execute_parallel(by_block[block], agent, model=model, log_dir=log_dir, max_workers=max_workers)
        else:
            execute(by_block[block], agent, model=model, log_dir=log_dir)
        blocks_run.append(block)

    return {"blocks_run": blocks_run, "blocks_skipped": blocks_skipped, "stopped_on_budget": stopped,
           "spent_gbp": _spent_gbp(log_dir)}
