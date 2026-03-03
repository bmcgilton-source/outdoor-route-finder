# TrailOps — UX Considerations

## Status
Design phase. Terminal MVP built and smoke-tested. Streamlit UI is next step.

---

## Base UI Design — Streamlit Web App

### Design Principles

| Principle | Application |
|---|---|
| Progressive disclosure | Reveal one step at a time — don't show the full pipeline |
| Outdoor aesthetic | Earthy greens, slate blues, warm stone tones — not a tech dashboard |
| Risk is primary | Risk level is the most important output — make it impossible to miss |
| Conversational intake | Chat UI, not a 6-field form |
| Scannable brief | Break trip brief into visual blocks, not a wall of prose |

### Screen Flow

```
Landing --> Intake Chat --> Route Cards --> Planning (loading) --> Trip Brief --> Q&A Chat
                                                  |
                                           (No route found)
                                           (No viable route)
```

---

### Screen 1 — Landing / Home

```
+---------------------------------------------------------------------+
|                                                                     |
|                    ^  TRAILOPS                                      |
|              Pacific Northwest Route Planner                        |
|                                                                     |
|    +-------------------------------------------------------------+  |
|    |  Live weather  Fire & smoke  Water crossing risk            |  |
|    |  AI-planned itineraries  Gear lists  Plan B routes          |  |
|    +-------------------------------------------------------------+  |
|                                                                     |
|                  [ Plan my trip  -> ]                               |
|                                                                     |
|    15 routes  *  5 regions  *  Easy to Epic difficulty             |
|                                                                     |
+---------------------------------------------------------------------+
```

- Muted hero image: alpine meadow, low saturation. Text legible over it.
- Single primary CTA. Nothing else to click.
- Feature lines build confidence that real data powers the app.

---

### Screen 2 — Intake Chat

```
+---------------------------------------------------------------------+
| <- TrailOps                                             PNW         |
+---------------------------------------------------------------------+
|                                                                     |
|  [ TrailOps ]                                                       |
|  Hey! Tell me about your trip. Where are you thinking,              |
|  and when are you planning to go?                                   |
|                                                                     |
|              [ Goat Rocks, first weekend of August, 2 days ]        |
|                                                                     |
|  [ TrailOps ]                                                       |
|  Perfect. Goat Rocks in August is a classic. Just to make          |
|  sure I plan the right pace -- would you call this a hard           |
|  push or more of a relaxed backpack?                                |
|                                                                     |
|  [ Hard push ]  [ Relaxed / Moderate ]   <- quick-reply chips       |
|                                                                     |
+---------------------------------------------------------------------+
|  Message TrailOps...                                          [->]  |
+---------------------------------------------------------------------+
```

- TrailOps bubbles: left, dark forest green, white text.
- User bubbles: right, warm stone, dark text.
- **Quick-reply chips** appear contextually for difficulty, route type, region.
  Free text always works too — chips just reduce friction.
- One question per turn. No forms, no fields.

---

### Screen 3 — Route Selection Cards

```
+---------------------------------------------------------------------+
|  Routes that fit your trip                                          |
|  2 days * Hard * South Cascades * Aug 2-3                          |
|                                                                     |
|  +---------------------------------------------------------------+  |
|  |  * RECOMMENDED                                                |  |
|  |  Goat Rocks -- Snowgrass Flat          Loop * Hard            |  |
|  |  South Cascades                                               |  |
|  |                                                               |  |
|  |  23 mi   +3,800 ft   11.5 mi/day   Permit: None              |  |
|  |                                                               |  |
|  |  A high-country loop through wildflower meadows with          |  |
|  |  panoramic Cascade views. Fits your 2 days well.             |  |
|  |                             [ Plan this route -> ]           |  |
|  +---------------------------------------------------------------+  |
|                                                                     |
|  +---------------------------------------------------------------+  |
|  |  Enchantments Traverse         Thru * Epic                    |  |
|  |  18.5 mi  +4,800 ft   Permit: !! Lottery                     |  |
|  |                             [ Plan this route -> ]           |  |
|  +---------------------------------------------------------------+  |
|                                                                     |
|  +---------------------------------------------------------------+  |
|  |  Olympic High Divide           Loop * Hard * Olympics         |  |
|  |  44 mi  +9,200 ft   Permit: Advance                          |  |
|  |                             [ Plan this route -> ]           |  |
|  +---------------------------------------------------------------+  |
+---------------------------------------------------------------------+
```

- Cards replace the monospace terminal table — scannable on any screen width.
- Recommended card is full-height with description; others collapse to summary.
- Lottery permit gets an amber warning icon — visible before the user commits.
- Tapping anywhere on a card expands it.

---

### Screen 4 — Planning (Loading State)

