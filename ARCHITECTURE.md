# TrailOps — Outdoor Route Finder
## Architecture & Design Decisions

**Stack:** Claude API directly (no LangGraph/CrewAI)
**Region:** Pacific Northwest
**Tone:** Performance (maximize elevation gain, scenery, challenge)

---

## Agent Hierarchy (3 levels)

```
Orchestrator                    ← deterministic; owns Trip Context; spawns all top-level agents
├── Intelligence Agent          ← spawned by Orchestrator, runs in parallel with Day Planner
│   ├── [tool] get_weather      → NOAA/NWS API
│   ├── [tool] get_air_quality  → AirNow API
│   ├── [tool] get_fire_data    → NIFC API
│   └── [tool] get_streamflow   → USGS API
├── Day Planner                 ← spawned by Orchestrator, runs in parallel with Intelligence
│                               NOTE: lives in sub_agents/ for code organization only;
│                               it is a sibling of Intelligence Agent, NOT a child of it
└── Assessment Agent            ← spawned by Orchestrator after BOTH above complete
    ├── Gear Sub-agent          ← spawned inside Assessment; needs Intelligence conditions
    ├── Risk Scorer             ← deterministic code, not a Claude call
    ├── [conditional] Replanner ← spawned inside Assessment only if risk >= medium (max 1)
    └── [conditional] Plan B    ← spawned inside Assessment only if Replanner fails (max 1)
```

**Tool use pattern (Intelligence Agent):**
- Intelligence Agent is a single Claude API call with all 4 tools defined in the request
- Claude decides to call all 4 tools in parallel using parallel tool use
- Python executes the tool functions and returns results to Claude
- Claude synthesizes results into the Conditions Schema and writes to Trip Context
- No separate sub-agent Claude calls for data gathering — tools replace them

---

## UI Layer

**Primary:** Streamlit chat UI (`streamlit_app.py`) — also kept as terminal input (`ui.py`) for smoke tests. Input layer is decoupled from the Orchestrator; swapping UI requires no agent changes.

**Flow:**
1. User enters free-form text describing their trip
2. UI constructs a Claude API call (Haiku) with two parts:
   - **System prompt** — instructs Claude to extract required fields, infer approximate dates from vague phrasing ("early March" → March 5th), ask one follow-up if anything critical is missing, and return JSON when complete
   - **User message** — the user's raw text
3. If required fields are missing, Claude asks a follow-up question (loop back to step 1)
4. Once all required fields are present, Claude returns a structured JSON object
5. UI detects valid JSON and hands it off to the Orchestrator

**Required fields:**
| Field | Type | Default |
|-------|------|---------|
| Dates | date range | — (must ask; vague phrases inferred, not asked about) |
| Difficulty | Easy / Moderate / Hard / Epic | — (must ask) |
| Trip length | number of days | **1 day** |

**Optional fields:**
| Field | Type | Notes |
|-------|------|-------|
| Route type | thru / out-and-back / loop | Never asked; only set if user mentions it; `null` = no preference (no scoring penalty) |
| Sub-region | e.g. North Cascades, Olympics, South Cascades | Narrows candidates if provided |

**Derived fields (not asked):**
| Field | Derived from |
|-------|-------------|
| Total mileage range | trip_length × miles_per_day (from difficulty) |
| Season | start date |

**Difficulty mapping (internal):**
| Difficulty | Miles/day | Elevation preference |
|------------|-----------|----------------------|
| Easy | 8–10 | minimal |
| Moderate | 10–12 | moderate |
| Hard | 12–16 | high |
| Epic | 16+ | maximum |

Region is locked to PNW for now (implicit, not asked).

---

## Data Flow

1. User inputs free-form text via UI layer
2. Claude (Haiku) parses to structured input → populates Trip Context (user_input fields)
3. Orchestrator selects route from `routes.json` → adds to Trip Context
4. Orchestrator spawns Intelligence Agent + Day Planner in parallel
5. **Intelligence Agent — forecast horizon branch:**
   - If trip start ≤ 7 days out: single Claude (Sonnet) call with 4 tools defined → Claude calls all 4 tools in parallel → Python executes each tool → Claude synthesizes results → writes Conditions to Trip Context
   - If trip start > 7 days out: single Claude (Haiku) call for seasonal averages (skips live APIs) → writes Conditions with `_historical: true` flag
6. Day Planner builds initial itinerary from route data only → writes to Trip Context
7. Assessment Agent runs after **both** step 5 and 6 complete; emits progress updates via callback
8. Assessment spawns Gear Sub-agent (Haiku; uses conditions) → writes gear list to Trip Context
9. Risk Scorer (deterministic code) scores each day → writes risk to Trip Context
10. If any day risk > threshold → spawn Replanner (Haiku, max 1 attempt)
11. Replanner adjusts itinerary → Risk Scorer re-validates
12. If still failing → spawn Plan B Sub-agent (alternate route, same region, max 1 attempt)
13. If Plan B also fails → return "no viable route" response with explanation
14. Brief Reviewer (Haiku) cleans prose fields in the assembled brief
15. Orchestrator returns final trip brief; UI renders it (Sonnet call for prose formatting)

