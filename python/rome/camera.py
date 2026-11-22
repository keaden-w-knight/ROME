"""The camera: a free look-at camera, shared by every backend."""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass
class Camera:
    position: Vec3 = (0.0, 0.0, -5.0)
    target: Vec3 = (0.0, 0.0, 0.0)
    up: Vec3 = (0.0, 1.0, 0.0)
    fov: float = 50.0  # vertical, degrees

    @staticmethod
    def orbit(
        yaw: float,
        pitch: float,
        dist: float,
        target: Vec3 = (0.0, 0.0, 0.0),
        fov: float = 50.0,
    ) -> "Camera":
        """A camera placed `dist` from `target`, `yaw`/`pitch` radians around it."""
        ce = math.cos(pitch)
        position = (
            target[0] + dist * ce * math.sin(yaw),
            target[1] + dist * math.sin(pitch),
            target[2] - dist * ce * math.cos(yaw),
        )
        return Camera(position=position, target=target, up=(0.0, 1.0, 0.0), fov=fov)
