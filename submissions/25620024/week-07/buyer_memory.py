"""Week 08 — buyer_memory.py: the buyer's memory in two layers.

  episodes  memory.jsonl, one line per trade, append only. The evidence; read in full only to rebuild.
  profiles  shop_profiles.json, one compact entry per shop, built from the episodes and kept up to date
            incrementally: the file remembers how far into memory.jsonl it has read (a byte offset) and
            reads only the lines added since. A retraction line ({"retracts": ts}) or a shorter file
            triggers a full rebuild.

The profiles are what the buyer reads when it picks a shop and haggles ("memory as a behavior prior":
where to look and what to expect, not the evidence itself). Before this, every order re-read all of
memory.jsonl (11,217 lines on 10/27) to recompute the same summaries.

    python buyer_memory.py              # rebuild and print the profiles
"""
import json
import os
import statistics
import time
from pathlib import Path

MEMORY = Path(os.environ.get("MARKET_BUYER_MEMORY", Path(__file__).parent / "memory.jsonl"))
PROFILES = MEMORY.with_name(MEMORY.stem.replace("memory", "shop_profiles") + ".json") \
    if "memory" in MEMORY.stem else MEMORY.with_name("shop_profiles.json")
CHEAT_PREFIXES = ("receipt above", "receipt for", "misbehaved")
RECENT = 5                 # recent outcomes kept per shop
RATIOS = 20                # recent settle ratios kept per shop


def _empty():
    return {"trades": 0, "deals": 0, "signed": 0, "no_answer": 0, "cheats": [], "problems": [],
            "recent": [], "paid": [0.0, 0], "ratios": [], "last_price": {}, "last_ts": 0}


def _add(p, m):
    p["trades"] += 1
    p["last_ts"] = max(p["last_ts"], m.get("ts") or 0)
    p["recent"] = (p["recent"] + [[m.get("ts") or 0, m.get("outcome")]])[-RECENT:]
    prob = m.get("problem")
    if prob:
        p["problems"] = (p["problems"] + [prob])[-2:]
        if prob.startswith(CHEAT_PREFIXES):
            p["cheats"] = (p["cheats"] + [prob])[-3:]
    if m.get("outcome") == "no answer":
        p["no_answer"] += 1
    if m.get("outcome") == "deal":
        p["deals"] += 1
        p["signed"] += bool(m.get("signed"))
        agreed, budget, first = m.get("agreed"), m.get("budget"), m.get("first_ask")
        if agreed and budget:
            p["paid"] = [p["paid"][0] + agreed / budget, p["paid"][1] + 1]
        if agreed and first:
            p["ratios"] = (p["ratios"] + [round(agreed / first, 3)])[-RATIOS:]
        if agreed and m.get("item"):
            p["last_price"][m["item"]] = agreed


def _rebuild():
    profiles, rows = {}, []
    if MEMORY.exists():
        for line in MEMORY.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    withdrawn = {m["retracts"] for m in rows if "retracts" in m}
    for m in rows:
        if "retracts" in m or m.get("ts") in withdrawn or not m.get("shop"):
            continue
        _add(profiles.setdefault(m["shop"], _empty()), m)
    offset = MEMORY.stat().st_size if MEMORY.exists() else 0
    return {"offset": offset, "built": time.time(), "profiles": profiles}


def load():
    """The shop profiles, brought up to date with any lines added to memory.jsonl since the last call."""
    try:
        state = json.loads(PROFILES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = None
    size = MEMORY.stat().st_size if MEMORY.exists() else 0
    if not state or size < state.get("offset", 0):
        state = _rebuild()
    elif size > state["offset"]:
        with MEMORY.open("rb") as f:
            f.seek(state["offset"])
            new = f.read().decode("utf-8", errors="ignore")
        lines = [json.loads(x) for x in new.splitlines() if x.strip().startswith("{")]
        if any("retracts" in m for m in lines):
            state = _rebuild()
        else:
            for m in lines:
                if m.get("shop"):
                    _add(state["profiles"].setdefault(m["shop"], _empty()), m)
            state["offset"] = size
    try:
        PROFILES.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return state["profiles"]


def settle_ratio(p):
    """Median of agreed / first ask over my recent deals with this shop, or None with fewer than 3."""
    return statistics.median(p["ratios"]) if p and len(p["ratios"]) >= 3 else None


if __name__ == "__main__":
    t = time.time()
    prof = load()
    print(f"{len(prof)} shops from {MEMORY.name} in {time.time() - t:.2f} s")
    for name, p in sorted(prof.items(), key=lambda kv: -kv[1]["deals"])[:15]:
        r = settle_ratio(p)
        print(f"  {name:20} trades {p['trades']:5} deals {p['deals']:5} signed {p['signed']:5} "
              f"settles at {f'{r:.0%}' if r else '-':>4} of first ask  cheats {len(p['cheats'])}")
