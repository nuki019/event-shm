"""Produce the last v2.4 readiness receipt before any E9 scoring starts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.e9_mechanism_v2_4_ogw import MIN_AVAILABLE_MEMORY_BYTES, available_memory_bytes
from src.experiments.mechanism_v2_4_successor import ROOT, V24Error, load_json, resolve_within_root, sha256_file, verify_v24_freeze


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_4_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_4_preexperiment_audit.json"
SOURCE_RECEIPTS = {
    "ogw_cfrp_temperature_dam_d12": ROOT / "results" / "mechanism_v2_4_ogw_d12_source_receipt.json",
    "ogw_cfrp_temperature_dam_d16": ROOT / "results" / "mechanism_v2_4_ogw_d16_source_receipt.json",
    "morpho_fod7": ROOT / "results" / "mechanism_v2_4_morpho_source_receipt.json",
    "coqtel_corrosion": ROOT / "results" / "mechanism_v2_4_coqtel_source_receipt.json",
}
SCHEMA_RECEIPTS = {
    "morpho_fod7": ROOT / "results" / "mechanism_v2_4_morpho_schema_gate.json",
    "coqtel_corrosion": ROOT / "results" / "mechanism_v2_4_coqtel_schema_gate.json",
}


class PreflightError(RuntimeError):
    """Raised when a pre-experiment v2.4 invariant is missing or corrupted."""


def _source_receipt(path: Path, dataset_id: str, protocol_path: Path, manifest_path: Path, freeze_path: Path) -> dict[str, Any]:
    receipt = load_json(path)
    if receipt.get("protocol_id") != "mechanism-v2.4" or receipt.get("dataset_id") != dataset_id:
        raise PreflightError(f"source receipt has wrong identity: {path}")
    if receipt.get("waveform_access_permitted") is not True or receipt.get("raw_byte_hashing_only") is not True:
        raise PreflightError(f"source receipt does not preserve the raw-byte pre-access boundary: {path}")
    expected = {
        "protocol_sha256": sha256_file(protocol_path),
        "data_manifest_sha256": sha256_file(manifest_path),
        "freeze_receipt_sha256": sha256_file(freeze_path),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise PreflightError(f"source receipt is not bound to current v2.4 freeze: {path}")
    return receipt


def _schema_receipt(path: Path, dataset_id: str, protocol_path: Path, manifest_path: Path, freeze_path: Path) -> dict[str, Any]:
    receipt = load_json(path)
    data = receipt.get("data")
    selection = receipt.get("selection_receipt")
    if receipt.get("protocol_id") != "mechanism-v2.4" or not isinstance(data, dict) or data.get("dataset_id") != dataset_id:
        raise PreflightError(f"schema receipt has wrong identity: {path}")
    if receipt.get("protocol_sha256") != sha256_file(protocol_path) or receipt.get("data_manifest_sha256") != sha256_file(manifest_path):
        raise PreflightError(f"schema receipt is not bound to current v2.4 protocol/manifest: {path}")
    if receipt.get("freeze_receipt_sha256") != sha256_file(freeze_path):
        raise PreflightError(f"schema receipt is not bound to current v2.4 freeze: {path}")
    if not isinstance(selection, dict) or any(selection.get(key) is not False for key in ("waveform_scoring_started", "waveform_values_read", "metadata_values_read", "attribute_values_read")):
        raise PreflightError(f"schema receipt crossed the no-value/no-score boundary: {path}")
    return receipt


def _absence(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)), "exists": path.exists()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--calibration-binding", type=Path, default=ROOT / "results" / "mechanism_v2_4_ogw_udam_calibration_binding.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.protocol = resolve_within_root(args.protocol, "v2.4 preflight protocol")
        args.manifest = resolve_within_root(args.manifest, "v2.4 preflight manifest")
        args.freeze_receipt = resolve_within_root(args.freeze_receipt, "v2.4 preflight freeze receipt")
        args.calibration_binding = resolve_within_root(args.calibration_binding, "v2.4 calibration binding")
        args.output = resolve_within_root(args.output, "v2.4 preflight output", must_exist=False)
        if args.output.exists():
            raise PreflightError(f"refusing to overwrite pre-experiment audit: {args.output}")
        protocol = verify_v24_freeze(args.protocol, args.manifest, args.freeze_receipt)
        source = {
            dataset_id: _source_receipt(resolve_within_root(path, f"v2.4 {dataset_id} source receipt"), dataset_id, args.protocol, args.manifest, args.freeze_receipt)
            for dataset_id, path in SOURCE_RECEIPTS.items()
        }
        calibration = _source_receipt(args.calibration_binding, "ogw_cfrp_temperature_udam", args.protocol, args.manifest, args.freeze_receipt)
        schema = {
            dataset_id: _schema_receipt(resolve_within_root(path, f"v2.4 {dataset_id} schema receipt"), dataset_id, args.protocol, args.manifest, args.freeze_receipt)
            for dataset_id, path in SCHEMA_RECEIPTS.items()
        }
        e9_outputs = {
            "D12": ROOT / "results" / "mechanism_v2_4_ogw_d12_confirmation.json",
            "D16": ROOT / "results" / "mechanism_v2_4_ogw_d16_confirmation.json",
        }
        e9_caches = {
            "D12": ROOT / "data" / "interim" / "mechanism_v2_4_ogw_d12",
            "D16": ROOT / "data" / "interim" / "mechanism_v2_4_ogw_d16",
        }
        result = {
            "audit_id": "mechanism-v2.4-preexperiment-readiness-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_sha256": sha256_file(args.manifest),
            "freeze_receipt_sha256": sha256_file(args.freeze_receipt),
            "outcome_type": "preexperiment_readiness_only",
            "source_receipts": {key: str(SOURCE_RECEIPTS[key].relative_to(ROOT)) for key in source},
            "schema_gate_status": {key: value.get("schema_gate", {}).get("status") for key, value in schema.items()},
            "coqtel_binary_scoring_eligibility": schema["coqtel_corrosion"].get("schema_gate", {}).get("binary_scoring_eligibility"),
            "memory_gate": {
                "available_physical_memory_bytes": available_memory_bytes(),
                "minimum_required_bytes": MIN_AVAILABLE_MEMORY_BYTES,
                "passed": available_memory_bytes() >= MIN_AVAILABLE_MEMORY_BYTES,
            },
            "one_shot_absence_check": {
                "confirmation_outputs": {condition: _absence(path) for condition, path in e9_outputs.items()},
                "v2_4_cache_directories": {condition: _absence(path) for condition, path in e9_caches.items()},
            },
            "authorization_boundary": {
                "e7_e8_immutable_historical_evidence": True,
                "d04_d24_discovery_only": True,
                "all_v2_1_v2_2_v2_3_receipts_history_only": True,
                "waveform_scoring_started": False,
                "e9_started": False,
                "external_waveform_values_read": False,
                "pod_or_field_far_reporting_authorized": False,
                "hardware_or_power_reporting_authorized": False,
            },
            "next_authorized_action_if_user_requests_execution": {
                "D12": "Run the frozen v2.4 E9 wrapper exactly once with the D12 v2.4 source receipt, then run the v2.4 result audit.",
                "D16": "Run the frozen v2.4 E9 wrapper exactly once with the D16 v2.4 source receipt, then run the v2.4 result audit.",
                "external": "Only begin the separately frozen external score runner after its required v2.4 schema receipt is passed; do not activate COPV because a passed schema gate cannot be replaced for performance.",
            },
            "data_hashes_recorded": {
                key: [item.get("sha256") for item in value.get("archive_and_content_hashes", [])]
                for key, value in {**source, "ogw_cfrp_temperature_udam": calibration}.items()
            },
        }
        if not result["memory_gate"]["passed"]:
            raise PreflightError("available physical memory is below the frozen 8 GiB E9 threshold")
        if any(entry["exists"] for entry in result["one_shot_absence_check"]["confirmation_outputs"].values()) or any(
            entry["exists"] for entry in result["one_shot_absence_check"]["v2_4_cache_directories"].values()
        ):
            raise PreflightError("v2.4 one-shot output/cache namespace is already occupied")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (PreflightError, V24Error, OSError) as error:
        print(f"MECHANISM-V2.4 PRE-EXPERIMENT AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
