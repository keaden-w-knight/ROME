"""ASCII backend: renders the scene as grayscale ASCII in the terminal, using
the 3-ASCII engine (`three_ascii`). Fully renders scenes today.

This is also where terminal input lives: a real console gives key *events*, not
held-state, so a key counts as "held" for a short window after it was last seen —
smooth enough to steer by. A windowed backend would read true key state instead.
"""

from __future__ import annotations

import sys
import time

from ..camera import Camera
from ..input import InputState
from ..scene import Mesh, Scene
from . import register_backend
from .base import Backend, BackendConfig

_HOLD = 0.12  # seconds a key stays "held" after its last event


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

        if mesh.kind == "sphere":
            geo = geometry.sphere(mesh.segments, mesh.rings)
        elif mesh.kind == "cube":
            geo = geometry.cube()
        elif mesh.kind == "obj":
            geo = geometry.load_obj(mesh.path)
        elif mesh.kind == "gltf":
            geo = geometry.load_gltf(mesh.path)
        else:
            raise ValueError(f"unknown mesh kind {mesh.kind!r}")
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

    def render(self, scene: Scene, camera: Camera) -> None:
        ta = self._ta
        s = ta.Scene()
        for node in scene.nodes:
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
        )
        sys.stdout.write(frame)
        sys.stdout.flush()

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
