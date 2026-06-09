#!/usr/bin/env python3
"""
audit_discord_usernames.py — read-only check of the ClickUp Member Database.

Pages the Member DB list, filters to Accelerate members, and reports how many
have a Discord Username filled in vs. blank. A blank username means that member
is invisible to fetch_accelerate_usernames() in bot.py and therefore receives
NO weekly/midweek check-in (the eligibility filter fails closed).

Pure stdlib (urllib) so it runs on system python3 without the (stale) venv.
Does NOT modify anything.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


ENV = load_env(ENV_PATH)
TOKEN = (ENV.get("CLICKUP_TOKEN") or "").strip()
if not TOKEN:
    sys.exit("CLICKUP_TOKEN not found in .env")

MEMBER_DB_LIST_ID = "901516122313"
CU_FIELD_DISCORD_USERNAME = "1aad9b55-223b-40f9-96e6-9388386b5ed2"
CU_FIELD_PROGRAM_NAME = "d44e9584-d751-40fb-9b52-0cb7fb9d80aa"
CU_PROGRAM_ACCELERATE_INDEX = 1

HEADERS = {"Authorization": TOKEN, "Content-Type": "application/json"}


def get(path: str, params: dict) -> dict:
    url = f"https://api.clickup.com/api/v2{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


def fetch_all_tasks() -> list:
    tasks = []
    page = 0
    while True:
        data = get(
            f"/list/{MEMBER_DB_LIST_ID}/task",
            {"include_closed": "true", "subtasks": "true", "page": page},
        )
        batch = data.get("tasks", [])
        if not batch:
            break
        tasks.extend(batch)
        page += 1
    return tasks


def main() -> int:
    tasks = fetch_all_tasks()

    accel_with = []      # (name, username, status)
    accel_blank = []     # (name, task_id, status)
    program_counts: dict = {}

    for t in tasks:
        program_val = None
        discord_username = None
        for cf in t.get("custom_fields", []):
            if cf.get("id") == CU_FIELD_PROGRAM_NAME:
                program_val = cf.get("value")
            elif cf.get("id") == CU_FIELD_DISCORD_USERNAME:
                discord_username = (cf.get("value") or "").strip()

        key = "blank" if program_val is None else str(program_val)
        program_counts[key] = program_counts.get(key, 0) + 1

        is_accel = program_val is not None and int(program_val) == CU_PROGRAM_ACCELERATE_INDEX
        if not is_accel:
            continue

        name = t.get("name") or "(unnamed)"
        status = (t.get("status") or {}).get("status", "")
        if discord_username:
            accel_with.append((name, discord_username, status))
        else:
            accel_blank.append((name, t.get("id") or "", status))

    total_accel = len(accel_with) + len(accel_blank)
    print(f"Member DB list {MEMBER_DB_LIST_ID}: {len(tasks)} total tasks")
    print(f"Program-Name orderindex distribution: {program_counts}")
    print(f"  (Accelerate = orderindex {CU_PROGRAM_ACCELERATE_INDEX})")
    print()
    print(f"Accelerate members: {total_accel}")
    print(f"  with Discord username : {len(accel_with)}")
    print(f"  BLANK Discord username: {len(accel_blank)}")
    print()

    if accel_blank:
        print("Accelerate members MISSING a Discord username (get NO check-ins):")
        for name, task_id, status in sorted(accel_blank, key=lambda x: (x[2], x[0].lower())):
            print(f"  - {name!r:42} status={status:18} https://app.clickup.com/t/{task_id}")
    else:
        print("Every Accelerate member has a Discord username. Nothing missing.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
