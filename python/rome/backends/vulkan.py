"""Vulkan backend: the GPU window, via ROME's native `_rome` extension. The
default backend, and full colour.

It renders the scene's meshes on the GPU — lit, depth-tested, through the camera.
Meshes are uploaded once (cached by identity) and drawn each frame by handle.
Keyboard input is surfaced from SDL, so the game can steer the camera; the
window's close button and Escape also stop the loop.
"""

from __future__ import annotations

from .. import geometry
from ..camera import Camera
from ..input import InputState
from ..scene import Mesh, Scene
from . import register_backend
from .base import Backend, BackendConfig


class VulkanBackend(Backend):
    name = "vulkan"

    def __init__(self) -> None:
        self._app = None
        self._cache: dict[int, int] = {}  # id(framework Mesh) -> native handle
        self._running = True

    def open(self, config: BackendConfig) -> None:
        native = _load_native()
        self._app = native.App(
            width=config.width,
            height=config.height,
            title=config.title,
            vsync=config.vsync,
            clear_color=tuple(config.clear_color),
        )

    def _realize(self, mesh: Mesh) -> int:
        """Framework Mesh -> native GPU handle, uploaded once and cached."""
        handle = self._cache.get(id(mesh))
        if handle is not None:
            return handle
        geo = geometry.from_mesh(mesh)
        handle = self._app.upload_mesh(geo.positions, geo.normals, geo.indices)
        self._cache[id(mesh)] = handle
        return handle

    def poll_input(self) -> InputState:
        if self._app is None:
            return InputState.empty()
        held = frozenset(self._app.keys_held())
        pressed = frozenset(self._app.take_pressed_keys())
        dx, dy = self._app.mouse_delta()
        return InputState(held=held, pressed=pressed, mouse_dx=dx, mouse_dy=dy)

    def _hud_items(self, hud) -> list:
        if hud is None:
            return []
        return [
            (self._realize(it.mesh), it.x, it.y, it.size, it.rotation, it.color)
            for it in hud.items
        ]

    def render(self, scene: Scene, camera: Camera, hud=None) -> None:
        instances = [
            (self._realize(node.mesh), node.position, node.rotation, node.scale, node.color)
            for node in scene.nodes
            if node.visible
        ]
        self._running = self._app.render_scene(
            instances,
            cam_pos=camera.position,
            cam_target=camera.target,
            up=camera.up,
            fov=camera.fov,
            lights=[light.to_tuple() for light in scene.lights],
            ambient=scene.ambient,
            specular=scene.specular,
            shininess=scene.shininess,
            hud=self._hud_items(hud),
        )

    def render_image(self, scene: Scene, camera: Camera, width: int, height: int,
                     hud=None) -> bytes:
        instances = [
            (self._realize(node.mesh), node.position, node.rotation, node.scale, node.color)
            for node in scene.nodes
            if node.visible
        ]
        return self._app.render_to_image(
            instances,
            width,
            height,
            cam_pos=camera.position,
            cam_target=camera.target,
            up=camera.up,
            fov=camera.fov,
            lights=[light.to_tuple() for light in scene.lights],
            ambient=scene.ambient,
            specular=scene.specular,
            shininess=scene.shininess,
            hud=self._hud_items(hud),
        )

    def set_title(self, text: str) -> None:
        if self._app is not None:
            self._app.set_title(text)

    def set_mouse_look(self, enabled: bool) -> None:
        if self._app is not None:
            self._app.set_mouse_look(enabled)

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
