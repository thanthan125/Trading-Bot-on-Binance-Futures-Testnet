"""
config.py
---------
API key management.

Supports three credential sources (in priority order):
  1. Environment variables  BINANCE_API_KEY / BINANCE_API_SECRET
  2. A config.json file in the project root
  3. Interactive prompt (fallback — never stores keys)

Why multiple sources?
  - CI/CD pipelines use env vars
  - Local dev often uses a config file
  - Interactive prompt means the bot works out-of-the-box without setup

Security note: config.json is in .gitignore — keys are never committed.
"""

import json
import os
from pathlib import Path
from typing import Optional

from .logging_config import get_logger

logger = get_logger(__name__)

CONFIG_FILE = Path(__file__).parent.parent / "config.json"


def _load_from_env() -> tuple[Optional[str], Optional[str]]:
    key    = os.environ.get("BINANCE_API_KEY")
    secret = os.environ.get("BINANCE_API_SECRET")
    if key and secret:
        logger.debug("Loaded API credentials from environment variables.")
    return key, secret


def _load_from_file() -> tuple[Optional[str], Optional[str]]:
    if not CONFIG_FILE.exists():
        return None, None
    try:
        data   = json.loads(CONFIG_FILE.read_text())
        key    = data.get("api_key")
        secret = data.get("api_secret")
        if key and secret:
            logger.debug(f"Loaded API credentials from {CONFIG_FILE}")
            return key, secret
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Could not read {CONFIG_FILE}: {exc}")
    return None, None


def _prompt_for_credentials() -> tuple[str, str]:
    """Interactive fallback — keys are used in memory only."""
    import getpass
    print("\n⚠️  No API credentials found.")
    print("   Set BINANCE_API_KEY / BINANCE_API_SECRET env vars, or create config.json.\n")
    key    = input("Enter your Binance Testnet API Key: ").strip()
    secret = getpass.getpass("Enter your Binance Testnet API Secret: ").strip()
    if not key or not secret:
        raise ValueError("API key and secret cannot be empty.")
    return key, secret


def load_credentials() -> tuple[str, str]:
    """
    Return (api_key, api_secret) from the highest-priority available source.
    Raises ValueError if no valid credentials are found anywhere.
    """
    key, secret = _load_from_env()
    if key and secret:
        return key, secret

    key, secret = _load_from_file()
    if key and secret:
        return key, secret

    return _prompt_for_credentials()


def save_config(api_key: str, api_secret: str) -> None:
    """
    Write credentials to config.json (for convenience during development).
    Warns if the file is not in .gitignore.
    """
    CONFIG_FILE.write_text(
        json.dumps({"api_key": api_key, "api_secret": api_secret}, indent=2)
    )
    logger.info(f"Credentials saved to {CONFIG_FILE}")

    gitignore = Path(__file__).parent.parent / ".gitignore"
    if gitignore.exists() and "config.json" not in gitignore.read_text():
        logger.warning(
            "config.json is NOT in .gitignore — your API keys could be committed to git!"
        )
