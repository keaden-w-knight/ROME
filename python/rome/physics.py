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
from collections import namedtuple

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


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _body_centre(bound):
    """World centre of a tagged bound (sphere centre, or box midpoint)."""
    if bound[0] == "sphere":
        return bound[1]
    mn, mx = bound[1], bound[2]
    return ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2)


def _reach_along(bound, n):
    """How far the bound's surface is from its centre along direction ``n`` — the
    support distance. For the contact point used by the angular solver."""
    if bound[0] == "sphere":
        return bound[2]
    mn, mx = bound[1], bound[2]
    return (abs(n[0]) * (mx[0] - mn[0]) + abs(n[1]) * (mx[1] - mn[1])
            + abs(n[2]) * (mx[2] - mn[2])) / 2


# One solid-solid contact, everything the impulse solver needs. Inertia is a
# scalar approximation (isotropic) rather than a full tensor — plausible spin for
# a game, not a rigid-body reference.
Contact = namedtuple("Contact", "a b n pen inv_ma inv_mb invIa invIb ca cb cp")


def _inv_inertia(node, radius) -> float:
    """Inverse of a scalar moment of inertia: solid sphere 2/5·m·r², box ~1/6·m·r².
    Static bodies and zero mass are immovable (0)."""
    if node.static_body or node.mass <= 0.0 or radius <= 0.0:
        return 0.0
    factor = 0.4 if node.collision_shape == "sphere" else (1.0 / 6.0)
    inertia = factor * node.mass * radius * radius
    return 1.0 / inertia if inertia > 0.0 else 0.0


# --- Quaternion orientation (x, y, z, w). Used to integrate spin exactly, then
# converted back to the Euler `rotation` both renderers read. This fixes the
# small-angle error of adding ω·dt to Euler angles (wrong for multi-axis spin);
# the only residual limit is gimbal lock in the Euler *representation* near
# pitch ±90°, which a full quaternion render path (renderer + 3-ASCII) would
# remove. ---

def _quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def _euler_to_quat(e):
    """Euler (rx, ry, rz) → quaternion, matching the renderer's Rz·Rx·Ry order."""
    rx, ry, rz = e[0] / 2, e[1] / 2, e[2] / 2
    qx = (math.sin(rx), 0.0, 0.0, math.cos(rx))
    qy = (0.0, math.sin(ry), 0.0, math.cos(ry))
    qz = (0.0, 0.0, math.sin(rz), math.cos(rz))
    return _quat_mul(qz, _quat_mul(qx, qy))


def _quat_to_euler(q):
    """Quaternion → Euler (rx, ry, rz) in the renderer's Rz·Rx·Ry convention."""
    x, y, z, w = q
    # Rotation matrix elements we need (R = Rz·Rx·Ry): sin(rx)=R21, and
    # ry/rz from the surrounding terms. See the matrix in the collision docs.
    r21 = 2.0 * (y * z + w * x)
    r21 = max(-1.0, min(1.0, r21))
    rx = math.asin(r21)
    if abs(r21) < 0.99999:
        r20 = 2.0 * (x * z - w * y)
        r22 = 1.0 - 2.0 * (x * x + y * y)
        r01 = 2.0 * (x * y - w * z)
        r11 = 1.0 - 2.0 * (x * x + z * z)
        ry = math.atan2(-r20, r22)
        rz = math.atan2(-r01, r11)
    else:  # gimbal lock: fold ry into rz
        r00 = 1.0 - 2.0 * (y * y + z * z)
        r10 = 2.0 * (x * y + w * z)
        ry = 0.0
        rz = math.atan2(r10, r00)
    return (rx, ry, rz)


def _quat_integrate(q, omega, dt):
    """Rotate q by the exact rotation ω implies over dt (axis-angle, not a
    first-order step), then renormalise."""
    ox, oy, oz = omega
    speed = math.sqrt(ox * ox + oy * oy + oz * oz)
    if speed < 1e-12:
        return q
    half = speed * dt / 2.0
    s = math.sin(half) / speed
    dq = (ox * s, oy * s, oz * s, math.cos(half))
    r = _quat_mul(dq, q)
    n = math.sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2] + r[3] * r[3])
    return (r[0] / n, r[1] / n, r[2] / n, r[3] / n) if n > 0.0 else q


