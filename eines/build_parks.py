"""Preprocess OSM exports (playgrounds + trees + buildings) into SolParc park data
with a geometric shade profile per month and half-hour slot."""
import json, math, re, sys
import numpy as np
from matplotlib.path import Path
from scipy.spatial import ConvexHull

UP = "/root/.claude/uploads/7dac4db1-9824-52c9-b73e-f5eae3439f95/"
ZONES = {"a8f51d89-nord.geojson": "Nord", "a576d1c3-export-sud.geojson": "Sud", "d644dd4e-export.sudoest-geojson.geojson": "Sud-oest"}
FILES = ["a8f51d89-nord.geojson", "a576d1c3-export-sud.geojson", "d644dd4e-export.sudoest-geojson.geojson"]
LAT0, LON0 = 39.47, -0.37
KX = math.cos(LAT0 * math.pi / 180) * 111320.0
KY = 110574.0
SLOT0, NSLOT, STEP = 4.0, 35, 0.5          # UTC hours 04:00 .. 21:00
MIN_ALT = 2.0
MAX_SHADOW = 90.0                          # m (export only has obstacles ~70 m around parks)


def xy(lon, lat):
    return ((lon - LON0) * KX, (lat - LAT0) * KY)


def to_ll(x, y):
    return (LON0 + x / KX, LAT0 + y / KY)


# ---------- solar position (NOAA) ----------
def sun_pos(year, month, day, hour_utc, lat, lon):
    import datetime as dt
    d = dt.datetime(year, month, day) + dt.timedelta(hours=hour_utc)
    jd = (d - dt.datetime(2000, 1, 1, 12)).total_seconds() / 86400.0 + 2451545.0
    T = (jd - 2451545.0) / 36525.0
    L0 = (280.46646 + T * (36000.76983 + 0.0003032 * T)) % 360
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    Mr = math.radians(M)
    C = (math.sin(Mr) * (1.914602 - T * (0.004817 + 0.000014 * T)) + math.sin(2 * Mr) * (0.019993 - 0.000101 * T)
         + math.sin(3 * Mr) * 0.000289)
    true_long = L0 + C
    omega = 125.04 - 1934.136 * T
    lam = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam)))
    y = math.tan(math.radians(eps / 2)) ** 2
    L0r = math.radians(L0)
    eqt = 4 * math.degrees(y * math.sin(2 * L0r) - 2 * e * math.sin(Mr) + 4 * e * y * math.sin(Mr) * math.cos(2 * L0r)
                           - 0.5 * y * y * math.sin(4 * L0r) - 1.25 * e * e * math.sin(2 * Mr))
    tst = (hour_utc * 60 + eqt + 4 * lon) % 1440
    ha = tst / 4 - 180
    latr = math.radians(lat)
    cz = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(math.radians(ha))
    zen = math.acos(max(-1, min(1, cz)))
    alt = 90 - math.degrees(zen)
    az = math.degrees(math.atan2(math.sin(math.radians(ha)),
                                 math.cos(math.radians(ha)) * math.sin(latr) - math.tan(decl) * math.cos(latr))) + 180
    return alt, az % 360   # az: degrees clockwise from north


SUN = {}
for m in range(1, 13):
    for k in range(NSLOT):
        SUN[(m, k)] = sun_pos(2026, m, 15, SLOT0 + k * STEP, LAT0, LON0)


# ---------- load ----------
def rings_of(g):
    if g["type"] == "Polygon":
        return [g["coordinates"][0]]
    if g["type"] == "MultiPolygon":
        return [p[0] for p in g["coordinates"]]
    return []


parks, trees, buildings, named, streets = {}, [], [], [], []
seen_tree, seen_bld = set(), set()


def num(v):
    try:
        return float(re.sub(r"[^0-9.]", "", str(v).replace(",", ".")))
    except Exception:
        return None


def bld_height(p):
    h = num(p.get("height")) if p.get("height") else None
    if h and 2 < h < 200:
        return h
    lv = num(p.get("building:levels")) if p.get("building:levels") else None
    if lv and 0 < lv < 60:
        return lv * 3.1 + 1.0
    return {"apartments": 18, "residential": 15, "house": 7, "detached": 7, "terrace": 10, "roof": 3.5,
            "school": 10, "industrial": 8, "retail": 6, "warehouse": 8, "garage": 3, "shed": 3,
            "kiosk": 3}.get(p.get("building"), 9)


