# px4-flight-doctor

Analyzes a PX4 `.ulg` flight log **together with your drone's real physical
specs** (mass, motor bench data, prop ratings) and produces a prioritized
report of issues, fixes, and parameter recommendations.

Unlike a generic log viewer, it reconciles the log against physics: it
corrects your motor bench table for the actual pack voltage and air density
of the flight, predicts what hover throttle and current *should* have been,
and tells you whether the hardware is healthy or under-performing — plus
autotune quality analysis, vibration/FFT, EKF health, and config sanity
checks.

## Installation (once)

```bash
git clone <your-repo-url> px4-flight-doctor
cd px4-flight-doctor
./install.sh
```

`install.sh` creates a local virtualenv (`.venv`), installs all dependencies
and the package, and prints the two commands you'll use. Nothing is touched
outside this folder. To use a specific interpreter: `PYTHON=python3.12 ./install.sh`.

Activate once per shell (or keep using the `.venv/bin/` prefix):

```bash
source .venv/bin/activate
```

Manual alternative (any platform): `python3 -m venv .venv && .venv/bin/pip install -e .`

## Usage

### Web UI (recommended)

```bash
px4doctor-web
# open http://127.0.0.1:8050
```

Drag in the `.ulg`, optionally attach a vehicle YAML or type mass / OAT /
battery fields, and click **Analyze**. The results open with a **flight
dashboard** (duration, altitude, speed, distance, tilt, pack voltage/sag,
current, energy used, GPS quality, hover operating point, plus a flight-mode
time bar), then tabs for **Actions**, **Findings** and **Plots**. The
findings render as color-coded
cards (filterable by severity, with a prioritized action list and in-app
background docs) plus **interactive annotated plots** (Plotly, vendored
locally - works offline): drag to box-zoom, scroll to zoom, double-click to
reset, click legend entries to hide/show individual traces. The
**Download PDF** button exports a structured PDF with static versions of the
same figures embedded.

Plots: flight overview (altitude / cell voltage / current), **trajectory
plots** (a top-down plan view and a 3D view in the local NED frame, the same
track georeferenced onto a **satellite crop** of the flight area, and a
per-axis north/east/altitude **setpoint-vs-actual** panel with the RMS tracking
error), an **airframe
layout diagram** (top view of the rotor positions, numbering and CW/CCW spin
directions from the CA_ROTOR* geometry, with arm dimensions and the
thrust-weighted **estimated CG** marked when the log contains a quasi-static
hover), per-motor
commands with saturation & headroom annotations, rate tracking per axis,
raw accelerometer and gyro time series (all three axes),
in-flight vibration spectra (FFT with dominant peak, Nyquist and LPF
markers), an **acceleration power spectral density** map (2D frequency-vs-time
response of the raw accel, summed over x/y/z - yellow = strong) and a
per-axis gyro **spectrogram** of the same kind, and autotune convergence
(model variance vs threshold + gain evolution) - every time plot is tinted by
flight mode (mode name printed above the window) with autotune phases shaded
on top - plus a **hover-thrust** plot (PX4's own estimate with its 1-sigma
band against the configured MPC_THR_HOVER), and
magnetic-field-vs-current and battery V-I resistance scatter plots.

### Command line

```bash
# quick look, no specs needed
px4doctor flight.ulg

# add takeoff mass for thrust/weight analysis
px4doctor flight.ulg --mass 2.2 --oat 35

# full analysis with a vehicle file, plus a Markdown report
px4doctor flight.ulg --vehicle my_drone.yaml --report

# don't like YAML? answer questions instead
px4doctor flight.ulg --interactive
```

(`analyze.py` and `webapp.py` still work as direct scripts if you prefer.)

Copy `vehicle_example.yaml` (pre-filled for a Holybro X500 V2) and edit it
for your drone. Every field is optional — more fields unlock deeper checks.

## What it checks

