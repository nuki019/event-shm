"""Produce the final v2.5 readiness receipt before any one-shot runner starts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.e9_mechanism_v2_5_ogw import MIN_AVAILABLE_MEMORY_BYTES, available_memory_bytes
from src.experiments.mechanism_v2_5_successor import ROOT, V25Error, load_json, resolve_within_root, sha256_file, verify_v25_freeze


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_5.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_5_data_manifest.json"
DEFAULT_FREEZE = ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_5_preexperiment_audit.json"
SOURCE_RECEIPTS = {
    "ogw_cfrp_temperature_dam_d12": ROOT / "results" / "mechanism_v2_5_ogw_d12_source_receipt.json",
    "ogw_cfrp_temperature_dam_d16": ROOT / "results" / "mechanism_v2_5_ogw_d16_source_receipt.json",
    "morpho_fod7": ROOT / "results" / "mechanism_v2_5_morpho_source_receipt.json",
    "coqtel_corrosion": ROOT / "results" / "mechanism_v2_5_coqtel_source_receipt.json",
}
SCHEMA_RECEIPTS = {
    "morpho_fod7": ROOT / "results" / "mechanism_v2_5_morpho_schema_gate.json",
    "coqtel_corrosion": ROOT / "results" / "mechanism_v2_5_coqtel_schema_gate.json",
}


class PreflightError(RuntimeError):
    """Raised when a v2.5 pre-experiment invariant is missing or corrupted."""


def _source_receipt(path: Path, dataset_id: str, protocol_path: Path, manifest_path: Path, freeze_path: Path) -> dict[str, Any]:
    receipt = load_json(path)
    expected = {"protocol_sha256": sha256_file(protocol_path), "data_manifest_sha256": sha256_file(manifest_path), "freeze_receipt_sha256": sha256_file(freeze_path)}
    if receipt.get("protocol_id") != "mechanism-v2.5" or receipt.get("dataset_id") != dataset_id or receipt.get("waveform_access_permitted") is not True or receipt.get("raw_byte_hashing_only") is not True:
        raise PreflightError(f"source receipt has wrong identity or pre-access boundary: {path}")
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise PreflightError(f"source receipt is not bound to the v2.5 freeze: {path}")
    return receipt


def _schema_receipt(path: Path, dataset_id: str, protocol_path: Path, manifest_path: Path, freeze_path: Path) -> dict[str, Any]:
    receipt = load_json(path)
    data, selection, gate = receipt.get("data"), receipt.get("selection_receipt"), receipt.get("schema_gate")
    if receipt.get("protocol_id") != "mechanism-v2.5" or not isinstance(data, dict) or data.get("dataset_id") != dataset_id:
        raise PreflightError(f"schema receipt has wrong identity: {path}")
    if receipt.get("protocol_sha256") != sha256_file(protocol_path) or receipt.get("data_manifest_sha256") != sha256_file(manifest_path) or receipt.get("freeze_receipt_sha256") != sha256_file(freeze_path):
        raise PreflightError(f"schema receipt is not bound to v2.5 freeze: {path}")
    if not isinstance(selection, dict) or any(selection.get(key) is not False for key in ("waveform_scoring_started", "waveform_values_read", "metadata_values_read", "attribute_values_read")):
        raise PreflightError(f"schema receipt crossed the no-value/no-score boundary: {path}")
    if not isinstance(gate, dict) or gate.get("status") != "passed":
        raise PreflightError(f"schema receipt did not pass: {path}")
    return receipt


def _absence(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)), "exists": path.exists()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--calibration-binding", type=Path, default=ROOT / "results" / "mechanism_v2_5_ogw_udam_calibration_binding.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol_path = resolve_within_root(args.protocol, "v2.5 preflight protocol")
        manifest_path = resolve_within_root(args.manifest, "v2.5 preflight manifest")
        freeze_path = resolve_within_root(args.freeze_receipt, "v2.5 preflight freeze receipt")
        calibration_path = resolve_within_root(args.calibration_binding, "v2.5 calibration binding")
        output = resolve_within_root(args.output, "v2.5 preflight output", must_exist=False)
        if output.exists():
            raise PreflightError(f"refusing to overwrite v2.5 preflight receipt: {output}")
        protocol = verify_v25_freeze(protocol_path, manifest_path, freeze_path)
        source = {dataset: _source_receipt(resolve_within_root(path, f"v2.5 {dataset} source receipt"), dataset, protocol_path, manifest_path, freeze_path) for dataset, path in SOURCE_RECEIPTS.items()}
        calibration = _source_receipt(calibration_path, "ogw_cfrp_temperature_udam", protocol_path, manifest_path, freeze_path)
        schema = {dataset: _schema_receipt(resolve_within_root(path, f"v2.5 {dataset} schema receipt"), dataset, protocol_path, manifest_path, freeze_path) for dataset, path in SCHEMA_RECEIPTS.items()}
        outputs = {
            "D12": ROOT / "results" / "mechanism_v2_5_ogw_d12_confirmation.json",
            "D16": ROOT / "results" / "mechanism_v2_5_ogw_d16_confirmation.json",
            "MORPHO": ROOT / "results" / "mechanism_v2_5_morpho_confirmation.json",
        }
        caches = {
            "D12": ROOT / "data" / "interim" / "mechanism_v2_5_ogw_d12",
            "D16": ROOT / "data" / "interim" / "mechanism_v2_5_ogw_d16",
            "MORPHO": ROOT / "data" / "interim" / "mechanism_v2_5_morpho",
        }
        available = available_memory_bytes()
        result = {
            "audit_id": "mechanism-v2.5-preexperiment-readiness-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"], "protocol_sha256": sha256_file(protocol_path), "data_manifest_sha256": sha256_file(manifest_path), "freeze_receipt_sha256": sha256_file(freeze_path),
            "outcome_type": "preexperiment_readiness_only", "source_receipts": {key: str(SOURCE_RECEIPTS[key].relative_to(ROOT)) for key in source},
            "schema_gate_status": {key: value["schema_gate"]["status"] for key, value in schema.items()},
            "coqtel_binary_scoring_eligibility": schema["coqtel_corrosion"]["schema_gate"].get("binary_scoring_eligibility"),
            "memory_gate": {"available_physical_memory_bytes": available, "minimum_required_bytes": MIN_AVAILABLE_MEMORY_BYTES, "passed": available >= MIN_AVAILABLE_MEMORY_BYTES},
            "one_shot_absence_check": {"confirmation_outputs": {key: _absence(value) for key, value in outputs.items()}, "v2_5_cache_directories": {key: _absence(value) for key, value in caches.items()}},
            "authorization_boundary": {"e7_e8_immutable_historical_evidence": True, "d04_d24_discovery_only": True, "all_v2_1_to_v2_4_receipts_history_only": True, "waveform_scoring_started": False, "e9_started": False, "external_waveform_values_read": False, "pod_or_field_far_reporting_authorized": False, "hardware_or_power_reporting_authorized": False},
            "next_authorized_action_if_user_requests_execution": {"D12": "Run the frozen v2.5 D12 wrapper once, then its v2.5 OGW audit.", "D16": "Run the frozen v2.5 D16 wrapper once, then its v2.5 OGW audit.", "MORPHO": "Run the frozen v2.5 MORPHO runner once, then its v2.5 external audit. COQTEL remains metadata-eligible only because no binary cutpoint is frozen; do not activate COPV."},
            "data_hashes_recorded": {key: [item.get("sha256") for item in receipt.get("archive_and_content_hashes", [])] for key, receipt in {**source, "ogw_cfrp_temperature_udam": calibration}.items()},
        }
        if not result["memory_gate"]["passed"]:
            raise PreflightError("available physical memory is below the frozen 8 GiB threshold")
        if any(item["exists"] for item in result["one_shot_absence_check"]["confirmation_outputs"].values()) or any(item["exists"] for item in result["one_shot_absence_check"]["v2_5_cache_directories"].values()):
            raise PreflightError("a v2.5 one-shot output/cache namespace is already occupied")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (PreflightError, V25Error, OSError) as error:
        print(f"MECHANISM-V2.5 PRE-EXPERIMENT AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