# --- Swept sphere (exact time-of-impact). A sphere at p0 moving by v over a frame
# (centre p0 + t·v, t in 0..1) against a static bound; returns (t, normal) at first
# contact, normal pointing from the obstacle toward the sphere (the slide/push
# direction), or None for no hit. Exact for sphere-sphere; sphere-box uses the
# radius-inflated slab test (slightly boxy at rounded corners, never tunnels). ---

def _sweep_sphere_sphere(p0, r, v, c, rb):
    dx, dy, dz = p0[0] - c[0], p0[1] - c[1], p0[2] - c[2]
    R = r + rb
    a = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
    cc = dx * dx + dy * dy + dz * dz - R * R
    if cc <= 0.0:  # already touching
        d = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        return 0.0, (dx / d, dy / d, dz / d)
    if a < 1e-18:
        return None  # not moving and not already overlapping
    b = 2.0 * (dx * v[0] + dy * v[1] + dz * v[2])
    disc = b * b - 4.0 * a * cc
    if disc < 0.0:
        return None
    t = (-b - math.sqrt(disc)) / (2.0 * a)
    if t < 0.0 or t > 1.0:
        return None
    hx, hy, hz = dx + t * v[0], dy + t * v[1], dz + t * v[2]
    d = math.sqrt(hx * hx + hy * hy + hz * hz) or 1.0
    return t, (hx / d, hy / d, hz / d)


def _sweep_sphere_aabb(p0, r, v, b_min, b_max):
    emin = (b_min[0] - r, b_min[1] - r, b_min[2] - r)
    emax = (b_max[0] + r, b_max[1] + r, b_max[2] + r)
    tmin, tmax = 0.0, 1.0
    axis, sign = 0, 1.0
    for k in range(3):
        if abs(v[k]) < 1e-12:
            if p0[k] < emin[k] or p0[k] > emax[k]:
                return None  # parallel to this slab and outside it
            continue
        inv = 1.0 / v[k]
        t1, t2, s = (emin[k] - p0[k]) * inv, (emax[k] - p0[k]) * inv, -1.0
        if t1 > t2:
            t1, t2, s = t2, t1, 1.0
        if t1 > tmin:
            tmin, axis, sign = t1, k, s
        if t2 < tmax:
            tmax = t2
        if tmin > tmax:
            return None
    n = [0.0, 0.0, 0.0]
    n[axis] = sign
    return tmin, tuple(n)


