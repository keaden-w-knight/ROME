"""The ROME command line: scaffold a new game project.

    rome new mygame                 # prompts fill in the rest
    rome new mygame --backend ascii
    rome backends                   # list available backends

A generated project owns its scene, player control and loop, and imports ROME to
render. The layout:

    mygame/
      main.py            entry point: load config, build scene, run the loop
      game/
        world.py         build the scene (and load anything in assets/)
        player.py        player/camera control from input
      assets/            drop .obj models and other assets here
      config/game.toml   title, backend, window size, camera
      README.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backends import DEFAULT_BACKEND, available_backends

# --- templates (token-substituted, not str.format, so code braces are safe) ---

_MAIN = '''\
"""__NAME__ — a ROME game. You own this file; ROME just renders."""
from __future__ import annotations

import tomllib
from pathlib import Path

import rome

from game.player import Player
from game.world import build_scene

ROOT = Path(__file__).parent


def load_config() -> dict:
    with (ROOT / "config" / "game.toml").open("rb") as f:
        return tomllib.load(f)


def main() -> None:
    cfg = load_config()
    scene = build_scene(ROOT, cfg)
    p = cfg["player"]
    player = Player(
        position=tuple(p["start"]),
        fov=p["fov"],
        speed=p["speed"],
        sensitivity=p["sensitivity"],
    )

    app = rome.App(
        scene=scene,
        camera=player.camera,
        backend=cfg["render"]["backend"],
        width=cfg["window"]["width"],
        height=cfg["window"]["height"],
        title=cfg["game"]["title"],
    )
    app.set_mouse_look(True)  # capture the mouse for look (GPU; the terminal ignores it)
    title = cfg["game"]["title"]
    print(f"{title} — {app.info()}")

    # Refresh an FPS readout in the title a couple of times a second.
    stats = {"time": 0.0, "frames": 0}

    def update(app: rome.App) -> None:
        if app.input.down("escape"):
            app.close()
            return
        player.update(app.dt, app.input)
        app.camera = player.camera

        stats["time"] += app.dt
        stats["frames"] += 1
        if stats["time"] >= 0.5:
            app.set_title(f"{title} — {stats['frames'] / stats['time']:.0f} fps")
            stats["time"] = 0.0
            stats["frames"] = 0

    app.run(update)


if __name__ == "__main__":
    main()
'''

_WORLD = '''\
"""Build the scene. Replace this with your own world / zone loading."""
from __future__ import annotations

from pathlib import Path

import rome


def build_scene(root: Path, cfg: dict) -> rome.Scene:
    scene = rome.Scene()

    # A ground to walk on, and a few objects to walk around. Make it your own.
    scene.add(rome.Mesh.plane(), scale=14.0, color=(0.28, 0.30, 0.34))
    scene.add(rome.Mesh.sphere(), position=(-2.5, 1.0, 3.0), color=(0.80, 0.40, 0.40))
    scene.add(rome.Mesh.cube(), position=(2.5, 1.0, 4.0), rotation=(0.0, 0.5, 0.0),
              color=(0.45, 0.60, 0.88))
    scene.add(rome.Mesh.sphere(20, 14), position=(0.0, 0.8, 7.0), scale=0.8,
              color=(0.5, 0.8, 0.5))

    # Any .obj / .glb / .gltf dropped in assets/ is loaded automatically.
    assets = root / "assets"
    if assets.is_dir():
        for path in sorted(assets.iterdir()):
            if path.suffix.lower() in (".obj", ".glb", ".gltf"):
                scene.add(rome.Mesh.load(str(path)), position=(0.0, 1.0, 0.0))

    return scene
'''

_PLAYER = '''\
"""Player control: an FPS-style free-look camera. Make it your own.

WASD / arrow keys move; the mouse looks around (GPU backend). In the terminal
there's no mouse, so Q / E turn instead.
"""
from __future__ import annotations

import math

import rome


class Player:
    def __init__(
        self,
        position: tuple[float, float, float] = (0.0, 1.6, -6.0),
        yaw: float = 0.0,
        pitch: float = 0.0,
        fov: float = 60.0,
        speed: float = 4.0,
        sensitivity: float = 0.0025,
    ) -> None:
        self.x, self.y, self.z = position
        self.yaw = yaw
        self.pitch = pitch
        self.fov = fov
        self.speed = speed
        self.sensitivity = sensitivity
        self._refresh()

    def _refresh(self) -> None:
        cp = math.cos(self.pitch)
        fwd = (-math.sin(self.yaw) * cp, math.sin(self.pitch), math.cos(self.yaw) * cp)
        self.camera = rome.Camera(
            position=(self.x, self.y, self.z),
            target=(self.x + fwd[0], self.y + fwd[1], self.z + fwd[2]),
            fov=self.fov,
        )

    def update(self, dt: float, input: rome.InputState) -> None:
        # Look: mouse (GPU) or Q/E to turn (terminal fallback).
        self.yaw += input.mouse_dx * self.sensitivity
        self.pitch -= input.mouse_dy * self.sensitivity
        if input.down("q"):
            self.yaw -= 1.5 * dt
        if input.down("e"):
            self.yaw += 1.5 * dt
        limit = math.pi / 2 - 0.01
        self.pitch = max(-limit, min(limit, self.pitch))

        # Move on the ground plane: forward/back and strafe from the current yaw.
        # Right is world -X at yaw 0, matching the camera's screen-right.
        fx, fz = -math.sin(self.yaw), math.cos(self.yaw)
        rx, rz = -math.cos(self.yaw), -math.sin(self.yaw)
        forward = (1.0 if input.down("w") else 0.0) - (1.0 if input.down("s") else 0.0)
        strafe = (1.0 if input.down("d") else 0.0) - (1.0 if input.down("a") else 0.0)
        step = self.speed * dt
        self.x += (fx * forward + rx * strafe) * step
        self.z += (fz * forward + rz * strafe) * step
        self._refresh()
'''

_CONFIG = """\
# __NAME__ configuration.

