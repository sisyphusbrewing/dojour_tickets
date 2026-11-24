"""Portable deck stand v5 (Nov 23 2026): replaces Elgato's stand, with the Pi and batteries behind it.

Run: python3 stand.py [--straight-cable] [--preview DIR]
  -> deck-stand-base.stl, deck-stand-plate.stl, deck-stand-plate-emblem.stl
  (needs trimesh, manifold3d, shapely, opencv-python-headless, pillow)

Sam, Nov 23 2026: "we have more options if we take the stand off and design around that",
"we need to do the Sisyphus Logo somewhere" and "make sure to consider supports and ideal
printing arrangement".

How the deck is really held (from Sam's photos, Nov 23 2026): Elgato's stand is a flat plate. Two
M3 x 8 screws go straight UP through its front edge into two brass threaded holes in round bosses
at the deck's bottom (knob) end. Sam's calipers: the screws are 83.01 mm apart, the deck is
140.20 mm wide. Nothing holds the deck's back; it stands up from those two seats.

So this base copies that: two round seats at the front, the same two screws from underneath.
The seats stand alone and nothing else comes near the deck, so the fit depends only on the
83.01 mm spacing. The seats are 7 mm tall (Elgato's are about 5), so the deck's rubber feet end up
a millimetre or two off the table instead of pressing on it.

Behind the seats is the Pi's place. The clear acrylic plate from the Waveshare kit comes off and
this floor takes its place: the same four screws go up into the same four brass standoffs (the
Pi's published hole pattern, 58 x 49 mm). The Pi hangs upside down under the battery board, the
way Sam built it, with the batteries on top. The sides are open: USB ports on the right, SD card
on the left, batteries out the top.

The deck's USB-C port is on its back, in the middle, about 2 cm from the top (Sam). A straight
plug there points at the batteries, so the Pi sits just behind the reach of a right-angle plug.
--straight-cable moves the Pi 30 mm further back for a straight plug.

Printing (Bambu P2S, 0.4 mm nozzle): everything prints flat, as exported, with no supports. The
logo is the hop-and-barrel mark from the official badge, with no lettering (at this size the
outlined letters are thinner than the nozzle can draw, and the wording is changing). It sits on
its own back plate that prints lying down with the mark on top, so the printer changes colour
once. On an upright wall it would change colour twice on every layer, a few hundred times.
The plate slides down into the two slotted posts at the back, and lifts out to reach the Pi's
HDMI.
Units mm. X = left to right facing the deck, Y = front to back, Z up. Y = 0 is the base's front.
"""
import math
import sys

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon, box as sbox
from shapely.ops import unary_union
from trimesh.creation import cylinder, extrude_polygon

LOGO = "/mnt/project-files/logo/official/sisyphus-badge-bluegray.png"
STRAIGHT = "--straight-cable" in sys.argv

W = 140.2                          # deck width (Sam's calipers)
SCREW_SPAN = 83.01                 # between the two stand screws (Sam's calipers)
SEAT_Y = 6.0                       # screw line, from the base's front edge
SEAT_H = 7.0                       # seat top above the table
SEAT_D = 8.5                       # a little smaller than the deck's ~9.5 mm bosses
UNDER_HEAD = 3.6                   # plastic between screw head and deck: an M3 x 8 bites 4.4 mm
FLOOR = 4.0
FRONT_T = 3.2                      # thinner strip at the front, under the deck's lower bevel
WALL = 3.0

# Pi + UPS HAT (B) as Sam built it: 20 mm standoffs, Pi upside down, 10 mm, HAT, batteries on top
PI_L, PI_WID = 85.0, 56.0
PI_X0 = 5.0                        # SD-card end (left); leaves 48 mm on the right for USB plugs
PI_Y0 = 78.0 + (30.0 if STRAIGHT else 0.0)   # Pi's front edge; power/HDMI edge and charge jack face back
HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]   # from the SD end / from the power edge
SCREW_D, HEAD_D, HEAD_H = 2.9, 5.8, 2.0
BOSS_D, BOSS_H = 8.0, 1.0
STANDOFF = 20.0

PLATE_T = 3.0                      # logo plate thickness
YP0 = PI_Y0 + PI_WID + 5.5         # plate's front face (the HAT's jacks poke ~4 mm past the board)
YP1 = YP0 + PLATE_T
D = YP1 + 2.5                      # overall depth
POST = 8.0                         # slotted corner posts
PLATE_TOP = 26.0                   # the HAT's charge jack and switch sit above this
SILL = 1.2
RIM_H = 12.0


