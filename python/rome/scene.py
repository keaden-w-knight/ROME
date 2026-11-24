"""The scene model: what to draw, independent of how it's drawn.

A ``Scene`` is a backend-agnostic description — meshes placed by transform, plus
a light. Each rendering backend (Vulkan, ASCII, …) turns this same description
into its own native form, so one game's scene renders through any backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import _NO_THIS, Events

Vec3 = tuple[float, float, float]


@dataclass
class Mesh:
    """A backend-agnostic mesh *description*. A backend realises it into its own
    native mesh (GPU buffers, ASCII triangles, …) and caches that by identity."""

    kind: str  # "sphere" | "cube" | "plane" | "obj" | "gltf" | "arrays"
    path: str | None = None
    segments: int = 32
    rings: int = 20
    positions: Any = None  # kind="arrays": vertex xyz (numpy array or list)
    normals: Any = None  # kind="arrays": optional, computed when omitted
    indices: Any = None  # kind="arrays": optional, triangle soup when omitted

    @staticmethod
    def sphere(segments: int = 32, rings: int = 20) -> "Mesh":
        return Mesh(kind="sphere", segments=segments, rings=rings)

    @staticmethod
    def cube() -> "Mesh":
        return Mesh(kind="cube")

    @staticmethod
    def plane() -> "Mesh":
        """A flat square facing up (+Y). Scale it for a ground."""
        return Mesh(kind="plane")

    @staticmethod
    def from_arrays(positions, normals=None, indices=None) -> "Mesh":
        """A mesh from raw vertex arrays — numpy arrays or plain lists, flat
        (``[x, y, z, ...]``) or per-vertex (``[(x, y, z), ...]``). ``indices`` may
        be omitted for a triangle soup; ``normals`` may be omitted and are computed.
        Lets a game feed geometry it built itself (e.g. with numpy) to either
        backend."""
        return Mesh(kind="arrays", positions=positions, normals=normals, indices=indices)

    @staticmethod
    def load(path: str) -> "Mesh":
        """A mesh from a 3D file on disk: OBJ, or glTF 2.0 (.glb / .gltf)."""
        lower = path.lower()
        kind = "gltf" if lower.endswith((".glb", ".gltf")) else "obj"
        return Mesh(kind=kind, path=path)


@dataclass
class Node:
    """One placed instance of a mesh in the world."""

    mesh: Mesh
    position: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)  # Euler radians
    scale: float = 1.0
    color: Vec3 = (0.62, 0.68, 0.82)  # linear RGB 0..1 (GPU backends; ASCII ignores it)
    name: str | None = None
    visible: bool = True  # False hides the node from drawing (it still collides)
    collision: bool = False  # opt in to collision tests (fires events)
    collision_shape: str = "aabb"  # "aabb" | "sphere"
    layers: Any = (0,)  # only nodes sharing a layer are tested (see rome.physics)
    # Physics response (see rome.physics). A solid node is pushed apart from other
    # solids and exchanges momentum; a static body is solid but immovable (infinite
    # mass) — walls and floors. Velocity is integrated each tick for solid movers.
    solid: bool = False
    static_body: bool = False
    velocity: Vec3 = (0.0, 0.0, 0.0)
    angular_velocity: Vec3 = (0.0, 0.0, 0.0)  # Euler rad/sec; off-centre hits spin it
    mass: float = 1.0
    restitution: float = 0.2  # bounciness, 0 (dead stop) .. 1 (full bounce)
    friction: float = 0.0  # tangential friction coefficient (0 = frictionless)
    angular_damping: float = 0.0  # per-second spin decay (0 = spins forever)
    awake: bool = True  # physics-managed: a resting body sleeps; a hit wakes it
    # Per-node event dispatcher; collision events fire here. Excluded from the
    # dataclass's equality/repr so two nodes aren't "equal" by their listeners.
    events: Events = field(default_factory=Events, compare=False, repr=False)

    def on(self, event_type: str, callback=None, this=_NO_THIS):
        """Register an event listener on this node (chiefly ``"collision"`` and
        ``"collision_exit"``). Same shape as ``app.on`` — direct call or decorator,
        with an optional ``this`` handed to the listener as a second argument."""
        return self.events.on(event_type, callback, this)


_LIGHT_KIND = {"directional": 0, "point": 1, "spot": 2}


@dataclass
class Light:
    """A light: directional (a sun), point (a bulb), or spot (a cone). Placed and
    oriented like a Node. GPU backends only — the ASCII backend uses its own fixed
    shading. Use the directional()/point()/spot() constructors, or build directly."""

    kind: str = "directional"  # "directional" | "point" | "spot"
    position: Vec3 = (0.0, 5.0, 0.0)  # point / spot
    direction: Vec3 = (-0.4, -0.9, 0.3)  # directional / spot axis
    color: Vec3 = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    range: float = 20.0  # point / spot distance falloff
    inner_angle: float = 20.0  # spot cone, degrees (full brightness within)
    outer_angle: float = 30.0  # spot cone, degrees (zero beyond)

    @staticmethod
    def directional(direction: Vec3 = (-0.4, -0.9, 0.3), color: Vec3 = (1.0, 1.0, 1.0),
                    intensity: float = 1.0) -> "Light":
        return Light(kind="directional", direction=direction, color=color, intensity=intensity)

    @staticmethod
    def point(position: Vec3 = (0.0, 5.0, 0.0), color: Vec3 = (1.0, 1.0, 1.0),
              intensity: float = 1.0, range: float = 20.0) -> "Light":
        return Light(kind="point", position=position, color=color, intensity=intensity, range=range)

    @staticmethod
    def spot(position: Vec3 = (0.0, 5.0, 0.0), direction: Vec3 = (0.0, -1.0, 0.0),
             color: Vec3 = (1.0, 1.0, 1.0), intensity: float = 1.0, range: float = 20.0,
             inner_angle: float = 20.0, outer_angle: float = 30.0) -> "Light":
        return Light(kind="spot", position=position, direction=direction, color=color,
                     intensity=intensity, range=range, inner_angle=inner_angle,
                     outer_angle=outer_angle)

    def to_tuple(self) -> tuple:
        """Flatten to the tuple the renderer binding expects."""
        import math

        return (
            _LIGHT_KIND.get(self.kind, 0),
            tuple(self.position),
            tuple(self.direction),
            tuple(self.color),
            float(self.intensity),
            float(self.range),
            float(math.cos(math.radians(self.inner_angle))),
            float(math.cos(math.radians(self.outer_angle))),
        )


@dataclass
class HudItem:
    """One overlay item: a mesh drawn in screen space over the 3D scene."""

    mesh: Mesh
    x: float = 0.5  # 0..1, left..right
    y: float = 0.5  # 0..1, top..bottom
    size: float = 0.1  # fraction of the screen half-height
    rotation: Vec3 = (0.0, 0.0, 0.0)  # Euler radians
    color: Vec3 = (1.0, 1.0, 1.0)


class Hud:
    """A screen-space overlay. Add any mesh (3D or flat) at (x, y) in 0..1 with
    (0,0) = top-left; items always draw on top of the 3D scene, lit by a fixed
    front light. GPU backend only."""

    def __init__(self) -> None:
        self.items: list[HudItem] = []

    def add(self, mesh: Mesh, x: float = 0.5, y: float = 0.5, size: float = 0.1,
            rotation: Vec3 = (0.0, 0.0, 0.0), color: Vec3 = (1.0, 1.0, 1.0)) -> HudItem:
        item = HudItem(mesh=mesh, x=x, y=y, size=size, rotation=rotation, color=color)
        self.items.append(item)
        return item

    def clear(self) -> None:
        self.items.clear()

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class Scene:
    nodes: list[Node] = field(default_factory=list)
    # Lights (GPU backends; the ASCII backend uses its own fixed shading).
    lights: list[Light] = field(default_factory=lambda: [Light.directional()])
    ambient: float = 0.12  # scene-wide ambient fill
    specular: float = 0.4  # material highlight strength
    shininess: float = 32.0  # material highlight tightness

    def add(
        self,
        mesh: Mesh,
        position: Vec3 = (0.0, 0.0, 0.0),
        rotation: Vec3 = (0.0, 0.0, 0.0),
        scale: float = 1.0,
        color: Vec3 = (0.62, 0.68, 0.82),
        name: str | None = None,
        visible: bool = True,
        collision: bool = False,
        collision_shape: str = "aabb",
        layers: Any = (0,),
        solid: bool = False,
        static_body: bool = False,
        velocity: Vec3 = (0.0, 0.0, 0.0),
        angular_velocity: Vec3 = (0.0, 0.0, 0.0),
        mass: float = 1.0,
        restitution: float = 0.2,
        friction: float = 0.0,
        angular_damping: float = 0.0,
    ) -> Node:
        node = Node(
            mesh=mesh, position=position, rotation=rotation, scale=scale, color=color, name=name,
            visible=visible, collision=collision, collision_shape=collision_shape, layers=layers,
            solid=solid, static_body=static_body, velocity=velocity,
            angular_velocity=angular_velocity, mass=mass, restitution=restitution,
            friction=friction, angular_damping=angular_damping,
        )
        self.nodes.append(node)
        return node

    def add_light(self, light: Light) -> Light:
        self.lights.append(light)
        return light

    def remove(self, node: Node) -> None:
        self.nodes.remove(node)

    def clear(self) -> None:
        self.nodes.clear()

    def __len__(self) -> int:
        return len(self.nodes)
