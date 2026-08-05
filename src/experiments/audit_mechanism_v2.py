"""Read-only contract audit for mechanism-v2 result artifacts.

The audit checks frozen configuration, source identities, group boundaries,
complete grids, cap evidence, and explicit label/selection receipts.  It does
not prove hidden chronology by itself; source code review and download
receipts remain part of the evidence chain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.methods.mechanism_v2 import EVENT_FEATURE_NAMES, control_injection_grid


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_data_manifest.json"
SUPPORTED_PROTOCOL_IDS = {"mechanism-v2", "mechanism-v2.1"}


class AuditError(ValueError):
    """Raised when an artifact violates a mechanism-v2 invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read {path}: {error}") from error
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _finite_number(value: Any, context: str, minimum: float = -math.inf, maximum: float = math.inf) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise AuditError(f"{context} is not numeric") from error
    _require(math.isfinite(number) and minimum <= number <= maximum, f"{context} must lie in [{minimum}, {maximum}]")
    return number


def _manifest_entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    _require(isinstance(entries, list), "data manifest lacks data_sets")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("dataset_id") == dataset_id]
    _require(len(matches) == 1, f"dataset {dataset_id} is absent or duplicated in the frozen manifest")
    return matches[0]


def _expected_md5(entry: dict[str, Any]) -> dict[str, str]:
    official = entry.get("official")
    if not isinstance(official, dict):
        return {}
    files = official.get("files")
    if isinstance(files, list):
        expected = {}
        for item in files:
            if not isinstance(item, dict):
                continue
            checksum = item.get("official_checksum")
            if isinstance(checksum, dict) and checksum.get("algorithm") == "md5":
                expected[str(item.get("filename"))] = str(checksum.get("value"))
        return expected
    checksum = official.get("official_checksum")
    if isinstance(checksum, dict) and checksum.get("algorithm") == "md5":
        return {str(official.get("archive_filename")): str(checksum.get("value"))}
    return {}


def _audit_hashes(data: dict[str, Any], entry: dict[str, Any]) -> None:
    receipt = data.get("archive_and_content_hashes")
    _require(isinstance(receipt, list) and receipt, "data archive_and_content_hashes is missing")
    expected = _expected_md5(entry)
    actual: dict[str, dict[str, Any]] = {}
    for item in receipt:
        _require(isinstance(item, dict), "archive hash receipt contains a non-object")
        filename = item.get("filename")
        _require(isinstance(filename, str) and filename, "archive hash receipt has no filename")
        _require(_is_sha256(item.get("sha256")), f"{filename} lacks a SHA-256 receipt")
        _require(item.get("md5_verified_before_waveform_access") is True, f"{filename} lacks a pre-access MD5 verification receipt")
        actual[filename] = item
    for filename, expected_md5 in expected.items():
        _require(filename in actual, f"frozen source {filename} has no hash receipt")
        _require(actual[filename].get("md5") == expected_md5, f"{filename} MD5 differs from frozen manifest")


def _audit_group_split(group_split: Any) -> None:
    _require(isinstance(group_split, dict), "group_split is missing")
    _require(group_split.get("unit_of_analysis") == "monitoring_record", "group split unit is not monitoring record")
    _require(_is_sha256(group_split.get("split_manifest_sha256")), "group split lacks a manifest SHA-256")
    splits = group_split.get("splits")
    _require(isinstance(splits, dict) and set(splits) == {"train", "validation", "test"}, "group split must contain train/validation/test")
    members: dict[str, str] = {}
    for name, groups in splits.items():
        _require(isinstance(groups, list) and groups, f"{name} group set is empty")
        for group in groups:
            key = str(group)
            _require(key not in members, f"group {key} leaks from {members.get(key)} into {name}")
            members[key] = name
    _require(group_split.get("paths_or_repeats_are_independent_samples") is False, "group split permits path/repeat pseudoreplication")


def _audit_configuration(protocol: dict[str, Any], configuration: Any) -> tuple[set[int], set[int]]:
    _require(isinstance(configuration, dict), "configuration is missing")
    expected_capacities = {int(value) for value in protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]}
    expected_deltas = {int(value) for value in protocol["eventization_grid"]["delta_codes"]}
    _require(set(configuration.get("capacity_bytes_per_record", [])) == expected_capacities, "capacity grid differs from frozen protocol")
    _require(set(configuration.get("delta_codes", [])) == expected_deltas, "delta grid differs from frozen protocol")
    _require(tuple(configuration.get("event_features", [])) == EVENT_FEATURE_NAMES, "event feature list differs from frozen protocol")
    _require(
        tuple(configuration.get("aggregation_heads", [])) == tuple(protocol["eventization_grid"]["diagnostic"]["heads"]),
        "aggregation head list differs from frozen protocol",
    )
    return expected_capacities, expected_deltas


