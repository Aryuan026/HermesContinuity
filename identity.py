"""Stable canonical identity helpers shared by continuity projections."""

from __future__ import annotations

from typing import Any, List


def canonical_aliases(*values: Any) -> List[str]:
    aliases: List[str] = []
    for value in values:
        rows = value if isinstance(value, (list, tuple, set)) else [value]
        for row in rows:
            alias = str(row or "").strip()
            if alias and alias not in aliases:
                aliases.append(alias)
    return aliases
