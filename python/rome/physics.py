"""Collision detection: physics layers, selectable bounds, and enter/exit events.

The model is deliberately small and backend-independent — it reads the same
``Scene`` the renderer draws, so collisions line up with what's on screen without
the GPU being involved (and it's unit-testable with no window).

Each ``Node`` can opt in with ``collision=True`` and carry a set of ``layers``;
two nodes are only ever tested against each other when they share a layer. A
node's bound is an axis-aligned box (``collision_shape="aabb"``) or a sphere
(``"sphere"``), fit around the mesh's own extents and moved by the node's
transform each frame. When two bounds begin overlapping a ``collision`` event
fires on *both* nodes (each sees the other as ``event.other``); when they stop, a
``collision_exit`` event fires the same way. Listeners are registered per node:

    enemy.on("collision", lambda e: e.node.die() if e.other is player else None)

See ``rome.events`` for the listener shape (lambdas, optional ``this``).
"""

from __future__ import annotations

import math

from .events import Event

#: node-level event types (app-level ones live in rome.events.EVENT_TYPES)
COLLISION_EVENT_TYPES = ("collision", "collision_exit")


def _as_set(layers) -> set:
    """A node's layers as a set, tolerating a bare scalar (``layers=3``)."""
    if isinstance(layers, (list, tuple, set, frozenset)):
        return set(layers)
    return {layers}


def local_bounds(positions):
    """From flat xyz positions: (min, max, centre, radius) in the mesh's own
    space. Computed once per mesh and cached by the CollisionSystem."""
    xs = positions[0::3]
    ys = positions[1::3]
    zs = positions[2::3]
    cmin = (min(xs), min(ys), min(zs))
    cmax = (max(xs), max(ys), max(zs))
    centre = ((cmin[0] + cmax[0]) / 2, (cmin[1] + cmax[1]) / 2, (cmin[2] + cmax[2]) / 2)
    radius = 0.0
    for i in range(0, len(positions), 3):
        dx = positions[i] - centre[0]
        dy = positions[i + 1] - centre[1]
        dz = positions[i + 2] - centre[2]
        radius = max(radius, dx * dx + dy * dy + dz * dz)
    return cmin, cmax, centre, math.sqrt(radius)


def _rotate(rotation, p):
    """Apply the node's Euler rotation to a point, matching the renderer's
    Rz·Rx·Ry order (so bounds sit where the mesh is drawn)."""
    rx, ry, rz = rotation
    x, y, z = p
    # Ry
    cy, sy = math.cos(ry), math.sin(ry)
    x, z = x * cy + z * sy, -x * sy + z * cy
    # Rx
    cx, sx = math.cos(rx), math.sin(rx)
    y, z = y * cx - z * sx, y * sx + z * cx
    # Rz
    cz, sz = math.cos(rz), math.sin(rz)
    x, y = x * cz - y * sz, x * sz + y * cz
    return (x, y, z)


def world_bounds(node, local):
    """A node's world-space bound, tagged by shape. AABB is re-fit around the
    transformed corners (conservative under rotation); the sphere is exact and
    rotation-invariant."""
    cmin, cmax, centre, radius = local
    s = node.scale
    px, py, pz = node.position

    if node.collision_shape == "sphere":
        cw = _rotate(node.rotation, centre)
        return ("sphere", (px + s * cw[0], py + s * cw[1], pz + s * cw[2]), radius * s)

    # AABB: transform all eight corners of the local box and take their extent.
    bmin = [math.inf, math.inf, math.inf]
    bmax = [-math.inf, -math.inf, -math.inf]
    for ax in (cmin[0], cmax[0]):
        for ay in (cmin[1], cmax[1]):
            for az in (cmin[2], cmax[2]):
                wx, wy, wz = _rotate(node.rotation, (ax, ay, az))
                wx, wy, wz = px + s * wx, py + s * wy, pz + s * wz
                bmin[0], bmax[0] = min(bmin[0], wx), max(bmax[0], wx)
                bmin[1], bmax[1] = min(bmin[1], wy), max(bmax[1], wy)
                bmin[2], bmax[2] = min(bmin[2], wz), max(bmax[2], wz)
    return ("aabb", tuple(bmin), tuple(bmax))


