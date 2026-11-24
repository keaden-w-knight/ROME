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


def _median(values) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


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


def aabb_of(bound):
    """The axis-aligned (min, max) box enclosing a tagged bound — a sphere's is
    its centre ± radius. Used by the broadphase grid, which is boxes-only."""
    if bound[0] == "aabb":
        return bound[1], bound[2]
    c, r = bound[1], bound[2]
    return (c[0] - r, c[1] - r, c[2] - r), (c[0] + r, c[1] + r, c[2] + r)


class CollisionSystem:
    """Steps collisions once per frame: fits each colliding node's bound, tests
    the pairs that share a layer, and fires enter/exit events. Caches each mesh's
    local bound by identity and remembers which pairs overlapped last frame."""

    #: below this many colliding nodes, brute force is cheaper than hashing.
    brute_threshold = 48

    def __init__(self) -> None:
        self._local: dict[int, tuple] = {}  # id(mesh) -> local bounds
        self._prev: dict[tuple, tuple] = {}  # pair key -> (node_a, node_b)
        self.cell_size: float | None = None  # None = auto (from the typical object)
        self.use_grid = True  # False forces brute force (used by tests for parity)

    def _local_for(self, mesh):
        key = id(mesh)
        cached = self._local.get(key)
        if cached is None:
            from . import geometry  # deferred: avoid import cycle at module load

            cached = local_bounds(geometry.from_mesh(mesh).positions)
            self._local[key] = cached
        return cached

    def _candidate_pairs(self, nodes, boxes):
        """Index pairs worth a precise test. Brute force for a few nodes; above
        ``brute_threshold`` a uniform spatial hash, so far-apart nodes are never
        compared — ~O(n) for evenly-spread scenes instead of O(n²).

        ``boxes[i]`` is node i's (min, max) AABB. The cell is sized from the
        typical (median) object; the rare node much larger than a cell (a ground
        plane) is pulled out and tested against everyone, so one big object can't
        collapse the grid back to O(n²)."""
        n = len(nodes)
        if n < self.brute_threshold or not self.use_grid:
            return [(i, j) for i in range(n) for j in range(i + 1, n)]

        extents = [max(mx[k] - mn[k] for k in range(3)) / 2 for mn, mx in boxes]
        cell = self.cell_size or 2.0 * _median(extents)
        cell = max(cell, 1e-6)

        grid: dict[tuple, list[int]] = {}
        large: list[int] = []
        for i, (mn, mx) in enumerate(boxes):
            if extents[i] > cell:  # bigger than a cell: brute-force it instead
                large.append(i)
                continue
            for cx in range(int(mn[0] // cell), int(mx[0] // cell) + 1):
                for cy in range(int(mn[1] // cell), int(mx[1] // cell) + 1):
                    for cz in range(int(mn[2] // cell), int(mx[2] // cell) + 1):
                        grid.setdefault((cx, cy, cz), []).append(i)

        pairs: set[tuple[int, int]] = set()
        for bucket in grid.values():
            for bi in range(len(bucket)):
                for bj in range(bi + 1, len(bucket)):
                    a, b = bucket[bi], bucket[bj]
                    pairs.add((a, b) if a < b else (b, a))
        for i in large:  # large nodes vs everyone (they're few)
            for j in range(n):
                if j != i:
                    pairs.add((i, j) if i < j else (j, i))
        return pairs

    def step(self, scene, app) -> None:
        nodes = [n for n in scene.nodes if getattr(n, "collision", False)]

        current: dict[tuple, tuple] = {}
        colliders: dict[int, list] = {}
        if len(nodes) >= 2:
            bounds = [world_bounds(n, self._local_for(n.mesh)) for n in nodes]
            boxes = [aabb_of(bd) for bd in bounds]
            for i, j in self._candidate_pairs(nodes, boxes):
                a, b = nodes[i], nodes[j]
                if _as_set(a.layers).isdisjoint(_as_set(b.layers)):
                    continue
                if overlap(bounds[i], bounds[j]):
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
