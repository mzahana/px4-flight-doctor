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
        _shade_autotune(a2, spans)
    a2.set_xlabel("time [s]")
    return ("overview", "Flight overview",
            "Altitude with autotune phases shaded; battery cell voltage and pack current below.",
            *_render(fig))


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
    for i, (ax, name) in enumerate(zip(axes, ("roll", "pitch", "yaw"))):
        ax.plot(*_ds(tr, np.degrees(rs[name])), color=C["grey"], lw=0.9, label="setpoint")
        ax.plot(*_ds(ta, np.degrees(av[f"xyz[{i}]"])), color=MOTOR_COLORS[i], lw=0.9,
                alpha=0.85, label="actual")
        ax.set_ylabel(f"{name} [deg/s]")
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
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.4))
    for src, ax, unit in (("accelerometer_m_s2", a1, "m/s²"), ("gyro_rad", a2, "rad/s")):
        peak_f, peak_v = 0, 0
        for i, lbl in enumerate("xyz"):
            x = sc[f"{src}[{i}]"][m].astype(float)
            x -= x.mean()
            fr = np.fft.rfftfreq(len(x), dt)
            P = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x) * 4
            sel = fr > 3
            ax.plot(fr[sel], P[sel], lw=0.9, label=lbl, color=MOTOR_COLORS[i])
            j = np.argmax(P[sel])
            if P[sel][j] > peak_v:
                peak_v, peak_f = P[sel][j], fr[sel][j]
        ax.annotate(f"dominant {peak_f:.0f} Hz", (peak_f, peak_v),
                    xytext=(12, 4), textcoords="offset points", fontsize=8.5,
                    color=C["red"], fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=C["red"]))
        nyq = 0.5 / dt
        ax.axvline(nyq, color=C["grey"], ls="--", lw=0.9)
        ax.text(nyq, ax.get_ylim()[1] * 0.95, "Nyquist ", ha="right", fontsize=7.5, color=C["grey"])
        cutoff = log.param("IMU_GYRO_CUTOFF")
        if src.startswith("gyro") and cutoff:
            ax.axvline(cutoff, color=C["green"], ls=":", lw=0.9)
            ax.text(cutoff, ax.get_ylim()[1] * 0.85, f" LPF {cutoff:.0f} Hz",
                    fontsize=7.5, color=C["green"])
        ax.set_xlabel("frequency [Hz]")
        ax.set_ylabel(f"amplitude [{unit}]")
        ax.set_title("Accelerometer spectrum" if ax is a1 else "Gyro spectrum")
        ax.legend(fontsize=8)
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
    cv = np.stack([d[f"coeff_var[{i}]"] for i in range(5)])
    worst = np.max(cv, axis=0)
    a1.semilogy(*_ds(t, worst), color=C["blue"], lw=1.2, label="worst coefficient variance")
    a1.axhline(50, color=C["red"], ls="--", lw=1)
    a1.text(t[0], 50, " convergence threshold (50)", color=C["red"], fontsize=8, va="bottom")
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




# --------------------------------------------------------------------------- #
def fig_mag_power(log, spec):
    from .checks import _mag_power_data
    d = _mag_power_data(log)
    if d is None or "I" not in d:
        return None
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.4))
    t, B, I = d["t"], d["B"] * 1000, d["I"]   # B in mGauss
    a1.plot(*_ds(t, B), color=C["blue"], lw=1.1, label="|B| [mG]")
    a1.set_xlabel("time [s]"); a1.set_ylabel("|B| [mG]", color=C["blue"])
    a1.set_title("Magnetic field vs power draw")
    ax2 = a1.twinx()
    ax2.plot(*_ds(t, I), color=C["purple"], lw=1.0, alpha=0.8, label="current [A]")
    ax2.set_ylabel("current [A]", color=C["purple"]); ax2.grid(False)
    _shade_autotune(a1, _autotune_spans(log), y=0.1)
    r = float(np.corrcoef(B, I)[0, 1])
    p = np.polyfit(I, B, 1)
    a2.plot(I, B, ".", ms=2, color=C["grey"], alpha=0.4)
    xs = np.linspace(I.min(), I.max(), 20)
    a2.plot(xs, np.polyval(p, xs), color=C["red"], lw=1.6,
            label=f"fit {p[0]:+.2f} mG/A")
    a2.annotate(f"corr = {r:+.2f}", (0.05, 0.92), xycoords="axes fraction",
                fontsize=10, fontweight="bold",
                color=C["red"] if abs(r) > 0.5 else C["green"])
    a2.set_xlabel("battery current [A]"); a2.set_ylabel("|B| [mG]")
    a2.set_title("|B| vs current"); a2.legend(fontsize=8, loc="lower right")
    return ("magpower", "Magnetic field vs power",
            "Left: field magnitude and battery current over the flight. Right: the same "
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

ALL_FIGS = [fig_overview, fig_motors, fig_rates, fig_vibration, fig_autotune,
            fig_mag_power, fig_batt_ri]


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
