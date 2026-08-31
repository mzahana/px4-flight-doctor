"""Trajectory extraction and satellite basemap fetching.

Shared by both plot back-ends (`plots.py` -> matplotlib/PDF, `iplots.py` -> Plotly)
so the two render the same track from the same numbers.

Frames: PX4's local position is NED. Everything here is exposed as
`n` (north, m), `e` (east, m), `u` (up, m = -z) so the plots can put east on the
horizontal axis and read like a map.
"""
import io
import math
import os
import urllib.request

import numpy as np

R_EARTH = 6378137.0
# ESRI World Imagery: publicly reachable raster tiles, no API key required.
TILE_URL = os.environ.get(
    "PX4DOCTOR_TILE_URL",
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
    "MapServer/tile/{z}/{y}/{x}")
TILE_ATTRIB = "Imagery: Esri, Maxar, Earthstar Geographics"
MAX_ZOOM = 21
BLANK_STD = 12.0        # below this a tile is the server's "no imagery here" filler
MAX_TILES = 36          # 6x6 -> at most 36 HTTP GETs per report
TARGET_PX = 1100        # target width of the stitched crop


# --- trajectory ------------------------------------------------------------ #
def _finite_axis(a, need=10):
    """None when an axis is absent or effectively never commanded."""
    if a is None:
        return None
    return a if int(np.isfinite(a).sum()) >= need else None


def _setpoint(log, t0, t1):
    """Position setpoint as (t, n, e, u), each component None when unused.

    `vehicle_local_position_setpoint` is what the position controller actually ran;
    `trajectory_setpoint` (its input) is the fallback for logs that lack it. Both
    carry NaN on axes the current mode does not control in position - those NaNs
    are kept so the plotted setpoint breaks instead of interpolating across a
    velocity- or altitude-controlled stretch.
    """
    for topic, keys in (("vehicle_local_position_setpoint", ("x", "y", "z")),
                        ("trajectory_setpoint", ("position[0]", "position[1]",
                                                 "position[2]"))):
        d = log.get(topic)
        if d is None or any(k not in d for k in keys):
            continue
        t = log.t(d)
        m = (t >= t0) & (t <= t1)
        if m.sum() < 10:
            continue
        x, y, z = (d[k][m].astype(float) for k in keys)
        n, e, u = _finite_axis(x), _finite_axis(y), _finite_axis(-z)
        if n is None and e is None and u is None:
            continue
        return dict(t=t[m], n=n, e=e, u=u, source=topic)
    return None


def trajectory(log):
    """Measured and commanded position over the flight, or None.

    Returns dict(t, n, e, u, sp, lat0, lon0, span) where `sp` is the setpoint dict
    (or None) and `lat0/lon0` are the local-frame origin (None when the log never
    had a global reference).
    """
    lp = log.get("vehicle_local_position")
    if lp is None or not all(k in lp for k in ("x", "y", "z")):
        return None
    t = log.t(lp)
    w = log.in_air_window()
    t0, t1 = (w[0] - 2.0, w[1] + 2.0) if w else (t[0], t[-1])
    m = (t >= t0) & (t <= t1) & np.isfinite(lp["x"]) & np.isfinite(lp["y"]) \
        & np.isfinite(lp["z"])
    if m.sum() < 10:
        return None
    n, e, u = lp["x"][m].astype(float), lp["y"][m].astype(float), -lp["z"][m].astype(float)
    lat0 = lon0 = None
    if "ref_lat" in lp and "ref_lon" in lp:
        la, lo = float(lp["ref_lat"][m][-1]), float(lp["ref_lon"][m][-1])
        if np.isfinite(la) and np.isfinite(lo) and (abs(la) > 1e-6 or abs(lo) > 1e-6):
            lat0, lon0 = la, lo
    span = float(max(n.max() - n.min(), e.max() - e.min()))
    return dict(t=t[m], n=n, e=e, u=u, sp=_setpoint(log, t0, t1),
                lat0=lat0, lon0=lon0, span=span)


def track_errors(tr):
    """RMS setpoint-tracking error per axis, {axis: (rms, n_samples)}."""
    out = {}
    sp = tr.get("sp")
    if not sp:
        return out
    for key in ("n", "e", "u"):
        if sp.get(key) is None:
            continue
        ref = np.interp(sp["t"], tr["t"], tr[key])
        err = sp[key] - ref
        ok = np.isfinite(err)
        if ok.sum() >= 10:
            out[key] = (float(np.sqrt(np.mean(err[ok] ** 2))), int(ok.sum()))
    return out


# --- geodesy --------------------------------------------------------------- #
def ne_to_ll(n, e, lat0, lon0):
    lat = lat0 + math.degrees(n / R_EARTH)
    lon = lon0 + math.degrees(e / (R_EARTH * math.cos(math.radians(lat0))))
    return lat, lon


def ll_to_ne(lat, lon, lat0, lon0):
    n = math.radians(lat - lat0) * R_EARTH
    e = math.radians(lon - lon0) * R_EARTH * math.cos(math.radians(lat0))
    return n, e


def _tile_xy(lat, lon, z):
    """Fractional web-mercator tile coordinate."""
    k = 2 ** z
    la = math.radians(max(-85.0, min(85.0, lat)))
    x = (lon + 180.0) / 360.0 * k
    y = (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * k
    return x, y


def _tile_lat_lon(x, y, z):
    k = 2 ** z
    lon = x / k * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / k))))
    return lat, lon


