"""Metadata-only schema gate for MORPHO FOD7 and COQTEL Corrosion.

This module reads ONLY HDF5 structure (dataset names, shapes, dtypes,
attributes) without dereferencing waveform array values.  It verifies the
frozen v2.6 schema mapping before any external waveform scoring is authorized.

A schema gate failure produces a schema_ineligible record; it does not
authorize waveform access, scoring, or label construction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import h5py

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PROTOCOL_PATH = ROOT / "protocols" / "mechanism_v2_6.json"
MORPHO_PATH = ROOT / "data" / "external" / "mechanism_v2" / "MORPHO_FOD7.h5"
COQTEL_DIR = ROOT / "data" / "external" / "mechanism_v2_1" / "coqtel"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_6_external_schema_gate.json"


def _load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _audit_morpho(mapping: dict[str, Any], h5_path: Path) -> dict[str, Any]:
    """Verify MORPHO HDF5 structure against the frozen mapping."""

    if not h5_path.exists():
        return {"passed": False, "reason": f"File not found: {h5_path}"}

    errors: list[str] = []
    warnings: list[str] = []
    verified: list[str] = []

    try:
        with h5py.File(h5_path, "r") as f:
            # Check active root exists
            active_root = mapping.get("active_root", "/5_Active")
            if active_root not in f:
                return {"passed": False, "reason": f"Active root '{active_root}' not found"}
            verified.append(f"active_root '{active_root}' exists")

            root_group = f[active_root]

            # Enumerate all datasets under active root
            all_datasets = []
            def _collect(name, obj):
                if isinstance(obj, h5py.Dataset):
                    all_datasets.append(name)
            root_group.visititems(_collect)

            # Verify regex matches and expected shapes
            pattern = re.compile(mapping["waveform_dataset_path_regex"])
            matched = 0
            expected_shape = tuple(mapping["expected_waveform_shape"])
            for ds_path in all_datasets:
                full_path = f"{active_root}/{ds_path}"
                m = pattern.match(full_path)
                if m:
                    matched += 1
                    ds = f[full_path]
                    if ds.shape != expected_shape:
                        errors.append(f"Shape mismatch for {full_path}: got {ds.shape}, expected {expected_shape}")

            if matched == 0:
                errors.append("No dataset matched the waveform path regex")
            else:
                verified.append(f"{matched} datasets matched waveform regex")

            # Check baseline blocks exist
            baseline_blocks = mapping.get("baseline_blocks", [])
            for block in baseline_blocks:
                block_path = f"{active_root}/{block}"
                if block_path not in f:
                    errors.append(f"Baseline block '{block}' not found")
                else:
                    verified.append(f"baseline block '{block}' exists")

            # Check Status attribute name is present on at least one block
            status_attr = mapping.get("block_status_attribute", "Status")
            status_found = False
            for block in baseline_blocks:
                block_path = f"{active_root}/{block}"
                if block_path in f:
                    grp = f[block_path]
                    if status_attr in grp.attrs:
                        status_found = True
                        verified.append(f"Status attribute '{status_attr}' found on {block}")
                        break
            if not status_found:
                errors.append(f"Status attribute '{status_attr}' not found on any baseline block")

            # Check sampling rate attribute
            fs_attr = mapping.get("sampling_rate_attribute", "fs")
            fs_found = False
            for block in baseline_blocks:
                block_path = f"{active_root}/{block}"
                if block_path in f:
                    grp = f[block_path]
                    if fs_attr in grp.attrs:
                        fs_found = True
                        verified.append(f"Sampling rate attribute '{fs_attr}' found on {block}")
                        break
            if not fs_found:
                warnings.append(f"Sampling rate attribute '{fs_attr}' not found on baseline blocks (may be deeper)")

            # Check fatigue blocks exist
            fatigue_blocks = mapping.get("fatigue_blocks_order", [])
            found_fatigue = 0
            for block in fatigue_blocks:
                block_path = f"{active_root}/{block}"
                if block_path in f:
                    found_fatigue += 1
                else:
                    warnings.append(f"Fatigue block '{block}' not found")
            verified.append(f"{found_fatigue}/{len(fatigue_blocks)} fatigue blocks found")

    except Exception as e:
        return {"passed": False, "reason": f"HDF5 read error: {e}"}

    passed = len(errors) == 0
    return {
        "passed": passed,
        "dataset": "morpho_fod7",
        "file": str(h5_path),
        "errors": errors,
        "warnings": warnings,
        "verified": verified,
        "reason": None if passed else "; ".join(errors),
    }


def _audit_coqtel(mapping: dict[str, Any], h5_dir: Path) -> dict[str, Any]:
    """Verify COQTEL HDF5 structure against the frozen mapping."""

    campaigns = mapping.get("campaigns", {})
    results = []
    all_passed = True

    for filename, campaign_id in campaigns.items():
        h5_path = h5_dir / filename
        if not h5_path.exists():
            results.append({
                "campaign": campaign_id,
                "file": str(h5_path),
                "passed": False,
                "reason": "File not found",
            })
            all_passed = False
            continue

        errors = []
        verified = []

        try:
            with h5py.File(h5_path, "r") as f:
                # Check EC_data group
                ec_paths = mapping.get("ec_metadata_paths", ["/EC_data/EC_time"])
                for ec_path in ec_paths:
                    if ec_path in f:
                        verified.append(f"{ec_path} exists")
                    else:
                        errors.append(f"{ec_path} not found")

                # Check State_n groups
                state_pattern = re.compile(mapping.get("state_group_path_regex", r"^/State_(?P<state_id>[1-9][0-9]*)$"))
                states = []
                for name in f:
                    m = state_pattern.match(f"/{name}")
                    if m:
                        states.append(name)

                if not states:
                    errors.append("No State_n groups found")
                else:
                    verified.append(f"{len(states)} State_n groups found")

                # Check waveform datasets under first state
                if states:
                    first_state = states[0]
                    wf_pattern = re.compile(mapping.get("waveform_dataset_path_regex", ""))
                    wf_found = False
                    def _check_wf(name, obj):
                        nonlocal wf_found
                        if isinstance(obj, h5py.Dataset):
                            full_path = f"/{first_state}/{name}"
                            if wf_pattern.match(full_path) and not wf_found:
                                wf_found = True
                                expected_shape = tuple(mapping.get("expected_waveform_shape", [5, 2000]))
                                if obj.shape != expected_shape:
                                    errors.append(f"Shape mismatch: {full_path} got {obj.shape}, expected {expected_shape}")
                    f[first_state].visititems(_check_wf)
                    if not wf_found:
                        errors.append("No waveform dataset matched regex under first state")
                    else:
                        verified.append("Waveform dataset found and shape verified")

        except Exception as e:
            errors.append(f"HDF5 read error: {e}")

        passed = len(errors) == 0
        if not passed:
            all_passed = False

        results.append({
            "campaign": campaign_id,
            "file": str(h5_path),
            "passed": passed,
            "errors": errors,
            "verified": verified,
            "reason": "; ".join(errors) if errors else None,
        })

    return {
        "passed": all_passed,
        "dataset": "coqtel_corrosion",
        "campaigns": results,
        "reason": None if all_passed else "One or more campaigns failed schema gate",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_protocol()
    mapping = protocol["external_schema_mappings"]

    morpho_result = _audit_morpho(mapping["morpho_fod7"], MORPHO_PATH)
    coqtel_result = _audit_coqtel(mapping["coqtel_corrosion"], COQTEL_DIR)

    output = {
        "protocol_id": protocol["protocol_id"],
        "test_runner_id": "mechanism-v2.6-external-schema-gate-v1",
        "morpho_fod7": morpho_result,
        "coqtel_corrosion": coqtel_result,
        "authorization": {
            "morpho_waveform_access": morpho_result["passed"],
            "coqtel_waveform_access": False,  # Schema-only qualification, no binary cutoff
            "coqtel_schema_qualification_reported": coqtel_result["passed"],
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"saved {args.output}")
    print(f"MORPHO schema gate: {'PASS' if morpho_result['passed'] else 'FAIL'}")
    print(f"COQTEL schema gate: {'PASS' if coqtel_result['passed'] else 'FAIL'} (qualification only, no scoring)")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
