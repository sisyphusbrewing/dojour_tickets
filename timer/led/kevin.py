# Kevin, 24x32 pixels: long hair, beard, robe, and an empty mug he would
# like refilled. Pure data so code.py (CircuitPython) and the preview script
# (desktop Python) can share it.

PALETTE = {
    ".": 0x000000,
    "H": 0x6A3D14,  # hair
    "S": 0xC8825A,  # skin
    "B": 0x4A2A10,  # beard
    "M": 0x200000,  # open mouth
    "E": 0x000000,  # eyes
    "R": 0x6E6450,  # robe
    "r": 0x3A3428,  # robe stripe
    "G": 0x9AB4C8,  # glass
    "F": 0xDDDDDD,  # last bit of foam
}

HEAD = [
    ".......HHHHHHH..........",
    ".....HHHHHHHHHHH........",
    "....HHHHHHHHHHHHH.......",
    "....HHHSSSSSSSHHH.......",
    "...HHHSSSSSSSSSHHH......",
    "...HHSSSSSSSSSSSHH......",
    "...HHSSEESSSEESSHH......",
    "...HHSSSSSSSSSSSHH......",
    "...HHSSSSSSSSSSSHH......",
    "...HHSBSSSSSSSBSHH......",
    "...HHHBBSSSSSBBHHH......",
    "...HHHBBBBBBBBBHHH......",
    "....HHHBBBBBBBHHH.......",
    "....HHH.BBBBB.HHH.......",
    "....HH...SSS...HH.......",
]

BODY = [
    "...RRRRRSSSSSRRRRR......",
    "..RRRRRRSSSSSRRRRRR.....",
    ".RRRRRRRRSSSRRRRRRRR....",
    ".RRrRRRRRRSRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRrrrRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
    ".RRrRRRRRRRRRRRRRrRR....",
]

# Right arm and mug, drawn over the picture: (row, col, rows of pixels).
MUG_LOW = (19, 16, [
    "...GGGGG",
    "..SGF..GG",
    "RRSG...G.G",
    "RRSG...G.G",
    "RRSG...GG",
    "...GGGGG",
])
MUG_UP = (6, 17, [
    "GGGGG..",
    "GF..GG.",
    "G...G.G",
    "G...G.G",
    "G...GG.",
    "GGGGG..",
    ".SS....",
    ".RR....",
    ".RR....",
    ".RR....",
    "RR.....",
    "RR.....",
    "R......",
])
MUG_TILT = (5, 16, [
    "..GGGGG",
    ".GF...G",
    "GG....G",
    "G.G...G",
    "GG.GGG.",
    ".....SS",
    ".....RR",
    "....RR.",
    "...RR..",
    "..RR...",
    "..RR...",
    ".R.....",
])

MOUTH_OPEN = (10, 9, ["MMM"])
EYES_BLINK = (6, 7, ["SS...SS"])


def frame(mug, talking=False, blink=False):
    rows = [list(r) for r in HEAD + BODY]
    layers = [mug]
    if talking:
        layers.append(MOUTH_OPEN)
    if blink:
        layers.append(EYES_BLINK)
    for top, left, art in layers:
        for dy, line in enumerate(art):
            for dx, ch in enumerate(line):
                y, x = top + dy, left + dx
                if ch != "." and 0 <= y < 32 and 0 <= x < 24:
                    rows[y][x] = ch
    return ["".join(r) for r in rows]


# The show: (picture, words on the right, seconds).
WHITE, AMBER = 0xB4B4B4, 0xE09000
SCRIPT = [
    (frame(MUG_LOW), ("", ""), 1.2),
    (frame(MUG_LOW, blink=True), ("", ""), 0.15),
    (frame(MUG_LOW), ("", ""), 0.8),
    (frame(MUG_LOW, talking=True), ("HEY", "MAN"), 0.4),
    (frame(MUG_LOW), ("HEY", "MAN"), 0.4),
    (frame(MUG_LOW, talking=True), ("HEY", "MAN"), 0.6),
    (frame(MUG_UP), ("", ""), 0.5),
    (frame(MUG_TILT), ("", ""), 0.5),
    (frame(MUG_UP), ("", ""), 0.4),
    (frame(MUG_TILT), ("", ""), 0.4),
    (frame(MUG_UP, talking=True), ("ONE", "MORE"), 0.4),
    (frame(MUG_UP), ("ONE", "MORE"), 0.4),
    (frame(MUG_UP, talking=True), ("BEER?", ""), 0.5),
    (frame(MUG_UP), ("BEER?", ""), 1.2),
    (frame(MUG_LOW), ("", ""), 0.6),
    (frame(MUG_LOW, talking=True), ("KEVIN", "ABIDES"), 0.4),
    (frame(MUG_LOW), ("KEVIN", "ABIDES"), 2.0),
]
