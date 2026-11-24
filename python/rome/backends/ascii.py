"""ASCII backend: renders the scene as grayscale ASCII in the terminal, using
the 3-ASCII engine (`three_ascii`). Fully renders scenes today.

This is also where terminal input lives: a real console gives key *events*, not
held-state, so a key counts as "held" for a short window after it was last seen —
smooth enough to steer by. A windowed backend would read true key state instead.
"""

from __future__ import annotations

import re
import sys
import time

from ..camera import Camera
from ..input import InputState
from ..scene import Mesh, Scene
from . import register_backend
from .base import Backend, BackendConfig

_HOLD = 0.12  # seconds a key stays "held" after its last event

# One ANSI escape: CSI params + a final letter. three_ascii emits `\x1b[H` (home)
# and 24-bit colour `\x1b[…m` sequences; we tokenise both to composite the HUD at
# the character-cell level over the already-coloured frame.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class AsciiBackend(Backend):
    name = "ascii"

    def __init__(self) -> None:
        self._ta = None
        self._cache: dict[int, object] = {}
        self._poll = None
        self._held_times: dict[str, float] = {}
        self._prev: frozenset[str] = frozenset()
        self._w = 100
        self._h = 44
        self._color = "depth"  # glyph = fill/brightness, gray = depth (chosen look)
        self._closed = False

    def open(self, config: BackendConfig) -> None:
        import three_ascii as ta  # deferred: only needed for this backend

        self._ta = ta
        # The config width/height are pixels for a window; for the terminal they
        # are character columns/rows, so treat small numbers as a grid and fall
        # back to a sensible default for window-sized values.
        self._w = config.width if 0 < config.width < 400 else 100
        self._h = config.height if 0 < config.height < 200 else 44
        # Never let the grid exceed the real terminal: a frame taller than the
        # window scrolls every row and flickers. Clamp down to what fits, leaving
        # one row spare at the bottom — but only down, so an explicit small grid is
        # kept. The fallback leaves a non-tty (piped/captured) output unchanged.
        import shutil

        cols, rows = shutil.get_terminal_size(fallback=(self._w, self._h + 1))
        self._w = max(1, min(self._w, cols))
        self._h = max(1, min(self._h, rows - 1))
        _enable_ansi()
        self._poll = _make_key_reader()
        sys.stdout.write("\x1b[2J\x1b[?25l")  # clear, hide cursor
        sys.stdout.flush()

    def _realize(self, mesh: Mesh):
        """Framework Mesh -> three_ascii.Mesh, cached by identity. Geometry comes
        from the shared `rome.geometry` module (same source the GPU backend uses),
        so both backends draw identical meshes."""
        cached = self._cache.get(id(mesh))
        if cached is not None:
            return cached
        from .. import geometry

        geo = geometry.from_mesh(mesh)
        native = self._ta.Mesh.from_arrays(geo.positions, geo.normals, geo.indices)
        self._cache[id(mesh)] = native
        return native

    def poll_input(self) -> InputState:
        if self._poll is None:
            return InputState.empty()
        now = time.perf_counter()
        for key in self._poll():
            self._held_times[key] = now
        held = frozenset(k for k, t in self._held_times.items() if now - t < _HOLD)
        pressed = held - self._prev
        self._prev = held
        return InputState(held=held, pressed=pressed)

    def render(self, scene: Scene, camera: Camera, hud=None) -> None:
        ta = self._ta
        s = ta.Scene()
        for node in scene.nodes:
            if not node.visible:
                continue
            s.add(
                self._realize(node.mesh),
                position=node.position,
                rotation=node.rotation,
                scale=node.scale,
            )
        frame = ta.render_scene(
            s,
            width=self._w,
            height=self._h,
            cam_pos=camera.position,
            cam_target=camera.target,
            up=camera.up,
            fov=camera.fov,
            color=self._color,
            vt=True,
            lights=[light.to_tuple() for light in scene.lights],
            ambient=scene.ambient,
        )
        # Drop the trailing newline three_ascii appends to the last row. The frame
        # homes the cursor (\x1b[H) and overwrites in place without clearing, so a
        # final newline past the bottom row forces the terminal to scroll one line;
        # the next frame homes into the scrolled view and the whole image shimmers.
        if frame.endswith("\n"):
            frame = frame[:-1]
        if hud is not None and hud.items:
            frame = self._composite_hud(frame, hud.items)
        sys.stdout.write(frame)
        sys.stdout.flush()

    def _composite_hud(self, frame: str, items) -> str:
        """Overlay HUD items onto the coloured frame. Each item's mesh is rendered
        to a small plain-glyph block and its non-blank cells are stamped onto the
        frame at the item's screen position (x, y in 0..1, top-left origin), in the
        item's colour — the terminal equivalent of the GPU HUD's always-on-top pass."""
        parsed = [_parse_line(line) for line in frame.split("\n")]
        nrows = len(parsed)
        for item in items:
            native = self._realize(item.mesh)
            # size is a fraction of the grid height; width is doubled because a
            # terminal cell is about twice as tall as it is wide.
            ih = max(2, round(item.size * self._h))
            iw = max(2, round(item.size * self._h * 2))
            esc = _color_escape(item.color)
            block = self._ta.render(
                native, width=iw, height=ih,
                yaw=float(item.rotation[1]), pitch=float(item.rotation[0]),
                dist=3.0, color="glyph", vt=False,
            )
            row0 = round(item.y * self._h - ih / 2)
            col0 = round(item.x * self._w - iw / 2)
            for ry, rline in enumerate(block.split("\n")):
                tr = row0 + ry
                if tr < 0 or tr >= nrows:
                    continue
                cells = parsed[tr][1]
                for rx, ch in enumerate(rline):
                    if ch == " ":
                        continue  # blank glyph = transparent
                    tc = col0 + rx
                    if 0 <= tc < len(cells):
                        cells[tc] = [ch, esc]
        return "\n".join(prefix + _serialize_cells(cells) for prefix, cells in parsed)

    def set_title(self, text: str) -> None:
        # OSC 0: set the terminal window/tab title.
        try:
            sys.stdout.write(f"\x1b]0;{text}\x07")
            sys.stdout.flush()
        except Exception:
            pass

    def should_close(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[2J\x1b[H")  # restore cursor, clear
        sys.stdout.flush()

    def info(self) -> str:
        return f"ascii {self._w}x{self._h}"


def _parse_line(line: str):
    """Split one frame line into ([non-colour prefix escapes], [[glyph, colour], …]).

    A cell's colour is the active 24-bit escape string, or None for the default.
    Non-colour escapes (the leading `\\x1b[H` home) are kept as a prefix so the
    re-serialised line is byte-identical when nothing is composited over it."""
    cells: list[list] = []
    prefix = ""
    cur = None
    pos = 0
    for mo in _ANSI.finditer(line):
        for ch in line[pos:mo.start()]:
            cells.append([ch, cur])
        esc = mo.group()
        if esc.endswith("m"):
            cur = None if esc == "\x1b[0m" else esc
        else:
            prefix += esc  # cursor move etc.: carries no colour, kept verbatim
        pos = mo.end()
    for ch in line[pos:]:
        cells.append([ch, cur])
    return prefix, cells


def _serialize_cells(cells) -> str:
    """Re-emit cells, writing a colour escape only when it changes (run-length,
    as three_ascii does), and a trailing reset. Empty line stays empty."""
    if not cells:
        return ""
    out: list[str] = []
    cur = None  # a line begins after the previous line's reset
    for glyph, color in cells:
        if color != cur:
            out.append("\x1b[0m" if color is None else color)
            cur = color
        out.append(glyph)
    out.append("\x1b[0m")
    return "".join(out)


def _color_escape(color) -> str:
    """A 24-bit foreground escape from a linear RGB 0..1 triple."""
    r, g, b = (max(0, min(255, round(c * 255))) for c in color)
    return f"\x1b[38;2;{r};{g};{b}m"


def _enable_ansi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            pass


def _name(ch: str) -> str:
    if ch == "\x1b":
        return "escape"
    if ch == " ":
        return "space"
    if ch in ("\r", "\n"):
        return "enter"
    return ch.lower()


def _make_key_reader():
    if sys.platform == "win32":
        import msvcrt

        def poll() -> list[str]:
            out: list[str] = []
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # arrow / function prefix
                    code = msvcrt.getwch()
                    out.append({"H": "w", "P": "s", "K": "a", "M": "d"}.get(code, ""))
                else:
                    out.append(_name(ch))
            return [k for k in out if k]

        return poll

    import select

    def poll() -> list[str]:
        out: list[str] = []
        while select.select([sys.stdin], [], [], 0)[0]:
            out.append(_name(sys.stdin.read(1)))
        return [k for k in out if k]

    return poll


register_backend("ascii", AsciiBackend)
