"""
TrailOps — Streamlit web UI

Run with:
    streamlit run streamlit_app.py

Replaces the terminal ui.py with a web interface.
All agents and orchestrator are unchanged.
"""

import json
import re
import time
from pathlib import Path

import anthropic
import folium
import streamlit as st
import streamlit.components.v1 as _stc

import orchestrator
from agents.assessment import gear as gear_module
from tools.base import CONFIG
from ui import _build_system, _is_valid_input, _save_adhoc_route, _try_parse_json

# ── Constants ─────────────────────────────────────────────────────────────────

_client      = anthropic.Anthropic()
_HAIKU_MODEL  = CONFIG["claude"]["haiku_model"]   # haiku — Q&A chat
_SONNET_MODEL = CONFIG["claude"]["model"]         # sonnet — intake

# risk_scorer emits: low / medium / high
# display labels:    LOW / MODERATE / HIGH / CRITICAL
# mapping → (display_label, border_color, background_color)
_RISK = {
    "low":      ("LOW",      "#22C55E", "rgba(34, 197, 94, 0.15)"),
    "medium":   ("MODERATE", "#F59E0B", "rgba(245, 158, 11, 0.15)"),
    "high":     ("HIGH",     "#EF4444", "rgba(239, 68, 68, 0.15)"),
    "critical": ("CRITICAL", "#991B1B", "rgba(153, 27, 27, 0.15)"),
}

