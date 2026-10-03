"""Solve the campaign from scratch and write a watchable replay.

    python -m mario
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from mario.agent import pack_actions, replay, solve_level
from mario.engine import State
from mario.levels import campaign

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer" / "index.html"
PROOF = ROOT / "replays" / "proof.json"


def _record(level, actions: list[tuple[bool, bool, bool, bool]]) -> dict:
    state = State(level)
    frames = []
    events = []
    seen: set[tuple[int, int]] = set()

    def grab() -> None:
        snap = state.snapshot()
        flat = [
            snap["px"],
            snap["py"],
            snap["face"],
            snap["ground"],
            snap["coins"],
            snap["time"],
            snap["won"],
            state.stomps,
        ]
        for ex, ey, alive in snap["enemies"]:
            flat.extend((ex, ey, alive))
        frames.append(flat)
        for tx, ty, code in snap["changed"]:
            key = (tx, ty)
            if key not in seen:
                seen.add(key)
                events.append([len(frames) - 1, tx, ty, code])

    grab()
    for buttons in actions:
        if state.won or state.dead:
            break
        state.step(buttons)
        grab()
    rows = []
    for y, row in enumerate(level.rows):
        chars = []
        for x, ch in enumerate(row):
            chars.append("." if ch in "@GKWC" else ch)
        rows.append("".join(chars))
    return {
        "name": level.name,
        "world": level.world,
        "stage": level.stage,
        "theme": level.theme,
        "rows": rows,
        "kinds": [e.kind for e in level.enemies0],
        "frames": frames,
        "events": events,
        "coins": state.coins,
        "stomps": state.stomps,
        "frames_played": state.frame,
        "won": state.won,
        "dead": state.dead,
    }


def main() -> int:
    levels = campaign()
    if len(levels) != 32:
        print(f"expected 32 stages, found {len(levels)}")
        return 1
    print("Mario champion — receding-horizon search over the real physics")
    proof_levels = []
    recordings = []
    deaths = 0
    t0 = time.perf_counter()
    for level in levels:
        started = time.perf_counter()
        state, actions = solve_level(level)
        solved = time.perf_counter() - started
        check = replay(level, actions)
        ok = state.won and not state.dead and check.won and not check.dead and check.frame == state.frame
        if not ok:
            deaths += 0 if state.won else 1
            print(f"  {level.name} FAIL  dead={state.dead} won={state.won} frame={state.frame}")
            return 1
        recordings.append(_record(level, actions))
        proof_levels.append(
            {
                "name": level.name,
                "theme": level.theme,
                "frames": state.frame,
                "coins": state.coins,
                "stomps": state.stomps,
                "solve_s": round(solved, 3),
                "actions": pack_actions(actions),
            }
        )
        print(
            f"  {level.name}  CLEAR  {state.frame:4} frames  "
            f"coins {state.coins:2}  stomps {state.stomps:2}  {solved:.2f}s"
        )
    elapsed = time.perf_counter() - t0
    total_frames = sum(item["frames"] for item in proof_levels)
    total_coins = sum(item["coins"] for item in proof_levels)
    proof = {
        "agent": "receding-horizon forward-model search",
        "levels": 32,
        "deaths": 0,
        "cleared": True,
        "frames": total_frames,
        "coins": total_coins,
        "solve_s": round(elapsed, 2),
        "stages": proof_levels,
    }
    PROOF.parent.mkdir(parents=True, exist_ok=True)
    PROOF.write_text(json.dumps(proof))
    data = {
        "deaths": 0,
        "frames": total_frames,
        "coins": total_coins,
        "solve_s": round(elapsed, 2),
        "levels": recordings,
    }
    _write_viewer(data)
    print()
    print(f"GAME CLEAR  32/32 deathless  {total_frames} frames  {total_coins} coins  {elapsed:.1f}s search")
    print(f"proof   {PROOF}")
    print(f"watch   {VIEWER}")
    return 0


def _write_viewer(data: dict) -> None:
    template = (ROOT / "viewer" / "template.html").read_text()
    payload = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    html = template.replace("/*__REPLAY__*/null", payload)
    VIEWER.write_text(html)


if __name__ == "__main__":
    sys.exit(main())
