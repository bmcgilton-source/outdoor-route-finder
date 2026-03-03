"""
Brief Reviewer — lightweight final-pass agent that cleans all prose text
fields in the assembled trip brief before it is shown to the user.

Two-pass approach:
  1. Claude call — rewrites the main narrative blocks (conditions summary,
     itinerary summary, gear notes, risk dominant factor) in clean plain prose.
  2. Regex pass — strips residual markdown artifacts (bold, italic, bullets,
     inline code) from short string fields (highlights, camp names, gear reasons).
"""

import json
import re

import anthropic

from logger import get_logger
from tools.base import CONFIG

log = get_logger(__name__)

_client = anthropic.Anthropic()
_MODEL  = CONFIG["claude"]["haiku_model"]

_SYSTEM = """\
You are a copy editor for TrailOps hiking trip briefs.

Your job: receive a set of AI-generated prose text fields that may contain
formatting artifacts, and return them cleaned up.

Rules:
- Remove ALL markdown formatting: no **bold**, no *italic*, no # headers,
  no - bullet points, no numbered lists, no backticks, no ``` code fences.
- Fix broken or awkward sentences into natural, flowing plain English.
- Keep every factual detail intact — do not add or remove information.
- Write in a warm, conversational tone.
- Return ONLY a valid JSON object with the same keys as the input.
  No preamble, no explanation, no text outside the JSON.
"""


def run(brief: dict) -> dict:
    """
    Review and clean all prose text fields in the assembled trip brief.

    Skips briefs with error status (no_route_found, no_viable_route) since
    those are short messages, not AI-generated narrative.

    Returns the brief with cleaned text in-place.
    """
    if brief.get("status") in ("no_route_found", "no_viable_route"):
        return brief
    log.info("Brief Reviewer: cleaning prose fields")

    # --- Pass 1: Claude rewrites main narrative blocks ---
    prose = {
        "conditions_summary": brief.get("conditions", {}).get("summary", ""),
        "itinerary_summary":  brief.get("itinerary", {}).get("itinerary_summary", ""),
        "gear_notes":         brief.get("gear_notes", ""),
        "risk_dominant_factor": brief.get("risk", {}).get("dominant_factor", ""),
    }

    if any(prose.values()):
        cleaned = _claude_clean(prose)
        if cleaned.get("conditions_summary"):
            brief.setdefault("conditions", {})["summary"] = cleaned["conditions_summary"]
        if cleaned.get("itinerary_summary"):
            brief.setdefault("itinerary", {})["itinerary_summary"] = cleaned["itinerary_summary"]
        if cleaned.get("gear_notes"):
            brief["gear_notes"] = cleaned["gear_notes"]
        if cleaned.get("risk_dominant_factor"):
            brief.setdefault("risk", {})["dominant_factor"] = cleaned["risk_dominant_factor"]

    # --- Pass 2: Regex strip on short string fields ---
    for day in brief.get("itinerary", {}).get("days", []):
        if day.get("highlights"):
            day["highlights"] = [_strip_md(h) for h in day["highlights"]]
        if day.get("camp"):
            day["camp"] = _strip_md(day["camp"])

    for item in brief.get("gear", []):
        if item.get("item"):
            item["item"] = _strip_md(item["item"])
        if item.get("reason"):
            item["reason"] = _strip_md(item["reason"])

    return brief


def _claude_clean(prose: dict) -> dict:
    """Send prose fields to Claude for cleanup. Falls back to originals on any error."""
    try:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    "Clean up these trip brief text fields and return them as a JSON "
                    "object with the same keys:\n\n"
                    + json.dumps(prose, indent=2)
                ),
            }],
        )
        raw = next((b.text for b in response.content if hasattr(b, "text")), "{}")
        return _parse_json(raw)
    except Exception as e:
        log.warning(f"Brief Reviewer: Claude cleanup failed — using originals. Error: {e}")
        return prose


def _strip_md(text: str) -> str:
    """Remove common markdown artifacts from a short string."""
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)   # bold / italic
    text = re.sub(r"`([^`\n]+)`", r"\1", text)                  # inline code
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered lists
    return text.strip()


def _parse_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().strip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            pass
    return {}
