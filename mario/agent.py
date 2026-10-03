"""Champion Mario agent.

The controller is a receding-horizon search over the real physics. Whenever a
straight sprint would die, stall, or leave the ground, it simulates a catalog
of run, jump, wait, and backup plans in the cloneable forward model and
commits to the plan that gets farthest toward the flag alive.

That is the same family of technique as the A* agents that won the Mario AI
Competition: with a perfect model of a deterministic platformer, search beats
a trained reflex policy. Plans are scored by exact rollouts, not by a neural
net guessing from pixels.
"""

from __future__ import annotations

import random

from mario.engine import (
    LAVA,
    ONEWAY,
    PLAYER_H,
    SOLID_CODES,
    SPRINT,
    TILE,
    State,
    WAIT,
    WALK,
)

# Long enough for a full-speed run-up plus a full jump, so a plan can be
# scored on the landing itself instead of a guessed arc.
HORIZON = 110
# right, left, jump, run
JUMP_R = (True, False, True, True)
JUMP_W = (True, False, True, False)
LEFT = (False, True, False, True)


def _pattern(delay: int, hold: int, run: bool, direction: int = 1) -> list[tuple[bool, bool, bool, bool]]:
    seq = []
    right = direction > 0
    left = direction < 0
    for t in range(HORIZON):
        jumping = delay <= t < delay + hold
        seq.append((right, left, jumping, run))
    return seq


def _backup_then_jump(back: int, hold: int) -> list[tuple[bool, bool, bool, bool]]:
    seq = []
    for t in range(HORIZON):
        if t < back:
            seq.append(LEFT)
        elif t < back + hold:
            seq.append(JUMP_R)
        else:
            seq.append(SPRINT)
    return seq


def _wait_then(wait: int, hold: int) -> list[tuple[bool, bool, bool, bool]]:
    seq = []
    for t in range(HORIZON):
        if t < wait:
            seq.append(WAIT)
        elif t < wait + hold:
            seq.append(JUMP_R)
        else:
            seq.append(SPRINT)
    return seq


def _burst(run_for: int, hold: int = 0) -> list[tuple[bool, bool, bool, bool]]:
    """Move forward, maybe hop, then stop. Used to step off a perch without a pit."""
    seq = []
    for t in range(HORIZON):
        if t < run_for:
            seq.append((True, False, t < hold, True))
        else:
            seq.append(WAIT)
    return seq


def _double_jump(d1: int, h1: int, gap: int, h2: int) -> list[tuple[bool, bool, bool, bool]]:
    seq = []
    second = d1 + h1 + gap
    for t in range(HORIZON):
        jumping = (d1 <= t < d1 + h1) or (second <= t < second + h2)
        seq.append((True, False, jumping, True))
    return seq


