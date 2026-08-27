#!/usr/bin/env python3
"""Web UI for px4-flight-doctor.

Run:  .venv/bin/python webapp.py     then open http://127.0.0.1:8050
"""
import io
import os
import tempfile
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory, abort

from analyzer.core import Log, Severity
from analyzer.vehicle import VehicleSpec, load_spec
from analyzer.propulsion import hover_state
from analyzer.checks import run_all
from analyzer.summary import flight_summary
from analyzer.pdf import build_pdf
from analyzer.plots import generate_all
from analyzer.iplots import generate_interactive

# repo root = parent of the analyzer package (web/ and docs/ live there)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
RESULTS = {}          # id -> {findings, errors, meta}


@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "web"), "index.html")


@app.get("/docs/<name>")
def doc(name):
    if "/" in name or not name.endswith(".md"):
        abort(404)
    path = os.path.join(BASE, "docs", name)
    if not os.path.isfile(path):
        abort(404)
    with open(path) as f:
        return f.read(), 200, {"Content-Type": "text/markdown; charset=utf-8"}


@app.post("/analyze")
def analyze():
    up = request.files.get("log")
    if not up or not up.filename:
        return jsonify(error="no .ulg file uploaded"), 400
    spec = VehicleSpec()
    vf = request.files.get("vehicle")
    tmpdir = tempfile.mkdtemp(prefix="px4doctor_")
    try:
        if vf and vf.filename:
            vpath = os.path.join(tmpdir, "vehicle.yaml")
            vf.save(vpath)
            spec = load_spec(vpath)
        for field, attr, cast in (("mass", "mass_kg", float), ("oat", "oat_c", float),
                                  ("cells", "battery_cells", int),
                                  ("capacity", "battery_capacity_mah", float)):
            v = request.form.get(field, "").strip()
            if v:
                setattr(spec, attr, cast(v))
        lpath = os.path.join(tmpdir, "flight.ulg")
        up.save(lpath)
        log = Log(lpath)
        hover = hover_state(log)
        findings, errors = run_all(log, spec, hover)
        try:
            summary = flight_summary(log, spec, hover)
        except Exception as e:      # the dashboard is never worth failing the run over
            summary = {"items": [], "modes": [], "header": {},
                       "error": f"{type(e).__name__}: {e}"}
        plots = generate_all(log, spec)          # static PNG/SVG for the PDF
        iplots = generate_interactive(log, spec)  # plotly specs for the UI
        w = log.in_air_window()
        meta = {"log": up.filename, "mass_kg": spec.mass_kg,
                "duration": (w[1] - w[0]) if w else None}
    except Exception as e:
        return jsonify(error=f"failed to analyze: {type(e).__name__}: {e}"), 422
    finally:
        for f in os.listdir(tmpdir):
            os.unlink(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)
    rid = uuid.uuid4().hex[:12]
    RESULTS[rid] = {"findings": findings, "errors": errors, "meta": meta,
                    "plots": plots, "iplots": iplots, "summary": summary}
    counts = {s.label: sum(1 for f in findings if f.severity == s) for s in Severity}
    return jsonify(
        id=rid, meta=meta, counts=counts, errors=errors, summary=summary,
        plots=[{"id": pl["id"], "title": pl["title"], "caption": pl["caption"]} for pl in iplots],
        findings=[{
            "severity": int(f.severity), "severity_label": f.severity.label,
            "category": f.category, "title": f.title, "detail": f.detail,
            "fixes": f.fixes, "doc": f.doc,
        } for f in findings])


@app.get("/report/<rid>/plotly/<pid>.json")
def plotly_json(rid, pid):
    r = RESULTS.get(rid)
    if not r:
        abort(404)
    for pl in r["iplots"]:
        if pl["id"] == pid:
            return jsonify(pl["spec"])
    abort(404)


@app.get("/asset/<name>")
def asset(name):
    if name not in ("plotly.min.js",):
        abort(404)
    return send_from_directory(os.path.join(BASE, "web"), name)


@app.get("/report/<rid>/pdf")
def report_pdf(rid):
    r = RESULTS.get(rid)
    if not r:
        abort(404)
    pdf = build_pdf(r["findings"], r["errors"], r["meta"], r.get("plots"))
    name = os.path.splitext(r["meta"]["log"])[0] + "_report.pdf"
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name=name)


def main():
    port = int(os.environ.get("PORT", 8050))
    print(f"px4-flight-doctor web UI -> http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
