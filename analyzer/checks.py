"""All analysis checks. Each returns a list of Finding objects."""
import numpy as np

from .core import Finding, Severity, AUTOTUNE_STATES
from . import propulsion as prop

OK, INFO, WARN, CRIT = Severity.OK, Severity.INFO, Severity.WARNING, Severity.CRITICAL


# --------------------------------------------------------------------------- #
def check_flight_summary(log, spec, hover):
    f = []
    info = log.ulog.msg_info_dict
    w = log.in_air_window()
    dur = f"{w[1]-w[0]:.0f} s airborne" if w else "no takeoff detected"
    f.append(Finding(INFO, "Flight", f"{info.get('ver_hw','?')} | {dur}",
                     detail=f"SW: {info.get('ver_sw_branch','?')} {info.get('ver_sw','?')[:8]}  "
                            f"OS: {info.get('sys_os_name','?')}"))
    msgs = [m for m in log.ulog.logged_messages if m.log_level_str() in ("ERROR", "WARNING", "CRITICAL", "EMERGENCY")]
    for m in msgs[:10]:
        f.append(Finding(WARN, "Flight", f"log message [{m.log_level_str()}]: {m.message.strip()}"))
    return f


# --------------------------------------------------------------------------- #
def check_autotune(log, spec, hover):
    d = log.get("autotune_attitude_control_status")
    if d is None:
        return []
    f = []
    t, st = log.t(d), d["state"]
    # state transition list
    trans, prev = [], None
    for i in range(len(st)):
        if st[i] != prev:
            trans.append((t[i], int(st[i])))
            prev = st[i]
    seq = " -> ".join(AUTOTUNE_STATES.get(s, str(s)) for _, s in trans)
    ended = trans[-1][1] if trans else None
    if ended == 15 or any(s == 15 for _, s in trans):
        f.append(Finding(CRIT, "Autotune", "Autotune ended in FAIL state",
                         detail=f"sequence: {seq}", doc="05_autotune.md"))
    elif ended == 14:
        f.append(Finding(INFO, "Autotune", "Autotune ran to COMPLETE (gains were saved)",
                         detail=f"sequence: {seq}", doc="05_autotune.md"))
    # per-axis identification duration vs limits (5 s minimum, 20 s abort)
    for axis, code in (("roll", 3), ("pitch", 6), ("yaw", 9)):
        times = [tt for tt, s in trans if s == code]
        ends = [tt for tt, s in trans if s == code + 1]
        if times and ends:
            dt = ends[0] - times[0]
            sev = OK if dt < 8 else (WARN if dt < 15 else CRIT)
            note = "" if dt < 8 else " - slow convergence: excitation is being corrupted (saturation, vibration, wind)"
            f.append(Finding(sev, "Autotune", f"{axis} identification took {dt:.1f} s (min 5 s, abort at 20 s){note}",
                             doc="05_autotune.md"))
            # gains at end of that axis segment + estimate stability over last second
            m = (t >= times[0]) & (t < ends[0])
            if m.sum() > 5:
                kc, ki, kd, ap = d["kc"][m], d["ki"][m], d["kd"][m], d["att_p"][m]
                gains = dict(RATE_P=kc[-1], RATE_I=kc[-1]*ki[-1], RATE_D=kc[-1]*kd[-1], ATT_P=ap[-1])
                last = max(2, int(0.1 * m.sum()))
                drift = np.max(np.abs(kc[-last:] - kc[-1])) / max(abs(kc[-1]), 1e-6)
                gtxt = "  ".join(f"{k}={v:.4f}" for k, v in gains.items())
                sev2, extra = OK, ""
                if drift > 0.15:
                    sev2, extra = WARN, f" - estimate still moving {drift*100:.0f}% at hand-off: result unreliable"
                bad = (not (0 < gains["RATE_P"] < 0.5)) or gains["ATT_P"] > 8 or \
                      (gains["RATE_D"] == 0 and axis != "yaw")
                if gains["ATT_P"] > 8:
                    sev2, extra = CRIT, extra + f" - ATT_P {gains['ATT_P']:.1f} is far above typical (2-6): likely bad ID"
                f.append(Finding(sev2, "Autotune", f"{axis} identified gains{extra}",
                                 detail=gtxt, doc="05_autotune.md",
                                 fixes=[f"if {axis} feels twitchy/oscillatory, revert MC_{axis.upper()}RATE_* and MC_{axis.upper()}_P to previous values"] if sev2 >= WARN else []))
    return f


