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

## v2: pod behind the screen (pod.py, Nov 4 2026)

Sam's pick: the Pi tucks in behind the deck, under the tilted screen, instead of the v1 tray.
`python3 pod.py` -> `deck-pod-base.stl` (152 x 92 x 76.5 mm) + `deck-pod-lid.stl`. Deck profile was
measured from Sam's photos (scaled to Elgato's 140 x 138 x 110). The stand's tail slides into a
wedge tunnel under the pod's front, so the two lock together; the pod keeps 4 mm off the screen back
and sticks out about 34 mm behind the deck. Use a right-angle (down) USB-C cable from the deck;
it drops into the notch at the front-left of the box.
