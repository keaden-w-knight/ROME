"""Mesh geometry: the common source both backends draw from.

Turns a mesh description (cube / sphere / OBJ file) into flat vertex arrays —
positions, normals, and triangle indices — so pointing either backend at the
same scene draws the same geometry. (The ASCII backend will consume these too
once `three_ascii` gains a from-arrays constructor; today it still uses its own
generator, which produces the same shapes.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass
class Geometry:
    """Flat arrays ready for GPU upload."""

    positions: list[float]  # xyz per vertex
    normals: list[float]  # xyz per vertex (same count as positions)
    indices: list[int]  # triangle list


def cube() -> Geometry:
    # Each face gets its own four vertices carrying the face normal, so edges
    # stay crisp (shared vertices with averaged normals would round them off).
    faces = [
        ((1.0, 0.0, 0.0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
        ((-1.0, 0.0, 0.0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
        ((0.0, 1.0, 0.0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
        ((0.0, -1.0, 0.0), [(-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)]),
        ((0.0, 0.0, 1.0), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0.0, 0.0, -1.0), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
    ]
    verts: list[Vec3] = []
    normals: list[Vec3] = []
    tris: list[tuple[int, int, int]] = []
    for normal, corners in faces:
        base = len(verts)
        for c in corners:
            verts.append((float(c[0]), float(c[1]), float(c[2])))
            normals.append(normal)
        tris.append((base, base + 1, base + 2))
        tris.append((base, base + 2, base + 3))
    return _build(verts, tris, normals)


def sphere(segments: int = 32, rings: int = 20) -> Geometry:
    segments = max(3, segments)
    rings = max(2, rings)
    verts: list[Vec3] = []
    for r in range(rings + 1):
        phi = math.pi * r / rings
        sp, cp = math.sin(phi), math.cos(phi)
        for s in range(segments + 1):
            theta = math.tau * s / segments
            st, ct = math.sin(theta), math.cos(theta)
            verts.append((sp * ct, cp, sp * st))
    stride = segments + 1
    tris: list[tuple[int, int, int]] = []
    for r in range(rings):
        for s in range(segments):
            a = r * stride + s
            b = a + stride
            # Wound so the normals point outward (CCW seen from outside), matching
            # the cube and OBJ convention.
            tris.append((a, a + 1, b))
            tris.append((a + 1, b + 1, b))
    # Analytic normals: a centred sphere's normal is its normalized position.
    # Exact, and identical for the duplicated seam/pole vertices, so there's no
    # lighting crease where the longitude wraps (which averaged normals leave).
    normals = [_normalized(v) for v in verts]
    return _build(verts, tris, normals)


def load_obj(path: str) -> Geometry:
    verts: list[Vec3] = []
    tris: list[tuple[int, int, int]] = []
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            parts = raw.split()
            if not parts:
                continue
            if parts[0] == "v":
                coords = [float(x) for x in parts[1:4]]
                if len(coords) < 3:
                    raise ValueError(f"{path}:{lineno}: malformed vertex")
                verts.append((coords[0], coords[1], coords[2]))
            elif parts[0] == "f":
                idx = []
                for tok in parts[1:]:
                    n = int(tok.split("/")[0])
                    idx.append(n - 1 if n > 0 else len(verts) + n)
                if len(idx) < 3:
                    raise ValueError(f"{path}:{lineno}: face needs 3+ vertices")
                for k in range(1, len(idx) - 1):  # fan triangulate
                    tris.append((idx[0], idx[k], idx[k + 1]))
    if not verts or not tris:
        raise ValueError(f"{path}: no geometry found")
    return _build(verts, tris)


def _build(
    verts: list[Vec3],
    tris: list[tuple[int, int, int]],
    normals: list[Vec3] | None = None,
) -> Geometry:
    verts = _center_and_scale(verts)
    # Explicit normals (e.g. a cube's per-face normals) are kept; otherwise smooth
    # per-vertex normals are computed. Centering/uniform scale don't change them.
    if normals is None:
        normals = _vertex_normals(verts, tris)
    positions: list[float] = []
    for v in verts:
        positions.extend(v)
    flat_normals: list[float] = []
    for n in normals:
        flat_normals.extend(n)
    indices: list[int] = []
    for t in tris:
        indices.extend(t)
    return Geometry(positions=positions, normals=flat_normals, indices=indices)


def _normalized(v: Vec3) -> Vec3:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length < 1e-6:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _center_and_scale(verts: list[Vec3]) -> list[Vec3]:
    """Centre on the origin and scale to roughly unit radius, so any model frames
    sensibly whatever units it was exported in."""
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    cz = (min(zs) + max(zs)) / 2
    hx = (max(xs) - min(xs)) / 2
    hy = (max(ys) - min(ys)) / 2
    hz = (max(zs) - min(zs)) / 2
    extent = max(math.sqrt(hx * hx + hy * hy + hz * hz), 1e-6)
    return [((v[0] - cx) / extent, (v[1] - cy) / extent, (v[2] - cz) / extent) for v in verts]


def _vertex_normals(verts: list[Vec3], tris: list[tuple[int, int, int]]) -> list[Vec3]:
    """Area-weighted vertex normals (each face contributes its un-normalized
    cross product), then normalized per vertex."""
    acc = [[0.0, 0.0, 0.0] for _ in verts]
    for a, b, c in tris:
        va, vb, vc = verts[a], verts[b], verts[c]
        e1 = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
        e2 = (vc[0] - va[0], vc[1] - va[1], vc[2] - va[2])
        fn = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        )
        for i in (a, b, c):
            acc[i][0] += fn[0]
            acc[i][1] += fn[1]
            acc[i][2] += fn[2]
    normals: list[Vec3] = []
    for n in acc:
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if length < 1e-6:
            normals.append((0.0, 0.0, 1.0))
        else:
            normals.append((n[0] / length, n[1] / length, n[2] / length))
    return normals