def _audit_grid_results(protocol: dict[str, Any], results: Any, capacities: set[int], deltas: set[int]) -> None:
    _require(isinstance(results, list), "grid_results is missing")
    expected_pairs = {(capacity, delta) for capacity in capacities for delta in deltas}
    by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for entry in results:
        _require(isinstance(entry, dict), "grid result contains a non-object")
        pair = (int(entry.get("capacity_bytes", -1)), int(entry.get("delta_codes", -1)))
        _require(pair in expected_pairs, f"undeclared grid cell {pair}")
        _require(pair not in by_pair, f"duplicate grid cell {pair}")
        by_pair[pair] = entry
    _require(set(by_pair) == expected_pairs, "capacity x delta grid is incomplete")
    waveform_required = set(protocol["eventization_grid"]["waveform_metrics"]["all_required"])
    for pair, entry in by_pair.items():
        metrics = entry.get("waveform_metrics")
        _require(isinstance(metrics, dict) and waveform_required <= set(metrics), f"{pair} omits a required waveform metric")
        _finite_number(metrics.get("waveform_correlation_mean"), f"{pair} waveform correlation", -1.0, 1.0)
        _finite_number(metrics.get("relative_error_mean"), f"{pair} relative error", 0.0)
        _finite_number(metrics.get("peak_cross_correlation_delay_samples_median"), f"{pair} peak delay")
        _finite_number(metrics.get("peak_cross_correlation_delay_samples_mean_absolute"), f"{pair} absolute peak delay", 0.0)
        retention = metrics.get("frequency_band_retention")
        _require(isinstance(retention, dict) and retention, f"{pair} lacks frequency-band retention")
        for band, value in retention.items():
            _finite_number(value, f"{pair} band retention {band}", 0.0)
        event_statistics = entry.get("event_statistics")
        _require(isinstance(event_statistics, dict), f"{pair} auditable event statistics are missing")
        means = event_statistics.get("mean_event_features")
        _require(isinstance(means, dict) and set(means) == set(EVENT_FEATURE_NAMES), f"{pair} event feature means are incomplete")
        for feature, value in means.items():
            _finite_number(value, f"{pair} event feature {feature}")
        trace_receipt = event_statistics.get("fixed_trace_receipt")
        _require(isinstance(trace_receipt, dict), f"{pair} fixed event trace receipt is missing")
        _require(_is_sha256(trace_receipt.get("event_times_sha256")), f"{pair} event-time receipt lacks SHA-256")
        _require(_is_sha256(trace_receipt.get("event_level_deltas_sha256")), f"{pair} event-amplitude receipt lacks SHA-256")
        event_scores = entry.get("event_diagnostic")
        expected_heads = set(protocol["eventization_grid"]["diagnostic"]["heads"])
        _require(isinstance(event_scores, dict) and set(event_scores) == expected_heads, f"{pair} event heads are incomplete")
        for head, summary in event_scores.items():
            _require(isinstance(summary, dict), f"{pair} {head} event summary is missing")
            _finite_number(summary.get("roc_auc"), f"{pair} {head} AUC", 0.0, 1.0)
            interval = summary.get("roc_auc_ci95")
            _require(isinstance(interval, list) and len(interval) == 2, f"{pair} {head} AUC interval is invalid")
            lower = _finite_number(interval[0], f"{pair} {head} AUC interval lower", 0.0, 1.0)
            upper = _finite_number(interval[1], f"{pair} {head} AUC interval upper", 0.0, 1.0)
            _require(lower <= upper, f"{pair} {head} AUC interval is reversed")
            _require(summary.get("bootstrap_unit") == "predeclared_group", f"{pair} {head} uses the wrong bootstrap unit")
        decomposition = entry.get("loss_decomposition")
        _require(isinstance(decomposition, dict), f"{pair} loss decomposition is missing")
        _require(set(protocol["eventization_grid"]["loss_decomposition"]) <= set(decomposition), f"{pair} loss decomposition is incomplete")
        cap = entry.get("cap_evidence")
        _require(isinstance(cap, dict), f"{pair} cap evidence is missing")
        _require(cap.get("all_packets_within_declared_capacity") is True, f"{pair} lacks a hard-cap receipt")
        _finite_number(cap.get("mean_cap_hold_fraction"), f"{pair} cap hold fraction", 0.0, 1.0)
        _finite_number(cap.get("cap_saturated_path_fraction"), f"{pair} cap saturation fraction", 0.0, 1.0)
        _finite_number(cap.get("mean_bytes_per_record"), f"{pair} bytes per record", 0.0, float(pair[0]))
        _finite_number(cap.get("bits_per_original_sample"), f"{pair} bits per original sample", 0.0)


