"""Ceiling hanger tab for the 64x32 LED stage clock (Adafruit 2278 panel,
255 x 127 x 13 mm (Sam measured 13), M3 threaded holes on the back). Print two.

Each tab screws into one of the panel's top two holes with an M3 x 10 screw
and a washer, and has a lug above the panel for an S-hook or cable loop.
The lug sits behind the panel, so the clock hangs face-down toward the stage
by about TILT degrees. Run:  python3 hanger.py  -> hanger-tilt15.stl, hanger-flat.stl
Units: mm. z up (panel top edge at z=0), y toward the back (panel back at y=0).
"""
import math

import trimesh
from trimesh.creation import box, cylinder

W = 22.0          # tab width
PLATE = 5.0       # plate thickness against the panel back
SLOT = (-42.0, -8.0)  # slot reach below the panel top: fits holes 8-42 mm down
SCREW = 3.4       # M3 clearance
LUG_HOLE = 6.0    # S-hook / cable loop
PANEL_COM = (-4.0, -63.0)  # (y, z) of panel + board centre of mass, roughly


def block(x0, x1, y0, y1, z0, z1):
    b = box(extents=(x1 - x0, y1 - y0, z1 - z0))
    b.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return b


def hanger(lug_y):
    x0, x1 = -W / 2, W / 2
    parts = [
        block(x0, x1, 0, PLATE, SLOT[0] - 6, 8),             # plate on the panel back, up past the top edge
        block(x0, x1, min(0, lug_y - 8), max(PLATE, lug_y + 8), 8, 16),  # arm across, above the top edge
        block(x0, x1, lug_y - 8, lug_y + 8, 8, 30),           # lug
    ]
    solid = trimesh.boolean.union(parts, engine="manifold")
    slot_len = SLOT[1] - SLOT[0]
    cut = [block(-SCREW / 2, SCREW / 2, -1, PLATE + 1, SLOT[0], SLOT[1])]
    for z in SLOT:  # round the slot ends
        c = cylinder(radius=SCREW / 2, height=PLATE + 2, sections=32)
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0)))
        c.apply_translation((0, PLATE / 2, z))
        cut.append(c)
    hole = cylinder(radius=LUG_HOLE / 2, height=W + 2, sections=48)
    hole.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (0, 1, 0)))
    hole.apply_translation((0, lug_y, 23))
    cut.append(hole)
    solid = trimesh.boolean.difference([solid] + cut, engine="manifold")
    tilt = math.degrees(math.atan2(lug_y - PANEL_COM[0], 23 - PANEL_COM[1]))
    return solid, tilt


if __name__ == "__main__":
    for name, lug_y in (("hanger-tilt15", 18.0), ("hanger-flat", PANEL_COM[0])):
        solid, tilt = hanger(lug_y)
        # lay it on its side for printing: the profile flat on the bed
        solid.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (0, 1, 0)))
        solid.apply_translation(-solid.bounds[0])
        solid.export(f"{name}.stl")
        print(name, "tilt %.0f deg" % tilt, "size", solid.extents.round(1), "watertight", solid.is_watertight)
