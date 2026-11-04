"""Pi pod v2: the Pi 3B+ + UPS HAT (B) box tucks in behind the Stream Deck +, under the tilted screen.

Run: python3 pod.py  -> deck-pod-base.stl, deck-pod-lid.stl (needs trimesh + manifold3d)

Deck profile, measured from Sam's tape-measure photos (Nov 4 2026) and scaled to Elgato's published
140 x 138 x 110 mm. Side view, Y = front to back from the deck's front-bottom edge, Z up (mm):
  footprint Y -20 .. 116, top of screen ~110 at Y ~85
  screen back (slab inner face): through V = (32, 25), rising at ~46.7 deg, ends at (84, 80)
  stand: a wedge on the table, top face from V down to (118, 8)
  deck USB-C cable comes out of the screen back around (67, 65): use a right-angle (down) USB-C plug

The pod sits on the table behind the deck. A wedge tunnel under its front swallows the stand's tail,
so pushing the deck in locks the two together. The Pi box behind is the v1 box (dock.py): HAT under
the Pi, charge jack/switch out the back, Ethernet out the left, SD card end on the right.
Units mm. X = width (left to right, facing the deck).
"""
import math

import trimesh

from dock import HOLES, blk, cyl, U, S

# ---- deck (measured) ----
VY, VZ = 32.0, 25.0
SLAB = math.radians(46.7)          # screen back angle from the table
STAND_END = 118.0
def stand_top(y):                  # stand top face height at Y
    return VZ - (y - VY) * (VZ - 8.0) / (STAND_END - VY)
def slab_y(z):                     # screen back Y at height Z
    return VY + (z - VZ) / math.tan(SLAB)

# ---- pod ----
T = 2.5
CLEAR = 4.0                        # gap to the screen back
W = 152.0                          # a little wider than the deck so the tunnel can take a full-width stand
TUN_W = 143.0                      # tunnel width (stand assumed up to 140 wide)
Y_FRONT = 60.0                     # tongue front: grips the last ~58 mm of the stand
FLOOR = 20.0                       # Pi compartment floor top
POST_H = 22.8
HAT_TOP = FLOOR + POST_H + 1.6
PI_BOTTOM = HAT_TOP + 10.0
STACK_TOP = PI_BOTTOM + 18.6       # top of the USB jacks
H = STACK_TOP + 3.5                # wall top
LID_T = 2.5
BOX_IN_D = 57.5


def chamfer_ok(y_in):
    """Is the top-front inside corner of the box at least CLEAR + T behind the screen back?"""
    z = H + LID_T
    d = (y_in - slab_y(z)) * math.sin(SLAB)
    return d >= CLEAR + T


Y_BI0 = 80.0
while not chamfer_ok(Y_BI0):
    Y_BI0 += 0.5
Y_BI1 = Y_BI0 + BOX_IN_D
D_END = Y_BI1 + T
PI_SD_X = W - T - 2.0
PI_POWER_EDGE_Y = Y_BI1 - 0.5


def P(px, py):
    return PI_SD_X - px, PI_POWER_EDGE_Y - py


def wedge_tunnel():
    """Stand-tail tunnel: open at the front, follows the stand top + 2 mm."""
    y0, y1 = Y_FRONT - 1, STAND_END + 4
    pts = [(y0, -1), (y1, -1), (y1, stand_top(STAND_END) + 3), (y0, stand_top(y0) + 2)]
    return prism_yz(pts, (W - TUN_W) / 2, (W + TUN_W) / 2)


