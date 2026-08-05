"""Read-only contract audit for strict-evaluation-v1 result artifacts.

The checker verifies that an E7/E8 output is complete and structurally
consistent with the frozen protocol: every declared capacity and threshold is
present, packet limits hold, validation-selected descriptors are traceable,
and reported metrics have valid domains.  It cannot prove run chronology or
absence of hidden data access; those remain properties of the reviewed code,
data provenance, and the frozen protocol.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "protocols" / "strict_evaluation_v1.json"
DEFAULT_E7 = ROOT / "results" / "e7_strict_codec_benchmark_v1.json"
DEFAULT_E8 = ROOT / "results" / "e8_cold_start_alarm_v1.json"
V1_THRESHOLD_COUNT = 9


class AuditError(ValueError):
    """Raised when an output violates a frozen-result contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _number_in_range(value: Any, lower: float, upper: float, context: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise AuditError(f"{context} is not numeric") from error
    _require(math.isfinite(number) and lower <= number <= upper, f"{context} must lie in [{lower}, {upper}]")
    return number


def _descriptor_is_listed(descriptor: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    return any(all(candidate.get(key) == value for key, value in descriptor.items()) for candidate in candidates)


def _payload_is_within_cap(summary: Any, capacity: int, context: str) -> None:
    _require(isinstance(summary, dict), f"{context} payload summary is missing")
    maximum = _number_in_range(summary.get("maximum_bytes_per_record"), 0.0, float(capacity), f"{context} maximum payload")
    mean = _number_in_range(summary.get("mean_bytes_per_record"), 0.0, float(capacity), f"{context} mean payload")
    _require(mean <= maximum, f"{context} mean payload exceeds its maximum")


def audit_e7(protocol: dict[str, Any], output: dict[str, Any]) -> None:
    benchmark = protocol["codec_benchmark"]
    _require(output.get("protocol_id") == protocol["protocol_id"], "E7 protocol identifier does not match")
    _require(output.get("smoke") is False, "E7 smoke output is not paper-eligible")

    capacities = [int(value) for value in benchmark["target_payload_bytes_per_record"]]
    codecs = list(benchmark["codecs"])
    conditions = list(benchmark["damage_test_sets"])
    results = output.get("test_results")
    audit = output.get("validation_payload_candidate_audit")
    _require(isinstance(results, dict) and set(results) == set(codecs), "E7 codec result set is incomplete")
    _require(isinstance(audit, dict) and set(audit) == set(codecs), "E7 validation audit set is incomplete")

    matched_limit = float(benchmark["paired_temperature_analysis"]["maximum_difference_celsius"])
    for codec_name in codecs:
        entries = results[codec_name]
        _require(isinstance(entries, list) and len(entries) == len(capacities), f"E7 {codec_name} has an incomplete capacity grid")
        entries_by_capacity = {entry.get("target_payload_bytes_per_record"): entry for entry in entries if isinstance(entry, dict)}
        _require(set(entries_by_capacity) == set(capacities), f"E7 {codec_name} capacities do not match the protocol")
        candidate_audit = audit.get(codec_name)
        _require(isinstance(candidate_audit, dict), f"E7 {codec_name} validation audit is missing")

        for capacity in capacities:
            entry = entries_by_capacity[capacity]
            _number_in_range(
                entry.get("hard_capacity_guaranteed_bytes_per_record"),
                0.0,
                float(capacity),
                f"E7 {codec_name} {capacity}B guaranteed capacity",
            )
            descriptor = entry.get("selected_from_healthy_validation_only")
            candidates = candidate_audit.get(str(capacity))
            _require(isinstance(descriptor, dict), f"E7 {codec_name} {capacity}B selected descriptor is missing")
            _require(isinstance(candidates, list) and _descriptor_is_listed(descriptor, candidates),
                     f"E7 {codec_name} {capacity}B selected descriptor is absent from its validation audit")

            entry_conditions = entry.get("conditions")
            _require(isinstance(entry_conditions, dict) and set(entry_conditions) == set(conditions),
                     f"E7 {codec_name} {capacity}B condition set is incomplete")
            for condition in conditions:
                result = entry_conditions[condition]
                _require(isinstance(result, dict), f"E7 {codec_name} {capacity}B {condition} result is missing")
                _number_in_range(result.get("roc_auc"), 0.0, 1.0, f"E7 {codec_name} {capacity}B {condition} AUC")
                ci = result.get("roc_auc_ci95")
                _require(isinstance(ci, list) and len(ci) == 2, f"E7 {codec_name} {capacity}B {condition} AUC interval is invalid")
                lower = _number_in_range(ci[0], 0.0, 1.0, f"E7 {codec_name} {capacity}B {condition} AUC lower interval")
                upper = _number_in_range(ci[1], 0.0, 1.0, f"E7 {codec_name} {capacity}B {condition} AUC upper interval")
                _require(lower <= upper, f"E7 {codec_name} {capacity}B {condition} AUC interval is reversed")
                _payload_is_within_cap(result.get("healthy_payload"), capacity, f"E7 {codec_name} {capacity}B healthy")
                _payload_is_within_cap(result.get("damage_payload"), capacity, f"E7 {codec_name} {capacity}B {condition}")
                matched = result.get("temperature_matched")
                _require(isinstance(matched, dict) and int(matched.get("n_pairs", 0)) > 0,
                         f"E7 {codec_name} {capacity}B {condition} lacks temperature-matched pairs")
                differences = matched.get("temperature_abs_difference_celsius")
                _require(isinstance(differences, dict), f"E7 {codec_name} {capacity}B {condition} matching summary is missing")
                _number_in_range(
                    differences.get("maximum"),
                    0.0,
                    matched_limit,
                    f"E7 {codec_name} {capacity}B {condition} maximum matched temperature difference",
                )


def audit_e8(protocol: dict[str, Any], output: dict[str, Any]) -> None:
    alarm = protocol["cold_start_alarm"]
    _require(output.get("protocol_id") == protocol["protocol_id"], "E8 protocol identifier does not match")
    _require(output.get("smoke") is False, "E8 smoke output is not paper-eligible")
    _require(output.get("calibration_month") == alarm["calibration_month"], "E8 calibration month does not match")
    _require(output.get("blind_test_month") == alarm["blind_test_month"], "E8 blind-test month does not match")
    _require(int(output.get("calibration_records", 0)) > 0, "E8 has no calibration records")
    _require(int(output.get("blind_test_records", 0)) > 0, "E8 has no blind-test records")

    metadata = output.get("test_label_metadata")
    _require(isinstance(metadata, dict), "E8 test-label metadata is missing")
    expected_onset_index = int(alarm["test_label_change_record"])
    _require(int(metadata.get("protocol_declared_source_index", -1)) == expected_onset_index,
             "E8 reported onset index does not match the protocol")
    _require(int(metadata.get("first_nonzero_label_local_index", -1)) == expected_onset_index,
             "E8 observed onset index does not match the protocol")
    expected_onset_time_text = str(alarm["test_label_change_time"])
    _require(metadata.get("first_nonzero_label_time") == expected_onset_time_text,
             "E8 observed onset time does not match the protocol")
    try:
        expected_onset_time = datetime.fromisoformat(expected_onset_time_text)
    except ValueError as error:
        raise AuditError("strict-evaluation-v1 has an invalid onset timestamp") from error
    _require(metadata.get("blind_replay_completed_before_label_evaluation") is True,
             "E8 output does not attest that blind replay preceded label evaluation")

    features = output.get("feature_results")
    expected_features = set(alarm["feature_comparators"])
    _require(isinstance(features, dict) and set(features) == expected_features, "E8 feature set is incomplete")
    for feature_name, feature in features.items():
        _require(isinstance(feature, dict), f"E8 {feature_name} result is missing")
        thresholds = feature.get("thresholds_from_2021_03_only")
        curve = feature.get("blind_test_curve")
        _require(isinstance(thresholds, list) and len(thresholds) == V1_THRESHOLD_COUNT,
                 f"E8 {feature_name} threshold grid is incomplete")
        _require(isinstance(curve, list) and len(curve) == len(thresholds),
                 f"E8 {feature_name} curve length does not match its threshold grid")
        previous = -math.inf
        for index, (threshold, point) in enumerate(zip(thresholds, curve)):
            threshold_value = _number_in_range(threshold, -math.inf, math.inf, f"E8 {feature_name} threshold {index}")
            _require(threshold_value >= previous, f"E8 {feature_name} threshold grid is not ordered")
            previous = threshold_value
            _require(isinstance(point, dict), f"E8 {feature_name} threshold {index} point is missing")
            reported = _number_in_range(point.get("threshold"), -math.inf, math.inf, f"E8 {feature_name} threshold {index} reported threshold")
            _require(math.isclose(threshold_value, reported, rel_tol=0.0, abs_tol=1e-12),
                     f"E8 {feature_name} threshold {index} is not replayed as declared")
            _number_in_range(point.get("false_calls_per_day"), 0.0, math.inf, f"E8 {feature_name} threshold {index} false calls/day")
            _require(int(point.get("healthy_records", 0)) > 0, f"E8 {feature_name} threshold {index} has no healthy exposure")
            for coverage_key in ("post_onset_record_exceedance_coverage", "post_onset_day_exceedance_coverage"):
                coverage = point.get(coverage_key)
                if coverage is not None:
                    _number_in_range(coverage, 0.0, 1.0, f"E8 {feature_name} threshold {index} {coverage_key}")
            pre_onset_active = point.get("pre_onset_incident_active_at_onset")
            _require(type(pre_onset_active) is bool,
                     f"E8 {feature_name} threshold {index} pre-onset activity flag must be boolean")
            first_alarm = point.get("first_post_onset_alarm")
            delay = point.get("first_post_onset_delay_minutes")
            if first_alarm is None:
                _require(delay is None,
                         f"E8 {feature_name} threshold {index} has a delay without a new post-onset alarm")
                continue
            _require(isinstance(first_alarm, str) and first_alarm,
                     f"E8 {feature_name} threshold {index} first post-onset alarm is invalid")
            try:
                alarm_time = datetime.fromisoformat(first_alarm)
            except ValueError as error:
                raise AuditError(f"E8 {feature_name} threshold {index} first post-onset alarm is not ISO-8601") from error
            _require(alarm_time >= expected_onset_time,
                     f"E8 {feature_name} threshold {index} first post-onset alarm predates the onset")
            _require(delay is not None,
                     f"E8 {feature_name} threshold {index} has a post-onset alarm without a delay")
            reported_delay = _number_in_range(delay, 0.0, math.inf,
                                              f"E8 {feature_name} threshold {index} post-onset delay")
            expected_delay = (alarm_time - expected_onset_time).total_seconds() / 60.0
            _require(math.isclose(reported_delay, expected_delay, rel_tol=0.0, abs_tol=1e-6),
                     f"E8 {feature_name} threshold {index} post-onset delay does not match its alarm time")
            _require(not pre_onset_active or expected_delay > 0.0,
                     f"E8 {feature_name} threshold {index} credits an onset-active incident as a new alarm")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read {path}: {error}") from error
    _require(isinstance(payload, dict), f"{path} must contain a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--e7", type=Path, default=DEFAULT_E7)
    parser.add_argument("--e8", type=Path, default=DEFAULT_E8)
    args = parser.parse_args()
    try:
        protocol = _load_json(args.protocol)
        _require(protocol.get("protocol_id") == "strict-evaluation-v1", "this checker supports strict-evaluation-v1 only")
        audit_e7(protocol, _load_json(args.e7))
        audit_e8(protocol, _load_json(args.e8))
    except AuditError as error:
        print(f"STRICT-OUTPUT AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print("STRICT-OUTPUT AUDIT PASSED: 4 codecs x 4 capacities; 2 alarm features x 9 frozen thresholds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
