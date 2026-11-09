#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exam Dice -- pick random exam questions with a dice.

One file, standard library only, two interfaces:

* a window interface (tkinter, bundled with Python on Windows)
* a terminal interface (ANSI escape codes; works on Linux/macOS and
  Windows 10+ terminals; falls back to a simple line mode when piped)

The dice defaults to 6 sides; the number of sides can be changed at any
time (2-30).  A "series" guarantees that every question comes up at most
once: if the dice rolls a number that was already drawn in the current
series, it re-rolls automatically (and tells you why).  Starting a new
series makes all numbers available again.

Usage:
    python exam_dice.py              # window if possible, else terminal
    python exam_dice.py --cli        # force the terminal interface
    python exam_dice.py --gui        # force the window interface
    python exam_dice.py --sides 12   # start with a d12
    python exam_dice.py --selftest   # logic + GUI smoke test

Terminal keys:  SPACE/Enter roll · N new series · S sides · Q quit
Window:         ROLL button / Space · "Series" menu · Ctrl+N · spinbox
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import shutil
import sys
import time

try:
    import tkinter as tk
except ImportError:  # pragma: no cover - python without tcl/tk
    tk = None

MIN_SIDES = 2
MAX_SIDES = 30

# --------------------------------------------------------------------------
# core logic (shared by both interfaces)
# --------------------------------------------------------------------------


class Series:
    """One series of rolls: each number 1..sides comes up at most once."""

    def __init__(self, sides: int, rng: random.Random | None = None):
        if not MIN_SIDES <= sides <= MAX_SIDES:
            raise ValueError(f"sides must be {MIN_SIDES}..{MAX_SIDES}")
        self.sides = sides
        self.used: set[int] = set()
        self.rng = rng or random.Random()

    @property
    def complete(self) -> bool:
        return len(self.used) >= self.sides

    def reset(self) -> None:
        self.used.clear()

    def draws(self):
        """Yield (value, is_final) tuples for one user-visible roll.

        A number that was already drawn in this series is re-rolled
        automatically.  The tuple with is_final=True is the accepted
        result (recorded in .used) and the last one yielded.
        """
        while True:
            v = self.rng.randint(1, self.sides)
            if v not in self.used:
                self.used.add(v)
                yield v, True
                return
            yield v, False


# --------------------------------------------------------------------------
# dice shapes (2..30 sides)
# --------------------------------------------------------------------------

# standard dice get their classic silhouette, the rest get a generic one
CLASSIC_SHAPES = {
    2: "coin",      # heads/tails
    3: "triangle",
    4: "triangle",  # tetrahedron
    5: "pentagon",
    6: "square",    # cube, shown with pips
    8: "diamond",   # octahedron
    10: "kite",     # pentagonal trapezohedron
    12: "pentagon", # dodecahedron
    20: "hexagon",  # icosahedron
}


def shape_name(sides: int) -> str:
    s = CLASSIC_SHAPES.get(sides)
    if s:
        return s
    return "polygon" if sides <= 12 else "oval"


# --------------------------------------------------------------------------
# terminal interface
# --------------------------------------------------------------------------

RESET, DIM = "\x1b[0m", "\x1b[2m"
BOLD_YELLOW, BOLD_GREEN, BOLD_RED = "\x1b[1;93m", "\x1b[1;92m", "\x1b[1;91m"
HIDE_CUR, SHOW_CUR = "\x1b[?25l", "\x1b[?25h"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# pip positions on a 3x3 grid (row, col), rows/cols numbered 0..2
PIP_LAYOUT = {
    1: [(1, 1)],
    2: [(0, 0), (2, 2)],
    3: [(0, 0), (1, 1), (2, 2)],
    4: [(0, 0), (0, 2), (2, 0), (2, 2)],
    5: [(0, 0), (0, 2), (1, 1), (2, 0), (2, 2)],
    6: [(0, 0), (0, 2), (1, 0), (1, 2), (2, 0), (2, 2)],
}


def _plain(s: str) -> str:
    """Length of a string as seen on screen (ANSI codes stripped)."""
    return ANSI_RE.sub("", s)


