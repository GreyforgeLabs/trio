# Copyright 2026 Jeremy Dixon. MIT; see licenses/Reposition-MIT.txt.
# Incorporated for TRIO: canonical contract imports and product service integration.
from __future__ import annotations
import re, json, hashlib
from typing import Any
from .query import expression

def _match_span(text: str, query: str) -> tuple[int, int] | None:
    """Find a literal query span without changing the source's code-point offsets."""
    spans = []
    for literal in re.findall(r'"([^\"]+)"', expression(query)):
        words = literal.split()
        pattern = r"(?<![^\W_])" + r"[\W_]+".join(map(re.escape, words)) + r"(?![^\W_])"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            spans.append(match.span())
        elif len(words) > 1:
            # TF-IDF flattens phrases; retain a matching term when no phrase is present.
            for word in words:
                match = re.search(
                    r"(?<![^\W_])" + re.escape(word) + r"(?![^\W_])", text, re.IGNORECASE
                )
                if match:
                    spans.append(match.span())
    return min(spans) if spans else None


