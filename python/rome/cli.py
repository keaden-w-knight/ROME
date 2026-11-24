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
        radius=p.get("radius", 0.4),
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
        player.update(app.dt, app.input, app.scene)
        app.camera = player.camera

        stats["time"] += app.dt
        stats["frames"] += 1
        if stats["time"] >= 0.5:
            app.set_title(f"{title} — {stats['frames'] / stats['time']:.0f} fps")
            stats["time"] = 0.0
            stats["frames"] = 0

    # Example event listener — press Space to toggle a HUD marker. Add your own
    # (custom keys, triggers, how the player reacts) here. See docs/EVENTS.md.
    marker = []

    @app.on("key_down")
    def on_key(event):
        if event.key == "space":
            if marker:
                event.app.hud.items.remove(marker.pop())
            else:
                marker.append(event.app.hud.add(rome.Mesh.sphere(), x=0.5, y=0.08, size=0.04,
                                                color=(1.0, 0.9, 0.3)))

    # A one-line lambda listener with a bound "this" (the player, passed as the
    # 3rd arg): press F to toggle sprint. No named function needed.
    app.on("key_down",
           lambda e, p: (setattr(p, "speed", 8.0 if p.speed < 6 else 4.0) if e.key == "f" else None),
           player)

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

    # A ground to walk on, and a few objects to walk around. The obstacles are
    # `solid=True` so the player (a rome.CharacterController) bumps and slides
    # along them instead of walking through; `static_body=True` means they never
    # move. Drop `solid=` to make something walk-through-able scenery.
    scene.add(rome.Mesh.plane(), scale=14.0, color=(0.28, 0.30, 0.34))
    scene.add(rome.Mesh.sphere(), position=(-2.5, 1.2, 3.0), scale=1.2,
              color=(0.80, 0.40, 0.40), collision=True, solid=True, static_body=True)
    scene.add(rome.Mesh.cube(), position=(2.5, 1.2, 4.0), rotation=(0.0, 0.5, 0.0), scale=1.2,
              color=(0.45, 0.60, 0.88), collision=True, solid=True, static_body=True)
    scene.add(rome.Mesh.cube(), position=(0.0, 1.2, 7.0), scale=1.4,
              color=(0.5, 0.8, 0.5), collision=True, solid=True, static_body=True)

    # Any .obj / .glb / .gltf dropped in assets/ is loaded automatically.
    assets = root / "assets"
    if assets.is_dir():
        for path in sorted(assets.iterdir()):
            if path.suffix.lower() in (".obj", ".glb", ".gltf"):
                scene.add(rome.Mesh.load(str(path)), position=(0.0, 1.0, 0.0))

    # Lights: a soft "sun" (directional) plus a warm point light over the scene.
    # Try rome.Light.spot(...) too. Lights are GPU-only; the terminal uses its
    # own shading. Tune scene.ambient / specular / shininess to taste.
    scene.lights = [
        rome.Light.directional(direction=(-0.4, -0.9, 0.3), intensity=0.8),
        rome.Light.point(position=(2.0, 4.0, 3.0), color=(1.0, 0.9, 0.7), intensity=1.0, range=18.0),
    ]
    scene.ambient = 0.14

    return scene
'''

_PLAYER = '''\
"""Player control: an FPS-style free-look camera that collides with the world.

WASD / arrow keys move; the mouse looks around (GPU backend). In the terminal
there's no mouse, so Q / E turn instead.

Movement goes through a rome.CharacterController — a kinematic sphere that slides
along solid nodes instead of walking through them (set `solid=True` on the things
you want to block the player; see game/world.py). `plane_lock` keeps the eye at a
fixed height, so this is a flat walker; drop it (and feed gravity) for falling.
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
        radius: float = 0.4,
    ) -> None:
        self.body = rome.CharacterController(position, radius=radius, plane_lock=True)
        self.yaw = yaw
        self.pitch = pitch
        self.fov = fov
        self.speed = speed
        self.sensitivity = sensitivity
        self._refresh()

    @property
    def position(self) -> tuple[float, float, float]:
        return self.body.position

    def _refresh(self) -> None:
        x, y, z = self.body.position
        cp = math.cos(self.pitch)
        fwd = (-math.sin(self.yaw) * cp, math.sin(self.pitch), math.cos(self.yaw) * cp)
        self.camera = rome.Camera(
            position=(x, y, z),
            target=(x + fwd[0], y + fwd[1], z + fwd[2]),
            fov=self.fov,
        )

    def update(self, dt: float, input: rome.InputState, scene: rome.Scene) -> None:
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
        delta = ((fx * forward + rx * strafe) * step, 0.0, (fz * forward + rz * strafe) * step)
        # Hand the intended move to the controller; it slides us out of any solid.
        self.body.move(delta, scene)
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
# Starting position (x, y, z), field of view, move speed, mouse sensitivity,
# and the collision radius (how close you can get to a solid object).
start = [0.0, 1.6, -6.0]
fov = 60.0
speed = 4.0
sensitivity = 0.0025
radius = 0.4
"""

