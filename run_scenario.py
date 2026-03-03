"""
Scenario runner — bypasses the UI conversation and runs a pre-built test scenario.

Usage:
    python run_scenario.py 1   # Goat Rocks, clean conditions
    python run_scenario.py 2   # Enchantments, high AQI/smoke
    python run_scenario.py 3   # Olympic High Divide, weather + river risk

The MOCK_SCENARIO env var is set from the scenario file's _mock_scenario field,
so USE_MOCK is forced to true automatically.
"""

import json
import os
import sys
from pathlib import Path

# --- Set mock env vars BEFORE importing any project modules ---
# (load_dotenv in tools/base.py runs at import time and won't override these)

def _load_scenario(num: str) -> dict:
    path = Path(__file__).parent / "data" / "scenarios" / f"scenario_{num}.json"
    if not path.exists():
        sys.stderr.write(f"Error: scenario file not found: {path}\n")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


if len(sys.argv) != 2 or sys.argv[1] not in ("1", "2", "3"):
    sys.stderr.write("Usage: python run_scenario.py <1|2|3>\n")
    sys.exit(1)

scenario_num = sys.argv[1]
scenario = _load_scenario(scenario_num)

os.environ["USE_MOCK"] = "true"
os.environ["MOCK_SCENARIO"] = str(scenario.get("_mock_scenario", scenario_num))

# --- Now safe to import project modules ---
import orchestrator
import ui
from logger import get_logger

log = get_logger(__name__)

# Strip internal fields before passing to orchestrator
user_input = {k: v for k, v in scenario.items() if not k.startswith("_")}

log.info(f"run_scenario: starting scenario {scenario_num} — {scenario.get('_description', '')}")
print(f"\nRunning Scenario {scenario_num}: {scenario.get('_description', '')}")
print(f"Mock scenario: {os.environ['MOCK_SCENARIO']} | USE_MOCK: true\n")

brief = orchestrator.run(user_input)
ui.render_brief(brief)
