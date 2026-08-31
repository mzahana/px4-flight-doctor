# Trajectory: Frames, Setpoints, and Tracking Error

## The frame

PX4's estimator works in a local **NED** frame: `x` north, `y` east, `z`
**down**, all in metres. The trajectory plots convert this to the way a map
reads — east on the horizontal axis, north on the vertical, and altitude as
`up = −z`.

The origin is not the takeoff point. It is the **local position reference**
the EKF set when it first got a usable global fix, logged as `ref_lat` /
`ref_lon` / `ref_alt` in `vehicle_local_position`. So:

- a track that does not start at (0, 0) is normal — the origin is wherever
  the estimator initialised, which may be a different spot or a different
  session;
- an altitude that is **negative** throughout simply means the reference was
  set higher than the vehicle ever flew. It is not an error, and the shape of
  the curve is still exactly right. Only *differences* in altitude are
  meaningful unless you have checked what `ref_alt` was.

If the EKF resets its origin mid-log (a `xy_reset_counter` bump), the track
jumps by the reset delta. That jump is in the estimate, not in the vehicle.

## Why the setpoint has gaps

The commanded position comes from `vehicle_local_position_setpoint` — what
the position controller actually ran — falling back to `trajectory_setpoint`,
its input, for logs that lack it.

Both carry **NaN on any axis the active mode is not controlling in
position**, and the plots preserve that: the dashed setpoint line breaks
rather than interpolating across the gap. This is information, not missing
data. Typical patterns:

| Mode | x / y setpoint | z setpoint |
|---|---|---|
| `POSCTL`, sticks centred | present (position hold) | present (altitude hold) |
| `POSCTL`, roll/pitch deflected | absent (velocity control) | unaffected |
| `POSCTL`, throttle off centre | unaffected | absent (climb-rate control) |
| `ALTCTL` | absent | present only while throttle is centred |
| `STABILIZED` / `MANUAL` / `ACRO` | absent | absent |
| `AUTO_*`, `OFFBOARD` (position) | present | present |

The gating is **per axis, and follows the stick, not just the mode**. In
`POSCTL` the horizontal setpoint disappears the moment you deflect
roll/pitch and the vertical one disappears the moment you move the throttle
off centre, independently of each other — so a `POSCTL` segment routinely
shows a solid horizontal setpoint with a broken vertical one. Measured over
the sample logs in this repo, a typical hands-on `POSCTL` flight logs a
horizontal setpoint about 60–95% of the time and a vertical one 1–60%,
depending entirely on how much the pilot was flying it.

So a flight that is mostly stick-flown shows a long blue track with only
short dashed segments where the pilot let go. Because of that, gaps are not
by themselves suspicious and there is no "expected" amount of setpoint
coverage — the RMS error is computed only over the samples where a setpoint
existed, so it describes the held portions and says nothing about the rest.
What *is* worth a look is a gap in an `AUTO_*` or `OFFBOARD` segment, where
the vehicle should be under position control throughout.

## Reading the per-axis plot

The per-axis figure shows commanded vs estimated position for north, east and
altitude, with the **RMS tracking error** over the samples where a setpoint
existed. Only the shape tells you what is wrong:

- **Constant offset** — the vehicle sits a fixed distance off the setpoint.
  Usually a steady disturbance (wind, a CG offset the attitude loop is
  trimming out) that the position loop has no integrator authority to remove,
  or an estimator bias. Check the wind estimate and the airframe layout
  figure before touching gains.
- **Lag that grows with speed** — the actual curve is the setpoint shifted
  right in time. The position loop is under-gained: `MPC_XY_P`, `MPC_Z_P`.
- **Overshoot and ringing after each step** — too much velocity-loop gain
  (`MPC_XY_VEL_P_ACC`, `MPC_Z_VEL_P_ACC`) or too little damping
  (`..._D_ACC`). Fix the *rate and attitude* loops first: the position
  cascade sits on top of them and cannot be tuned around a bad inner loop
  (see [05_autotune.md](05_autotune.md)).
- **Error that only appears when moving fast** — you may simply be at the
  limits set by `MPC_XY_VEL_MAX` / `MPC_ACC_HOR_MAX`, in which case the
  setpoint is being rate-limited and the tracking is fine.

Altitude deserves its own look: a persistent altitude error with a healthy
horizontal one usually points at the thrust model rather than the position
loop — see [03_thrust_curve.md](03_thrust_curve.md) and the hover-thrust
figure.

Absolute numbers depend on how aggressive the flight was. Sub-decimetre RMS
in a hover is unremarkable; the same number through fast waypoints is good.
Judge the shape, not the magnitude.

## The satellite map

The map figure georeferences the local track by converting the NED origin to
WGS-84 with the estimator's `ref_lat` / `ref_lon` and a flat-earth
approximation (exact enough over a flight-sized area). It is **as accurate as
the GNSS fix and the EKF's global alignment, and no more** — a metre-level
offset between the drawn track and what you remember flying is expected, and
imagery is itself only orthorectified to a few metres and may be years old.
Use it for context — which side of the building, how close to the treeline —
not as survey data.

The crop is fetched from Esri's public World Imagery tiles when the report is
generated, then embedded in the report, so the PDF and the web UI show the
same pixels and the browser needs no tile access. The figure is omitted
entirely when the log has no global reference, when the tile server cannot be
reached, or when there is no imagery at a useful zoom for that location.
Set `PX4DOCTOR_NO_NETWORK=1` to skip the fetch; `PX4DOCTOR_TILE_URL`
overrides the tile server.
