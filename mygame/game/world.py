"""Build the scene. Replace this with your own world / zone loading."""
from __future__ import annotations

from pathlib import Path

import rome


def build_scene(root: Path, cfg: dict) -> rome.Scene:
    scene = rome.Scene()

    # A starter arrangement — swap for your own.
    scene.add(rome.Mesh.sphere(), position=(-2.6, 0.0, 0.0), scale=0.9)
    scene.add(rome.Mesh.sphere(), position=(0.0, 0.0, 0.0), scale=1.3)
    scene.add(rome.Mesh.cube(), position=(2.6, 0.2, 0.0), rotation=(0.3, 0.6, 0.0), scale=0.9)

    # Any .obj dropped in assets/ is loaded automatically.
    for obj in sorted((root / "assets").glob("*.obj")):
        scene.add(rome.Mesh.load(str(obj)), position=(0.0, -1.5, 0.0))

    return scene
