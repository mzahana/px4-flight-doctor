"""Interactive Plotly figure specs (plain dicts -> JSON), rendered client-side.

Each builder returns (id, title, caption, spec) where spec = {data, layout}.
Zoom/pan and per-trace toggling come free from Plotly's UI.
"""
import numpy as np

from .plots import _autotune_spans, MOTOR_COLORS, C


def _r(arr, nd=4):
    return [None if not np.isfinite(v) else round(float(v), nd) for v in arr]


def _ds(t, y, n=1600):
    if len(t) <= n:
        return t, y
    s = len(t) // n + 1
    return t[::s], y[::s]


def _tr(t, y, name, color, yaxis="y", xaxis="x", width=1.3, dash=None, visible=True):
    d = dict(type="scatter", mode="lines", x=_r(t, 2), y=_r(y), name=name,
             line=dict(color=color, width=width), yaxis=yaxis, xaxis=xaxis)
    if dash:
        d["line"]["dash"] = dash
    if not visible:
        d["visible"] = "legendonly"
    return d


def _span_shapes(spans):
    shapes, notes = [], []
    for t0, t1, lbl in spans:
        shapes.append(dict(type="rect", xref="x", yref="paper", x0=t0, x1=t1,
                           y0=0, y1=1, fillcolor=C["band"], opacity=0.15,
                           line=dict(width=0), layer="below"))
        notes.append(dict(x=(t0 + t1) / 2, y=1.0, xref="x", yref="paper",
                          text=f"<b>{lbl}</b>", showarrow=False, yanchor="bottom",
                          font=dict(size=10, color="#8a6d1a")))
    return shapes, notes


def _hline(y, color, text, yref="y", dash="dash"):
    shape = dict(type="line", xref="paper", yref=yref, x0=0, x1=1, y0=y, y1=y,
                 line=dict(color=color, width=1.2, dash=dash))
    note = dict(x=0.005, y=y, xref="paper", yref=yref, text=text, showarrow=False,
                xanchor="left", yanchor="bottom", font=dict(size=10, color=color))
    return shape, note


def _vline(x, color, text, dash="dot"):
    shape = dict(type="line", xref="x", yref="paper", x0=x, x1=x, y0=0, y1=1,
                 line=dict(color=color, width=1, dash=dash))
    note = dict(x=x, y=0.03, xref="x", yref="paper", text=text, showarrow=False,
                textangle=-90, xanchor="right", font=dict(size=9, color=color))
    return shape, note


def _layout(title, height=380, **axes):
    lay = dict(title=dict(text=title, font=dict(size=14)), height=height,
               margin=dict(l=55, r=20, t=45, b=40), hovermode="x unified",
               legend=dict(orientation="h", y=-0.12, font=dict(size=10)),
               dragmode="zoom", shapes=[], annotations=[])
    lay.update(axes)
    return lay


