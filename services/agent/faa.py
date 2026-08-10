"""FAA National Airspace System live status.

One keyless public XML feed (``nasstatus.faa.gov``) reporting what is happening in
US airspace *right now*: ground stops, ground delay programmes, general
arrival/departure delays and airport closures.

This is the only tool in the service that reads live data, and it is deliberately
fenced off from the investment analysis:

* **Everything else answers from BTS/FAA historical data via SQL.** Those numbers
  are stable, sourced and reproducible.
* **This answers "is the airport in trouble this afternoon".** A thunderstorm over
  Boston is an operations fact, not evidence about a terminal-expansion case.

The prompt states that distinction as a hard rule; the tool payload repeats it, so
a model that skipped the prompt still sees it next to the numbers.

Failure is a normal outcome, not an exception: an external feed that is down,
slow or reshaped must degrade to "FAA feed unavailable" and leave the rest of the
answer intact.
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from agent.logging_config import get_logger

log = get_logger(__name__)

#: The feed is ~6 KB. Anything far past that is not the document we expect, and
#: ElementTree offers no protection against a hostile one - so cap before parsing.
MAX_BODY_BYTES = 2_000_000

#: Section list-element tags. Dispatch is on the child tag rather than on the
#: <Name> text: the live feed emits the same Name more than once (two separate
#: "Airport Closures" blocks were observed), so keying on Name loses rows.
_SECTIONS = {
    "Ground_Stop_List": "ground_stops",
    "Ground_Delay_List": "ground_delays",
    "Arrival_Departure_Delay_List": "delays",
    "Airport_Closure_List": "closures",
}

_EMPTY: dict[str, list[dict[str, Any]]] = {name: [] for name in _SECTIONS.values()}


class _Cache:
    """Whole-document cache. One fetch serves every airport asked about.

    The lock matters: without it, N concurrent questions on a cold cache become N
    calls to a public government feed.
    """

    def __init__(self) -> None:
        self._at: float = 0.0
        self._doc: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def get(self, url: str, timeout: float, ttl: float) -> dict[str, Any]:
        now = time.monotonic()
        if self._doc is not None and now - self._at < ttl:
            return self._doc
        async with self._lock:
            # Another request may have refreshed it while we waited for the lock.
            now = time.monotonic()
            if self._doc is not None and now - self._at < ttl:
                return self._doc
            doc = await _fetch(url, timeout)
            if doc.get("available"):
                self._doc, self._at = doc, now
            elif self._doc is not None:
                # Serve the last good document rather than nothing, clearly stale-marked.
                return {**self._doc, "stale": True, "refresh_error": doc.get("error")}
            return doc

    def clear(self) -> None:
        self._doc, self._at = None, 0.0


_cache = _Cache()


def _text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    value = (node.findtext(tag) or "").strip()
    return value or None


def _entry(item: ET.Element) -> dict[str, Any]:
    """Flatten one section row. Shapes differ per section; keep whatever is there."""
    row: dict[str, Any] = {"iata": _text(item, "ARPT"), "reason": _text(item, "Reason")}
    for tag, key in (
        ("End_Time", "end_time"),
        ("Avg", "average_delay"),
        ("Max", "max_delay"),
        ("Start", "closed_since"),
        ("Reopen", "reopens"),
    ):
        value = _text(item, tag)
        if value:
            row[key] = value
    # General arrival/departure delays nest their numbers one level down.
    leg = item.find("Arrival_Departure")
    if leg is not None:
        row["direction"] = leg.get("Type")
        for tag, key in (("Min", "min_delay"), ("Max", "max_delay"), ("Trend", "trend")):
            value = _text(leg, tag)
            if value:
                row[key] = value
    return row


def parse(xml_text: str) -> dict[str, Any]:
    """Parse the NAS status document into per-section lists."""
    root = ET.fromstring(xml_text)
    doc: dict[str, Any] = {
        "available": True,
        "updated": _text(root, "Update_Time"),
        **{name: [] for name in _SECTIONS.values()},
    }
    for section in root.iter():
        key = _SECTIONS.get(section.tag)
        if key is None:
            continue
        for item in section:
            entry = _entry(item)
            if entry.get("iata"):
                doc[key].append(entry)
    return doc


async def _fetch(url: str, timeout: float) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/xml"})
        response.raise_for_status()
        if len(response.content) > MAX_BODY_BYTES:
            raise ValueError(f"response is {len(response.content)} bytes, over the cap")
        return parse(response.text)
    except Exception as exc:
        log.warning("FAA feed unavailable", extra={"error": f"{type(exc).__name__}: {exc}"})
        return {"available": False, "error": f"{type(exc).__name__}: {exc}", **_EMPTY}


async def airport_status(
    iata: str, *, url: str, timeout: float = 5.0, ttl: float = 300.0
) -> dict[str, Any]:
    """Live NAS status for one airport.

    Returns ``available: False`` with a reason when the feed cannot be read - never
    raises, so a live-status failure cannot take down an answer built on SQL.
    """
    code = (iata or "").strip().upper()
    doc = await _cache.get(url, timeout, ttl)
    if not doc.get("available"):
        return {
            "iata": code,
            "available": False,
            "error": doc.get("error"),
            "note": "FAA feed unavailable - live operational status is unknown right now.",
        }

    mine = {key: [r for r in doc.get(key, []) if r.get("iata") == code] for key in _EMPTY}
    impacts = sum(len(v) for v in mine.values())
    return {
        "iata": code,
        "available": True,
        "feed_updated": doc.get("updated"),
        "stale": doc.get("stale", False),
        "has_impacts": impacts > 0,
        "impact_count": impacts,
        "status": "normal operations reported" if impacts == 0 else "operational impacts reported",
        **mine,
    }


def reset_cache() -> None:
    """Test hook - drop the cached document."""
    _cache.clear()