# --- satellite basemap ----------------------------------------------------- #
_BASEMAP_CACHE = {}


def _fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "px4-flight-doctor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def satellite_basemap(lat0, lon0, n, e, pad=0.25, timeout=8.0):
    """Satellite crop covering the track, or None when it cannot be fetched.

    Returns dict(png, extent=(e_min, e_max, n_min, n_max), zoom, attrib) with the
    extent in the same local east/north metres as the track, so the image can be
    dropped straight behind the trajectory. Network failures (offline runs, a
    blocked tile server) return None and the caller simply omits the figure.

    Set PX4DOCTOR_NO_NETWORK=1 to skip the fetch entirely.
    """
    if os.environ.get("PX4DOCTOR_NO_NETWORK"):
        return None
    if lat0 is None or lon0 is None:
        return None
    # square, padded bounding box around the track, with a floor so a hover-in-place
    # flight still gets a sensible amount of ground around it
    cn, ce = (n.max() + n.min()) / 2, (e.max() + e.min()) / 2
    half = max(n.max() - n.min(), e.max() - e.min()) / 2
    half = max(half * (1 + 2 * pad), 20.0)
    key = (round(lat0, 6), round(lon0, 6), round(cn, 1), round(ce, 1), round(half, 1))
    if key in _BASEMAP_CACHE:
        return _BASEMAP_CACHE[key]
    result = None
    try:
        result = _build_basemap(lat0, lon0, cn, ce, half, timeout)
    except Exception:
        result = None
    _BASEMAP_CACHE[key] = result
    return result


def _build_basemap(lat0, lon0, cn, ce, half, timeout):
    from PIL import Image

    lat_s, lon_w = ne_to_ll(cn - half, ce - half, lat0, lon0)
    lat_n, lon_e = ne_to_ll(cn + half, ce + half, lat0, lon0)
    ground = 2 * half
    tiles = {}

    def tile(z, tx, ty):
        """Fetch (and memoise) one tile; None when it is missing or blank."""
        key = (z, tx, ty)
        if key not in tiles:
            try:
                raw = _fetch(TILE_URL.format(z=z, x=tx, y=ty), timeout)
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                # past the deepest imagery the server still answers 200 with a flat
                # filler tile, so judge availability by content, not status code
                blank = float(np.asarray(img, dtype=np.float64).std()) < BLANK_STD
                tiles[key] = None if blank else img
            except Exception:
                tiles[key] = None
        return tiles[key]

    # deepest zoom that has real imagery, fits the tile budget, and does not blow
    # past the target crop width (metres per pixel = 156543.03 * cos(lat) / 2^z)
    zoom = None
    for z in range(MAX_ZOOM, 0, -1):
        mpp = 156543.03392 * math.cos(math.radians(lat0)) / (2 ** z)
        if ground / mpp > TARGET_PX:
            continue
        x0f, y0f = _tile_xy(lat_n, lon_w, z)
        x1f, y1f = _tile_xy(lat_s, lon_e, z)
        if (int(x1f) - int(x0f) + 1) * (int(y1f) - int(y0f) + 1) > MAX_TILES:
            continue
        cx, cy = _tile_xy((lat_n + lat_s) / 2, (lon_w + lon_e) / 2, z)
        if tile(z, int(cx), int(cy)) is not None:
            zoom = z
            break
    if zoom is None:
        return None

    x0f, y0f = _tile_xy(lat_n, lon_w, zoom)
    x1f, y1f = _tile_xy(lat_s, lon_e, zoom)
    tx0, ty0, tx1, ty1 = int(x0f), int(y0f), int(x1f), int(y1f)
    ts = 256
    canvas = Image.new("RGB", (ts * (tx1 - tx0 + 1), ts * (ty1 - ty0 + 1)), (32, 34, 36))
    got = 0
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            img = tile(zoom, tx, ty)
            if img is None:
                continue
            canvas.paste(img.resize((ts, ts)), ((tx - tx0) * ts, (ty - ty0) * ts))
            got += 1
    if got == 0:
        return None

    # crop the stitched sheet back to the requested bbox
    left, right = int(round((x0f - tx0) * ts)), int(round((x1f - tx0) * ts))
    top, bottom = int(round((y0f - ty0) * ts)), int(round((y1f - ty0) * ts))
    if right - left < 8 or bottom - top < 8:
        return None
    crop = canvas.crop((left, top, right, bottom))
    # exact extent of the cropped pixels, back in local metres
    lat_top, lon_left = _tile_lat_lon(tx0 + left / ts, ty0 + top / ts, zoom)
    lat_bot, lon_right = _tile_lat_lon(tx0 + right / ts, ty0 + bottom / ts, zoom)
    n_max, e_min = ll_to_ne(lat_top, lon_left, lat0, lon0)
    n_min, e_max = ll_to_ne(lat_bot, lon_right, lat0, lon0)

    buf = io.BytesIO()
    crop.save(buf, format="PNG", optimize=True)
    return dict(png=buf.getvalue(), size=crop.size, zoom=zoom, attrib=TILE_ATTRIB,
                extent=(float(e_min), float(e_max), float(n_min), float(n_max)))
