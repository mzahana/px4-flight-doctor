"""Flight summary - the at-a-glance numbers shown above the diagnosis.

`flight_summary` never raises: every item is computed defensively and simply
omitted when the topic or field it needs is missing, so a log from another
airframe/firmware yields a shorter dashboard rather than an error.
"""
import numpy as np

from .core import nav_state_name


def _stat(label, value, unit="", hint="", tone=""):
    return dict(label=label, value=value, unit=unit, hint=hint, tone=tone)


def _fmt(v, nd=1):
    return f"{float(v):.{nd}f}"


def _hhmmss(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def _identity(log):
    """Airframe / firmware strings out of the ulog header, best effort."""
    out = {}
    info = getattr(log.ulog, "msg_info_dict", {}) or {}
    for key, name in (("sys_name", "sys"), ("ver_sw", "sw"), ("ver_hw", "hw"),
                      ("ver_hw_subtype", "hw_sub"), ("ver_sw_branch", "branch")):
        v = info.get(key)
        if isinstance(v, str) and v.strip():
            out[name] = v.strip()
    rel = info.get("ver_sw_release")
    if isinstance(rel, int):                 # 0xMMmmppTT packed version
        out["rel"] = f"v{(rel >> 24) & 0xFF}.{(rel >> 16) & 0xFF}.{(rel >> 8) & 0xFF}"
    if "sw" in out:
        out["sw"] = out["sw"][:9]
    return out


def flight_summary(log, spec, hover=None):
    """-> {'items': [stat, ...], 'modes': [{name, seconds, pct}], 'header': {...}}"""
    items, ident = [], _identity(log)
    w = log.in_air_window()
    total = float(log.ulog.last_timestamp - log.ulog.start_timestamp) / 1e6

    items.append(_stat("Log duration", _hhmmss(total), "min:s"))
    if w:
        items.append(_stat("Airborne", _hhmmss(w[1] - w[0]), "min:s",
                           f"takeoff at t={w[0]:.0f} s"))

    lp = log.get("vehicle_local_position")
    if lp is not None:
        t = log.t(lp)
        m = np.ones_like(t, dtype=bool) if not w else (t >= w[0]) & (t <= w[1])
        if m.sum() > 5:
            z, vx, vy, vz = lp["z"][m], lp["vx"][m], lp["vy"][m], lp["vz"][m]
            alt = -(z - z[0])
            items.append(_stat("Max altitude", _fmt(np.nanmax(alt)), "m AGL",
                               "relative to takeoff point"))
            vh = np.hypot(vx, vy)
            items.append(_stat("Max ground speed", _fmt(np.nanmax(vh)), "m/s",
                               f"mean {_fmt(np.nanmean(vh))} m/s"))
            items.append(_stat("Max climb / descent",
                               f"{_fmt(np.nanmax(-vz))} / {_fmt(np.nanmin(-vz))}", "m/s"))
            dist = float(np.nansum(np.hypot(np.diff(lp["x"][m]), np.diff(lp["y"][m]))))
            items.append(_stat("Distance flown", _fmt(dist, 0), "m",
                               f"max {_fmt(np.nanmax(np.hypot(lp['x'][m], lp['y'][m])), 0)} m from origin"))

    att = log.get("vehicle_attitude")
    if att is not None:
        q = np.stack([att[f"q[{i}]"] for i in range(4)]).astype(float)
        t = log.t(att)
        m = np.ones_like(t, dtype=bool) if not w else (t >= w[0]) & (t <= w[1])
        if m.sum() > 5:
            qw, qx, qy, qz = q[:, m]
            # cos of tilt angle = body z projected on world z
            czz = np.clip(1 - 2 * (qx ** 2 + qy ** 2), -1, 1)
            tilt = np.degrees(np.arccos(czz))
            items.append(_stat("Max tilt", _fmt(np.nanmax(tilt), 0), "deg",
                               f"mean {_fmt(np.nanmean(tilt), 0)}°"))

    b = log.get("battery_status")
    if b is not None:
        t = log.t(b)
        m = np.ones_like(t, dtype=bool) if not w else (t >= w[0]) & (t <= w[1])
        if m.sum() > 5:
            V = b["voltage_v"][m]
            cells = int(log.param("BAT1_N_CELLS", 0) or 0)
            per = f" ({_fmt(V[0] / cells, 2)} → {_fmt(V[-1] / cells, 2)} V/cell)" if cells else ""
            items.append(_stat("Pack voltage", f"{_fmt(V[0], 1)} → {_fmt(V[-1], 1)}", "V",
                               f"sag {_fmt(V[0] - float(np.nanmin(V)), 1)} V worst{per}"))
            if "current_a" in b:
                I = b["current_a"][m]
                if np.isfinite(I).any() and np.nanmax(I) > 0:
                    items.append(_stat("Current", f"{_fmt(np.nanmean(I))} avg / "
                                       f"{_fmt(np.nanmax(I))} peak", "A"))
                    items.append(_stat("Mean power", _fmt(np.nanmean(V * I), 0), "W"))
            if "discharged_mah" in b:
                used = float(np.nanmax(b["discharged_mah"][m]) - np.nanmin(b["discharged_mah"][m]))
                cap = spec.battery_capacity_mah if getattr(spec, "battery_capacity_mah", None) else None
                items.append(_stat("Energy used", _fmt(used, 0), "mAh",
                                   f"{used / cap * 100:.0f} % of pack" if cap else ""))
            if "remaining" in b:
                items.append(_stat("Battery left", _fmt(np.nanmin(b["remaining"][m]) * 100, 0), "%"))

    g = log.get("vehicle_gps_position") or log.get("sensor_gps")
    if g is not None and "satellites_used" in g:
        sats = g["satellites_used"].astype(float)
        hd = g.get("hdop")
        items.append(_stat("GPS satellites", f"{np.nanmin(sats):.0f} – {np.nanmax(sats):.0f}", "",
                           f"HDOP min {np.nanmin(hd):.1f}" if hd is not None and np.isfinite(hd).any() else ""))

    if hover:
        nc = hover.get("norm_cmd")
        if nc is not None and np.size(nc) and np.isfinite(nc).any():
            items.append(_stat("Hover throttle", _fmt(np.nanmean(nc) * 100, 0), "%",
                               f"spread {np.nanmax(nc) * 100 - np.nanmin(nc) * 100:.0f} pp across motors"))
        if hover.get("current") is not None:
            items.append(_stat("Hover draw", f"{_fmt(hover['current'])} A @ "
                               f"{_fmt(hover['voltage'])} V", "",
                               "steady-state hover operating point"))

    if getattr(spec, "mass_kg", None):
        items.append(_stat("Takeoff mass", _fmt(spec.mass_kg, 2), "kg", "as entered"))

    # mode timeline for the little stacked bar
    modes, spans = [], log.mode_spans()
    if spans:
        agg = {}
        for t0, t1, name in spans:
            agg[name] = agg.get(name, 0.0) + (t1 - t0)
        span_total = sum(agg.values()) or 1.0
        modes = [dict(name=n, seconds=round(s, 1), pct=round(s / span_total * 100, 1))
                 for n, s in sorted(agg.items(), key=lambda kv: -kv[1])]

    fw = " ".join(x for x in (ident.get("rel", ""), ident.get("branch", ""),
                              ident.get("sw", "")) if x)
    header = dict(airframe=ident.get("sys", ""), firmware=fw,
                  hardware=" ".join(x for x in (ident.get("hw", ""), ident.get("hw_sub", "")) if x),
                  airframe_id=str(int(log.param("SYS_AUTOSTART", 0) or 0) or ""))
    return dict(items=items, modes=modes, header=header)
