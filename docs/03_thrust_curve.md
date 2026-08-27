# The Thrust Curve: THR_MDL_FAC, Battery Scaling, and MPC_THR_HOVER

## The problem

PX4's controllers compute a **normalized thrust command** `s ∈ [0,1]` and
assume the motors deliver thrust *proportionally* to it. Real props don't:
thrust vs ESC signal is closer to **quadratic** (thrust ∝ RPM², RPM roughly
∝ signal). PX4 models this with one parameter:

```
rel_thrust(s) = f·s² + (1−f)·s        f = THR_MDL_FAC
```

- `f = 0`  → assume linear (default)
- `f = 1`  → assume fully quadratic (correct for RPM-governed ESCs)
- PWM ESCs are typically in between; PX4's guide suggests 0.3 as a start,
  but you can **fit f from a bench table** (the analyzer does this).

## Why a wrong f ruins tuning

The controller cares about the **local slope** dT/ds — how much extra thrust
one unit of command buys *at the current operating point*:

```
dT/ds = 2f·s + (1−f)
```

With `f = 0` PX4 assumes slope 1 everywhere. If the real curve is quadratic
and you hover at s = 0.75, the true slope there is ≈ 1.5 — **every torque
command produces ~1.5× the torque PX4 intended**, and the factor changes
with throttle:

| where | throttle | true gain vs assumed |
|---|---|---|
| descent | 0.55 | ×1.1 |
| hover | 0.75 | ×1.5 |
| climb | 0.90 | ×1.8 |

This is a throttle-dependent plant gain. PID gains tuned in hover are
under-gained in descent and over-gained in climb, and autotune's system
identification — which assumes one constant plant — converges slowly or to a
wrong model.

## Fitting f from bench data

Take the bench thrust curve over your *configured output window*, normalize
it so rel_thrust(1) = 1, and least-squares fit f. Note the fitted value
depends on the PWM window: a 1100–1900 µs window skips the flattest bottom
part of the curve, so it fits a smaller f than the full 1000–2000 range.
**Set your PWM range first, then fit and set THR_MDL_FAC, then re-measure
hover thrust** — each one changes the meaning of the next.

## Battery scaling (MC_BAT_SCALE_EN)

Thrust at fixed throttle scales with (V/V_full)². A 4S pack sagging from
16.8 V to 14.2 V loses ~29% thrust per unit command — so the *effective*
loop gain of your rate controllers drops the same way through the flight.
`MC_BAT_SCALE_EN 1` multiplies thrust commands by the inverse voltage ratio
so the tune feels identical at 20% battery and at 90%.

## MPC_THR_HOVER

The position controller's feed-forward guess of hover command. If it's 0.5
but the vehicle really hovers at 0.7, every altitude-mode engagement starts
with a sag until the integrator catches up. Read the converged value of
`hover_thrust_estimate` from a log and set it. Re-measure after **any**
change to THR_MDL_FAC, PWM range, mass, or props — they all move it.
