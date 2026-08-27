# Reading the Report

The analyzer groups findings into categories and ranks them by severity:

| Icon | Meaning |
|---|---|
| 🛑 CRITICAL | Actively degrading flight safety or making tuning results invalid. Fix before the next tuning flight. |
| ⚠️ WARNING | Costing performance, endurance, or data quality. Fix soon. |
| ℹ️ INFO | Context, measurements, or an optional improvement. |
| ✅ OK | Checked and healthy — listed so you know it was verified. |

Two rules of thumb when acting on a report:

1. **Fix physics before parameters.** Vibration, mass balance, and thrust
   headroom problems corrupt every downstream tuning step. A perfect PID tune
   on a vibrating, saturated airframe is still a bad tune.
2. **One change per flight** when possible. If you change five parameters and
   the next flight is worse, you learn nothing.

Every finding that has deeper math behind it links to one of the docs in this
folder. They use real numbers from an example drone (Holybro X500 V2, 2.2 kg,
AIR2216II motors, T1045II props) so you can follow along with a calculator.
