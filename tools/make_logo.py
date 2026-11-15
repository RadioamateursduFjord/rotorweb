#!/usr/bin/env python3
"""Génère les fichiers du logo RotorWeb (« Azimut », logo B).

Sorties :
  logo/          fichiers sources pour le dépôt GitHub (SVG + PNG, sombre/clair)
  rotorweb/static/  icônes de l'application (favicon, PWA, Apple)

Usage : python3 tools/make_logo.py [--font chemin/space-grotesk-700.woff]
Nécessite rsvg-convert (paquet librsvg2-bin) et fontTools pour le mot-symbole.
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DARK = {"b": "#58a6ff", "g": "#3fb950", "bg": "#0e1319", "text": "#e6edf3"}
LIGHT = {"b": "#1f6feb", "g": "#1a7f37", "bg": "#ffffff", "text": "#1f2328"}

FULL = """<path d="M50 50 L66.9 13.75 A40 40 0 0 1 86.25 33.1 Z" fill="{g}" fill-opacity=".28"/>
<circle cx="50" cy="50" r="40" fill="none" stroke="{b}" stroke-width="4"/>
<path d="M50 10V18M90 50H82M50 90V82M10 50H18" stroke="{b}" stroke-width="4" stroke-linecap="round"/>
<path d="M70 15.36L68 18.82M84.64 30L81.18 32M84.64 70L81.18 68M70 84.64L68 81.18M30 84.64L32 81.18M15.36 70L18.82 68M15.36 30L18.82 32M30 15.36L32 18.82" stroke="{b}" stroke-width="2.5" stroke-linecap="round" stroke-opacity=".7"/>
<g transform="rotate(-45 50 50)"><path d="M50 50H84M56 39V61M64 41V59M72 43V57M80 45V55" stroke="{b}" stroke-width="4.5" stroke-linecap="round" fill="none"/>
<path d="M84 50 L78 45 M84 50 L78 55" stroke="{g}" stroke-width="4.5" stroke-linecap="round" fill="none"/></g>
<circle cx="50" cy="50" r="5.5" fill="{g}"/>"""

SIMPLE = """<path d="M50 50 L66.9 13.75 A40 40 0 0 1 86.25 33.1 Z" fill="{g}" fill-opacity=".35"/>
<circle cx="50" cy="50" r="40" fill="none" stroke="{b}" stroke-width="7"/>
<g transform="rotate(-45 50 50)"><path d="M50 50H84M62 38V62M76 42V58" stroke="{b}" stroke-width="7" stroke-linecap="round" fill="none"/></g>
<circle cx="50" cy="50" r="7" fill="{g}"/>"""


def symbol(c, simple=False):
    return (SIMPLE if simple else FULL).format(**c)


def svg_symbol(c, simple=False, bg=None, scale=1.0, radius=0):
    """Symbole seul, viewBox 100x100. bg = couleur de fond (carré arrondi), scale = taille du symbole."""
    inner = symbol(c, simple)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">']
    if bg:
        out.append(f'<rect width="100" height="100" rx="{radius}" fill="{bg}"/>')
    if scale != 1.0:
        off = 50 * (1 - scale)
        inner = f'<g transform="translate({off:.2f} {off:.2f}) scale({scale})">{inner}</g>'
    out.append(inner)
    out.append("</svg>")
    return "\n".join(out)


def wordmark_paths(font_path):
    """Retourne (largeur, hauteur_cap, chemins 'Rotor', chemins 'Web') en unités de police."""
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    f = TTFont(font_path)
    gs, cmap = f.getGlyphSet(), f.getBestCmap()
    hmtx = f["hmtx"]
    asc = f["OS/2"].sCapHeight or f["hhea"].ascent
    x = 0
    parts = {"Rotor": "", "Web": ""}
    for word in ("Rotor", "Web"):
        for ch in word:
            gname = cmap[ord(ch)]
            pen = SVGPathPen(gs)
            # y vers le bas : on retourne le glyphe
            gs[gname].draw(TransformPen(pen, (1, 0, 0, -1, x, asc)))
            parts[word] += pen.getCommands()
            x += hmtx[gname][0]
    return x, asc, parts["Rotor"], parts["Web"]


def svg_horizontal(c, wm, with_bg=False, with_symbol=True):
    width_u, cap_u, rotor, web = wm
    h = 100.0
    cap = 46.0                    # hauteur des capitales dans le logo
    k = cap / cap_u
    tw = width_u * k
    x0 = 122 if with_symbol else 2
    total = x0 + tw + 6
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.1f} {h:.0f}">']
    if with_bg:
        out.append(f'<rect width="100%" height="100%" fill="{c["bg"]}"/>')
    if with_symbol:
        out.append(symbol(c))
    ty = (h - cap) / 2
    out.append(f'<g transform="translate({x0} {ty:.2f}) scale({k:.5f})">'
               f'<path d="{rotor}" fill="{c["b"]}"/><path d="{web}" fill="{c["g"]}"/></g>')
    out.append("</svg>")
    return "\n".join(out)


def raster(svg_text, path, size, height=None):
    tmp = path + ".tmp.svg"
    with open(tmp, "w") as f:
        f.write(svg_text)
    cmd = ["rsvg-convert", "-w", str(size)]
    if height:
        cmd += ["-h", str(height)]
    subprocess.run(cmd + ["-o", path, tmp], check=True)
    os.remove(tmp)


def write(path, text):
    with open(path, "w") as f:
        f.write(text + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", help="Space Grotesk Bold (.woff/.ttf) pour le mot-symbole")
    a = ap.parse_args()
    logo = os.path.join(ROOT, "logo")
    static = os.path.join(ROOT, "rotorweb", "static")
    os.makedirs(logo, exist_ok=True)

    # --- dossier logo/ (dépôt GitHub) ---
    for name, c in (("sombre", DARK), ("clair", LIGHT)):
        s = svg_symbol(c)
        write(f"{logo}/rotorweb-symbole-{name}.svg", s)
        raster(s, f"{logo}/rotorweb-symbole-{name}-1024.png", 1024)
        write(f"{logo}/rotorweb-symbole-simplifie-{name}.svg", svg_symbol(c, simple=True))
    icon = svg_symbol(DARK, bg=DARK["bg"], scale=0.78, radius=22)
    write(f"{logo}/rotorweb-icone.svg", icon)
    raster(icon, f"{logo}/rotorweb-icone-1024.png", 1024)
    if a.font:
        wm = wordmark_paths(a.font)
        for name, c in (("sombre", DARK), ("clair", LIGHT)):
            h = svg_horizontal(c, wm)
            write(f"{logo}/rotorweb-horizontal-{name}.svg", h)
            raster(h, f"{logo}/rotorweb-horizontal-{name}-1200.png", 1200)
        write(f"{static}/logo-horizontal.svg", svg_horizontal(DARK, wm))
        write(f"{static}/wordmark.svg", svg_horizontal(DARK, wm, with_symbol=False))
        for name, c in (("sombre", DARK), ("clair", LIGHT)):
            write(f"{logo}/rotorweb-motsymbole-{name}.svg", svg_horizontal(c, wm, with_symbol=False))
    else:
        print("(mot-symbole ignoré : --font absent)", file=sys.stderr)

    # --- icônes de l'application ---
    write(f"{static}/logo.svg", svg_symbol(DARK))
    write(f"{static}/favicon.svg", svg_symbol(DARK, simple=True, bg=DARK["bg"], scale=0.86, radius=20))
    raster(svg_symbol(DARK, simple=True, bg=DARK["bg"], scale=0.86, radius=20), f"{static}/favicon.png", 32)
    any_icon = svg_symbol(DARK, bg=DARK["bg"], scale=0.78, radius=0)        # le système arrondit lui-même
    mask_icon = svg_symbol(DARK, bg=DARK["bg"], scale=0.62, radius=0)       # zone sûre Android (80 %)
    raster(any_icon, f"{static}/icon-192.png", 192)
    raster(any_icon, f"{static}/icon-512.png", 512)
    raster(mask_icon, f"{static}/icon-maskable-192.png", 192)
    raster(mask_icon, f"{static}/icon-maskable-512.png", 512)
    raster(svg_symbol(DARK, bg=DARK["bg"], scale=0.74, radius=0), f"{static}/apple-touch-icon.png", 180)
    print("Logo généré :", logo, "et", static)


if __name__ == "__main__":
    main()
