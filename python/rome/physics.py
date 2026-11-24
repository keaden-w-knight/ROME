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


def _mesh_local_bounds(mesh, cache):
    """A mesh's local (min, max, centre, radius) bounds, cached by identity. Shared
    by the collision system and the character controller."""
    key = id(mesh)
    v = cache.get(key)
    if v is None:
        from . import geometry  # deferred: avoid an import cycle at module load

        v = local_bounds(geometry.from_mesh(mesh).positions)
        cache[key] = v
    return v


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


# --- Contacts (for resolution): the normal (pointing from a toward b) and how
# deep they penetrate. Used only for solid-vs-solid pairs. ---

def _contact_sphere_sphere(ca, ra, cb, rb):
    dx, dy, dz = cb[0] - ca[0], cb[1] - ca[1], cb[2] - ca[2]
    d2 = dx * dx + dy * dy + dz * dz
    if d2 < 1e-18:
        return (1.0, 0.0, 0.0), ra + rb  # coincident: pick any axis
    d = math.sqrt(d2)
    return (dx / d, dy / d, dz / d), ra + rb - d


def _contact_aabb_aabb(a_min, a_max, b_min, b_max):
    overlaps = [min(a_max[k], b_max[k]) - max(a_min[k], b_min[k]) for k in range(3)]
    axis = min(range(3), key=lambda k: overlaps[k])  # axis of least penetration
    a_c = (a_min[axis] + a_max[axis]) / 2
    b_c = (b_min[axis] + b_max[axis]) / 2
    n = [0.0, 0.0, 0.0]
    n[axis] = 1.0 if b_c >= a_c else -1.0
    return tuple(n), overlaps[axis]


def _contact_sphere_aabb(c, r, b_min, b_max):
    """Normal points from the sphere toward the box."""
    closest = [min(max(c[k], b_min[k]), b_max[k]) for k in range(3)]
    dx = [c[k] - closest[k] for k in range(3)]
    d2 = dx[0] * dx[0] + dx[1] * dx[1] + dx[2] * dx[2]
    if d2 > 1e-18:  # centre outside the box
        d = math.sqrt(d2)
        return (-dx[0] / d, -dx[1] / d, -dx[2] / d), r - d
    # centre inside the box: push out along the nearest face
    best_axis, best_dist, best_sign = 0, math.inf, 1.0
    for k in range(3):
        to_min, to_max = c[k] - b_min[k], b_max[k] - c[k]
        dist, sign = (to_min, -1.0) if to_min < to_max else (to_max, 1.0)
        if dist < best_dist:
            best_axis, best_dist, best_sign = k, dist, sign
    n = [0.0, 0.0, 0.0]
    n[best_axis] = -best_sign  # a→b points opposite the sphere's exit direction
    return tuple(n), best_dist + r


