"""Draw the toolbar icons for the UTP panel.

    python tools/make_icons.py

Drawn here rather than kept as binary in the repository, so a change is a
change to this file and anyone can see what the picture is meant to be.

Everything below was measured off Fusion's own icons rather than guessed at,
after two attempts that looked wrong on the toolbar. The reference is
NeuCAM/UI/NeuCAMUI/Resources/Icons/StrategyAdaptive2D in the Fusion install.

**Fusion picks a file per theme and per display, by name.** A folder holds
16x16.png and 16x16-dark.png, and an @2x of each for HiDPI, for every size. So:

    16x16.png  16x16@2x.png  16x16-dark.png  16x16-dark@2x.png   (and 32, 64)

The first attempt shipped only 16x16/32x32/64x64. On a HiDPI screen Fusion had
no @2x to use and scaled a 16-pixel bitmap up, which is exactly the "lower
resolution than Fusion's own" that was reported. And with no -dark file it used
the light one on both themes, which is why the first set was drawn to carry a
light element and a dark one at once -- a compromise invented for a problem
Fusion had already solved.

**They fill the frame.** Every Fusion icon's alpha runs the full width and
height: (0, 0, 16, 16). Mine sat in a 3/32 margin, so they read as small and
inset beside Fusion's.

**And the palette is pale, not saturated.** Fusion's icons are near-white faces
and mid greys with one light blue accent; the only dark ink is a thin outline,
and on the dark theme even that goes light. A saturated blue body looks like a
stranger in the toolbar, which was the last of the three complaints.

Everything is drawn at eight times size and reduced with LANCZOS. Drawing
straight at the target size gives hard stair-steps.

The forms are plain on purpose: at sixteen pixels a drawing of a tool is four
grey pixels. What survives is a strong silhouette and one accent of colour.
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "addin", "UTP", "utp", "resources")

# Drawn this many times larger, then reduced. The whole of the quality.
OVER = 8

# Fusion's own, sampled from StrategyAdaptive2D/32x32.png. Both of its variants
# use these same colours; the dark one simply has no dark ink in it.
FACE = (243, 243, 243, 255)      # the near-white body everything is built from
BLUE = (103, 177, 230, 255)      # the one accent
BLUE_DEEP = (62, 134, 190, 255)  # the shaded side of it
GREY = (196, 196, 196, 255)
GREY_DEEP = (150, 150, 150, 255)
GREEN = (106, 184, 110, 255)
RED = (214, 106, 96, 255)

# The only thing that differs between the two files: the outline. Dark ink on
# the light theme, light ink on the dark one.
INK = {"light": (102, 102, 102, 255), "dark": (217, 217, 217, 255)}

# Every size Fusion looks for, and the pixel size each file is drawn at. The
# @2x is twice its name, which is the whole point of it.
WANTED = [("16x16", 16), ("16x16@2x", 32),
          ("32x32", 32), ("32x32@2x", 64),
          ("64x64", 64), ("64x64@2x", 128)]


def _canvas(pixels):
    """A canvas and a unit. One unit is 1/32 of the icon, whatever its size."""
    image = Image.new("RGBA", (pixels * OVER, pixels * OVER), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), float(pixels * OVER) / 32.0


def _done(image, pixels):
    return image.resize((pixels, pixels), Image.LANCZOS)


def _w(u, weight=1.5):
    """A stroke width that never rounds down to nothing at the small sizes."""
    return max(1, int(round(weight * u)))


def _plate(draw, u, ink, box, spine=BLUE, face=FACE):
    """A preset, as a card seen flat: a pale face with a coloured spine.

    The shape most of these are built from, so the set reads as a set.
    """
    x, y, right, bottom = [v * u for v in box]
    radius = 2.4 * u
    draw.rounded_rectangle([x, y, right, bottom], radius=radius, fill=face)
    draw.rounded_rectangle([x, y, x + 6.5 * u, bottom], radius=radius,
                           fill=spine)
    draw.rectangle([x + 4 * u, y, x + 6.5 * u, bottom], fill=spine)
    draw.line([(x + 6.5 * u, y), (x + 6.5 * u, bottom)], fill=ink, width=_w(u))
    draw.rounded_rectangle([x, y, right, bottom], radius=radius, outline=ink,
                           width=_w(u))


def _rows(draw, u, x, y, width, rows, gap=4.6, colour=GREY_DEEP):
    for row in range(rows):
        top = (y + row * gap) * u
        draw.line([(x * u, top), ((x + width) * u, top)], fill=colour,
                  width=_w(u, 1.7))


def _badge(draw, u, ink, box, fill):
    """A disc in the corner, which is how Fusion hangs a verb off a noun."""
    draw.ellipse([v * u for v in box], fill=fill, outline=ink, width=_w(u, 1.3))


def update_presets(pixels, theme):
    """A preset with an arrow on it: there is something newer to pick up."""
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    _plate(draw, u, ink, (0.8, 1.0, 22.0, 24.0))
    _rows(draw, u, 9.5, 7.5, 9.5, rows=3)
    _badge(draw, u, ink, (15.5, 15.5, 31.2, 31.2), GREEN)
    # An arrow, drawn as one polygon so the head and the stem cannot drift
    # apart at sixteen pixels.
    cx, white = 23.35 * u, (255, 255, 255, 255)
    draw.polygon([(cx, 18.4 * u), (cx + 4.6 * u, 23.2 * u),
                  (cx + 1.9 * u, 23.2 * u), (cx + 1.9 * u, 28.4 * u),
                  (cx - 1.9 * u, 28.4 * u), (cx - 1.9 * u, 23.2 * u),
                  (cx - 4.6 * u, 23.2 * u)], fill=white)
    return _done(image, pixels)


def check_only(pixels, theme):
    """The same preset under a magnifier: looks, writes nothing."""
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    _plate(draw, u, ink, (0.8, 1.0, 22.0, 24.0))
    _rows(draw, u, 9.5, 7.5, 9.5, rows=3)
    draw.line([(25.0 * u, 25.0 * u), (30.8 * u, 30.8 * u)], fill=BLUE_DEEP,
              width=_w(u, 3.6))
    draw.line([(25.0 * u, 25.0 * u), (30.8 * u, 30.8 * u)], fill=ink,
              width=_w(u, 1.2))
    _badge(draw, u, ink, (14.0, 14.0, 27.4, 27.4), FACE)
    _badge(draw, u, ink, (16.4, 16.4, 25.0, 25.0), BLUE)
    return _done(image, pixels)


def remove_marks(pixels, theme):
    """The preset with a cross on it: the notes come off."""
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    _plate(draw, u, ink, (0.8, 1.0, 22.0, 24.0), spine=GREY)
    _rows(draw, u, 9.5, 8.5, 9.5, rows=2, colour=GREY)
    _badge(draw, u, ink, (15.5, 15.5, 31.2, 31.2), RED)
    white = (255, 255, 255, 255)
    for a, b in (((19.6, 19.6), (27.1, 27.1)), ((27.1, 19.6), (19.6, 27.1))):
        draw.line([(a[0] * u, a[1] * u), (b[0] * u, b[1] * u)], fill=white,
                  width=_w(u, 2.6))
    return _done(image, pixels)


def switches(pixels, theme):
    """Two toggles, one on and one off."""
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    for row, (on, colour) in enumerate(((True, BLUE), (False, GREY))):
        y = (1.1 + row * 16.4) * u
        high = y + 14.4 * u
        draw.rounded_rectangle([0.9 * u, y, 31.1 * u, high], radius=6.5 * u,
                               fill=colour, outline=ink, width=_w(u, 1.4))
        cx = 24.4 * u if on else 7.6 * u
        draw.ellipse([cx - 6.0 * u, y + 0.6 * u, cx + 6.0 * u, high - 0.6 * u],
                     fill=FACE, outline=ink, width=_w(u, 1.4))
    return _done(image, pixels)


def folder(pixels, theme):
    """A folder, for the reports."""
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    draw.polygon([(0.9 * u, 1.2 * u), (12.5 * u, 1.2 * u), (16.0 * u, 5.4 * u),
                  (31.1 * u, 5.4 * u), (31.1 * u, 26.0 * u),
                  (0.9 * u, 26.0 * u)], fill=BLUE_DEEP, outline=ink,
                 width=_w(u, 1.3))
    draw.polygon([(0.9 * u, 9.0 * u), (31.1 * u, 9.0 * u),
                  (31.1 * u, 31.1 * u), (0.9 * u, 31.1 * u)], fill=BLUE,
                 outline=ink, width=_w(u, 1.3))
    return _done(image, pixels)


def report(pixels, theme):
    """A page with a turned corner."""
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    outline = [(1.6, 0.9), (22.0, 0.9), (30.4, 9.3), (30.4, 31.1),
               (1.6, 31.1)]
    draw.polygon([(a * u, b * u) for a, b in outline], fill=FACE)
    draw.rectangle([1.6 * u, 0.9 * u, 6.8 * u, 31.1 * u], fill=BLUE)
    draw.polygon([(22.0 * u, 0.9 * u), (30.4 * u, 9.3 * u),
                  (22.0 * u, 9.3 * u)], fill=BLUE_DEEP)
    draw.polygon([(a * u, b * u) for a, b in outline], outline=ink,
                 width=_w(u, 1.3))
    draw.line([(22.0 * u, 0.9 * u), (22.0 * u, 9.3 * u), (30.4 * u, 9.3 * u)],
              fill=ink, width=_w(u, 1.3))
    _rows(draw, u, 10.0, 14.0, 16.5, rows=4, gap=4.8)
    return _done(image, pixels)


def instructions(pixels, theme):
    """An i in a disc.

    A question mark was the first choice and it was not legible at sixteen
    pixels: the curve, the stem and the dot came out as one blob that read as
    an exclamation. An i is two strokes and survives the reduction.
    """
    image, draw, u = _canvas(pixels)
    ink = INK[theme]
    draw.ellipse([0.9 * u, 0.9 * u, 31.1 * u, 31.1 * u], fill=BLUE,
                 outline=ink, width=_w(u, 1.5))
    draw.ellipse([13.3 * u, 6.2 * u, 18.7 * u, 11.6 * u], fill=FACE)
    draw.rounded_rectangle([13.5 * u, 13.8 * u, 18.5 * u, 25.8 * u],
                           radius=1.6 * u, fill=FACE)
    return _done(image, pixels)


ICONS = {
    "update-presets": update_presets,
    "check-only": check_only,
    "remove-marks": remove_marks,
    "switches": switches,
    "folder": folder,
    "report": report,
    "instructions": instructions,
}


def main():
    written = 0
    for name, draw_it in ICONS.items():
        where = os.path.join(OUT, name)
        os.makedirs(where, exist_ok=True)
        # Anything left from an older set goes, or a renamed file lingers and
        # Fusion keeps picking it.
        for stale in os.listdir(where):
            if stale.endswith(".png"):
                os.remove(os.path.join(where, stale))
        for label, pixels in WANTED:
            for theme in ("light", "dark"):
                # "16x16@2x" with -dark becomes "16x16-dark@2x": the suffix
                # goes before the @2x, which is how Fusion names them.
                tag = label if theme == "light" else label.replace(
                    "@2x", "-dark@2x") if "@2x" in label else label + "-dark"
                draw_it(pixels, theme).save(
                    os.path.join(where, "%s.png" % tag))
                written += 1
    print("%d files for %d icons in %s" % (written, len(ICONS), OUT))


if __name__ == "__main__":
    main()