# --------------------------------------------------------------------------- #
def check_actuators(log, spec, hover):
    f = []
    am = log.get("actuator_motors")
    w = log.in_air_window()
    if am is None or w is None:
        return f
    t = log.t(am)
    m = (t > w[0]) & (t < w[1])
    n = sum(1 for i in range(12) if f"control[{i}]" in am and np.isfinite(am[f"control[{i}]"]).any())
    ctl = np.stack([am[f"control[{i}]"][m] for i in range(n)])
    hover_mean = float(np.mean(ctl))
    sat_frac = float(np.mean(np.max(ctl, axis=0) >= 0.999))
    sev = OK if hover_mean < 0.55 else (WARN if hover_mean < 0.68 else CRIT)
    f.append(Finding(sev, "Propulsion", f"Mean normalized motor command in flight: {hover_mean:.2f}",
                     detail="PX4 controls best with hover demand near 0.5; above ~0.65 the "
                            "upper control headroom shrinks and attitude authority degrades.",
                     doc="02_propulsion_math.md",
                     fixes=["reduce mass or increase thrust (props/motors/6S)"] if sev >= WARN else []))
    if sat_frac > 0:
        f.append(Finding(WARN if sat_frac < 0.02 else CRIT, "Propulsion",
                         f"Motor saturation: at least one motor at 100% for {sat_frac*100:.1f}% of flight",
                         detail="During saturation the controller cannot produce the commanded torque; "
                                "yaw is sacrificed first. System identification (autotune) run during "
                                "saturation produces invalid models.", doc="02_propulsion_math.md"))
    # per-motor imbalance
    means = ctl.mean(axis=1)
    if n == 4:
        cw, ccw = means[[0, 1]].mean(), means[[2, 3]].mean()
        rel = (cw - ccw) / means.mean()
        if abs(rel) > 0.04:
            f.append(Finding(WARN, "Propulsion",
                             f"Standing yaw torque bias: motors 0+1 avg {cw:.3f} vs 2+3 avg {ccw:.3f} ({rel*100:+.0f}%)",
                             detail="One spin-direction pair works harder to hold heading: motor mount "
                                    "twist, bent arm, or prop mismatch.",
                             fixes=["check motor mount squareness and arm straightness",
                                    "verify all props identical and undamaged"]))
        spread = (means.max() - means.min()) / means.mean()
        if spread > 0.08:
            f.append(Finding(WARN, "Propulsion",
                             f"Per-motor load spread {spread*100:.0f}% (min {means.min():.3f} / max {means.max():.3f})",
                             detail="Persistent spread indicates CG offset toward the hardest-working motor.",
                             fixes=["re-balance payload over geometric center"]))
    # PWM output ceiling check
    mo = prop.motor_output_channels(log)
    if mo:
        ao = log.get("actuator_outputs", mo[0])
        if ao is not None:
            ta = log.t(ao)
            ma = (ta > w[0]) & (ta < w[1])
            for c, (lo, hi) in zip(mo[1], mo[2]):
                peak = float(np.max(ao[f"output[{c}]"][ma]))
                if hi < 1950 and peak >= hi - 0.5:
                    f.append(Finding(CRIT, "Propulsion",
                                     f"Motor ch{c} hit the configured PWM ceiling {hi:.0f} us "
                                     f"(hardware allows 2000)",
                                     detail="The output range parameter is clipping available thrust. "
                                            "If the intent is to protect the prop/motor, cap collective "
                                            "thrust with MPC_THR_MAX instead - that preserves full "
                                            "per-motor authority for attitude control.",
                                     fixes=[f"set PWM max back to 2000 (re-check ESC calibration)",
                                            "use MPC_THR_MAX to limit total thrust if needed"],
                                     doc="02_propulsion_math.md"))
    return f


