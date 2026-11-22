"""ROME — a renderer-agnostic 3D framework you drive from Python.

Build a ``Scene``, point a ``Camera``, pick a backend (Vulkan by default, ASCII
for the terminal), and run your loop. Rendering lives behind a backend interface,
so the same game runs on the GPU or in a terminal — or on a backend that ships as
its own plugin.

    import rome

    scene = rome.Scene()
    scene.add(rome.Mesh.sphere(), position=(0, 0, 0))
    cam = rome.Camera.orbit(yaw=0.6, pitch=0.4, dist=6)

    app = rome.App(scene=scene, camera=cam, backend="ascii")
    app.run(lambda app: app.close() if app.input.down("escape") else None)

Create a new project with the scaffolder:  ``rome new mygame``
"""

from __future__ import annotations

from .app import App
from .backends import (
    DEFAULT_BACKEND,
    available_backends,
    create_backend,
    register_backend,
)
from .camera import Camera
from .image import save_png
from .input import InputState
from .scene import Mesh, Node, Scene

try:  # version comes from installed package metadata when available
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("rome")
    except PackageNotFoundError:
        __version__ = "0.1.0"
except Exception:  # pragma: no cover
    __version__ = "0.1.0"

__all__ = [
    "App",
    "Camera",
    "Scene",
    "Node",
    "Mesh",
    "InputState",
    "save_png",
    "available_backends",
    "create_backend",
    "register_backend",
    "DEFAULT_BACKEND",
    "__version__",
]
