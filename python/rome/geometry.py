"""Mesh geometry: the common source both backends draw from.

Turns a mesh description (cube / sphere / OBJ file) into flat vertex arrays —
positions, normals, and triangle indices — so pointing either backend at the
same scene draws the same geometry. (The ASCII backend will consume these too
once `three_ascii` gains a from-arrays constructor; today it still uses its own
generator, which produces the same shapes.)
"""

from __future__ import annotations

import base64
import json
import math
import os
import struct
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass
class Geometry:
    """Flat arrays ready for GPU upload."""

    positions: list[float]  # xyz per vertex
    normals: list[float]  # xyz per vertex (same count as positions)
    indices: list[int]  # triangle list


def from_mesh(mesh) -> Geometry:
    """Turn a framework ``rome.scene.Mesh`` into flat arrays. The single place the
    mesh *kind* is mapped to geometry, so both backends draw the same thing."""
    kind = mesh.kind
    if kind == "sphere":
        return sphere(mesh.segments, mesh.rings)
    if kind == "cube":
        return cube()
    if kind == "plane":
        return plane()
    if kind == "obj":
        return load_obj(mesh.path)
    if kind == "gltf":
        return load_gltf(mesh.path)
    if kind == "arrays":
        return from_arrays(mesh.positions, mesh.normals, mesh.indices)
    raise ValueError(f"unknown mesh kind {kind!r}")


def _flat(seq) -> list:
    """Flatten a positions/normals/indices argument to a flat Python list.

    Accepts a flat sequence ``[x, y, z, ...]``, a sequence of tuples
    ``[(x, y, z), ...]``, or a numpy array of any shape — so numpy meshes drop in
    without a hard numpy dependency here."""
    if hasattr(seq, "reshape") and hasattr(seq, "tolist"):  # numpy ndarray
        return seq.reshape(-1).tolist()
    out: list = []
    for x in seq:
        if isinstance(x, (list, tuple)):
            out.extend(x)
        else:
            out.append(x)
    return out


def from_arrays(positions, normals=None, indices=None) -> Geometry:
    """Build geometry from caller-supplied vertex arrays — numpy arrays or plain
    lists, flat (``[x, y, z, ...]``) or per-vertex (``[(x, y, z), ...]``).

    ``indices`` may be omitted for a triangle soup (vertices taken three at a
    time); ``normals`` may be omitted and smooth per-vertex normals are computed.
    Coordinates are kept as given — unlike the file loaders, this does not recentre
    or rescale, because the caller placed these vertices deliberately."""
    pos = [float(x) for x in _flat(positions)]
    if len(pos) % 3:
        raise ValueError("positions length must be a multiple of 3")
    nverts = len(pos) // 3
    verts = [(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]) for i in range(nverts)]

    if indices is None:
        idx = list(range(nverts))
    else:
        idx = [int(i) for i in _flat(indices)]
    if len(idx) % 3:
        raise ValueError("indices length must be a multiple of 3")
    tris = [(idx[k], idx[k + 1], idx[k + 2]) for k in range(0, len(idx), 3)]

    if normals is None:
        norms = _vertex_normals(verts, tris)
    else:
        nrm = [float(x) for x in _flat(normals)]
        if len(nrm) != len(pos):
            raise ValueError("normals must have the same length as positions")
        norms = [(nrm[3 * i], nrm[3 * i + 1], nrm[3 * i + 2]) for i in range(nverts)]

    flat_normals: list[float] = []
    for n in norms:
        flat_normals.extend(n)
    return Geometry(positions=pos, normals=flat_normals, indices=idx)


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


def plane() -> Geometry:
    """A flat square on the XZ plane (y = 0), facing up (+Y). Scale it for a
    ground. Centred, so one unit each way before Node scale."""
    verts = [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (1.0, 0.0, 1.0), (-1.0, 0.0, 1.0)]
    normals = [(0.0, 1.0, 0.0)] * 4
    tris = [(0, 1, 2), (0, 2, 3)]
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