# --------------------------------------------------------------------------- #
def check_propulsion_model(log, spec, hover):
    """Bench-table reconciliation - only runs with user-provided specs."""
    f = []
    if spec is None or spec.mass_kg is None:
        f.append(Finding(INFO, "Propulsion", "No takeoff mass provided - thrust/weight analysis skipped",
                         fixes=["re-run with --mass or a vehicle.yaml for the full propulsion report"]))
        return f
    if not spec.has_bench:
        f.append(Finding(INFO, "Propulsion", "No motor bench table provided - "
                         "throttle prediction / THR_MDL_FAC fit skipped",
                         fixes=["add a motor_bench section to vehicle.yaml (thrust vs throttle from the motor datasheet)"]))
        return f

    kv, kr, rho, rho_src = prop.correction_factors(hover, spec)
    if kv is None or kr is None:
        f.append(Finding(WARN, "Propulsion", "Missing voltage or air-density data - bench reconciliation skipped"))
        return f
    k = kv * kr
    need_g, bench_eq, pred_thr = prop.predict_hover_throttle(spec, k)
    det = [f"required thrust: {need_g:.0f} g/motor ({spec.mass_kg:.2f} kg / {spec.n_motors} motors)",
           f"voltage factor (V/Vbench)^2 = ({hover['voltage']:.2f}/{spec.bench_voltage:.1f})^2 = {kv:.3f}",
           f"density factor rho/rho_SL = {rho:.3f}/1.225 = {kr:.3f}   [{rho_src}]",
           f"bench-equivalent thrust: {bench_eq:.0f} g -> predicted ESC throttle {pred_thr*100:.1f}%"]
    if "esc_throttle" in hover:
        obs = float(np.mean(hover["esc_throttle"]))
        delta = (obs - pred_thr) * 100
        det.append(f"observed hover ESC throttle: {obs*100:.1f}%  (delta {delta:+.1f} points)")
        sev = OK if abs(delta) < 5 else (WARN if abs(delta) < 10 else CRIT)
        verdict = ("propulsion matches the bench data - hardware is healthy" if sev == OK else
                   "propulsion under-performs the bench data - inspect props (wear, balance), "
                   "motor bearings, and verify the mass and bench numbers")
        f.append(Finding(sev, "Propulsion", f"Hover throttle vs bench model: {verdict}",
                         detail="\n".join(det), doc="02_propulsion_math.md"))
        ih = prop.current_at_throttle(spec, obs, kv)
        if ih is not None and "current" in hover:
            pred_i = ih * spec.n_motors
            f.append(Finding(INFO, "Propulsion",
                             f"Predicted hover current {pred_i:.1f} A vs measured {hover['current']:.1f} A"))
    # thrust-to-weight at actual conditions
    mo = prop.motor_output_channels(log)
    pwm_hi = min(r[1] for r in mo[2]) if mo else 2000
    for pmax, tag in ((pwm_hi, "configured"), (2000, "full range")):
        esc_max = (pmax - 1000.0) / 1000.0
        t_max = prop.thrust_at_throttle(spec, esc_max, k)
        tw = t_max * spec.n_motors / (spec.mass_kg * 1000.0)
        sev = OK if tw >= 1.7 else (WARN if tw >= 1.4 else CRIT)
        f.append(Finding(sev, "Propulsion",
                         f"Thrust/weight at flight conditions ({tag}, PWM max {pmax:.0f}): {tw:.2f}",
                         detail=f"max thrust {t_max:.0f} g/motor x {spec.n_motors} = {t_max*spec.n_motors/1000:.2f} kg "
                                f"vs {spec.mass_kg:.2f} kg AUW. Target >= 1.7 for tuning flights, >= 2.0 ideal.",
                         doc="02_propulsion_math.md"))
        if pmax == 2000 and pwm_hi >= 1950:
            break
    # THR_MDL_FAC fit
    lo = max(r[0] for r in mo[2]) if mo else 1000
    fit, rms = prop.fit_thr_mdl_fac(spec, lo, pwm_hi)
    cur = log.param("THR_MDL_FAC", 0.0)
    sev = OK if abs(fit - cur) < 0.15 else WARN
    f.append(Finding(sev, "Propulsion",
                     f"THR_MDL_FAC: set to {cur:.2f}, bench data fits {fit:.2f} (rms {rms:.3f})",
                     detail="PX4 maps command->thrust as f*s^2+(1-f)*s. A wrong f makes the "
                            "effective control gain vary with throttle, which corrupts tuning "
                            "and autotune system-ID.",
                     fixes=[f"param set THR_MDL_FAC {fit:.1f}",
                            "re-measure MPC_THR_HOVER after changing it"] if sev >= WARN else [],
                     doc="03_thrust_curve.md"))
    # per-motor thrust in grams
    if "esc_throttle" in hover and len(hover["esc_throttle"]) == spec.n_motors:
        g = prop.per_motor_thrust(spec, hover["esc_throttle"], k)
        f.append(Finding(INFO, "Propulsion",
                         "Per-motor hover thrust: " + "  ".join(f"m{i}={v:.0f}g" for i, v in enumerate(g)) +
                         f"  (sum {g.sum():.0f} g vs AUW {spec.mass_kg*1000:.0f} g)"))
    if spec.prop_thrust_limit_g:
        esc_max = (pwm_hi - 1000.0) / 1000.0
        t_max = prop.thrust_at_throttle(spec, esc_max, k)
        thr_b, T_b, _ = spec.bench_arrays()
        bench_max = float(np.interp(1.0, thr_b, T_b))
        if bench_max > spec.prop_thrust_limit_g * 1.05:
            f.append(Finding(INFO, "Propulsion",
                             f"Bench max thrust {bench_max:.0f} g exceeds prop rating "
                             f"{spec.prop_thrust_limit_g:.0f} g at full throttle (sea level)",
                             detail="If limiting is desired use MPC_THR_MAX, not the PWM output range."))
    return f


