# Vibration, Sampling, and Notch Filters

## Why vibration matters

The rate controller's D-term differentiates gyro data — differentiation
amplifies high frequency noise by the frequency itself. Vibration also:

- **Clips the accelerometer** (the signal hits sensor full-scale). Clipping
  is not noise — it is data loss, and it biases the EKF's velocity/position.
- Corrupts autotune's system-ID (the model fits vibration instead of dynamics).
- Heats motors through constant micro-corrections.

## The numbers to look at

| Metric | OK | Investigate |
|---|---|---|
| accel vibration metric (`vehicle_imu_status`) | < 5 | > 10 |
| in-flight accel σ per axis | < 2 m/s² | > 4 m/s² |
| accel clipping counter | 0 | any |
| imbalanced-prop metric | < 5 | > 10 |

## Reading an FFT

Take the in-flight accel/gyro signal, remove the mean, apply a window,
FFT it. Peaks tell you *what* vibrates:

- Peak at the **prop rotation frequency** (RPM/60): unbalanced prop or bent
  shaft. Example: 8100 RPM hover → 135 Hz. A peak at ~66 Hz with 8000 RPM
  motors is *not* the props — look for a structural resonance (payload
  mount, landing gear, GPS mast) or a sub-harmonic.
- Peak at **2× rotation**: blade tracking / aerodynamic asymmetry.
- Broad noise floor rising: loose fasteners, frame flex.

## Nyquist and aliasing (why sample rate matters)

A signal sampled at F_s can only represent content below **F_s/2** (the
Nyquist frequency). Energy above it doesn't disappear — it **aliases**:
folds back to a false low frequency the controller will chase. With
`IMU_INTEG_RATE = 200` Hz the control loop sees only 0–100 Hz, and a real
120 Hz vibration shows up as a fake 80 Hz one. If you have strong content
near Nyquist, raise the integrator rate (e.g. 400 Hz) *and* fix the source.

## Filters: the toolbox

- **Low-pass** (`IMU_GYRO_CUTOFF`, `IMU_DGYRO_CUTOFF`): attenuates everything
  above the cutoff, but adds **phase lag** — lag destabilizes the loop, so
  you can't just lower the cutoff forever.
- **Static notch** (`IMU_GYRO_NF0_FRQ/BW`): surgically removes one narrow
  band with little phase cost elsewhere. Perfect for a fixed structural
  resonance you found in the FFT.
- **Dynamic notch** (`IMU_GYRO_DNF_EN`): tracks motor RPM (needs ESC
  telemetry/bidirectional DShot) or an onboard FFT, and moves the notch with
  the props. Best choice for prop-order vibration.

Order of attack: **mechanics first** (balance props, tighten, soft-mount the
FC and heavy payloads), then notch the residual, and only then consider
lowering low-pass cutoffs.