def _aabb_aabb(a_min, a_max, b_min, b_max) -> bool:
    return (
        a_min[0] <= b_max[0] and a_max[0] >= b_min[0]
        and a_min[1] <= b_max[1] and a_max[1] >= b_min[1]
        and a_min[2] <= b_max[2] and a_max[2] >= b_min[2]
    )


def _sphere_sphere(ca, ra, cb, rb) -> bool:
    dx, dy, dz = ca[0] - cb[0], ca[1] - cb[1], ca[2] - cb[2]
    rr = ra + rb
    return dx * dx + dy * dy + dz * dz <= rr * rr


def _sphere_aabb(c, r, b_min, b_max) -> bool:
    # Nearest point on the box to the sphere centre, then distance.
    d = 0.0
    for i in range(3):
        v = c[i]
        if v < b_min[i]:
            d += (b_min[i] - v) ** 2
        elif v > b_max[i]:
            d += (v - b_max[i]) ** 2
    return d <= r * r


def overlap(a, b) -> bool:
    """Do two tagged world bounds overlap? Handles every shape combination."""
    if a[0] == "aabb" and b[0] == "aabb":
        return _aabb_aabb(a[1], a[2], b[1], b[2])
    if a[0] == "sphere" and b[0] == "sphere":
        return _sphere_sphere(a[1], a[2], b[1], b[2])
    if a[0] == "sphere":  # sphere vs aabb
        return _sphere_aabb(a[1], a[2], b[1], b[2])
    return _sphere_aabb(b[1], b[2], a[1], a[2])  # aabb vs sphere


class CollisionSystem:
    """Steps collisions once per frame: fits each colliding node's bound, tests
    the pairs that share a layer, and fires enter/exit events. Caches each mesh's
    local bound by identity and remembers which pairs overlapped last frame."""

    def __init__(self) -> None:
        self._local: dict[int, tuple] = {}  # id(mesh) -> local bounds
        self._prev: dict[tuple, tuple] = {}  # pair key -> (node_a, node_b)

    def _local_for(self, mesh):
        key = id(mesh)
        cached = self._local.get(key)
        if cached is None:
            from . import geometry  # deferred: avoid import cycle at module load

            cached = local_bounds(geometry.from_mesh(mesh).positions)
            self._local[key] = cached
        return cached

    def step(self, scene, app) -> None:
        nodes = [n for n in scene.nodes if getattr(n, "collision", False)]

        current: dict[tuple, tuple] = {}
        colliders: dict[int, list] = {}
        if len(nodes) >= 2:
            bounds = {id(n): world_bounds(n, self._local_for(n.mesh)) for n in nodes}
            for i in range(len(nodes)):
                a = nodes[i]
                la = _as_set(a.layers)
                for j in range(i + 1, len(nodes)):
                    b = nodes[j]
                    if la.isdisjoint(_as_set(b.layers)):
                        continue
                    if overlap(bounds[id(a)], bounds[id(b)]):
                        ia, ib = id(a), id(b)
                        key = (ia, ib) if ia < ib else (ib, ia)
                        current[key] = (a, b)
                        colliders.setdefault(ia, []).append(b)
                        colliders.setdefault(ib, []).append(a)

        # Enter: overlapping now but not last frame.
        for key, (a, b) in current.items():
            if key not in self._prev:
                self._fire(a, b, "collision", colliders, app)
                self._fire(b, a, "collision", colliders, app)
        # Exit: overlapped last frame but not now.
        for key, (a, b) in self._prev.items():
            if key not in current:
                self._fire(a, b, "collision_exit", colliders, app)
                self._fire(b, a, "collision_exit", colliders, app)

        self._prev = current

    @staticmethod
    def _fire(node, other, event_type, colliders, app) -> None:
        node.events.emit(
            Event(
                event_type,
                app=app,
                node=node,
                other=other,
                others=tuple(colliders.get(id(node), ())),
            )
        )