_GLTF_COMPONENT = {
    5120: ("b", 1),  # BYTE
    5121: ("B", 1),  # UNSIGNED_BYTE
    5122: ("h", 2),  # SHORT
    5123: ("H", 2),  # UNSIGNED_SHORT
    5125: ("I", 4),  # UNSIGNED_INT
    5126: ("f", 4),  # FLOAT
}
_GLTF_TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_gltf(path: str) -> Geometry:
    """Load geometry from a glTF 2.0 file (.glb binary, or .gltf with external /
    base64 buffers). Walks the node hierarchy and applies each node's world
    transform, so multi-part models land correctly positioned. Falls back to
    mesh-local geometry when the file has no nodes."""
    with open(path, "rb") as f:
        data = f.read()

    if data[:4] == b"glTF":  # .glb binary container
        gltf, bin_chunk = _parse_glb(data)
        buffers = [bin_chunk]
    else:  # .gltf JSON
        gltf = json.loads(data)
        base = os.path.dirname(path)
        buffers = [_load_gltf_buffer(b, base) for b in gltf.get("buffers", [])]

    accessors = gltf.get("accessors", [])
    views = gltf.get("bufferViews", [])
    meshes = gltf.get("meshes", [])

    def read_accessor(idx: int) -> list[tuple]:
        acc = accessors[idx]
        view = views[acc["bufferView"]]
        buf = buffers[view.get("buffer", 0)]
        fmt_char, comp_size = _GLTF_COMPONENT[acc["componentType"]]
        ncomp = _GLTF_TYPE_COUNT[acc["type"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or (comp_size * ncomp)
        fmt = "<" + fmt_char * ncomp
        return [struct.unpack_from(fmt, buf, start + i * stride) for i in range(acc["count"])]

    def read_mesh(mesh_index: int):
        verts: list[Vec3] = []
        normals: list[Vec3] = []
        tris: list[tuple[int, int, int]] = []
        have_normals = True
        for prim in meshes[mesh_index].get("primitives", []):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            base_index = len(verts)
            positions = read_accessor(attrs["POSITION"])
            verts.extend((p[0], p[1], p[2]) for p in positions)
            if "NORMAL" in attrs:
                normals.extend((n[0], n[1], n[2]) for n in read_accessor(attrs["NORMAL"]))
            else:
                have_normals = False
            if "indices" in prim:
                flat = [v[0] for v in read_accessor(prim["indices"])]
            else:
                flat = list(range(len(positions)))  # non-indexed
            for k in range(0, len(flat) - 2, 3):
                tris.append((base_index + flat[k], base_index + flat[k + 1], base_index + flat[k + 2]))
        return verts, normals, tris, have_normals

    out_v: list[Vec3] = []
    out_n: list[Vec3] = []
    out_t: list[tuple[int, int, int]] = []
    state = {"have_normals": True}  # closure-writable flag

    def emit(mesh_index: int, world: list[float]) -> None:
        verts, normals, tris, have_normals = read_mesh(mesh_index)
        base = len(out_v)
        out_v.extend(_mat_point(world, v) for v in verts)
        if have_normals and len(normals) == len(verts):
            out_n.extend(_normalized(_mat_dir(world, n)) for n in normals)
        else:
            state["have_normals"] = False
            out_n.extend((0.0, 0.0, 1.0) for _ in verts)
        out_t.extend((base + a, base + b, base + c) for a, b, c in tris)

    nodes = gltf.get("nodes")
    if nodes:
        def node_local(node: dict) -> list[float]:
            if "matrix" in node:
                return list(node["matrix"])
            return _mat_trs(node.get("translation", (0.0, 0.0, 0.0)),
                            node.get("rotation", (0.0, 0.0, 0.0, 1.0)),
                            node.get("scale", (1.0, 1.0, 1.0)))

        def walk(index: int, parent: list[float]) -> None:
            node = nodes[index]
            world = _mat_mul(parent, node_local(node))
            if "mesh" in node:
                emit(node["mesh"], world)
            for child in node.get("children", ()):
                walk(child, world)

        if "scenes" in gltf and gltf["scenes"]:
            roots = gltf["scenes"][gltf.get("scene", 0)].get("nodes", [])
        else:  # no scene: roots are nodes that aren't anyone's child
            children = {c for n in nodes for c in n.get("children", ())}
            roots = [i for i in range(len(nodes)) if i not in children]
        for root in roots:
            walk(root, _MAT_IDENTITY)
    else:
        for mesh_index in range(len(meshes)):
            emit(mesh_index, _MAT_IDENTITY)

    if not out_v or not out_t:
        raise ValueError(f"{path}: no mesh geometry found")
    return _build(out_v, out_t, out_n if state["have_normals"] else None)


# --- 4x4 matrices, column-major like glTF -------------------------------------

_MAT_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _mat_mul(a: list[float], b: list[float]) -> list[float]:
    r = [0.0] * 16
    for col in range(4):
        for row in range(4):
            r[col * 4 + row] = (
                a[row] * b[col * 4]
                + a[4 + row] * b[col * 4 + 1]
                + a[8 + row] * b[col * 4 + 2]
                + a[12 + row] * b[col * 4 + 3]
            )
    return r


def _mat_trs(t, q, s) -> list[float]:
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    sx, sy, sz = s
    return [
        (1 - 2 * (yy + zz)) * sx, (2 * (xy + wz)) * sx, (2 * (xz - wy)) * sx, 0.0,
        (2 * (xy - wz)) * sy, (1 - 2 * (xx + zz)) * sy, (2 * (yz + wx)) * sy, 0.0,
        (2 * (xz + wy)) * sz, (2 * (yz - wx)) * sz, (1 - 2 * (xx + yy)) * sz, 0.0,
        t[0], t[1], t[2], 1.0,
    ]


def _mat_point(m: list[float], p: Vec3) -> Vec3:
    px, py, pz = p
    return (
        m[0] * px + m[4] * py + m[8] * pz + m[12],
        m[1] * px + m[5] * py + m[9] * pz + m[13],
        m[2] * px + m[6] * py + m[10] * pz + m[14],
    )


def _mat_dir(m: list[float], v: Vec3) -> Vec3:
    vx, vy, vz = v
    return (
        m[0] * vx + m[4] * vy + m[8] * vz,
        m[1] * vx + m[5] * vy + m[9] * vz,
        m[2] * vx + m[6] * vy + m[10] * vz,
    )


def _parse_glb(data: bytes) -> tuple[dict, bytes]:
    json_bytes: bytes | None = None
    bin_chunk = b""
    offset = 12  # skip 12-byte header (magic, version, length)
    while offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type == 0x4E4F534A:  # "JSON"
            json_bytes = chunk
        elif chunk_type == 0x004E4942:  # "BIN\0"
            bin_chunk = chunk
    if json_bytes is None:
        raise ValueError("glb: no JSON chunk")
    return json.loads(json_bytes), bin_chunk


def _load_gltf_buffer(buf: dict, base_dir: str) -> bytes:
    uri = buf.get("uri")
    if uri is None:
        return b""
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    with open(os.path.join(base_dir, uri), "rb") as f:
        return f.read()


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
