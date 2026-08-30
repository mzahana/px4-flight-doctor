# Propulsion Math: Hover Throttle, Thrust-to-Weight, and Headroom

## Why hover throttle matters more than max thrust

A multicopter steers by making some motors produce *more* thrust and others
*less*. The room to do that is called **control headroom**:

```
headroom_up   = max_thrust  - hover_thrust
headroom_down = hover_thrust - min_thrust
```

If you hover at 75% command, only 25% of the range is left to fight a gust,
follow a step input, or execute an autotune excitation. When any motor reaches
100% it **saturates**: the controller demands torque the hardware cannot
deliver. PX4's allocator then sacrifices axes in priority order — **yaw is
dropped first** (yaw torque comes from weak drag effects; roll/pitch from
strong lever-arm effects).

Rule of thumb: hover command ≤ 0.5 is ideal, ≤ 0.65 acceptable, above that
expect degraded control and unreliable autotune.

## Thrust-to-weight (T/W)

```
T/W = (max thrust of all motors, at actual flight conditions) / (weight)
```

Target **≥ 2.0** for a responsive machine, **≥ 1.7** minimum for tuning
flights. Note "actual flight conditions" — the datasheet number is almost
always measured at full battery voltage and sea level, which you rarely have.

## Correcting bench data to your flight

Motor bench tables (thrust vs throttle) are measured at a fixed voltage
(often 16 V for 4S) and roughly sea-level density. Two corrections map them
to your flight:

### 1. Voltage

At a fixed throttle percentage, a brushless motor's RPM is roughly
proportional to voltage, and propeller thrust is proportional to RPM²:

```
thrust_scale = (V_flight / V_bench)²
```

Example: pack sagging to 14.5 V vs a 16 V bench → (14.5/16)² = **0.82**.
You lose 18% of the table's thrust just from voltage sag.

### 2. Air density

Propeller thrust at fixed RPM is proportional to air density ρ:

```
rho = P / (R_air · T)        R_air = 287.05 J/(kg·K), T in kelvin
density_scale = rho / 1.225
```

Example: field at 650 m elevation on a 35 °C day → P ≈ 93.8 kPa,
ρ = 93800 / (287.05 × 308) = **1.06 kg/m³** → scale = 1.06/1.225 = **0.87**.

⚠️ The autopilot's logged temperature is usually the **barometer die
temperature**, self-heated 15–25 °C above outside air. Always supply the real
OAT — a 20 °C error moves density ~6%.

### Putting it together — worked example

X500 V2 at 2.2 kg: each of 4 motors must lift 550 g.

```
combined scale k = 0.82 × 0.87 = 0.71
bench-equivalent thrust = 550 / 0.71 = 775 g
```

Read 775 g off the bench table → ≈ 68% throttle. If the log shows the motors
averaging ~70%, **the propulsion is healthy** — the high hover throttle is
explained entirely by voltage + density, not by worn props. If the observed
throttle is much higher than predicted, suspect the hardware (prop wear,
bearings) or your mass/bench numbers.

The same table predicts current: read A at the observed throttle, scale by
the *voltage* factor, multiply by motor count, and compare with the logged
pack current. Agreement within ~5% is a strong health confirmation.

## PWM output range vs thrust limits

`PWM_MAIN_MAXn` / `PWM_AUX_MAXn` below 2000 µs silently caps every motor,
e.g. 1900 µs = 90% throttle ceiling. This distorts the whole command→thrust
mapping and steals attitude authority. If you need to protect a prop or motor
rated below full-throttle thrust, cap **collective** thrust with
`MPC_THR_MAX` instead — attitude control can still momentarily use full
per-motor output, which is exactly what you want in a gust.

## When the balance / CG analysis is valid

Per-motor load comparisons (hover demand, standing yaw-torque bias, load
spread / CG offset) are only meaningful in **quasi-static hover**: during
translation or maneuvering the controller redistributes motor load for
aerodynamic and dynamic reasons that say nothing about mass or geometry.
The analyzer therefore restricts those checks to samples where |vz| < 0.3 m/s
and horizontal speed < 1 m/s (excluding the first 3 s after takeoff and the
last 1 s before landing), and skips them entirely — with an INFO note — when
the log contains less than ~5 s of such hover.

Spin-direction groups and rotor positions come from the `CA_ROTOR*`
control-allocation parameters, so the checks apply to any multirotor (quad,
hex, octo, coax), not just the standard quad layout. When the geometry is
available, the load spread finding also reports a thrust-weighted estimate of
the CG offset direction in the body frame.

One caveat the analyzer cannot remove: hovering in **steady wind** requires a
constant lean, which shifts load between motors exactly like a CG offset.
When the log carries a wind estimate above ~2 m/s the finding says so; when
there is no wind estimate, treat a balance warning from a windy flight with
suspicion and re-fly in calm air before re-rigging the airframe.
