"""Thirty-two courses in the original game's world order.

Each slot uses that game's course type: overworld, underground, athletic,
underwater, or castle. The geometry is original and stays inside this
engine's jump. These are not Nintendo's maps.
"""

from __future__ import annotations

import random

from mario.engine import Level

# (theme passed to the renderer, builder kind)
COURSES = {
    (1, 1): ("overworld", "ground"),
    (1, 2): ("underground", "underground"),
    (1, 3): ("athletic", "athletic"),
    (1, 4): ("castle", "castle"),
    (2, 1): ("overworld", "ground"),
    (2, 2): ("water", "water"),
    (2, 3): ("overworld", "ground"),
    (2, 4): ("castle", "castle"),
    (3, 1): ("overworld", "ground"),
    (3, 2): ("overworld", "ground"),
    (3, 3): ("athletic", "athletic"),
    (3, 4): ("castle", "castle"),
    (4, 1): ("overworld", "ground"),
    (4, 2): ("underground", "underground"),
    (4, 3): ("athletic", "athletic"),
    (4, 4): ("castle", "castle"),
    (5, 1): ("overworld", "ground"),
    (5, 2): ("water", "water"),
    (5, 3): ("athletic", "athletic"),
    (5, 4): ("castle", "castle"),
    (6, 1): ("overworld", "ground"),
    (6, 2): ("overworld", "ground"),
    (6, 3): ("athletic", "athletic"),
    (6, 4): ("castle", "castle"),
    (7, 1): ("overworld", "ground"),
    (7, 2): ("water", "water"),
    (7, 3): ("athletic", "athletic"),
    (7, 4): ("castle", "castle"),
    (8, 1): ("overworld", "ground"),
    (8, 2): ("underground", "underground"),
    (8, 3): ("athletic", "athletic"),
    (8, 4): ("castle", "castle"),
}


class Builder:
    def __init__(self) -> None:
        self.h = 15
        self.gy = 12
        self.cols: list[list[str]] = []

    def add(self, n: int, ground: bool = True, lava: bool = False) -> int:
        start = len(self.cols)
        for _ in range(n):
            col = ["."] * self.h
            if ground:
                for y in range(self.gy, self.h):
                    col[y] = "#"
            elif lava:
                col[self.h - 1] = "~"
            self.cols.append(col)
        return start

    def set(self, x: int, y: int, ch: str) -> None:
        if 0 <= x < len(self.cols) and 0 <= y < self.h and self.cols[x][y] == ".":
            self.cols[x][y] = ch

    def force(self, x: int, y: int, ch: str) -> None:
        self.cols[x][y] = ch

    def rows(self) -> list[str]:
        width = len(self.cols)
        return ["".join(self.cols[x][y] for x in range(width)) for y in range(self.h)]

    def pipe(self, height: int) -> None:
        x = self.add(2, ground=True)
        for dx in range(2):
            for dy in range(height):
                self.force(x + dx, self.gy - 1 - dy, "P")

    def stairs(self) -> None:
        for i in range(4):
            xs = self.add(1, ground=True)
            for s in range(i + 1):
                self.force(xs, self.gy - 1 - s, "#")
        for i in range(3, -1, -1):
            xs = self.add(1, ground=True)
            for s in range(i):
                self.force(xs, self.gy - 1 - s, "#")

    def flag(self) -> None:
        self.add(6, ground=True)
        fx = len(self.cols)
        self.add(4, ground=True)
        pole = fx + 1
        for y in range(self.gy - 6, self.gy):
            self.force(pole, y, "|")
        self.force(pole, self.gy - 6, "F")

    def ceiling(self) -> None:
        # Keep rows 0-1 clear so the HUD sits on open sky or black.
        for x in range(len(self.cols)):
            if self.cols[x][2] == "." and x % 6 != 0:
                self.cols[x][2] = "B"


def _enemy(world: int, rng: random.Random, water: bool = False) -> str:
    if water:
        return "C"
    if world >= 6 and rng.random() < 0.2:
        return "W"
    if world >= 3 and rng.random() < 0.4:
        return "K"
    return "G"


def _gap(world: int, rng: random.Random) -> int:
    cap = min(5, 2 + (world >= 3) + (world >= 5) + (world >= 7))
    return rng.randint(max(2, cap - 1), cap)


