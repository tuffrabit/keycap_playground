#!/usr/bin/env python3
"""Cross-section a (binary or ASCII) STL at X=0 and test how straight the
front (-Y) and back (+Y) exterior silhouettes are.

Usage: python3 scripts/stl_profile.py file.stl --rot x,y,z [--ztop N]

--rot applies the inverse of an OpenSCAD rotate([x,y,z]) so the cap can be
measured in its local frame.  --ztop excludes the top N mm (dish region)
from the line fit.
"""
import sys
import math
from stl_check import read_stl, rot_mat, apply, transpose


def section_yz(tris, rot=None, eps=1e-4):
    """Intersect all triangles with the X=0 plane; return list of (y,z) points."""
    pts = []
    for n, v in tris:
        vv = [apply(rot, p) if rot else p for p in v]
        crossing = []
        # Vertices lying (nearly) on the plane count as section points too
        for a in vv:
            if abs(a[0]) < eps:
                crossing.append((a[1], a[2]))
        for i in range(3):
            a = vv[i]
            b = vv[(i + 1) % 3]
            if (a[0] < -eps) == (b[0] < -eps):
                continue
            t = a[0] / (a[0] - b[0])
            y = a[1] + t * (b[1] - a[1])
            z = a[2] + t * (b[2] - a[2])
            crossing.append((y, z))
        pts.extend(crossing)
    return pts


def silhouette(pts, zmin, zmax, bins=200, pick=min):
    """One extreme-y point per z bin -> sorted list of (z, y)."""
    width = (zmax - zmin) / bins
    cells = {}
    for y, z in pts:
        i = int((z - zmin) / width)
        if 0 <= i < bins:
            zc = zmin + (i + 0.5) * width
            if i not in cells:
                cells[i] = (zc, y)
            else:
                cells[i] = (cells[i][0], pick(cells[i][1], y))
    return sorted(cells.values())


def fit_line(points):
    """Least squares y = a + b*z; returns (a, b, max_abs_residual)."""
    n = len(points)
    sz = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    szz = sum(p[0] ** 2 for p in points)
    szy = sum(p[0] * p[1] for p in points)
    d = n * szz - sz * sz
    a = (sy * szz - sz * szy) / d
    b = (n * szy - sz * sy) / d
    res = max(abs(p[1] - (a + b * p[0])) for p in points)
    return a, b, res


def main():
    path = sys.argv[1]
    rot = None
    ztop = 0.0
    if "--rot" in sys.argv:
        x, y, z = (float(a) for a in sys.argv[sys.argv.index("--rot") + 1].split(","))
        rot = transpose(rot_mat(x, y, z))
    if "--ztop" in sys.argv:
        ztop = float(sys.argv[sys.argv.index("--ztop") + 1])

    pts = section_yz(read_stl(path), rot)
    zs = [p[1] for p in pts]
    zmin, zmax = min(zs), max(zs)
    front = silhouette(pts, zmin, zmax, pick=min)
    back = silhouette(pts, zmin, zmax, pick=max)

    for name, sil in (("front (-Y)", front), ("back  (+Y)", back)):
        use = [p for p in sil if p[0] < zmax - ztop]
        a, b, res = fit_line(use)
        angle = math.degrees(math.atan(abs(b)))
        print(f"{name}: {len(use):3d} slices, wall angle from vertical: "
              f"{angle:6.2f} deg, straightness max deviation: {res:.4f} mm")


if __name__ == "__main__":
    main()
