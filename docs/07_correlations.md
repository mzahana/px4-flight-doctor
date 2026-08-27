# Cross-Signal Correlations: What Signals Say About Each Other

Single signals tell you *what* happened; correlations between signals tell
you *why*. These are the relations the analyzer computes.

## Magnetic field vs thrust / current

Motor and battery currents create their own magnetic field on top of
Earth's (Ampère's law: B ∝ I / distance). The compass can't tell them
apart, so high throttle bends the heading estimate — classically causing
the "toilet bowl" circling in position hold, or yaw jumps on punch-outs.

**The test:** correlate field magnitude |B| with battery current over the
flight, and fit a slope:

```
corr(|B|, I)          how consistently the field follows current
slope [mG/A]          how much field one amp adds
Δ|B| across I range   the effect size, as % of the mean field
```

Judging it: |corr| > 0.5 **and** several % of field change = real
interference. A weak correlation with small Δ|B| is just noise — no action.

**Fixes**, in order of effectiveness: twist the battery + ESC power leads
(cancels their loops' fields), increase mag-to-power-wiring distance (field
falls off ~1/r), raise the GPS/mag mast, and as a software mitigation PX4
can compensate the mag from measured current (`CAL_MAG_COMP_TYP`).

Note the distinction from a *static* field-strength offset vs the world
model (see 06): static offset = ferrous hardware / calibration, dynamic
current-correlated change = power wiring. Different causes, different fixes.

## |B| vs heading: calibration quality

Earth's field magnitude doesn't depend on which way you face. So if the
*measured* |B| changes with yaw, the difference is residual hard/soft-iron
calibration error. The analyzer bins |B| by heading (when the flight covers
> 90° of yaw) and reports the spread: < 3% good, > 8% recalibrate.

## Battery internal resistance from the V–I scatter

Every time the current changes, the pack voltage instantly moves by
`ΔV = −R_internal · ΔI`. A flight with varying throttle therefore *is* a
resistance measurement. The analyzer fits:

```
V(t) = V_oc − R_pack · I(t) − k · t
```

The `k·t` term absorbs the slow state-of-charge droop so it doesn't bias
the resistance slope; `R_pack / cell_count` is the per-cell value for
`BAT1_R_INTERNAL`. With it set, PX4 computes SOC from the *sag-corrected*
voltage, so the "remaining %" stops crashing every time you throttle up.

Healthy 4S–6S packs: ~2–8 mΩ/cell new; > 15 mΩ/cell means the pack is aging
(more sag, more heat, less usable capacity). Tracking this number across
flights is a battery health monitor for free. The fit needs current
*variation* (> 4 A spread) — a constant-hover log can't separate R from V_oc.

## Hover efficiency (g/W)

```
g/W = mass [g] / (V_hover · I_hover)
```

The single most honest number for "is this airframe overloaded?". For
10-inch-class quads: > 7 g/W excellent, 5–7 normal, < 5 the propulsion is
operating far past its efficient region — expect heat, sag, and short
flights. Comparing against the bench table's g/W at the same throttle
separates airframe problems (dirty aero, extra weight) from propulsion
problems (worn props, weak motor).

## IMU bias vs estimator limits

The EKF continuously estimates gyro and accel biases and *clips* them at
`EKF2_GYR_B_LIM` / `EKF2_ABL_LIM`. An estimate near its clip limit means
the true bias is probably beyond it — the filter can no longer track it,
and attitude/velocity errors follow. Bias under 50% of the limit is
healthy; above ~85%, recalibrate the IMU (ideally at flight temperature —
bias is temperature-dependent).