def _ground(b: Builder, world: int, rng: random.Random, underground: bool) -> None:
    b.add(9, ground=True)
    b.force(3, b.gy - 1, "@")
    loops = 2 + (world >= 2) + (world >= 4) + (world >= 7)
    if underground:
        loops += 1
    for i in range(loops):
        span = 9 + (i % 2)
        x0 = b.add(span, ground=True)
        b.set(x0 + 2, b.gy - 1, "o")
        b.set(x0 + 3, b.gy - 1, "o")
        if world <= 3 and i == 0:
            b.set(x0 + 5, b.gy - 4, "?")
            b.set(x0 + 6, b.gy - 4, "B")
        if rng.random() < 0.85:
            b.force(x0 + 4, b.gy - 1, _enemy(world, rng))
        b.add(_gap(world, rng), ground=False, lava=False)
        b.add(8, ground=True)
        if i % 2 == 0 and not underground:
            b.pipe(2 if world < 6 else 3)
            b.add(7, ground=True)
    if not underground:
        b.stairs()
        b.add(3, ground=True)
    b.flag()
    if underground:
        b.ceiling()


def _athletic(b: Builder, world: int, rng: random.Random) -> None:
    b.add(10, ground=True)
    b.force(3, b.gy - 1, "@")
    crossings = 1 + (world >= 4) + (world >= 7)
    for i in range(crossings):
        b.add(6, ground=True)
        xg = b.add(12, ground=False)
        for k in range(5):
            b.force(xg + 3 + k, b.gy - 2, "=")
        b.add(8, ground=True)
        if rng.random() < 0.7:
            x0 = len(b.cols) - 5
            b.force(x0, b.gy - 1, _enemy(world, rng))
        if i + 1 < crossings or world >= 5:
            b.add(_gap(world, rng), ground=False)
            b.add(8, ground=True)
    b.stairs()
    b.add(3, ground=True)
    b.flag()


def _castle(b: Builder, world: int, rng: random.Random) -> None:
    b.add(8, ground=True)
    b.force(3, b.gy - 1, "@")
    loops = 2 + (world >= 3) + (world >= 6)
    for i in range(loops):
        span = 8
        x0 = b.add(span, ground=True)
        if rng.random() < 0.8:
            b.force(x0 + 4, b.gy - 1, "K" if world >= 2 else "G")
        width = min(5, 2 + (world >= 4) + (world >= 8))
        b.add(width, ground=False, lava=True)
        b.add(7, ground=True)
        if i % 2 == 0:
            b.pipe(2 if world < 7 else 3)
            b.add(6, ground=True)
    # The bridge before the pole.
    bridge = b.add(8, ground=True)
    b.force(bridge + 3, b.gy - 1, "K" if world >= 4 else "G")
    b.flag()
    b.ceiling()


def _water(b: Builder, world: int, rng: random.Random) -> None:
    b.add(10, ground=True)
    b.force(3, b.gy - 1, "@")
    loops = 2 + (world >= 5) + (world >= 7)
    for _ in range(loops):
        span = 11
        x0 = b.add(span, ground=True)
        b.set(x0 + 2, b.gy - 3, "o")
        b.set(x0 + 3, b.gy - 3, "o")
        b.force(x0 + 6, b.gy - 1, "C")
        if world >= 5 and rng.random() < 0.5:
            b.force(x0 + 8, b.gy - 3, "C")
        b.add(rng.randint(2, 3), ground=False)
        b.add(8, ground=True)
    b.add(6, ground=True)
    b.flag()


def build_level(world: int, stage: int) -> Level:
    theme, kind = COURSES[(world, stage)]
    rng = random.Random(80_000 + world * 40 + stage)
    b = Builder()
    if kind == "water":
        _water(b, world, rng)
    elif kind == "athletic":
        _athletic(b, world, rng)
    elif kind == "castle":
        _castle(b, world, rng)
    else:
        _ground(b, world, rng, underground=(kind == "underground"))
    return Level(f"{world}-{stage}", b.rows(), theme, world, stage)


def campaign() -> list[Level]:
    return [build_level(world, stage) for world in range(1, 9) for stage in range(1, 5)]