_PERMIT_LABELS = {
    "none":       "None required",
    "advance":    "Advance — Recreation.gov",
    "lottery":    "⚠ Lottery — very competitive",
    "self-issue": "Self-issue at trailhead",
}

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TrailOps",
    page_icon="🏔",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  footer  { visibility: hidden; }
  #MainMenu { visibility: hidden; }
  header  { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults = {
        "screen":           "landing",
        "intake_messages":  [],
        "intake_system":    None,
        "user_input":       {},
        "route_options":    [],
        "brief":            None,
        "qa_messages":      [],
        "qa_pending_action": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Router ────────────────────────────────────────────────────────────────────

def main() -> None:
    _init_state()
    screen = st.session_state.screen
    if   screen == "landing":          _show_landing()
    elif screen == "intake":           _show_intake()
    elif screen == "route_library":    _show_route_library()
    elif screen == "route_selection":  _show_route_selection()
    elif screen == "planning":         _show_planning()
    elif screen == "brief":            _show_brief()


# ── Screen 1 — Landing ────────────────────────────────────────────────────────

def _show_landing() -> None:
    st.markdown("""
    <div style="text-align:center;padding:72px 0 36px;">
      <div style="font-size:2.8rem;font-weight:700;">🏔 TrailOps</div>
      <div style="font-size:1.1rem;color:#6B7280;margin-top:6px;">
        Pacific Northwest Route Planner
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="background:var(--secondary-background-color);border-radius:10px;
                padding:14px 24px;margin:0 auto 36px;text-align:center;color:#6B7280;
                max-width:520px;font-size:0.95rem;">
      Live weather &nbsp;·&nbsp; Fire &amp; smoke &nbsp;·&nbsp; Water crossing risk
      &nbsp;·&nbsp; AI itineraries &nbsp;·&nbsp; Gear lists &nbsp;·&nbsp; Plan B routes
    </div>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        if st.button("Plan my trip  →", use_container_width=True, type="primary"):
            st.session_state.screen = "intake"
            st.rerun()
        if st.button("Browse routes", use_container_width=True):
            st.session_state.screen = "route_library"
            st.rerun()

    route_count = len(json.loads(Path("data/routes.json").read_text())["routes"])
    st.markdown(f"""
    <div style="text-align:center;color:#9CA3AF;margin-top:20px;font-size:0.85rem;">
      {route_count} routes &nbsp;·&nbsp; 5 regions &nbsp;·&nbsp; Easy to Epic difficulty
    </div>
    """, unsafe_allow_html=True)


# ── Screen 2 — Route library ──────────────────────────────────────────────────

def _show_route_library() -> None:
    col_title, col_back = st.columns([4, 1])
    with col_title:
        st.markdown("### Trail Database")
    with col_back:
        if st.button("← Back"):
            st.session_state.screen = "landing"
            st.rerun()

    routes = json.loads(Path("data/routes.json").read_text())["routes"]

    # Filters
    col_diff, col_region, col_type = st.columns(3)
    difficulties = ["All"] + sorted({r["difficulty"] for r in routes})
    regions      = ["All"] + sorted({r["sub_region"] for r in routes})
    types        = ["All"] + sorted({r["route_type"] for r in routes})
    diff_filter   = col_diff.selectbox("Difficulty", difficulties)
    region_filter = col_region.selectbox("Region", regions)
    type_filter   = col_type.selectbox("Type", types)

    filtered = [
        r for r in routes
        if (diff_filter  == "All" or r["difficulty"] == diff_filter)
        and (region_filter == "All" or r["sub_region"] == region_filter)
        and (type_filter   == "All" or r["route_type"] == type_filter)
    ]

    st.caption(f"{len(filtered)} route{'s' if len(filtered) != 1 else ''}")

    for r in filtered:
        res    = r.get("reservations", {})
        permit = _PERMIT_LABELS.get(res.get("permit_type", "none"), "")
        with st.container(border=True):
            col_name, col_btn = st.columns([4, 1])
            with col_name:
                adhoc_tag = "  ·  *user-added*" if r.get("_adhoc") else ""
                st.markdown(f"**{r['name']}**{adhoc_tag}")
                st.caption(
                    f"{r['sub_region']}  ·  {r['difficulty']}  ·  {r['route_type']}  ·  "
                    f"{r['total_miles']} mi  ·  +{r.get('elevation_gain_ft', 0):,} ft"
                )
                if permit and permit != "None required":
                    st.caption(f"Permit: {permit}")
            with col_btn:
                if st.button("Plan  →", key=f"lib_{r['id']}"):
                    st.session_state.intake_messages = [
                        {"role": "user", "content": f"I want to plan a trip to {r['name']}"}
                    ]
                    st.session_state.screen = "intake"
                    st.rerun()


# ── Intake Claude call ────────────────────────────────────────────────────────

def _intake_respond() -> None:
    """Call intake Claude and handle routing. Reads/writes session state."""
    with st.chat_message("assistant", avatar="🏔"):
        with st.spinner(""):
            try:
                response = _claude_create(
                    model=_SONNET_MODEL,
                    max_tokens=512,
                    system=st.session_state.intake_system,
                    messages=st.session_state.intake_messages,
                )
            except Exception:
                st.warning("The AI service is temporarily unavailable. Please try again in a moment.")
                return

        parsed = _try_parse_json(response)

        if parsed and _is_valid_input(parsed):
            # Coerce trip_length_days to int (Claude occasionally outputs 2.0)
            parsed["trip_length_days"] = int(parsed.get("trip_length_days") or 1)
            reply = "Got it — let me find your options."
            st.write(reply)
            st.session_state.intake_messages.append({"role": "assistant", "content": reply})
            st.session_state.user_input = parsed

            if parsed.get("requested_trail") and not parsed.get("route_id"):
                st.session_state.screen = "planning"
            elif parsed.get("route_id"):
                st.session_state.screen = "planning"
            else:
                with st.spinner("Searching routes..."):
                    options = orchestrator.get_route_options(parsed)
                st.session_state.route_options = options
                st.session_state.screen = "route_selection"
            st.rerun()
        else:
            st.write(response)
            st.session_state.intake_messages.append({"role": "assistant", "content": response})


# ── Screen 3 — Intake chat ────────────────────────────────────────────────────

def _show_intake() -> None:
    col_title, col_back = st.columns([4, 1])
    with col_title:
        st.markdown("#### 🏔 TrailOps")
    with col_back:
        if st.button("← Back"):
            _reset()

    # Build system prompt once and cache in session state
    if not st.session_state.intake_system:
        st.session_state.intake_system = _build_system()

    # Seed with opening greeting on first load
    if not st.session_state.intake_messages:
        st.session_state.intake_messages.append({
            "role": "assistant",
            "content": (
                "Hey! Tell me about your trip — where are you thinking, "
                "and when are you planning to go?"
            ),
        })

    # Render conversation history
    for msg in st.session_state.intake_messages:
        avatar = "🏔" if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=avatar):
            st.write(msg["content"])

    # Auto-call Claude if last message is from user (e.g. seeded from route library)
    if st.session_state.intake_messages[-1]["role"] == "user":
        _intake_respond()

    # Handle new user input
    if prompt := st.chat_input("Message TrailOps..."):
        with st.chat_message("user"):
            st.write(prompt)
        st.session_state.intake_messages.append({"role": "user", "content": prompt})
        _intake_respond()


# ── Screen 3 — Route selection cards ─────────────────────────────────────────

def _show_route_selection() -> None:
    ui = st.session_state.user_input
    options = st.session_state.route_options
    dates = ui.get("dates", {})
    trip_days = ui.get("trip_length_days", 1)

    st.markdown("### Routes for your trip")
    st.caption(
        f"{trip_days} day{'s' if trip_days != 1 else ''}  ·  "
        f"{ui.get('difficulty', '')}  ·  "
        f"{dates.get('start', '')} – {dates.get('end', '')}"
    )

    for opt in options:
        r       = opt["route"]
        is_best = opt["is_best"]
        res     = r.get("reservations", {})
        permit  = _PERMIT_LABELS.get(res.get("permit_type", "none"), "Unknown")

        with st.container(border=True):
            if is_best:
                st.success("★  Recommended")

            col_name, col_permit = st.columns([3, 1])
            with col_name:
                st.markdown(f"**{r['name']}**")
                st.caption(
                    f"{r['sub_region']}  ·  {r['difficulty']}  ·  {r['route_type']}"
                )
            with col_permit:
                if "⚠" in permit:
                    st.warning(permit, icon="⚠")
                else:
                    st.caption(f"Permit: {permit}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Miles",    r["total_miles"])
            c2.metric("Gain",     f"+{r['elevation_gain_ft']:,} ft")
            c3.metric("Mi / day", f"{opt['mi_per_day']:.1f}")
            c4.metric("Days",     opt["trip_days"])

            if is_best and r.get("description"):
                st.caption(r["description"][:220] + "…")

            st.caption(opt["rationale"])

            if st.button(
                "Plan this route  →",
                key=f"plan_{r['id']}",
                type="primary" if is_best else "secondary",
                use_container_width=True,
            ):
                st.session_state.user_input.update({
                    "route_id":   r["id"],
                    "difficulty": r["difficulty"],
                    "route_type": r["route_type"],
                })
                st.session_state.user_input.pop("requested_trail", None)
                st.session_state.screen = "planning"
                st.rerun()


# ── Screen 4 — Planning / loading ─────────────────────────────────────────────

def _show_planning() -> None:
    # Guard: if we already have a brief, skip straight through
    if st.session_state.brief is not None:
        st.session_state.screen = "brief"
        st.rerun()
        return

    ui = st.session_state.user_input
    route_display = (
        ui.get("requested_trail")
        or ui.get("route_id", "your route").replace("-", " ").title()
    )
    dates = ui.get("dates", {})

    st.markdown(f"### Planning {route_display}")
    st.caption(
        f"{dates.get('start', '')} – {dates.get('end', '')}  ·  "
        f"{ui.get('difficulty', '')}  ·  "
        f"{ui.get('trip_length_days', 1)} day(s)"
    )

    # ── Step tracker ──────────────────────────────────────────────────────────
    st.markdown(
        "<style>"
        "@keyframes trailops-spin { to { transform: rotate(360deg); } }"
        ".step-spin { display: inline-block; animation: trailops-spin 1s linear infinite; }"
        "</style>",
        unsafe_allow_html=True,
    )

    STEPS = [
        ("route",       "Selecting route"),
        ("conditions",  "Gathering conditions"),
        ("itinerary",   "Building itinerary"),
        ("risk",        "Scoring risk"),
        ("replan",      "Adjusting itinerary"),    # shown only if replanning triggered
        ("plan_b_step", "Finding alternate route"), # shown only if Plan B triggered
        ("brief",       "Polishing brief"),
    ]
    _labels = {k: v for k, v in STEPS}

    # Steps that start hidden and only appear if the pipeline reaches them
    _HIDDEN_INITIALLY = {"replan", "plan_b_step"}

    # Track current state so we can skip hidden steps in the final "mark all done" pass
    _state: dict[str, str] = {
        key: ("hidden" if key in _HIDDEN_INITIALLY else "pending")
        for key, _ in STEPS
    }

    def _step_html(key: str, state: str) -> str:
        if state == "hidden":
            return ""
        label = _labels[key]
        if state == "done":
            return f'<span style="color:#22C55E;">&#10003; {label}</span>'
        if state == "running":
            return f'<span style="color:#F59E0B;"><span class="step-spin">&#8635;</span> {label}&hellip;</span>'
        return f'<span style="color:#9CA3AF;">&#9675; {label}</span>'

    _ph = {}
    for key, _ in STEPS:
        _ph[key] = st.empty()
        _ph[key].markdown(_step_html(key, _state[key]), unsafe_allow_html=True)

    def _update(key: str, state: str) -> None:
        _state[key] = state
        _ph[key].markdown(_step_html(key, state), unsafe_allow_html=True)

    def progress_cb(msg: str) -> None:
        if "Route selected" in msg:
            _update("route",      "done")
            _update("conditions", "running")
            _update("itinerary",  "running")
        elif "Fetching live" in msg:
            _update("conditions", "running")
            _update("itinerary",  "running")
        elif "Conditions checked" in msg:
            _update("conditions", "done")
            _update("itinerary",  "done")
            _update("risk",       "running")
        elif "Risk assessed" in msg:
            _update("risk", "done")
        elif "Risk elevated" in msg:
            # Replanner spawned — show the replan step
            _update("replan", "running")
        elif "Itinerary adjustment insufficient" in msg:
            # Plan B spawned — show the Plan B step
            _update("replan",      "done")
            _update("plan_b_step", "running")
        elif "Polishing" in msg:
            # Whatever was last running, close it out
            for key in ("replan", "plan_b_step"):
                if _state[key] == "running":
                    _update(key, "done")
            _update("brief", "running")

    brief = orchestrator.run(ui, progress_cb=progress_cb)

    # Mark any remaining visible steps done (skip steps that were never shown)
    for key, _ in STEPS:
        if _state[key] != "hidden":
            _update(key, "done")

    # Auto-save ad-hoc routes to build the trail database
    if brief.get("route", {}).get("_adhoc"):
        _save_adhoc_route(brief["route"])

    st.session_state.brief = brief
    st.session_state.screen = "brief"
    st.rerun()


# ── Screen 5 — Trip brief ─────────────────────────────────────────────────────

def _show_brief() -> None:
    brief = st.session_state.brief
    if brief is None:
        st.session_state.screen = "landing"
        st.rerun()
        return

    status = brief.get("status", "ok")

    # ── No route found ────────────────────────────────────────────────────────
    if status == "no_route_found":
        st.error(brief.get("message", "No route found matching your criteria."))
        for step in brief.get("suggested_next_steps", []):
            st.write(f"→ {step}")
        if st.button("Start over"):
            _reset()
        return

    # ── Pass closed — trailhead not accessible ────────────────────────────────
    if status == "pass_closed":
        pass_s = brief.get("pass_status", {})
        route  = brief.get("route", {})
        st.error(
            f"**{pass_s.get('pass_name', 'Access road')} is currently closed** — "
            f"the trailhead for {route.get('name', 'this route')} is not accessible.",
            icon="🚧",
        )
        if pass_s.get("road_condition"):
            st.write(f"**Road condition:** {pass_s['road_condition']}")
        if pass_s.get("restriction"):
            st.write(f"**Restriction:** {pass_s['restriction']}")
        st.write("**What to do:**")
        for step in brief.get("suggested_next_steps", []):
            st.write(f"→ {step}")
        if st.button("Start over"):
            _reset()
        return

    # ── Normal brief (ok or plan_b) ───────────────────────────────────────────
    route             = brief.get("route", {})
    risk              = brief.get("risk", {})
    itinerary         = brief.get("itinerary", {})
    conditions        = brief.get("conditions", {})
    community_reports = conditions.get("community_reports", {})
    gear_list         = brief.get("gear", [])
    gear_notes        = brief.get("gear_notes", "")

    overall_risk              = risk.get("overall_risk", "low")
    dominant                  = risk.get("dominant_factor")
    risk_label, r_color, r_bg = _RISK.get(overall_risk, _RISK["low"])

    # Per-day risk lookup: day number → risk level
    risk_by_day = {d["day"]: d["risk_level"] for d in risk.get("days", [])}

    # ── Header ────────────────────────────────────────────────────────────────
    col_title, col_back = st.columns([4, 1])
    with col_title:
        display_name = route.get("name", "")
        if status == "plan_b":
            plan_b = brief.get("plan_b", {})
            display_name = plan_b.get("alternate_route_name", display_name)
        st.markdown(f"## {display_name}")
    with col_back:
        if st.button("← New trip"):
            _reset()

    # ── Banners ───────────────────────────────────────────────────────────────
    if status == "plan_b":
        plan_b = brief.get("plan_b", {})
        st.info(
            f"**Plan B:** original route had high risk. "
            f"Switched to **{plan_b.get('alternate_route_name', 'alternate')}** — "
            f"{plan_b.get('reason_selected', '')}",
            icon="ℹ",
        )

    if route.get("_adhoc"):
        st.warning(
            "Waypoint coordinates are approximate "
            "(generated from Claude's training knowledge, not GPS data).",
            icon="⚠",
        )

    # ── Risk / rejection banner ────────────────────────────────────────────────
    if status == "no_viable_route":
        nvr     = brief.get("no_viable_route", {})
        nv_risk = nvr.get("overall_risk", "high")
        nv_dom  = nvr.get("dominant_factor", "")
        _, nv_col, nv_bg = _RISK.get(nv_risk, _RISK["high"])
        dom_str = f"  ·  Main concern: {nv_dom}" if nv_dom else ""
        st.markdown(
            f'<div style="background:{nv_bg};border-left:6px solid {nv_col};'
            f'border-radius:4px;padding:14px 20px;margin:12px 0 12px;">'
            f'<span style="font-size:1.1rem;font-weight:700;color:{nv_col};">⚠ Trip Not Recommended</span>'
            f'<span style="color:#6B7280;">{dom_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        # Per-condition warning blocks
        _rl  = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        def _warn_html(title: str, risk: str, detail: str) -> str:
            if not risk or _rl.get(risk, 0) < 1:
                return ""
            lbl, col, bg = _RISK.get(risk, _RISK["high"])
            return (
                f'<div style="background:{bg};border-left:4px solid {col};'
                f'border-radius:4px;padding:10px 16px;margin:8px 0;">'
                f'<b>{title}</b>&nbsp;&nbsp;&bull;&nbsp;&nbsp;{lbl}<br>'
                f'<span style="font-size:0.9rem;">{detail}</span>'
                f'</div>'
            )
        blocks = []
        weather = conditions.get("weather", {})
        alerts  = weather.get("alerts", [])
        w_days  = weather.get("days", [])
        if alerts:
            w_risk   = "high"
            headline = alerts[0].get("headline", alerts[0].get("event", ""))
            high_days = [d for d in w_days if _rl.get(d.get("risk_level", "low"), 0) >= 2]
            low_days  = [d for d in w_days if _rl.get(d.get("risk_level", "low"), 0) == 0]
            day_note  = ""
            if high_days:
                summaries = list(dict.fromkeys(d.get("summary", "") for d in high_days if d.get("summary")))
                day_note = f" {', '.join(summaries[:2])} on {len(high_days)} day(s)."
            if low_days:
                day_note += f" Conditions improve from day {w_days.index(low_days[0]) + 1}."
            w_detail = headline + day_note
        elif w_days:
            worst_w  = max(w_days, key=lambda d: _rl.get(d.get("risk_level", "low"), 0))
            w_risk   = worst_w.get("risk_level", "low")
            w_detail = worst_w.get("summary", "")
        else:
            w_risk, w_detail = "", ""
        blocks.append(_warn_html("Weather", w_risk, w_detail))

        a_days = conditions.get("aqi", {}).get("days", [])
        if a_days:
            worst_a  = max(a_days, key=lambda d: _rl.get(d.get("risk_level", "low"), 0))
            a_risk   = worst_a.get("risk_level", "low")
            aqis     = [d["aqi"] for d in a_days if d.get("aqi")]
            aqi_range = (f"AQI {min(aqis)}–{max(aqis)}" if len(aqis) > 1 else f"AQI {aqis[0]}" if aqis else "")
            a_detail = f"{worst_a.get('category', '')} ({aqi_range})." if aqi_range else worst_a.get("category", "")
        else:
            a_risk, a_detail = "", ""
        blocks.append(_warn_html("Air quality", a_risk, a_detail))

        fire     = conditions.get("fire", {})
        f_risk   = fire.get("risk_level", "")
        fires    = fire.get("active_fires_nearby", [])
        f_detail = (f"{fires[0]['name']}, {fires[0].get('distance_miles', '?')} miles from trailhead."
                    if fires else "Elevated fire danger in the area.")
        blocks.append(_warn_html("Fire", f_risk, f_detail))

        crossings = conditions.get("water", {}).get("crossings", [])
        if crossings:
            worst_c  = max(crossings, key=lambda c: _rl.get(c.get("risk_level", "low"), 0))
            c_risk   = worst_c.get("risk_level", "low")
            risky    = [c for c in crossings if _rl.get(c.get("risk_level", "low"), 0) >= 1]
            listed   = risky if risky else crossings
            c_parts  = [f"{c['name']} ({c.get('streamflow_cfs', '?')} CFS, {c.get('risk_level', '').capitalize()})" for c in listed]
            c_detail = " · ".join(c_parts) + ". Confirm gauge levels before entering the route."
            blocks.append(_warn_html("Water crossings", c_risk, c_detail))

        wildlife  = conditions.get("wildlife", {})
        wl_risk   = wildlife.get("risk_level", "")
        wl_detail = wildlife.get("notes", "")
        if not wl_detail:
            bears, cougars = wildlife.get("bear_count", 0), wildlife.get("cougar_count", 0)
            wl_parts = ([f"{bears} bear{'s' if bears != 1 else ''}"] if bears else []) + \
                       ([f"{cougars} cougar{'s' if cougars != 1 else ''}"] if cougars else [])
            wl_detail = f"{', '.join(wl_parts)} sighted in last 30 days." if wl_parts else ""
        if wl_detail:
            blocks.append(_warn_html("Wildlife", wl_risk, wl_detail))

        html = "".join(blocks)
        if html:
            st.markdown(html, unsafe_allow_html=True)

        # Conditions summary — route-specific explanation of why conditions are problematic
        nvr_summary = conditions.get("summary", "")
        if nvr_summary:
            st.info(nvr_summary, icon="ℹ")
    else:
        dominant_str = f"  ·  Main concern: {dominant}" if dominant else ""
        st.markdown(
            f'<div style="background:{r_bg};border-left:6px solid {r_color};'
            f'border-radius:4px;padding:14px 20px;margin:12px 0 20px;">'
            f'<span style="font-size:1.1rem;font-weight:700;color:{r_color};">'
            f'⬤ {risk_label} RISK</span>'
            f'<span style="color:#6B7280;"> {dominant_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Route summary ─────────────────────────────────────────────────────────
    with st.expander("Route details", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Miles",      route.get("total_miles", ""))
        c2.metric("Elev gain",  f"+{route.get('elevation_gain_ft', 0):,} ft")
        c3.metric("Difficulty", route.get("difficulty", ""))
        c4.metric("Type",       route.get("route_type", ""))

        res = route.get("reservations", {})
        if res:
            permit      = _PERMIT_LABELS.get(res.get("permit_type", "none"), "")
            parking     = res.get("parking_pass", "")
            permit_type = res.get("permit_type", "none")
            if "⚠" in permit:
                st.warning(f"Permit: {permit}", icon="⚠")
            else:
                st.caption(f"Permit: {permit}  ·  Parking: {parking}")
            # Only show notes when permit type requires booking/action (avoids repeating "no permit" info)
            if res.get("notes") and permit_type != "none":
                st.caption(res["notes"])

        if brief.get("days_adjusted"):
            st.caption(f"ℹ {brief['days_adjusted'].get('note', '')}")

        if route.get("description"):
            st.write(route["description"])

        # Risk summary badges — one per checked category
        _rl_ord = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        cat_risk = {"weather": "low", "aqi": "low", "fire": "low", "water": "low"}
        for d in risk.get("days", []):
            for cat, lvl in d.get("factors", {}).items():
                if _rl_ord.get(lvl, 0) > _rl_ord.get(cat_risk.get(cat, "low"), 0):
                    cat_risk[cat] = lvl
        cat_risk["wildlife"] = conditions.get("wildlife", {}).get("risk_level", "low")

        _CAT_LABELS = [
            ("weather",  "Weather"),
            ("aqi",      "Air Quality"),
            ("fire",     "Fire"),
            ("water",    "Water"),
            ("wildlife", "Wildlife"),
        ]
        st.markdown("")
        cols = st.columns(5)
        for col, (cat, lbl) in zip(cols, _CAT_LABELS):
            r = cat_risk.get(cat, "low")
            rlbl, color, bg = _RISK.get(r, _RISK["low"])
            col.markdown(
                f'<div style="background:{bg};border:1px solid {color};border-radius:6px;'
                f'padding:8px 4px;text-align:center;">'
                f'<div style="font-size:0.72rem;color:#6B7280;margin-bottom:3px;">{lbl}</div>'
                f'<div style="font-size:0.85rem;font-weight:700;color:{color};">{rlbl}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Route map ─────────────────────────────────────────────────────────────
    _show_route_map(route)

    # ── Conditions ────────────────────────────────────────────────────────────
    with st.expander("Current Conditions", expanded=True):
        if conditions.get("_historical"):
            st.caption("Typical seasonal averages · live forecasts available within 7 days of your trip")
        else:
            st.caption("Live data · Sources: NWS · AirNow · NIFC · USGS · iNaturalist · WSDOT")
        _rl = {"low": 0, "medium": 1, "high": 2}

        if conditions.get("_historical"):
            # ── Historical schema (typical_* keys) ────────────────────────────
            w = conditions.get("weather", {})
            a = conditions.get("aqi", {})
            f = conditions.get("fire", {})
            crossings_h = conditions.get("water", {}).get("crossings", [])
            if w.get("typical_high_f"):
                st.markdown(
                    f"- **Weather:** {w.get('typical_conditions', '')},"
                    f" {w.get('typical_low_f', '?')}–{w['typical_high_f']}°F"
                )
            if a.get("typical_category"):
                st.markdown(
                    f"- **Air quality:** {a['typical_category']}"
                    + (f" (AQI ~{a['typical_aqi']})" if a.get("typical_aqi") else "")
                )
            if f.get("typical_fire_risk"):
                st.markdown(f"- **Fire:** {f['typical_fire_risk']} risk typical")
            if crossings_h:
                flows = [c.get("typical_flow", "") for c in crossings_h if c.get("typical_flow")]
                if flows:
                    st.markdown(f"- **Water crossings:** typical flow {flows[0].lower()}")
            w_hist = conditions.get("wildlife", {})
            if w_hist.get("bear_activity_level"):
                st.markdown(f"- **Wildlife:** Bear activity {w_hist['bear_activity_level'].lower()} for this month")
            elif w_hist.get("note"):
                st.markdown(f"- **Wildlife:** {w_hist['note']}")
            # Road access — historical path: just note which pass gates the route
            pass_info = conditions.get("pass", {}) or {}
            if pass_info.get("_gated") and pass_info.get("pass_name"):
                st.markdown(f"- **Road access:** {pass_info['pass_name']} — seasonal status varies")

            notes = conditions.get("synthesis_notes") or conditions.get("summary", "")
            if notes:
                st.caption(notes)

        else:
            # ── Live schema (days[] + risk_level keys) ─────────────────────────
            # Weather — derive from per-day summaries + temp range
            w_days = conditions.get("weather", {}).get("days", [])
            if w_days:
                descs = list(dict.fromkeys(d.get("summary", "") for d in w_days if d.get("summary")))
                temps = [d["high_f"] for d in w_days if d.get("high_f")]
                temp_str = f", {min(temps)}–{max(temps)}°F" if temps else ""
                st.markdown(f"- **Weather:** {', '.join(descs[:3])}{temp_str} · *NWS*")

            # AQI — worst category + AQI range
            a_days = conditions.get("aqi", {}).get("days", [])
            if a_days:
                worst_a = max(a_days, key=lambda d: _rl.get(d.get("risk_level", "low"), 0))
                aqis = [d["aqi"] for d in a_days if d.get("aqi")]
                aqi_str = (f" (AQI {min(aqis)}–{max(aqis)})" if len(aqis) > 1
                           else f" (AQI {aqis[0]})" if aqis else "")
                st.markdown(f"- **Air quality:** {worst_a.get('category', 'Unknown')}{aqi_str} · *AirNow*")

            # Fire — risk level + nearest fire if present
            fire = conditions.get("fire", {})
            fire_risk = fire.get("risk_level", "")
            if fire_risk:
                fires = fire.get("active_fires_nearby", [])
                fire_note = (f" · {fires[0]['name']} ({fires[0].get('distance_miles', '?')} mi)"
                             if fires else "")
                st.markdown(f"- **Fire:** {fire_risk.capitalize()} risk{fire_note} · *NIFC*")

            # Water — crossing count + worst risk
            crossings = conditions.get("water", {}).get("crossings", [])
            if crossings:
                worst_c = max(crossings, key=lambda c: _rl.get(c.get("risk_level", "low"), 0))
                n = len(crossings)
                st.markdown(
                    f"- **Water crossings:** {n} crossing{'s' if n > 1 else ''}"
                    f" · highest: {worst_c.get('risk_level', 'low').capitalize()} · *USGS*"
                )

            # Wildlife — bear/cougar sightings
            wildlife = conditions.get("wildlife", {})
            w_risk = wildlife.get("risk_level", "")
            if w_risk and w_risk != "low":
                bears   = wildlife.get("bear_count", 0)
                cougars = wildlife.get("cougar_count", 0)
                parts = []
                if bears:
                    parts.append(f"{bears} bear{'s' if bears != 1 else ''}")
                if cougars:
                    parts.append(f"{cougars} cougar{'s' if cougars != 1 else ''}")
                st.markdown(
                    f"- **Wildlife:** {', '.join(parts)} sighted in last 30 days"
                    f" · {w_risk.capitalize()} risk · *iNaturalist*"
                )
            elif w_risk == "low":
                st.markdown("- **Wildlife:** No bear or cougar sightings in last 30 days · *iNaturalist*")

            # Road access — live pass status
            pass_info = conditions.get("pass", {}) or {}
            if pass_info.get("_gated") and pass_info.get("pass_name"):
                road_cond = pass_info.get("road_condition", "Open")
                restriction = pass_info.get("restriction")
                road_str = road_cond
                if restriction:
                    road_str += f" · {restriction}"
                st.markdown(f"- **Road access:** {pass_info['pass_name']} — {road_str} · *WSDOT*")

            # Conditions summary — always shown; explains what the data means for this route
            notes = conditions.get("summary") or conditions.get("synthesis_notes", "")
            if notes:
                st.caption(notes)
            elif not any([w_days, a_days, fire_risk, crossings]):
                st.caption("No conditions data available.")

        # ── Historical comparison (live trips only) ────────────────────────────
        ch = brief.get("conditions_historical")
        if ch and not conditions.get("_historical"):
            st.divider()
            st.caption("Typical conditions for this time of year")
            w = ch.get("weather", {})
            a = ch.get("aqi", {})
            f = ch.get("fire", {})
            wc = ch.get("water", {}).get("crossings", [])
            if w.get("typical_high_f"):
                st.markdown(
                    f"- **Weather:** {w.get('typical_conditions', '')},"
                    f" {w.get('typical_low_f', '?')}–{w['typical_high_f']}°F"
                )
            if a.get("typical_category"):
                st.markdown(
                    f"- **Air quality:** {a['typical_category']}"
                    + (f" (AQI ~{a['typical_aqi']})" if a.get("typical_aqi") else "")
                )
            if f.get("typical_fire_risk"):
                st.markdown(f"- **Fire:** {f['typical_fire_risk']} risk typical")
            if wc:
                flows = [c.get("typical_flow", "") for c in wc if c.get("typical_flow")]
                if flows:
                    st.markdown(f"- **Water crossings:** typical flow {flows[0].lower()}")
            if ch.get("summary"):
                st.caption(ch["summary"])

    # ── Community Reports ─────────────────────────────────────────────────────
    cr_posts = community_reports.get("posts", [])
    if cr_posts:
        with st.expander(f"Community Reports  ({len(cr_posts)} recent)", expanded=False):
            st.caption(
                "Unverified community trip reports from Reddit. "
                "Cross-reference with official conditions above."
            )
            for post in cr_posts:
                st.markdown(
                    f"**{post.get('title', '')}**  \n"
                    f"<span style='color:#888;font-size:0.85em'>"
                    f"{post.get('subreddit', '')} &nbsp;·&nbsp; {post.get('date', '')}"
                    f"</span>",
                    unsafe_allow_html=True,
                )
                snippet = post.get("snippet", "")
                if snippet:
                    st.write(snippet)
                url = post.get("url", "")
                if url and not community_reports.get("_mock"):
                    st.markdown(f"[View post]({url})")
                st.divider()

    # ── Itinerary ─────────────────────────────────────────────────────────────
    # Use Plan B itinerary if available, otherwise use original
    if status == "plan_b" and brief.get("plan_b", {}).get("itinerary"):
        days_to_show = brief["plan_b"]["itinerary"].get("days", [])
        avg_mpd      = brief["plan_b"]["itinerary"].get("miles_per_day_avg", 0)
        itin_summary = brief["plan_b"]["itinerary"].get("planner_notes", "")
    else:
        days_to_show = itinerary.get("days", [])
        avg_mpd      = itinerary.get("miles_per_day_avg", 0)
        itin_summary = itinerary.get("itinerary_summary", "")

    if days_to_show:
        st.markdown(f"#### Itinerary  ·  {avg_mpd:.1f} mi / day avg")

        for day in days_to_show:
            day_n      = day.get("day", "")
            day_risk   = risk_by_day.get(day_n, "low")
            d_label, d_color, d_bg = _RISK.get(day_risk, _RISK["low"])

            start  = day.get("start_waypoint", "")
            end    = day.get("end_waypoint", "")
            miles  = day.get("miles", 0)
            gain   = day.get("elevation_gain_ft", 0)
            highlights   = day.get("highlights", [])
            water_srcs   = day.get("water_sources", [])
            camp         = day.get("camp", "")
            description  = day.get("description", "")

            # Header + stats in the colored accent block
            st.markdown(
                f'<div style="border-left:4px solid {d_color};background:{d_bg};'
                f'border-radius:0 6px 6px 0;padding:12px 16px;margin:16px 0 4px;">'
                f'<strong>Day {day_n} &nbsp;·&nbsp; {day.get("date","")}</strong>'
                f'&nbsp;&nbsp;<span style="color:{d_color};font-size:0.8rem;'
                f'font-weight:600;">{d_label}</span><br/>'
                f'<span>{start} → {end} &nbsp;·&nbsp; '
                f'{miles} mi &nbsp;·&nbsp; +{gain:,} ft</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Details below the header
            if highlights:
                st.caption("Highlights: " + " · ".join(highlights))
            water_str = " · ".join(water_srcs) if water_srcs else "carry sufficient water"
            st.caption(f"Water: {water_str}")
            if camp:
                st.caption(f"Camp: {camp}")
            if description:
                st.write(description)

    # ── Gear ──────────────────────────────────────────────────────────────────
    if status not in ("no_viable_route",):
        if gear_list:
            with st.expander("What to Pack", expanded=True):
                for priority, label in (
                    ("required",    "Must-have"),
                    ("recommended", "Recommended"),
                    ("optional",    "Nice to have"),
                ):
                    items = [g for g in gear_list if g.get("priority") == priority]
                    if items:
                        st.markdown(f"**{label}**")
                        for g in items:
                            reason = f"  —  {g['reason']}" if g.get("reason") else ""
                            prefix = "✓" if priority == "required" else "◦"
                            st.write(f"{prefix}  {g['item']}{reason}")

                if gear_notes:
                    st.caption(gear_notes)
        else:
            if st.button("Get gear recommendations", type="secondary"):
                with st.spinner("Generating gear list…"):
                    _ctx = {
                        "selected_route": brief["route"],
                        "itinerary": brief["itinerary"],
                        "conditions": {
                            **brief["conditions"],
                            "synthesis_notes": brief["conditions"].get("summary", ""),
                        },
                        "user_input": st.session_state.user_input,
                        "reasoning_trace": [],
                    }
                    _result = gear_module.run(_ctx)
                st.session_state.brief["gear"] = _result.get("gear", [])
                st.session_state.brief["gear_notes"] = _result.get("gear_notes", "")
                st.rerun()

    st.download_button(
        "Export trip brief",
        data=_build_export(brief),
        file_name=f"trailops-{route.get('id', 'brief')}.txt",
        mime="text/plain",
    )

    # ── Next steps (no viable route only) ────────────────────────────────────
    if status == "no_viable_route":
        st.divider()
        st.markdown("#### What would you like to do?")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Change dates", use_container_width=True):
                st.session_state.brief = None
                st.session_state.intake_messages = []
                st.session_state.intake_system = None
                st.session_state.screen = "intake"
                st.session_state.user_input = {
                    k: v for k, v in st.session_state.get("user_input", {}).items()
                    if k != "dates"
                }
                st.rerun()
        with col2:
            if st.button("Pick a different route", use_container_width=True):
                st.session_state.brief = None
                st.session_state.screen = "route_selection"
                st.rerun()
        with col3:
            if st.button("Start over", use_container_width=True):
                _reset()

    # ── Ad-hoc route note ─────────────────────────────────────────────────────
    if route.get("_adhoc"):
        st.caption("Route added to your trail database for future trips.")

    # ── Q&A chat ──────────────────────────────────────────────────────────────
    st.divider()
    col_qa_title, col_qa_back = st.columns([4, 1])
    with col_qa_title:
        st.markdown("#### Ask a question about this trip")
    with col_qa_back:
        if st.button("← New trip", key="new_trip_bottom"):
            _reset()

    _qa_system = (
        "You are a knowledgeable trail advisor for TrailOps, an outdoor route planning system "
        "for the Pacific Northwest. The user has received a trip brief and may have follow-up "
        "questions about the route, conditions, risk, gear, itinerary, or anything else.\n\n"
        "Be conversational, warm, and concise. Write in plain prose — no markdown, no bullets, "
        "no bold. Answer from the trip brief data where possible. "
        "If asked about something not in the brief, draw on your knowledge of PNW hiking.\n\n"
        "NAVIGATION ACTIONS: If the user asks to change their trip dates, try different dates, "
        "or replan for another time, acknowledge their request and append exactly [ACTION:change_dates] "
        "at the very end of your response. If they ask to pick a different route or try another trail, "
        "append [ACTION:pick_route]. If they want to start over or plan a completely new trip, "
        "append [ACTION:start_over]. Only append one action tag per response, and only when the user "
        "is clearly requesting one of these navigation changes.\n\n"
        "TRIP BRIEF:\n"
        + json.dumps(
            {k: v for k, v in brief.items() if k != "reasoning_trace"},
            indent=2,
        )
    )

    for msg in st.session_state.qa_messages:
        avatar = "🏔" if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=avatar):
            st.write(msg["content"])

    if not st.session_state.qa_messages:
        with st.chat_message("assistant", avatar="🏔"):
            st.write(
                "Got questions about the route, conditions, gear, or itinerary? Ask away."
            )

    if qa_prompt := st.chat_input("Ask anything about this trip…"):
        with st.chat_message("user"):
            st.write(qa_prompt)
        st.session_state.qa_messages.append({"role": "user", "content": qa_prompt})

        with st.chat_message("assistant", avatar="🏔"):
            with st.spinner(""):
                try:
                    qa_reply = _claude_create(
                        model=_HAIKU_MODEL,
                        max_tokens=1024,
                        system=_qa_system,
                        messages=st.session_state.qa_messages,
                    )
                except Exception:
                    st.warning("The AI service is temporarily unavailable. Please try again in a moment.")
                    st.session_state.qa_messages.pop()
                    qa_reply = None
            if qa_reply:
                _action_match = re.search(r'\[ACTION:(change_dates|pick_route|start_over)\]', qa_reply)
                _clean_reply = re.sub(r'\[ACTION:[^\]]+\]', '', qa_reply).strip()
                st.write(_clean_reply)
                if _action_match:
                    st.session_state.qa_pending_action = _action_match.group(1)
        if qa_reply:
            _clean_reply = re.sub(r'\[ACTION:[^\]]+\]', '', qa_reply).strip()
            st.session_state.qa_messages.append(
                {"role": "assistant", "content": _clean_reply}
            )

    # ── Q&A pending action button ──────────────────────────────────────────────
    _pending = st.session_state.get("qa_pending_action")
    if _pending:
        _action_labels = {
            "change_dates": "Change dates",
            "pick_route":   "Pick a different route",
            "start_over":   "Start over",
        }
        if st.button(_action_labels.get(_pending, _pending), key="qa_action_btn"):
            st.session_state.qa_pending_action = None
            if _pending == "change_dates":
                st.session_state.brief = None
                st.session_state.intake_messages = []
                st.session_state.intake_system = None
                st.session_state.screen = "intake"
                st.session_state.user_input = {
                    k: v for k, v in st.session_state.get("user_input", {}).items()
                    if k != "dates"
                }
            elif _pending == "pick_route":
                st.session_state.brief = None
                st.session_state.screen = "route_selection"
            elif _pending == "start_over":
                _reset()
                return
            st.rerun()

    # ── Pipeline trace (dev) ───────────────────────────────────────────────────
    trace = brief.get("reasoning_trace")
    if trace:
        with st.expander("Pipeline trace", expanded=False):
            st.json(trace)


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data
def _load_geometry(route_id: str) -> list[list[float]]:
    """Load trail geometry from data/geometry/{route_id}.json. Cached per route_id."""
    geo_path = Path("data") / "geometry" / f"{route_id}.json"
    if geo_path.exists():
        return [[p["lat"], p["lon"]] for p in json.loads(geo_path.read_text())]
    return []


@st.cache_data
def _build_route_map_html(route_id: str, route_data_json: str) -> tuple[str, bool]:
    """
    Build folium map HTML for a route. Cached per route so construction only
    happens once per session — subsequent re-renders (Q&A, button clicks, etc.)
    skip the folium build entirely and serve the cached HTML string.
    """
    route   = json.loads(route_data_json)
    geo_pts = _load_geometry(route_id)
    has_geo = bool(geo_pts)
    coords  = geo_pts or [[w["lat"], w["lon"]] for w in route.get("waypoints", [])]

    if not coords:
        return "", False

    lats, lons = [c[0] for c in coords], [c[1] for c in coords]
    center = [(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2]
    span   = max(max(lats) - min(lats), max(lons) - min(lons))
    zoom   = 14 if span < 0.03 else 13 if span < 0.07 else 12 if span < 0.12 else 11 if span < 0.25 else 10 if span < 0.50 else 9
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap", prefer_canvas=True)

    folium.PolyLine(coords, color="#3B82F6", weight=3, opacity=0.85).add_to(m)

    for wp in route.get("waypoints", []):
        folium.CircleMarker(
            location=[wp["lat"], wp["lon"]],
            radius=5,
            color="#1D4ED8",
            fill=True,
            fill_color="#3B82F6",
            fill_opacity=0.9,
            popup=folium.Popup(
                f"<b>{wp['name']}</b><br>{wp.get('elevation_ft', 0):,} ft"
                f" &nbsp;·&nbsp; {wp.get('cumulative_miles', '')} mi",
                max_width=220,
            ),
            tooltip=wp["name"],
        ).add_to(m)

    for wc in route.get("water_crossings", []):
        folium.CircleMarker(
            location=[wc["lat"], wc["lon"]],
            radius=5,
            color="#0EA5E9",
            fill=True,
            fill_color="#38BDF8",
            fill_opacity=0.85,
            popup=folium.Popup(f"Water crossing: {wc['name']}", max_width=180),
            tooltip=wc["name"],
        ).add_to(m)

    th = route.get("trailhead", {})
    if th.get("lat") and th.get("lon"):
        folium.Marker(
            location=[th["lat"], th["lon"]],
            popup=folium.Popup(f"<b>Trailhead</b><br>{th.get('name', '')}", max_width=200),
            tooltip="Trailhead",
            icon=folium.Icon(color="green", icon="flag"),
        ).add_to(m)

    return m._repr_html_(), has_geo


def _show_route_map(route: dict) -> None:
    """Render the cached route map HTML inside a collapsed expander."""
    route_id = route.get("id", "")
    html, has_geo = _build_route_map_html(route_id, json.dumps(route, sort_keys=True))
    if not html:
        return
    source = "OSM trail geometry" if has_geo else "waypoint approximation"
    with st.expander("Route Map", expanded=False):
        _stc.html(html, height=420, scrolling=False)
        st.caption(f"Trail line from {source} · Click markers for details")


def _claude_create(**kwargs) -> str:
    """Call _client.messages.create with retry on 529 overload. Returns response text."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return _client.messages.create(**kwargs).content[0].text
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < max_retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            raise


def _reset() -> None:
    """Clear all session state and return to the landing screen."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def _build_export(brief: dict) -> str:
    """Build a plain-text export of the trip brief."""
    route      = brief.get("route", {})
    risk       = brief.get("risk", {})
    itinerary  = brief.get("itinerary", {})
    conditions = brief.get("conditions", {})
    gear_list  = brief.get("gear", [])

    overall   = risk.get("overall_risk", "low")
    dominant  = risk.get("dominant_factor", "")
    r_label   = _RISK.get(overall, _RISK["low"])[0]
    risk_by_day = {d["day"]: d["risk_level"] for d in risk.get("days", [])}

    lines = [
        f"TRAILOPS TRIP BRIEF — {route.get('name', '').upper()}",
        "=" * 60,
        "",
        f"Route:      {route.get('name','')}",
        f"Difficulty: {route.get('difficulty','')}  ·  {route.get('route_type','')}",
        f"Region:     {route.get('sub_region','')}",
        f"Distance:   {route.get('total_miles','')} miles  /  +{route.get('elevation_gain_ft',0):,} ft",
        "",
        f"OVERALL RISK: {r_label}" + (f"  ·  Main concern: {dominant}" if dominant else ""),
        "",
        "CONDITIONS",
        "-" * 40,
        conditions.get("summary", "(see individual condition sections)"),
        "",
        "ITINERARY",
        "-" * 40,
    ]

    for day in itinerary.get("days", []):
        day_n    = day.get("day", "")
        day_risk = risk_by_day.get(day_n, "low")
        d_label  = _RISK.get(day_risk, _RISK["low"])[0]
        lines.append(
            f"Day {day_n} ({day.get('date','')})  [{d_label}]"
        )
        lines.append(
            f"  {day.get('start_waypoint','')} → {day.get('end_waypoint','')}  "
            f"|  {day.get('miles',0)} mi  |  +{day.get('elevation_gain_ft',0):,} ft"
        )
        if day.get("highlights"):
            lines.append(f"  Highlights: {', '.join(day['highlights'])}")
        if day.get("water_sources"):
            lines.append(f"  Water:      {', '.join(day['water_sources'])}")
        lines.append(f"  Camp:       {day.get('camp','')}")
        lines.append("")

    lines += ["GEAR", "-" * 40]
    for priority in ("required", "recommended", "optional"):
        items = [g for g in gear_list if g.get("priority") == priority]
        if items:
            lines.append(f"{priority.upper()}:")
            for g in items:
                reason = f" — {g['reason']}" if g.get("reason") else ""
                lines.append(f"  - {g['item']}{reason}")
            lines.append("")

    lines += ["-" * 60, "Generated by TrailOps"]
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

main()
