@echo off
:: Run TrailOps in mock mode with a specific scenario.
:: Usage: run_mock [1|2|3|4]
::
:: Scenarios:
::   1 - Goat Rocks, clean conditions (green-light path)
::   2 - Enchantments, high AQI/smoke (Replanner triggered)
::   3 - Olympic High Divide, weather + river risk (Plan B triggered)
::   4 - Maple Pass Loop / Pasayten, SR-20 closed (pass gate, pipeline bails early)
::
:: Default: scenario 1

set SCENARIO=%1
if "%SCENARIO%"=="" set SCENARIO=1

set USE_MOCK=true
set MOCK_SCENARIO=%SCENARIO%

echo Starting TrailOps -- mock scenario %SCENARIO%
python -m streamlit run streamlit_app.py
