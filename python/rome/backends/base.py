"""The contract every rendering backend implements.

A backend is the only part that knows *how* pixels (or characters) get drawn.
Everything above it — scenes, cameras, the loop, input — is backend-agnostic, so
the same game runs on Vulkan, on the terminal, or on a future plugin backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..camera import Camera
from ..input import InputState
from ..scene import Scene

Color = tuple[float, float, float] | tuple[float, float, float, float]


@dataclass
class BackendConfig:
    width: int = 1280
    height: int = 720
    title: str = "ROME"
    clear_color: Color = (0.05, 0.05, 0.08)
    vsync: bool = True


class Backend(ABC):
    """A rendering target. Opened once, then driven a frame at a time."""

    #: short identifier, e.g. "vulkan" or "ascii"
    name: str = "?"

    @abstractmethod
    def open(self, config: BackendConfig) -> None:
        """Acquire the window/terminal/device."""

    @abstractmethod
    def poll_input(self) -> InputState:
        """Current input for this frame."""

    @abstractmethod
    def render(self, scene: Scene, camera: Camera) -> None:
        """Draw one frame of `scene` from `camera`, and present it."""

    @abstractmethod
    def should_close(self) -> bool:
        """True once the backend wants the loop to stop (window closed, etc.)."""

    @abstractmethod
    def close(self) -> None:
        """Release everything."""

    def render_image(self, scene: Scene, camera: Camera, width: int, height: int) -> bytes:
        """Render the scene off-screen and return width*height*4 RGBA8 bytes.
        Optional: backends that cannot render off-screen raise."""
        raise NotImplementedError(f"the {self.name} backend has no off-screen render")

    def info(self) -> str:
        """A human-readable line about the backend (device name, mode, …)."""
        return self.name