def _center(inner: int, v, style: str = "") -> str:
    """Put v (optionally styled) in the middle of a fixed-width field."""
    t = str(v)
    lpad = (inner - len(t)) // 2
    rpad = inner - len(t) - lpad
    body = f"{style}{t}{RESET}" if style else t
    return " " * lpad + body + " " * rpad


def _art_d6(v, style):
    grid = [[" "] * 7 for _ in range(3)]
    mark = f"{style}\u25cf{RESET}" if style else "\u25cf"
    for r, c in PIP_LAYOUT.get(v, []):
        grid[r][c * 2 + 1] = mark
    rows = ["\u2502" + "".join(row) + "\u2502" for row in grid]
    return ["\u250c───────\u2510", *rows, "\u2514───────\u2518"]


def _art_triangle(v, style):
    return ["   /\\", "  /  \\", f" /{_center(4, v, style)}\\", "/______\\"]


def _art_coin(v, style):
    return ["  .----.", f" /{_center(6, v, style)}\\", " \\      /", "  '----'"]


def _art_diamond(v, style):
    return ["  /\\", " /  \\", f"<{_center(4, v, style)}>", " \\  /", "  \\/"]


def _art_kite(v, style):
    return [
        "   /\\",
        "  /  \\",
        " /    \\",
        f"<{_center(6, v, style)}>",
        " \\    /",
        "  \\  /",
        "   \\/",
    ]


def _art_pentagon(v, style):
    return [
        "   ____",
        "  /    \\",
        " /      \\",
        f"<{_center(8, v, style)}>",
        " \\      /",
        "  \\____/",
    ]


def _art_hexagon(v, style):
    return [
        "   ____",
        "  /    \\",
        " /      \\",
        f"|{_center(8, v, style)}|",
        " \\      /",
        "  \\____/",
    ]


def _art_box(v, style):
    return [
        "\u250c───────\u2510",
        "\u2502       \u2502",
        f"\u2502{_center(7, v, style)}\u2502",
        "\u2502       \u2502",
        "\u2514───────\u2518",
    ]


_ART = {
    2: _art_coin,
    3: _art_triangle,
    4: _art_triangle,
    6: _art_d6,
    8: _art_diamond,
    10: _art_kite,
    12: _art_pentagon,
    20: _art_hexagon,
}


def die_art(sides: int, value, style: str = "") -> list[str]:
    """ASCII picture of the die for the given number of sides."""
    if value == "?":  # idle face before the first roll
        return _art_box("?", style)
    return _ART.get(sides, _art_box)(value, style)


class KeyReader:
    """Cross-platform single key presses in raw mode."""

    def start(self):
        if os.name == "nt":
            import msvcrt

            self._msvcrt = msvcrt
        else:
            import termios
            import tty

            self._termios, self._tty = termios, tty
            self._saved = termios.tcgetattr(sys.stdin)
            self._tty.setcbreak(sys.stdin)

    def stop(self):
        if os.name != "nt":
            self._termios.tcsetattr(
                sys.stdin, self._termios.TCSADRAIN, self._saved
            )

    def getch(self) -> str:
        if os.name == "nt":
            ch = self._msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # prefix of a special key
                self._msvcrt.getwch()
                return ""
            return ch
        ch = sys.stdin.read(1)
        if ch == "\x1b":  # Esc, or the start of an escape sequence
            import select

            if select.select([sys.stdin], [], [], 0.03)[0]:
                while select.select([sys.stdin], [], [], 0.01)[0]:
                    sys.stdin.read(1)
                return ""  # arrow key etc. - ignore
        return ch

    def drain(self):
        """Drop key presses buffered while an animation was running."""
        if os.name == "nt":
            while self._msvcrt.kbhit():
                self._msvcrt.getwch()
        else:
            import select

            while select.select([sys.stdin], [], [], 0)[0]:
                if not sys.stdin.read(1):
                    break


