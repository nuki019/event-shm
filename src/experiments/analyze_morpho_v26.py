#!/usr/bin/env python3
"""Quick analysis of MORPHO v2.6 confirmation results."""
import json
from pathlib import Path

RESULT = Path(__file__).resolve().parents[2] / "results" / "mechanism_v2_6_morpho_confirmation.json"


def analyze():
    if not RESULT.exists():
        print("Result file not yet available.")
        return

    data = json.loads(RESULT.read_text())
    grid = data["grid_results"]

    print("=" * 60)
    print("MORPHO v2.6 Confirmation Results Summary")
    print("=" * 60)

    # AUC table
    print("\n--- AUC by (capacity, delta) ---")
    print(f"{'Capacity':>10} {'Delta':>8} {'Global AUC':>12} {'Max-path AUC':>14} {'Status'}")
    print("-" * 55)
    for cell in grid:
        cap = cell["capacity_bytes"]
        delta = cell["delta_codes"]
        global_auc = cell["event_diagnostic"]["global"]["roc_auc"]
        max_auc = cell["event_diagnostic"]["max_path"]["roc_auc"]
        status = "PASS" if global_auc > 0.7 else "FAIL"
        print(f"{cap:>10} {delta:>8} {global_auc:>12.3f} {max_auc:>14.3f} {status}")

    # Outcome determination
    all_global = [cell["event_diagnostic"]["global"]["roc_auc"] for cell in grid]
    best_global = max(all_global)
    print(f"\nBest global AUC: {best_global:.3f}")
    if best_global > 0.7:
        print("→ Outcome A: Event-native features recover separation on MORPHO")
    else:
        print("→ Outcome B: Information loss confirmed on MORPHO")

    # Cap evidence
    print("\n--- Capacity compliance ---")
    for cell in grid:
        cap = cell["capacity_bytes"]
        delta = cell["delta_codes"]
        ev = cell["cap_evidence"]
        print(f"  ({cap}, {delta}): within_cap={ev['all_component_packets_within_declared_capacity']}, "
              f"mean_bytes={ev['mean_bytes_per_component_packet']:.1f}, "
              f"max_bytes={ev['maximum_bytes_per_component_packet']}, "
              f"sat_frac={ev['cap_saturated_path_fraction']:.3f}")

    # Mechanism probes
    print("\n--- Mechanism probes ---")
    probes = data.get("mechanism_probes", [])
    for probe in probes:
        if probe["proposition"] == "quantization_collision":
            print(f"  ({probe['capacity_bytes']}, {probe['delta_codes']}): collision={probe['status']}")
        elif probe["proposition"] == "terminal_hold":
            print(f"  ({probe['capacity_bytes']}, {probe['delta_codes']}): terminal_hold={probe['status']}")

    # Control injections
    print("\n--- Control injections (sample) ---")
    injections = data.get("control_injections", [])
    for inj in injections[:3]:
        print(f"  {inj['family']} amp={inj['amplitude_delta_multiplier']}: "
              f"payload_identical={inj['mean_payload_identical_fraction']:.3f}, "
              f"event_delta={inj['mean_event_count_difference']:.2f}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    analyze()
