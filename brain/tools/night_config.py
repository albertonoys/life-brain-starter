#!/usr/bin/env python3
"""Read the night-shift settings out of config.json as shell variables.

    eval "$(python3 brain/tools/night_config.py)"

The shell scripts must not parse JSON themselves — zsh and PowerShell would
each need their own parser and they would drift. This prints one form both
can eval, and is the single place the defaults live.

Config shape, under `"night"` in brain/config.json:

    "night": {
      "enabled": false,          the whole thing, off by default
      "at": "01:00",             read by setup_night.sh when scheduling
      "jobs": ["queue", "wrap"], run in order, one at a time
      "model": "",               "" follows the default model (the Usage page's
                                 pick if set, else careful -> haiku)
      "on_battery": false        laptops: skip unless plugged in
    }
"""

import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.dirname(HERE)

DEFAULTS = {"enabled": False, "at": "01:00", "jobs": ["queue"],
            "model": "", "on_battery": False}
# The jobs an unattended run may do. /today is deliberately absent: the morning
# plan must be written in the morning, against the day it is planning. Every
# name here must exist in .claude/commands/ — the night runs `claude -p /job`.
ALLOWED = {"queue", "wrap", "sync", "brief", "discover", "scout"}


def load():
    try:
        with open(os.path.join(BRAIN, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    night = dict(DEFAULTS, **(cfg.get("night") or {}))
    jobs = [j for j in (night.get("jobs") or []) if j in ALLOWED]
    night["jobs"] = jobs or ["queue"]
    if not night.get("model"):
        # Same resolution as every other run: the Usage page's explicit
        # default model if set, else the mode's.
        ov = (cfg.get("ai_features") or {}).get("model")
        if ov in ("haiku", "sonnet", "opus", "fable"):
            night["model"] = ov
        else:
            careful = cfg.get("ai") in ("low", "careful", "pro")
            night["model"] = "haiku" if careful else "sonnet"
    # setup_night.sh does arithmetic on the hour and minute, and a shell
    # evaluates what it finds inside arithmetic: only a real time passes.
    if not re.fullmatch(r"\d{1,2}:\d{2}", str(night.get("at") or "")):
        night["at"] = DEFAULTS["at"]
    return night


def _ps(value):
    """A PowerShell single-quoted literal: nothing inside it expands. Curly
    single quotes also close a PowerShell string, so they are doubled too."""
    s = str(value)
    for q in ("'", "\u2018", "\u2019", "\u201a", "\u201b"):
        s = s.replace(q, q + q)
    return "'" + s + "'"


def main():
    n = load()
    if "--json" in sys.argv:
        print(json.dumps(n, indent=2))
        return 0
    # The shells pass this straight to `claude --model`, which wants Fable by
    # its full name — the short alias comes back 404.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import usage
    n = dict(n, model=usage.cli_model(n["model"]))
    # Both shells eval these lines, so every value is quoted as a literal:
    # a config value like $(...) must arrive as text, never run.
    if "--powershell" in sys.argv:
        print(f'$NightEnabled = {_ps(1 if n["enabled"] else 0)}')
        print(f'$NightJobs = {_ps(" ".join(n["jobs"]))}')
        print(f'$NightModel = {_ps(n["model"])}')
        print(f'$NightBattery = {_ps(1 if n["on_battery"] else 0)}')
        print(f'$NightAt = {_ps(n["at"])}')
        return 0
    q = shlex.quote
    print(f'NIGHT_ENABLED={q(str(1 if n["enabled"] else 0))}')
    print(f'NIGHT_JOBS={q(" ".join(n["jobs"]))}')
    print(f'NIGHT_MODEL={q(n["model"])}')
    print(f'NIGHT_BATTERY={q(str(1 if n["on_battery"] else 0))}')
    print(f'NIGHT_AT={q(n["at"])}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