def contact(a, b):
    """(normal a→b, penetration) for two overlapping tagged bounds, any shapes."""
    if a[0] == "sphere" and b[0] == "sphere":
        return _contact_sphere_sphere(a[1], a[2], b[1], b[2])
    if a[0] == "aabb" and b[0] == "aabb":
        return _contact_aabb_aabb(a[1], a[2], b[1], b[2])
    if a[0] == "sphere":  # sphere a vs box b: normal is already a→b
        return _contact_sphere_aabb(a[1], a[2], b[1], b[2])
    n, pen = _contact_sphere_aabb(b[1], b[2], a[1], a[2])  # sphere b vs box a: b→a
    return (-n[0], -n[1], -n[2]), pen


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
        # Dynamics: constant acceleration applied to solid movers, how many impulse
        # passes the solver runs (more = stiffer stacks), and the positional-fix
        # tuning (fraction of penetration removed per frame, and a tolerance so
        # resting contacts don't jitter). dt is clamped so a long frame can't make
        # bodies tunnel through everything.
        self.gravity: tuple = (0.0, 0.0, 0.0)
        self.solver_iterations = 4
        self.position_correction = 0.8
        self.slop = 0.01
        self.max_dt = 0.05

    @staticmethod
    def _inv_mass(node) -> float:
        if node.static_body or node.mass <= 0.0:
            return 0.0
        return 1.0 / node.mass

    def _integrate(self, participants, dt) -> None:
        """Advance solid movers by their velocity (and gravity). Non-solid nodes
        and static bodies are positioned by the game, so they're left alone."""
        if dt <= 0.0:
            return
        gx, gy, gz = self.gravity
        for n in participants:
            if not n.solid or n.static_body:
                continue
            vx, vy, vz = n.velocity
            vx, vy, vz = vx + gx * dt, vy + gy * dt, vz + gz * dt
            n.velocity = (vx, vy, vz)
            px, py, pz = n.position
            n.position = (px + vx * dt, py + vy * dt, pz + vz * dt)

    def _resolve(self, contacts) -> None:
        """Sequential-impulse solver: iterate the contacts, each pass killing the
        approaching relative velocity (with restitution) and applying friction,
        then a single positional correction so bodies don't sink."""
        percent, slop = self.position_correction, self.slop
        # contacts: (a, b, nx, ny, nz, pen, inv_a, inv_b)
        for _ in range(self.solver_iterations):
            for a, b, nx, ny, nz, pen, inv_a, inv_b in contacts:
                inv_sum = inv_a + inv_b
                if inv_sum == 0.0:
                    continue
                avx, avy, avz = a.velocity
                bvx, bvy, bvz = b.velocity
                rvx, rvy, rvz = bvx - avx, bvy - avy, bvz - avz
                vn = rvx * nx + rvy * ny + rvz * nz
                if vn >= 0.0:
                    continue  # already separating
                e = min(a.restitution, b.restitution)
                j = -(1.0 + e) * vn / inv_sum
                avx, avy, avz = avx - j * nx * inv_a, avy - j * ny * inv_a, avz - j * nz * inv_a
                bvx, bvy, bvz = bvx + j * nx * inv_b, bvy + j * ny * inv_b, bvz + j * nz * inv_b
                # Coulomb friction along the tangent of the (updated) relative vel.
                mu = math.sqrt(a.friction * b.friction)
                if mu > 0.0:
                    rvx, rvy, rvz = bvx - avx, bvy - avy, bvz - avz
                    vn2 = rvx * nx + rvy * ny + rvz * nz
                    tx, ty, tz = rvx - vn2 * nx, rvy - vn2 * ny, rvz - vn2 * nz
                    tl = math.sqrt(tx * tx + ty * ty + tz * tz)
                    if tl > 1e-9:
                        tx, ty, tz = tx / tl, ty / tl, tz / tl
                        jt = -(rvx * tx + rvy * ty + rvz * tz) / inv_sum
                        jt = max(-mu * j, min(mu * j, jt))  # clamp to the friction cone
                        avx, avy, avz = avx - jt * tx * inv_a, avy - jt * ty * inv_a, avz - jt * tz * inv_a
                        bvx, bvy, bvz = bvx + jt * tx * inv_b, bvy + jt * ty * inv_b, bvz + jt * tz * inv_b
                a.velocity, b.velocity = (avx, avy, avz), (bvx, bvy, bvz)
        # Positional correction: shove the pair apart so penetration doesn't
        # accumulate, split by inverse mass (the lighter body moves more).
        for a, b, nx, ny, nz, pen, inv_a, inv_b in contacts:
            inv_sum = inv_a + inv_b
            if inv_sum == 0.0:
                continue
            corr = max(pen - slop, 0.0) / inv_sum * percent
            ax, ay, az = a.position
            a.position = (ax - nx * corr * inv_a, ay - ny * corr * inv_a, az - nz * corr * inv_a)
            bx, by, bz = b.position
            b.position = (bx + nx * corr * inv_b, by + ny * corr * inv_b, bz + nz * corr * inv_b)

    def _local_for(self, mesh):
        return _mesh_local_bounds(mesh, self._local)

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
        # A node is in the physics world if it collides (fires events) or is solid
        # (gets resolved); solids are integrated before anything is detected.
        nodes = [
            n for n in scene.nodes
            if getattr(n, "collision", False) or getattr(n, "solid", False)
        ]
        dt = min(max(getattr(app, "dt", 0.0), 0.0), self.max_dt)
        self._integrate(nodes, dt)

        current: dict[tuple, tuple] = {}
        colliders: dict[int, list] = {}
        contacts: list = []
        if len(nodes) >= 2:
            bounds = [world_bounds(n, self._local_for(n.mesh)) for n in nodes]
            boxes = [aabb_of(bd) for bd in bounds]
            for i, j in self._candidate_pairs(nodes, boxes):
                a, b = nodes[i], nodes[j]
                if _as_set(a.layers).isdisjoint(_as_set(b.layers)):
                    continue
                if not overlap(bounds[i], bounds[j]):
                    continue
                if a.collision and b.collision:  # fire events
                    ia, ib = id(a), id(b)
                    key = (ia, ib) if ia < ib else (ib, ia)
                    current[key] = (a, b)
                    colliders.setdefault(ia, []).append(b)
                    colliders.setdefault(ib, []).append(a)
                if a.solid and b.solid:  # resolve
                    inv_a, inv_b = self._inv_mass(a), self._inv_mass(b)
                    if inv_a + inv_b > 0.0:
                        nrm, pen = contact(bounds[i], bounds[j])
                        contacts.append((a, b, nrm[0], nrm[1], nrm[2], pen, inv_a, inv_b))

        if contacts:
            self._resolve(contacts)

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