---

## Project Structure

```
outdoor-route-finder/
├── ARCHITECTURE.md             ← this file
├── config.json                 ← API endpoints, thresholds, Claude model config
├── .env.example                ← API key template
├── ui.py                       ← terminal input (kept for CLI/smoke tests)
├── streamlit_app.py            ← primary UI (chat intake + trip brief display)
├── orchestrator.py
├── agents/
│   ├── intelligence_agent.py   ← single Claude call with 4 tools defined
│   ├── assessment_agent.py
│   ├── brief_reviewer.py       ← cleans AI-generated prose before display (Haiku)
│   └── sub_agents/
│       ├── day_planner.py      ← runs parallel with Intelligence
│       ├── gear.py             ← runs inside Assessment (needs conditions)
│       ├── replanner.py
│       └── plan_b.py
├── risk_scorer.py              ← deterministic code, not an agent
├── tools/                      # tool definitions + execution functions
│   ├── tool_definitions.py     ← tool schemas passed to Claude API
│   ├── nws.py                  ← executes when Claude calls get_weather
│   ├── airnow.py               ← executes when Claude calls get_air_quality
│   ├── usgs.py                 ← executes when Claude calls get_streamflow
│   └── nifc.py                 ← executes when Claude calls get_fire_data
├── data/
│   ├── routes.json             # PNW route catalog (15 routes)
│   └── scenarios/              # 3 pre-built test cases
└── output/                     # generated trip briefs
```

---

## Trip Context Object

A single shared object passed through the entire pipeline. Each agent reads from it and writes its outputs back to it. The Orchestrator owns it.

```json
{
  "user_input": {
    "dates": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
    "difficulty": "Easy|Moderate|Hard|Epic",
    "trip_length_days": 1,
    "route_type": "thru|out-and-back|loop|null",
    "sub_region": null
  },
  "selected_route": {},
  "conditions": {},
  "itinerary": {},
  "gear": [],
  "risk": {},
  "plan_b": null,
  "no_viable_route": null,
  "reasoning_trace": []
}
```

---

## Conditions Schema (Intelligence Agent output)

Structured JSON written to Trip Context after Intelligence Agent synthesizes all 4 sub-agents:

```json
{
  "weather": {
    "days": [
      {"date": "YYYY-MM-DD", "summary": "...", "precip_chance": 0.1,
       "high_f": 72, "low_f": 48, "wind_mph": 10, "risk_level": "low|medium|high"}
    ],
    "alerts": []
  },
  "aqi": {
    "days": [
      {"date": "YYYY-MM-DD", "aqi": 45, "category": "Good", "risk_level": "low|medium|high"}
    ]
  },
  "fire": {
    "active_fires_nearby": [],
    "closest_fire_miles": null,
    "risk_level": "low|medium|high"
  },
  "water": {
    "crossings": [
      {"name": "...", "streamflow_cfs": 120, "risk_level": "low|medium|high"}
    ]
  },
  "synthesis_notes": "...",
  "_historical": false
}
```

`_historical: true` is set when trip start is > 7 days out and live API data is unavailable. The flag is forwarded through `_assemble_brief()` so the UI can display a "Typical seasonal averages" notice instead of "Live data".

---

## Risk Scoring (deterministic code, not a Claude call)

```
risk_score per day = max(weather_risk, aqi_risk, fire_risk, water_risk)
where: low = 0, medium = 1, high = 2

overall_risk = max(all daily scores)
replanning triggered if overall_risk >= 1 (medium)
```

---

## Replanning Exit Conditions

```
Replanner attempt:  max 1
  → if resolved: proceed to trip brief
  → if not resolved: spawn Plan B (max 1 attempt)
    → if Plan B resolved: proceed to trip brief
    → if Plan B fails: return no_viable_route response

no_viable_route response includes:
  - reason (which condition triggered failure)
  - what was attempted (replanner, plan B)
  - suggested next steps for user
```

---

## API Resilience

- **Timeout:** 10 seconds per API call
- **Retries:** 2 attempts with exponential backoff (1s, 2s)
- **On persistent failure:** auto-fallback to mock data, flag in reasoning trace
- **Mock strategy:**
  - `USE_MOCK=true` in `.env` forces all tools to use mock data (for offline dev/demo)
  - Auto-fallback activates silently on API failure — system continues, trace records it
  - Each mock returns realistic data tuned to its test scenario

---

## Performance Tone Calibration

