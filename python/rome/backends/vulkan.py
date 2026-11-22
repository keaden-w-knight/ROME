"""Vulkan backend: the GPU window, via ROME's native `_rome` extension. The
default backend.

Status: `_rome` today gives a window, a device, and a cleared frame — its
scene-graph, camera, and mesh rendering are on ROME's roadmap. So this backend
opens a real Vulkan window and runs the loop now, and will draw the scene as the
native side grows. Until then, pick the `ascii` backend to see meshes.
"""

from __future__ import annotations

from ..camera import Camera
from ..input import InputState
from ..scene import Scene
from . import register_backend
from .base import Backend, BackendConfig


class VulkanBackend(Backend):
    name = "vulkan"

    def __init__(self) -> None:
        self._app = None
        self._running = True
        self._warned = False

    def open(self, config: BackendConfig) -> None:
        native = _load_native()
        cc = tuple(config.clear_color)
        self._app = native.App(
            width=config.width,
            height=config.height,
            title=config.title,
            vsync=config.vsync,
            clear_color=cc,
        )

    def poll_input(self) -> InputState:
        # Surfacing SDL events to Python is on ROME's roadmap.
        return InputState.empty()

    def render(self, scene: Scene, camera: Camera) -> None:
        if scene.nodes and not self._warned:
            import warnings

            warnings.warn(
                "the vulkan backend does not draw meshes yet (scene rendering is on "
                "ROME's roadmap); it shows a cleared window. Use backend='ascii' to "
                "render the scene.",
                stacklevel=2,
            )
            self._warned = True
        # _rome.App.tick() processes events, clears, and presents one frame.
        self._running = self._app.tick()

    def should_close(self) -> bool:
        return not self._running

    def close(self) -> None:
        if self._app is not None:
            self._app.close()

    def info(self) -> str:
        try:
            return f"vulkan ({self._app.gpu_name})"
        except Exception:
            return "vulkan"


def _load_native():
    """Import rome._rome, making its co-located SDL3.dll resolvable first."""
    import os
    import sys
    from pathlib import Path

    pkg_dir = Path(__file__).resolve().parent.parent  # the rome/ package dir
    if sys.platform == "win32" and hasattr(os, "add_dll_directory") and pkg_dir.is_dir():
        try:
            os.add_dll_directory(str(pkg_dir))
        except Exception:
            pass
    try:
        from .. import _rome  # rome._rome, the compiled extension

        return _rome
    except Exception as e:  # pragma: no cover - depends on a native build
        raise RuntimeError(
            "the vulkan backend needs the compiled rome._rome extension. Build it "
            "with scikit-build / CMake (see the ROME README), or choose "
            "backend='ascii'. Original import error: " + repr(e)
        ) from e


register_backend("vulkan", VulkanBackend)
