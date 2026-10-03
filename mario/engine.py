"""Deterministic 2D Mario-style engine with a cloneable forward model.

Physics are an original approximation of the classic side-scroller: run,
variable jump, stomps, question blocks, pipes, lava, and a flagpole.
No Nintendo ROM, sprites, or level data are used.
"""

from __future__ import annotations

TILE = 16
PLAYER_W = 12
PLAYER_H = 16

GRAVITY = 0.50
HOLD_GRAVITY = 0.26
JUMP_V = -7.55
CUT_V = -2.4
MAX_FALL = 7.5
MAX_WALK = 1.50
MAX_RUN = 2.55
ACCEL = 0.14
ACCEL_RUN = 0.22
AIR_ACCEL_SCALE = 0.65
FRICTION = 0.16
STEP_H = 16.5
STOMP_BOUNCE = -5.0
COYOTE = 5
JUMP_BUFFER = 6

EMPTY = 0
SOLID = 1
BRICK = 2
QUESTION = 3
PIPE = 4
ONEWAY = 5
POLE = 6
FLAG = 7
LAVA = 8
COIN = 9
USED = 10

SOLID_CODES = frozenset((SOLID, BRICK, QUESTION, PIPE, USED))
CHAR_CODE = {
    ".": EMPTY,
    "#": SOLID,
    "B": BRICK,
    "?": QUESTION,
    "P": PIPE,
    "=": ONEWAY,
    "|": POLE,
    "F": FLAG,
    "~": LAVA,
    "o": COIN,
    "U": USED,
}
CODE_CHAR = {v: k for k, v in CHAR_CODE.items()}

# right, left, jump, run
SPRINT = (True, False, False, True)
WALK = (True, False, False, False)
WAIT = (False, False, False, False)


class Enemy:
    __slots__ = ("x", "y", "vx", "vy", "w", "h", "kind", "alive")

    def __init__(self, x: float, y: float, kind: str):
        self.kind = kind
        self.alive = True
        self.vx = -0.55 if kind == "G" else (-0.65 if kind == "C" else -0.80)
        self.vy = 0.0
        if kind == "K":
            self.w, self.h = 16.0, 24.0
        elif kind == "C":
            self.w, self.h = 16.0, 12.0
        elif kind == "W":
            self.w, self.h = 16.0, 16.0
            self.vx = -0.70
        else:
            self.w, self.h = 16.0, 16.0
        self.x = x
        self.y = y

    def clone(self) -> "Enemy":
        e = Enemy.__new__(Enemy)
        e.x, e.y, e.vx, e.vy = self.x, self.y, self.vx, self.vy
        e.w, e.h, e.kind, e.alive = self.w, self.h, self.kind, self.alive
        return e


class Level:
    __slots__ = (
        "name",
        "world",
        "stage",
        "theme",
        "w",
        "h",
        "tiles",
        "spawn_x",
        "spawn_y",
        "flag_x",
        "enemies0",
        "rows",
    )

    def __init__(
        self,
        name: str,
        rows: list[str],
        theme: str,
        world: int,
        stage: int,
    ):
        self.name = name
        self.world = world
        self.stage = stage
        self.theme = theme
        self.h = len(rows)
        self.w = len(rows[0])
        if any(len(r) != self.w for r in rows):
            raise ValueError(f"{name}: ragged rows")
        self.rows = tuple(rows)
        tiles = bytearray(self.w * self.h)
        enemies: list[Enemy] = []
        spawn_x = 32.0
        spawn_y = 0.0
        found_spawn = False
        flag_x = (self.w - 4) * TILE
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == "@":
                    tiles[y * self.w + x] = EMPTY
                    spawn_x = x * TILE + 2
                    spawn_y = y * TILE
                    found_spawn = True
                    continue
                if ch in ("G", "K", "W", "C"):
                    tiles[y * self.w + x] = EMPTY
                    ey = y * TILE - (8 if ch == "K" else 0)
                    enemies.append(Enemy(x * TILE, ey, ch))
                    continue
                code = CHAR_CODE.get(ch)
                if code is None:
                    raise ValueError(f"{name}: bad tile {ch!r} at {x},{y}")
                tiles[y * self.w + x] = code
                if ch == "|":
                    flag_x = x * TILE
        self.tiles = tiles
        self.enemies0 = enemies
        self.flag_x = flag_x
        if not found_spawn:
            spawn_x, spawn_y = _default_spawn(self)
        self.spawn_x = spawn_x
        self.spawn_y = spawn_y

    def code_at(self, tx: int, ty: int) -> int:
        if tx < 0 or ty < 0 or tx >= self.w or ty >= self.h:
            return EMPTY
        return self.tiles[ty * self.w + tx]


