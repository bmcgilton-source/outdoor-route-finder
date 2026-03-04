"""
Assessment Agent — runs after BOTH Intelligence Agent and Day Planner complete.

Responsibilities:
  1. Run Risk Scorer (deterministic code)
  2. If replanning required → spawn Replanner (max 1 attempt)
  3. If still failing → spawn Plan B (max 1 attempt)
  4. If Plan B fails → set no_viable_route in Trip Context

Gear recommendations are generated on-demand from the UI, not in this pipeline.
Does NOT make a Claude call itself — it orchestrates the sub-agents and scorer.
"""

import risk_scorer
from agents.assessment import replanner
from agents.assessment import plan_b as plan_b_agent
from logger import get_logger

log = get_logger(__name__)


def run(trip_context: dict, progress_cb=None) -> dict:
    """
    Run the full assessment pipeline.

    Reads from trip_context: conditions, itinerary, selected_route, user_input
    Writes to trip_context: gear, risk, plan_b, no_viable_route, reasoning_trace

    progress_cb: optional callable(str) for live UI progress updates.

    Returns: updated trip_context
    """
    def _cb(msg: str) -> None:
        log.debug(msg)
        print(f"      -> {msg}", flush=True)
        if progress_cb:
            progress_cb(msg)

    trace = trip_context.setdefault("reasoning_trace", [])
    trace.append({"agent": "assessment", "event": "start"})

    # Step 1: Score risk (deterministic)
    trip_context = risk_scorer.score(trip_context)

    risk = trip_context["risk"]
    dominant = risk.get("dominant_factor") or "none"
    _cb(f"Risk assessed: {risk['overall_risk'].upper()}  ·  main concern: {dominant}")
    trace.append({
        "agent": "assessment",
        "event": "risk_scored",
        "overall_risk": risk["overall_risk"],
        "replanning_required": risk["replanning_required"],
    })

    if not risk["replanning_required"]:
        trace.append({"agent": "assessment", "event": "complete", "path": "green_light"})
        return trip_context

    # Step 3: Replanner (max 1 attempt)
    log.warning(f"Assessment: {risk['overall_risk'].upper()} risk — spawning Replanner (dominant: {dominant})")
    _cb(f"Risk elevated ({dominant}) — adjusting the itinerary…")
    trace.append({"agent": "assessment", "event": "spawning_replanner"})
    trip_context = replanner.run(trip_context)

    # Re-score after replanning
    trip_context = risk_scorer.score(trip_context)
    risk = trip_context["risk"]

    if not risk["replanning_required"]:
        trace.append({"agent": "assessment", "event": "complete", "path": "replanned"})
        return trip_context

    # Step 4: Plan B (max 1 attempt)
    log.warning(f"Assessment: Replanner insufficient — spawning Plan B (dominant: {risk.get('dominant_factor')})")
    _cb("Itinerary adjustment insufficient — searching for an alternate route…")
    trace.append({"agent": "assessment", "event": "spawning_plan_b"})
    trip_context = plan_b_agent.run(trip_context)

    # Re-score Plan B conditions if available
    if trip_context.get("plan_b") and not trip_context.get("no_viable_route"):
        trip_context = risk_scorer.score(trip_context)
        risk = trip_context["risk"]

        if not risk["replanning_required"]:
            trace.append({"agent": "assessment", "event": "complete", "path": "plan_b"})
            return trip_context

    # Step 5: No viable route
    if not trip_context.get("no_viable_route"):
        log.error(f"Assessment: no viable route found (dominant: {risk.get('dominant_factor')}, risk: {risk.get('overall_risk')})")
        trip_context["no_viable_route"] = _build_no_viable_response(trip_context)

    trace.append({"agent": "assessment", "event": "complete", "path": "no_viable_route"})
    return trip_context


def _build_no_viable_response(trip_context: dict) -> dict:
    risk = trip_context.get("risk", {})
    conditions = trip_context.get("conditions", {})
    route = trip_context.get("selected_route", {})

    return {
        "dominant_factor": risk.get("dominant_factor", "unknown"),
        "overall_risk": risk.get("overall_risk", "high"),
        "route_attempted": route.get("name", ""),
        "conditions_summary": conditions.get("synthesis_notes", ""),
        "what_was_tried": ["original itinerary", "replanner adjustment", "plan b alternate route"],
        "suggested_next_steps": [
            "Check conditions again closer to your trip date",
            "Consider an alternate region with lower risk",
            "Reduce trip length to avoid the highest-risk days",
        ],
    }