def _focused_plans(state: State) -> list[list[tuple[bool, bool, bool, bool]]]:
    """Sample jump timings aimed at the next gap, wall, or enemy."""
    plans = []
    speed = max(state.vx, 2.2)
    tx = int((state.px + PLAYER_H * 0.5) // TILE)
    feet = int((state.py + PLAYER_H + 1) // TILE)
    body = int((state.py + 4) // TILE)
    obstacle_x = None
    for i in range(1, 22):
        x = tx + i
        below = state.code(x, feet)
        ahead = state.code(x, body)
        stepped = state.code(x, feet - 1)
        gap = below not in SOLID_CODES and below != ONEWAY and stepped not in SOLID_CODES
        wall = ahead in SOLID_CODES and stepped in SOLID_CODES
        if gap or wall:
            obstacle_x = x * TILE
            break
    if obstacle_x is not None:
        for back in (0, 6, 12, 18, 26, 34, 44, 56):
            takeoff = obstacle_x - back
            delay = int(max(0, round((takeoff - state.px) / speed)))
            if delay >= HORIZON - 8:
                continue
            for hold in (4, 8, 12, 16, 22):
                plans.append(_pattern(delay, hold, True, 1))
                if hold in (8, 16):
                    plans.append(_pattern(max(0, delay - 1), hold, True, 1))
    for e in state.enemies:
        if not e.alive:
            continue
        dx = e.x - state.px
        if dx < -8 or dx > TILE * 14:
            continue
        for back in (0, 10, 20, 30):
            delay = int(max(0, round((dx - back) / speed)))
            if delay >= HORIZON - 8:
                continue
            for hold in (2, 5, 10, 16):
                plans.append(_pattern(delay, hold, True, 1))
    return plans


def catalog(state: State, deep: bool) -> list[list[tuple[bool, bool, bool, bool]]]:
    plans = [
        [SPRINT] * HORIZON,
        [WALK] * HORIZON,
        [WAIT] * HORIZON,
        [LEFT] * HORIZON,
    ]
    delays = range(0, 96, 4)
    holds = (2, 6, 12, 18, 24)
    for delay in delays:
        for hold in holds:
            plans.append(_pattern(delay, hold, True, 1))
    for delay in (0, 6, 12, 20, 28):
        for hold in (3, 10, 18):
            plans.append(_pattern(delay, hold, False, 1))
    plans.extend(_focused_plans(state))
    for back in (8, 16, 24):
        for hold in (10, 18):
            plans.append(_backup_then_jump(back, hold))
    for wait in (8, 16, 28):
        plans.append(_wait_then(wait, 14))
    for run_for in (8, 14, 22, 32):
        plans.append(_burst(run_for))
        plans.append(_burst(run_for, hold=3))
    for d1 in (0, 6, 12):
        for gap in (8, 16, 24):
            plans.append(_double_jump(d1, 10, gap, 12))
    if deep:
        rng = random.Random((state.frame + 1) * 997 + int(state.px * 4) + int(state.py) * 13)
        for _ in range(180):
            delay = rng.randrange(0, 60)
            hold = rng.choice((2, 4, 8, 12, 16, 22))
            run = rng.random() < 0.8
            direction = 1 if rng.random() < 0.9 else -1
            plans.append(_pattern(delay, hold, run, direction))
    return plans


def _finish(s: State, last: tuple[bool, bool, bool, bool]) -> None:
    """Keep simulating until the arc ends so a pit cannot look like progress."""
    if s.on_ground or s.dead or s.won:
        return
    extra_jump = 10 if last[2] and s.vy < 0.0 else 0
    for k in range(54):
        jump = k < extra_jump
        s.step((last[0], last[1], jump, last[3]))
        if s.on_ground or s.dead or s.won:
            return


def _score_rollout(state: State, plan: list[tuple[bool, bool, bool, bool]]) -> float:
    s = state.clone()
    for buttons in plan:
        s.step(buttons)
        if s.won:
            return 1.0e8 - s.frame
        if s.dead:
            return -1.0e7 + s.px
    _finish(s, plan[-1])
    if s.won:
        return 1.0e8 - s.frame
    if s.dead or not s.on_ground:
        return -1.0e7 + s.px
    score = s.px + s.coins * 8.0 + s.stomps * 4.0 - s.frame * 0.02
    if s.px < state.px - 6.0:
        score -= 1000.0
    for e in s.enemies:
        if not e.alive:
            continue
        dx = e.x - s.px
        dy = abs(e.y - s.py)
        if -6.0 < dx < 22.0 and dy < 22.0:
            score -= 350.0
    return score


def sprint_is_safe(state: State, frames: int = 36) -> bool:
    """True when sprinting forward for a bit cannot fall, bonk, or hit anyone."""
    tx = int((state.px + 6) // TILE)
    feet = int((state.py + PLAYER_H + 1) // TILE)
    for i in range(1, 14):
        x = tx + i
        below = state.code(x, feet)
        step = state.code(x, feet - 1)
        tall = state.code(x, feet - 2)
        if below == LAVA:
            return False
        if below not in SOLID_CODES and below != ONEWAY and step not in SOLID_CODES:
            return False
        if step in SOLID_CODES and tall in SOLID_CODES:
            return False
    for e in state.enemies:
        if e.alive and -12.0 < (e.x - state.px) < TILE * 12 and abs(e.y - state.py) < 48:
            return False
    s = state.clone()
    x0 = s.px
    for _ in range(frames):
        s.step(SPRINT)
        if s.won:
            return True
        if s.dead:
            return False
    if not s.on_ground:
        return False
    if s.px <= x0 + 4.0 and abs(s.vx) < 0.4:
        return False
    return True


def _commit(state: State, plan: list[tuple[bool, bool, bool, bool]]) -> list[tuple[bool, bool, bool, bool]]:
    """Execute a chosen plan through its first landing, including the run-up."""
    s = state.clone()
    jumped = False
    has_jump = any(b[2] for b in plan)
    out: list[tuple[bool, bool, bool, bool]] = []
    for i, buttons in enumerate(plan):
        s.step(buttons)
        out.append(buttons)
        if buttons[2] and s.vy < 0.0:
            jumped = True
        if s.dead or s.won:
            break
        if jumped and s.on_ground:
            if buttons[2]:
                release = (buttons[0], buttons[1], False, buttons[3])
                trial = s.clone()
                trial.step(release)
                if not trial.dead:
                    out.append(release)
            break
        if not has_jump and i >= 9:
            break
        if not jumped and i >= 90:
            break
    return out or [SPRINT]


def select_plan(state: State) -> list[tuple[bool, bool, bool, bool]]:
    if state.on_ground and sprint_is_safe(state):
        return [SPRINT] * 10
    best_score = -1.0e18
    best: list[tuple[bool, bool, bool, bool]] | None = None
    for plan in catalog(state, deep=False):
        score = _score_rollout(state, plan)
        if score > best_score:
            best_score = score
            best = plan
    if best_score < -1.0e6:
        for plan in catalog(state, deep=True):
            score = _score_rollout(state, plan)
            if score > best_score:
                best_score = score
                best = plan
    return best if best is not None else [SPRINT] * 8


def solve_level(level, max_frames: int | None = None) -> tuple[State, list[tuple[bool, bool, bool, bool]]]:
    """Play one level. The returned trace is a deterministic winning replay."""
    state = State(level)
    actions: list[tuple[bool, bool, bool, bool]] = []
    limit = max_frames if max_frames is not None else level.w * 14
    idle_x = state.px
    idle = 0
    while not state.won and not state.dead and state.frame < limit:
        plan = select_plan(state)
        commit = _commit(state, plan)
        for buttons in commit:
            state.step(buttons)
            actions.append(buttons)
            if state.won or state.dead:
                break
        if state.px <= idle_x + 0.75:
            idle += len(commit)
        else:
            idle_x = state.px
            idle = 0
        if idle > 280:
            break
    return state, actions


def replay(level, actions: list[tuple[bool, bool, bool, bool]]) -> State:
    state = State(level)
    for buttons in actions:
        if state.won or state.dead:
            break
        state.step(buttons)
    return state


def pack_actions(actions: list[tuple[bool, bool, bool, bool]]) -> str:
    chars = "0123456789abcdef"
    out = []
    for right, left, jump, run in actions:
        nibble = (1 if right else 0) | (2 if left else 0) | (4 if jump else 0) | (8 if run else 0)
        out.append(chars[nibble])
    return "".join(out)


def unpack_actions(text: str) -> list[tuple[bool, bool, bool, bool]]:
    actions = []
    for ch in text:
        n = int(ch, 16)
        actions.append((bool(n & 1), bool(n & 2), bool(n & 4), bool(n & 8)))
    return actions
