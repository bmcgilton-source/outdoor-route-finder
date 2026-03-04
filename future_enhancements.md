# TrailOps — Future Enhancements

## Quality & Reliability Improvements

### Upgrade Intake Agent to Sonnet
The intake agent currently uses Haiku, which occasionally fuzzy-matches wrong trails, asks
questions it shouldn't (difficulty, route type for named trails), and ignores prompt rules.
Switching to Sonnet for the intake conversation eliminates most of these issues at ~$0.01/session.

**Change:** In `streamlit_app.py`, replace `_HAIKU_MODEL` with `_SONNET_MODEL` for the
intake `_claude_create` call.

---

### Validate Ad-Hoc Route Name After Generation
When `_generate_adhoc_route` succeeds but Claude returns data for the wrong trail (hallucination),
the pipeline plans a completely different hike than the one requested. Fix: after generation,
verify that the returned route name contains at least one word from the requested trail name.
If not, treat it as a failure and return None.

---

### Retry on JSON Parse Failure (Ad-Hoc Generation)
If `_generate_adhoc_route` returns truncated or malformed JSON, retry once with a note to the
model to return only the JSON object. One retry recovers most transient failures without
significantly increasing latency.

---

### Persist Ad-Hoc Routes to GitHub via API
On Streamlit Cloud, writes to `routes.json` are ephemeral — the container resets on restart.
Fix: after a successful ad-hoc generation, commit the new route to the repo via the GitHub
Contents API (`PUT /repos/{owner}/{repo}/contents/data/routes.json`). Requires a GitHub PAT
with `contents:write` scope stored in Streamlit secrets.

**Complexity:** Medium — need to base64-encode the file, include the current file SHA,
handle concurrent writes (unlikely but possible). Worth doing once the route catalog is
actively growing from user searches.

---

### Smoke Tests for Intake + Pipeline
No automated tests exist — bugs are discovered in production. Add a `tests/` directory with:
- Intake JSON output tests: mock Claude responses, verify correct `route_id`/`requested_trail`
  parsing for a handful of known inputs
- Pipeline smoke tests: run each mock scenario (1–4) and assert the brief `status` field is correct
- Run on push via GitHub Actions

---

## Campsite Data (Overpass API)
Add a `campsites` array to each route in `routes.json`, populated from OSM via Overpass API
(`tourism=camp_site` + `backcountry=yes` within the route bounding box), with cumulative mileage
calculated by snapping each campsite to the nearest point on the route geometry.