def _audit_probes(probes: Any, capacities: set[int], deltas: set[int]) -> None:
    _require(isinstance(probes, list), "mechanism_probes is missing")
    expected = {(capacity, delta, proposition) for capacity in capacities for delta in deltas for proposition in ("quantization_collision", "terminal_hold")}
    by_key: dict[tuple[int, int, str], dict[str, Any]] = {}
    for probe in probes:
        _require(isinstance(probe, dict), "mechanism probe contains a non-object")
        key = (int(probe.get("capacity_bytes", -1)), int(probe.get("delta_codes", -1)), str(probe.get("proposition")))
        _require(key in expected and key not in by_key, f"invalid or duplicate mechanism probe {key}")
        by_key[key] = probe
    _require(set(by_key) == expected, "mechanism proposition grid is incomplete")
    for (capacity, delta, proposition), probe in by_key.items():
        status = probe.get("status")
        if proposition == "quantization_collision" and delta <= 2:
            _require(status == "not_applicable", f"{capacity}/{delta} collision must be marked not_applicable")
            continue
        _require(status == "passed", f"{capacity}/{delta} {proposition} did not pass")
        if proposition == "quantization_collision":
            _require(probe.get("same_quantized_levels") is True, f"{capacity}/{delta} collision lacks equal levels")
            _require(probe.get("same_serialized_payload") is True, f"{capacity}/{delta} collision lacks equal payload")
        else:
            _require(probe.get("first_cap_saturated") is True and probe.get("second_cap_saturated") is True, f"{capacity}/{delta} terminal hold lacks cap saturation")
            _require(probe.get("same_serialized_payload") is True and probe.get("same_decoded_output") is True, f"{capacity}/{delta} terminal hold lacks suffix equivalence")


def _audit_control_grid(protocol: dict[str, Any], controls: Any, capacities: set[int], deltas: set[int]) -> None:
    _require(isinstance(controls, list), "control_injections is missing")
    expected = {condition["control_id"] for condition in control_injection_grid(sorted(capacities), sorted(deltas), protocol["healthy_control_injections"])}
    actual: dict[str, dict[str, Any]] = {}
    for entry in controls:
        _require(isinstance(entry, dict) and isinstance(entry.get("control_id"), str), "control injection is missing control_id")
        control_id = entry["control_id"]
        _require(control_id in expected and control_id not in actual, "control injection grid contains an unknown or duplicate cell")
        _require(entry.get("status") in {"evaluated", "not_applicable"}, "control injection has an invalid status")
        actual[control_id] = entry
    _require(set(actual) == expected, "control injection grid is incomplete")


def audit_result(protocol_path: Path, manifest_path: Path, result_path: Path) -> None:
    protocol = _load_json(protocol_path)
    manifest = _load_json(manifest_path)
    result = _load_json(result_path)
    _require(protocol.get("protocol_id") in SUPPORTED_PROTOCOL_IDS, "audit requires a supported mechanism-v2 protocol")
    _require(result.get("protocol_id") == protocol["protocol_id"], "result protocol identifier differs from frozen protocol")
    _require(result.get("protocol_sha256") == _sha256_file(protocol_path), "result protocol SHA-256 differs from frozen protocol")
    _require(result.get("data_manifest_sha256") == _sha256_file(manifest_path), "result data manifest SHA-256 differs from frozen manifest")
    _require(isinstance(result.get("code_revision"), str) and result["code_revision"], "result lacks code revision")
    outcome = result.get("outcome_type")
    _require(outcome in {"confirmation", "schema_ineligible"}, "result outcome_type is invalid")
    data = result.get("data")
    _require(isinstance(data, dict) and isinstance(data.get("dataset_id"), str), "result data identity is missing")
    entry = _manifest_entry(manifest, data["dataset_id"])
    _require(data.get("data_role") == entry.get("role"), "result data role differs from frozen manifest")
    selection = result.get("selection_receipt")
    _require(isinstance(selection, dict), "result selection receipt is missing")
    _require(selection.get("discovery_data_used_for_selection") is False, "discovery data entered selection")
    _require(selection.get("posthoc_configuration_selection") is False, "result admits post-hoc configuration selection")
    if outcome == "schema_ineligible":
        _require(isinstance(result.get("exclusion_reason"), str) and result["exclusion_reason"], "schema exclusion reason is missing")
        schema = data.get("schema_gate")
        _require(isinstance(schema, dict) and schema.get("status") == "failed", "schema-ineligible output lacks a failed schema gate")
        _require(selection.get("waveform_scoring_started") is False, "schema-ineligible output started waveform scoring")
        _require(not result.get("grid_results"), "schema-ineligible output must not contain signal grid results")
        return
    _require(selection.get("test_labels_read_after_scoring") is True, "confirmation lacks post-scoring label receipt")
    _require(selection.get("all_configurations_fixed_before_confirmation") is True, "confirmation lacks frozen configuration receipt")
    schema = data.get("schema_gate")
    _require(isinstance(schema, dict) and schema.get("status") == "passed", "confirmation lacks a passed schema gate")
    _require(_is_sha256(schema.get("schema_fingerprint_sha256")), "confirmation lacks a schema fingerprint SHA-256")
    _audit_hashes(data, entry)
    _audit_group_split(result.get("group_split"))
    capacities, deltas = _audit_configuration(protocol, result.get("configuration"))
    _audit_grid_results(protocol, result.get("grid_results"), capacities, deltas)
    _audit_probes(result.get("mechanism_probes"), capacities, deltas)
    _audit_control_grid(protocol, result.get("control_injections"), capacities, deltas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        audit_result(args.protocol, args.manifest, args.result)
    except AuditError as error:
        print(f"MECHANISM-V2 AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print("MECHANISM-V2 AUDIT PASSED: frozen grid, data role, hashes, groups, cap evidence, and no-selection receipts verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
