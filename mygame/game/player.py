"""Player control: orbit the camera around the scene. Make it your own."""
from __future__ import annotations

import rome


class Player:
    def __init__(self, distance: float = 8.0, fov: float = 55.0) -> None:
        self.yaw = 0.6
        self.pitch = 0.4
        self.dist = distance
        self.fov = fov
        self.auto = True
        self._refresh()

    def _refresh(self) -> None:
        self.camera = rome.Camera.orbit(self.yaw, self.pitch, self.dist, fov=self.fov)

    def update(self, dt: float, input: rome.InputState) -> None:
        turn = 1.5 * dt
        if input.down("a"):
            self.yaw -= turn
        if input.down("d"):
            self.yaw += turn
        if input.down("w"):
            self.pitch = min(1.4, self.pitch + turn)
        if input.down("s"):
            self.pitch = max(-1.4, self.pitch - turn)
        if input.down("q"):
            self.dist += 4.0 * dt
        if input.down("e"):
            self.dist = max(3.0, self.dist - 4.0 * dt)
        if input.just_pressed("r"):
            self.auto = not self.auto
        if self.auto:
            self.yaw += 0.4 * dt
        self._refresh()