[game]
title = "__NAME__"

[render]
# "vulkan" (GPU window) or "ascii" (terminal). See: rome backends
backend = "__BACKEND__"

[window]
# For the vulkan backend these are pixels; for ascii, character columns/rows.
width = __WIDTH__
height = __HEIGHT__

[player]
# Starting position (x, y, z), field of view, move speed, mouse sensitivity.
start = [0.0, 1.6, -6.0]
fov = 60.0
speed = 4.0
sensitivity = 0.0025
"""

_README = """\
# __NAME__

A game built on [ROME](https://github.com/keaden-w-knight/ROME).

```bash
python main.py
```

Controls: **W/A/S/D** or **arrows** move · **mouse** look (GPU) or **Q/E** turn (terminal) · **Esc** quit

## Layout

- `main.py` — entry point: loads config, builds the scene, runs the loop.
- `game/world.py` — builds the scene; also loads any `.obj` in `assets/`.
- `game/player.py` — player/camera control from input.
- `assets/` — drop models and other assets here.
- `config/game.toml` — title, backend, window size, camera.

Switch renderer in `config/game.toml` (`backend = "vulkan"` or `"ascii"`).
"""

_GITIGNORE = """\
__pycache__/
*.py[cod]
.venv/
venv/
"""

_ASSETS_README = "Drop .obj models and other assets here; world.py loads *.obj automatically.\n"


def _write(path: Path, text: str, name: str, backend: str, width: int, height: int) -> None:
    text = (
        text.replace("__NAME__", name)
        .replace("__BACKEND__", backend)
        .replace("__WIDTH__", str(width))
        .replace("__HEIGHT__", str(height))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cmd_new(args: argparse.Namespace) -> int:
    name = args.name or input("Project name: ").strip()
    if not name:
        print("a project name is required", file=sys.stderr)
        return 2

    backend = args.backend
    if backend not in available_backends() and backend != DEFAULT_BACKEND:
        print(f"warning: unknown backend {backend!r}; using it anyway", file=sys.stderr)

    # Sensible window defaults per backend: pixels for vulkan, a grid for ascii.
    if args.width and args.height:
        width, height = args.width, args.height
    elif backend == "ascii":
        width, height = 100, 40
    else:
        width, height = 1280, 720

    root = Path(args.into or ".") / name
    if root.exists() and any(root.iterdir()):
        print(f"{root} already exists and is not empty", file=sys.stderr)
        return 1

    files = {
        "main.py": _MAIN,
        "game/__init__.py": "",
        "game/world.py": _WORLD,
        "game/player.py": _PLAYER,
        "config/game.toml": _CONFIG,
        "assets/README.md": _ASSETS_README,
        "README.md": _README,
        ".gitignore": _GITIGNORE,
    }
    for rel, text in files.items():
        _write(root / rel, text, name, backend, width, height)

    print(f"Created {root}")
    print("  cd", name)
    print("  python main.py")
    if backend == "ascii":
        print("  (needs the 'three-ascii' package: pip install three-ascii)")
    return 0


def cmd_backends(_args: argparse.Namespace) -> int:
    names = available_backends()
    print("Available backends:" if names else "No backends available.")
    for n in names:
        mark = "  (default)" if n == DEFAULT_BACKEND else ""
        print(f"  - {n}{mark}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rome", description="ROME — 3D framework & scaffolder")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="scaffold a new game project")
    p_new.add_argument("name", nargs="?", help="project name (prompted if omitted)")
    p_new.add_argument("--backend", default=DEFAULT_BACKEND, help="vulkan | ascii | <plugin>")
    p_new.add_argument("--into", help="parent directory to create the project in")
    p_new.add_argument("--width", type=int, help="window width / columns")
    p_new.add_argument("--height", type=int, help="window height / rows")
    p_new.set_defaults(func=cmd_new)

    p_backends = sub.add_parser("backends", help="list available render backends")
    p_backends.set_defaults(func=cmd_backends)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