def prism_yz(pts, x0, x1):
    """Extrude a Y/Z polygon along X."""
    from shapely.geometry import Polygon
    m = trimesh.creation.extrude_polygon(Polygon(pts), x1 - x0)
    # extrude_polygon builds in XY and extrudes along Z: map (u,v,w) -> (x0 + w, u, v)
    m.apply_transform([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    return m


def screen_cut():
    """Everything in front of the plane CLEAR mm behind the screen back (keeps the pod off the screen)."""
    big = 400
    z0, z1 = -50, 300
    pts = [(slab_y(z0) + CLEAR / math.sin(SLAB), z0), (slab_y(z1) + CLEAR / math.sin(SLAB), z1), (-big, z1), (-big, z0)]
    return prism_yz(pts, -10, W + 10)


# body: tongue + box
tongue_top = stand_top(Y_FRONT) + 2 + 3.0
parts = [blk(0, W, Y_FRONT, Y_BI0, 0, tongue_top + 0),                 # tongue (over the stand tail)
         blk(0, W, Y_BI0 - T, D_END, 0, FLOOR),                         # solid under the Pi floor
         blk(0, W, Y_BI0 - T, Y_BI0, FLOOR, H),                         # front wall
         blk(0, W, Y_BI1, D_END, FLOOR, H),                             # back wall
         blk(0, T, Y_BI0, Y_BI1, FLOOR, H),                             # left wall
         blk(W - T, W, Y_BI0, Y_BI1, FLOOR, H)]                         # right wall
for px, py in HOLES:
    x, y = P(px, py)
    parts.append(cyl(x, y, 4.0, FLOOR, FLOOR + POST_H))
parts.append(blk(PI_SD_X - 89.0, PI_SD_X - 86.0, Y_BI0 + 12, Y_BI1 - 12, FLOOR, FLOOR + 18))  # stops the stack sliding left
base = U(*parts)

cuts = [wedge_tunnel(), screen_cut()]
for px, py in HOLES:
    x, y = P(px, py)
    cuts.append(cyl(x, y, 3.1, FLOOR + POST_H - 4.0, FLOOR + POST_H + 0.1))
x61, _ = P(56, 0)
x11, _ = P(6, 0)
cuts.append(blk(x61, x11, Y_BI1 - 0.1, D_END + 0.1, HAT_TOP - 4, H + 0.1))        # back: charge jack, switch, Pi micro-USB
cuts.append(blk(W - T - 0.1, W + 0.1, *sorted((P(0, 6)[1], P(0, 38)[1])), HAT_TOP - 5, PI_BOTTOM + 2))  # right: SD card
ey = P(0, 10.25)[1]
cuts.append(blk(-0.1, T + 0.1, ey - 10, ey + 10, PI_BOTTOM + 0.5, PI_BOTTOM + 17.5))      # left: Ethernet
cuts.append(blk(8, 48, Y_BI0 - T - 0.1, Y_BI0 + 0.1, FLOOR + 6, H + 0.1))                 # front: deck cable drops in
# lighten the solid block under the floor (behind the tunnel) and save filament
cuts.append(blk(T, W - T, STAND_END + 4 + T, D_END - T, -0.1, FLOOR - T))
for fx, fy in [(12, Y_FRONT + 10), (W - 12, Y_FRONT + 10), (12, D_END - 10), (W - 12, D_END - 10)]:
    cuts.append(cyl(fx, fy, 6.0, -0.1, 1.0))                                              # bumper recesses
base = S(base, *cuts)

# lid
CL = 0.3
lid = blk(0, W, Y_BI0 - T, D_END, H, H + LID_T)
rim = S(blk(T + CL, W - T - CL, Y_BI0 + CL, Y_BI1 - CL, H - 4, H),
        blk(T + CL + 1.6, W - T - CL - 1.6, Y_BI0 + CL + 1.6, Y_BI1 - CL - 1.6, H - 4.1, H + 0.1))
tab = blk(x61 + CL, x11 - CL, Y_BI1 + CL, D_END, PI_BOTTOM + 5, H)
ftab = blk(8 + CL, 48 - CL, Y_BI0 - T, Y_BI0 - CL, H - 6, H)            # closes the top of the cable notch
rib = blk(PI_SD_X - 72, PI_SD_X - 70, Y_BI0 + 6, Y_BI1 - 6, STACK_TOP + 1, H)
lid = U(lid, rim, tab, ftab, rib)
vents = [blk(PI_SD_X - 12 - i * 9, PI_SD_X - 8 - i * 9, Y_BI0 + 12, Y_BI1 - 12, H - 0.1, H + LID_T + 0.1) for i in range(6)]
lid = S(lid, *vents, screen_cut())

if __name__ == "__main__":
    base.export("deck-pod-base.stl")
    flip = lid.copy()
    flip.apply_transform(trimesh.transformations.rotation_matrix(math.pi, (1, 0, 0)))
    flip.apply_translation(-flip.bounds[0])
    flip.export("deck-pod-lid.stl")
    for n, m in (("base", base), ("lid", flip)):
        print(n, m.is_watertight, (m.bounds[1] - m.bounds[0]).round(1), round(m.volume / 1000, 1), "cm3")
    print("box inside front Y", Y_BI0, "pod back Y", D_END, "past deck back by", round(D_END - STAND_END, 1))