| Category | Checks |
|---|---|
| Autotune | whether the log contains an autotune run at all, state sequence, per-axis convergence time, estimate stability at hand-off, gain sanity |
| Propulsion | hover throttle vs bench prediction (voltage+density corrected), thrust/weight, motor saturation, PWM ceiling clipping, per-motor thrust in grams, yaw-bias / CG imbalance (hover-gated, wind-aware, any multirotor geometry via CA_ROTOR*), THR_MDL_FAC fit, current prediction |
| Hover thrust | PX4's `hover_thrust_estimate` vs MPC_THR_HOVER, and vs the bench-predicted hover throttle |
| Vibration | IMU metrics, accel clipping, FFT peak identification, notch filter config, imbalanced-prop metric |
| EKF | innovation test ratios, fault/timeout flags, in-flight resets |
| GPS | satellites, fix, accuracy, jamming/spoofing |
| Battery | cell sag, capacity/R_internal params, endurance estimate, MC_BAT_SCALE_EN |
| Compass | field strength & inclination vs world model |
| Config | rangefinder/optical-flow enabled but silent, control-allocation geometry symmetry |
| System | CPU, 5V rail, RC link, logger dropouts, estimator time-slip |
| Control | rate-tracking RMS error, sustained-oscillation detector |
| Correlations | mag-field vs thrust/current (power interference), \|B\| vs heading (cal quality), battery internal-resistance fit from V-I scatter, hover g/W efficiency, IMU bias vs estimator limits |

## Docs — the math behind the tuning

| File | Explains |
|---|---|
| [docs/01_reading_the_report.md](docs/01_reading_the_report.md) | severities, how to act on findings |
| [docs/02_propulsion_math.md](docs/02_propulsion_math.md) | hover throttle, T/W, headroom, voltage & density corrections (worked example) |
| [docs/03_thrust_curve.md](docs/03_thrust_curve.md) | THR_MDL_FAC, throttle-dependent gain, battery scaling, MPC_THR_HOVER |
| [docs/04_vibration_filters.md](docs/04_vibration_filters.md) | reading FFTs, Nyquist/aliasing, low-pass vs notch filters |
| [docs/05_autotune.md](docs/05_autotune.md) | how autotune's system-ID works, what corrupts it, gain forms |
| [docs/06_ekf_health.md](docs/06_ekf_health.md) | innovations, test ratios, resets, magnetometer sanity |
| [docs/07_correlations.md](docs/07_correlations.md) | mag-vs-current interference, internal-resistance fitting, g/W efficiency, IMU bias limits |

## Abbreviations

### General

