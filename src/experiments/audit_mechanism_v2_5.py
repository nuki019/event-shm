"""Read-only result auditor for the frozen mechanism-v2.5 MORPHO runner."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_5_successor import (
    ROOT, V25Error, external_execution_contract, external_mapping, json_hash, load_json, load_v25_manifest,
    manifest_entry, resolve_within_root, sha256_file, verify_v25_freeze,
)
from src.methods.mechanism_v2 import EVENT_FEATURE_NAMES, control_injection_grid


class AuditError(ValueError):
    """Raised when an external v2.5 result violates a frozen invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _finite(value: Any, label: str, minimum: float = -math.inf, maximum: float = math.inf) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise AuditError(f"{label} is not numeric") from error
    _require(math.isfinite(number) and minimum <= number <= maximum, f"{label} must lie in [{minimum}, {maximum}]")
    return number


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _expected_md5(entry: dict[str, Any]) -> dict[str, str]:
    official = entry.get("official")
    files = official.get("files") if isinstance(official, dict) else None
    if not isinstance(files, list):
        return {}
    output: dict[str, str] = {}
    for item in files:
        checksum = item.get("official_checksum") if isinstance(item, dict) else None
        if isinstance(item, dict) and isinstance(checksum, dict) and checksum.get("algorithm") == "md5":
            output[str(item.get("filename"))] = str(checksum.get("value"))
    return output


def _audit_hashes(data: dict[str, Any], entry: dict[str, Any]) -> None:
    receipt = data.get("archive_and_content_hashes")
    expected = _expected_md5(entry)
    _require(isinstance(receipt, list) and receipt and expected, "external data hash receipt is missing")
    actual: dict[str, dict[str, Any]] = {}
    for item in receipt:
        _require(isinstance(item, dict), "external data hash receipt contains a non-object")
        filename = item.get("filename")
        _require(isinstance(filename, str) and filename, "external data hash receipt lacks a filename")
        _require(_sha(item.get("sha256")), f"external source {filename} lacks SHA-256")
        _require(item.get("md5_verified_before_waveform_access") is True, f"external source {filename} lacks MD5-before-access evidence")
        actual[filename] = item
    _require(set(actual) == set(expected), "external source receipt file set differs from frozen manifest")
    for filename, md5 in expected.items():
        _require(actual[filename].get("md5") == md5, f"external source {filename} MD5 differs from frozen manifest")


def _audit_group_split(result: dict[str, Any], mapping: dict[str, Any], contract: dict[str, Any]) -> None:
    split = result.get("group_split")
    _require(isinstance(split, dict), "external group split is missing")
    expected = {
        "fit": ["Healthy_Clamped"],
        "held_out_normal": ["Healthy_Unclamped"],
        "degradation": [str(value) for value in mapping["fatigue_blocks_order"]],
    }
    _require(split.get("unit_of_analysis") == "fatigue_baseline_block", "external group split has wrong unit")
    _require(split.get("splits") == expected, "external group split differs from frozen block assignments")
    _require(split.get("split_manifest_sha256") == json_hash(expected), "external group split SHA-256 differs from frozen assignments")
    _require(split.get("component_cross_split_forbidden") is True and split.get("paths_or_repeats_are_independent_samples") is False, "external group split permits component pseudoreplication")
    expected_packets = len(mapping["frequency_values"]) * len(mapping["actuator_ids"]) * len(mapping["repeat_ids"])
    _require(split.get("component_packets_per_block") == expected_packets, "external group split has wrong packet count")
    _require(contract["group_split"]["component_cross_split_forbidden"] is True, "frozen contract does not forbid split leakage")