class TerminalApp:
    HELP = f"[SPACE] roll   [N] new series   [S] sides ({MIN_SIDES}-{MAX_SIDES})   [Q] quit"

    def __init__(self, sides: int):
        self.series = Series(sides)
        self.face = ("?", DIM)
        self.message = ""
        self._nlines = 0
        self._out = sys.stdout

    # -- rendering -----------------------------------------------------

    def _block(self) -> list[str]:
        s = self.series
        used = " ".join(map(str, sorted(s.used))) or "-"
        art = die_art(s.sides, *self.face)
        w = max(len(_plain(l)) for l in art)
        art = [l + " " * (w - len(_plain(l))) for l in art]  # common width
        cap = f"{DIM}d{s.sides}{RESET}"
        head = f"EXAM DICE \u00b7 d{s.sides} \u00b7 drawn {len(s.used)}/{s.sides}: {used}"
        return [head, "", *art, cap, "", self.message, "", DIM + self.HELP + RESET]

    def _render(self):
        cols = shutil.get_terminal_size().columns
        lines = self._block()
        if self._nlines > 1:
            self._out.write(f"\x1b[{self._nlines - 1}F")
        elif self._nlines == 1:
            self._out.write("\r")
        for i, line in enumerate(lines):
            pad = max(0, (cols - len(_plain(line))) // 2)
            self._out.write("\x1b[2K" + " " * pad + line)
            if i < len(lines) - 1:
                self._out.write("\n")
        self._out.flush()
        self._nlines = len(lines)

    def _display(self, value, style):
        self.face = (value, style)
        self._render()

    # -- actions ---------------------------------------------------------

    def _animate(self, value, final: bool):
        """Tumble through random faces and settle on the result."""
        rng = random.Random()
        frames = 14
        for i in range(frames):
            self._display(rng.randint(1, self.series.sides), BOLD_YELLOW)
            time.sleep(0.03 + 0.15 * (i / frames) ** 2)
        self._display(value, BOLD_GREEN if final else BOLD_RED)

    def do_roll(self):
        if self.series.complete:
            self.message = "all numbers drawn -- press N to start a new series"
            self._render()
            return
        self.message = ""
        for v, final in self.series.draws():
            self._animate(v, final)
            if final:
                self.message = (
                    f"\u2192 question #{v}  "
                    f"({len(self.series.used)}/{self.series.sides} drawn)"
                )
                if self.series.complete:
                    self.message += "  -- series complete, N for a new one"
            else:
                self.message = f"{v} already drawn this series -- rolling again..."
                self._render()
                time.sleep(0.85)
        self._render()

    def new_series(self):
        self.series.reset()
        self.message = "new series -- every number is available again"
        self._display("?", DIM)

    def ask_sides(self, keys: KeyReader):
        keys.stop()
        try:
            raw = input(
                f"\nsides ({MIN_SIDES}-{MAX_SIDES}, Enter keeps d{self.series.sides}): "
            ).strip()
        finally:
            keys.start()
        self._out.write("\x1b[2J\x1b[H")
        self._nlines = 0
        if raw:
            try:
                n = int(raw)
            except ValueError:
                self.message = "not a number -- sides unchanged"
            else:
                if MIN_SIDES <= n <= MAX_SIDES:
                    self.series = Series(n)
                    self.message = f"d{n} -- new series started"
                else:
                    self.message = f"sides must be {MIN_SIDES}-{MAX_SIDES} -- unchanged"
        self._display("?", DIM)

    # -- main loops ------------------------------------------------------

    def run(self):
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return self.run_line_mode()
        os.system("")  # enable ANSI escapes on Windows 10+
        keys = KeyReader()
        keys.start()
        self._out.write("\x1b[2J\x1b[H" + HIDE_CUR)
        try:
            self._render()
            while True:
                k = (keys.getch() or "").lower()
                if k in (" ", "\r", "\n"):
                    self.do_roll()
                    keys.drain()
                elif k == "n":
                    self.new_series()
                elif k == "s":
                    self.ask_sides(keys)
                elif k in ("q", "\x1b"):
                    break
                elif k == "\x03":
                    raise KeyboardInterrupt
        finally:
            keys.stop()
            self._out.write(SHOW_CUR + "\n")

    def run_line_mode(self):
        """Simple fallback when stdin/stdout is not a real terminal."""
        print("EXAM DICE (line mode)")
        while True:
            s = self.series
            used = " ".join(map(str, sorted(s.used))) or "-"
            print(f"\nd{s.sides} \u00b7 drawn {len(s.used)}/{s.sides}: {used}")
            cmd = input("[Enter]=roll  n=new series  s<N>=set sides  q=quit > ").strip().lower()
            if cmd in ("", "r", "roll"):
                if s.complete:
                    print("all numbers drawn -- start a new series (n)")
                    continue
                for v, final in s.draws():
                    suffix = "" if final else "  -- already drawn, rolling again..."
                    print(f"  rolled {v}{suffix}")
            elif cmd == "n":
                s.reset()
                print("new series started")
            elif cmd.startswith("s"):
                arg = cmd[1:].strip().lstrip("=").strip()
                try:
                    n = int(arg)
                except ValueError:
                    print(f"give the number of sides, e.g. s12 ({MIN_SIDES}-{MAX_SIDES})")
                    continue
                if not MIN_SIDES <= n <= MAX_SIDES:
                    print(f"sides must be {MIN_SIDES}-{MAX_SIDES}")
                    continue
                self.series = Series(n)
                print(f"d{n} -- new series started")
            elif cmd in ("q", "quit", "exit"):
                break
            else:
                print("unknown command")


# --------------------------------------------------------------------------
# window interface (tkinter)
# --------------------------------------------------------------------------


class DiceGui:
    FACE, EDGE, PIP = "#faf6ea", "#3d3a33", "#2b2620"
    OK, WARN, MUTED = "#1e7e46", "#b26a00", "#8a8a8a"
    BG = "#f4f1ea"

    def __init__(self, root: "tk.Tk", sides: int):
        self.root = root
        self.series = Series(sides)
        self.animating = False
        self.last: int | None = None
        self._phase = random.uniform(0, math.pi)

        root.title("Exam Dice")
        root.configure(bg=self.BG)
        root.resizable(False, False)
        self._build_menu()

        top = tk.Frame(root, bg=self.BG)
        top.pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(top, text="Sides:", bg=self.BG).pack(side="left")
        self.sides_var = tk.StringVar(value=str(sides))
        spin = tk.Spinbox(
            top, from_=MIN_SIDES, to=MAX_SIDES, width=4, justify="center",
            textvariable=self.sides_var, command=self.on_sides_spin, takefocus=0,
        )
        spin.bind("<Return>", lambda _e: self.on_sides_spin())
        spin.bind("<FocusOut>", lambda _e: self.on_sides_spin())
        spin.pack(side="left", padx=(4, 12))
        tk.Button(top, text="New series", command=self.new_series, takefocus=0).pack(side="right")
        self.roll_btn = tk.Button(
            top, text="ROLL", font=("Helvetica", 12, "bold"),
            width=10, command=self.start_roll, takefocus=0,
        )
        self.roll_btn.pack(side="right", padx=6)

        self.canvas = tk.Canvas(root, width=460, height=410, bg="#ffffff", highlightthickness=0)
        self.canvas.pack(padx=12, pady=2)

        self.chip_area = tk.Frame(root, bg=self.BG)
        self.chip_area.pack(padx=12, pady=4)
        self.chips: dict[int, "tk.Label"] = {}
        self.build_chips()

        self.status_var = tk.StringVar(
            value=f"d{sides} -- press ROLL (or Space) to draw a question"
        )
        self.status = tk.Label(
            root, textvariable=self.status_var, bg=self.BG,
            fg="#333333", anchor="w", font=("Helvetica", 11),
        )
        self.status.pack(fill="x", padx=14, pady=(2, 10))

        root.bind("<Return>", lambda _e: self.start_roll())
        root.bind("<space>", lambda _e: self.start_roll())
        root.bind("<Control-n>", lambda _e: self.new_series())
        root.bind("<Control-q>", lambda _e: root.destroy())
        self.draw_face("?")

    # -- menu ----------------------------------------------------------

    def _build_menu(self):
        m = tk.Menu(self.root)
        menu = tk.Menu(m, tearoff=0)
        menu.add_command(label="Roll", accelerator="Space", command=self.start_roll)
        menu.add_command(label="New series", accelerator="Ctrl+N", command=self.new_series)
        menu.add_separator()
        menu.add_command(label="Change sides...", command=self.ask_sides)
        menu.add_separator()
        menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.root.destroy)
        m.add_cascade(label="Series", menu=menu)
        self.root.config(menu=m)

    # -- chips (series progress) ----------------------------------------

    def build_chips(self):
        for w in self.chip_area.winfo_children():
            w.destroy()
        self.chips = {}
        s = self.series.sides
        cols = s if s <= 15 else 15
        for i in range(1, s + 1):
            lbl = tk.Label(
                self.chip_area, text=str(i), width=2, relief="groove", bd=1,
                font=("Helvetica", 10), bg="#ffffff", fg=self.MUTED,
            )
            lbl.grid(row=(i - 1) // cols, column=(i - 1) % cols, padx=2, pady=2)
            self.chips[i] = lbl
        self.update_chips()

    def update_chips(self):
        for i, lbl in self.chips.items():
            if i in self.series.used:
                if i == self.last:
                    lbl.config(bg="#14532d", fg="white")
                else:
                    lbl.config(bg="#2e8b57", fg="white")
            else:
                lbl.config(bg="#ffffff", fg=self.MUTED)

    # -- drawing ---------------------------------------------------------

    @staticmethod
    def _ngon(cx, cy, r, n, rotate=0.0):
        a0 = math.radians(rotate - 90)
        pts = []
        for k in range(n):
            a = a0 + 2 * math.pi * k / n
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        return pts

    @staticmethod
    def _rot(pts, cx, cy, deg):
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        out = []
        for i in range(0, len(pts), 2):
            x, y = pts[i] - cx, pts[i + 1] - cy
            out += [cx + x * ca - y * sa, cy + x * sa + y * ca]
        return out

    def draw_face(self, value, *, angle=0.0, scale=1.0, coin_w=1.0, result=None):
        """Draw the die; result=None while tumbling, 'ok' or 'dup' settled."""
        c = self.canvas
        c.delete("die")
        cx, cy = 230, 190
        r = 150 * max(scale, 0.55)
        sides = self.series.sides
        shape = shape_name(sides)
        outline = self.EDGE if result is None else (
            self.OK if result == "ok" else self.WARN
        )
        kw = dict(fill=self.FACE, outline=outline, width=3 if result is None else 6,
                  tags="die")

        if shape == "coin":  # d2: an ellipse whose width shrinks while spinning
            rw = r * max(coin_w, 0.12)
            c.create_oval(cx - rw, cy - r, cx + rw, cy + r, **kw)
            c.create_oval(cx - rw * 0.84, cy - r * 0.84,
                          cx + rw * 0.84, cy + r * 0.84,
                          outline=outline, width=1, tags="die")
            if coin_w > 0.45:  # face visible only when not edge-on
                c.create_text(cx, cy, text=str(value),
                              font=("Helvetica", int(r * 0.6), "bold"),
                              fill=self.PIP, tags="die")
            return

        pts = None
        if shape == "triangle":
            pts, text_xy, f = self._ngon(cx, cy, r, 3), (cx, cy + r * 0.20), 0.40
        elif shape == "square":
            pts, text_xy, f = self._ngon(cx, cy, r * 0.92, 4, 45), (cx, cy), 0.60
        elif shape == "diamond":
            pts, text_xy, f = self._ngon(cx, cy, r, 4), (cx, cy), 0.55
        elif shape == "kite":
            pts = []
            for ux, uy in ((0, -1), (0.66, -0.12), (0, 1), (-0.66, -0.12)):
                pts += [cx + ux * r, cy + uy * r]
            text_xy, f = (cx, cy + r * 0.05), 0.50
        elif shape == "pentagon":
            pts, text_xy, f = self._ngon(cx, cy, r, 5), (cx, cy), 0.55
        elif shape == "hexagon":
            pts, text_xy, f = self._ngon(cx, cy, r, 6), (cx, cy), 0.55
        elif shape == "polygon":
            pts, text_xy, f = self._ngon(cx, cy, r, sides), (cx, cy), 0.50
        else:  # oval for the many-sided dice
            c.create_oval(cx - r, cy - r, cx + r, cy + r, **kw)
            text_xy, f = (cx, cy), 0.60

        if pts is not None:
            if angle:
                pts = self._rot(pts, cx, cy, angle)
            c.create_polygon(*pts, **kw)

        if isinstance(value, int) and sides == 6:  # classic pips
            pr = r * 0.13
            ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            span = r * 0.48
            for row, col in PIP_LAYOUT.get(value, []):
                x, y = (col - 1) * span, (row - 1) * span
                px, py = cx + x * ca - y * sa, cy + x * sa + y * ca
                c.create_oval(px - pr, py - pr, px + pr, py + pr,
                              fill=self.PIP, outline="", tags="die")
        else:
            fs = int(r * f * (0.8 if len(str(value)) >= 2 else 1))
            c.create_text(text_xy, text=str(value),
                          font=("Helvetica", fs, "bold"),
                          fill=self.PIP if value != "?" else "#9a938a", tags="die")

    # -- rolling ---------------------------------------------------------

    def start_roll(self, *_a):
        if self.animating:
            return
        if self.series.complete:
            self._offer_new_series()
            return
        self.animating = True
        self.roll_btn.config(state="disabled")
        self._status("rolling...", "#333333")
        self._attempts = self.series.draws()
        self._next_attempt()

    def _next_attempt(self):
        try:
            v, final = next(self._attempts)
        except StopIteration:  # defensive; cannot normally happen
            self.animating = False
            self.roll_btn.config(state="normal")
            return
        self._tumble(v, final, 0)

    def _tumble(self, target, final, step):
        n = 18
        sides = self.series.sides
        coin = sides == 2
        if step < n:
            t = step / n
            amp = 15 * (1 - t) ** 1.6
            self._phase += 0.55
            self.draw_face(
                random.randint(1, sides),
                angle=random.uniform(-amp, amp) * (0.3 if coin else 1.0),
                scale=1 + random.uniform(-0.05, 0.05) * (1 - t),
                coin_w=abs(math.sin(self._phase)) if coin else 1.0,
            )
            self.root.after(
                int(26 + 230 * t ** 2.3),
                lambda: self._tumble(target, final, step + 1),
            )
        else:
            self.draw_face(target, scale=1.13, result="ok" if final else "dup")
            self.root.after(90, lambda: self._attempt_done(target, final))

    def _attempt_done(self, v, final):
        self.draw_face(v, result="ok" if final else "dup")
        if final:
            self.last = v
            self.update_chips()
            extra = "  -- series complete!" if self.series.complete else ""
            self._status(
                f"Question #{v} \u00b7 {len(self.series.used)}/{self.series.sides} drawn{extra}",
                self.WARN if self.series.complete else self.OK,
            )
            self.animating = False
            self.roll_btn.config(state="normal")
            if self.series.complete:
                self.root.after(700, self._offer_new_series)
        else:
            self._status(f"{v} was already drawn this series -- rolling again...", self.WARN)
            self.root.after(850, self._next_attempt)

    def _offer_new_series(self):
        from tkinter import messagebox

        if messagebox.askyesno(
            "Series complete",
            f"All {self.series.sides} numbers have been drawn.\n\nStart a new series?",
        ):
            self.new_series()

    def new_series(self):
        if self.animating:
            return
        self.series.reset()
        self.last = None
        self.update_chips()
        self.draw_face("?")
        self._status("new series -- every number is available again")

    # -- sides ------------------------------------------------------------

    def ask_sides(self):
        from tkinter import simpledialog

        n = simpledialog.askinteger(
            "Number of sides",
            f"Sides ({MIN_SIDES}-{MAX_SIDES}):",
            parent=self.root, initialvalue=self.series.sides,
            minvalue=MIN_SIDES, maxvalue=MAX_SIDES,
        )
        if n is not None:
            self._apply_sides(n)

    def on_sides_spin(self):
        if self.animating:
            self.sides_var.set(str(self.series.sides))
            self._status("wait for the roll to finish...", self.WARN)
            return
        try:
            n = int(self.sides_var.get())
        except ValueError:
            self.sides_var.set(str(self.series.sides))
            return
        n = max(MIN_SIDES, min(MAX_SIDES, n))
        self._apply_sides(n)

    def _apply_sides(self, n):
        self.sides_var.set(str(n))
        self.series = Series(n)
        self.last = None
        self.build_chips()
        self.draw_face("?")
        self._status(f"d{n} -- new series started")

    def _status(self, msg, color="#333333"):
        self.status.config(fg=color)
        self.status_var.set(msg)


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


def run_cli(sides: int) -> int:
    try:
        TerminalApp(sides).run()
    except KeyboardInterrupt:
        pass
    return 0


def run_gui(sides: int) -> int:
    if tk is None:
        raise SystemExit(
            "tkinter is not available in this Python installation.\n"
            "Windows: re-run the Python installer and tick 'tcl/tk and IDLE'.\n"
            "Or start the program with --cli for the terminal interface."
        )
    root = tk.Tk()
    DiceGui(root, sides)
    root.mainloop()
    return 0


def _gui_selftest():
    root = tk.Tk()
    app = DiceGui(root, 6)
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a[1])
    root.after(300, app.start_roll)
    root.after(3200, lambda: app._apply_sides(10))
    root.after(3800, app.start_roll)
    root.after(6500, root.destroy)
    root.mainloop()
    if errors:
        raise RuntimeError(f"GUI errors: {errors!r}")