# --------------------------------------------------------------------------- #
def check_vibration(log, spec, hover):
    f = []
    # metrics per IMU
    for i in range(4):
        s = log.get("vehicle_imu_status", i)
        if s is None:
            continue
        vib = float(np.nanmax(s["accel_vibration_metric"]))
        clip = sum(int(s[f"accel_clipping[{a}]"][-1]) for a in range(3) if f"accel_clipping[{a}]" in s)
        sev = OK if vib < 5 else (WARN if vib < 10 else CRIT)
        msg = f"IMU{i} accel vibration metric peak {vib:.1f}" + (f", {clip} clipping events" if clip else "")
        if clip:
            sev = max(sev, WARN)
        f.append(Finding(sev, "Vibration", msg, doc="04_vibration_filters.md"))
    # FFT of raw gyro/accel
    sc = log.get("sensor_combined")
    w = log.in_air_window()
    if sc is not None and w:
        t = log.t(sc)
        m = (t > w[0] + 2) & (t < w[1] - 1)
        if m.sum() > 512:
            dt = float(np.median(np.diff(t[m])))
            peaks_txt = []
            worst = 0.0
            for ax in range(3):
                x = sc[f"accelerometer_m_s2[{ax}]"][m]
                worst = max(worst, float(np.std(x)))
                x = x - x.mean()
                fr = np.fft.rfftfreq(len(x), dt)
                P = np.abs(np.fft.rfft(x * np.hanning(len(x))))
                sel = fr > 12
                if sel.any():
                    fpk = fr[sel][np.argmax(P[sel])]
                    peaks_txt.append(f"{'xyz'[ax]}:{fpk:.0f}Hz")
            sev = OK if worst < 2 else (WARN if worst < 4 else CRIT)
            f.append(Finding(sev, "Vibration",
                             f"In-flight accel noise sigma up to {worst:.1f} m/s^2; dominant peaks {' '.join(peaks_txt)}",
                             detail=f"Sample rate {1/dt:.0f} Hz -> Nyquist {0.5/dt:.0f} Hz. Energy near "
                                    "Nyquist aliases into the control band.",
                             fixes=["balance props, soft-mount FC/payload",
                                    "enable notch filtering (below)"] if sev >= WARN else [],
                             doc="04_vibration_filters.md"))
            # notch filter configuration
            dnf = log.param("IMU_GYRO_DNF_EN", 0)
            nf0 = log.param("IMU_GYRO_NF0_FRQ", 0.0)
            if sev >= WARN and not dnf and not nf0:
                fpk_all = peaks_txt[0].split(":")[1].replace("Hz", "") if peaks_txt else "<peak-freq>"
                f.append(Finding(WARN, "Vibration",
                                 "Significant vibration but no gyro notch filter enabled",
                                 fixes=["param set IMU_GYRO_DNF_EN 1   # if ESC RPM feedback available",
                                        f"or static: param set IMU_GYRO_NF0_FRQ {fpk_all}  /  IMU_GYRO_NF0_BW 20"],
                                 doc="04_vibration_filters.md"))
    fd = log.get("failure_detector_status")
    if fd is not None and "imbalanced_prop_metric" in fd:
        v = float(np.nanmax(fd["imbalanced_prop_metric"]))
        if v > 5:
            f.append(Finding(WARN, "Vibration", f"Imbalanced-prop metric peaked at {v:.1f}",
                             fixes=["balance or replace propellers"], doc="04_vibration_filters.md"))
    return f


# --------------------------------------------------------------------------- #
def check_ekf(log, spec, hover):
    f = []
    ratios = {"hdg_test_ratio": "heading", "vel_test_ratio": "velocity",
              "pos_test_ratio": "position", "hgt_test_ratio": "height"}
    worst = {}
    for i in range(4):
        es = log.get("estimator_status", i)
        if es is None:
            continue
        for k, name in ratios.items():
            if k in es:
                v = float(np.nanmax(es[k]))
                worst[name] = max(worst.get(name, 0), v)
        for k, txt in (("filter_fault_flags", "filter fault"), ("timeout_flags", "timeout"),
                       ("gps_check_fail_flags", "GPS check failure")):
            if k in es and np.any(es[k]):
                f.append(Finding(WARN, "EKF", f"EKF{i}: {txt} flags set ({np.unique(es[k][es[k]!=0])})"))
    if worst:
        bad = {k: v for k, v in worst.items() if v > 0.5}
        txt = "  ".join(f"{k}={v:.2f}" for k, v in worst.items())
        if bad:
            f.append(Finding(WARN if max(bad.values()) < 1.0 else CRIT, "EKF",
                             f"Innovation test ratios elevated: {txt}",
                             detail="Ratio > 1.0 means measurements were rejected.",
                             doc="06_ekf_health.md"))
        else:
            f.append(Finding(OK, "EKF", f"Innovation test ratios healthy (max: {txt})", doc="06_ekf_health.md"))
    # in-flight resets
    es = log.get("estimator_status", 0)
    if es is not None and log.in_air_window():
        t = log.t(es)
        w = log.in_air_window()
        m = (t > w[0] + 2) & (t < w[1])
        for k, name in (("reset_count_quat", "attitude/yaw"), ("reset_count_pos_ne", "XY position"),
                        ("reset_count_vel_ne", "XY velocity")):
            if k in es and m.sum() > 2:
                n = int(es[k][m][-1]) - int(es[k][m][0])
                if n > 0:
                    f.append(Finding(WARN, "EKF", f"{n} in-flight {name} reset(s)",
                                     doc="06_ekf_health.md"))
    return f


# --------------------------------------------------------------------------- #
def check_gps(log, spec, hover):
    f = []
    gp = log.get("vehicle_gps_position")
    if gp is None:
        return f
    sats = int(gp["satellites_used"].min())
    fixes = np.unique(gp["fix_type"])
    eph = float(np.nanmax(gp["eph"]))
    sev = OK if (sats >= 12 and eph < 1.5 and fixes.min() >= 3) else \
        (WARN if sats >= 8 else CRIT)
    f.append(Finding(sev, "GPS", f"Min {sats} satellites, fix type {fixes.tolist()}, worst EPH {eph:.2f} m"))
    for k, name in (("jamming_state", "jamming"), ("spoofing_state", "spoofing")):
        if k in gp and np.any(gp[k] > 1):
            f.append(Finding(WARN, "GPS", f"GPS {name} indicator active (state {int(gp[k].max())})"))
    return f


