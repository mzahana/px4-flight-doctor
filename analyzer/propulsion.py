"""Propulsion physics: reconcile logged actuator data against motor bench measurements.

All the math here is explained in docs/02_propulsion_math.md and docs/03_thrust_curve.md.
"""
import numpy as np

from .vehicle import RHO_SL, air_density


def rotor_geometry(log, n=None):
    """[(px_fwd, py_right, km)] per rotor from the CA_ROTOR* control-allocation
    params, or None when they are absent/unconfigured. `n` (if given) must match
    CA_ROTOR_COUNT. KM > 0 is a CCW-spinning rotor in PX4's convention."""
    cnt = int(log.param("CA_ROTOR_COUNT", 0) or 0)
    if cnt < 3 or (n is not None and cnt != n):
        return None
    geo = []
    for i in range(cnt):
        px, py, km = (log.param(f"CA_ROTOR{i}_{s}") for s in ("PX", "PY", "KM"))
        if px is None or py is None or km is None:
            return None
        geo.append((float(px), float(py), float(km)))
    if all(abs(px) + abs(py) < 0.01 for px, py, _ in geo):
        return None
    return geo


def cg_offset(geo, means):
    """Thrust-weighted CG shift (m forward, m right) from the geometric rotor
    center, treating each rotor's mean hover command as its thrust share."""
    p = np.array([(px, py) for px, py, _ in geo])
    w = np.asarray(means, dtype=float)
    dx, dy = (w[:, None] * p).sum(axis=0) / w.sum() - p.mean(axis=0)
    return float(dx), float(dy)


def motor_output_channels(log):
    """Find the PWM output channels driving motors and their configured range.

    Returns (instance, [channel indices], [(pwm_min, pwm_max)]) or None.
    Motor output functions are 101..116 on PWM_MAIN_FUNCn / PWM_AUX_FUNCn.
    """
    for prefix, inst_guess in (("PWM_MAIN", 0), ("PWM_AUX", 1)):
        chans, ranges = [], []
        for i in range(1, 17):
            fn = log.param(f"{prefix}_FUNC{i}")
            if fn is not None and 101 <= fn <= 116:
                chans.append(i - 1)
                ranges.append((log.param(f"{prefix}_MIN{i}", 1000),
                               log.param(f"{prefix}_MAX{i}", 2000)))
        if chans:
            # find the actuator_outputs instance whose sample count is largest
            best, best_n = None, 0
            for inst in range(3):
                d = log.get("actuator_outputs", inst)
                if d is not None and len(d["timestamp"]) > best_n:
                    best, best_n = inst, len(d["timestamp"])
            return best, chans, ranges
    return None


def hover_state(log):
    """Measured quantities during quasi-static hover.

    Returns dict with: pwm per motor (us), esc throttle per motor (0..1),
    normalized command per motor, pack voltage, current, rho.
    """
    out = {}
    mo = motor_output_channels(log)
    ao = log.get("actuator_outputs", mo[0]) if mo else None
    if ao is not None:
        t = log.t(ao)
        m = log.hover_mask(t)
        if m.sum() > 10:
            out["pwm"] = np.array([np.mean(ao[f"output[{c}]"][m]) for c in mo[1]])
            out["pwm_range"] = mo[2]
            # ESC throttle: fraction of the *hardware* 1000-2000us range
            out["esc_throttle"] = (out["pwm"] - 1000.0) / 1000.0
    am = log.get("actuator_motors")
    if am is not None:
        t = log.t(am)
        m = log.hover_mask(t)
        if m.sum() > 10:
            n = int(np.sum([f"control[{i}]" in am for i in range(12)]))
            ctl = [am[f"control[{i}]"][m] for i in range(n)
                   if np.isfinite(am[f"control[{i}]"][m]).all()]
            out["norm_cmd"] = np.array([np.mean(c) for c in ctl if len(c)])
    b = log.get("battery_status")
    if b is not None:
        t = log.t(b)
        m = log.hover_mask(t)
        if m.sum() > 3:
            out["voltage"] = float(np.mean(b["voltage_v"][m]))
            out["current"] = float(np.nanmean(b["current_a"][m]))
    ad = log.get("vehicle_air_data")
    if ad is not None:
        out["pressure_pa"] = float(np.mean(ad["baro_pressure_pa"]))
        out["rho_logged"] = float(np.mean(ad["rho"]))
        out["temp_source"] = int(ad["temperature_source"][0]) if "temperature_source" in ad else None
        out["logged_temp"] = float(np.mean(ad["ambient_temperature"])) if "ambient_temperature" in ad else None
    return out


def correction_factors(hover, spec):
    """Scale factors mapping bench-table thrust to flight conditions.

    thrust  ~ V^2  at fixed throttle (RPM ~ V, thrust ~ RPM^2 ~ rho)
    thrust  ~ rho  at fixed RPM
    """
    kv = kr = None
    if spec.has_bench and "voltage" in hover:
        kv = (hover["voltage"] / spec.bench_voltage) ** 2
    if "pressure_pa" in hover:
        if spec.oat_c is not None:
            rho = air_density(hover["pressure_pa"], spec.oat_c)
            rho_src = f"baro pressure + user OAT {spec.oat_c:.0f} degC"
        else:
            rho = hover.get("rho_logged")
            rho_src = "logged rho (CAUTION: uses baro die temperature, likely self-heated)"
        if rho:
            kr = rho / RHO_SL
            return kv, kr, rho, rho_src
    return kv, None, None, ""


def predict_hover_throttle(spec, k_total):
    """Bench-equivalent thrust needed per motor and the ESC throttle that produces it."""
    thr, T, _ = spec.bench_arrays()
    need_g = spec.mass_kg * 1000.0 / spec.n_motors
    bench_equiv = need_g / k_total
    return need_g, bench_equiv, float(np.interp(bench_equiv, T, thr))


def thrust_at_throttle(spec, esc_throttle, k_total):
    thr, T, _ = spec.bench_arrays()
    return np.interp(esc_throttle, thr, T) * k_total


def current_at_throttle(spec, esc_throttle, kv):
    thr, _, I = spec.bench_arrays()
    if np.isnan(I).any():
        return None
    return np.interp(esc_throttle, thr, I) * kv


def fit_thr_mdl_fac(spec, pwm_min, pwm_max):
    """Least-squares fit of PX4's thrust model to the bench curve.

    PX4 maps normalized command s in [0,1] to output signal, then assumes
        rel_thrust(s) = f*s^2 + (1-f)*s.
    We compute the *actual* rel_thrust over the configured PWM window and fit f.
    """
    thr, T, _ = spec.bench_arrays()
    s = np.linspace(0.05, 1.0, 60)
    esc = ((pwm_max - pwm_min) * s + pwm_min - 1000.0) / 1000.0
    esc_top = (pwm_max - 1000.0) / 1000.0
    rel = np.interp(esc, thr, T) / np.interp(esc_top, thr, T)
    basis = s - s ** 2                       # rel - s = -f * (s - s^2)
    f = float(np.sum((s - rel) * basis) / np.sum(basis ** 2))
    resid = rel - (f * s ** 2 + (1 - f) * s)
    return f, float(np.sqrt(np.mean(resid ** 2)))


def per_motor_thrust(spec, esc_throttles, k_total):
    """Per-motor thrust in grams at flight conditions from measured PWM."""
    return np.array([thrust_at_throttle(spec, e, k_total) for e in esc_throttles])
