"""Annotated diagnostic figures (matplotlib, Agg). Each figure is rendered once
as SVG (web UI) and PNG (PDF embedding)."""
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .core import AUTOTUNE_STATES

C = dict(blue="#2471a3", red="#c0392b", green="#1e8449", orange="#b9770e",
         purple="#6c3483", grey="#7f8c8d", band="#f2c94c")
MOTOR_COLORS = ["#2471a3", "#c0392b", "#1e8449", "#b9770e"]

plt.rcParams.update({
    "figure.dpi": 110, "savefig.bbox": "tight",
    "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.titlepad": 22,   # room for the two staggered rows of flight-mode labels
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "legend.framealpha": 0.85,
    "figure.constrained_layout.use": True,
})


def _ds(t, y, n=1800):
    """Stride-downsample so SVGs stay small."""
    if len(t) <= n:
        return t, y
    step = len(t) // n + 1
    return t[::step], y[::step]


def _autotune_spans(log):
    d = log.get("autotune_attitude_control_status")
    if d is None:
        return []
    t, st = log.t(d), d["state"]
    spans, start, cur = [], None, None
    label = {3: "ROLL ID", 6: "PITCH ID", 9: "YAW ID"}
    for i in range(len(st)):
        s = int(st[i])
        if s in label and s != cur:
            start, cur = t[i], s
        elif cur in label and s != cur:
            spans.append((start, t[i], label[cur]))
            cur = None
    if cur in label:
        spans.append((start, t[-1], label[cur]))
    return [(float(a), float(b), l) for a, b, l in spans]


# Flight-mode shading -------------------------------------------------------
MODE_COLORS = {
    "MANUAL": "#9b59b6", "STABILIZED": "#8e44ad", "ACRO": "#e67e22",
    "ALTCTL": "#16a085", "POSCTL": "#2980b9", "POSITION_SLOW": "#5dade2",
    "AUTO_MISSION": "#27ae60", "AUTO_LOITER": "#1abc9c", "AUTO_RTL": "#f39c12",
    "AUTO_TAKEOFF": "#58d68d", "AUTO_LAND": "#af7ac5", "OFFBOARD": "#c0392b",
    "DESCEND": "#7f8c8d", "TERMINATION": "#922b21", "ORBIT": "#d35400",
    "PRECLAND": "#a569bd", "FOLLOW_TARGET": "#48c9b0", "AUTO_VTOL_TAKEOFF": "#52be80",
}
_MODE_FALLBACK = ["#7f8c8d", "#34495e", "#c39bd3", "#5499c7"]


def mode_color(name):
    """Stable color per mode name (unknown modes hash into a fallback palette)."""
    if name in MODE_COLORS:
        return MODE_COLORS[name]
    return _MODE_FALLBACK[sum(map(ord, name)) % len(_MODE_FALLBACK)]


def _shade_modes(ax, spans, label=False):
    """Tint the background by flight mode; label above the axes on the top plot.

    Labels are staggered over two rows and dropped for slivers too narrow to hold
    text, so a mode-hopping flight does not turn the strip into overlapping mush.
    """
    if not spans:
        return
    total = float(spans[-1][1] - spans[0][0]) or 1.0
    row, prev_end = 0, -np.inf
    for t0, t1, name in spans:
        c = mode_color(name)
        ax.axvspan(t0, t1, color=c, alpha=0.09, zorder=0)
        ax.axvline(t0, color=c, lw=0.8, alpha=0.45, zorder=0)
        if not label:
            continue
        # a label needs roughly this much x-room; below it, skip rather than overlap
        need = 0.011 * total * max(len(name), 4)
        if (t1 - t0) < min(need, 0.05 * total):
            continue
        mid = (t0 + t1) / 2
        row = 0 if mid - prev_end > 0.10 * total else 1 - row
        ax.text(mid, 1.015 + 0.055 * row, name, transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=7, color=c, fontweight="bold",
                clip_on=False)
        prev_end = mid


def _shade_autotune(ax, spans, y=0.97):
    for t0, t1, lbl in spans:
        ax.axvspan(t0, t1, color=C["band"], alpha=0.18, zorder=0)
        ax.text((t0 + t1) / 2, y, lbl, transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=7.5, color="#8a6d1a", fontweight="bold")


def _flight_markers(ax, log):
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            ax.axvline(x, color=C["grey"], ls=":", lw=1)
            ax.annotate(lbl, (x, 0.02), xycoords=ax.get_xaxis_transform(),
                        fontsize=7.5, color=C["grey"], rotation=90, va="bottom",
                        ha="right", xytext=(-2, 0), textcoords="offset points")


def _render(fig):
    svg, png = io.StringIO(), io.BytesIO()
    fig.savefig(svg, format="svg")
    fig.savefig(png, format="png", dpi=130)
    plt.close(fig)
    return svg.getvalue(), png.getvalue()