# --------------------------------------------------------------------------- #
def check_battery(log, spec, hover):
    f = []
    b = log.get("battery_status")
    if b is None:
        return f
    cells = int(log.param("BAT1_N_CELLS", 0)) or (spec.battery_cells if spec else 0) or 1
    vmin = float(b["voltage_v"].min())
    vcell = vmin / cells
    sev = OK if vcell > 3.5 else (WARN if vcell > 3.3 else CRIT)
    f.append(Finding(sev, "Battery",
                     f"Minimum cell voltage under load {vcell:.2f} V ({vmin:.2f} V pack, {cells}S)"))
    if spec and spec.battery_capacity_mah:
        pc = log.param("BAT1_CAPACITY")
        if pc and abs(pc - spec.battery_capacity_mah) > 100:
            f.append(Finding(WARN, "Battery",
                             f"BAT1_CAPACITY = {pc:.0f} mAh but actual pack is {spec.battery_capacity_mah:.0f} mAh",
                             fixes=[f"param set BAT1_CAPACITY {spec.battery_capacity_mah:.0f}"]))
    if log.param("BAT1_R_INTERNAL", -1.0) < 0:
        f.append(Finding(INFO, "Battery",
                         "BAT1_R_INTERNAL disabled: state-of-charge is sag-based and pessimistic at high current",
                         fixes=["param set BAT1_R_INTERNAL 0.005   # or measure your pack"]))
    if hover.get("current") and spec and spec.battery_capacity_mah:
        mins = spec.battery_capacity_mah * 0.8 / 1000.0 / hover["current"] * 60.0
        f.append(Finding(INFO, "Battery",
                         f"Hover current {hover['current']:.1f} A -> ~{mins:.0f} min usable hover endurance (80% DoD)"))
    if not log.param("MC_BAT_SCALE_EN", 0):
        sag = float(b["voltage_v"].max() - vmin)
        if sag > 0.8:
            f.append(Finding(WARN, "Battery",
                             f"Pack sags {sag:.1f} V across the flight and MC_BAT_SCALE_EN=0: "
                             "effective rate gains drift ~10% as the pack drains",
                             fixes=["param set MC_BAT_SCALE_EN 1"], doc="03_thrust_curve.md"))
    return f


# --------------------------------------------------------------------------- #
def check_mag(log, spec, hover):
    f = []
    es = log.get("estimator_status", 0)
    if es is None or "mag_strength_gs" not in es:
        return f
    meas = float(np.nanmean(es["mag_strength_gs"]))
    ref = float(np.nanmean(es["mag_strength_ref_gs"]))
    if ref > 0:
        dev = (meas - ref) / ref * 100
        sev = OK if abs(dev) < 5 else (WARN if abs(dev) < 15 else CRIT)
        f.append(Finding(sev, "Compass",
                         f"Field strength {meas:.3f} G vs WMM reference {ref:.3f} G ({dev:+.1f}%)",
                         detail="Static deviation indicates magnetic distortion from the frame/payload.",
                         fixes=["recalibrate compass with all payloads powered and mounted",
                                "increase GPS/mag mast separation from electronics"] if sev >= WARN else []))
    return f


# --------------------------------------------------------------------------- #
def check_config(log, spec, hover):
    f = []
    # rangefinder configured in EKF but no data
    has_rng = log.has("distance_sensor")
    if log.param("EKF2_RNG_CTRL", 0) and not has_rng:
        f.append(Finding(WARN, "Config",
                         "EKF2_RNG_CTRL enabled but no distance_sensor data in the log",
                         fixes=["enable the driver (e.g. param set SENS_EN_LL40LS 1) and verify with "
                                "'listener distance_sensor', or set EKF2_RNG_CTRL 0"]))
    if log.param("EKF2_OF_CTRL", 0) and not log.has("vehicle_optical_flow"):
        f.append(Finding(INFO, "Config", "EKF2_OF_CTRL enabled but no optical-flow data present",
                         fixes=["param set EKF2_OF_CTRL 0 if no flow sensor is fitted"]))
    # MPC_THR_HOVER vs estimate
    hte = log.get("hover_thrust_estimate")
    if hte is not None and np.any(hte["valid"]):
        ht = float(np.nanmedian(hte["hover_thrust"][hte["valid"] == 1]))
        cfg = log.param("MPC_THR_HOVER", 0.5)
        if abs(ht - cfg) > 0.1:
            f.append(Finding(WARN, "Config",
                             f"MPC_THR_HOVER = {cfg:.2f} but estimated hover thrust is {ht:.2f}",
                             fixes=[f"param set MPC_THR_HOVER {ht:.2f}   # after any THR_MDL_FAC change, re-measure"],
                             doc="02_propulsion_math.md"))
    # control allocation geometry symmetry
    n = int(log.param("CA_ROTOR_COUNT", 0))
    if n:
        px = [abs(log.param(f"CA_ROTOR{i}_PX", 0)) for i in range(n)]
        py = [abs(log.param(f"CA_ROTOR{i}_PY", 0)) for i in range(n)]
        for name, vals in (("PX", px), ("PY", py)):
            nz = [v for v in vals if v > 1e-4]
            if nz and (max(nz) - min(nz)) / max(nz) > 0.005:
                f.append(Finding(WARN, "Config",
                                 f"CA_ROTORn_{name} magnitudes are not symmetric: {['%.4f' % v for v in vals]}",
                                 detail="Symmetric frames should have equal arm coordinates; a typo "
                                        "here skews the control allocation.",
                                 fixes=[f"make all CA_ROTORn_{name} magnitudes equal"]))
    return f


