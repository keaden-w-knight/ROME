"""The scene model: what to draw, independent of how it's drawn.

A ``Scene`` is a backend-agnostic description — meshes placed by transform, plus
a light. Each rendering backend (Vulkan, ASCII, …) turns this same description
into its own native form, so one game's scene renders through any backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]


@dataclass
class Mesh:
    """A backend-agnostic mesh *description*. A backend realises it into its own
    native mesh (GPU buffers, ASCII triangles, …) and caches that by identity."""

    kind: str  # "sphere" | "cube" | "obj"
    path: str | None = None
    segments: int = 32
    rings: int = 20

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


@dataclass
class Scene:
    nodes: list[Node] = field(default_factory=list)
    light_direction: Vec3 = (-0.5, 0.8, -1.0)

    def add(
        self,
        mesh: Mesh,
        position: Vec3 = (0.0, 0.0, 0.0),
        rotation: Vec3 = (0.0, 0.0, 0.0),
        scale: float = 1.0,
        color: Vec3 = (0.62, 0.68, 0.82),
        name: str | None = None,
    ) -> Node:
        node = Node(
            mesh=mesh, position=position, rotation=rotation, scale=scale, color=color, name=name
        )
        self.nodes.append(node)
        return node

    def remove(self, node: Node) -> None:
        self.nodes.remove(node)

    def clear(self) -> None:
        self.nodes.clear()

    def __len__(self) -> int:
        return len(self.nodes)
