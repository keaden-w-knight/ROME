"""The App: owns the loop, the chosen backend, the camera, and per-frame input.

Two loop styles, mirroring pygame and a scene library:

    # You own the loop
    app = rome.App(scene=scene, camera=cam)
    while app.tick():          # poll input + time
        ...move things...
        app.draw()             # render the scene

    # ROME owns the loop
    app.run(update)            # update(app) called each frame, then draw
"""

from __future__ import annotations

import time
from typing import Callable

from .backends import DEFAULT_BACKEND, BackendConfig, create_backend
from .camera import Camera
from .events import _NO_THIS, Event, Events
from .input import InputState
from .physics import CollisionSystem
from .scene import Hud, Scene


class App:
    def __init__(
        self,
        scene: Scene | None = None,
        camera: Camera | None = None,
        *,
        backend: str | None = None,
        width: int = 1280,
        height: int = 720,
        title: str = "ROME",
        clear_color: tuple = (0.05, 0.05, 0.08),
        vsync: bool = True,
    ) -> None:
        self.scene = scene if scene is not None else Scene()
        self.camera = camera if camera is not None else Camera()
        self.hud = Hud()  # screen-space overlay; add items with app.hud.add(...)
        self.backend_name = backend or DEFAULT_BACKEND
        self._backend = create_backend(
            backend,
            BackendConfig(width=width, height=height, title=title, clear_color=clear_color, vsync=vsync),
        )
        self.events = Events()  # register listeners with app.on(type, fn)
        self.physics = CollisionSystem()  # per-node collision events each tick
        self.input = InputState.empty()
        self._prev_held: frozenset = frozenset()
        self._last = time.perf_counter()
        self.dt = 0.0
        self._closed = False

    @property
    def running(self) -> bool:
        return not self._closed and not self._backend.should_close()

    @property
    def fps(self) -> float:
        """Frames per second from the most recent tick's delta time."""
        return 1.0 / self.dt if self.dt > 0 else 0.0

    def set_title(self, text: str) -> None:
        """Set the window (or terminal) title — handy for an FPS readout."""
        self._backend.set_title(text)

    def set_mouse_look(self, enabled: bool = True) -> None:
        """Capture the cursor for mouse-look (GPU backends). The ASCII backend
        ignores it — terminals can't do relative mouse motion."""
        self._backend.set_mouse_look(enabled)

    def info(self) -> str:
        return self._backend.info()

    def on(self, event_type: str, callback=None, this=_NO_THIS):
        """Register an event listener (see rome.events). Convenience for
        ``app.events.on(...)``; works as a decorator too. Pass ``this`` to hand the
        listener a second argument (a context), so a lambda can stay a one-liner."""
        return self.events.on(event_type, callback, this)

    def tick(self) -> bool:
        """Advance time, poll input, and fire events. Returns whether the app is
        still running (so it reads as a `while app.tick():` condition). No draw."""
        now = time.perf_counter()
        self.dt = now - self._last
        self._last = now
        self.input = self._backend.poll_input()
        self._dispatch_events()
        self.physics.step(self.scene, self)  # fire collision / collision_exit events
        return self.running

    def _dispatch_events(self) -> None:
        inp = self.input
        for key in inp.pressed:
            self.events.emit(Event("key_down", app=self, input=inp, key=key))
        for key in self._prev_held - inp.held:
            self.events.emit(Event("key_up", app=self, input=inp, key=key))
        self._prev_held = inp.held
        if inp.mouse_dx or inp.mouse_dy:
            self.events.emit(
                Event("mouse_move", app=self, input=inp, dx=inp.mouse_dx, dy=inp.mouse_dy)
            )
        self.events.emit(Event("update", app=self, input=inp, dt=self.dt))

    def draw(self) -> None:
        """Render the current scene from the current camera."""
        self._backend.render(self.scene, self.camera, self.hud)

    def render_image(self, width: int = 1280, height: int = 720) -> bytes:
        """Render the current scene off-screen (no window drawing) and return
        width*height*4 RGBA8 bytes. Backend-dependent; the vulkan backend
        supports it. Pair with rome.save_png."""
        return self._backend.render_image(self.scene, self.camera, width, height, self.hud)

    def render_array(self, width: int = 1280, height: int = 720):
        """Render off-screen and return the frame as a numpy ``(height, width, 4)``
        uint8 RGBA array — handy for notebooks, tests, and feeding other imaging
        tools. Requires numpy (only when called). The array is a view over the
        rendered bytes; copy it if you need to keep it past the next render."""
        try:
            import numpy as np
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "render_array needs numpy installed; use render_image for raw bytes."
            ) from e
        data = self.render_image(width, height)
        return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)

    def run(self, update: Callable[["App"], None] | None = None) -> None:
        """Drive the loop to completion. `update(app)` runs each frame before the
        draw — move the camera, step the world, read `app.input`, `app.dt`."""
        try:
            while self.tick():
                if update is not None:
                    update(self)
                if self._closed:
                    break
                self.draw()
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self.events.emit(Event("quit", app=self, input=self.input))
            self._closed = True
            self._backend.close()

    def __enter__(self) -> "App":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
