# EKF Health: Innovations, Test Ratios, and Resets

## The one concept: innovation

The EKF continuously predicts what each sensor *should* read from its
current state estimate. The difference between prediction and actual
measurement is the **innovation**:

```
innovation = measurement − prediction
```

A healthy filter has small, zero-mean, noise-like innovations. Structured or
growing innovations mean the model and reality disagree — bad sensor, bad
calibration, or unmodeled disturbance.

## Test ratios

Raw innovation size is meaningless without context (1 m position error is
terrible for RTK, normal for a phone GPS). So each innovation is normalized
by its expected uncertainty and gate size:

```
test_ratio = innovation² / (gate² · innovation_variance)
```

- **< 0.5** healthy
- **0.5 – 1.0** stressed: the measurement barely fits the model
- **> 1.0** the measurement was **rejected** — the filter is flying on
  fewer sensors than you think

The report shows the worst ratio per group (velocity, position, height,
heading) over the flight.

## Resets

When innovations stay too large too long, the EKF gives up blending and
**snaps** its state to the measurement. Each snap increments a reset counter
(position, velocity, heading). Resets during flight are visible as jumps in
the position/attitude estimate — the controllers react to them, so an
"unexplained twitch" in flight often lines up with a reset in the log.
Occasional single resets right after takeoff (e.g. in-flight yaw alignment)
are normal; repeated resets mid-flight are a sensor problem.

## Magnetometer sanity

The World Magnetic Model (WMM) predicts field strength and inclination for
your GPS location. The EKF logs both measured and reference values:

- strength deviation < 5%: clean installation
- 5–15%: static distortion from the frame/payload — recalibrate with
  payloads powered; heading is degraded but usable
- > 15%: expect heading trouble; physically separate the mag from
  current-carrying wires and ferrous parts

A field deviation that *correlates with battery current* is power-wiring
interference (twist leads, move mag); one that doesn't is static iron
(calibrate it out or relocate).