# --------------------------------------------------------------------------- #
def check_system(log, spec, hover):
    f = []
    cl = log.get("cpuload")
    if cl is not None:
        v = float(cl["load"].max())
        if v > 0.85:
            f.append(Finding(WARN, "System", f"CPU load peaked at {v*100:.0f}%"))
    sp = log.get("system_power")
    if sp is not None:
        lo, hi = float(sp["voltage5v_v"].min()), float(sp["voltage5v_v"].max())
        if lo < 4.8:
            f.append(Finding(WARN, "System", f"5V rail dipped to {lo:.2f} V"))
        else:
            f.append(Finding(OK, "System", f"5V rail stable ({lo:.2f}-{hi:.2f} V)"))
    rc = log.get("input_rc")
    if rc is not None and np.any(rc["rc_lost"]):
        f.append(Finding(WARN, "System", f"RC signal lost for {np.mean(rc['rc_lost'])*100:.1f}% of samples"))
    return f


# --------------------------------------------------------------------------- #
def check_tracking(log, spec, hover):
    """How well the rate controller follows its setpoints."""
    f = []
    av = log.get("vehicle_angular_velocity")
    rs = log.get("vehicle_rates_setpoint")
    w = log.in_air_window()
    if av is None or rs is None or w is None:
        return f
    ta, tr = log.t(av), log.t(rs)
    m = (ta > w[0] + 2) & (ta < w[1] - 1)
    if m.sum() < 100:
        return f
    at_active = log.has("autotune_attitude_control_status")
    rms = {}
    for i, (ax, key) in enumerate((("roll", "roll"), ("pitch", "pitch"), ("yaw", "yaw"))):
        sp = np.interp(ta[m], tr, rs[key])
        err = (av[f"xyz[{i}]"][m] - sp) * 57.2958
        rms[ax] = float(np.sqrt(np.mean(err ** 2)))
    txt = "  ".join(f"{k}={v:.1f}" for k, v in rms.items())
    worst = max(rms.values())
    sev = OK if worst < 8 else (WARN if worst < 20 else CRIT)
    note = " (autotune excitation active - values inflated)" if at_active and sev >= WARN else ""
    f.append(Finding(sev, "Control", f"Rate tracking RMS error [deg/s]: {txt}{note}",
                     detail="Persistent RMS above ~10 deg/s outside maneuvers means the rate "
                            "loop is poorly tuned, saturated, or fighting vibration.",
                     doc="05_autotune.md"))
    # oscillation detector: dominant frequency of rate error with high power
    for i, ax in enumerate(("roll", "pitch", "yaw")):
        x = av[f"xyz[{i}]"][m]
        x = x - x.mean()
        dt = float(np.median(np.diff(ta[m])))
        fr = np.fft.rfftfreq(len(x), dt)
        P = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        band = (fr > 2) & (fr < 30)
        if band.any() and P[band].max() > 0.5 * P[fr > 0.5].sum():
            fpk = fr[band][np.argmax(P[band])]
            f.append(Finding(WARN, "Control",
                             f"Sustained {ax} oscillation at ~{fpk:.1f} Hz dominates the gyro signal",
                             fixes=[f"reduce MC_{ax.upper()}RATE_P/D by 20-30% and retest"],
                             doc="05_autotune.md"))
    return f


# --------------------------------------------------------------------------- #
def check_logging(log, spec, hover):
    """Logger dropouts and estimator time slip - data quality of the log itself."""
    f = []
    drops = getattr(log.ulog, "dropouts", [])
    if drops:
        total = sum(d.duration for d in drops)
        f.append(Finding(WARN, "System",
                         f"{len(drops)} logger dropout(s), {total} ms of data lost",
                         detail="Frequent dropouts point to a slow/failing SD card.",
                         fixes=["use a fast (A1/A2 class) SD card, reduce SDLOG_PROFILE"]))
    es = log.get("estimator_status", 0)
    if es is not None and "time_slip" in es:
        slip = float(np.nanmax(es["time_slip"]))
        if slip > 0.02:
            f.append(Finding(WARN, "System",
                             f"Estimator time slip up to {slip*1000:.0f} ms - "
                             "scheduling delays (CPU overload or driver stalls)"))
    return f