class CharacterController:
    """A kinematic sphere you move explicitly, that slides along solid nodes
    instead of passing through them — the usual way to drive a first- or
    third-person character.

    Unlike a dynamic solid body it never bounces, tips, or drifts, so input maps
    straight to motion: compute where you want to go and call ``move``; it resolves
    out of any solid it would end up inside, keeping the motion that runs *along*
    the surface (so you slide round a wall rather than sticking to it). ``plane_lock``
    pins the height, which is what you want for a ground walker with no gravity."""

    def __init__(self, position, radius: float = 0.4, layers=(0,), max_slides: int = 4,
                 plane_lock: bool = False) -> None:
        self.position = tuple(position)
        self.radius = radius
        self.layers = layers
        self.max_slides = max_slides  # resolve passes (corners need more than one)
        self.plane_lock = plane_lock
        self._local: dict[int, tuple] = {}

    def move(self, delta, scene):
        """Advance by ``delta`` then slide out of any solid node. Returns (and
        stores on ``self.position``) the resolved position. Only nodes that are
        ``solid`` and share a layer are considered."""
        start_y = self.position[1]
        p = (self.position[0] + delta[0], self.position[1] + delta[1], self.position[2] + delta[2])
        la = _as_set(self.layers)
        solids = [
            n for n in scene.nodes
            if getattr(n, "solid", False)
            and not la.isdisjoint(_as_set(getattr(n, "layers", (0,))))
        ]
        for _ in range(self.max_slides):
            hit = False
            for n in solids:
                bound = world_bounds(n, _mesh_local_bounds(n.mesh, self._local))
                nrm, pen = contact(("sphere", p, self.radius), bound)  # normal sphere→node
                if pen <= 0.0:
                    continue  # not actually overlapping this one
                # push the sphere out, opposite the toward-node normal
                p = (p[0] - nrm[0] * pen, p[1] - nrm[1] * pen, p[2] - nrm[2] * pen)
                hit = True
            if not hit:
                break
        if self.plane_lock:
            p = (p[0], start_y, p[2])
        self.position = p
        return p