_README = """\
# __NAME__

A game built on [ROME](https://github.com/keaden-w-knight/ROME).

```bash
python main.py
```

## Controls

| | |
|---|---|
| **W/A/S/D** or **arrows** | move / strafe |
| **mouse** | look around (GPU backend) |
| **Q / E** | turn (terminal fallback — no mouse) |
| **Esc** | quit |

## Project layout

- `main.py` — entry point: loads config, builds the scene, runs the loop.
- `game/world.py` — builds the scene (meshes + lights); loads `assets/`.
- `game/player.py` — the FPS camera controller.
- `assets/` — drop `.obj` / `.glb` / `.gltf` models here (auto-loaded).
- `config/game.toml` — title, backend, window size, player settings.

Switch renderer in `config/game.toml`: `backend = "vulkan"` (GPU window) or
`"ascii"` (terminal). Run `rome backends` to list them.

## Building a scene (`game/world.py`)

Everything lives on a `rome.Scene`. Add meshes with `scene.add(...)`, lights with
`scene.lights` (or `scene.add_light(...)`).

### Meshes

```python
scene.add(mesh, position=(x, y, z), rotation=(rx, ry, rz), scale=1.0, color=(r, g, b))
```

Built-in meshes, plus files:

| Mesh | |
|---|---|
| `rome.Mesh.cube()` | unit cube |
| `rome.Mesh.sphere(segments=32, rings=20)` | UV sphere |
| `rome.Mesh.plane()` | flat square facing up (+Y); scale it for a ground |
| `rome.Mesh.load("assets/model.obj")` | OBJ or glTF 2.0 (`.glb` / `.gltf`) |
| `rome.Mesh.from_arrays(positions, normals=None, indices=None)` | geometry you built yourself — numpy arrays or lists, flat or per-vertex; normals/indices optional |

`position` is world XYZ, `rotation` is Euler **radians** (applied Y→X→Z), `scale`
is uniform, `color` is linear RGB in 0..1 (GPU only; the terminal is grayscale).

### Lights (GPU backend)

```python
scene.lights = [
    rome.Light.directional(direction=(-0.4, -0.9, 0.3), color=(1, 1, 1), intensity=0.8),
    rome.Light.point(position=(2, 4, 3), color=(1, 0.9, 0.7), intensity=1.0, range=18),
    rome.Light.spot(position=(0, 6, 0), direction=(0, -1, 0), inner_angle=20, outer_angle=30),
]
scene.ambient = 0.14      # constant fill
scene.specular = 0.4      # highlight strength
scene.shininess = 32.0    # highlight tightness
```

| Light | What it is |
|---|---|
| `directional` | a sun — a direction, no position, no falloff |
| `point` | a bulb — a position, radiates all ways, distance falloff (`range`) |
| `spot` | a cone — position + direction + `inner_angle`/`outer_angle` (degrees) |

Up to 8 lights. The terminal (ASCII) backend ignores lights and uses its own
fixed shading.

## Player (`game/player.py`)

An FPS free-look camera: WASD/arrows move on the ground plane, the mouse turns
(yaw/pitch). `main.py` calls `app.set_mouse_look(True)` to capture the cursor on
the GPU backend. Edit `Player.update(...)` to change how movement feels, or
replace the class entirely for a different control scheme. Tune the start
position, FOV, speed, and mouse sensitivity in `config/game.toml` under
`[player]`.

## HUD overlay

`app.hud.add(mesh, x, y, size, rotation, color)` draws a mesh in screen space on
top of the 3D scene — `x`/`y` are 0..1 with (0,0) top-left. Good for markers,
reticles, or 3D icons. Both backends: the GPU draws it as an always-on-top pass,
the terminal composites it as glyphs over the frame.

## Events

Register listeners to react to input and frames without touching the loop:

```python
@app.on("key_down")
def on_key(event):
    if event.key == "space":
        ...
```

`main.py` ships a Space-to-toggle-a-HUD-marker example. See **[docs/EVENTS.md](docs/EVENTS.md)**
for the full event list and keep it updated as you add your own.

## Collision

Opt a node in with `collision=True` and give it `layers`; two nodes are only
tested when they **share a layer** (so bullets-vs-enemies never costs you a
walls-vs-walls check). Pick a bound per object with `collision_shape`:

```python
player = scene.add(rome.Mesh.sphere(), collision=True, collision_shape="sphere",
                   layers=("player",))
pickup = scene.add(rome.Mesh.cube(), collision=True, layers=("player", "items"))
```

| Field | Meaning |
|---|---|
| `collision` | `False` by default; `True` to take part in collision tests |
| `collision_shape` | `"aabb"` (box, the default) or `"sphere"` |
| `layers` | any hashables; only nodes sharing one are tested (default `(0,)`) |
| `visible` | `False` hides a node from drawing — **it still collides** |

Listen on the **node itself** (not `app`): `collision` fires once when two nodes
begin overlapping, `collision_exit` once when they separate. The event carries
`node` (the one you attached to), `other` (what it hit), and `others` (everything
it overlaps this frame).

```python
pickup.on("collision", lambda e: e.node.collect() if e.other is player else None)
enemy.on("collision_exit", lambda e, hud: hud.clear(), app.hud)  # event + "this"
```

### Physics response (solid bodies)

Events tell you a hit *happened*; mark a node `solid=True` and it's also **pushed
apart** from other solids and exchanges momentum. Solid movers are driven by
`velocity` (the engine integrates it each tick, plus `app.physics.gravity`), so
you set velocity instead of position for them. A `static_body` is solid but never
moves (walls, floors) — movers bounce off it correctly.

```python
app.physics.gravity = (0.0, -9.8, 0.0)

floor = scene.add(rome.Mesh.cube(), position=(0,-3,0), scale=6.0,
                  collision=True, solid=True, static_body=True)
ball  = scene.add(rome.Mesh.sphere(), position=(0,5,0), collision_shape="sphere",
                  collision=True, solid=True, velocity=(2,0,0),
                  mass=1.0, restitution=0.7, friction=0.3)  # bouncy, a bit grippy
```

| Field | Meaning |
|---|---|
| `solid` | push apart + momentum (needs `collision=True` to also fire events) |
| `static_body` | solid but immovable — infinite mass (walls, floors) |
| `velocity` | `(x,y,z)` per second; integrated each tick for solid movers |
| `mass` | heavier bodies shove lighter ones more (ignored for a static body) |
| `restitution` | bounciness `0` (dead stop) .. `1` (full bounce) |
| `friction` | tangential friction `0`..`1` (slows sliding along a surface) |

Tune the solver on `app.physics`: `gravity`, `solver_iterations` (stiffer stacks),
`position_correction`/`slop` (how hard penetration is pushed out), and `max_dt`
(caps the step so a long frame can't tunnel bodies through each other). A
**non-solid** collider is a pure *trigger* — it fires events but never pushes.
"""