# --------------------------------------------------------------------------- #
def ip_overview(log, spec):
    lp, b = log.get("vehicle_local_position"), log.get("battery_status")
    if lp is None:
        return None
    t = log.t(lp)
    data = [_tr(*_ds(t, -lp["z"]), "altitude [m]", C["blue"])]
    lay = _layout("Flight overview", height=460,
                  xaxis=dict(title="time [s]", anchor="y2"),
                  yaxis=dict(title="altitude [m]", domain=[0.56, 1]),
                  yaxis2=dict(title="V / cell", domain=[0, 0.44], titlefont=dict(color=C["red"])),
                  yaxis3=dict(title="current [A]", overlaying="y2", side="right",
                              titlefont=dict(color=C["purple"]), showgrid=False))
    if b is not None:
        tb = log.t(b)
        cells = max(int(log.param("BAT1_N_CELLS", 4)), 1)
        vc = b["voltage_v"] / cells
        data.append(_tr(*_ds(tb, vc), "cell voltage [V]", C["red"], yaxis="y2"))
        data.append(_tr(*_ds(tb, b["current_a"]), "current [A]", C["purple"], yaxis="y3", width=1))
        s, n = _hline(3.5, C["red"], "3.5 V sag floor", yref="y2")
        lay["shapes"].append(s); lay["annotations"].append(n)
        i = int(np.argmin(vc))
        lay["annotations"].append(dict(x=float(tb[i]), y=float(vc[i]), xref="x", yref="y2",
                                       text=f"min {vc[i]:.2f} V/cell", showarrow=True,
                                       arrowcolor=C["red"], font=dict(size=10, color=C["red"]),
                                       ax=25, ay=20))
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh; lay["annotations"] += an
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            s, n = _vline(x, C["grey"], lbl)
            lay["shapes"].append(s); lay["annotations"].append(n)
    return ("overview", "Flight overview",
            "Altitude, battery cell voltage and pack current. Autotune phases shaded. "
            "Drag to zoom, double-click to reset, click legend entries to hide traces.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_motors(log, spec):
    am = log.get("actuator_motors")
    if am is None:
        return None
    t = log.t(am)
    n = sum(1 for i in range(12) if f"control[{i}]" in am and np.isfinite(am[f"control[{i}]"]).any())
    data = [_tr(*_ds(t, am[f"control[{i}]"]), f"motor {i}", MOTOR_COLORS[i % 4], width=1.1)
            for i in range(min(n, 8))]
    lay = _layout("Motor commands", height=400,
                  xaxis=dict(title="time [s]"),
                  yaxis=dict(title="normalized command", range=[0, 1.12]))
    s0, n0 = _hline(1.0, C["red"], "saturation limit")
    s1, n1 = _hline(0.5, C["green"], "ideal hover ~0.5", dash="dot")
    lay["shapes"] += [s0, s1]; lay["annotations"] += [n0, n1]
    w = log.in_air_window()
    if w:
        m = (t > w[0]) & (t < w[1])
        hov = float(np.mean(np.stack([am[f"control[{i}]"][m] for i in range(n)])))
        s2, n2 = _hline(round(hov, 3), C["grey"], f"flight mean {hov:.2f}", dash="dashdot")
        lay["shapes"].append(s2); lay["annotations"].append(n2)
        # ceiling-hit annotation
        from .propulsion import motor_output_channels
        mo = motor_output_channels(log)
        if mo and min(r[1] for r in mo[2]) < 1950:
            hi = min(r[1] for r in mo[2])
            hits = np.max(np.stack([am[f"control[{i}]"][m] for i in range(n)]), 0) >= 0.999
            if hits.any():
                th = float(t[m][hits][0])
                lay["annotations"].append(dict(
                    x=th, y=1.0, xref="x", yref="y",
                    text=f"<b>hit configured ceiling (PWM max {hi:.0f})</b>",
                    showarrow=True, arrowcolor=C["red"], ax=40, ay=35,
                    font=dict(size=10, color=C["red"])))
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh; lay["annotations"] += an
    return ("motors", "Motor commands",
            "Per-motor normalized thrust. The gap between the flight mean and the "
            "saturation limit is your control headroom. Click a legend entry to isolate motors.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_rates(log, spec):
    av, rs = log.get("vehicle_angular_velocity"), log.get("vehicle_rates_setpoint")
    if av is None or rs is None:
        return None
    ta, tr_ = log.t(av), log.t(rs)
    doms = [[0.70, 1.0], [0.35, 0.65], [0.0, 0.30]]
    data, axes = [], {}
    for i, name in enumerate(("roll", "pitch", "yaw")):
        ya = "y" if i == 0 else f"y{i+1}"
        data.append(_tr(*_ds(tr_, np.degrees(rs[name])), f"{name} setpoint", C["grey"],
                        yaxis=ya, width=1.0, dash="dot"))
        data.append(_tr(*_ds(ta, np.degrees(av[f"xyz[{i}]"])), f"{name} actual",
                        MOTOR_COLORS[i], yaxis=ya, width=1.0))
        axes["yaxis" if i == 0 else f"yaxis{i+1}"] = dict(
            title=f"{name} [deg/s]", domain=doms[i])
    lay = _layout("Rate tracking: setpoint vs actual", height=560,
                  xaxis=dict(title="time [s]", anchor="y3"), **axes)
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh; lay["annotations"] += an
    return ("rates", "Rate tracking",
            "Measured body rates vs controller setpoints, per axis. In the shaded autotune "
            "bands the actual should follow the square wave crisply; lag or overshoot there "
            "is exactly what the identifier fits.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_vibration(log, spec):
    sc = log.get("sensor_combined")
    w = log.in_air_window()
    if sc is None or w is None:
        return None
    t = log.t(sc)
    m = (t > w[0] + 2) & (t < w[1] - 1)
    if m.sum() < 512:
        return None
    dt = float(np.median(np.diff(t[m])))
    nyq = 0.5 / dt
    data, lay_extra = [], {}
    peaks = {}
    for k, (src, xa, ya, unit) in enumerate((("accelerometer_m_s2", "x", "y", "m/s²"),
                                             ("gyro_rad", "x2", "y2", "rad/s"))):
        best = (0, 0)
        for i, lbl in enumerate("xyz"):
            x = sc[f"{src}[{i}]"][m].astype(float)
            x -= x.mean()
            fr = np.fft.rfftfreq(len(x), dt)
            P = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x) * 4
            sel = fr > 3
            frd, Pd = _ds(fr[sel], P[sel], 1200)
            nm = ("accel " if k == 0 else "gyro ") + lbl
            data.append(dict(type="scatter", mode="lines", x=_r(frd, 1), y=_r(Pd, 5),
                             name=nm, xaxis=xa, yaxis=ya,
                             line=dict(color=MOTOR_COLORS[i], width=1)))
            j = int(np.argmax(P[sel]))
            if P[sel][j] > best[1]:
                best = (float(fr[sel][j]), float(P[sel][j]))
        peaks[ya] = best
    lay = _layout("Vibration spectrum (in flight)", height=400,
                  xaxis=dict(title="frequency [Hz]", domain=[0, 0.46]),
                  yaxis=dict(title="accel amplitude [m/s²]"),
                  xaxis2=dict(title="frequency [Hz]", domain=[0.54, 1], anchor="y2"),
                  yaxis2=dict(title="gyro amplitude [rad/s]", anchor="x2"))
    lay["hovermode"] = "closest"
    for ya, xa in (("y", "x"), ("y2", "x2")):
        f0, v0 = peaks[ya]
        lay["annotations"].append(dict(x=f0, y=v0, xref=xa, yref=ya,
                                       text=f"<b>dominant {f0:.0f} Hz</b>", showarrow=True,
                                       arrowcolor=C["red"], ax=30, ay=-25,
                                       font=dict(size=10, color=C["red"])))
        lay["shapes"].append(dict(type="line", xref=xa, yref="paper", x0=nyq, x1=nyq,
                                  y0=0, y1=1, line=dict(color=C["grey"], width=1, dash="dash")))
    lay["annotations"].append(dict(x=nyq, y=0.97, xref="x", yref="paper", text="Nyquist",
                                   showarrow=False, xanchor="right", font=dict(size=9, color=C["grey"])))
    cutoff = log.param("IMU_GYRO_CUTOFF")
    if cutoff:
        lay["shapes"].append(dict(type="line", xref="x2", yref="paper", x0=cutoff, x1=cutoff,
                                  y0=0, y1=1, line=dict(color=C["green"], width=1, dash="dot")))
        lay["annotations"].append(dict(x=cutoff, y=0.90, xref="x2", yref="paper",
                                       text=f"gyro LPF {cutoff:.0f} Hz", showarrow=False,
                                       xanchor="left", font=dict(size=9, color=C["green"])))
    return ("vibration", "Vibration spectrum",
            "FFT of raw accel (left) and gyro (right) during flight. Put a notch on the "
            "dominant peak; energy near Nyquist aliases into the control band.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_autotune(log, spec):
    d = log.get("autotune_attitude_control_status")
    if d is None:
        return None
    t = log.t(d)
    cv = np.stack([d[f"coeff_var[{i}]"] for i in range(5)])
    worst = np.max(cv, axis=0)
    data = [_tr(*_ds(t, worst), "worst coeff variance", C["blue"])]
    data[-1]["yaxis"] = "y"
    data.append(_tr(*_ds(t, d["kc"]), "rate gain K", C["green"], yaxis="y2"))
    data.append(_tr(*_ds(t, d["kd"] * 10), "rate D ×10", C["purple"], yaxis="y2", width=1))
    data.append(_tr(*_ds(t, d["att_p"] / 10), "attitude P ÷10", C["orange"], yaxis="y2", width=1))
    lay = _layout("Autotune convergence", height=520,
                  xaxis=dict(title="time [s]", anchor="y2"),
                  yaxis=dict(title="coeff variance (log)", type="log", domain=[0.55, 1]),
                  yaxis2=dict(title="gain estimates", domain=[0, 0.45], rangemode="tozero"))
    s, n = _hline(50, C["red"], "convergence threshold (50)")
    lay["shapes"].append(s); lay["annotations"].append(n)
    spans = _autotune_spans(log)
    sh, an = _span_shapes(spans)
    lay["shapes"] += sh; lay["annotations"] += an
    for t0, t1, lbl in spans:
        t1 = float(t1)
        lay["shapes"].append(dict(type="line", xref="x", yref="paper", x0=t1, x1=t1,
                                  y0=0, y1=1, line=dict(color=C["grey"], width=1, dash="dot")))
        i = int(np.searchsorted(t, t1)) - 1
        if 0 <= i < len(worst):
            lay["annotations"].append(dict(x=float(t1), y=float(np.log10(max(float(worst[i]), 1e-3))),
                                           xref="x", yref="y", text=f"locked @ {float(worst[i]):.0f}",
                                           showarrow=True, ax=25, ay=-15,
                                           font=dict(size=9, color=C["blue"]),
                                           arrowcolor=C["blue"]))
    return ("autotune", "Autotune convergence",
            "Top: model uncertainty (gains lock the instant the worst variance crosses 50 "
            "after the 5 s minimum). Bottom: the gain estimates - flat before lock-in = "
            "trustworthy, still moving = snapshot of an unconverged fit.",
            dict(data=data, layout=lay))




# --------------------------------------------------------------------------- #
def ip_mag_power(log, spec):
    from .checks import _mag_power_data
    d = _mag_power_data(log)
    if d is None or "I" not in d:
        return None
    t, B, I = d["t"], d["B"] * 1000, d["I"]
    data = [
        _tr(*_ds(t, B), "|B| [mG]", C["blue"]),
        _tr(*_ds(t, I), "current [A]", C["purple"], yaxis="y2", width=1),
    ]
    td, Id = _ds(t, I, 900)
    _, Bd = _ds(t, B, 900)
    data.append(dict(type="scatter", mode="markers", x=_r(Id, 2), y=_r(Bd, 1),
                     name="|B| vs I (scatter)", xaxis="x2", yaxis="y3",
                     marker=dict(size=3, color=_r(td - td[0], 1), colorscale="Viridis",
                                 showscale=False), hovertext=[f"t={v:.0f}s" for v in td - td[0]]))
    p = np.polyfit(I, B, 1)
    r = float(np.corrcoef(B, I)[0, 1])
    xs = np.linspace(float(I.min()), float(I.max()), 15)
    data.append(dict(type="scatter", mode="lines", x=_r(xs, 2), y=_r(np.polyval(p, xs), 1),
                     name=f"fit {p[0]:+.2f} mG/A", xaxis="x2", yaxis="y3",
                     line=dict(color=C["red"], width=2)))
    lay = _layout("Magnetic field vs power draw", height=420,
                  xaxis=dict(title="time [s]", domain=[0, 0.58]),
                  yaxis=dict(title="|B| [mG]", titlefont=dict(color=C["blue"])),
                  yaxis2=dict(title="current [A]", overlaying="y", side="right",
                              titlefont=dict(color=C["purple"]), showgrid=False),
                  xaxis2=dict(title="current [A]", domain=[0.68, 1], anchor="y3"),
                  yaxis3=dict(title="|B| [mG]", anchor="x2"))
    lay["hovermode"] = "closest"
    lay["annotations"].append(dict(x=0.70, y=1.02, xref="paper", yref="paper",
                                   text=f"<b>corr = {r:+.2f}</b>", showarrow=False,
                                   font=dict(size=12, color=C["red"] if abs(r) > 0.5 else C["green"])))
    return ("magpower", "Magnetic field vs power",
            "Left: |B| and battery current over time. Right: |B| vs current scatter "
            "(colored by time) with linear fit - a strong slope means motor current is "
            "bending the compass. Corr > 0.5 with several % field change = interference.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_batt_ri(log, spec):
    b = log.get("battery_status")
    w = log.in_air_window()
    if b is None or w is None:
        return None
    t = log.t(b)
    m = (t > w[0]) & (t < w[1]) & np.isfinite(b["current_a"]) & (b["current_a"] > 0.5)
    if m.sum() < 30 or float(np.ptp(b["current_a"][m])) < 4:
        return None
    I, V, tt = b["current_a"][m], b["voltage_v"][m], t[m] - t[m][0]
    A = np.column_stack([np.ones_like(I), -I, -tt])
    coef, *_ = np.linalg.lstsq(A, V, rcond=None)
    cells = max(int(log.param("BAT1_N_CELLS", 4)), 1)
    data = [dict(type="scatter", mode="markers", x=_r(I, 2), y=_r(V, 3),
                 name="samples", marker=dict(size=4, color=_r(tt, 1),
                 colorscale="Viridis", colorbar=dict(title="t [s]", thickness=12)),
                 hovertext=[f"t={v:.0f}s" for v in tt])]
    xs = np.linspace(float(I.min()), float(I.max()), 15)
    mid = float(np.median(tt))
    data.append(dict(type="scatter", mode="lines", x=_r(xs, 2),
                     y=_r(coef[0] - coef[1] * xs - coef[2] * mid, 3),
                     name=f"fit: {coef[1]*1000:.1f} mΩ pack = {coef[1]/cells*1000:.1f} mΩ/cell",
                     line=dict(color=C["red"], width=2.5)))
    lay = _layout("Battery internal resistance (V-I scatter)", height=400,
                  xaxis=dict(title="current [A]"),
                  yaxis=dict(title="pack voltage [V]"))
    lay["hovermode"] = "closest"
    return ("battri", "Battery internal resistance",
            "Voltage vs current colored by time. The fit slope (slow SOC droop removed) is "
            "the pack resistance - set BAT1_R_INTERNAL to the per-cell value.",
            dict(data=data, layout=lay))

ALL_IPLOTS = [ip_overview, ip_motors, ip_rates, ip_vibration, ip_autotune,
              ip_mag_power, ip_batt_ri]


def generate_interactive(log, spec):
    out = []
    for fn in ALL_IPLOTS:
        try:
            r = fn(log, spec)
        except Exception:
            r = None
        if r:
            pid, title, caption, spec_ = r
            out.append(dict(id=pid, title=title, caption=caption, spec=spec_))
    return out
