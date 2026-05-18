"""Parse human duration strings like "30m", "1h30m", "45s", "2h"."""
from __future__ import annotations

import re

_PATTERN = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE)


def parse_duration(value: str | int | float) -> float:
    """Return seconds.

    Accepts: "30", "30s", "5m", "1h", "1h30m", "1h30m45s", or numeric.
    A bare number is interpreted as seconds.
    """
    if isinstance(value, (int, float)):
        return float(value)
    s = value.strip().lower()
    if not s:
        raise ValueError("empty duration")
    if s.isdigit():
        return float(s)
    m = _PATTERN.match(s)
    if not m or not any(m.groups()):
        # Try float seconds form like "30.5"
        try:
            return float(s)
        except ValueError as exc:
            raise ValueError(f"invalid duration: {value!r}") from exc
    h, mm, ss = m.groups()
    return (int(h or 0) * 3600) + (int(mm or 0) * 60) + (int(ss or 0))


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return "".join(parts)
