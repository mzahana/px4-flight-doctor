"""User-supplied physical vehicle specification: mass, motor bench data, battery, environment."""
from dataclasses import dataclass, field

import yaml

RHO_SL = 1.225          # ISA sea-level air density, kg/m^3
R_AIR = 287.05          # specific gas constant of dry air, J/(kg K)


@dataclass
class BenchPoint:
    throttle: float     # 0..1 ESC throttle
    thrust_g: float     # grams per motor
    current_a: float = None
    rpm: float = None


@dataclass
class VehicleSpec:
    mass_kg: float = None
    n_motors: int = 4
    bench_voltage: float = None          # voltage the bench table was measured at
    bench: list = field(default_factory=list)   # list[BenchPoint], sorted by throttle
    prop_thrust_limit_g: float = None    # manufacturer per-prop thrust limit
    motor_peak_current_a: float = None
    battery_cells: int = None
    battery_capacity_mah: float = None
    oat_c: float = None                  # outside air temperature during flight
    notes: str = ""

    @property
    def has_bench(self):
        return self.bench_voltage is not None and len(self.bench) >= 3

    def bench_arrays(self):
        import numpy as np
        pts = sorted(self.bench, key=lambda p: p.throttle)
        thr = np.array([p.throttle for p in pts])
        T = np.array([p.thrust_g for p in pts])
        I = np.array([p.current_a if p.current_a is not None else np.nan for p in pts])
        return thr, T, I


def load_spec(path):
    with open(path) as f:
        raw = yaml.safe_load(f)
    spec = VehicleSpec()
    spec.mass_kg = raw.get("mass_kg")
    spec.n_motors = raw.get("n_motors", 4)
    spec.prop_thrust_limit_g = raw.get("prop_thrust_limit_g")
    spec.motor_peak_current_a = raw.get("motor_peak_current_a")
    spec.battery_cells = raw.get("battery_cells")
    spec.battery_capacity_mah = raw.get("battery_capacity_mah")
    spec.oat_c = raw.get("oat_c")
    spec.notes = raw.get("notes", "")
    bench = raw.get("motor_bench")
    if bench:
        spec.bench_voltage = bench.get("voltage")
        for row in bench.get("points", []):
            thr = row["throttle_pct"] / 100.0 if "throttle_pct" in row else row["throttle"]
            spec.bench.append(BenchPoint(
                throttle=thr,
                thrust_g=row["thrust_g"],
                current_a=row.get("current_a"),
                rpm=row.get("rpm"),
            ))
    return spec


def _ask(prompt, cast=float, optional=True):
    while True:
        raw = input(prompt).strip()
        if not raw:
            if optional:
                return None
            print("  a value is required")
            continue
        try:
            return cast(raw)
        except ValueError:
            print("  could not parse that, try again")


def interactive_spec():
    print("\n-- Vehicle specification (press Enter to skip any item) --")
    spec = VehicleSpec()
    spec.mass_kg = _ask("Takeoff mass [kg]: ")
    spec.n_motors = _ask("Number of motors [4]: ", int) or 4
    spec.battery_cells = _ask("Battery cell count (e.g. 4 for 4S): ", int)
    spec.battery_capacity_mah = _ask("Battery capacity [mAh]: ")
    spec.prop_thrust_limit_g = _ask("Prop thrust limit per motor [g] (from prop datasheet): ")
    spec.motor_peak_current_a = _ask("Motor peak current [A] (from motor datasheet): ")
    spec.oat_c = _ask("Outside air temperature during flight [deg C]: ")
    if input("Do you have a motor bench-test table (thrust vs throttle)? [y/N]: ").lower().startswith("y"):
        spec.bench_voltage = _ask("Bench test voltage [V]: ", optional=False)
        print("Enter rows as: throttle% thrust_g [current_A]   (blank line to finish)")
        while True:
            row = input("  row: ").strip()
            if not row:
                break
            parts = row.replace(",", " ").split()
            try:
                spec.bench.append(BenchPoint(
                    throttle=float(parts[0]) / 100.0,
                    thrust_g=float(parts[1]),
                    current_a=float(parts[2]) if len(parts) > 2 else None,
                ))
            except (ValueError, IndexError):
                print("    could not parse, expected e.g.:  50 447 3.6")
    return spec


def air_density(pressure_pa, oat_c):
    """rho = P / (R T)."""
    return pressure_pa / (R_AIR * (oat_c + 273.15))