for fn in FILES:
    for f in json.load(open(UP + fn))["features"]:
        p, g = f["properties"], f["geometry"]
        oid = p.get("@id")
        if p.get("leisure") == "playground":
            if oid in parks:
                continue
            if p.get("access") in ("private", "customers", "no") or p.get("indoor") in ("yes", "room"):
                continue
            parks[oid] = (p, g, ZONES[fn])
        elif p.get("natural") == "tree" and g["type"] == "Point":
            if oid in seen_tree:
                continue
            seen_tree.add(oid)
            x, y = xy(*g["coordinates"])
            h = num(p.get("height")) if p.get("height") else None
            h = h if h and 2 < h < 40 else 8.0
            dc = num(p.get("diameter_crown")) if p.get("diameter_crown") else None
            dc = dc if dc and 1 < dc < 30 else 6.0
            cyc = p.get("leaf_cycle") or ("deciduous" if p.get("leaf_type") == "broadleaved" and False else "")
            trees.append((x, y, h, dc / 2, cyc))
            if p.get("name"):
                named.append((x, y, p["name"]))
        elif "building" in p and g["type"] in ("Polygon", "MultiPolygon"):
            if oid in seen_bld:
                continue
            seen_bld.add(oid)
            for ring in rings_of(g):
                pts = np.array([xy(*c) for c in ring])
                buildings.append((pts, bld_height(p), p.get("building") == "roof"))
                c = pts.mean(0)
                if p.get("addr:street"):
                    streets.append((c[0], c[1], p["addr:street"]))
                if p.get("name"):
                    named.append((c[0], c[1], p["name"]))
        else:
            if p.get("name") and g["type"] in ("Point", "Polygon", "MultiPolygon"):
                if g["type"] == "Point":
                    c = xy(*g["coordinates"])
                else:
                    c = np.array([xy(*q) for q in rings_of(g)[0]]).mean(0)
                named.append((c[0], c[1], p["name"]))

T = np.array([(t[0], t[1], t[2], t[3]) for t in trees])
TCYC = [t[4] for t in trees]
BB = np.array([(b[0][:, 0].min(), b[0][:, 1].min(), b[0][:, 0].max(), b[0][:, 1].max()) for b in buildings])
print("parks", len(parks), "trees", len(T), "buildings", len(buildings), file=sys.stderr)


def tree_opacity(cyc, m):
    if cyc == "deciduous":
        return {12: .3, 1: .3, 2: .3, 3: .4, 4: .6, 11: .5}.get(m, .8)
    if cyc == "evergreen":
        return .8
    return {12: .6, 1: .6, 2: .6, 3: .65}.get(m, .75)


