# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
./install.sh                     # creates .venv, pip install -e . (PYTHON=python3.12 ./install.sh to pick an interpreter)

.venv/bin/px4doctor flight.ulg [--vehicle my_drone.yaml] [--mass 2.2] [--oat 35] [--report] [--interactive]
.venv/bin/px4doctor-web          # Flask UI on http://127.0.0.1:8050 (PORT env var overrides)
```

There is no test suite, linter, or CI. The practical smoke test is running the CLI against a
`.ulg` in the repo root and checking the terminal report plus the `errors` section at the bottom
(failed checks are listed there rather than raising). `.ulg` files and `*_report.md/pdf` are
gitignored, so logs used during development stay local.

## Architecture

One analysis pipeline, three front-ends (terminal, Markdown, web+PDF). Both entry points do the
same four steps:

1. `vehicle.load_spec` / `interactive_spec` → `VehicleSpec` — the user's *physical* drone data
   (mass, motor bench table, prop/motor limits, battery, OAT). Every field is optional; checks
   degrade gracefully when a field is `None`.
2. `core.Log` — thin `pyulog` wrapper. `log.get(topic, instance)` returns a cached topic dict or
   `None`, `log.t(data)` converts timestamps to seconds, `log.param(name, default)` reads initial
   params. `in_air_window()` and `hover_mask()` define the flight phases nearly every check uses;
   `mode_spans()` returns the `nav_state` timeline that both plot back-ends shade.
3. `propulsion.hover_state(log)` → dict of measured hover quantities (per-motor PWM, ESC throttle,
   normalized command, pack voltage, current, air density).
4. `checks.run_all(log, spec, hover)` → `(findings, errors)`.

The central premise: bench thrust data is measured at one voltage and sea-level density, so it is
corrected to flight conditions before comparison (`propulsion.correction_factors` → `kv` from
V², `kr` from ρ/ρ_SL). Predicted vs. measured hover throttle/current is what drives most propulsion
findings. The math is documented in `docs/02_propulsion_math.md` and `docs/03_thrust_curve.md`;
keep code and docs in sync when changing formulas, and cite the doc file in `Finding.doc` so the
web UI can link it.

### Findings

`core.Finding(severity, category, title, detail, fixes, doc)` is the only output currency —
`report.py` (terminal via `rich` + Markdown), `pdf.py` (reportlab), and the web JSON payload all
render the same list. `Severity` is an `IntEnum` (OK/INFO/WARNING/CRITICAL) so findings sort and
filter numerically.

**Adding a check**: write `def check_x(log, spec, hover) -> list[Finding]` in `analyzer/checks.py`
and append it to `ALL_CHECKS`. `run_all` wraps each check in try/except, so one raising check
degrades to an entry in `errors` instead of killing the report. Return `[]` when the required topic
is absent — that is the normal way checks handle logs from other airframes/firmware.

### Plots

`plots.py` (matplotlib → SVG+PNG, for the PDF) and `iplots.py` (Plotly figure *specs* as plain
dicts, serialized to JSON for the browser) are deliberate parallel implementations of the same
eight figures. `iplots` imports shared colors and `_autotune_spans` from `plots`. Each builder
returns a tuple and is registered in `ALL_FIGS` / `ALL_IPLOTS`; the generators swallow exceptions
per figure, so a figure that can't be built is simply omitted. Adding a figure usually means
touching both files to keep the web UI and PDF showing the same thing.

### Web app

`analyzer/webapp.py` is a small Flask app with no database: `POST /analyze` writes the upload to a
temp dir, runs the pipeline, deletes the temp dir, and stashes findings/plots/iplots in the
in-process `RESULTS` dict keyed by a random id (lost on restart). The front-end is a single static
`web/index.html`; Plotly is vendored at `web/plotly.min.js` so the UI works offline. `BASE` is
computed as the parent of the `analyzer` package, which is why the install is editable — `web/` and
`docs/` are served from the source tree, not from site-packages.

`analyze.py` and `webapp.py` in the root are thin shims kept for backwards compatibility; the real
code lives in `analyzer/`.