_EVENTS_DOC = """\
# Events in __NAME__

ROME fires events every frame; register listeners to react — the place to change
how the player interacts with the scene without touching the loop.

```python
@app.on("key_down")
def on_key(event):
    if event.key == "space":
        ...  # event.app gives you the scene, camera, hud, player, etc.
```

Listeners are just callables — a **lambda** works, no named function needed.
Modelled on JS `addEventListener`: the listener gets the **event** by default, and
if you pass a value as the 3rd argument to `on(...)` it's handed to the listener
as a second parameter (a "this"/context), so a lambda can carry state inline:

```python
app.on("key_down", lambda e: e.app.close())                 # event only
app.on("key_down", lambda e, player: player.jump(), player)  # event + "this"
```

Remove a listener with `app.events.off("update", fn)`.

## Built-in event types

| Type         | Fired when                      | Fields           |
|--------------|---------------------------------|------------------|
| `update`     | every frame                     | `dt`             |
| `key_down`   | a key is pressed this frame     | `key`            |
| `key_up`     | a key is released               | `key`            |
| `mouse_move` | the mouse moved (GPU backend)   | `dx`, `dy`       |
| `quit`       | the app is closing              | —                |

Every event also carries `app` (reach the scene / camera / hud) and `input` (the
current `InputState`). Key names: lowercase letters, `escape`, `space`, `enter`;
arrow keys report as `w`/`a`/`s`/`d`.

## Node (collision) events

These fire on a **node**, registered with `node.on(...)` rather than `app.on(...)`,
once per frame the state changes (see the Collision section of the README):

| Type             | Fired when                          | Fields                   |
|------------------|-------------------------------------|--------------------------|
| `collision`      | two nodes begin overlapping         | `node`, `other`, `others`|
| `collision_exit` | two overlapping nodes separate      | `node`, `other`, `others`|

`node` is the node the listener is on, `other` is the collider, and `others` is
every node it overlaps this frame. Same lambda / optional-`this` shape as above.

## Your game's events

As you add your own interactions, list them here so they stay documented:

| Type | What it does |
|------|--------------|
| `space` (key_down) | toggles a HUD marker (the starter example in `main.py`) |
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
        "docs/EVENTS.md": _EVENTS_DOC,
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