**Why this matters:** Without explicit campsite data, the Replanner cannot meaningfully adjust an
itinerary. Replanning works by shifting which nights are spent where — but if the system doesn't
know where designated camps are, it can't propose valid alternatives. Trip length adjustment is
not a viable replanning strategy (it changes the user's trip, not the risk). Campsite data is a
prerequisite for Replanner to function as intended.

**Implementation:**
1. At route-build time, query Overpass for campsites within bounding box
2. Snap each result to route geometry to derive cumulative mileage
3. Store as `campsites: [{name, lat, lon, cumulative_miles}]` in routes.json
4. Update Day Planner prompt to assign camp from the `campsites` list by mileage range
5. Update Replanner prompt to shift camp assignments using the same list

**Caveats:** OSM coverage in PNW is good for popular trails, patchy for remote ones. Manually
review and supplement Overpass results per route. Consider Recreation.gov API for permit
availability data as a follow-on.

---

## Gear Weight Calculator
Extend the gear section with an opt-in pack weight calculator. User enters a target base weight;
system allocates a budget across gear categories and suggests items that fit within each
allocation. Conditions-flagged items (e.g. trekking poles for a river ford) are locked and
non-negotiable — budget adjusts around them.

Full design spec in `UX_CONSIDERATIONS.md`.

---

## React + FastAPI Frontend
Replace Streamlit with a React frontend and FastAPI backend for full design control, standard
web deployment, and production-ready streaming progress via SSE.

**Migration trigger:** When Streamlit limitations become real — specifically the loading progress
screen, custom risk styling, and mobile layout.

Full design spec (API endpoints, SSE architecture, session state) in `UX_CONSIDERATIONS.md`.

---

## Proactive Trip Alerts
When a saved trip is within 7 days, notify the user that conditions have changed and re-run
the risk assessment. Requires saved trips, user identity, and a background scheduler.

**Dependencies:** Server deployment + multi-user support. Design as a second-phase feature.

---

## Multi-User Support
Multiple users with separate saved trips, preferences, and alert settings. Natural complement
to server deployment and Trip Alerts.

---

## Saved Trips
Allow users to save a completed trip brief and retrieve it in a future session.

**Why this matters:** Currently all state is in-memory and lost when the session ends. Saving
trips enables the Proactive Alerts feature (re-run risk assessment when trip is within 7 days)
and multi-user support. Also useful on its own — users want to reference their plan without
re-running the pipeline.

**Key decisions:**
- Storage: SQLite for single-user local, Postgres/Redis for multi-user server deployment
- Identity: anonymous saved trips (device-local) vs. authenticated user account
- What to save: the full trip brief dict + user_input + timestamp
- UI: "My Trips" section on landing page; load brief directly into the brief screen

**Dependencies:** Pairs naturally with Proactive Alerts and Multi-User Support — design together.

---

## Routes Database Migration (SQLite or Postgres)
Migrate `routes.json` to a database when any of these become true:
- Ad-hoc route writes create race conditions under concurrent users
- Route catalog grows large enough to warrant indexed queries
- Horizontal scaling requires a shared data store

Not needed at current scale (15-1500 routes, single instance).

---

## Route Pre-Filter for Intake (Fuzzy Match + Short-List)
Currently the intake prompt injects a compact one-line summary of every route in the catalog
so Claude (Haiku) can match the user's request to a route. This works fine at 15 routes but
degrades as the catalog grows.

**When this becomes a problem:**
- ~50-100 routes: the injected list becomes a wall of text; fuzzy matching by Claude gets
  unreliable (wrong route selected, missed regional matches)
- ~200+ routes: token cost per intake call becomes meaningful — you're paying to process the
  full catalog on every session just to pick one route

**Fix:** Add a Python pre-filter step before the intake Claude call. Use `rapidfuzz` (or
similar) to fuzzy-match the user's input against route names, regions, and tags. Return the
top 5-10 candidates. The intake prompt then only sees those candidates — Claude's job becomes
selection from a short list, not needle-in-a-haystack search. More reliable and cheaper.

**Switch point:** Around 50-100 routes. Not urgent at current scale.

---

## Route Imagery (Mapbox + Flickr)
Show visual context for each route: a satellite map thumbnail and real trail photos.

**Two data sources:**
- **Mapbox Static Images API** — generates a static satellite/terrain map image with the route
  overlaid as a polyline. Already have all inputs: bounding box, waypoint coordinates. Free
  tier covers low-traffic usage.
- **Flickr API** — query by bounding box + tags (`hiking`, `trail`) to return geotagged user
  photos of the area. Free, good coverage of popular PNW trails. Less consistent for remote
  routes.

**Where to show it:** Route options screen (thumbnail per route) and trip brief header
(satellite map + 2-3 scenery photos).

**What not to use:** AllTrails and WTA have rich photo libraries but no public API — scraping
is ToS risk. Unsplash is free but hit-or-miss for specific trails.

---

## "What's Good Right Now?" — Conditions-First Discovery
Alternate entry point on the landing page alongside "Plan my trip." Inverts the current flow:
instead of user → parameters → route, it's conditions → filtered routes → user picks.

**User provides:** only dates + difficulty preference (or nothing — just "this weekend")

**System behavior:** Runs the Intelligence Agent across all routes in parallel (or a
lightweight conditions-only scan), filters out high-risk ones, and surfaces what's actually
in good shape right now.

**Output:** A ranked "conditions board" — each route with green/amber/red status and a
one-line reason (e.g. "Clear skies, no permits needed, low water"). Card grid, not a chat —
browsable, not conversational. Selecting a route drops into the normal planning flow.

**Why this matters:** "I have a free weekend, what should I do?" is a very common use case
that the current flow doesn't support at all.

---

## Trail Conditions APIs (SNOTEL, NWAC, WA DOT, USFS GIS)
Four free APIs that address the gap between weather data and actual trail passability. All
integrate as new parallel tool calls in the Intelligence Agent alongside existing NWS/AirNow/
USGS/NIFC tools.

**SNOTEL (NRCS — Natural Resources Conservation Service)**
Snowpack monitoring stations throughout the Cascades; free REST API. Query nearest station(s)
to route waypoints by lat/lng. Key data: snow water equivalent (SWE), snow depth, current vs.
historical average. Use case: infer whether high routes are snow-free — if Goat Ridge high
point is 7,400 ft and SWE is above normal, flag as likely snow-covered → recommend
microspikes, adjust risk score.

**NWAC (Northwest Avalanche Center)**
Avalanche forecasts + snow conditions for Cascade forecast zones; free JSON feed. Query by
zone (e.g. "Olympics", "West Slopes North"). Key data: danger rating, problem types, travel
advice. Primary signal for alpine route safety in shoulder season (May-Jul, Oct-Nov); feeds
Assessment Agent risk score and gear sub-agent (beacon/probe/shovel).

**Washington DOT — Mountain Pass Reports**
Real-time road conditions for mountain passes; free, structured data. Covers Stevens,
Snoqualmie, White Pass, North Cascades Highway, etc. Key data: road open/closed, chain
requirements, traction advisory. Use case: trailhead access gate — if the access road or
nearest pass is closed, the trip is a non-starter. Should run early in the pipeline as a
hard gate before the full Intelligence Agent tool suite.

**USFS GIS — Road and Trail Closures**
US Forest Service publishes closure data via GIS REST services; free. Covers fire perimeters,
seasonal gate closures, restoration closures. Data quality varies by forest district — more
reliable for fire/seasonal closures than real-time trail conditions. Lower priority than the
above three due to data inconsistency.

**Integration notes:**
- SNOTEL + NWAC feed the risk scorer (new `snow_conditions` risk factor)
- WA DOT acts as a pre-flight gate — closed pass = bail early, skip full pipeline
- Display in brief: "Trail conditions" section distinct from "Weather" section
- All are official data (same trust tier as NWS/USGS) — no community-report caveat needed

---

## Ad-Hoc Route Generation — Hybrid (Overpass + Open Topo Data)
Upgrade the Claude-only ad-hoc route generation with accurate geodata from real APIs.

**Current state:** `_generate_adhoc_route` in `orchestrator.py` uses Claude's training
knowledge to generate route JSON (waypoints, water sources, reservations). Coordinates are
approximate (~100m accuracy). Generated routes are flagged with `_adhoc: true`.

**Hybrid upgrade:**
1. **Overpass API** — query trail geometry by name; returns accurate lat/lon. Already used
   to build `routes.json` (same tooling reused here).
2. **Open Topo Data** — fill in `elevation_ft` per waypoint via batch elevation query.
   Already used in the original routes.json build process.
3. **Claude still handles** non-geodata fields: description, difficulty, season,
   water_sources, reservations/permit info.

**Architecture:** New `tools/route_lookup.py` with `overpass_trail_waypoints(name)` and
`opentopo_elevations(waypoints)`. `_generate_adhoc_route` calls these before the Claude call,
passes real coordinates into the Claude prompt. Fallback: if Overpass returns no results,
fall back to the current Claude-only path.

**Effort:** ~1 day: route_lookup.py + orchestrator wiring + test against 2-3 known trails.

---

## Trip Report Ingestion (Reddit + Web Search)
Pull recent hiker-submitted trip reports to supplement API conditions data. APIs tell you what
the weather was — trip reports tell you whether the trail is actually passable right now (snow
on the pass, washed-out bridge, bug situation, etc.).

**Sources:**
- **Reddit API (PRAW)** — r/PNWhiking, r/WashingtonHiking, r/Ultralight. Free read-only
  access. Search by trail name + recent date filter. Most reliable free source of current
  conditions from actual hikers.
- **Google Custom Search API** — broad web search scoped to known trip report sites (WTA,
  hiking blogs). Returns links + snippets without scraping the sites directly.
- **WTA trip reports** — best source for PNW but no public API; scraping is ToS risk.

**Where it fits in the pipeline:** New tool in the Intelligence Agent's tool set. Claude
already synthesizes 4 API sources — trip reports become a 5th. Claude extracts conditions
signals (snow depth, trail damage, water levels, recent hazards) from unstructured text and
folds them into the Conditions output.

**Why this matters:** APIs have a reporting lag and don't capture ground truth. A trip report
from 3 days ago saying "knee-deep snow at the pass" is more actionable than a forecast model.
This is especially valuable for shoulder-season trips where conditions are highly variable.

---

## Show Original Itinerary When Replanning Changes the Plan
When the Replanner adjusts an itinerary or Plan B switches to a different route, show users
what the original plan looked like so they can understand what changed and why.

**What it looks like:**
- A collapsed "Originally planned" section on the trip brief page showing the pre-replan itinerary
- For Plan B: side-by-side or sequential display of original route vs. alternate route
- Clear labeling of what was changed and the reason (e.g. "Day 2 camp moved to avoid high-risk
  river crossing")

**Why this matters:** Currently replanning is invisible. Users see the final plan but have no
visibility into what the system changed or why. Transparency builds trust and helps users decide
whether to accept the modified plan or start over.

**Implementation notes:**
- Snapshot `trip_context["itinerary"]` as `trip_context["itinerary_original"]` before the
  Replanner runs in `assessment_agent.py`
- Include `itinerary_original` in the assembled brief when replanning occurred
- UI: collapsed expander "View original itinerary" below the active itinerary
- For Plan B: the original route data is already in `trip_context["selected_route"]` —
  include it in the Plan B brief alongside the alternate route

---

## Server Deployment
Move the app from local-only to a hosted, publicly accessible service.

**Why this matters:** Currently the app runs on a single developer machine. Server deployment
is a hard prerequisite for Proactive Trip Alerts (needs a background scheduler), Multi-User
Support (needs shared state), and the React/FastAPI migration (needs a real server). Without
it, those features can't ship.

**Phase 1 — Streamlit Community Cloud (do this first)**
Free hosting directly from a GitHub repo. No Docker, no CI/CD config, no server management.
Push to main → auto-deploys. Secrets managed in the Streamlit Cloud dashboard (replaces .env).
Limitations: single instance, no background tasks, app sleeps after inactivity on free tier.
This covers 90% of the value for near-zero effort.

**Phase 2 — Containerized deployment (if/when Streamlit Cloud hits a ceiling)**
Render, Fly.io, or Railway for containerized Streamlit. Needed when: background scheduler
(Proactive Alerts), always-on (no sleep), or horizontal scaling. Add GitHub Actions CI/CD
at this point — on push to main, run smoke tests, build image, deploy.

**Sequencing:** Streamlit Community Cloud first. React/FastAPI migration and multi-user
support layer on top of Phase 2 infra when those features are ready.