def _selftest() -> int:
    # series logic: every number exactly once, duplicates re-rolled
    for sides in range(MIN_SIDES, MAX_SIDES + 1):
        for _ in range(30):
            ser = Series(sides)
            seen = []
            while not ser.complete:
                finals = 0
                for v, final in ser.draws():  # one roll incl. re-rolls
                    if final:
                        finals += 1
                        assert v not in seen, (sides, v, seen)
                        seen.append(v)
                        assert ser.used == set(seen)
                    else:
                        assert v in seen, (sides, v, seen)
                assert finals == 1
            assert len(seen) == sides and ser.complete
    # uniformity of the underlying RNG (d6, 60k rolls)
    rng = random.Random()
    n = 60000
    counts = [0] * 6
    for _ in range(n):
        counts[rng.randint(1, 6) - 1] += 1
    e = n / 6
    chi2 = sum((o - e) ** 2 / e for o in counts)
    assert chi2 < 30, chi2
    print(f"logic ok (d6 chi2 = {chi2:.2f}, df = 5)")
    # ASCII art builds for every die size
    for sides in range(MIN_SIDES, MAX_SIDES + 1):
        for v in (1, sides, "?"):
            for line in die_art(sides, v):
                assert "\x1b" not in _plain(line)
    print("ascii art ok for d2..d30")
    for s in (2, 3, 4, 6, 8, 10, 12, 20, 30):
        print(f"-- d{s}")
        for line in die_art(s, 1 if s == 2 else s):
            print(line)
    if tk is None:
        print("tkinter not installed -- GUI test skipped")
        return 0
    try:
        _gui_selftest()
    except tk.TclError as exc:
        print(f"no display for the GUI ({exc}) -- skipped")
    else:
        print("gui smoke test ok")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # keep box characters printable
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="Dice roller for picking random exam questions."
    )
    ap.add_argument("-s", "--sides", type=int, default=6, metavar=f"{MIN_SIDES}-{MAX_SIDES}",
                    help=f"number of sides, {MIN_SIDES}-{MAX_SIDES} (default: 6)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--cli", action="store_true", help="force the terminal interface")
    g.add_argument("--gui", action="store_true", help="force the window interface")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests")
    args = ap.parse_args(argv)

    if not MIN_SIDES <= args.sides <= MAX_SIDES:
        ap.error(f"--sides must be {MIN_SIDES}..{MAX_SIDES}")
    if args.selftest:
        return _selftest()
    if args.cli:
        return run_cli(args.sides)
    if args.gui:
        return run_gui(args.sides)
    # auto: prefer a window, fall back to the terminal
    if tk is None:
        print("tkinter is not installed -- using the terminal interface.\n")
        return run_cli(args.sides)
    try:
        return run_gui(args.sides)
    except tk.TclError as exc:
        print(f"cannot open a window ({exc}) -- using the terminal interface.\n")
        return run_cli(args.sides)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