```
+---------------------------------------------------------------------+
|                                                                     |
|         Planning Goat Rocks -- Snowgrass Flat                       |
|         Aug 2-3  *  2 days  *  Hard                                |
|                                                                     |
|  (*)  Fetching live weather forecast        done                    |
|  (*)  Checking air quality (AirNow)         done                    |
|  (*)  Checking fire & smoke conditions      done                    |
|  (*)  Checking water crossing levels        done                    |
|  ( )  Assessing conditions & risk           ...                     |
|  ( )  Building your day-by-day itinerary                            |
|  ( )  Selecting gear for conditions                                 |
|                                                                     |
|       This usually takes about 15-30 seconds.                       |
|                                                                     |
+---------------------------------------------------------------------+
```

- Progress items tick off in real time (streamed from orchestrator).
- Filled circle = complete, empty = pending, animated dot = in progress.
- Showing actual pipeline steps builds trust and manages wait-time perception.
- Honest "15-30 seconds" sets expectations.

---

### Screen 5 — Trip Brief

```
+---------------------------------------------------------------------+
| <- Back     GOAT ROCKS -- SNOWGRASS FLAT              [Export]      |
+---------------------------------------------------------------------+
|                                                                     |
|  +----------------------------------------------------------------+ |
|  |  OVERALL RISK   [=======---]  MODERATE                        | |
|  |  Main concern:  Wind exposure on Goat Ridge                   | |
|  +----------------------------------------------------------------+ |
|                                                                     |
|  Route summary                                                      |
|  23 mi loop  *  +3,800 ft  *  2 days  *  Hard  *  South Cascades  |
|  Northwest Forest Pass  *  No overnight permit                      |
|                                                                     |
|  Conditions                                                         |
|  Clear skies Aug 2-3. Light NW winds 12 mph, gusting to 22 at      |
|  ridgeline. AQI 34 (Good). Cispus River running high from          |
|  snowmelt -- ford with caution early morning.                       |
|                                                                     |
|  Itinerary                                                          |
|                                                                     |
|  +----------------------------------------------------------------+ |
|  | Day 1 * Aug 2               (green) LOW RISK                  | |
|  | Snowgrass Flat TH -> Snowgrass Flat Camp                      | |
|  | 7.5 mi  *  +1,900 ft                                          | |
|  | Highlights: Wildflower meadows above 6,000 ft.                | |
|  | Camp: Snowgrass Flat Camp (6,500 ft)                          | |
|  +----------------------------------------------------------------+ |
|                                                                     |
|  +----------------------------------------------------------------+ |
|  | Day 2 * Aug 3               (amber) MODERATE RISK             | |
|  | Snowgrass Flat -> Goat Ridge -> Trailhead                     | |
|  | 15.5 mi  *  +1,900 ft                                         | |
|  | Highlights: Goat Ridge panorama (7,400 ft). Exposed.          | |
|  | Cross Cispus River -- go early before snowmelt peaks.         | |
|  +----------------------------------------------------------------+ |
|                                                                     |
|  What to Pack                                                       |
|  Must-have:    Trekking poles * Wind shell * Water filter           |
|  Recommended:  Microspikes * Sun protection                         |
|  Nice to have: Camp chair * Rain cover * Gaiters                    |
|                                                                     |
+---------------------------------------------------------------------+
|  Ask a question about this trip                        [ Chat -> ]  |
+---------------------------------------------------------------------+
```

- Risk banner anchors the top. Color-coded: green / amber / red.
- Risk bar gives at-a-glance severity.
- Day cards use colored left-border to signal day-level risk independently.
- Gear is tiered: Must / Recommended / Nice-to-have.
- Export: copy to clipboard or download as plain text (Claude-rendered brief).
- Q&A chat entry is persistent at the bottom.

---

### Screen 5b — No Viable Route

```
+---------------------------------------------------------------------+
| <- Back     ENCHANTMENTS TRAVERSE                                   |
+---------------------------------------------------------------------+
|                                                                     |
|  +----------------------------------------------------------------+ |
|  |  (!) NOT RECOMMENDED FOR THESE DATES                          | |
|  |  Overall risk: CRITICAL  *  Main concern: Air quality (AQI)   | |
|  +----------------------------------------------------------------+ |
|                                                                     |
|  AQI is 178-195 (Very Unhealthy) across the Central Cascades.       |
|  Extended exposure at elevation is not advisable.                   |
|                                                                     |
|  What we tried                                                      |
|  x  Original itinerary (AQI too high)                              |
|  x  Adjusted itinerary -- shifted to lower elevation days           |
|  x  Plan B route (Maple Pass Loop) -- same smoke event             |
|                                                                     |
|  Suggested next steps                                               |
|  ->  Try dates 10+ days out -- smoke events typically clear in 3-5  |
|  ->  Switch to the Olympics -- different weather pattern            |
|  ->  Try a lower-elevation route (Rattlesnake Ledge, Ozette)        |
|                                                                     |
|  [ Try different dates -> ]   [ Try a different region ]            |
|                                                                     |
+---------------------------------------------------------------------+
```

