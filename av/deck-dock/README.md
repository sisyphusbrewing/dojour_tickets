# Portable deck dock

Stream Deck + sits in the front cradle; the Pi 3B+ and Waveshare UPS HAT (B) live in the box behind it.
`python3 dock.py` regenerates `deck-dock-base.stl` and `deck-dock-lid.stl` (trimesh + manifold3d).

Fit was checked against Waveshare's own 3D model of the HAT (no overlaps). The deck size is the
published 140 x 138 x 110 mm, so the cradle is generous (145 x 142); tighten `CRADLE_W/D` once measured.

Print: no supports, PETG or PLA, 3 walls, 20% infill. Base 151 x 208.5 x 60 mm; lid prints flat side down as exported.

Assembly: HAT goes under the Pi on the kit standoffs, screw heads drop into the four post nests,
charge jack and switch face out the back window, SD card end on the right, USB/Ethernet on the left.
Deck cable: a short USB-C to USB-A (0.3 m, right angle is nicest) drops into the notch in the front wall.
Cat6 plugs in through the left wall. Four 12 mm stick-on bumpers go in the bottom recesses.