def _default_spawn(level: Level) -> tuple[float, float]:
    for y in range(level.h):
        for x in range(level.w):
            if level.tiles[y * level.w + x] in SOLID_CODES:
                return x * TILE + 2, (y - 1) * TILE - 1
    return 32.0, 0.0


class State:
    """One instant of a level. `clone` + `step` is the agent's forward model."""

    __slots__ = (
        "level",
        "tiles",
        "px",
        "py",
        "vx",
        "vy",
        "on_ground",
        "face",
        "prev_jump",
        "coins",
        "frame",
        "time_left",
        "dead",
        "won",
        "enemies",
        "stomps",
        "holds",
        "coyote",
        "jump_buffer",
    )

    def __init__(self, level: Level):
        self.level = level
        self.tiles = bytearray(level.tiles)
        self.px = float(level.spawn_x)
        self.py = float(level.spawn_y)
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.face = 1
        self.prev_jump = False
        self.coins = 0
        self.frame = 0
        self.time_left = 400
        self.dead = False
        self.won = False
        self.enemies = [e.clone() for e in level.enemies0]
        self.stomps = 0
        self.holds = 0
        self.coyote = 0
        self.jump_buffer = 0
        self._plant_feet()

    def _plant_feet(self) -> None:
        probe = self._overlap_solid(
            self.px, self.py + 1.0, PLAYER_W, PLAYER_H, self.py + PLAYER_H
        )
        if probe is None:
            return
        _tx, ty, _code = probe
        top = ty * TILE
        gap = top - (self.py + PLAYER_H)
        if 0.0 <= gap <= 1.05:
            self.py = top - PLAYER_H
            self.on_ground = True
            self.coyote = COYOTE

    def clone(self) -> "State":
        s = State.__new__(State)
        s.level = self.level
        s.tiles = bytearray(self.tiles)
        s.px, s.py, s.vx, s.vy = self.px, self.py, self.vx, self.vy
        s.on_ground = self.on_ground
        s.face = self.face
        s.prev_jump = self.prev_jump
        s.coins = self.coins
        s.frame = self.frame
        s.time_left = self.time_left
        s.dead = self.dead
        s.won = self.won
        s.enemies = [e.clone() for e in self.enemies]
        s.stomps = self.stomps
        s.holds = self.holds
        s.coyote = self.coyote
        s.jump_buffer = self.jump_buffer
        return s

    def code(self, tx: int, ty: int) -> int:
        w, h = self.level.w, self.level.h
        if ty < 0:
            return EMPTY
        if tx < 0 or tx >= w:
            return SOLID
        if ty >= h:
            return EMPTY
        return self.tiles[ty * w + tx]

    def _set(self, tx: int, ty: int, code: int) -> None:
        self.tiles[ty * self.level.w + tx] = code

    def step(self, buttons: tuple[bool, bool, bool, bool]) -> None:
        if self.dead or self.won:
            return
        right, left, jump, run = buttons
        if right and left:
            right = left = False

        self._accelerate(right, left, run)
        self._jump_and_fall(jump)
        prev_py = self.py
        self._move_x()
        self._move_y(prev_py)
        self._move_enemies()
        self._combat(prev_py)
        self._collect_and_goal()
        if self.py > self.level.h * TILE:
            self.dead = True
        self.prev_jump = jump
        self.frame += 1
        if self.frame % 24 == 0:
            self.time_left -= 1
            if self.time_left <= 0:
                self.dead = True

    def _accelerate(self, right: bool, left: bool, run: bool) -> None:
        if right:
            target = MAX_RUN if run else MAX_WALK
            self.face = 1
        elif left:
            target = -(MAX_RUN if run else MAX_WALK)
            self.face = -1
        else:
            target = 0.0
        if self.level.theme == "water":
            target = max(-1.25, min(1.25, target))
        if target != 0.0:
            acc = (ACCEL_RUN if run else ACCEL) * (
                1.0 if self.on_ground else AIR_ACCEL_SCALE
            )
            if self.vx < target:
                self.vx = target if self.vx + acc > target else self.vx + acc
            elif self.vx > target:
                self.vx = target if self.vx - acc < target else self.vx - acc
        elif self.on_ground:
            if self.vx > 0:
                self.vx = 0.0 if self.vx < FRICTION else self.vx - FRICTION
            elif self.vx < 0:
                self.vx = 0.0 if self.vx > -FRICTION else self.vx + FRICTION

    def _jump_and_fall(self, jump: bool) -> None:
        if self.level.theme == "water":
            self._swim(jump)
            return
        if self.on_ground:
            self.coyote = COYOTE
        elif self.coyote > 0:
            self.coyote -= 1
        if jump and not self.prev_jump:
            self.jump_buffer = JUMP_BUFFER
        can_jump = self.on_ground or self.coyote > 0
        if self.jump_buffer > 0 and can_jump and self.vy >= 0.0:
            self.vy = JUMP_V
            self.on_ground = False
            self.coyote = 0
            self.jump_buffer = 0
            self.holds = 1
        elif self.jump_buffer > 0:
            self.jump_buffer -= 1
        if not self.on_ground:
            if jump and self.vy < 0.0 and self.holds > 0 and self.holds < 18:
                self.vy += HOLD_GRAVITY
                self.holds += 1
            else:
                self.vy += GRAVITY
                if self.vy < CUT_V and not jump:
                    self.vy = CUT_V
                self.holds = 0
            if self.vy > MAX_FALL:
                self.vy = MAX_FALL

    def _swim(self, jump: bool) -> None:
        """Water courses: tap or hold jump to stroke upward, otherwise drift down."""
        if self.on_ground and jump and not self.prev_jump:
            self.vy = -2.3
            self.on_ground = False
            self.holds = 1
            return
        if self.on_ground:
            self.vy = 0.0
            return
        if jump:
            self.vy -= 0.16
        else:
            self.vy += 0.055
        if self.vy < -2.05:
            self.vy = -2.05
        if self.vy > 1.35:
            self.vy = 1.35

    def _overlap_solid(self, x: float, y: float, w: float, h: float, oneway_from: float | None) -> tuple[int, int, int] | None:
        """Return (tx, ty, code) of a blocking tile, if any.

        oneway_from is the previous bottom edge; one-way tiles block only
        when falling onto them from above.
        """
        x0 = int(x // TILE)
        y0 = int(y // TILE)
        x1 = int((x + w - 0.01) // TILE)
        y1 = int((y + h - 0.01) // TILE)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                code = self.code(tx, ty)
                if code in SOLID_CODES:
                    return tx, ty, code
                if code == ONEWAY and oneway_from is not None:
                    top = ty * TILE
                    if oneway_from <= top + 0.5 and y + h >= top:
                        return tx, ty, code
        return None

    def _move_x(self) -> None:
        if self.vx == 0.0:
            return
        nx = self.px + self.vx
        if nx < 0.0:
            self.px = 0.0
            self.vx = 0.0
            return
        hit = self._overlap_solid(nx, self.py, PLAYER_W, PLAYER_H, None)
        if hit is None:
            self.px = nx
            return
        tx, ty, _code = hit
        feet = self.py + PLAYER_H
        top = ty * TILE
        # Step onto a short curb or stair instead of bonking into it.
        if self.vy >= 0.0 and 0.0 < feet - top <= STEP_H:
            head = self._overlap_solid(nx, top - PLAYER_H, PLAYER_W, PLAYER_H - 1, None)
            if head is None:
                self.py = top - PLAYER_H
                self.px = nx
                self.vy = 0.0
                return
        if self.vx > 0:
            self.px = tx * TILE - PLAYER_W
        else:
            self.px = (tx + 1) * TILE
        self.vx = 0.0

    def _move_y(self, prev_py: float) -> None:
        self.on_ground = False
        ny = self.py + self.vy
        prev_bottom = prev_py + PLAYER_H
        if self.vy >= 0:
            hit = self._overlap_solid(self.px, ny, PLAYER_W, PLAYER_H, prev_bottom)
            if hit is None:
                probe = self._overlap_solid(
                    self.px, ny + 1.0, PLAYER_W, PLAYER_H, prev_bottom
                )
                if probe is not None:
                    _tx, ty, _code = probe
                    top = ty * TILE
                    gap = top - (ny + PLAYER_H)
                    if 0.0 <= gap <= 1.05:
                        self.py = top - PLAYER_H
                        self.vy = 0.0
                        self.on_ground = True
                        self.holds = 0
                        return
                self.py = ny
                return
            _tx, ty, _code = hit
            self.py = ty * TILE - PLAYER_H
            self.vy = 0.0
            self.on_ground = True
            self.holds = 0
            return
        hit = self._overlap_solid(self.px, ny, PLAYER_W, PLAYER_H, None)
        if hit is None:
            self.py = ny
            return
        tx, ty, code = hit
        self.py = (ty + 1) * TILE
        self.vy = 0.4
        self.holds = 0
        if code == QUESTION:
            self._set(tx, ty, USED)
            self.coins += 1
        elif code == BRICK:
            self._set(tx, ty, EMPTY)

    def _move_enemies(self) -> None:
        for e in self.enemies:
            if not e.alive:
                continue
            if e.kind == "C":
                e.x += e.vx
                wall = self._overlap_solid(e.x, e.y, e.w, e.h, None)
                if wall is not None or e.x < 0:
                    e.x -= e.vx
                    e.vx = -e.vx
                continue
            if e.kind == "W" and self.frame % 48 == 0 and _grounded_enemy(self, e):
                e.vy = -5.2
            e.vy = min(MAX_FALL, e.vy + GRAVITY)
            e.x += e.vx
            wall = self._overlap_solid(e.x, e.y, e.w, e.h, None)
            if wall is not None or e.x < 0:
                e.x -= e.vx
                e.vx = -e.vx
            e.y += e.vy
            prev_bottom = e.y - e.vy + e.h
            ground = self._overlap_solid(e.x, e.y, e.w, e.h, prev_bottom)
            if ground is not None and e.vy >= 0:
                _tx, ty, _code = ground
                e.y = ty * TILE - e.h
                e.vy = 0.0
            elif ground is not None and e.vy < 0:
                e.y -= e.vy
                e.vy = 0.0
            if e.y > self.level.h * TILE:
                e.alive = False
                continue
            # Turn around before walking off a ledge (red-koopa style).
            if e.vy == 0.0:
                front = e.x + e.w + 1 if e.vx > 0 else e.x - 1
                fx = int(front // TILE)
                fy = int((e.y + e.h + 1) // TILE)
                below = self.code(fx, fy)
                if below not in SOLID_CODES and below != ONEWAY:
                    e.vx = -e.vx

    def _combat(self, prev_py: float) -> None:
        if self.dead or self.won:
            return
        prev_feet = prev_py + PLAYER_H
        feet = self.py + PLAYER_H
        for e in self.enemies:
            if not e.alive:
                continue
            if not _rects_overlap(self.px, self.py, PLAYER_W, PLAYER_H, e.x, e.y, e.w, e.h):
                continue
            stomp = self.vy > 0 and prev_feet <= e.y + 8 and feet <= e.y + e.h * 0.65
            if stomp:
                e.alive = False
                self.vy = STOMP_BOUNCE
                self.on_ground = False
                self.stomps += 1
                self.py = e.y - PLAYER_H
            else:
                self.dead = True
                return

    def _collect_and_goal(self) -> None:
        if self.dead:
            return
        x0 = int(self.px // TILE)
        y0 = int(self.py // TILE)
        x1 = int((self.px + PLAYER_W - 0.01) // TILE)
        y1 = int((self.py + PLAYER_H - 0.01) // TILE)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                code = self.code(tx, ty)
                if code == COIN:
                    self._set(tx, ty, EMPTY)
                    self.coins += 1
                elif code == LAVA:
                    self.dead = True
                    return
                elif code in (POLE, FLAG):
                    self.won = True
                    self.vx = 0.0
                    return

    def snapshot(self) -> dict:
        w = self.level.w
        changed = []
        base = self.level.tiles
        tiles = self.tiles
        for i, (a, b) in enumerate(zip(base, tiles)):
            if a != b:
                changed.append((i % w, i // w, int(b)))
        return {
            "px": round(self.px, 2),
            "py": round(self.py, 2),
            "vx": round(self.vx, 2),
            "vy": round(self.vy, 2),
            "face": self.face,
            "ground": 1 if self.on_ground else 0,
            "coins": self.coins,
            "time": self.time_left,
            "won": 1 if self.won else 0,
            "dead": 1 if self.dead else 0,
            "enemies": [
                [round(e.x, 2), round(e.y, 2), 1 if e.alive else 0] for e in self.enemies
            ],
            "changed": changed,
        }


def _grounded_enemy(state: State, e: Enemy) -> bool:
    fy = int((e.y + e.h + 1) // TILE)
    fx = int((e.x + e.w * 0.5) // TILE)
    return state.code(fx, fy) in SOLID_CODES or state.code(fx, fy) == ONEWAY


def _rects_overlap(ax, ay, aw, ah, bx, by, bw, bh) -> bool:
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def project_landing(state: State) -> tuple[float, bool]:
    """Fast ballistic guess of where the current arc meets ground.

    Used as a search heuristic. The real step() remains the source of truth.
    """
    if state.on_ground:
        return state.px, True
    x, y, vx, vy = state.px, state.py, state.vx, state.vy
    hold = state.holds
    for _ in range(56):
        if vy < 0.0 and hold > 0 and hold < 18:
            vy += HOLD_GRAVITY
            hold += 1
        else:
            vy += GRAVITY
        if vy > MAX_FALL:
            vy = MAX_FALL
        x += vx
        y += vy
        feet = y + PLAYER_H
        if feet > state.level.h * TILE + 8:
            return x, False
        tx0 = int(x // TILE)
        tx1 = int((x + PLAYER_W - 0.01) // TILE)
        ty = int(feet // TILE)
        for tx in range(tx0, tx1 + 1):
            code = state.code(tx, ty)
            if code in SOLID_CODES or code == ONEWAY:
                return x, True
    return x, False


def max_jump_tiles() -> dict[str, float]:
    """Measure jump reach on an empty field so levels stay fair."""
    rows = ["." * 40 for _ in range(18)]
    ground = list("#" * 40)
    rows[16] = "".join(ground)
    rows[17] = "".join(ground)
    # spawn in the air-friendly spot
    chars = [list(r) for r in rows]
    chars[15][2] = "@"
    level = Level("cal", ["".join(r) for r in chars], "overworld", 1, 1)
    results = {}
    for name, run, hold in (
        ("walk_short", False, 2),
        ("walk_full", False, 30),
        ("run_full", True, 30),
    ):
        st = State(level)
        # build speed
        for _ in range(40):
            st.step((True, False, False, run))
        x0 = st.px
        for i in range(70):
            st.step((True, False, i < hold, run))
            if st.on_ground and i > 4:
                break
        results[name] = (st.px - x0) / TILE
    # jump height
    st = State(level)
    y0 = st.py
    peak = y0
    for i in range(70):
        st.step((False, False, i < 30, False))
        peak = min(peak, st.py)
        if st.on_ground and i > 4:
            break
    results["height"] = (y0 - peak) / TILE
    return results