- Miles/day target: 12–16
- AQI threshold: <150 acceptable (vs <100 for safety-first)
- Weather risk only triggers replanning at high confidence
- Gear recommendations: technical (trail runners, cuben fiber, etc.)
- Route preference: max elevation gain, exposure, views — not the easy option

---

## External APIs

| API | Purpose | URL |
|-----|---------|-----|
| NOAA/NWS | Forecasts + alerts | https://api.weather.gov |
| EPA AirNow | AQI observations + forecasts | https://docs.airnowapi.org |
| USGS Water | Streamflow / river crossing risk | https://api.waterdata.usgs.gov |
| NIFC | Active wildfire perimeters | https://data-nifc.opendata.arcgis.com |

All APIs are free. Each tool wrapper lives in `tools/` and has a mock fallback for testing.

## Route Data Sources (for populating routes.json)

| API | Purpose | URL | Key Required |
|-----|---------|-----|-------------|
| Overpass API | Trail geometry (lat/lon waypoints) | https://overpass-api.de/api/interpreter | No |
| Open Topo Data | Elevation per waypoint (USGS NED 10m) | https://api.opentopodata.org/v1/ned10m | No |

**Workflow:**
1. Query Overpass by trail name → returns lat/lon waypoint arrays
2. POST waypoints to Open Topo Data → returns elevation per point (meters)
3. Calculate total elevation gain from profile
4. Hardcode results into `routes.json` (static file, not queried at runtime)

---

## Test Scenarios (3 pre-built)

| # | Route | Condition Trigger | Agent Path |
|---|-------|-------------------|------------|
| 1 | Goat Rocks — Snowgrass Flat loop | Clean conditions | Straight through, no replanning |
| 2 | Enchantments traverse | High AQI/smoke | Replanner adjusts days |
| 3 | Olympic High Divide | Weather + river crossing risk | Plan B alternate route |

Each scenario is designed to exercise a different conditional sub-agent path.

---

## Build Order

1. `data/routes.json` — 5 PNW routes with coordinates, mileage, elevation, waypoints
2. `tools/` — 4 API wrappers with mock fallbacks
3. Intelligence Agent + 4 data sub-agents
4. Planning Agent + Day Planner + Gear sub-agents
5. Assessment Agent + Risk Scorer sub-agent
6. Orchestrator wires all agents → trip brief output
7. Replanner + Plan B sub-agents (conditional spawn logic)

---

## Output Format (Trip Brief)

Each run produces:
- Day-by-day itinerary with mileage and elevation
- Risk assessment per day (weather / AQI / fire / water)
- Gear delta list with reasons
- Plan B option (if triggered)
- Reasoning trace: which tools were called, what was found, what was decided

---

## Key Design Decisions

- **Claude API directly** — no LangGraph or CrewAI; full control over agent logic
- **Decoupled UI layer** — UI only produces structured input; Orchestrator never touches UI code
- **Difficulty abstraction** — users pick Easy/Moderate/Hard/Epic; system maps to mileage/elevation internally
- **Shared Trip Context** — single object passed through pipeline; each agent reads and writes to it
- **Tool use for data gathering** — Intelligence Agent uses Claude's tool use (parallel tool calls) instead of separate sub-agent Claude calls; simpler and more natural
- **Parallel spawning** — Intelligence + Day Planner run concurrently; Intelligence tools run concurrently within Claude's tool use loop
- **Gear after conditions** — Gear Sub-agent runs inside Assessment after Intelligence completes, not before
- **Risk Scorer is code** — deterministic scoring (not a Claude call) saves latency and cost
- **Bounded replanning** — max 1 Replanner attempt + max 1 Plan B attempt; failure returns structured "no viable route" response
- **Conditional sub-agents** — Replanner and Plan B only spawn when needed
- **API resilience** — 10s timeout, 2 retries, auto-fallback to mock on failure
- **Mock fallbacks** — `USE_MOCK=true` forces mocks; auto-fallback activates on API failure
- **Reasoning trace** — every agent logs its decisions and evidence citations
- **Model tier split** — Sonnet for high-stakes reasoning (Intelligence tool loop, Day Planner, brief rendering); Haiku for all other calls (intake, Q&A, route classification, historical conditions, gear, replanner, brief reviewer); configured in `config.json` as `model` and `haiku_model`
- **Forecast horizon** — Intelligence Agent checks days until trip at runtime; > 7 days skips live APIs and calls a single Haiku call for seasonal averages, setting `_historical: true` on the conditions object
- **route_type is optional** — never asked during intake; `null` means no preference; scoring and rationale both skip type matching when null
- **Progress callback** — `orchestrator.run()` and `assessment_agent.run()` accept `progress_cb=None`; called at sequential milestones only (NOT from ThreadPoolExecutor workers — Streamlit cannot write from non-main threads)
- **Brief rendering** — final trip brief prose is rendered by Claude (Sonnet) in the UI, not a Python template; Brief Reviewer (Haiku) cleans AI-generated prose fields before display
