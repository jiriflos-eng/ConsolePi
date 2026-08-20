#!/usr/bin/env python3
"""Regression checks for console transcript cleanup on abrupt SSH disconnect."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
session = (ROOT / "usr/local/sbin/consolepi-session").read_text(encoding="utf-8")
writer = (ROOT / "usr/local/sbin/consolepi-transcript-writer").read_text(encoding="utf-8")


def require(condition, message):
    if not condition:
        raise SystemExit(f"FAIL: {message}")


require("--logfile \"$TRANSCRIPT\"" in session,
        "recording session must use picocom native output logging")
session_code = "\n".join(line for line in session.splitlines() if not line.lstrip().startswith("#"))
require("setsid" not in session_code,
        "recording must not outlive a closed SSH client")
require("script --quiet" not in session_code,
        "recording must not insert a script pseudo-terminal before picocom")
require("finalize_picocom_transcript" in session,
        "session must finalize picocom transcript on all exit paths")
require('mv -f "$TRANSCRIPT" "${TRANSCRIPT%.active}.log"' in session,
        "completed transcript must be atomically renamed in its directory")
require('rm -f "$TRANSCRIPT"' in session,
        "empty transcript must not be retained")

print("Transcript disconnect behavior: PASS")