def _audit_score_summary(summary: Any, label: str) -> None:
    _require(isinstance(summary, dict), f"{label} score summary is missing")
    _finite(summary.get("roc_auc"), f"{label} AUC", 0.0, 1.0)
    interval = summary.get("roc_auc_ci95")
    _require(isinstance(interval, list) and len(interval) == 2, f"{label} AUC interval is invalid")
    lower, upper = _finite(interval[0], f"{label} AUC lower", 0.0, 1.0), _finite(interval[1], f"{label} AUC upper", 0.0, 1.0)
    _require(lower <= upper, f"{label} AUC interval is reversed")
    _require(summary.get("bootstrap_unit") == "predeclared_group", f"{label} bootstrap unit is not a predeclared group")
    _require(summary.get("healthy_group_count") == 1, f"{label} must disclose exactly one held-out healthy block")


def _audit_waveform(metrics: Any, label: str, required: set[str]) -> None:
    _require(isinstance(metrics, dict) and required <= set(metrics), f"{label} omits a required waveform metric")
    _finite(metrics.get("waveform_correlation_mean"), f"{label} waveform correlation", -1.0, 1.0)
    _finite(metrics.get("relative_error_mean"), f"{label} relative error", 0.0)
    _finite(metrics.get("peak_cross_correlation_delay_samples_median"), f"{label} delay")
    _finite(metrics.get("peak_cross_correlation_delay_samples_mean_absolute"), f"{label} absolute delay", 0.0)
    retention = metrics.get("frequency_band_retention")
    _require(isinstance(retention, dict) and retention, f"{label} lacks frequency-band retention")
    for band, value in retention.items():
        _finite(value, f"{label} band {band}", 0.0)
    if "event_density" in required:
        _finite(metrics.get("event_density"), f"{label} event density", 0.0)
    if "cap_hold_fraction" in required:
        _finite(metrics.get("cap_hold_fraction"), f"{label} cap hold", 0.0, 1.0)


def _audit_block_records(records: Any, mapping: dict[str, Any], expected_packets: int, capacity: int, label: str) -> None:
    expected_blocks = ["Healthy_Unclamped", *[str(value) for value in mapping["fatigue_blocks_order"]]]
    expected_labels = [0] + [1] * len(mapping["fatigue_blocks_order"])
    _require(isinstance(records, list) and len(records) == len(expected_blocks), f"{label} does not report every held-out block")
    for record, block, binary_label in zip(records, expected_blocks, expected_labels):
        _require(isinstance(record, dict) and record.get("block_id") == block, f"{label} block order differs from frozen mapping")
        _require(record.get("binary_label_constructed_after_scoring") == binary_label, f"{label} block label differs from frozen path-token rule")
        _require(record.get("component_packet_count") == expected_packets, f"{label} block component packet count differs from frozen topology")
        features = record.get("mean_event_features")
        _require(isinstance(features, dict) and set(features) == set(EVENT_FEATURE_NAMES), f"{label} block event features are incomplete")
        for name, value in features.items():
            _finite(value, f"{label} block {block} {name}")
        scores = record.get("event_scores")
        _require(isinstance(scores, dict) and set(scores) == {"global", "max_path"}, f"{label} block event scores are incomplete")
        for head, value in scores.items():
            _finite(value, f"{label} block {block} {head}", 0.0)
        _finite(record.get("dense_energy_score"), f"{label} block dense score", 0.0)
        _finite(record.get("reconstruction_energy_score"), f"{label} block reconstruction score", 0.0)
        _finite(record.get("mean_bytes_per_component_packet"), f"{label} block packet bytes", 0.0, capacity)
        _require(isinstance(record.get("bytes_per_monitoring_block"), int) and record["bytes_per_monitoring_block"] > 0, f"{label} block total bytes are invalid")
        _finite(record.get("bits_per_original_sample"), f"{label} block bits/sample", 0.0)
        _finite(record.get("cap_saturated_path_fraction"), f"{label} block cap saturation", 0.0, 1.0)
        _finite(record.get("mean_cap_hold_fraction"), f"{label} block cap hold", 0.0, 1.0)
        trace = record.get("fixed_trace_receipt")
        _require(isinstance(trace, dict) and _sha(trace.get("event_times_sha256")) and _sha(trace.get("event_level_deltas_sha256")), f"{label} block trace receipt is incomplete")


