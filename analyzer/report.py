"""Terminal (rich) and Markdown report rendering."""
from collections import OrderedDict
from datetime import datetime

from .core import Severity

CAT_ORDER = ["Flight", "Autotune", "Propulsion", "Vibration", "EKF", "GPS",
             "Battery", "Compass", "Config", "System"]


def _grouped(findings):
    groups = OrderedDict()
    cats = CAT_ORDER + sorted({f.category for f in findings} - set(CAT_ORDER))
    for c in cats:
        items = [f for f in findings if f.category == c]
        if items:
            groups[c] = sorted(items, key=lambda f: -int(f.severity))
    return groups


def print_terminal(findings, errors, log_path):
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        from rich.markup import escape
    except ImportError:
        _print_plain(findings, errors)
        return
    con = Console()
    counts = {s: sum(1 for f in findings if f.severity == s) for s in Severity}
    head = Text()
    head.append(f"{log_path}\n", style="bold")
    head.append(f"🛑 {counts[Severity.CRITICAL]} critical   ⚠️  {counts[Severity.WARNING]} warnings   "
                f"ℹ️  {counts[Severity.INFO]} info   ✅ {counts[Severity.OK]} ok")
    con.print(Panel(head, title="PX4 Flight Doctor", border_style="cyan"))
    style = {Severity.OK: "green", Severity.INFO: "cyan",
             Severity.WARNING: "yellow", Severity.CRITICAL: "bold red"}
    for cat, items in _grouped(findings).items():
        con.print(f"\n[bold underline]{cat}[/]")
        for f in items:
            con.print(f"  {f.severity.emoji} [{style[f.severity]}]{escape(f.title)}[/]")
            if f.detail:
                for line in f.detail.splitlines():
                    con.print(f"      [dim]{escape(line)}[/]")
            for fix in f.fixes:
                con.print(f"      [magenta]->[/] {escape(fix)}")
            if f.doc:
                con.print(f"      [dim italic]see docs/{f.doc}[/]")
    if errors:
        con.print("\n[red]Some checks failed to run:[/]")
        for e in errors:
            con.print(f"  [red]{e}[/]")


def _print_plain(findings, errors):
    for cat, items in _grouped(findings).items():
        print(f"\n== {cat} ==")
        for f in items:
            print(f"  [{f.severity.label}] {f.title}")
            if f.detail:
                print("      " + f.detail.replace("\n", "\n      "))
            for fix in f.fixes:
                print(f"      -> {fix}")
    for e in errors:
        print(f"CHECK ERROR: {e}")


def write_markdown(findings, errors, log_path, out_path, spec=None):
    lines = ["# PX4 Flight Analysis Report", "",
             f"**Log:** `{log_path}`  ",
             f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}  "]
    if spec and spec.mass_kg:
        lines.append(f"**Takeoff mass:** {spec.mass_kg:.2f} kg  ")
    counts = {s: sum(1 for f in findings if f.severity == s) for s in Severity}
    lines += ["",
              f"| 🛑 Critical | ⚠️ Warning | ℹ️ Info | ✅ OK |",
              "|---|---|---|---|",
              f"| {counts[Severity.CRITICAL]} | {counts[Severity.WARNING]} "
              f"| {counts[Severity.INFO]} | {counts[Severity.OK]} |", ""]
    # action summary first
    actions = [f for f in findings if f.fixes and f.severity >= Severity.WARNING]
    if actions:
        lines += ["## Recommended actions (highest priority first)", ""]
        for i, f in enumerate(sorted(actions, key=lambda x: -int(x.severity)), 1):
            lines.append(f"{i}. **{f.title}**")
            for fix in f.fixes:
                lines.append(f"   - `{fix}`" if fix.startswith("param") else f"   - {fix}")
        lines.append("")
    for cat, items in _grouped(findings).items():
        lines.append(f"## {cat}")
        lines.append("")
        for f in items:
            lines.append(f"### {f.severity.emoji} {f.title}")
            if f.detail:
                lines += ["", f.detail]
            if f.fixes:
                lines.append("")
                lines.append("**Fix:**")
                for fix in f.fixes:
                    lines.append(f"- `{fix}`" if fix.startswith("param") else f"- {fix}")
            if f.doc:
                lines.append(f"\n*Background: [docs/{f.doc}](docs/{f.doc})*")
            lines.append("")
    if errors:
        lines += ["## Analyzer internal errors", ""] + [f"- `{e}`" for e in errors]
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path