| Term | Meaning |
|---|---|
| **PX4** | Open-source flight control firmware this tool analyzes logs from |
| **ULog / `.ulg`** | PX4's binary flight-log format |
| **CLI** | Command-line interface |
| **UI** | User interface (here: the browser front-end) |
| **YAML** | The human-readable config format used for `vehicle.yaml` |
| **FC** | Flight controller (the autopilot board, e.g. Pixhawk FMUv6X) |
| **FMU** | Flight Management Unit — the autopilot hardware family/revision |
| **RC** | Radio control (pilot's transmitter link) |
| **RSSI** | Received Signal Strength Indicator (RC/telemetry link quality) |
| **SD** | Secure Digital (the card logs are written to) |

### Airframe and propulsion

| Term | Meaning |
|---|---|
| **AUW** | All-Up Weight — total takeoff mass including battery and payload |
| **T/W** | Thrust-to-Weight ratio — max total thrust ÷ weight |
| **CG** | Center of Gravity |
| **ESC** | Electronic Speed Controller — drives each motor |
| **PWM** | Pulse-Width Modulation — the µs-width signal PX4 sends to each ESC (1000–2000 µs) |
| **RPM** | Revolutions Per Minute |
| **KV** | Motor velocity constant — RPM per volt with no load |
| **g/W** | Grams of thrust per watt — hover efficiency metric |
| **Headroom** | Unused control authority between hover thrust and motor saturation |
| **Bench table** | Manufacturer's measured thrust/current vs throttle for one motor+prop |

### Power

| Term | Meaning |
|---|---|
| **LiPo** | Lithium-Polymer battery |
| **4S / 6S** | Cell count in series (4S = 4 cells ≈ 14.8 V nominal) |
| **mAh** | Milliamp-hour — battery capacity |
| **SOC** | State of Charge — remaining battery percentage |
| **DoD** | Depth of Discharge — how much capacity is actually used |
| **R_internal** | Battery internal resistance (mΩ per cell) — causes voltage sag under load |
| **V_oc** | Open-circuit voltage — pack voltage with no current drawn |

### Sensors and estimation

| Term | Meaning |
|---|---|
| **IMU** | Inertial Measurement Unit — accelerometer + gyroscope |
| **EKF / EKF2** | Extended Kalman Filter — PX4's state estimator |
| **Innovation** | Difference between a sensor reading and the EKF's prediction of it |
| **Test ratio** | Normalized innovation; > 1.0 means the measurement was rejected |
| **GNSS / GPS** | Global Navigation Satellite System |
| **EPH / EPV** | Estimated Position error, Horizontal / Vertical (metres) |
| **HDOP** | Horizontal Dilution Of Precision — GPS geometry quality |
| **AGL / MSL** | Above Ground Level / Mean Sea Level (altitude references) |
| **HAGL** | Height Above Ground Level (from a rangefinder) |
| **Mag** | Magnetometer (compass) |
| **WMM** | World Magnetic Model — reference field strength/inclination for a location |
| **G / mG** | Gauss / milligauss — magnetic field strength units |
| **LiDAR** | Laser rangefinder used for height above terrain |

### Control and tuning

| Term | Meaning |
|---|---|
| **PID** | Proportional-Integral-Derivative controller |
| **System-ID** | System Identification — fitting a dynamic model from measured response |
| **Autotune** | PX4's automated system-ID + PID gain calculation routine |
| **FFT** | Fast Fourier Transform — converts a time signal to its frequency spectrum |
| **Nyquist** | Highest frequency representable at a given sample rate (F_s ÷ 2) |
| **LPF** | Low-Pass Filter |
| **DNF** | Dynamic Notch Filter — a notch that tracks motor RPM |
| **RMS** | Root Mean Square — magnitude of an error signal |
| **HTE** | Hover Thrust Estimate — PX4's online estimate of hover thrust |
| **Allocator** | Control allocation: converts desired torque/thrust into per-motor commands |

### Atmosphere

| Term | Meaning |
|---|---|
| **OAT** | Outside Air Temperature |
| **ISA** | International Standard Atmosphere (15 °C, 101325 Pa at sea level) |
| **SL** | Sea Level |
| **ρ (rho)** | Air density (kg/m³) — thrust is proportional to it |
| **Density altitude** | Altitude at which ISA density equals the actual local density |

### PX4 parameter prefixes

| Prefix | Covers |
|---|---|
| `MC_` | Multicopter attitude/rate controller gains |
| `MPC_` | Multicopter position/velocity controller |
| `EKF2_` | State estimator configuration |
| `CA_` | Control Allocation — frame geometry and rotor layout |
| `IMU_` | IMU filtering (low-pass, notch) |
| `BAT1_` | Battery 1 monitoring and capacity |
| `SENS_` | Sensor drivers enable/config |
| `PWM_MAIN_` / `PWM_AUX_` | Output channel function and µs range |
| `THR_` | Thrust model |
| `COM_` | Commander — arming, failsafes, mode logic |
| `SDLOG_` | Logging profile and backend |

## Layout

```
pyproject.toml           package definition (pip-installable, console commands)
install.sh               one-shot installer (venv + deps + package)
analyze.py               CLI entry point (script form of `px4doctor`)
webapp.py                web UI launcher (script form of `px4doctor-web`)
vehicle_example.yaml     vehicle spec template (X500 V2 numbers pre-filled)

analyzer/
  core.py                log wrapper, Finding/Severity, flight phases
  vehicle.py             vehicle spec loading (YAML / interactive)
  propulsion.py          bench-table physics, THR_MDL_FAC fit
  checks.py              all analysis checks
  trajectory.py          trajectory extraction + satellite basemap fetching
  plots.py               static matplotlib figures (for PDF export)
  iplots.py              interactive Plotly figure specs (for the web UI)
  summary.py             at-a-glance flight stats for the web dashboard
  report.py              terminal + Markdown rendering
  pdf.py                 structured PDF generation (reportlab)
  webapp.py              the Flask app
  cli.py                 argument parsing

web/
  index.html             single-page front-end
  plotly.min.js          vendored Plotly (keeps the UI fully offline)

docs/                    tuning math explained (see table above)
```

Adding a check: write a function in `analyzer/checks.py` returning
`list[Finding]` and append it to `ALL_CHECKS`. A crashing check is reported
at the bottom of the output but never kills the rest of the report.