def poly_area(pts):
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def sample_points(rings):
    allp = np.vstack(rings)
    x0, y0 = allp.min(0)
    x1, y1 = allp.max(0)
    area = sum(poly_area(r) for r in rings)
    s = min(8.0, max(1.5, math.sqrt(max(area, 1) / 70)))
    gx, gy = np.meshgrid(np.arange(x0 + s / 2, x1, s), np.arange(y0 + s / 2, y1, s))
    cand = np.c_[gx.ravel(), gy.ravel()]
    inside = np.zeros(len(cand), bool)
    for r in rings:
        inside |= Path(r).contains_points(cand)
    pts = cand[inside]
    if len(pts) < 5:
        pts = np.vstack([pts, allp.mean(0)[None, :], allp[:: max(1, len(allp) // 6)] * 0.7 + allp.mean(0) * 0.3])
    return pts, area


CH = "0123456789X"


def shade_profile(pts, bbox):
    x0, y0, x1, y1 = bbox
    R = MAX_SHADOW
    ti = np.where((T[:, 0] > x0 - 40) & (T[:, 0] < x1 + 40) & (T[:, 1] > y0 - 40) & (T[:, 1] < y1 + 40))[0]
    bi = np.where((BB[:, 2] > x0 - R) & (BB[:, 0] < x1 + R) & (BB[:, 3] > y0 - R) & (BB[:, 1] < y1 + R))[0]
    out = []
    for m in range(1, 13):
        op = np.array([tree_opacity(TCYC[i], m) for i in ti])
        row = []
        for k in range(NSLOT):
            alt, az = SUN[(m, k)]
            if alt < MIN_ALT:
                row.append("-")
                continue
            u = np.array([math.sin(math.radians(az)), math.cos(math.radians(az))])
            ta = math.tan(math.radians(alt))
            light = np.ones(len(pts))
            # buildings: shadow polygon = hull(footprint ∪ footprint shifted away from sun)
            bshade = np.zeros(len(pts), bool)
            for b in bi:
                fp, H, roof = buildings[b]
                L = min(H / ta, R)
                sh = fp - u * L
                allp = np.vstack([fp, sh])
                bx0, by0 = allp.min(0)
                bx1, by1 = allp.max(0)
                if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                    continue
                try:
                    hull = allp[ConvexHull(allp).vertices]
                except Exception:
                    continue
                bshade |= Path(hull).contains_points(pts)
            light[bshade] = 0.0
            # trees: crown disc at 0.7*H projected along sun ray
            if len(ti):
                tt = T[ti]
                D = (tt[:, 2] * 0.7) / ta
                D = np.minimum(D, R)
                cx = tt[:, 0] - u[0] * D
                cy = tt[:, 1] - u[1] * D
                dx = pts[:, 0][:, None] - cx[None, :]
                dy = pts[:, 1][:, None] - cy[None, :]
                hit = (dx * dx + dy * dy) < (tt[:, 3] ** 2)[None, :]
                trans = np.prod(np.where(hit, 1 - op[None, :], 1.0), axis=1)
                light *= trans
            f = 1 - light.mean()
            row.append(CH[int(round(f * 10))])
        out.append("".join(row))
    return out


def nearest(lst, x, y, maxd):
    best, bd = None, maxd
    for (a, b, n) in lst:
        d = math.hypot(a - x, b - y)
        if d < bd:
            best, bd = n, d
    return best


def clean_street(s):
    return s.strip()


AGE_MAP = lambda lo, hi: [k for k, a, b in (("0-3", 0, 3), ("3-6", 3, 6), ("6-12", 6, 12)) if not (hi is not None and hi < a) and not (lo is not None and lo >= b)]
SURF = {"rubber": "cautxu", "tartan": "cautxu", "rubber_tiles": "cautxu", "sand": "sorra", "artificial_turf": "gespa",
        "grass": "gespa", "dirt": "grava", "gravel": "grava", "fine_gravel": "grava", "ground": "grava", "woodchips": "grava"}

result = []
from collections import Counter
NAMECOUNT = Counter(n for (_, _, n) in named)
named = [t for t in named if NAMECOUNT[t[2]] <= 2 and len(t[2]) <= 48]
zone_seq = Counter()
for oid, (p, g, zone) in sorted(parks.items(), key=lambda kv: -kv[1][1]["coordinates"][0][0][1] if kv[1][1]["type"] == "Polygon" else 0):
    if g["type"] == "Point":
        cx, cy = xy(*g["coordinates"])
        ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        rings = [np.c_[cx + 12 * np.cos(ang), cy + 12 * np.sin(ang)]]
    else:
        rings = [np.array([xy(*c) for c in r]) for r in rings_of(g)]
        if not rings:
            continue
    pts, area = sample_points(rings)
    allp = np.vstack(rings)
    bbox = (*allp.min(0), *allp.max(0))
    c = pts.mean(0)
    prof = shade_profile(pts, bbox)
    name = p.get("name:ca") or p.get("name")
    auto = False
    if not name:
        auto = True
        st = nearest(streets, c[0], c[1], 70)
        if st:
            name = "Zona de jocs · " + clean_street(st)
        else:
            nm = nearest(named, c[0], c[1], 160)
            if nm:
                name = "Zona de jocs prop de " + nm
            else:
                zone_seq[zone] += 1
                name = "Zona de jocs %s %d" % (zone, zone_seq[zone])
    lon, lat = to_ll(c[0], c[1])
    rec = {"id": "osm-" + oid.replace("/", "-"), "n": name[:80], "la": round(lat, 6), "lo": round(lon, 6),
           "a": int(round(area)), "s": "".join(prof), "_z": zone}
    if auto:
        rec["u"] = 1
    terra = SURF.get(p.get("surface"))
    if terra:
        rec["t"] = terra
    lo_, hi_ = num(p.get("min_age")) if p.get("min_age") else None, num(p.get("max_age")) if p.get("max_age") else None
    if lo_ is not None or hi_ is not None:
        rec["e"] = AGE_MAP(lo_, hi_)
    result.append(rec)

cnt = Counter(r["n"] for r in result)
seen = Counter()
for r in sorted(result, key=lambda r: -r["a"]):
    if cnt[r["n"]] > 3 and "prop de" in r["n"]:
        zone_seq[r["_z"]] += 1
        r["n"] = "Zona de jocs %s %d" % (r["_z"], zone_seq[r["_z"]])
        continue
    if cnt[r["n"]] > 1:
        seen[r["n"]] += 1
        if seen[r["n"]] > 1:
            r["n"] = (r["n"][:74] + " (%d)" % seen[r["n"]])
for r in result:
    r.pop("_z", None)
result.sort(key=lambda r: (r["la"], r["lo"]))
json.dump({"slot0": SLOT0, "step": STEP, "n": NSLOT, "parks": result}, open("/home/claude/osm/parks_osm.json", "w"),
          ensure_ascii=False, separators=(",", ":"))
print("written", len(result), file=sys.stderr)