# --------------------------------------------------------------------------- #
def fig_overview(log, spec):
    lp, b = log.get("vehicle_local_position"), log.get("battery_status")
    if lp is None:
        return None
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 4.6), sharex=True)
    t = log.t(lp)
    a1.plot(*_ds(t, -lp["z"]), color=C["blue"], lw=1.2, label="altitude (local)")
    a1.set_ylabel("altitude [m]")
    a1.set_title("Flight overview")
    spans = _autotune_spans(log)
    modes = log.mode_spans()
    _shade_modes(a1, modes, label=True)
    _shade_autotune(a1, spans)
    _flight_markers(a1, log)
    a1.legend(loc="upper left", fontsize=8)
    if b is not None:
        tb = log.t(b)
        cells = max(int(log.param("BAT1_N_CELLS", 4)), 1)
        vc = b["voltage_v"] / cells
        a2.plot(*_ds(tb, vc), color=C["red"], lw=1.2, label="cell voltage")
        a2.set_ylabel("V / cell", color=C["red"])
        imin = np.argmin(vc)
        a2.annotate(f"min {vc[imin]:.2f} V/cell", (tb[imin], vc[imin]),
                    xytext=(10, -12), textcoords="offset points", fontsize=8,
                    color=C["red"], arrowprops=dict(arrowstyle="->", color=C["red"], lw=0.8))
        a2.axhline(3.5, color=C["red"], ls="--", lw=0.8, alpha=0.5)
        a2.text(t[0], 3.5, " 3.5 V sag floor", fontsize=7, color=C["red"], va="bottom")
        a3 = a2.twinx()
        a3.plot(*_ds(tb, b["current_a"]), color=C["purple"], lw=1.0, alpha=0.8, label="current")
        a3.set_ylabel("current [A]", color=C["purple"])
        a3.grid(False)
        _shade_modes(a2, modes)
        _shade_autotune(a2, spans)
    a2.set_xlabel("time [s]")
    return ("overview", "Flight overview",
            "Altitude with flight-mode windows tinted (mode name above the plot) and autotune "
            "phases shaded in amber; battery cell voltage and pack current below.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def _airframe_data(log):
    """Shared geometry/load data for the airframe diagram (both back-ends).

    Returns dict(pos Nx2 [fwd,right], km N, arms N, means N|None, cg (dx,dy)|None)
    or None when the log has no usable CA_ROTOR* geometry. `means`/`cg` are None
    when the log lacks a quasi-static hover segment (same gate as the checks).
    """
    from .propulsion import rotor_geometry, cg_offset
    geo = rotor_geometry(log)
    if geo is None:
        return None
    pos = np.array([(px, py) for px, py, _ in geo])
    km = np.array([g[2] for g in geo])
    means = cg = None
    am = log.get("actuator_motors")
    if am is not None:
        t = log.t(am)
        m = log.hover_mask(t)
        dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
        if int(m.sum()) >= 30 and m.sum() * dt >= 5.0:
            vals = []
            for i in range(len(geo)):
                key = f"control[{i}]"
                if key not in am or not np.isfinite(am[key][m]).any():
                    vals = None
                    break
                vals.append(float(np.nanmean(am[key][m])))
            if vals:
                means = np.array(vals)
                cg = cg_offset(geo, means)
    return dict(pos=pos, km=km, arms=np.hypot(pos[:, 0], pos[:, 1]),
                means=means, cg=cg)


def _cg_words(dx, dy, dist):
    parts = []
    if abs(dx) > 0.25 * dist:
        parts.append("forward" if dx > 0 else "aft")
    if abs(dy) > 0.25 * dist:
        parts.append("right" if dy > 0 else "left")
    return "-".join(parts) or "off"


AIRFRAME_CAPTION = (
    "Rotor positions and expected spin directions from the CA_ROTOR* "
    "control-allocation parameters; motor numbers are PX4's 0-based rotor/"
    "actuator_motors indices, so mount your motors and prop directions to match "
    "(disc size is schematic, not the real prop diameter). The value "
    "under each motor is its mean normalized command during quasi-static hover - "
    "equal values mean a balanced airframe. The red dot is the thrust-weighted CG "
    "estimate relative to the geometric rotor center (grey cross); hovering in "
    "steady wind shifts load the same way, so confirm a CG finding in calm air.")


def fig_airframe(log, spec):
    d = _airframe_data(log)
    if d is None:
        return None
    pos, km, arms, means, cg = d["pos"], d["km"], d["arms"], d["means"], d["cg"]
    r_disc = 0.38 * float(arms[arms > 0.01].min())
    lim = float(arms.max()) + 2.1 * r_disc
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    ax.set_aspect("equal")
    ax.set_title("Airframe layout (top view)")
    ax.set_xlabel("right [m]")
    ax.set_ylabel("forward [m]")
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    for (fx, ry) in pos:
        ax.plot([0, ry], [0, fx], color=C["grey"], lw=2.5, alpha=0.45,
                solid_capstyle="round", zorder=1)
    labeled = set()
    for i, ((fx, ry), k) in enumerate(zip(pos, km)):
        col = C["blue"] if k > 0 else C["orange"]
        ax.add_patch(plt.Circle((ry, fx), r_disc, facecolor=col, alpha=0.14,
                                edgecolor=col, lw=1.6, zorder=2))
        ax.text(ry, fx + 0.32 * r_disc, f"M{i} {'CCW ↺' if k > 0 else 'CW ↻'}",
                ha="center", va="center", fontsize=9, fontweight="bold",
                color=col, zorder=3)
        if means is not None:
            ax.text(ry, fx - 0.40 * r_disc, f"{means[i]:.3f}", ha="center",
                    va="center", fontsize=8, color="#333333", zorder=3)
        rkey = round(float(arms[i]), 2)
        if rkey not in labeled and arms[i] > 0.01:
            labeled.add(rkey)
            ax.text(0.55 * ry, 0.55 * fx, f"{arms[i]:.2f} m", ha="center",
                    va="center", fontsize=7.5, color=C["grey"], zorder=3,
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    ax.plot(0, 0, marker="+", color=C["grey"], ms=13, mew=1.8, zorder=4)
    ax.annotate("forward", xy=(0, 0.97 * lim), xytext=(0, 0.72 * lim),
                ha="center", fontsize=8, color=C["grey"],
                arrowprops=dict(arrowstyle="->", color=C["grey"]))
    span = float(max(np.hypot(*(p - q)) for p in pos for q in pos))
    foot = f"max motor-to-motor span {span:.2f} m"
    if cg is not None:
        dx, dy = cg
        dist = float(np.hypot(dx, dy))
        ax.plot(dy, dx, marker="o", color=C["red"], ms=7, zorder=5)
        ax.annotate(f"est. CG {dist*100:.1f} cm {_cg_words(dx, dy, dist)}",
                    xy=(dy, dx), xytext=(0.04, 0.05), textcoords="axes fraction",
                    fontsize=8.5, color=C["red"], fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=C["red"], lw=0.9))
    else:
        foot += "  ·  no quasi-static hover in log - CG not estimated"
    ax.text(0.98, 0.02, foot, transform=ax.transAxes, ha="right",
            fontsize=7.5, color=C["grey"])
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    handles = [Patch(facecolor=C["blue"], alpha=0.3, edgecolor=C["blue"], label="CCW ↺"),
               Patch(facecolor=C["orange"], alpha=0.3, edgecolor=C["orange"], label="CW ↻")]
    if cg is not None:
        handles.append(Line2D([], [], marker="o", ls="", color=C["red"], label="estimated CG"))
    ax.legend(handles=handles, loc="upper right", fontsize=7.5)
    return ("airframe", "Airframe layout", AIRFRAME_CAPTION, *_render(fig))


# --------------------------------------------------------------------------- #
def fig_motors(log, spec):
    am = log.get("actuator_motors")
    if am is None:
        return None
    fig, ax = plt.subplots(figsize=(9, 3.4))
    t = log.t(am)
    n = sum(1 for i in range(12) if f"control[{i}]" in am and np.isfinite(am[f"control[{i}]"]).any())
    for i in range(min(n, 8)):
        ax.plot(*_ds(t, am[f"control[{i}]"]), lw=0.9,
                color=MOTOR_COLORS[i % 4], label=f"motor {i}", alpha=0.9)
    ax.axhline(1.0, color=C["red"], ls="--", lw=1.2)
    ax.text(t[0], 1.0, " saturation limit", color=C["red"], fontsize=8, va="bottom")
    # configured PWM ceiling below hardware max?
    from .propulsion import motor_output_channels
    mo = motor_output_channels(log)
    if mo and min(r[1] for r in mo[2]) < 1950:
        hi = min(r[1] for r in mo[2])
        w = log.in_air_window()
        m = (t > w[0]) & (t < w[1]) if w else slice(None)
        ceil_hits = np.max(np.stack([am[f"control[{i}]"][m] for i in range(n)]), 0) >= 0.999
        if ceil_hits.any():
            th = t[m][ceil_hits][0]
            ax.annotate(f"hit configured ceiling (PWM max {hi:.0f})", (th, 1.0),
                        xytext=(15, -25), textcoords="offset points", fontsize=8,
                        color=C["red"], fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color=C["red"]))
    w = log.in_air_window()
    if w:
        m = (t > w[0]) & (t < w[1])
        hov = float(np.mean(np.stack([am[f"control[{i}]"][m] for i in range(n)])))
        ax.axhline(hov, color=C["grey"], ls="-.", lw=0.9)
        ax.text(t[-1], hov, f"mean {hov:.2f} ", color=C["grey"], fontsize=8,
                ha="right", va="bottom")
        ax.axhline(0.5, color=C["green"], ls=":", lw=0.9)
        ax.text(t[0], 0.5, " ideal hover ~0.5", color=C["green"], fontsize=7.5, va="bottom")
    _shade_modes(ax, log.mode_spans(), label=True)
    _shade_autotune(ax, _autotune_spans(log), y=0.12)
    _flight_markers(ax, log)
    ax.set_ylim(0, 1.1)
    ax.set_xlabel("time [s]")
    ax.set_ylabel("normalized command")
    ax.set_title("Motor commands")
    ax.legend(loc="lower right", fontsize=7.5, ncol=4)
    return ("motors", "Motor commands",
            "Per-motor normalized thrust command. Watch the gap between the flight mean "
            "and the saturation limit - that gap is your control headroom.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_rates(log, spec):
    av, rs = log.get("vehicle_angular_velocity"), log.get("vehicle_rates_setpoint")
    if av is None or rs is None:
        return None
    fig, axes = plt.subplots(3, 1, figsize=(9, 5.6), sharex=True)
    ta, tr = log.t(av), log.t(rs)
    spans = _autotune_spans(log)
    modes = log.mode_spans()
    for i, (ax, name) in enumerate(zip(axes, ("roll", "pitch", "yaw"))):
        ax.plot(*_ds(tr, np.degrees(rs[name])), color=C["grey"], lw=0.9, label="setpoint")
        ax.plot(*_ds(ta, np.degrees(av[f"xyz[{i}]"])), color=MOTOR_COLORS[i], lw=0.9,
                alpha=0.85, label="actual")
        ax.set_ylabel(f"{name} [deg/s]")
        _shade_modes(ax, modes, label=(i == 0))
        _shade_autotune(ax, spans)
        if i == 0:
            ax.set_title("Rate tracking: setpoint vs actual")
            ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("time [s]")
    return ("rates", "Rate tracking",
            "How closely the measured body rates follow the controller's setpoints. "
            "Shaded bands are autotune square-wave injections - the actual should follow "
            "them crisply; lag or overshoot there is what the identifier 'sees'.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_raw_imu(log, spec):
    """Raw accelerometer and gyro time series, all three axes."""
    sc = log.get("sensor_combined")
    if sc is None:
        return None
    t = log.t(sc)
    if len(t) < 100:
        return None
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
    modes = log.mode_spans()
    for ax, src, unit, first in ((a1, "accelerometer_m_s2", "m/s²", True),
                                 (a2, "gyro_rad", "rad/s", False)):
        for i, lbl in enumerate("xyz"):
            y = sc[f"{src}[{i}]"].astype(float)
            ax.plot(*_ds(t, y, 6000), lw=0.6, alpha=0.85, color=MOTOR_COLORS[i], label=lbl)
        ax.set_ylabel(f"{'accel' if first else 'gyro'} [{unit}]")
        _shade_modes(ax, modes, label=first)
        _shade_autotune(ax, _autotune_spans(log), y=0.06 if first else 0.97)
        _flight_markers(ax, log)
        ax.legend(fontsize=8, ncol=3, loc="upper right", framealpha=0.95,
                  borderpad=0.3, columnspacing=1.0, handlelength=1.2)
    a1.set_title("Raw IMU: accelerometer (top) and gyro (bottom)")
    a2.set_xlabel("time [s]")
    return ("rawimu", "Raw IMU signals",
            "Unfiltered accelerometer and gyro straight off the sensor. The z accel sits "
            "near -9.8 m/s² in level flight; band thickness is vibration, steps are "
            "impacts or clipping, and a slow drift on the gyro at rest is bias. Compare "
            "the noise band before and after takeoff to separate airframe vibration from "
            "sensor noise.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_vibration(log, spec):
    sc = log.get("sensor_combined")
    w = log.in_air_window()
    if sc is None or w is None:
        return None
    t = log.t(sc)
    m = (t > w[0] + 2) & (t < w[1] - 1)
    if m.sum() < 512:
        return None
    dt = float(np.median(np.diff(t[m])))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.6))
    for src, ax, unit in (("accelerometer_m_s2", a1, "m/s²"), ("gyro_rad", a2, "rad/s")):
        peak_f, peak_v, top = 0, 0, 0
        for i, lbl in enumerate("xyz"):
            x = sc[f"{src}[{i}]"][m].astype(float)
            x -= x.mean()
            fr = np.fft.rfftfreq(len(x), dt)
            P = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x) * 4
            sel = fr > 3
            ax.plot(fr[sel], P[sel], lw=0.9, label=lbl, color=MOTOR_COLORS[i])
            j = np.argmax(P[sel])
            top = max(top, float(P[sel][j]))
            if P[sel][j] > peak_v:
                peak_v, peak_f = P[sel][j], fr[sel][j]
        # headroom so the legend never lands on a trace or on the peak callout
        ax.set_ylim(0, top * 1.45)
        nyq = 0.5 / dt
        right = peak_f > 0.55 * nyq          # keep the callout inside the axes
        ax.annotate(f"dominant {peak_f:.0f} Hz", (peak_f, peak_v),
                    xytext=(-14 if right else 14, 10), textcoords="offset points",
                    fontsize=8.5, ha="right" if right else "left",
                    color=C["red"], fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=C["red"]))
        ax.axvline(nyq, color=C["grey"], ls="--", lw=0.9)
        # vertical labels sit along the bottom, clear of the legend box
        ax.text(nyq, 0.04, "Nyquist ", transform=ax.get_xaxis_transform(), rotation=90,
                rotation_mode="anchor", ha="left", va="top", fontsize=7.5, color=C["grey"])
        cutoff = log.param("IMU_GYRO_CUTOFF")
        if src.startswith("gyro") and cutoff:
            ax.axvline(cutoff, color=C["green"], ls=":", lw=0.9)
            ax.text(cutoff, 0.04, f"LPF {cutoff:.0f} Hz ", transform=ax.get_xaxis_transform(),
                    rotation=90, rotation_mode="anchor", ha="left", va="bottom",
                    fontsize=7.5, color=C["green"])
        ax.set_xlabel("frequency [Hz]")
        ax.set_ylabel(f"amplitude [{unit}]")
        ax.set_title("Accelerometer spectrum" if ax is a1 else "Gyro spectrum")
        ax.legend(fontsize=8, ncol=3, loc="upper right", framealpha=0.95,
                  borderpad=0.3, columnspacing=1.0, handlelength=1.2)
    return ("vibration", "Vibration spectrum",
            "In-flight FFT of raw IMU data. Sharp peaks are mechanical resonances or "
            "prop-order vibration; a notch filter should be placed on the dominant peak. "
            "Energy near Nyquist aliases into the control band.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_autotune(log, spec):
    d = log.get("autotune_attitude_control_status")
    if d is None:
        return None
    t = log.t(d)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
    spans = _autotune_spans(log)
    modes = log.mode_spans()
    cv = np.stack([d[f"coeff_var[{i}]"] for i in range(5)])
    worst = np.max(cv, axis=0)
    a1.semilogy(*_ds(t, worst), color=C["blue"], lw=1.2, label="worst coefficient variance")
    a1.axhline(50, color=C["red"], ls="--", lw=1)
    a1.text(t[0], 50, " convergence threshold (50)", color=C["red"], fontsize=8, va="bottom")
    _shade_modes(a1, modes, label=True)
    _shade_autotune(a1, spans)
    for t0, t1, lbl in spans:
        i = np.searchsorted(t, t1) - 1
        if 0 <= i < len(worst):
            a1.annotate(f"{worst[i]:.0f}", (t1, worst[i]), fontsize=7.5,
                        color=C["blue"], xytext=(3, 3), textcoords="offset points")
    a1.set_ylabel("coeff variance")
    a1.set_title("Autotune convergence (lower = more certain model)")
    a1.legend(fontsize=8, loc="upper right")
    a2.plot(*_ds(t, d["kc"]), color=C["green"], lw=1.2, label="rate gain K")
    a2.plot(*_ds(t, d["kd"] * 10), color=C["purple"], lw=1.0, label="rate D x10")
    a2.plot(*_ds(t, d["att_p"] / 10), color=C["orange"], lw=1.0, label="attitude P / 10")
    _shade_modes(a2, modes)
    _shade_autotune(a2, spans)
    for t0, t1, lbl in spans:
        a2.axvline(t1, color=C["grey"], ls=":", lw=0.8)
        a2.annotate("gains locked", (t1, 0.02), xycoords=("data", "axes fraction"),
                    fontsize=7, color=C["grey"], rotation=90, va="bottom", ha="right")
    a2.set_ylim(bottom=0)
    a2.set_xlabel("time [s]")
    a2.set_ylabel("estimate")
    a2.set_title("Identified gain evolution - flat before lock-in = trustworthy")
    a2.legend(fontsize=8, loc="upper right")
    return ("autotune", "Autotune convergence",
            "Top: model uncertainty per axis run; gains are accepted the moment the worst "
            "variance drops below 50. Bottom: the gain estimates themselves - if they were "
            "still moving when locked, the result is a snapshot of an unconverged fit.",
            *_render(fig))




def _spectrogram(t, sig, target_cols=220, min_seg=256, max_seg=2048):
    """Plain-numpy STFT of one signal.

    Returns (times, freqs, P) where P is power spectral density (unit²/Hz) with
    one column per window. Kept dependency-free (no scipy) on purpose.
    """
    dt = float(np.median(np.diff(t)))
    fs = 1.0 / dt
    n = int(2 ** round(np.log2(max(len(sig) / max(target_cols, 1) * 2, min_seg))))
    nseg = int(min(max(n, min_seg), max_seg, len(sig)))
    if nseg < min_seg:
        return None
    hop = max(nseg // 2, 1)
    win = np.hanning(nseg)
    norm = fs * (win ** 2).sum()          # PSD scaling for a windowed segment
    starts = range(0, len(sig) - nseg + 1, hop)
    cols, times = [], []
    for a in starts:
        seg = sig[a:a + nseg]
        seg = seg - seg.mean()
        P = np.abs(np.fft.rfft(seg * win)) ** 2 / norm
        P[1:-1] *= 2                       # one-sided
        cols.append(P)
        times.append(float(t[a + nseg // 2]))
    if not cols:
        return None
    return np.array(times), np.fft.rfftfreq(nseg, dt), np.array(cols).T


# --------------------------------------------------------------------------- #
def fig_mag_power(log, spec):
    from .checks import _mag_power_data
    d = _mag_power_data(log)
    if d is None or "I" not in d:
        return None
    # stacked, not side by side: the twin current axis on the right of the time plot
    # used to run straight into the scatter's |B| label
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 6.0),
                                 gridspec_kw=dict(height_ratios=[1.15, 1]))
    t, B, I = d["t"], d["B"] * 1000, d["I"]   # B in mGauss
    l1, = a1.plot(*_ds(t, B), color=C["blue"], lw=1.1, label="|B| [mG]")
    a1.set_xlabel("time [s]"); a1.set_ylabel("|B| [mG]", color=C["blue"])
    a1.set_title("Magnetic field vs power draw")
    ax2 = a1.twinx()
    l2, = ax2.plot(*_ds(t, I), color=C["purple"], lw=1.0, alpha=0.8, label="current [A]")
    ax2.set_ylabel("current [A]", color=C["purple"]); ax2.grid(False)
    _shade_modes(a1, log.mode_spans(), label=True)
    _shade_autotune(a1, _autotune_spans(log), y=0.1)
    # one legend for both axes instead of two boxes fighting over the same corner
    a1.legend([l1, l2], [l1.get_label(), l2.get_label()], fontsize=8,
              loc="upper left", ncol=2, framealpha=0.9)
    r = float(np.corrcoef(B, I)[0, 1])
    p = np.polyfit(I, B, 1)
    a2.plot(I, B, ".", ms=2, color=C["grey"], alpha=0.4, label="samples")
    xs = np.linspace(I.min(), I.max(), 20)
    a2.plot(xs, np.polyval(p, xs), color=C["red"], lw=1.6,
            label=f"fit {p[0]:+.2f} mG/A")
    a2.annotate(f"corr = {r:+.2f}", (0.02, 0.90), xycoords="axes fraction",
                fontsize=10, fontweight="bold",
                color=C["red"] if abs(r) > 0.5 else C["green"])
    a2.set_xlabel("battery current [A]"); a2.set_ylabel("|B| [mG]")
    a2.set_title("|B| vs current")
    a2.legend(fontsize=8, loc="lower right", framealpha=0.9)
    return ("magpower", "Magnetic field vs power",
            "Top: field magnitude and battery current over the flight. Bottom: the same "
            "data as a scatter with linear fit - a strong slope/correlation means motor "
            "current is bending the compass reading (move mag / twist power leads).",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_batt_ri(log, spec):
    b = log.get("battery_status")
    w = log.in_air_window()
    if b is None or w is None:
        return None
    t = log.t(b)
    m = (t > w[0]) & (t < w[1]) & np.isfinite(b["current_a"]) & (b["current_a"] > 0.5)
    if m.sum() < 30 or np.ptp(b["current_a"][m]) < 4:
        return None
    I, V, tt = b["current_a"][m], b["voltage_v"][m], t[m]
    A = np.column_stack([np.ones_like(I), -I, -(tt - tt[0])])
    coef, *_ = np.linalg.lstsq(A, V, rcond=None)
    cells = max(int(log.param("BAT1_N_CELLS", 4)), 1)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    sc = ax.scatter(I, V, c=tt - tt[0], s=6, cmap="viridis", alpha=0.7)
    fig.colorbar(sc, ax=ax, label="time [s]")
    xs = np.linspace(I.min(), I.max(), 20)
    mid_t = float(np.median(tt - tt[0]))
    ax.plot(xs, coef[0] - coef[1] * xs - coef[2] * mid_t, color=C["red"], lw=1.8,
            label=f"fit: R = {coef[1]*1000:.1f} mΩ pack "
                  f"= {coef[1]/cells*1000:.1f} mΩ/cell")
    ax.set_xlabel("current [A]"); ax.set_ylabel("pack voltage [V]")
    ax.set_title("Battery internal resistance (V-I scatter)")
    ax.legend(fontsize=9)
    return ("battri", "Battery internal resistance",
            "Pack voltage vs current, colored by time; the slope of the fit (with the slow "
            "SOC droop removed) is the pack's internal resistance. Set BAT1_R_INTERNAL to "
            "the per-cell value for accurate state-of-charge.",
            *_render(fig))

# --------------------------------------------------------------------------- #
def fig_accel_psd(log, spec):
    """Flight-Review style 2D accel PSD: summed x+y+z power vs frequency vs time."""
    sc = log.get("sensor_combined")
    if sc is None:
        return None
    t = log.t(sc)
    if len(t) < 4096:
        return None
    acc = None
    for i in range(3):
        r = _spectrogram(t, sc[f"accelerometer_m_s2[{i}]"].astype(float))
        if r is None:
            return None
        tt, fr, P = r
        acc = P if acc is None else acc + P     # sum the three axes' power
    sel = fr > 2
    db = 10 * np.log10(acc[sel] + 1e-12)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    mesh = ax.pcolormesh(tt, fr[sel], db, cmap="viridis", shading="auto",
                         vmin=np.percentile(db, 40), vmax=np.percentile(db, 99.9))
    _flight_markers(ax, log)
    cutoff = log.param("IMU_ACCEL_CUTOFF")
    if cutoff:
        ax.axhline(cutoff, color="w", ls=":", lw=1.0)
        ax.text(0.995, cutoff, f"accel LPF {cutoff:.0f} Hz ", color="w", fontsize=7.5,
                fontweight="bold", transform=ax.get_yaxis_transform(),
                ha="right", va="bottom")
    ax.set_xlabel("time [s]")
    ax.set_ylabel("frequency [Hz]")
    ax.set_title("Acceleration power spectral density")
    ax.grid(False)
    fig.colorbar(mesh, ax=ax, label="PSD [dB, (m/s²)²/Hz]", pad=0.015, aspect=30)
    return ("accelpsd", "Acceleration power spectral density",
            "Frequency response of the raw accelerometer over time, summed over x, y and "
            "z. Brighter (yellow) = more vibration energy at that time and frequency. "
            "Horizontal lines are fixed resonances; bands that drift up and down with "
            "throttle are motor/prop order. Broad yellow smears mean the airframe is "
            "shaking across the whole band, which is what corrupts the EKF.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_vibe_spectrogram(log, spec):
    sc = log.get("sensor_combined")
    if sc is None:
        return None
    t = log.t(sc)
    if len(t) < 4096:
        return None
    axis_names = ("roll", "pitch", "yaw")
    fig, axes = plt.subplots(3, 1, figsize=(9, 7.2), sharex=True, sharey=True)
    cutoff = log.param("IMU_GYRO_CUTOFF")
    w = log.in_air_window()
    mesh = None
    for i, (ax, name) in enumerate(zip(axes, axis_names)):
        r = _spectrogram(t, sc[f"gyro_rad[{i}]"].astype(float))
        if r is None:
            plt.close(fig)
            return None
        tt, fr, P = r
        sel = fr > 2
        db = 10 * np.log10(P[sel] + 1e-12)
        # common scale across axes: absolute dB is what matters, not per-axis contrast
        mesh = ax.pcolormesh(tt, fr[sel], db, cmap="magma", shading="auto",
                             vmin=np.percentile(db, 40), vmax=np.percentile(db, 99.9))
        ax.set_ylabel(f"{name} gyro\nfreq [Hz]")
        if cutoff:
            ax.axhline(cutoff, color="#7fd3ff", ls=":", lw=1.0)
        if w:
            for x in w:
                ax.axvline(x, color="w", ls=":", lw=1.0, alpha=0.7)
    if cutoff:
        axes[0].text(0.995, cutoff, f"gyro LPF {cutoff:.0f} Hz ", color="#7fd3ff",
                     transform=axes[0].get_yaxis_transform(), ha="right", va="bottom",
                     fontsize=7.5, fontweight="bold")
    if w:
        axes[0].text(w[0], 0.98, " takeoff", transform=axes[0].get_xaxis_transform(),
                     color="w", fontsize=7.5, va="top")
    axes[0].set_title("Gyro spectrogram - vibration energy vs time")
    axes[-1].set_xlabel("time [s]")
    fig.colorbar(mesh, ax=list(axes), label="PSD [dB, (rad/s)²/Hz]", pad=0.015,
                 aspect=40)
    return ("spectrogram", "Vibration spectrogram",
            "Gyro power spectral density over the whole log, one row per body axis. "
            "Horizontal bright lines are steady resonances; lines that sweep up and down "
            "with throttle are prop/motor order (rpm-driven) and are the ones a notch or "
            "dynamic notch should track. Broadband brightening after a point in time "
            "usually means something came loose. Energy above the gyro LPF line is what "
            "the filter is already removing.",
            *_render(fig))


# --------------------------------------------------------------------------- #
def fig_hover_thrust(log, spec):
    """PX4's online hover-thrust estimate with its 1-sigma band vs MPC_THR_HOVER."""
    hte = log.get("hover_thrust_estimate")
    if hte is None:
        return None
    t, ht = log.t(hte), hte["hover_thrust"].astype(float)
    var = hte["hover_thrust_var"].astype(float)
    ok = (hte["valid"] == 1) & np.isfinite(ht)
    if ok.sum() < 10:
        return None
    sd = np.sqrt(np.clip(var, 0, None))
    cfg = float(log.param("MPC_THR_HOVER", 0.5))
    med = float(np.nanmedian(ht[ok]))
    fig, ax = plt.subplots(figsize=(9, 3.6))
    _shade_modes(ax, log.mode_spans(), label=True)
    ax.fill_between(t, ht - sd, ht + sd, color=C["blue"], alpha=0.18, lw=0,
                    label="+/- 1 sigma")
    ht_v = np.where(ok, ht, np.nan)     # break the line where the estimate is invalid
    ax.plot(t, ht_v, color=C["blue"], lw=1.6, label="PX4 hover-thrust estimate")
    ax.axhline(cfg, color=C["red"], ls="--", lw=1.4,
               label=f"MPC_THR_HOVER = {cfg:.2f}")
    ax.axhline(med, color=C["green"], ls=":", lw=1.4,
               label=f"median estimate = {med:.2f}")
    ax.annotate(f"{med - cfg:+.2f}", (t[-1], (med + cfg) / 2), ha="right", va="center",
                fontsize=9, fontweight="bold",
                color=C["green"] if abs(med - cfg) <= 0.05 else C["red"])
    _flight_markers(ax, log)
    lo = float(np.nanmin(ht[ok])); hi = float(np.nanmax(ht[ok]))
    pad = max(0.06, 0.25 * (hi - lo))
    ax.set_ylim(min(lo, cfg) - pad, max(hi, cfg) + pad)
    ax.set_xlabel("time [s]"); ax.set_ylabel("normalized thrust [0-1]")
    ax.set_title("Hover thrust: PX4 estimate vs MPC_THR_HOVER")
    ax.legend(fontsize=8, loc="lower right", ncol=2)
    return ("hoverthrust", "Hover thrust estimate",
            "PX4's own hover-thrust estimator (an accelerometer-driven Kalman filter) "
            "vs the configured MPC_THR_HOVER. The blue line is the estimate, the shaded "
            "band its 1-sigma uncertainty; gaps are samples the estimator marked invalid "
            "(ground contact, aggressive climbs, or modes where it does not run). "
            "The dashed red line should sit inside the band once the estimate settles - "
            "if it does not, the altitude controller is fighting a wrong feed-forward "
            "and MPC_THR_HOVER should be set to the median.",
            *_render(fig))


# --------------------------------------------------------------------------- #
# Trajectory figures. Local frame is NED; every plot puts east on the horizontal
# axis and up on the vertical one so the track reads like a map.
TRAJ_COLORS = dict(act=C["blue"], sp=C["red"], start="#1e8449", end="#c0392b")
MAP_COLORS = dict(act="#00e5ff", sp="#ffd000", start="#39ff88", end="#ff4d4d")


def _ds_path(arrs, n=4000):
    """Stride-downsample a path, keeping the final sample so the end marker is exact."""
    if len(arrs[0]) <= n:
        return arrs
    s = len(arrs[0]) // n + 1
    return tuple(np.append(a[::s], a[-1]) for a in arrs)


def _traj_pair(tr, keys=("e", "n")):
    """Actual and (joint-finite) setpoint arrays for the given axes."""
    act = _ds_path(tuple(tr[k] for k in keys))
    sp = tr.get("sp")
    if not sp or any(sp.get(k) is None for k in keys):
        return act, None
    m = np.ones(len(sp["t"]), dtype=bool)
    for k in keys:
        m &= np.isfinite(sp[k])
    if m.sum() < 10:
        return act, None
    return act, _ds_path(tuple(sp[k][m] for k in keys))


def _traj_endpoints(ax, e, n, colors, z=None):
    kw = dict(zorder=6, edgecolor="white", linewidths=1.2)
    pts = [(e[0], n[0], colors["start"], "o", "start"),
           (e[-1], n[-1], colors["end"], "s", "end")]
    for x, y, c, mk, lbl in pts:
        args = (x, y) if z is None else (x, y, z[0] if lbl == "start" else z[-1])
        ax.scatter(*args, s=55, marker=mk, color=c, label=lbl, **kw)


def _scalebar(ax, extent, color="white"):
    """A round-number metre bar in the corner - satellite crops have no gridlines."""
    span = extent[1] - extent[0]
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        bar = step
        if step >= 0.18 * span:
            break
    x0 = extent[0] + 0.06 * span
    y0 = extent[2] + 0.07 * (extent[3] - extent[2])
    ax.plot([x0, x0 + bar], [y0, y0], color=color, lw=3, solid_capstyle="butt", zorder=7)
    ax.text(x0 + bar / 2, y0 + 0.015 * span, f"{bar:g} m", color=color, fontsize=8,
            ha="center", va="bottom", fontweight="bold", zorder=7)


TRAJ_XY_CAPTION = (
    "Top-down (plan) view of the flight in the EKF's local NED frame, east right and "
    "north up, drawn to equal scale so distances and shapes are undistorted. The origin "
    "is the local-position reference the estimator set at initialisation. The dashed red "
    "line is the commanded position; it breaks wherever the active flight mode was not "
    "controlling horizontal position (manual, altitude or pure velocity control), which "
    "is why a stick-flown segment shows the blue track alone. See docs/08_trajectory.md.")


def fig_traj_xy(log, spec):
    from .trajectory import trajectory
    tr = trajectory(log)
    if tr is None:
        return None
    (e, n), sp = _traj_pair(tr)
    fig, ax = plt.subplots(figsize=(7.0, 6.4))
    ax.plot(e, n, color=TRAJ_COLORS["act"], lw=2.2, label="actual", zorder=4)
    if sp is not None:
        ax.plot(sp[0], sp[1], color=TRAJ_COLORS["sp"], lw=1.3, ls="--", alpha=0.95,
                label="setpoint", zorder=5)
    _traj_endpoints(ax, e, n, TRAJ_COLORS)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("east [m]"); ax.set_ylabel("north [m]")
    ax.set_title("Trajectory - plan view (local NED)")
    ax.annotate("N", (0.965, 0.90), xycoords="axes fraction", ha="center", fontsize=9,
                fontweight="bold", color=C["grey"],
                xytext=(0.965, 0.78), textcoords="axes fraction",
                arrowprops=dict(arrowstyle="->", color=C["grey"], lw=1.2))
    ax.legend(fontsize=8, loc="best")
    return ("trajxy", "Trajectory - plan view", TRAJ_XY_CAPTION, *_render(fig))


TRAJ_3D_CAPTION = (
    "The same flight in three dimensions (east, north, altitude above the local origin). "
    "The grey curve on the floor is the track's ground projection, so vertical excursions "
    "can be told apart from horizontal ones. The dashed red path is the commanded "
    "position and appears only over the stretches where the controller was tracking "
    "position on all three axes. See docs/08_trajectory.md.")


def fig_traj_3d(log, spec):
    from .trajectory import trajectory
    tr = trajectory(log)
    if tr is None:
        return None
    (e, n, u), sp = _traj_pair(tr, ("e", "n", "u"))
    fig = plt.figure(figsize=(7.6, 6.2))
    ax = fig.add_subplot(111, projection="3d")
    floor = float(np.min(u)) - 0.08 * (float(np.ptp(u)) or 1.0)
    ax.plot(e, n, np.full_like(u, floor), color=C["grey"], lw=1.0, alpha=0.5,
            label="ground track")
    ax.plot(e, n, u, color=TRAJ_COLORS["act"], lw=2.2, label="actual")
    if sp is not None:
        ax.plot(sp[0], sp[1], sp[2], color=TRAJ_COLORS["sp"], lw=1.3, ls="--",
                alpha=0.95, label="setpoint")
    _traj_endpoints(ax, e, n, TRAJ_COLORS, z=u)
    ax.set_xlabel("east [m]"); ax.set_ylabel("north [m]"); ax.set_zlabel("up [m]")
    ax.set_title("Trajectory - 3D (local NED)")
    # equal horizontal scale; altitude keeps its own so a low hover is still readable
    ce, cn = (e.max() + e.min()) / 2, (n.max() + n.min()) / 2
    half = max(float(np.ptp(e)), float(np.ptp(n)), 1.0) / 2 * 1.1
    ax.set_xlim(ce - half, ce + half); ax.set_ylim(cn - half, cn + half)
    ax.set_zlim(floor, float(np.max(u)) + 0.08 * (float(np.ptp(u)) or 1.0))
    ax.view_init(elev=24, azim=-58)
    ax.legend(fontsize=8, loc="upper left")
    return ("traj3d", "Trajectory - 3D", TRAJ_3D_CAPTION, *_render(fig))


TRAJ_MAP_CAPTION = (
    "The track georeferenced onto a satellite crop of the flight area. The local NED "
    "origin is converted to WGS-84 using the estimator's reference latitude/longitude, "
    "so this is only as accurate as the GNSS fix and the EKF's global alignment - treat "
    "it as context, not as survey data. The crop is fetched from Esri's public World "
    "Imagery tiles at analysis time; the figure is omitted when the log has no global "
    "reference or the tile server cannot be reached "
    "(set PX4DOCTOR_NO_NETWORK=1 to skip the fetch). See docs/08_trajectory.md.")


def fig_traj_map(log, spec):
    from .trajectory import trajectory, satellite_basemap
    tr = trajectory(log)
    if tr is None:
        return None
    bm = satellite_basemap(tr["lat0"], tr["lon0"], tr["n"], tr["e"])
    if bm is None:
        return None
    import matplotlib.image as mpimg
    img = mpimg.imread(io.BytesIO(bm["png"]), format="png")
    (e, n), sp = _traj_pair(tr)
    fig, ax = plt.subplots(figsize=(7.0, 6.6))
    ax.imshow(img, extent=bm["extent"], origin="upper", interpolation="bilinear",
              zorder=0)
    ax.plot(e, n, color=MAP_COLORS["act"], lw=2.4, label="actual", zorder=4)
    if sp is not None:
        ax.plot(sp[0], sp[1], color=MAP_COLORS["sp"], lw=1.4, ls="--", alpha=0.95,
                label="setpoint", zorder=5)
    _traj_endpoints(ax, e, n, MAP_COLORS)
    ax.set_xlim(bm["extent"][0], bm["extent"][1])
    ax.set_ylim(bm["extent"][2], bm["extent"][3])
    ax.set_aspect("equal")
    ax.grid(False)
    _scalebar(ax, bm["extent"])
    lat, lon = tr["lat0"], tr["lon0"]
    ax.set_xlabel("east [m]"); ax.set_ylabel("north [m]")
    ax.set_title("Trajectory over satellite imagery")
    box = dict(facecolor="black", alpha=0.45, edgecolor="none", pad=1.8)
    ax.text(0.995, 0.008, f"{bm['attrib']}  ·  z{bm['zoom']}", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6.5, color="white", bbox=box, zorder=7)
    ax.text(0.005, 0.992, f"origin {lat:.6f}, {lon:.6f}", transform=ax.transAxes,
            ha="left", va="top", fontsize=7, color="white", bbox=box, zorder=7)
    leg = ax.legend(fontsize=8, loc="upper right", facecolor="black", framealpha=0.45)
    for txt in leg.get_texts():
        txt.set_color("white")
    return ("trajmap", "Trajectory on satellite map", TRAJ_MAP_CAPTION, *_render(fig))


TRAJ_COMP_CAPTION = (
    "Each position axis against time, commanded (dashed red) versus estimated (blue). "
    "Gaps in the setpoint are the stretches where that axis was not under position "
    "control. The RMS figure in each panel is the tracking error over the samples where "
    "a setpoint existed: a persistent offset points at a trim or estimator bias, a lag "
    "that grows with speed at an under-gained position loop (MPC_XY_P / MPC_Z_P), and "
    "overshoot after each step at too much velocity gain. See docs/08_trajectory.md.")

_NOTE_BOX = dict(facecolor="white", alpha=0.72, edgecolor="none", pad=1.5)
_TRAJ_AXES = (("n", "north [m]", "north"), ("e", "east [m]", "east"),
              ("u", "altitude [m]", "up"))


def fig_traj_components(log, spec):
    from .trajectory import trajectory, track_errors
    tr = trajectory(log)
    if tr is None:
        return None
    sp, errs = tr.get("sp"), track_errors(tr)
    modes, at = log.mode_spans(), _autotune_spans(log)
    fig, axes = plt.subplots(3, 1, figsize=(9, 7.2), sharex=True)
    for i, (key, ylab, name) in enumerate(_TRAJ_AXES):
        ax = axes[i]
        _shade_modes(ax, modes, label=(i == 0))
        _shade_autotune(ax, at)
        if sp and sp.get(key) is not None:
            ax.plot(*_ds(sp["t"], sp[key]), color=C["red"], lw=1.4, ls="--",
                    label="setpoint")
        ax.plot(*_ds(tr["t"], tr[key]), color=C["blue"], lw=1.3, label="actual")
        _flight_markers(ax, log)
        ax.set_ylabel(ylab)
        if key in errs:
            rms, cnt = errs[key]
            ax.annotate(f"RMS error {rms:.2f} m  ({cnt} samples)",
                        (0.995, 0.04), xycoords="axes fraction", ha="right",
                        fontsize=8, fontweight="bold", bbox=_NOTE_BOX,
                        color=C["green"] if rms < 0.5 else C["orange"])
        elif sp is None or sp.get(key) is None:
            ax.annotate(f"no {name} setpoint logged", (0.995, 0.04),
                        xycoords="axes fraction", ha="right", fontsize=8,
                        color=C["grey"], bbox=_NOTE_BOX)
        ax.legend(fontsize=8, loc="upper left", ncol=2)
    axes[0].set_title("Position setpoint vs actual, per axis")
    axes[-1].set_xlabel("time [s]")
    return ("trajcomp", "Position tracking per axis", TRAJ_COMP_CAPTION, *_render(fig))


ALL_FIGS = [fig_overview, fig_traj_xy, fig_traj_3d, fig_traj_map, fig_traj_components,
            fig_airframe, fig_motors, fig_rates, fig_raw_imu, fig_vibration,
            fig_accel_psd, fig_vibe_spectrogram, fig_autotune, fig_mag_power,
            fig_hover_thrust,
            fig_batt_ri]


def generate_all(log, spec):
    """Returns list of dicts: {id, title, caption, svg, png}."""
    out = []
    for fn in ALL_FIGS:
        try:
            r = fn(log, spec)
        except Exception:
            r = None
        if r:
            fid, title, caption, svg, png = r
            out.append(dict(id=fid, title=title, caption=caption, svg=svg, png=png))
    return out