def _audit_grid(result: dict[str, Any], protocol: dict[str, Any], mapping: dict[str, Any]) -> None:
    configuration = result.get("configuration")
    _require(isinstance(configuration, dict), "result configuration is missing")
    capacities = {int(value) for value in protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]}
    deltas = {int(value) for value in protocol["eventization_grid"]["delta_codes"]}
    _require(set(configuration.get("capacity_bytes_per_record", [])) == capacities, "result capacity grid differs from frozen protocol")
    _require(set(configuration.get("delta_codes", [])) == deltas, "result delta grid differs from frozen protocol")
    _require(tuple(configuration.get("event_features", [])) == EVENT_FEATURE_NAMES, "result event feature list differs from frozen protocol")
    _require(tuple(configuration.get("aggregation_heads", [])) == tuple(protocol["eventization_grid"]["diagnostic"]["heads"]), "result aggregation head list differs from frozen protocol")
    _require(configuration.get("control_injection_grid_sha256") == json_hash(control_injection_grid(sorted(capacities), sorted(deltas), protocol["healthy_control_injections"])), "result control grid hash differs from frozen protocol")
    rows = result.get("grid_results")
    _require(isinstance(rows, list), "result grid_results is missing")
    expected_pairs = {(capacity, delta) for capacity in capacities for delta in deltas}
    by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        _require(isinstance(row, dict), "result grid row is not an object")
        pair = (int(row.get("capacity_bytes", -1)), int(row.get("delta_codes", -1)))
        _require(pair in expected_pairs and pair not in by_pair, f"invalid or duplicate grid cell {pair}")
        by_pair[pair] = row
    _require(set(by_pair) == expected_pairs, "result capacity x delta grid is incomplete")
    required_metrics = set(protocol["eventization_grid"]["waveform_metrics"]["all_required"])
    expected_packets = len(mapping["frequency_values"]) * len(mapping["actuator_ids"]) * len(mapping["repeat_ids"])
    for pair, row in by_pair.items():
        capacity, _ = pair
        _audit_waveform(row.get("waveform_metrics"), f"{pair}", required_metrics)
        event = row.get("event_statistics")
        _require(isinstance(event, dict), f"{pair} lacks event statistics")
        means = event.get("mean_event_features")
        _require(isinstance(means, dict) and set(means) == set(EVENT_FEATURE_NAMES), f"{pair} event features are incomplete")
        for name, value in means.items():
            _finite(value, f"{pair} event feature {name}")
        trace = event.get("fixed_trace_receipt")
        _require(isinstance(trace, dict) and _sha(trace.get("event_times_sha256")) and _sha(trace.get("event_level_deltas_sha256")), f"{pair} trace receipt is incomplete")
        diagnostic = row.get("event_diagnostic")
        _require(isinstance(diagnostic, dict) and set(diagnostic) == {"global", "max_path"}, f"{pair} event heads are incomplete")
        for head, summary in diagnostic.items():
            _audit_score_summary(summary, f"{pair} {head}")
        paired = row.get("paired_group_auc_difference_vs_dense_energy")
        _require(isinstance(paired, dict) and set(paired) == {"global", "max_path"}, f"{pair} paired AUC heads are incomplete")
        for head, summary in paired.items():
            _require(isinstance(summary, dict), f"{pair} {head} paired AUC is missing")
            _finite(summary.get("auc_difference"), f"{pair} {head} paired AUC difference", -1.0, 1.0)
            interval = summary.get("auc_difference_ci95")
            _require(isinstance(interval, list) and len(interval) == 2, f"{pair} {head} paired AUC interval is invalid")
            lower, upper = _finite(interval[0], f"{pair} {head} paired AUC lower", -1.0, 1.0), _finite(interval[1], f"{pair} {head} paired AUC upper", -1.0, 1.0)
            _require(lower <= upper, f"{pair} {head} paired AUC interval is reversed")
        decomposition = row.get("loss_decomposition")
        _require(isinstance(decomposition, dict) and set(protocol["eventization_grid"]["loss_decomposition"]) <= set(decomposition), f"{pair} loss decomposition is incomplete")
        _audit_waveform(decomposition.get("quantization_only"), f"{pair} quantization loss", required_metrics - {"event_density", "cap_hold_fraction"})
        _audit_waveform(decomposition.get("hard_cap_truncation"), f"{pair} truncation loss", required_metrics - {"event_density", "cap_hold_fraction"})
        mismatch = decomposition.get("score_head_mismatch")
        _require(isinstance(mismatch, dict) and set(mismatch) == {"global", "max_path"}, f"{pair} score-head mismatch is incomplete")
        for head, values in mismatch.items():
            _require(isinstance(values, dict), f"{pair} {head} mismatch is invalid")
            _finite(values.get("dense_vs_reconstruction_mean_absolute_score_difference"), f"{pair} {head} dense/reconstruction mismatch", 0.0)
            _finite(values.get("reconstruction_vs_event_mean_absolute_score_difference"), f"{pair} {head} reconstruction/event mismatch", 0.0)
        cap = row.get("cap_evidence")
        _require(isinstance(cap, dict), f"{pair} cap evidence is missing")
        _require(cap.get("component_packet_capacity_bytes") == capacity and cap.get("all_component_packets_within_declared_capacity") is True, f"{pair} lacks component-packet hard-cap evidence")
        _finite(cap.get("hard_capacity_guaranteed_bytes_per_component_packet"), f"{pair} hard packet bound", 0.0, capacity)
        _finite(cap.get("mean_bytes_per_component_packet"), f"{pair} mean packet bytes", 0.0, capacity)
        _finite(cap.get("maximum_bytes_per_component_packet"), f"{pair} max packet bytes", 0.0, capacity)
        block_bytes = cap.get("bytes_per_monitoring_block")
        _require(isinstance(block_bytes, dict) and len(block_bytes) == 1 + len(mapping["fatigue_blocks_order"]), f"{pair} block-byte evidence is incomplete")
        _finite(cap.get("mean_bytes_per_monitoring_block"), f"{pair} mean block bytes", 0.0)
        _finite(cap.get("bits_per_original_sample"), f"{pair} bits/sample", 0.0)
        _finite(cap.get("cap_saturated_path_fraction"), f"{pair} cap saturation", 0.0, 1.0)
        _finite(cap.get("mean_cap_hold_fraction"), f"{pair} cap hold", 0.0, 1.0)
        _audit_waveform(row.get("condition_metrics", {}).get("held_out_normal"), f"{pair} held-out normal", required_metrics - {"event_density", "cap_hold_fraction"})
        _audit_waveform(row.get("condition_metrics", {}).get("fatigue_degradation"), f"{pair} fatigue", required_metrics - {"event_density", "cap_hold_fraction"})
        _audit_block_records(row.get("block_score_records"), mapping, expected_packets, capacity, str(pair))


