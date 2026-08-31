"""Interactive Plotly figure specs (plain dicts -> JSON), rendered client-side.

Each builder returns (id, title, caption, spec) where spec = {data, layout}.
Zoom/pan and per-trace toggling come free from Plotly's UI.
"""
import numpy as np

from .plots import _autotune_spans, _spectrogram, mode_color, MOTOR_COLORS, C


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


def _mode_shapes(lay, log):
    """Tint the plot background by flight mode and label each window on top."""
    spans = log.mode_spans()
    if not spans:
        return
    total = float(spans[-1][1] - spans[0][0]) or 1.0
    row, prev_mid = 0, -1e18
    for t0, t1, name in spans:
        c = mode_color(name)
        lay["shapes"].append(dict(type="rect", xref="x", yref="paper", x0=t0, x1=t1,
                                  y0=0, y1=1, fillcolor=c, opacity=0.08,
                                  line=dict(width=0), layer="below"))
        lay["shapes"].append(dict(type="line", xref="x", yref="paper", x0=t0, x1=t0,
                                  y0=0, y1=1, line=dict(color=c, width=1),
                                  opacity=0.45, layer="below"))
        # drop labels for slivers and stagger the rest over two rows, so a
        # mode-hopping flight does not produce a row of overlapping names
        need = 0.011 * total * max(len(name), 4)
        if (t1 - t0) < min(need, 0.05 * total):
            continue
        mid = (t0 + t1) / 2
        row = 0 if mid - prev_mid > 0.10 * total else 1 - row
        lay["annotations"].append(dict(x=mid, y=1.03 + 0.045 * row, xref="x", yref="paper",
                                       text=f"<b>{name}</b>", showarrow=False,
                                       yanchor="bottom", font=dict(size=10, color=c)))
        prev_mid = mid
    lay["margin"]["t"] = max(lay["margin"].get("t", 45), 86)


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
    _mode_shapes(lay, log)
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh; lay["annotations"] += an
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            s, n = _vline(x, C["grey"], lbl)
            lay["shapes"].append(s); lay["annotations"].append(n)
    return ("overview", "Flight overview",
            "Altitude, battery cell voltage and pack current. Flight-mode windows are "
            "tinted (mode name on top), autotune phases shaded amber. "
            "Drag to zoom, double-click to reset, click legend entries to hide traces.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_airframe(log, spec):
    from .plots import _airframe_data, _cg_words, AIRFRAME_CAPTION
    d = _airframe_data(log)
    if d is None:
        return None
    pos, km, arms, means, cg = d["pos"], d["km"], d["arms"], d["means"], d["cg"]
    r_disc = 0.38 * float(arms[arms > 0.01].min())
    lim = float(arms.max()) + 2.1 * r_disc
    shapes, notes, data = [], [], []
    for (fx, ry) in pos:
        shapes.append(dict(type="line", xref="x", yref="y", x0=0, y0=0,
                           x1=float(ry), y1=float(fx), layer="below",
                           line=dict(color=C["grey"], width=3), opacity=0.4))
    for grp, name, col in ((km > 0, "CCW ↺", C["blue"]), (km < 0, "CW ↻", C["orange"])):
        idx = [i for i in range(len(km)) if grp[i]]
        if not idx:
            continue
        for i in idx:
            fx, ry = map(float, pos[i])
            shapes.append(dict(type="circle", xref="x", yref="y",
                               x0=ry - r_disc, x1=ry + r_disc,
                               y0=fx - r_disc, y1=fx + r_disc, layer="below",
                               fillcolor=col, opacity=0.14, line=dict(width=0)))
            shapes.append(dict(type="circle", xref="x", yref="y",
                               x0=ry - r_disc, x1=ry + r_disc,
                               y0=fx - r_disc, y1=fx + r_disc,
                               line=dict(color=col, width=1.6)))
        hover = [f"M{i} · {name}<br>fwd {pos[i][0]:+.3f} m, right {pos[i][1]:+.3f} m"
                 + (f"<br>hover mean cmd {means[i]:.3f} "
                    f"({means[i]/means.sum()*100:.1f}% of total)" if means is not None else "")
                 for i in idx]
        data.append(dict(type="scatter", mode="markers+text", name=name,
                         x=[float(pos[i][1]) for i in idx],
                         y=[float(pos[i][0]) for i in idx],
                         text=[f"<b>M{i} {'CCW ↺' if km[i] > 0 else 'CW ↻'}</b>"
                               + (f"<br>{means[i]:.3f}" if means is not None else "")
                               for i in idx],
                         textposition="top center", textfont=dict(size=10, color=col),
                         marker=dict(size=9, color=col),
                         hovertext=hover, hoverinfo="text"))
    data.append(dict(type="scatter", mode="markers", name="geometric center",
                     x=[0], y=[0], marker=dict(size=11, color=C["grey"],
                                               symbol="cross-thin",
                                               line=dict(color=C["grey"], width=2)),
                     hovertext=["geometric rotor center"], hoverinfo="text"))
    labeled = set()
    for i in range(len(arms)):
        rkey = round(float(arms[i]), 2)
        if rkey in labeled or arms[i] < 0.01:
            continue
        labeled.add(rkey)
        notes.append(dict(x=0.55 * float(pos[i][1]), y=0.55 * float(pos[i][0]),
                          xref="x", yref="y", text=f"{arms[i]:.2f} m",
                          showarrow=False, font=dict(size=9, color=C["grey"]),
                          bgcolor="rgba(255,255,255,0.7)"))
    notes.append(dict(x=0, y=0.85 * lim, xref="x", yref="y", ax=0, ay=45,
                      text="forward", showarrow=True, arrowcolor=C["grey"],
                      font=dict(size=9, color=C["grey"])))
    span = float(max(np.hypot(*(p - q)) for p in pos for q in pos))
    foot = f"max motor-to-motor span {span:.2f} m"
    if cg is not None:
        dx, dy = cg
        dist = float(np.hypot(dx, dy))
        data.append(dict(type="scatter", mode="markers", name="estimated CG",
                         x=[dy], y=[dx], marker=dict(size=10, color=C["red"]),
                         hovertext=[f"estimated CG<br>{dist*100:.1f} cm "
                                    f"{_cg_words(dx, dy, dist)} of center"],
                         hoverinfo="text"))
        notes.append(dict(x=dy, y=dx, xref="x", yref="y",
                          text=f"<b>est. CG {dist*100:.1f} cm {_cg_words(dx, dy, dist)}</b>",
                          showarrow=True, arrowcolor=C["red"], ax=45, ay=40,
                          font=dict(size=10, color=C["red"])))
    else:
        foot += "  ·  no quasi-static hover in log - CG not estimated"
    notes.append(dict(x=0.98, y=0.02, xref="paper", yref="paper", xanchor="right",
                      text=foot, showarrow=False, font=dict(size=9, color=C["grey"])))
    lay = _layout("Airframe layout (top view)", height=560,
                  xaxis=dict(title="right [m]", range=[-lim, lim], zeroline=False,
                             constrain="domain"),
                  yaxis=dict(title="forward [m]", range=[-lim, lim], zeroline=False,
                             scaleanchor="x", scaleratio=1))
    lay["hovermode"] = "closest"
    lay["shapes"] = shapes
    lay["annotations"] = notes
    return ("airframe", "Airframe layout", AIRFRAME_CAPTION, dict(data=data, layout=lay))


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
    _mode_shapes(lay, log)
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
    _mode_shapes(lay, log)
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh; lay["annotations"] += an
    return ("rates", "Rate tracking",
            "Measured body rates vs controller setpoints, per axis. In the shaded autotune "
            "bands the actual should follow the square wave crisply; lag or overshoot there "
            "is exactly what the identifier fits.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_raw_imu(log, spec):
    """Raw accelerometer and gyro time series, all three axes."""
    sc = log.get("sensor_combined")
    if sc is None:
        return None
    t = log.t(sc)
    if len(t) < 100:
        return None
    data = []
    for src, ya, pre in (("accelerometer_m_s2", "y", "accel"), ("gyro_rad", "y2", "gyro")):
        for i, lbl in enumerate("xyz"):
            td, yd = _ds(t, sc[f"{src}[{i}]"].astype(float), 3000)
            data.append(_tr(td, yd, f"{pre} {lbl}", MOTOR_COLORS[i], yaxis=ya, width=0.8))
    lay = _layout("Raw IMU: accelerometer and gyro", height=560,
                  xaxis=dict(title="time [s]", anchor="y2"),
                  yaxis=dict(title="accel [m/s²]", domain=[0.55, 1]),
                  yaxis2=dict(title="gyro [rad/s]", domain=[0, 0.45]))
    _mode_shapes(lay, log)
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh; lay["annotations"] += an
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            s_, a_ = _vline(float(x), C["grey"], lbl)
            lay["shapes"].append(s_); lay["annotations"].append(a_)
    return ("rawimu", "Raw IMU signals",
            "Unfiltered accelerometer and gyro straight off the sensor (decimated for "
            "display). Band thickness is vibration, steps are impacts or clipping, and a "
            "slow gyro drift at rest is bias. Zoom in to inspect a single event.",
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
    lay["legend"] = dict(orientation="h", y=-0.18, x=0.5, xanchor="center",
                         font=dict(size=10))
    lay["margin"]["b"] = 60
    for ya, xa in (("y", "x"), ("y2", "x2")):
        f0, v0 = peaks[ya]
        lay["annotations"].append(dict(x=f0, y=v0, xref=xa, yref=ya,
                                       text=f"<b>dominant {f0:.0f} Hz</b>", showarrow=True,
                                       arrowcolor=C["red"], ax=30, ay=-25,
                                       font=dict(size=10, color=C["red"])))
        lay["shapes"].append(dict(type="line", xref=xa, yref="paper", x0=nyq, x1=nyq,
                                  y0=0, y1=1, line=dict(color=C["grey"], width=1, dash="dash")))
    lay["annotations"].append(dict(x=nyq, y=0.02, xref="x", yref="paper", text="Nyquist",
                                   showarrow=False, textangle=-90, xanchor="right",
                                   yanchor="bottom", font=dict(size=9, color=C["grey"])))
    cutoff = log.param("IMU_GYRO_CUTOFF")
    if cutoff:
        lay["shapes"].append(dict(type="line", xref="x2", yref="paper", x0=cutoff, x1=cutoff,
                                  y0=0, y1=1, line=dict(color=C["green"], width=1, dash="dot")))
        lay["annotations"].append(dict(x=cutoff, y=0.02, xref="x2", yref="paper",
                                       text=f"gyro LPF {cutoff:.0f} Hz", showarrow=False,
                                       textangle=-90, xanchor="left", yanchor="bottom",
                                       font=dict(size=9, color=C["green"])))
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
    _mode_shapes(lay, log)
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
                  xaxis=dict(title="time [s]", domain=[0, 0.50]),
                  yaxis=dict(title="|B| [mG]", titlefont=dict(color=C["blue"])),
                  yaxis2=dict(title="current [A]", overlaying="y", side="right",
                              titlefont=dict(color=C["purple"]), showgrid=False),
                  xaxis2=dict(title="current [A]", domain=[0.70, 1], anchor="y3"),
                  yaxis3=dict(title="|B| [mG]", anchor="x2"))
    lay["hovermode"] = "closest"
    _mode_shapes(lay, log)
    lay["annotations"].append(dict(x=0.70, y=1.005, xref="paper", yref="paper",
                                   xanchor="left", yanchor="bottom",
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

# --------------------------------------------------------------------------- #
def ip_accel_psd(log, spec):
    """Flight-Review style 2D accel PSD: summed x+y+z power vs frequency vs time."""
    sc = log.get("sensor_combined")
    if sc is None:
        return None
    t = log.t(sc)
    if len(t) < 4096:
        return None
    acc = None
    for i in range(3):
        r = _spectrogram(t, sc[f"accelerometer_m_s2[{i}]"].astype(float), target_cols=200)
        if r is None:
            return None
        tt, fr, P = r
        acc = P if acc is None else acc + P
    sel = fr > 2
    db = 10 * np.log10(acc[sel] + 1e-12)
    data = [dict(type="heatmap", x=_r(tt, 1), y=_r(fr[sel], 1),
                 z=[[round(float(v), 1) for v in row] for row in db],
                 colorscale="Viridis", zmin=float(np.percentile(db, 40)),
                 zmax=float(np.percentile(db, 99.9)),
                 colorbar=dict(title="PSD<br>[dB]", thickness=12),
                 hovertemplate="t=%{x:.0f}s  %{y:.0f} Hz<br>%{z:.0f} dB<extra></extra>")]
    lay = _layout("Acceleration power spectral density", height=430,
                  xaxis=dict(title="time [s]"),
                  yaxis=dict(title="frequency [Hz]"))
    lay["hovermode"] = "closest"
    lay["showlegend"] = False
    cutoff = log.param("IMU_ACCEL_CUTOFF")
    if cutoff:
        lay["shapes"].append(dict(type="line", xref="paper", yref="y", x0=0, x1=1,
                                  y0=cutoff, y1=cutoff,
                                  line=dict(color="#ffffff", width=1, dash="dot")))
        lay["annotations"].append(dict(x=0.99, y=cutoff, xref="paper", yref="y",
                                       text=f"accel LPF {cutoff:.0f} Hz", showarrow=False,
                                       xanchor="right", yanchor="bottom",
                                       font=dict(size=9, color="#ffffff")))
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            sh, an = _vline(float(x), C["grey"], lbl)
            sh["line"]["color"] = "#ffffff"
            lay["shapes"].append(sh); lay["annotations"].append(an)
    return ("accelpsd", "Acceleration power spectral density",
            "Frequency response of the raw accelerometer over time, summed over x, y and "
            "z. Brighter (yellow) = more energy at that time and frequency. Horizontal "
            "lines are fixed resonances, bands drifting with throttle are motor/prop "
            "order, and broad yellow smears are what corrupts the EKF.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_vibe_spectrogram(log, spec):
    sc = log.get("sensor_combined")
    if sc is None:
        return None
    t = log.t(sc)
    if len(t) < 4096:
        return None
    data, axes = [], {}
    doms = [[0.70, 1.0], [0.35, 0.65], [0.0, 0.30]]
    lo, hi = None, None
    for i, name in enumerate(("roll", "pitch", "yaw")):
        r = _spectrogram(t, sc[f"gyro_rad[{i}]"].astype(float), target_cols=160)
        if r is None:
            return None
        tt, fr, P = r
        sel = fr > 2
        db = 10 * np.log10(P[sel] + 1e-12)
        if lo is None:                      # one shared color scale for all three
            lo, hi = float(np.percentile(db, 40)), float(np.percentile(db, 99.9))
        ya = "y" if i == 0 else f"y{i+1}"
        data.append(dict(type="heatmap", x=_r(tt, 1), y=_r(fr[sel], 1),
                         z=[[round(float(v), 1) for v in row] for row in db],
                         name=name, yaxis=ya, xaxis="x", colorscale="Magma",
                         zmin=lo, zmax=hi, showscale=(i == 0),
                         colorbar=dict(title="PSD<br>[dB]", thickness=12, len=1.0),
                         hovertemplate=(f"{name}<br>t=%{{x:.0f}}s  %{{y:.0f}} Hz"
                                        "<br>%{z:.0f} dB<extra></extra>")))
        axes["yaxis" if i == 0 else f"yaxis{i+1}"] = dict(
            title=f"{name} [Hz]", domain=doms[i])
    lay = _layout("Gyro spectrogram - vibration energy vs time", height=620,
                  xaxis=dict(title="time [s]", anchor="y3"), **axes)
    lay["hovermode"] = "closest"
    lay["showlegend"] = False
    cutoff = log.param("IMU_GYRO_CUTOFF")
    if cutoff:
        for ya in ("y", "y2", "y3"):
            lay["shapes"].append(dict(type="line", xref="paper", yref=ya, x0=0, x1=1,
                                      y0=cutoff, y1=cutoff,
                                      line=dict(color="#7fd3ff", width=1, dash="dot")))
        lay["annotations"].append(dict(x=0.99, y=cutoff, xref="paper", yref="y",
                                       text=f"gyro LPF {cutoff:.0f} Hz", showarrow=False,
                                       xanchor="right", yanchor="bottom",
                                       font=dict(size=9, color="#7fd3ff")))
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            lay["shapes"].append(dict(type="line", xref="x", yref="paper", x0=x, x1=x,
                                      y0=0, y1=1,
                                      line=dict(color="#ffffff", width=1, dash="dot")))
            lay["annotations"].append(dict(x=x, y=1.0, xref="x", yref="paper", text=lbl,
                                           showarrow=False, xanchor="left", yanchor="bottom",
                                           font=dict(size=9, color=C["grey"])))
    return ("spectrogram", "Vibration spectrogram",
            "Gyro power spectral density vs time, one panel per body axis. Horizontal "
            "bright lines are fixed-frequency resonances; lines that sweep with throttle "
            "are rpm-driven prop order - those are what a dynamic notch tracks. Broadband "
            "brightening partway through a flight usually means something came loose.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
def ip_hover_thrust(log, spec):
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
    ht_v = np.where(ok, ht, np.nan)     # break the line where the estimate is invalid
    data = [
        dict(type="scatter", mode="lines", x=_r(t, 2), y=_r(ht + sd), name="+1 sigma",
             line=dict(width=0), hoverinfo="skip", showlegend=False),
        dict(type="scatter", mode="lines", x=_r(t, 2), y=_r(ht - sd), name="+/- 1 sigma",
             line=dict(width=0), fill="tonexty", fillcolor="rgba(36,113,163,0.20)",
             hoverinfo="skip"),
        _tr(t, ht_v, "PX4 hover-thrust estimate", C["blue"], width=1.8),
    ]
    lay = _layout("Hover thrust: PX4 estimate vs MPC_THR_HOVER", height=380,
                  xaxis=dict(title="time [s]"),
                  yaxis=dict(title="normalized thrust [0-1]"))
    for y, col, txt in ((cfg, C["red"], f"MPC_THR_HOVER = {cfg:.2f}"),
                        (med, C["green"], f"median estimate = {med:.2f}")):
        sh, an = _hline(y, col, f"<b>{txt}</b>")
        lay["shapes"].append(sh); lay["annotations"].append(an)
    lo = float(np.nanmin(ht[ok])); hi = float(np.nanmax(ht[ok]))
    pad = max(0.06, 0.25 * (hi - lo))
    lay["yaxis"]["range"] = [min(lo, cfg) - pad, max(hi, cfg) + pad]
    _mode_shapes(lay, log)
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            sh, an = _vline(x, C["grey"], lbl)
            lay["shapes"].append(sh); lay["annotations"].append(an)
    return ("hoverthrust", "Hover thrust estimate",
            f"PX4's accelerometer-driven hover-thrust estimator (blue, with its 1-sigma "
            f"band) against the configured MPC_THR_HOVER. Line gaps are samples the "
            f"estimator marked invalid. Median {med:.2f} vs configured {cfg:.2f} "
            f"({med - cfg:+.2f}) - if the red line sits outside the band once the "
            f"estimate settles, set MPC_THR_HOVER to the median.",
            dict(data=data, layout=lay))


# --------------------------------------------------------------------------- #
# Trajectory figures (see plots.py for the matplotlib twins and the captions).
def _traj_traces(tr, keys, colors, dims=2):
    """Actual + setpoint traces for a spatial plot, actual drawn first (underneath)."""
    from .plots import _ds_path, _traj_pair
    act, sp = _traj_pair(tr, keys)
    kind = "scatter3d" if dims == 3 else "scatter"
    axis = dict(zip("xyz", act))

    def pt(a, i, name, color, symbol):
        d = dict(type=kind, mode="markers", name=name, hoverinfo="text",
                 hovertext=[name],
                 marker=dict(size=11 if dims == 2 else 6, color=color,
                             symbol=symbol,
                             line=dict(color="white", width=1.5)))
        for k, arr in zip("xyz", a):
            d[k] = [round(float(arr[i]), 3)]
        return d

    traces = [dict(type=kind, mode="lines", name="actual",
                   line=dict(color=colors["act"], width=3.4 if dims == 2 else 5),
                   **{k: _r(v, 3) for k, v in axis.items()})]
    if sp is not None:
        traces.append(dict(type=kind, mode="lines", name="setpoint",
                           line=dict(color=colors["sp"], width=2 if dims == 2 else 3,
                                     dash="dash"),
                           **{k: _r(v, 3) for k, v in zip("xyz", sp)}))
    traces.append(pt(act, 0, "start", colors["start"],
                     "circle" if dims == 2 else "circle"))
    traces.append(pt(act, -1, "end", colors["end"],
                     "square" if dims == 2 else "square"))
    return traces


def ip_traj_xy(log, spec):
    from .plots import TRAJ_COLORS, TRAJ_XY_CAPTION
    from .trajectory import trajectory
    tr = trajectory(log)
    if tr is None:
        return None
    lay = _layout("Trajectory - plan view (local NED)", height=560,
                  xaxis=dict(title="east [m]", constrain="domain"),
                  yaxis=dict(title="north [m]", scaleanchor="x", scaleratio=1))
    lay["hovermode"] = "closest"
    return ("trajxy", "Trajectory - plan view",
            TRAJ_XY_CAPTION + " Drag to zoom, double-click to reset.",
            dict(data=_traj_traces(tr, ("e", "n"), TRAJ_COLORS), layout=lay))


def ip_traj_3d(log, spec):
    from .plots import TRAJ_COLORS, TRAJ_3D_CAPTION
    from .trajectory import trajectory
    tr = trajectory(log)
    if tr is None:
        return None
    data = _traj_traces(tr, ("e", "n", "u"), TRAJ_COLORS, dims=3)
    e, n, u = tr["e"], tr["n"], tr["u"]
    floor = float(np.min(u)) - 0.08 * (float(np.ptp(u)) or 1.0)
    data.insert(0, dict(type="scatter3d", mode="lines", name="ground track",
                        x=_r(e, 3), y=_r(n, 3),
                        z=[round(floor, 3)] * len(e),
                        line=dict(color=C["grey"], width=2), opacity=0.55,
                        hoverinfo="skip"))
    span = max(float(np.ptp(e)), float(np.ptp(n)), 1.0)
    lay = _layout("Trajectory - 3D (local NED)", height=620)
    lay.pop("hovermode", None)
    lay["margin"] = dict(l=0, r=0, t=45, b=0)
    lay["scene"] = dict(
        xaxis=dict(title="east [m]", range=[(e.max() + e.min()) / 2 - span * 0.55,
                                            (e.max() + e.min()) / 2 + span * 0.55]),
        yaxis=dict(title="north [m]", range=[(n.max() + n.min()) / 2 - span * 0.55,
                                             (n.max() + n.min()) / 2 + span * 0.55]),
        zaxis=dict(title="up [m]"),
        aspectmode="manual", aspectratio=dict(x=1, y=1, z=0.7),
        camera=dict(eye=dict(x=1.5, y=-1.6, z=0.9)))
    return ("traj3d", "Trajectory - 3D",
            TRAJ_3D_CAPTION + " Drag to orbit, scroll to zoom.",
            dict(data=data, layout=lay))


def ip_traj_map(log, spec):
    import base64
    from .plots import MAP_COLORS, TRAJ_MAP_CAPTION
    from .trajectory import trajectory, satellite_basemap
    tr = trajectory(log)
    if tr is None:
        return None
    bm = satellite_basemap(tr["lat0"], tr["lon0"], tr["n"], tr["e"])
    if bm is None:
        return None
    e0, e1, n0, n1 = bm["extent"]
    lay = _layout("Trajectory over satellite imagery", height=620,
                  xaxis=dict(title="east [m]", range=[e0, e1], showgrid=False,
                             zeroline=False, constrain="domain"),
                  yaxis=dict(title="north [m]", range=[n0, n1], showgrid=False,
                             zeroline=False, scaleanchor="x", scaleratio=1))
    lay["hovermode"] = "closest"
    # the crop is embedded rather than tiled live, so the browser needs no network
    # and the web UI and the PDF show byte-identical imagery
    lay["images"] = [dict(source="data:image/png;base64," +
                          base64.b64encode(bm["png"]).decode(),
                          xref="x", yref="y", x=e0, y=n1, sizex=e1 - e0, sizey=n1 - n0,
                          xanchor="left", yanchor="top", sizing="stretch",
                          layer="below", opacity=1)]
    lay["annotations"].append(dict(
        x=1, y=0, xref="paper", yref="paper", xanchor="right", yanchor="bottom",
        text=f"{bm['attrib']} · z{bm['zoom']} · origin {tr['lat0']:.6f}, {tr['lon0']:.6f}",
        showarrow=False, font=dict(size=9, color="white"),
        bgcolor="rgba(0,0,0,0.45)"))
    lay["legend"] = dict(x=0.99, y=0.99, xanchor="right", yanchor="top",
                         bgcolor="rgba(0,0,0,0.45)", font=dict(size=11, color="white"))
    return ("trajmap", "Trajectory on satellite map",
            TRAJ_MAP_CAPTION, dict(data=_traj_traces(tr, ("e", "n"), MAP_COLORS),
                                   layout=lay))


def ip_traj_components(log, spec):
    from .plots import TRAJ_COMP_CAPTION, _TRAJ_AXES
    from .trajectory import trajectory, track_errors
    tr = trajectory(log)
    if tr is None:
        return None
    sp, errs = tr.get("sp"), track_errors(tr)
    doms = [[0.70, 1.0], [0.36, 0.64], [0.0, 0.28]]
    axes = {}
    data = []
    for i, (key, ylab, name) in enumerate(_TRAJ_AXES):
        ya = "y" if i == 0 else f"y{i + 1}"
        axes[f"yaxis{i + 1}" if i else "yaxis"] = dict(title=ylab, domain=doms[i])
        if sp and sp.get(key) is not None:
            data.append(_tr(*_ds(sp["t"], sp[key]), f"{name} setpoint", C["red"],
                            yaxis=ya, dash="dash"))
        data.append(_tr(*_ds(tr["t"], tr[key]), f"{name} actual", C["blue"], yaxis=ya))
    lay = _layout("Position setpoint vs actual, per axis", height=680,
                  xaxis=dict(title="time [s]", anchor="y3"), **axes)
    for i, (key, ylab, name) in enumerate(_TRAJ_AXES):
        if key in errs:
            rms, cnt = errs[key]
            txt = f"RMS error {rms:.2f} m ({cnt} samples)"
            col = C["green"] if rms < 0.5 else C["orange"]
        else:
            txt, col = f"no {name} setpoint logged", C["grey"]
        lay["annotations"].append(dict(x=1, y=doms[i][0], xref="paper", yref="paper",
                                       xanchor="right", yanchor="bottom",
                                       text=f"<b>{txt}</b>", showarrow=False,
                                       font=dict(size=11, color=col),
                                       bgcolor="rgba(255,255,255,0.72)"))
    _mode_shapes(lay, log)
    sh, an = _span_shapes(_autotune_spans(log))
    lay["shapes"] += sh
    lay["annotations"] += an
    w = log.in_air_window()
    if w:
        for x, lbl in ((w[0], "takeoff"), (w[1], "landing")):
            s_, n_ = _vline(x, C["grey"], lbl)
            lay["shapes"].append(s_)
            lay["annotations"].append(n_)
    return ("trajcomp", "Position tracking per axis", TRAJ_COMP_CAPTION,
            dict(data=data, layout=lay))


ALL_IPLOTS = [ip_overview, ip_traj_xy, ip_traj_3d, ip_traj_map, ip_traj_components,
              ip_airframe, ip_motors, ip_rates, ip_raw_imu, ip_vibration,
              ip_accel_psd, ip_vibe_spectrogram, ip_autotune, ip_mag_power,
              ip_hover_thrust,
              ip_batt_ri]


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