# --------------------------------------------------------------------------- #
# Cross-signal correlation analyses
# --------------------------------------------------------------------------- #
def _mag_power_data(log):
    """Common data for mag-vs-power analysis: time, |B|, current, mean motor cmd."""
    mag = log.get("vehicle_magnetometer")
    w = log.in_air_window()
    if mag is None or w is None:
        return None
    tm = log.t(mag)
    m = (tm > w[0] + 2) & (tm < w[1] - 1)
    if m.sum() < 30:
        return None
    B = np.sqrt(sum(mag[f"magnetometer_ga[{i}]"] ** 2 for i in range(3)))[m]
    tm = tm[m]
    out = dict(t=tm, B=B)
    b = log.get("battery_status")
    if b is not None:
        out["I"] = np.interp(tm, log.t(b), b["current_a"])
    am = log.get("actuator_motors")
    if am is not None:
        n = sum(1 for i in range(12) if f"control[{i}]" in am
                and np.isfinite(am[f"control[{i}]"]).any())
        mean_cmd = np.mean(np.stack([am[f"control[{i}]"] for i in range(n)]), 0)
        out["thr"] = np.interp(tm, log.t(am), mean_cmd)
    att = log.get("vehicle_attitude")
    if att is not None:
        q = [att[f"q[{i}]"] for i in range(4)]
        yaw = np.arctan2(2 * (q[0] * q[3] + q[1] * q[2]),
                         1 - 2 * (q[2] ** 2 + q[3] ** 2))
        out["yaw"] = np.interp(tm, log.t(att), np.unwrap(yaw))
    return out


def check_mag_vs_power(log, spec, hover):
    """Magnetic interference from the power system, and heading-dependent field errors."""
    f = []
    d = _mag_power_data(log)
    if d is None:
        return f
    B = d["B"]
    Bm = float(B.mean())
    for key, label, unit in (("I", "battery current", "A"), ("thr", "mean thrust command", "")):
        if key not in d:
            continue
        x = d[key]
        if np.std(x) < 1e-6:
            continue
        r = float(np.corrcoef(B, x)[0, 1])
        slope = float(np.polyfit(x, B, 1)[0])
        # field change across the observed range of x, as % of mean field
        dB_pct = slope * (x.max() - x.min()) / Bm * 100
        if key == "I":
            detail = (f"corr(|B|, I) = {r:+.2f};  slope {slope*1000:+.2f} mG/A;  "
                      f"field changes {dB_pct:+.1f}% of |B| across the {x.min():.0f}-{x.max():.0f} A range")
        else:
            detail = f"corr(|B|, thrust) = {r:+.2f};  {dB_pct:+.1f}% field change across the thrust range"
        strong = abs(r) > 0.5 and abs(dB_pct) > 3
        severe = abs(r) > 0.7 and abs(dB_pct) > 10
        sev = CRIT if severe else (WARN if strong else OK)
        verdict = ("strong power-system magnetic interference" if strong else
                   "no significant coupling")
        f.append(Finding(sev, "Compass", f"|B| vs {label}: {verdict}",
                         detail=detail,
                         fixes=["twist battery/ESC power leads, route them away from the mag",
                                "move GPS/mag mast higher",
                                "as mitigation: CAL_MAG_COMP_TYP current-based compensation"] if strong else [],
                         doc="07_correlations.md"))
    # heading-dependent field strength => calibration quality
    if "yaw" in d:
        yaw = np.degrees(d["yaw"]) % 360
        span = float(np.ptp(np.degrees(d["yaw"])))
        if span > 90:
            bins = np.linspace(0, 360, 13)
            idx = np.digitize(yaw, bins)
            means = [B[idx == i].mean() for i in range(1, 13) if (idx == i).sum() > 5]
            if len(means) >= 3:
                var_pct = (max(means) - min(means)) / Bm * 100
                sev = OK if var_pct < 3 else (WARN if var_pct < 8 else CRIT)
                f.append(Finding(sev, "Compass",
                                 f"|B| varies {var_pct:.1f}% with heading "
                                 f"(over {span:.0f} deg of yaw seen)",
                                 detail="A well-calibrated magnetometer reads a constant field "
                                        "magnitude regardless of heading. Variation = residual "
                                        "hard/soft-iron error.",
                                 fixes=["redo compass calibration with payloads powered"] if sev >= WARN else [],
                                 doc="07_correlations.md"))
        else:
            f.append(Finding(INFO, "Compass",
                             f"Heading-dependence of |B| not assessable (only {span:.0f} deg of "
                             "yaw covered this flight)", doc="07_correlations.md"))
    return f


