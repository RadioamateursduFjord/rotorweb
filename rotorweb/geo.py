# -*- coding: utf-8 -*-
"""RotorWeb — calculs géographiques (Maidenhead, cap, distance)."""
import math
import re

GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2}([0-9]{2})?)?$")


def valid_grid(grid):
    return bool(grid) and bool(GRID_RE.match(str(grid).strip().upper()))


def grid_to_latlon(grid):
    g = grid.strip().upper()
    if not GRID_RE.match(g):
        raise ValueError(f"Grid invalide : {grid}")
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    w, h = 2.0, 1.0
    if len(g) >= 6:
        lon += (ord(g[4]) - 65) * 2 / 24
        lat += (ord(g[5]) - 65) * 1 / 24
        w, h = 2 / 24, 1 / 24
    if len(g) == 8:
        lon += int(g[6]) * 2 / 240
        lat += int(g[7]) * 1 / 240
        w, h = 2 / 240, 1 / 240
    return lat + h / 2, lon + w / 2


def bearing_distance(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    brg = (math.degrees(math.atan2(y, x)) + 360) % 360
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    dist = 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))
    return brg, dist


def grid_bearing(from_grid, to_grid, path="short"):
    la1, lo1 = grid_to_latlon(from_grid)
    la2, lo2 = grid_to_latlon(to_grid)
    b, d = bearing_distance(la1, lo1, la2, lo2)
    if path == "long":
        b, d = (b + 180) % 360, 40030.0 - d
    return b, d


def latlon_to_grid(lat, lon):
    """Latitude/longitude → grid à 6 caractères."""
    lon = max(-180.0, min(179.9999, float(lon))) + 180
    lat = max(-90.0, min(89.9999, float(lat))) + 90
    a = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    b = str(int((lon % 20) // 2)) + str(int(lat % 10))
    c = chr(97 + int((lon % 2) * 12)) + chr(97 + int((lat % 1) * 24))
    return (a + b + c).upper()[:4] + c


def angdiff(a, b):
    """Écart angulaire absolu (0–180°), 365° et 5° sont considérés égaux."""
    return abs(((float(a) - float(b)) + 540) % 360 - 180)
