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

## v5: the print is the stand (stand.py, Nov 23 2026)

Sam, Nov 23 2026: "we have more options if we take the stand off and design around that", and
"we need to do the Sisyphus Logo somewhere". This replaces v1 and v2 above, which were never printed.

`python3 stand.py` -> `deck-stand-base.stl` (140.2 x 145 x 26 mm), `deck-stand-plate.stl` and
`deck-stand-plate-emblem.stl` (the logo plate and its raised mark, lying flat).

How the deck is held, from Sam's photos and calipers: Elgato's stand is a flat plate, 114 mm front to
back. Two M3 x 8 screws, 83.01 mm apart, go straight up through its front edge into two brass threaded
holes at the deck's bottom end, and about 5 mm of thread sticks out of the stand. The base copies that:
two round seats at the front, the same two screws from underneath, the same 5 mm bite.

Putting it together:
1. Deck: set its two round screw bosses on the two seats and put Elgato's two screws in from underneath.
   The deck's rubber feet end up about a millimetre off the table; that is on purpose.
2. Pi: take the clear acrylic plate off the Waveshare kit. Stand the four brass standoffs on the four
   pads and put the same four screws in from underneath. USB ports to the right (facing the keys), SD
   card to the left, charge jack to the back, batteries on top.
3. Logo plate: slide it down into the two posts at the back, mark facing out, notch on the SD-card side.
   It lifts out to reach the Pi's HDMI port.
4. Cable: a short (about 1 ft) USB-A to USB-C data cable with a right-angle USB-C end. A straight plug
   in the deck's back points at the batteries (Sam picked the right-angle cable, Nov 23 2026).

Printing: everything prints flat as exported, no supports, no brim on the SuperTack plate. The logo is
on its own plate so the colour changes on four layers only. The ready-to-print Bambu Studio project is
built on Sam's Mac by Bambu Studio's own command line (`~/Downloads/Sisyphus deck stand/build/build.sh`,
which re-reads his current printer and filament presets); it is not kept in this repo.
