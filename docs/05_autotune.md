# How PX4 Autotune Works (and Why It Fails)

## What it actually does

Autotune is **system identification**: it injects a small square-wave torque
on one axis at a time (roll → pitch → yaw), records how the airframe's
angular rate responds, and fits a low-order dynamic model with a recursive
least-squares estimator. From the fitted model it computes PID gains, checks
them for sanity (VERIFICATION), and applies them.

State machine you'll see in a log:

```
INIT → ROLL → ROLL_PAUSE → PITCH → PITCH_PAUSE → YAW → YAW_PAUSE
     → VERIFICATION → APPLY → (WAIT_FOR_DISARM | TEST) → COMPLETE
                            ↘ FAIL
```

Each axis needs **at least 5 s** and all five model-coefficient variances
below a threshold; if an axis takes longer than **20 s** the whole run
aborts. It also aborts on pilot stick input (>5%) or a flight-mode change.

## How to judge a run from the log

- **Convergence time per axis.** 5.0 s = clean. 10–15 s = the estimator was
  struggling; treat the result with suspicion even if it "passed".
- **Estimate stability at hand-off.** The gains PX4 keeps are whatever the
  estimator held at the instant the variance test passed. If `kc`/`kd` were
  still moving in the last second, the tune is a snapshot of a moving target.
- **Was any motor saturated during the excitation?** If yes, the injected
  torque never reached the airframe — the model is fit to clipped data.
  This hits **yaw hardest**: yaw torque is the weakest and the first thing
  the allocator sacrifices.

## What corrupts identification

| Cause | Mechanism |
|---|---|
| Motor saturation | commanded ≠ delivered torque → wrong model |
| Vibration | estimator fits resonance instead of rigid-body dynamics |
| Wrong THR_MDL_FAC | plant gain varies with throttle → no single model fits |
| Wind / turbulence | uncommanded disturbance treated as response |
| Low altitude | ground effect changes the dynamics being identified |
| Sagging battery | plant gain drifts during the run itself |

Pre-flight checklist for a good autotune: hover command < 0.65, vibration
metrics green, THR_MDL_FAC set, fresh pack, calm air, ≥ 10 m AGL.

## Gain forms: standard vs parallel (reading the results)

The estimator produces **standard form**: overall gain K with time-constant
ratios (K, i, d). PX4 parameters store **parallel form** (P, I, D). The
conversion when gains are saved:

```
RATE_P = K          RATE_I = K·i          RATE_D = K·d          (K param set to 1)
```

So after an autotune, `MC_xxxRATE_K` is 1 and the P/I/D params carry the
result. Sanity ranges enforced at VERIFICATION: 0 < K < 0.5, 0 < i < 10,
0 ≤ d < 0.1, 0 < attitude P < 12. Note these are wide — a tune can *pass*
verification and still be poor. Typical healthy values for a 500-class quad:
RATE_P 0.1–0.25, ATT_P 3–6.5. An attitude P near 8+ or a rate D of exactly 0
on roll/pitch deserves a manual look before you trust it.

## If it fails (or you distrust an axis)

Gains are only written at COMPLETE (or in TEST mode with backup/revert), so
a FAIL costs nothing but time. Revert a suspect axis to defaults
(`MC_YAWRATE_P 0.2 / I 0.1 / D 0 / K 1, MC_YAW_P 2.8` for yaw), fix the root
cause from the table above, and re-run.