def sweep_sphere(p0, r, v, bound):
    """Swept sphere vs a tagged bound → (toi, normal) or None (see above)."""
    if bound[0] == "sphere":
        return _sweep_sphere_sphere(p0, r, v, bound[1], bound[2])
    return _sweep_sphere_aabb(p0, r, v, bound[1], bound[2])


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
        # Continuous collision via substepping: when a solid mover would travel
        # far relative to its own size in one frame, split the frame so it can't
        # jump through a thin wall. Costs an extra detect per substep, so it only
        # kicks in for genuinely fast bodies (normal frames stay a single step).
        self.ccd = True
        self.max_substeps = 8
        # Sleeping: a solid mover that stays below these speeds for sleep_time is
        # put to sleep — skipped by integration and resolution — until a moving
        # body touches it. Whole contact-connected islands sleep and wake together,
        # so a resting stack costs nothing and doesn't jitter.
        self.sleeping = True
        self.sleep_linear = 0.05
        self.sleep_angular = 0.05
        self.sleep_time = 0.5
        self._sleep_timer: dict[int, float] = {}

    @staticmethod
    def _inv_mass(node) -> float:
        if node.static_body or node.mass <= 0.0:
            return 0.0
        return 1.0 / node.mass

    def _integrate(self, participants, dt, static_bounds=None) -> None:
        """Advance solid movers by their velocity (and gravity). Non-solid nodes
        and static bodies are positioned by the game, so they're left alone. A
        sphere mover is swept against the static world and stopped at its first
        time-of-impact, so it can't tunnel a wall even in a single big step."""
        if dt <= 0.0:
            return
        gx, gy, gz = self.gravity
        for n in participants:
            if not n.solid or n.static_body or not n.awake:
                continue  # sleeping bodies are frozen in place until woken
            vx, vy, vz = n.velocity
            vx, vy, vz = vx + gx * dt, vy + gy * dt, vz + gz * dt
            n.velocity = (vx, vy, vz)
            dx, dy, dz = vx * dt, vy * dt, vz * dt
            if static_bounds and n.collision_shape == "sphere" and (dx or dy or dz):
                local = _mesh_local_bounds(n.mesh, self._local)
                centre = _body_centre(world_bounds(n, local))
                r = local[3] * n.scale
                best_t = 1.0
                for _s, sb in static_bounds:
                    hit = sweep_sphere(centre, r, (dx, dy, dz), sb)
                    if hit is not None and hit[0] < best_t:
                        best_t = hit[0]
                if best_t < 1.0:  # stop at the wall; the resolver bounces it
                    dx, dy, dz = dx * best_t, dy * best_t, dz * best_t
            px, py, pz = n.position
            n.position = (px + dx, py + dy, pz + dz)
            # Angular: decay, then advance orientation by integrating the spin as a
            # quaternion (exact for any axis) and writing it back as Euler.
            wx, wy, wz = n.angular_velocity
            if wx or wy or wz:
                if n.angular_damping:
                    k = max(0.0, 1.0 - n.angular_damping * dt)
                    wx, wy, wz = wx * k, wy * k, wz * k
                    n.angular_velocity = (wx, wy, wz)
                q = _quat_integrate(_euler_to_quat(n.rotation), (wx, wy, wz), dt)
                n.rotation = _quat_to_euler(q)

    @staticmethod
    def _apply_impulse(c, imp):
        """Add impulse ``imp`` at the contact (linear + angular) to both bodies —
        a gets -imp at ca, b gets +imp at cb (angular via the lever arm)."""
        a, b = c.a, c.b
        if c.inv_ma > 0.0 or c.invIa > 0.0:
            av = a.velocity
            a.velocity = (av[0] - imp[0] * c.inv_ma, av[1] - imp[1] * c.inv_ma,
                          av[2] - imp[2] * c.inv_ma)
            ra = (c.cp[0] - c.ca[0], c.cp[1] - c.ca[1], c.cp[2] - c.ca[2])
            ta = _cross(ra, imp)
            aw = a.angular_velocity
            a.angular_velocity = (aw[0] - ta[0] * c.invIa, aw[1] - ta[1] * c.invIa,
                                  aw[2] - ta[2] * c.invIa)
        if c.inv_mb > 0.0 or c.invIb > 0.0:
            bv = b.velocity
            b.velocity = (bv[0] + imp[0] * c.inv_mb, bv[1] + imp[1] * c.inv_mb,
                          bv[2] + imp[2] * c.inv_mb)
            rb = (c.cp[0] - c.cb[0], c.cp[1] - c.cb[1], c.cp[2] - c.cb[2])
            tb = _cross(rb, imp)
            bw = b.angular_velocity
            b.angular_velocity = (bw[0] + tb[0] * c.invIb, bw[1] + tb[1] * c.invIb,
                                  bw[2] + tb[2] * c.invIb)

    @staticmethod
    def _rel_vel(c):
        """Relative velocity of the two bodies *at the contact point* — includes
        each body's spin (v + ω×r)."""
        a, b = c.a, c.b
        ra = (c.cp[0] - c.ca[0], c.cp[1] - c.ca[1], c.cp[2] - c.ca[2])
        rb = (c.cp[0] - c.cb[0], c.cp[1] - c.cb[1], c.cp[2] - c.cb[2])
        va = tuple(a.velocity[k] + _cross(a.angular_velocity, ra)[k] for k in range(3))
        vb = tuple(b.velocity[k] + _cross(b.angular_velocity, rb)[k] for k in range(3))
        return (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])

    def _eff_mass(self, c, axis):
        """Inverse effective mass along ``axis`` (a unit direction), including the
        rotational term invI·|r×axis|² for each body."""
        ra = (c.cp[0] - c.ca[0], c.cp[1] - c.ca[1], c.cp[2] - c.ca[2])
        rb = (c.cp[0] - c.cb[0], c.cp[1] - c.cb[1], c.cp[2] - c.cb[2])
        raxa, rbxa = _cross(ra, axis), _cross(rb, axis)
        return (c.inv_ma + c.inv_mb
                + c.invIa * _dot(raxa, raxa) + c.invIb * _dot(rbxa, rbxa))

    def _resolve(self, contacts) -> None:
        """Sequential-impulse solver with rotation: each pass kills the approaching
        relative velocity at the contact point (restitution), then friction;
        impulses applied at the contact point also spin the bodies. A final linear
        positional correction keeps penetration from accumulating."""
        percent, slop = self.position_correction, self.slop
        for _ in range(self.solver_iterations):
            for c in contacts:
                rv = self._rel_vel(c)
                vn = _dot(rv, c.n)
                if vn >= 0.0:
                    continue  # already separating
                inv_eff = self._eff_mass(c, c.n)
                if inv_eff <= 0.0:
                    continue
                e = min(c.a.restitution, c.b.restitution)
                j = -(1.0 + e) * vn / inv_eff
                self._apply_impulse(c, (c.n[0] * j, c.n[1] * j, c.n[2] * j))
                # Coulomb friction along the contact tangent.
                mu = math.sqrt(c.a.friction * c.b.friction)
                if mu <= 0.0:
                    continue
                rv = self._rel_vel(c)
                vn2 = _dot(rv, c.n)
                t = (rv[0] - vn2 * c.n[0], rv[1] - vn2 * c.n[1], rv[2] - vn2 * c.n[2])
                tl = math.sqrt(_dot(t, t))
                if tl <= 1e-9:
                    continue
                t = (t[0] / tl, t[1] / tl, t[2] / tl)
                inv_eff_t = self._eff_mass(c, t)
                if inv_eff_t <= 0.0:
                    continue
                jt = -_dot(rv, t) / inv_eff_t
                jt = max(-mu * j, min(mu * j, jt))  # clamp to the friction cone
                self._apply_impulse(c, (t[0] * jt, t[1] * jt, t[2] * jt))
        # Positional correction (linear only), split by inverse mass.
        for c in contacts:
            inv_sum = c.inv_ma + c.inv_mb
            if inv_sum == 0.0:
                continue
            corr = max(c.pen - slop, 0.0) / inv_sum * percent
            nx, ny, nz = c.n
            ax, ay, az = c.a.position
            c.a.position = (ax - nx * corr * c.inv_ma, ay - ny * corr * c.inv_ma,
                            az - nz * corr * c.inv_ma)
            bx, by, bz = c.b.position
            c.b.position = (bx + nx * corr * c.inv_mb, by + ny * corr * c.inv_mb,
                            bz + nz * corr * c.inv_mb)

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

    def _detect(self, nodes):
        """One broadphase + narrowphase pass over the current positions. Returns
        the event pairs (``current``, ``colliders``) and the solid-solid
        ``contacts`` to resolve."""
        current: dict[tuple, tuple] = {}
        colliders: dict[int, list] = {}
        contacts: list = []
        if len(nodes) < 2:
            return current, colliders, contacts
        locals_ = [self._local_for(n.mesh) for n in nodes]
        bounds = [world_bounds(n, locals_[i]) for i, n in enumerate(nodes)]
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
                invIa = _inv_inertia(a, locals_[i][3] * a.scale)
                invIb = _inv_inertia(b, locals_[j][3] * b.scale)
                if inv_a + inv_b + invIa + invIb > 0.0:
                    nrm, pen = contact(bounds[i], bounds[j])
                    ca, cb = _body_centre(bounds[i]), _body_centre(bounds[j])
                    reach_a, reach_b = _reach_along(bounds[i], nrm), _reach_along(bounds[j], nrm)
                    # contact point: midpoint of each body's surface point along n
                    pa = (ca[0] + nrm[0] * reach_a, ca[1] + nrm[1] * reach_a, ca[2] + nrm[2] * reach_a)
                    pb = (cb[0] - nrm[0] * reach_b, cb[1] - nrm[1] * reach_b, cb[2] - nrm[2] * reach_b)
                    cp = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2)
                    contacts.append(Contact(a, b, nrm, pen, inv_a, inv_b, invIa, invIb, ca, cb, cp))
        return current, colliders, contacts

    def _substeps(self, nodes, dt) -> int:
        """How many substeps this frame needs so no solid mover travels more than
        ~half its own size in one — the continuous-collision guard. 1 unless
        something is moving fast."""
        if not self.ccd or dt <= 0.0:
            return 1
        sub = 1
        for n in nodes:
            if not n.solid or n.static_body:
                continue
            if n.collision_shape == "sphere":
                continue  # sphere movers use exact swept CCD, not substeps
            vx, vy, vz = n.velocity
            disp = math.sqrt(vx * vx + vy * vy + vz * vz) * dt
            if disp <= 0.0:
                continue
            ext = _mesh_local_bounds(n.mesh, self._local)[3] * n.scale  # ~radius
            if ext <= 0.0:
                continue
            need = math.ceil(disp / (ext * 0.5))
            if need > sub:
                sub = need
        return min(sub, self.max_substeps)

    @staticmethod
    def _awake_mover(n) -> bool:
        return n.solid and not n.static_body and n.awake

    def _wake(self, contacts) -> None:
        """Island wake: a mover touching an awake mover (directly or through a
        chain of resting contacts) is woken, so a hit propagates through a pile."""
        if not self.sleeping:
            return
        adj: dict[int, set] = {}
        by_id: dict[int, object] = {}
        for c in contacts:
            am = c.a.solid and not c.a.static_body
            bm = c.b.solid and not c.b.static_body
            if am:
                by_id[id(c.a)] = c.a
            if bm:
                by_id[id(c.b)] = c.b
            if am and bm:  # an edge in the island graph
                adj.setdefault(id(c.a), set()).add(id(c.b))
                adj.setdefault(id(c.b), set()).add(id(c.a))
        from collections import deque

        queue = deque(i for i, n in by_id.items() if n.awake)
        seen = set(queue)
        while queue:
            i = queue.popleft()
            for j in adj.get(i, ()):
                if j not in seen:
                    seen.add(j)
                    queue.append(j)
        for i in seen:
            n = by_id[i]
            if not n.awake:
                n.awake = True
                self._sleep_timer[i] = 0.0

    def _active(self, contacts):
        """Contacts worth solving: at least one awake mover (two resting bodies,
        or a resting body on static ground, need no impulse)."""
        if not self.sleeping:
            return contacts
        return [c for c in contacts if self._awake_mover(c.a) or self._awake_mover(c.b)]

    def _sleep_update(self, nodes, dt) -> None:
        """Advance each mover's rest timer; sleep one that's been slow long enough
        (zeroing its motion), wake one that's moving."""
        if not self.sleeping or dt <= 0.0:
            return
        lin2, ang2 = self.sleep_linear ** 2, self.sleep_angular ** 2
        for n in nodes:
            if not n.solid or n.static_body:
                continue
            vx, vy, vz = n.velocity
            wx, wy, wz = n.angular_velocity
            slow = (vx * vx + vy * vy + vz * vz) <= lin2 and (wx * wx + wy * wy + wz * wz) <= ang2
            i = id(n)
            if slow:
                self._sleep_timer[i] = self._sleep_timer.get(i, 0.0) + dt
                if self._sleep_timer[i] >= self.sleep_time:
                    n.awake = False
                    n.velocity = (0.0, 0.0, 0.0)
                    n.angular_velocity = (0.0, 0.0, 0.0)
            else:
                self._sleep_timer[i] = 0.0
                n.awake = True

    def step(self, scene, app) -> None:
        # A node is in the physics world if it collides (fires events) or is solid
        # (gets resolved); solids are integrated before anything is detected.
        nodes = [
            n for n in scene.nodes
            if getattr(n, "collision", False) or getattr(n, "solid", False)
        ]
        dt = min(max(getattr(app, "dt", 0.0), 0.0), self.max_dt)

        # Static solids don't move, so their bounds are fixed for the whole frame —
        # compute once for the swept sphere CCD in _integrate. Only when CCD is on.
        static_bounds = [
            (n, world_bounds(n, self._local_for(n.mesh)))
            for n in nodes if n.solid and n.static_body
        ] if self.ccd else []

        sub = self._substeps(nodes, dt)
        if sub == 1:
            self._integrate(nodes, dt, static_bounds)
            current, colliders, contacts = self._detect(nodes)
            self._wake(contacts)
            active = self._active(contacts)
            if active:
                self._resolve(active)
        else:
            # Substep non-sphere fast movers so they can't tunnel; detect once more
            # at the end for the frame's enter/exit events. (Spheres are swept.)
            hdt = dt / sub
            for _ in range(sub):
                self._integrate(nodes, hdt, static_bounds)
                _, _, contacts = self._detect(nodes)
                self._wake(contacts)
                active = self._active(contacts)
                if active:
                    self._resolve(active)
            current, colliders, _ = self._detect(nodes)

        self._sleep_update(nodes, dt)

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

    SKIN = 1e-3  # tiny gap kept off a surface so the next sweep doesn't re-hit it

    def __init__(self, position, radius: float = 0.4, layers=(0,), max_slides: int = 4,
                 plane_lock: bool = False) -> None:
        self.position = tuple(position)
        self.radius = radius
        self.layers = layers
        self.max_slides = max_slides  # how many times a blocked move may redirect
        self.plane_lock = plane_lock
        self._local: dict[int, tuple] = {}

    def _slide(self, p, solids):
        """Push a sphere at ``p`` out of every solid it overlaps, a few passes so
        corners settle. Tangential motion is untouched, which is the slide."""
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
        return p

    def move(self, delta, scene):
        """Advance by ``delta``, sweeping (exact time-of-impact) against solids so
        it can't tunnel a thin wall, and redirecting the leftover motion along each
        surface it meets (the slide). Returns (and stores on ``self.position``) the
        resolved position. Only ``solid`` nodes sharing a layer are considered."""
        start_y = self.position[1]
        la = _as_set(self.layers)
        solids = [
            (n, world_bounds(n, _mesh_local_bounds(n.mesh, self._local)))
            for n in scene.nodes
            if getattr(n, "solid", False)
            and not la.isdisjoint(_as_set(getattr(n, "layers", (0,))))
        ]
        p = self.position
        remaining = delta
        for _ in range(self.max_slides + 1):
            if remaining[0] ** 2 + remaining[1] ** 2 + remaining[2] ** 2 < 1e-12:
                break
            best = None
            for _n, bound in solids:
                hit = sweep_sphere(p, self.radius, remaining, bound)
                if hit is not None and (best is None or hit[0] < best[0]):
                    best = hit
            if best is None:  # clear path: take the whole remaining move
                p = (p[0] + remaining[0], p[1] + remaining[1], p[2] + remaining[2])
                break
            t, nrm = best
            # advance to the contact, kept a hair off the surface
            p = (p[0] + remaining[0] * t + nrm[0] * self.SKIN,
                 p[1] + remaining[1] * t + nrm[1] * self.SKIN,
                 p[2] + remaining[2] * t + nrm[2] * self.SKIN)
            # slide: drop the into-surface part of what's left
            lx, ly, lz = remaining[0] * (1 - t), remaining[1] * (1 - t), remaining[2] * (1 - t)
            d = lx * nrm[0] + ly * nrm[1] + lz * nrm[2]
            remaining = (lx - nrm[0] * d, ly - nrm[1] * d, lz - nrm[2] * d)
        p = self._slide(p, [n for n, _b in solids])  # depenetrate any residual
        if self.plane_lock:
            p = (p[0], start_y, p[2])
        self.position = p
        return p
