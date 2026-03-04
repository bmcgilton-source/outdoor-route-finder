"""
Brief Reviewer — regex-only pass that strips markdown artifacts from all
prose text fields in the assembled trip brief before display.

No Claude call — pure regex for zero latency.
"""

import re

from logger import get_logger

log = get_logger(__name__)


def run(brief: dict) -> dict:
    """
    Strip markdown artifacts from all prose fields in the trip brief.

    Skips briefs with error status (no_route_found, no_viable_route).
    Returns the brief with cleaned text in-place.
    """
    if brief.get("status") in ("no_route_found", "no_viable_route"):
        return brief
    log.info("Brief Reviewer: stripping markdown artifacts")

    # Narrative prose fields
    conditions = brief.get("conditions", {})
    if conditions.get("summary"):
        conditions["summary"] = _strip_md(conditions["summary"])

    itinerary = brief.get("itinerary", {})
    if itinerary.get("itinerary_summary"):
        itinerary["itinerary_summary"] = _strip_md(itinerary["itinerary_summary"])
    if itinerary.get("planner_notes"):
        itinerary["planner_notes"] = _strip_md(itinerary["planner_notes"])

    if brief.get("gear_notes"):
        brief["gear_notes"] = _strip_md(brief["gear_notes"])

    # Per-day fields
    for day in itinerary.get("days", []):
        if day.get("highlights"):
            day["highlights"] = [_strip_md(h) for h in day["highlights"]]
        if day.get("camp"):
            day["camp"] = _strip_md(day["camp"])
        if day.get("description"):
            day["description"] = _strip_md(day["description"])

    # Gear items
    for item in brief.get("gear", []):
        if item.get("item"):
            item["item"] = _strip_md(item["item"])
        if item.get("reason"):
            item["reason"] = _strip_md(item["reason"])

    return brief


def _strip_md(text: str) -> str:
    """Remove common markdown artifacts from a string."""
    if not text:
        return text
    text = re.sub(r"```(?:[a-z]*)?\n?", "", text)                   # code fences
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)         # bold / italic
    text = re.sub(r"`([^`\n]+)`", r"\1", text)                      # inline code
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)      # headings
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)    # bullets
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)    # numbered lists
    text = re.sub(r"\n{3,}", "\n\n", text)                          # excess newlines
    return text.strip()