- Tone is "we looked hard, here's why" — not alarming.
- "What we tried" shows pipeline reasoning — builds trust.
- Two clear recovery CTAs. Not a dead end.

---

### Screen 6 — Follow-up Q&A

```
+---------------------------------------------------------------------+
| <- Trip Brief      Q&A -- Goat Rocks                                |
+---------------------------------------------------------------------+
|                                                                     |
|  [ TrailOps ]                                                       |
|  Your trip brief is ready. Got any questions? I have the full       |
|  conditions, itinerary, and gear context right here.                |
|                                                                     |
|           [ Is the Cispus ford sketchy for a solo hiker? ]          |
|                                                                     |
|  [ TrailOps ]                                                       |
|  In August it's manageable but takes care. Go early -- before       |
|  9am -- before snowmelt peaks. Trekking poles are non-negotiable,   |
|  and unbuckle your hip belt before you step in.                     |
|                                                                     |
|  Quick questions:                                                    |
|  [ What camp gear do I need? ]  [ Any cell signal? ]               |
|  [ What's the bail-out option? ]                                    |
|                                                                     |
+---------------------------------------------------------------------+
|  Ask anything about the trip...                               [->]  |
+---------------------------------------------------------------------+
```

- Suggested quick-questions surface common follow-ups.
- Full trip brief passed as context (same as terminal `follow_up_loop`).
- Back arrow returns to brief without losing conversation.

---

### Color & Visual System

```
Background      #F7F5F0   warm off-white (paper feel)
Surface         #FFFFFF
Text primary    #1C1C1E
Text muted      #6B7280

TrailOps msgs   left bubble   #2D4A3E  dark forest green + white text
User msgs       right bubble  #F0EDE8  warm stone + dark text

Risk LOW        #22C55E   green
Risk MODERATE   #F59E0B   amber
Risk HIGH       #EF4444   red
Risk CRITICAL   #991B1B   deep red

Accent          #2D6A4F   PNW green (buttons, links)
Permit warning  #D97706   amber (lottery / advance labels)
```

---

### Streamlit Implementation Map

| Phase | Streamlit technique |
|---|---|
| Intake chat | `st.chat_message` + `st.chat_input` + `st.session_state.messages` |
| Quick-reply chips | `st.columns` + `st.button` (cleared after tap) |
| Route cards | `st.container` with `st.columns` for stats row |
| Loading progress | `st.status` (Streamlit 1.28+) — live-updating steps |
| Trip brief | `st.tabs` for Brief / Gear / Q&A sections |
| Risk banner | Custom `st.markdown` with colored div |
| Export | `st.download_button` with Claude-rendered plain text |

Backend (`orchestrator.py` and all agents) is unchanged — Streamlit replaces
only the `print/input` layer in `ui.py`, exactly as the architecture intended.

---

## React Frontend (Future Migration Path)

### Summary
React + FastAPI is the right long-term frontend — full design control, standard
web deployment, production-ready. Streamlit is the right next step — faster to
build, Python-native, validates the full flow without an API layer.

### What Has to Change
The Python backend currently has no network layer. React requires inserting a
FastAPI server between the frontend and the existing agents.

```
Current:   ui.py  -->  orchestrator.py  -->  agents
React:     React  -->  FastAPI  -->  orchestrator.py  -->  agents
```

Agents, orchestrator, risk scorer — none of that changes. Only the API layer
is new, and `ui.py` is replaced by the React app.

### API Endpoints Needed (FastAPI)

| Endpoint | Purpose |
|---|---|
| `POST /session/start` | Initialize intake conversation, return session_id |
| `POST /session/{id}/message` | Send user message, return Claude response or final JSON |
| `POST /session/{id}/routes` | Call get_route_options(), return ranked list |
| `POST /session/{id}/plan` | Trigger orchestrator.run(), stream progress via SSE |
| `GET /session/{id}/brief` | Return completed trip brief |
| `POST /session/{id}/qa` | Follow-up Q&A messages |

### The Hard Part — Streaming Progress (SSE)

The loading screen (ticking off weather → AQI → risk → itinerary) requires
Server-Sent Events. The orchestrator blocks for 15–30 seconds. Solution:

1. Run `orchestrator.run()` in a background thread
2. Have the orchestrator emit progress events to a queue
3. Stream that queue to the React client via SSE (`StreamingResponse`,
   `text/event-stream` content type)

SSE is one-directional (server to browser only) — right tool for the loading
screen. Use WebSockets for the chat UI where both sides send messages.

