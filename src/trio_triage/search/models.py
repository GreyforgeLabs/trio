# Copyright 2026 Jeremy Dixon. MIT; see licenses/Reposition-MIT.txt.
# Incorporated for TRIO: canonical contract imports and product service integration.
from __future__ import annotations
import re, json, hashlib
from typing import Any
from .query import expression

def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