def prism_yz(pts, x0, x1):
    """Extrude a Y/Z outline along X."""
    m = extrude_polygon(Polygon(pts), x1 - x0)
    m.apply_transform([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    return m


def prism_xy(poly, z0, z1):
    m = extrude_polygon(poly, z1 - z0)
    m.apply_translation((0, 0, z0))
    return m


def blk(x0, x1, y0, y1, z0, z1, r=0.0):
    p = sbox(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, resolution=12) if r else sbox(x0, y0, x1, y1)
    return prism_xy(p, z0, z1)


def cyl(x, y, d, z0, z1, n=64):
    c = cylinder(radius=d / 2, height=z1 - z0, sections=n)
    c.apply_translation((x, y, (z0 + z1) / 2))
    return c


def U(*m):
    return trimesh.boolean.union(list(m), engine="manifold")


def S(a, *m):
    return trimesh.boolean.difference([a] + list(m), engine="manifold")


def pi_xy(px, py):
    return PI_X0 + px, PI_Y0 + PI_WID - py


SEATS = (W / 2 - SCREW_SPAN / 2, W / 2 + SCREW_SPAN / 2)


def build_base():
    outline = sbox(5, 5, W - 5, D - 5).buffer(5, resolution=16)
    parts = [prism_xy(outline, 0, FRONT_T),
             prism_xy(outline.intersection(sbox(-1, 12, W + 1, YP0 - 0.2)), 0, FLOOR)]
    for sx in SEATS:
        parts += [cyl(sx, SEAT_Y, 12.0, 0, 5.0), cyl(sx, SEAT_Y, SEAT_D, 0, SEAT_H)]
        # stiffening rib behind each seat, kept low so it stays well under the deck's back
        rib = [(9.5, 0), (9.5, SEAT_H), (36, 15.5), (42, 15.5), (66, 0)]
        parts.append(prism_yz(rib, sx - 1.6, sx + 1.6))
    # low side rims with a sloped start
    rim = [(20, 0), (20, FLOOR), (34, RIM_H), (YP0 - 2.5, RIM_H), (YP0 - 2.5, 0)]
    parts += [prism_yz(rim, 0, WALL), prism_yz(rim, W - WALL, W)]
    # slotted corner posts for the logo plate, on a thin sill
    parts.append(prism_xy(outline.intersection(sbox(-1, YP0 - 2.5, W + 1, D + 1)), 0, SILL))
    for x0, x1 in ((0, POST), (W - POST, W)):
        parts.append(prism_xy(outline.intersection(sbox(x0, YP0 - 2.5, x1, D + 1)), 0, PLATE_TOP))
    parts += [cyl(*pi_xy(px, py), BOSS_D, 0, FLOOR + BOSS_H) for px, py in HOLES]
    body = U(*parts)

    cuts = []
    for sx in SEATS:
        cuts.append(cyl(sx, SEAT_Y, 3.5, -1, 20))                               # M3 clearance
        cuts.append(cyl(sx, SEAT_Y, 6.4, -1, SEAT_H - UNDER_HEAD))              # screw head, from below
    for px, py in HOLES:
        x, y = pi_xy(px, py)
        cuts.append(cyl(x, y, SCREW_D, -1, 20))
        cuts.append(cyl(x, y, HEAD_D, -1, HEAD_H))
    for x0, x1 in ((POST - 3.0, POST + 0.1), (W - POST - 0.1, W - POST + 3.0)):  # the slots
        cuts.append(blk(x0, x1, YP0 - 0.2, YP1 + 0.2, SILL, 99))
    for bx, by in ((12, 7), (W - 12, 7), (16, YP0 - 12), (W - 16, YP0 - 12)):   # stick-on bumpers
        cuts.append(cyl(bx, by, 10.4, -1, 1.0))
    return S(body, *cuts)


def build_plate():
    """Logo plate, in its place on the base (use to_print() to lay it down)."""
    plate = blk(POST - 3.0 + 0.3, W - POST + 3.0 - 0.3, YP0, YP1, SILL, PLATE_TOP)
    notch = blk(-1, 27, YP0 - 1, YP1 + 1, 17.0, 99)                             # see the Pi's two lights
    return S(plate, notch)


def emblem(width=52.0, raise_=0.8):
    """Hop-and-barrel mark traced from the official badge file, on the plate's back face."""
    import cv2
    from PIL import Image
    im = np.array(Image.open(LOGO).convert("RGBA").crop((230, 60, 700, 290))).astype(int)
    r, g, b, a = (im[..., i] for i in range(4))
    blue = (a > 128) & (b - r > 40)
    gray = (a > 128) & (abs(b - r) < 25) & (r < 215)
    keep = np.zeros(blue.shape, bool)
    keep[:, 150:310] = blue[:, 150:310]                                  # the barrel
    keep[75:200, 15:140] |= gray[75:200, 15:140]                         # left hops
    keep[75:200, 328:450] |= gray[75:200, 328:450]                       # right hops
    big = cv2.resize(keep.astype(np.uint8) * 255, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    cs, hier = cv2.findContours((big > 127).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_L1)
    outers = [Polygon(c[:, 0, :]).buffer(0) for c, h in zip(cs, hier[0]) if h[3] < 0 and len(c) > 3]
    holes = [Polygon(c[:, 0, :]).buffer(0) for c, h in zip(cs, hier[0]) if h[3] >= 0 and len(c) > 3]
    shape = unary_union(outers).difference(unary_union(holes)) if holes else unary_union(outers)
    x0, y0, x1, y1 = shape.bounds
    k = width / (x1 - x0)
    shape = affinity.scale(affinity.translate(shape, -(x0 + x1) / 2, -y1), k, -k, origin=(0, 0))
    shape = shape.simplify(0.03)
    polys = [p for p in getattr(shape, "geoms", [shape]) if p.area > 0.3]
    m = trimesh.util.concatenate([extrude_polygon(p, raise_) for p in polys])
    h = (y1 - y0) * k
    z0 = SILL + (PLATE_TOP - SILL - h) / 2
    # stand it on the plate's back face: local x -> -X (reads right from behind), y -> Z, height -> +Y
    m.apply_transform([[-1, 0, 0, W / 2 + 8], [0, 0, 1, YP1], [0, 1, 0, z0], [0, 0, 0, 1]])
    return m, polys


def thinnest(polys):
    """Narrowest stroke and narrowest gap in the mark, mm (checked against the 0.4 mm nozzle)."""
    allp = unary_union(polys)
    stroke = next((round(float(t), 2) for t in np.arange(0.2, 4, 0.05)
                   if allp.buffer(-t / 2).area < 0.02 * allp.area), 4.0)
    gap = next((round(float(t), 2) for t in np.arange(0.2, 4, 0.05)
                if len(getattr(allp.buffer(t / 2), "geoms", [1])) < len(polys)), 4.0)
    return stroke, gap


def to_print(m):
    """Lay the plate (or its mark) down flat, back face up, the way it prints."""
    m = m.copy()
    m.apply_transform([[-1, 0, 0, W], [0, 0, 1, -SILL], [0, 1, 0, -YP0], [0, 0, 0, 1]])
    return m


def preview_parts():
    """Stand-ins for the deck, its plug and the Pi stack, for the picture only (estimated shapes)."""
    y0 = SEAT_Y
    prof = [(-28, 3), (-14, 3), (10.5, 14.4), (79, 87.7), (55.6, 109.5), (-36.5, 10.9)]
    deck = prism_yz([(y + y0, z) for y, z in prof], 0, W)
    a = math.radians(47)
    py, pz = 65 + y0, 73.0                                                     # USB-C port on the back
    n = (math.sin(a), -math.cos(a))
    reach = 38 if STRAIGHT else 11
    plug = prism_yz([(py - 3 * n[1], pz + 3 * n[0]), (py + 3 * n[1], pz - 3 * n[0]),
                     (py + 3 * n[1] + reach * n[0], pz - 3 * n[0] + reach * n[1]),
                     (py - 3 * n[1] + reach * n[0], pz + 3 * n[0] + reach * n[1])], W / 2 - 6, W / 2 + 6)
    bz = FLOOR + BOSS_H + STANDOFF
    x0, yb, x1, y1 = PI_X0, PI_Y0, PI_X0 + PI_L, PI_Y0 + PI_WID
    posts = [cyl(*pi_xy(px, py_), 4.5, FLOOR + BOSS_H, bz + 11.4) for px, py_ in HOLES]
    pi = [blk(x0, x1, yb, y1, bz, bz + 1.4, 3), blk(x1 - 21, x1 + 2, yb + 2, y1 - 2, bz - 16, bz)] + posts
    hat = [blk(x0, x1, yb, y1, bz + 11.4, bz + 13, 3), blk(x0 + 6, x0 + 56, y1 - 6, y1 + 4, bz + 3, bz + 11.4)]
    cells = [blk(x0 + 4, x1 - 4, yb + 7, y1 - 7, bz + 13, bz + 34.8, 1)]
    return {"deck": [deck], "plug": [plug], "pi": pi, "hat": hat, "cells": cells}


if __name__ == "__main__":
    base, plate = build_base(), build_plate()
    emb, polys = emblem()
    base.export("deck-stand-base.stl")
    to_print(plate).export("deck-stand-plate.stl")
    to_print(emb).export("deck-stand-plate-emblem.stl")
    for name, m in (("base", base), ("plate", to_print(plate)), ("emblem", to_print(emb))):
        print(name, "watertight", m.is_watertight, "size", (m.bounds[1] - m.bounds[0]).round(1),
              "volume", round(m.volume / 1000, 1), "cm3")
    print("emblem thinnest stroke / gap, mm:", thinnest(polys))
    if "--preview" in sys.argv:
        out = sys.argv[sys.argv.index("--preview") + 1]
        base.export(f"{out}/holder.stl")
        plate.export(f"{out}/plate.stl")
        emb.export(f"{out}/emblem.stl")
        for name, ms in preview_parts().items():
            trimesh.util.concatenate(ms).export(f"{out}/{name}.stl")
