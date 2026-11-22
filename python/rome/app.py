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
from .input import InputState
from .scene import Scene


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
        self.backend_name = backend or DEFAULT_BACKEND
        self._backend = create_backend(
            backend,
            BackendConfig(width=width, height=height, title=title, clear_color=clear_color, vsync=vsync),
        )
        self.input = InputState.empty()
        self._last = time.perf_counter()
        self.dt = 0.0
        self._closed = False

    @property
    def running(self) -> bool:
        return not self._closed and not self._backend.should_close()

    def info(self) -> str:
        return self._backend.info()

    def tick(self) -> bool:
        """Advance time and poll input. Returns whether the app is still running
        (so it reads naturally as a `while app.tick():` condition). Does not draw."""
        now = time.perf_counter()
        self.dt = now - self._last
        self._last = now
        self.input = self._backend.poll_input()
        return self.running

    def draw(self) -> None:
        """Render the current scene from the current camera."""
        self._backend.render(self.scene, self.camera)

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
            self._closed = True
            self._backend.close()

    def __enter__(self) -> "App":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
