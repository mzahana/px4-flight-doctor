"""Command-line interface for px4-flight-doctor."""
import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="px4doctor",
        description="Analyze a PX4 .ulg flight log against your drone's real physical "
                    "specs and produce an issue/fix report.",
        epilog="Examples:\n"
               "  ./analyze.py flight.ulg\n"
               "  ./analyze.py flight.ulg --mass 2.2\n"
               "  ./analyze.py flight.ulg --vehicle my_drone.yaml --report\n"
               "  ./analyze.py flight.ulg --interactive\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="path to the .ulg log file")
    ap.add_argument("--vehicle", "-v", help="vehicle spec YAML (see vehicle_example.yaml)")
    ap.add_argument("--mass", "-m", type=float, help="takeoff mass in kg (quick alternative to --vehicle)")
    ap.add_argument("--oat", type=float, help="outside air temperature during flight, deg C")
    ap.add_argument("--interactive", "-i", action="store_true",
                    help="answer questions about the vehicle instead of providing a YAML")
    ap.add_argument("--report", "-r", nargs="?", const="", metavar="FILE",
                    help="also write a Markdown report (default: <log>_report.md)")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.log):
        sys.exit(f"error: log file not found: {args.log}")

    from .core import Log
    from .vehicle import VehicleSpec, load_spec, interactive_spec
    from .propulsion import hover_state
    from .checks import run_all
    from .report import print_terminal, write_markdown

    if args.vehicle:
        spec = load_spec(args.vehicle)
    elif args.interactive:
        spec = interactive_spec()
    else:
        spec = VehicleSpec()
    if args.mass is not None:
        spec.mass_kg = args.mass
    if args.oat is not None:
        spec.oat_c = args.oat

    print(f"Parsing {args.log} ...")
    log = Log(args.log)
    hover = hover_state(log)
    findings, errors = run_all(log, spec, hover)
    print_terminal(findings, errors, args.log)

    if args.report is not None:
        out = args.report or os.path.splitext(args.log)[0] + "_report.md"
        write_markdown(findings, errors, args.log, out, spec)
        print(f"\nMarkdown report written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
