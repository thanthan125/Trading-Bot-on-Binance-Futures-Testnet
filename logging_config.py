"""
logging_config.py
-----------------
Two-channel logging setup:
  - FILE  → logs/trading_bot.log  (newline-delimited JSON, machine-readable)
  - CONSOLE → stderr              (human-readable, colour-coded by level)

Why JSON logs?
  Most candidates write plain-text logs. JSON lets you grep/pipe with tools
  like `jq`, ship to Datadog / Loki, or diff runs programmatically.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "trading_bot.log"

# ── ANSI colour helpers ────────────────────────────────────────────────────────
RESET = "\033[0m"
COLOURS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
}


class ColouredFormatter(logging.Formatter):
    """Pretty console formatter with level colours and timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        colour = COLOURS.get(record.levelname, RESET)
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%H:%M:%S"
        )
        prefix = f"{colour}[{record.levelname:<8}]{RESET} {ts}"
        msg = super().format(record)
        return f"{prefix}  {msg}"


class JsonFormatter(logging.Formatter):
    """
    Formats every log record as a single-line JSON object.
    Extra kwargs passed to logger.info(..., extra={...}) are merged in.
    """

    CORE_FIELDS = {"name", "msg", "args", "levelname", "created", "message"}

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # Attach any extra fields (e.g. request/response dicts)
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger with:
      - a JSON file handler  (DEBUG+)
      - a coloured console handler (INFO+)
    Calling this multiple times with the same name is safe (handlers won't duplicate).
    """
    logger = logging.getLogger(name)
    if logger.handlers:          # already configured
        return logger

    logger.setLevel(logging.DEBUG)

    # ── File handler (JSON) ────────────────────────────────────────────────────
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(JsonFormatter())

    # ── Console handler (pretty) ───────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(ColouredFormatter())

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False
    return logger
