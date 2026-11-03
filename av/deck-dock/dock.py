"""Portable deck dock: Stream Deck + cradle in front, Pi 3B+ + Waveshare UPS HAT (B) box behind.

Run: python3 dock.py  -> deck-dock-base.stl, deck-dock-lid.stl (needs trimesh + manifold3d)
Units mm. X = width (left to right, facing the deck), Y = front to back, Z up. Floor bottom at Z=0.

Stack, from the Waveshare 3D drawing (ups_hat_b__asm.stp): the UPS HAT (B) sits UNDER the Pi.
Its 2x18650 holder hangs 23.4 mm below the HAT board top; the Pi rides 10 mm above the HAT on the
kit standoffs (pogo pins touch the Pi's GPIO pins from below). Mounting holes = Pi pattern
(3.5 / 61.5 x 3.5 / 52.5). The HAT's three connectors (8.4 V charge jack etc.) poke ~4 mm past the
Pi's power/HDMI edge, which faces the back of the dock.

Stream Deck + with its stand: 140 x 138 x 110 mm (published). Cradle is 145 x 142 inside so it fits
either way round; tighten CRADLE_* once measured.
"""
import trimesh
from trimesh.creation import box, cylinder

T = 3.0                    # wall / floor
CRADLE_W, CRADLE_D = 145.0, 142.0
LIP_H = 10.0               # cradle lip height above floor
W = CRADLE_W + 2 * T       # 151
Y_SHARED = T + CRADLE_D    # front face of the wall between deck and Pi box
BOX_IN_D = 57.5            # Pi box inside depth (board is 56)
Y_BI0 = Y_SHARED + T       # Pi box inside, front
Y_BI1 = Y_BI0 + BOX_IN_D   # Pi box inside, back
D = Y_BI1 + T              # overall depth
H = 60.0                   # box wall top
F = T                      # floor top

# Pi / HAT placement. px along the Pi's 85 mm side (0 = SD card end), py across (0 = power/HDMI edge).
PI_SD_X = W - T - 2.0       # Pi SD-card end (right side). Power edge faces back, so the USB/Ethernet end is on the left.
PI_POWER_EDGE_Y = Y_BI1 - 0.5
POST_H = 22.8              # floor to HAT underside (batteries clear the floor by ~1 mm)
HAT_TOP = F + POST_H + 1.6
PI_BOTTOM = HAT_TOP + 10.0


def P(px, py):
    return PI_SD_X - px, PI_POWER_EDGE_Y - py


def blk(x0, x1, y0, y1, z0, z1):
    b = box(extents=(x1 - x0, y1 - y0, z1 - z0))
    b.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return b


def cyl(x, y, r, z0, z1, n=48):
    c = cylinder(radius=r, height=z1 - z0, sections=n)
    c.apply_translation((x, y, (z0 + z1) / 2))
    return c


def U(*m):
    return trimesh.boolean.union(list(m), engine="manifold")


def S(a, *m):
    return trimesh.boolean.difference([a] + list(m), engine="manifold")


HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]

# ---------- base ----------
parts = [blk(0, W, 0, D, 0, F)]                                   # floor
parts += [blk(0, T, 0, Y_SHARED, F, F + LIP_H),                  # cradle side lips
          blk(W - T, W, 0, Y_SHARED, F, F + LIP_H),
          blk(0, 30, 0, T, F, F + LIP_H),                        # front corner lips
          blk(W - 30, W, 0, T, F, F + LIP_H)]
parts += [blk(0, W, Y_SHARED, Y_BI0, F, H),                       # deck-side wall
          blk(0, W, Y_BI1, D, F, H),                              # back wall
          blk(0, T, Y_BI0, Y_BI1, F, H),                          # left wall
          blk(W - T, W, Y_BI0, Y_BI1, F, H)]                      # right wall
for px, py in HOLES:                                              # HAT posts
    x, y = P(px, py)
    parts.append(cyl(x, y, 4.0, F, F + POST_H))
# fence that stops the stack sliding toward the USB end
parts.append(blk(PI_SD_X - 89.0, PI_SD_X - 86.0, Y_BI0 + 12, Y_BI1 - 12, F, F + 18))
base = U(*parts)

cuts = []
for px, py in HOLES:                                              # nests for the kit screw heads
    x, y = P(px, py)
    cuts.append(cyl(x, y, 3.1, F + POST_H - 4.0, F + POST_H + 0.1))
x61, _ = P(56, 0)
x11, _ = P(6, 0)
cuts.append(blk(x61, x11, Y_BI1 - 0.1, D + 0.1, HAT_TOP - 4, H + 0.1))   # back: charge jack/switch + Pi micro-USB
cuts.append(blk(W - T - 0.1, W + 0.1, *sorted((P(0, 6)[1], P(0, 38)[1])), HAT_TOP - 5, PI_BOTTOM + 2))  # right: HAT side part + SD card
ey = P(0, 10.25)[1]
cuts.append(blk(-0.1, T + 0.1, ey - 10, ey + 10, PI_BOTTOM + 0.5, PI_BOTTOM + 17.5))      # left: Ethernet plug passes
cuts.append(blk(36, 48, Y_SHARED - 0.1, Y_BI0 + 0.1, H - 18, H + 0.1))                          # deck USB cable drop-in notch
for fx, fy in [(15, 15), (W - 15, 15), (15, D - 15), (W - 15, D - 15)]:                           # stick-on bumper recesses
    cuts.append(cyl(fx, fy, 6.0, -0.1, 1.0))
base = S(base, *cuts)

# ---------- lid (modelled in place, then flipped for printing) ----------
LID_T = 2.5
CL = 0.3
lid = blk(0, W, Y_SHARED, D, H, H + LID_T)
rim_o = blk(T + CL, W - T - CL, Y_BI0 + CL, Y_BI1 - CL, H - 5, H)
rim_i = blk(T + CL + 1.6, W - T - CL - 1.6, Y_BI0 + CL + 1.6, Y_BI1 - CL - 1.6, H - 5.1, H + 0.1)
rim = S(rim_o, rim_i)
tab = blk(x61 + CL, x11 - CL, Y_BI1 + CL, D, PI_BOTTOM + 5, H)   # plugs the top of the back notch
rib = blk(PI_SD_X - 72, PI_SD_X - 70, Y_BI0 + 6, Y_BI1 - 6, PI_BOTTOM + 18.5, H)  # keeps the stack from lifting
lid = U(lid, rim, tab, rib)
vents = [blk(PI_SD_X - 12 - i * 9, PI_SD_X - 8 - i * 9, Y_BI0 + 12, Y_BI1 - 12, H - 0.1, H + LID_T + 0.1) for i in range(6)]
lid = S(lid, *vents)

if __name__ == "__main__":
    base.export("deck-dock-base.stl")
    flip = lid.copy()
    flip.apply_transform(trimesh.transformations.rotation_matrix(3.14159265, (1, 0, 0)))
    flip.apply_translation(-flip.bounds[0])
    flip.export("deck-dock-lid.stl")
    for n, m in (("base", base), ("lid", flip)):
        print(n, m.is_watertight, m.bounds[1] - m.bounds[0], round(m.volume / 1000, 1), "cm3")