```
React                          FastAPI
  |-- POST /session/plan -->   |
  |<-- "weather: done" ------  | (each agent completion emits an event)
  |<-- "AQI: done" ----------  |
  |<-- "risk: done" ---------  |
  |<-- "complete: {brief}" --  |
```

Requires threading progress hooks through the orchestrator — modest but real
refactor. The orchestrator's existing step structure maps directly to events.

### Session State
Intake conversation `messages` list must live server-side, keyed by session_id.
- **In-memory dict** — fine for single-user local use, lost on restart
- **Redis** — right choice for multi-user server deployment

### Frontend Complexity by Screen

| Screen | Complexity |
|---|---|
| Landing | Low — static |
| Intake chat | Medium — useEffect + fetch, manage messages array |
| Quick-reply chips | Low |
| Route cards | Low — map over array, expand on click |
| Loading / SSE consumer | High — EventSource API, progress state machine |
| Trip brief | Medium — conditional sections, risk color logic |
| No viable route | Low — conditional render |
| Q&A chat | Medium — same pattern as intake |

### Effort vs. Streamlit

| | Streamlit | React + FastAPI |
|---|---|---|
| Backend API layer | None needed | ~2–3 days |
| Frontend | ~2–3 days | ~1–2 weeks |
| Streaming progress | st.status — free | SSE setup — real work |
| Design control | Limited | Full — design spec exactly |
| Production-ready | Needs workarounds | Standard web deployment |

### Migration Trigger
Migrate from Streamlit to React when the Streamlit ceiling becomes real —
specifically the loading progress screen (st.status is limited), custom risk
styling, and mobile layout.

The FastAPI layer built for React is also the right foundation for proactive
alerts and multi-user support — not wasted work, just premature until those
features are ready.

### Status
Deferred. Build Streamlit first. Revisit when Streamlit limitations are felt
or when server deployment / multi-user support becomes a requirement.

---

## Gear Weight Calculator

### Concept
Extend the gear section of the trip brief with an opt-in pack weight calculator.
User enters a target base weight; system allocates a budget across gear categories
and suggests items that fit within each allocation.

### Key Design Decisions
- **Base weight** as the primary input (excludes food/water/fuel — stays constant
  across trip). Show food and water estimates separately as calculated additions.
- **Presets** for common targets: Ultralight (<10 lbs), Lightweight (10–15 lbs),
  Traditional (15–25 lbs), plus a custom lbs input.
- **Budget bars** — visual horizontal bars per category, not just numbers. Users
  think "is there enough room here?" not "is 17% correct?"
- **Conditions-flagged items are locked.** Items the intelligence agent flags as
  must-have (e.g. trekking poles for a river ford, wind shell for exposed ridge)
  get a flag icon and their weight is non-negotiable — budget adjusts around them.
- **Categories are collapsible.** Shelter and Sleeping expanded by default (biggest
  decisions). Others expand on tap.
- **Gear suggestions are illustrative** — specific item names give a reference point
  for what hitting a weight target actually requires. Not a shopping list.
- **Food and water shown separately** — estimated at ~1.8 lbs/day for food; water
  based on route source density.

### Weight Categories
Shelter system · Sleeping system · Pack · Clothing · Kitchen · Water system ·
Navigation/safety · Electronics · Misc/toiletries · Trekking poles

### What TrailOps Already Provides (no new data needed)
Trip length, conditions (temp low, wind, rain probability, elevation), water
crossings, season — all feed into which items are flagged and what sleep system
temp rating is needed.

### Implementation Shape
- Weight target input added to Streamlit gear UI
- Budget allocation: deterministic Python (percentages tuned by trip length +
  difficulty)
- Expanded gear prompt to Claude: category-level suggestions with approximate weights
- Visualization: `st.progress` bars or `st.bar_chart`
- Conditions-flagging: already in `gear.py` — surface flags visually

### Status
Deferred. Design documented here for reference when gear feature is built.

---

## Proactive Trip Alerts

### Concept
When a saved trip is within 7 days, notify the user that conditions have changed
and re-run the risk assessment.

### Key UX Implications
- Requires a **saved trips** concept — trips must persist beyond a session
- Landing page needs two paths: "Plan a new trip" and "My saved trips"
- Notification channel choice (email / SMS / push) collected at save time
- Alert message shows what changed and how risk level shifted (delta, not just
  current state)

### Dependencies
Server deployment, background scheduler, user identity (see Multi-User below).
Design as a second-phase feature — all three are interdependent.

### Status
Deferred.

---

## Multi-User Support

### Concept
Multiple users with separate saved trips, preferences, and alert settings.

### Key UX Implications
- Login screen and profile layer (standard auth flow)
- "My Trips" scoped per user
- Local single-user mode stays simple; multi-user unlocks on server deployment

### Status
Deferred. Natural complement to server deployment and Trip Alerts.
