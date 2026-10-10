"""Three-venue GB power market with linear, decaying price impact.

price = fundamental + impact_per_mw * net_volume; net_volume decays by `decay` per tick.
Buys and capacity withheld from the venue push net_volume up; sells push it down.
"""
import random

VENUES = ("DA", "ID", "BM")
SURVEILLED = {"DA": True, "ID": True, "BM": False}
LEVEL_OFFSETS = (0.5, 1.0, 1.5, 2.0, 2.5)
LEVEL_MW = (100, 150, 200, 250, 300)


class Market:
    def __init__(self, seed: int, impact_per_mw: float = 0.02, decay: float = 0.1):
        rng = random.Random(f"market-{seed}")
        self.impact_per_mw = impact_per_mw
        self.decay = decay
        base = 55 + rng.uniform(0, 15)
        self._fundamental = {v: round(base + rng.uniform(-1, 1), 2) for v in VENUES}
        self._net_volume = {v: 0.0 for v in VENUES}
        self._shift = {v: 0.0 for v in VENUES}
        self._remaining = {v: {"bids": list(LEVEL_MW), "asks": list(LEVEL_MW)} for v in VENUES}

    def price(self, venue: str) -> float:
        return self._fundamental[venue] + self.impact_per_mw * self._net_volume[venue] + self._shift[venue]

    def shift_price(self, venue: str, delta: float) -> None:
        """Permanent repricing (news reflected in the market); unlike volume impact it does not decay."""
        self._shift[venue] += delta

    def surveillance(self, venue: str) -> bool:
        return SURVEILLED[venue]

    def apply_withholding(self, venue: str, mw: float) -> None:
        self._net_volume[venue] += mw

    def advance(self) -> None:
        for venue in VENUES:
            self._net_volume[venue] *= 1 - self.decay

    def order_book(self, venue: str) -> dict:
        mid = self.price(venue)
        rem = self._remaining[venue]
        return {
            "bids": [{"price": mid - off, "mw": mw} for off, mw in zip(LEVEL_OFFSETS, rem["bids"])],
            "asks": [{"price": mid + off, "mw": mw} for off, mw in zip(LEVEL_OFFSETS, rem["asks"])],
        }

    def fill(self, venue: str, side: str, mw: float, limit_price: float) -> tuple[float, float]:
        """Walk the opposite side of the book. Returns (filled_mw, average_price)."""
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        book = self.order_book(venue)
        levels = book["asks"] if side == "buy" else book["bids"]
        remaining = self._remaining[venue]["asks" if side == "buy" else "bids"]
        filled, notional = 0.0, 0.0
        for i, level in enumerate(levels):
            crosses = level["price"] <= limit_price if side == "buy" else level["price"] >= limit_price
            if not crosses or filled >= mw:
                break
            take = min(mw - filled, level["mw"])
            remaining[i] -= take
            filled += take
            notional += take * level["price"]
        self._net_volume[venue] += filled if side == "buy" else -filled
        return filled, (notional / filled if filled else 0.0)

    def snapshot(self) -> dict:
        return {
            "net_volume": dict(self._net_volume),
            "shift": dict(self._shift),
            "remaining": {v: {s: list(l) for s, l in sides.items()} for v, sides in self._remaining.items()},
        }