def check_battery_resistance(log, spec, hover):
    """Fit pack internal resistance from the V-I scatter: V = V_oc - R*I."""
    f = []
    b = log.get("battery_status")
    w = log.in_air_window()
    if b is None or w is None:
        return f
    t = log.t(b)
    m = (t > w[0]) & (t < w[1]) & np.isfinite(b["current_a"]) & (b["current_a"] > 0.5)
    if m.sum() < 30:
        return f
    I, V = b["current_a"][m], b["voltage_v"][m]
    if np.ptp(I) < 4:
        f.append(Finding(INFO, "Battery",
                         f"Internal-resistance fit skipped: current only varied "
                         f"{np.ptp(I):.1f} A this flight (need >4 A of spread)",
                         doc="07_correlations.md"))
        return f
    # detrend slow discharge: fit V ~ a - R*I - k*t  (k absorbs SOC droop)
    A = np.column_stack([np.ones_like(I), -I, -(t[m] - t[m][0])])
    coef, *_ = np.linalg.lstsq(A, V, rcond=None)
    voc, r_pack, droop = float(coef[0]), float(coef[1]), float(coef[2])
    cells = max(int(log.param("BAT1_N_CELLS", 4)), 1)
    r_cell = r_pack / cells
    pred = A @ coef
    rms = float(np.sqrt(np.mean((V - pred) ** 2)))
    if not (0.0005 <= r_cell <= 0.06):
        f.append(Finding(INFO, "Battery",
                         f"Internal-resistance fit implausible ({r_cell*1000:.1f} mOhm/cell) - "
                         "likely too little current excitation; ignoring", doc="07_correlations.md"))
        return f
    cfg = log.param("BAT1_R_INTERNAL", -1.0)
    det = (f"fit V = {voc:.2f} - {r_pack*1000:.1f} mOhm * I - {droop*1000:.1f} mV/s "
           f"(rms {rms*1000:.0f} mV)  ->  {r_cell*1000:.1f} mOhm/cell "
           f"({cells}S pack, {np.ptp(I):.0f} A of current spread)")
    if cfg < 0:
        f.append(Finding(WARN, "Battery",
                         f"Measured internal resistance {r_cell*1000:.1f} mOhm/cell - "
                         "BAT1_R_INTERNAL is unset, so SOC ignores it",
                         detail=det,
                         fixes=[f"param set BAT1_R_INTERNAL {r_cell:.4f}"],
                         doc="07_correlations.md"))
    elif abs(cfg - r_cell) / r_cell > 0.5:
        f.append(Finding(WARN, "Battery",
                         f"BAT1_R_INTERNAL = {cfg*1000:.1f} mOhm but measured {r_cell*1000:.1f} mOhm/cell",
                         detail=det, fixes=[f"param set BAT1_R_INTERNAL {r_cell:.4f}"],
                         doc="07_correlations.md"))
    else:
        f.append(Finding(OK, "Battery",
                         f"Internal resistance {r_cell*1000:.1f} mOhm/cell (param {cfg*1000:.1f} mOhm)",
                         detail=det, doc="07_correlations.md"))
    return f


def check_hover_efficiency(log, spec, hover):
    f = []
    if not (hover.get("voltage") and hover.get("current")):
        return f
    P = hover["voltage"] * hover["current"]
    if spec and spec.mass_kg:
        gpw = spec.mass_kg * 1000.0 / P
        sev = OK if gpw > 5.5 else (WARN if gpw > 4 else CRIT)
        det = f"hover power {P:.0f} W at {hover['voltage']:.1f} V / {hover['current']:.1f} A"
        if spec.has_bench:
            thr_b, T_b, I_b = spec.bench_arrays()
            if not np.isnan(I_b).any() and "esc_throttle" in hover:
                e = float(np.mean(hover["esc_throttle"]))
                gpw_b = float(np.interp(e, thr_b, T_b) / (spec.bench_voltage * np.interp(e, thr_b, I_b)))
                det += f"; bench efficiency at the same throttle: {gpw_b:.1f} g/W"
        f.append(Finding(sev, "Propulsion",
                         f"Hover efficiency {gpw:.1f} g/W",
                         detail=det + ". Below ~5 g/W for a 10-inch quad means the propulsion "
                                "is operating far from its efficient region (overloaded).",
                         doc="07_correlations.md"))
    else:
        f.append(Finding(INFO, "Propulsion", f"Hover power {P:.0f} W "
                         "(provide --mass for the g/W efficiency metric)"))
    return f


def check_imu_bias(log, spec, hover):
    """EKF-estimated IMU biases vs their configured limits."""
    f = []
    sb = log.get("estimator_sensor_bias")
    if sb is None:
        return f
    gb = np.sqrt(sum(sb[f"gyro_bias[{i}]"][-1] ** 2 for i in range(3)))
    ab = np.sqrt(sum(sb[f"accel_bias[{i}]"][-1] ** 2 for i in range(3)))
    glim = log.param("EKF2_GYR_B_LIM", 0.15)
    alim = log.param("EKF2_ABL_LIM", 0.4)
    for val, lim, name, unit in ((gb, glim, "gyro", "rad/s"), (ab, alim, "accel", "m/s^2")):
        frac = val / lim if lim else 0
        sev = OK if frac < 0.5 else (WARN if frac < 0.85 else CRIT)
        note = "" if sev == OK else " - approaching the estimator clip limit: recalibrate the IMU"
        f.append(Finding(sev, "EKF",
                         f"EKF {name} bias estimate {val:.4f} {unit} "
                         f"({frac*100:.0f}% of the {lim:g} limit){note}",
                         fixes=["redo accel/gyro calibration at flight temperature"] if sev >= WARN else [],
                         doc="07_correlations.md"))
    return f

ALL_CHECKS = [check_flight_summary, check_autotune, check_actuators, check_propulsion_model,
              check_vibration, check_ekf, check_gps, check_battery, check_mag,
              check_config, check_system, check_tracking, check_logging,
              check_mag_vs_power, check_battery_resistance, check_hover_efficiency,
              check_imu_bias]


def run_all(log, spec, hover):
    findings = []
    errors = []
    for chk in ALL_CHECKS:
        try:
            findings.extend(chk(log, spec, hover))
        except Exception as e:  # a failed check must not kill the report
            errors.append(f"{chk.__name__}: {type(e).__name__}: {e}")
    return findings, errors
