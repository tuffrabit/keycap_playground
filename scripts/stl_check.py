#!/usr/bin/env python3
"""Analyze a binary STL: bounding box and planarity of dominant faces.

Usage: python3 scripts/stl_check.py file.stl [--rot x,y,z]

--rot applies the inverse of an OpenSCAD rotate([x,y,z]) (Rz*Ry*Rx) to all
vertices first, so a keycap rendered with KEY_ROTATION can be measured in
cap-local coordinates.
"""
import sys
import struct
import math


def read_stl(path):
    with open(path, "rb") as f:
        data = f.read()
    # Binary STL: 80 byte header, 4 byte count, 50 bytes per triangle
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if 84 + count * 50 == len(data):
            tris = []
            off = 84
            for _ in range(count):
                vals = struct.unpack_from("<12fH", data, off)
                n = vals[0:3]
                v = [vals[3:6], vals[6:9], vals[9:12]]
                tris.append((n, v))
                off += 50
            return tris
    # ASCII STL
    text = data.decode("utf-8", "replace")
    tris = []
    normal = (0.0, 0.0, 0.0)
    verts = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "facet":
            normal = tuple(float(a) for a in parts[2:5])
        elif parts[0] == "vertex":
            verts.append(tuple(float(a) for a in parts[1:4]))
        elif parts[0] == "endfacet":
            if len(verts) == 3:
                tris.append((normal, verts))
            verts = []
    if tris:
        return tris
    raise SystemExit("Not a binary STL or unsupported format: " + path)


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def rot_mat(x, y, z):
    """OpenSCAD rotate([x,y,z]) == Rz(z) @ Ry(y) @ Rx(x), degrees."""
    rx, ry, rz = (math.radians(a) for a in (x, y, z))
    cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                              math.sin(ry), math.cos(rz), math.sin(rz))
    Rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    Rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    return mat_mul(Rz, mat_mul(Ry, Rx))


def apply(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def transpose(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


def main():
    path = sys.argv[1]
    tris = read_stl(path)
    rot = None
    if "--rot" in sys.argv:
        x, y, z = (float(a) for a in sys.argv[sys.argv.index("--rot") + 1].split(","))
        rot = transpose(rot_mat(x, y, z))  # inverse of the forward rotation

    verts = []
    out_tris = []
    for n, v in tris:
        vv = [apply(rot, p) if rot else p for p in v]
        nn = apply(rot, n) if rot else n
        out_tris.append((nn, vv))
        verts.extend(vv)

    xs, ys, zs = zip(*verts)
    print(f"triangles: {len(tris)}")
    print(f"bbox X: {min(xs):8.3f} .. {max(xs):8.3f}  ({max(xs)-min(xs):.3f})")
    print(f"bbox Y: {min(ys):8.3f} .. {max(ys):8.3f}  ({max(ys)-min(ys):.3f})")
    print(f"bbox Z: {min(zs):8.3f} .. {max(zs):8.3f}  ({max(zs)-min(zs):.3f})")

    # Planarity check: group triangles by dominant outward direction and fit a
    # plane through each group's vertices (plane from first tri, max deviation).
    groups = {"-Y (front)": [], "+Y (back)": [], "-X (left)": [], "+X (right)": []}
    for n, vv in out_tris:
        nx, ny, nz = n
        ax, ay, az = abs(nx), abs(ny), abs(nz)
        if ay >= ax and ay >= az and ay > 0.85:
            groups["-Y (front)" if ny < 0 else "+Y (back)"].append(vv)
        elif ax >= ay and ax >= az and ax > 0.85:
            groups["-X (left)" if nx < 0 else "+X (right)"].append(vv)

    for name, g in groups.items():
        if not g:
            print(f"{name}: no triangles")
            continue
        pts = [p for tri in g for p in tri]
        # Reference plane from the centroid and average normal
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cz = sum(p[2] for p in pts) / len(pts)
        # Normal via Newell average
        anx = any_ = anz = 0.0
        for tri in g:
            (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = tri
            ux, uy, uz = x2 - x1, y2 - y1, z2 - z1
            vx, vy, vz = x3 - x1, y3 - y1, z3 - z1
            anx += uy * vz - uz * vy
            any_ += uz * vx - ux * vz
            anz += ux * vy - uy * vx
        ln = math.sqrt(anx**2 + any_**2 + anz**2)
        anx, any_, anz = anx / ln, any_ / ln, anz / ln
        devs = [abs((p[0]-cx)*anx + (p[1]-cy)*any_ + (p[2]-cz)*anz) for p in pts]
        print(f"{name}: {len(g):5d} tris, plane-fit max deviation: {max(devs):.4f} mm")


if __name__ == "__main__":
    main()