def _audit_probes(result: dict[str, Any], protocol: dict[str, Any], mapping: dict[str, Any]) -> None:
    capacities = [int(value) for value in protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]]
    deltas = [int(value) for value in protocol["eventization_grid"]["delta_codes"]]
    expected = {(capacity, delta, proposition) for capacity in capacities for delta in deltas for proposition in ("quantization_collision", "terminal_hold")}
    probes = result.get("mechanism_probes")
    _require(isinstance(probes, list), "mechanism proposition grid is missing")
    actual: dict[tuple[int, int, str], dict[str, Any]] = {}
    for item in probes:
        _require(isinstance(item, dict), "mechanism proposition is not an object")
        key = (int(item.get("capacity_bytes", -1)), int(item.get("delta_codes", -1)), str(item.get("proposition")))
        _require(key in expected and key not in actual, f"invalid or duplicate mechanism proposition {key}")
        actual[key] = item
    _require(set(actual) == expected, "mechanism proposition grid is incomplete")
    for (capacity, delta, proposition), item in actual.items():
        if proposition == "quantization_collision" and delta <= 2:
            _require(item.get("status") == "not_applicable", f"{capacity}/{delta} collision must be not_applicable")
        else:
            _require(item.get("status") == "passed", f"{capacity}/{delta} {proposition} did not pass")
            if proposition == "quantization_collision":
                _require(item.get("same_quantized_levels") is True and item.get("same_serialized_payload") is True, f"{capacity}/{delta} collision evidence is incomplete")
            else:
                _require(all(item.get(key) is True for key in ("first_cap_saturated", "second_cap_saturated", "same_serialized_payload", "same_decoded_output")), f"{capacity}/{delta} terminal-hold evidence is incomplete")


