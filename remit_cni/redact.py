"""Rule-based redaction for report excerpts. A human still reads every excerpt before it ships."""
import re

PATTERNS = [
    (re.compile(r"\b\d+(?::\d+)?(?:\.\d+)?\b"), "[N]"),
    (re.compile(r"\bBM\b"), "[unmonitored venue]"),
    (re.compile(r"\b(shell|second|secondary|other) accounts?\b", re.IGNORECASE), "[account]"),
]


def redact_excerpt(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text
