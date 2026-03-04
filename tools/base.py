import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from logger import get_logger

load_dotenv()

log = get_logger(__name__)

_config_path = Path(__file__).parent.parent / "config.json"
with open(_config_path) as f:
    CONFIG = json.load(f)


def use_mock() -> bool:
    return os.getenv("USE_MOCK", "false").lower() == "true"


def mock_scenario() -> int:
    """
    1 = clean conditions (Goat Rocks)
    2 = high AQI/smoke (Enchantments)
    3 = weather + river crossing risk (Olympic High Divide)
    4 = SR-20 seasonal closure (Maple Pass Loop / Pasayten) — pipeline gates before Intelligence Agent
    """
    return int(os.getenv("MOCK_SCENARIO", "1"))


def call_with_retry(url: str, method: str = "GET", **kwargs) -> dict:
    """HTTP request with timeout, retry, and exponential backoff."""
    timeout = 10
    max_retries = 2

    log.debug(f"{method.upper()} {url}")
    for attempt in range(max_retries + 1):
        try:
            if method.upper() == "POST":
                response = requests.post(url, timeout=timeout, **kwargs)
            else:
                response = requests.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                log.warning(f"API attempt {attempt + 1}/{max_retries + 1} failed ({e}) — retrying in {wait}s")
                time.sleep(wait)
                continue
            log.error(f"API call failed after {max_retries + 1} attempts: {e} [{url}]")
            raise RuntimeError(f"API call failed after {max_retries + 1} attempts: {e}")