def _audit_controls(result: dict[str, Any], protocol: dict[str, Any], contract: dict[str, Any]) -> None:
    capacities = sorted(int(value) for value in protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"])
    deltas = sorted(int(value) for value in protocol["eventization_grid"]["delta_codes"])
    expected = {item["control_id"] for item in control_injection_grid(capacities, deltas, protocol["healthy_control_injections"])}
    controls = result.get("control_injections")
    _require(isinstance(controls, list), "healthy control grid is missing")
    actual: dict[str, dict[str, Any]] = {}
    fit = contract["healthy_only_fit"]
    for item in controls:
        _require(isinstance(item, dict) and isinstance(item.get("control_id"), str), "healthy control cell is malformed")
        key = item["control_id"]
        _require(key in expected and key not in actual, "healthy control grid has an unknown or duplicate cell")
        _require(item.get("status") in {"evaluated", "not_applicable"}, "healthy control has an invalid status")
        _require(item.get("healthy_component_packet_ordinals") == fit["control_component_ordinals"], "healthy control packet selection differs from frozen protocol")
        _require(item.get("receiver_indices_zero_based") == fit["control_receiver_indices_zero_based"], "healthy control receiver selection differs from frozen protocol")
        actual[key] = item
    _require(set(actual) == expected, "healthy control grid is incomplete")


def audit_external_result(protocol_path: Path, manifest_path: Path, freeze_path: Path, result_path: Path) -> None:
    protocol_file = resolve_within_root(protocol_path, "v2.5 external audit protocol")
    manifest_file = resolve_within_root(manifest_path, "v2.5 external audit manifest")
    freeze_file = resolve_within_root(freeze_path, "v2.5 external audit freeze receipt")
    result_file = resolve_within_root(result_path, "v2.5 external audit result")
    protocol = verify_v25_freeze(protocol_file, manifest_file, freeze_file)
    manifest, _ = load_v25_manifest(manifest_file)
    result = load_json(result_file)
    _require(result.get("protocol_id") == protocol["protocol_id"], "result protocol id differs from frozen protocol")
    _require(result.get("protocol_sha256") == sha256_file(protocol_file), "result protocol SHA-256 differs from frozen protocol")
    _require(result.get("data_manifest_sha256") == sha256_file(manifest_file), "result manifest SHA-256 differs from frozen manifest")
    _require(result.get("freeze_receipt_sha256") == sha256_file(freeze_file), "result freeze SHA-256 differs from frozen receipt")
    _require(result.get("result_schema_sha256") == protocol["result_schema"]["sha256"], "result schema SHA-256 differs from frozen schema")
    _require(isinstance(result.get("code_revision"), str) and result["code_revision"], "result lacks code revision")
    _require(result.get("outcome_type") == "external_confirmation", "result has an invalid external outcome type")
    data = result.get("data")
    _require(isinstance(data, dict) and data.get("dataset_id") == "morpho_fod7", "result does not identify MORPHO")
    entry = manifest_entry(manifest, "morpho_fod7")
    _require(data.get("data_role") == entry.get("role"), "result data role differs from frozen manifest")
    _audit_hashes(data, entry)
    source_receipt_value, source_receipt_hash = data.get("source_receipt_path"), data.get("source_receipt_sha256")
    schema_receipt_value, schema_receipt_hash = data.get("schema_gate_receipt_path"), data.get("schema_gate_receipt_sha256")
    _require(isinstance(source_receipt_value, str) and _sha(source_receipt_hash), "result lacks a source-receipt binding")
    _require(isinstance(schema_receipt_value, str) and _sha(schema_receipt_hash), "result lacks a schema-gate receipt binding")
    source_receipt_path = resolve_within_root(source_receipt_value, "result MORPHO source receipt")
    schema_receipt_path = resolve_within_root(schema_receipt_value, "result MORPHO schema gate receipt")
    _require(sha256_file(source_receipt_path) == source_receipt_hash, "result source receipt hash no longer matches")
    _require(sha256_file(schema_receipt_path) == schema_receipt_hash, "result schema gate receipt hash no longer matches")
    source_receipt = load_json(source_receipt_path)
    schema_receipt = load_json(schema_receipt_path)
    _require(data.get("archive_and_content_hashes") == source_receipt.get("archive_and_content_hashes"), "result source hashes differ from the bound source receipt")
    _require(schema_receipt.get("schema_gate") == data.get("schema_gate"), "result schema gate differs from the bound gate receipt")
    _require(isinstance(data.get("cache_namespace"), str) and data["cache_namespace"].startswith("data/interim/mechanism_v2_5_morpho"), "result cache namespace is not isolated")
    mapping = external_mapping(protocol, "morpho_fod7")
    contract = external_execution_contract(protocol)
    gate = data.get("schema_gate")
    _require(isinstance(gate, dict) and gate.get("status") == "passed" and gate.get("schema_mapping_sha256") == json_hash(mapping) and _sha(gate.get("inventory_schema_fingerprint_sha256")), "result lacks a matching passed MORPHO schema gate")
    _require(data.get("external_execution_contract_sha256") == json_hash(contract), "result external execution contract differs from frozen protocol")
    _require(data.get("component_packet_definition") == contract["component_packet_definition"], "result component packet definition differs from frozen protocol")
    selection = result.get("selection_receipt")
    _require(isinstance(selection, dict), "result selection receipt is missing")
    required_true = ("all_configurations_fixed_before_confirmation", "waveform_scoring_started", "labels_constructed_after_all_block_score_arrays", "test_labels_read_after_scoring", "healthy_only_quantizer_fit", "healthy_only_event_diagnostic_fit", "healthy_only_scalar_normalizer_fit")
    _require(all(selection.get(key) is True for key in required_true), "result selection receipt lacks a frozen execution assertion")
    _require(selection.get("discovery_data_used_for_selection") is False and selection.get("posthoc_configuration_selection") is False and selection.get("D04_D24_opened") is False, "result selection receipt crosses a discovery/post-hoc boundary")
    _audit_group_split(result, mapping, contract)
    _audit_grid(result, protocol, mapping)
    _audit_probes(result, protocol, mapping)
    _audit_controls(result, protocol, contract)
    limitations = result.get("limitations")
    _require(isinstance(limitations, dict) and limitations.get("one_held_out_healthy_block") is True and isinstance(limitations.get("statement"), str), "result omits the one-held-out-healthy-block limitation")
    rendered = str(result).lower()
    _require("probability_of_detection" not in rendered and "field far" not in rendered and "field_far" not in rendered, "result contains a prohibited operational claim")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "protocols" / "mechanism_v2_5.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "protocols" / "mechanism_v2_5_data_manifest.json")
    parser.add_argument("--freeze-receipt", type=Path, default=ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json")
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        audit_external_result(args.protocol, args.manifest, args.freeze_receipt, args.result)
    except (AuditError, V25Error) as error:
        print(f"MECHANISM-V2.5 EXTERNAL AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"mechanism-v2.5 external audit passed: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
