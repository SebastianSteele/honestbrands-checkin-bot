#!/usr/bin/env python3
"""
match_missing_to_discord.py — READ-ONLY best-guess matcher for ClickUp
Accelerate members who are missing a Discord username.

For each blank-username member (active / to-do), find the single best-guess
Discord account in the guild roster and report its join date + whether it falls
in the bot's check-in eligibility window (joined >= 2026-03-01 AND < 12 weeks).
"Should have received a check-in but didn't" == confident match that is
eligible but whose handle is blank in ClickUp (so the bot never saw them).

Nothing is modified. Pure stdlib. Emits an approval table + JSON sidecar.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
ROSTER_CACHE = HERE / ".discord_roster_cache.json"
OUT_JSON = HERE / ".match_proposals.json"


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
CLICKUP_TOKEN = (ENV.get("CLICKUP_TOKEN") or "").strip()
DISCORD_TOKEN = (ENV.get("DISCORD_TOKEN") or "").strip()
if not CLICKUP_TOKEN or not DISCORD_TOKEN:
    sys.exit("Need CLICKUP_TOKEN and DISCORD_TOKEN in .env")

MEMBER_DB_LIST_ID = "901516122313"
CU_FIELD_DISCORD_USERNAME = "1aad9b55-223b-40f9-96e6-9388386b5ed2"
CU_FIELD_PROGRAM_NAME = "d44e9584-d751-40fb-9b52-0cb7fb9d80aa"
CU_PROGRAM_ACCELERATE_INDEX = 1
MATCH_STATUSES = {"active", "to do"}
JOIN_CUTOFF = datetime(2026, 3, 1, tzinfo=timezone.utc)
WEEKS_CAP = 12

CU_HEADERS = {"Authorization": CLICKUP_TOKEN, "Content-Type": "application/json"}
DISCORD_API = "https://discord.com/api/v10"
DISCORD_HEADERS = {"Authorization": f"Bot {DISCORD_TOKEN}",
                   "User-Agent": "HonestBrandsCheckinAdmin (local-cli, 1.0)"}


def http_get(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers, method="GET")
    while True:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                body = json.loads(e.read() or b"{}")
                time.sleep(float(body.get("retry_after", 2)) + 0.5)
                continue
            raise RuntimeError(f"GET {url} -> {e.code}: {e.read().decode()[:200]}") from None


def clickup_get(path, params):
    return http_get(f"https://api.clickup.com/api/v2{path}?{urllib.parse.urlencode(params)}", CU_HEADERS)


def discord_get(path, params=None):
    url = DISCORD_API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    return http_get(url, DISCORD_HEADERS)


def norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---- ClickUp ----------------------------------------------------------------
def fetch_clickup():
    tasks, page = [], 0
    while True:
        data = clickup_get(f"/list/{MEMBER_DB_LIST_ID}/task",
                           {"include_closed": "true", "subtasks": "true", "page": page})
        batch = data.get("tasks", [])
        if not batch:
            break
        tasks.extend(batch)
        page += 1
    have_usernames, missing = set(), []
    for t in tasks:
        program_val, du = None, None
        for cf in t.get("custom_fields", []):
            if cf.get("id") == CU_FIELD_PROGRAM_NAME:
                program_val = cf.get("value")
            elif cf.get("id") == CU_FIELD_DISCORD_USERNAME:
                du = (cf.get("value") or "").strip()
        if program_val is None or int(program_val) != CU_PROGRAM_ACCELERATE_INDEX:
            continue
        if du:
            have_usernames.add(du.lower())
            continue
        status = (t.get("status") or {}).get("status", "")
        if status in MATCH_STATUSES:
            missing.append({"name": t.get("name") or "", "task_id": t.get("id") or "", "status": status})
    return have_usernames, missing


# ---- Discord ----------------------------------------------------------------
def fetch_roster(guild_id):
    if ROSTER_CACHE.exists() and time.time() - ROSTER_CACHE.stat().st_mtime < 1800:
        return json.loads(ROSTER_CACHE.read_text())
    members, after = [], "0"
    while True:
        batch = discord_get(f"/guilds/{guild_id}/members", {"limit": 1000, "after": after})
        if not batch:
            break
        members.extend(batch)
        after = batch[-1]["user"]["id"]
        if len(batch) < 1000:
            break
        time.sleep(0.3)
    ROSTER_CACHE.write_text(json.dumps(members))
    return members


def score(full_name: str, m: dict) -> int:
    """Conservative: candidate name must CONTAIN the full normalized name, or
    contain every name token (each >= 3 chars). No reverse-substring (which let
    1-letter display names match everything)."""
    target = norm(full_name)
    toks = [norm(t) for t in full_name.split() if len(norm(t)) >= 3]
    u = m.get("user") or {}
    cand = [norm(u.get("username")), norm(u.get("global_name")), norm(m.get("nick"))]
    cand = [c for c in cand if c]
    best = 0
    for c in cand:
        if c == target and target:
            best = max(best, 100)
        elif target and len(target) >= 6 and target in c:
            best = max(best, 90)
        elif len(toks) >= 2 and all(t in c for t in toks):
            best = max(best, 85)
    if len(toks) >= 2:
        joined = " ".join(cand)
        if all(t in joined for t in toks):       # first/last split across fields
            best = max(best, 70)
        elif toks[-1] in joined and len(toks[-1]) >= 4:  # distinctive surname only
            best = max(best, 50)
    return best


def main() -> int:
    have_usernames, missing = fetch_clickup()
    guilds = discord_get("/users/@me/guilds")
    gid = guilds[0]["id"]
    roster = fetch_roster(gid)
    now = datetime.now(timezone.utc)
    print(f"Guild {guilds[0]['name']}: {len(roster)} members | "
          f"ClickUp Accelerate w/ username: {len(have_usernames)} | "
          f"blank (active/to-do) to match: {len(missing)}")
    print(f"Eligible window: joined >= {JOIN_CUTOFF.date()} AND < {WEEKS_CAP}w (today {now.date()})\n")

    proposals = []
    for mm in sorted(missing, key=lambda x: (x["status"], x["name"].lower())):
        scored = [(score(mm["name"], m), m) for m in roster]
        scored = [(s, m) for s, m in scored if s >= 70]
        scored.sort(key=lambda x: -x[0])
        best = scored[0] if scored else None
        rec = {"name": mm["name"], "task_id": mm["task_id"], "status": mm["status"],
               "match": None}
        if best:
            s, m = best
            u = m["user"]
            jd = parse_iso(m["joined_at"]) if m.get("joined_at") else None
            elig = bool(jd and jd >= JOIN_CUTOFF and (now - jd).days < WEEKS_CAP * 7)
            n_strong = sum(1 for sc, _ in scored if sc >= 85)
            rec["match"] = {"username": u["username"], "user_id": u["id"],
                            "global_name": u.get("global_name"), "nick": m.get("nick"),
                            "joined": jd.date().isoformat() if jd else None,
                            "score": s, "eligible": elig, "rivals": n_strong}
        proposals.append(rec)

    OUT_JSON.write_text(json.dumps(proposals, indent=2))

    def show(group, members):
        print(f"### {group}")
        for r in members:
            mt = r["match"]
            if not mt:
                print(f"  {r['name']:30} ({r['status']:6}) -> NO confident match")
            else:
                amb = f" [{mt['rivals']} equally-strong rivals!]" if mt["rivals"] > 1 else ""
                print(f"  {r['name']:30} ({r['status']:6}) -> @{mt['username']:22} "
                      f"gn={str(mt['global_name'] or '-'):16} joined={mt['joined']} "
                      f"score={mt['score']} elig={'YES' if mt['eligible'] else 'no'}{amb}")
        print()

    eligible = [r for r in proposals if r["match"] and r["match"]["eligible"] and r["match"]["rivals"] <= 1]
    elig_amb = [r for r in proposals if r["match"] and r["match"]["eligible"] and r["match"]["rivals"] > 1]
    inelig = [r for r in proposals if r["match"] and not r["match"]["eligible"]]
    nomatch = [r for r in proposals if not r["match"]]

    show("SHOULD-HAVE-GOTTEN-IT: eligible + confident (prime send targets)", eligible)
    show("Eligible but AMBIGUOUS (multiple equally-strong matches — confirm)", elig_amb)
    show("Matched but INELIGIBLE (joined >12w ago / before cutoff — bot rolls off)", inelig)
    show("NO confident Discord match", nomatch)
    print(f"Proposals written to {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
