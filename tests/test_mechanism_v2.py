from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from src.data.mechanism_hdf5_schema import inspect_hdf5_metadata, schema_gate_result
from src.experiments.download_mechanism_v2_data import DownloadError, _resolve_within_workspace
from src.experiments.audit_mechanism_v2 import AuditError, audit_result
from src.methods.mechanism_v2 import (
    EVENT_FEATURE_NAMES,
    MechanismInvariantError,
    RobustEventDiagnostic,
    canonical_collision_probe,
    canonical_terminal_hold_probe,
    control_injection_grid,
    frequency_bands_from_nyquist_fractions,
    grouped_auc_bootstrap,
    quantization_collision_evidence,
    record_waveform_metrics,
    terminal_hold_evidence,
    trace_record_features,
    validate_group_split,
)
from src.methods.strict_codecs import SodTransitionCodec


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "protocols" / "mechanism_v2.json"
MANIFEST_PATH = ROOT / "protocols" / "mechanism_v2_data_manifest.json"


class SodMechanismTraceTests(unittest.TestCase):
    def test_trace_matches_payload_and_exposes_cap_hold(self) -> None:
        codec = SodTransitionCodec(delta_codes=2, signal_scale=1.0, max_path_payload_bytes=5)
        record = np.array([[0, 2, 0, 2, 0, 2], [0, -2, 0, -2, 0, -2]], dtype=np.int16)
        trace, features = trace_record_features(codec, record)
        self.assertEqual(trace.payload, codec.encode_record(record))
        self.assertEqual(trace.packet_bytes, len(codec.encode_record(record)))
        self.assertEqual(features.shape, (2, len(EVENT_FEATURE_NAMES)))
        self.assertTrue(all(path_trace.cap_saturated for path_trace in trace.path_traces))
        self.assertTrue(all(path_trace.cap_hold_samples > 0 for path_trace in trace.path_traces))

    def test_sublevel_collision_and_terminal_hold_propositions(self) -> None:
        unbounded = SodTransitionCodec(delta_codes=8, signal_scale=1.0)
        baseline, perturbed = canonical_collision_probe(delta_codes=8)
        collision = quantization_collision_evidence(unbounded, baseline, perturbed)
        self.assertTrue(collision["same_quantized_levels"])
        self.assertTrue(collision["same_serialized_payload"])
        bounded = SodTransitionCodec(delta_codes=8, signal_scale=1.0, max_path_payload_bytes=5)
        first, second = canonical_terminal_hold_probe(delta_codes=8, max_path_payload_bytes=5)
        terminal = terminal_hold_evidence(bounded, first, second)
        self.assertTrue(terminal["first_cap_saturated"])
        self.assertTrue(terminal["second_cap_saturated"])
        self.assertTrue(terminal["same_serialized_payload"])
        self.assertTrue(terminal["same_decoded_output"])
        with self.assertRaises(MechanismInvariantError):
            canonical_collision_probe(delta_codes=1)

    def test_fixed_event_diagnostic_uses_healthy_tensor_only(self) -> None:
        healthy = np.zeros((4, 2, len(EVENT_FEATURE_NAMES)), dtype=np.float64)
        healthy[1, :, 0] = 1.0
        model = RobustEventDiagnostic.fit(healthy)
        target = healthy.copy()
        target[-1, 0, 2] = 10.0
        scores = model.score(target)
        self.assertEqual(set(scores), {"global", "max_path"})
        self.assertEqual(scores["global"].shape, (4,))
        self.assertGreater(scores["max_path"][-1], scores["max_path"][0])

    def test_waveform_metric_grid_is_fixed(self) -> None:
        source = np.stack((np.sin(np.linspace(0, 2 * np.pi, 64)), np.cos(np.linspace(0, 2 * np.pi, 64))))
        reconstructed = np.roll(source, 2, axis=1)
        bands = frequency_bands_from_nyquist_fractions(10_000.0, ((0.01, 0.1), (0.1, 0.2)))
        metrics = record_waveform_metrics(source, reconstructed, 10_000.0, bands, 8)
        self.assertIn("frequency_band_retention", metrics)
        self.assertIn("50-500Hz", metrics["frequency_band_retention"])
        self.assertGreaterEqual(metrics["relative_error_mean"], 0.0)


class DownloadPathTests(unittest.TestCase):
    def test_relative_receipt_paths_resolve_inside_workspace(self) -> None:
        resolved = _resolve_within_workspace(Path("data") / "raw", "destination")
        self.assertEqual(resolved, ROOT / "data" / "raw")
        with self.assertRaises(DownloadError):
            _resolve_within_workspace(Path("C:/outside-mechanism-workspace"), "destination")


class GroupAndSchemaTests(unittest.TestCase):
    def test_group_split_and_group_bootstrap_never_use_paths(self) -> None:
        assignments = validate_group_split(["a", "a", "b", "c"], ["train", "train", "validation", "test"])
        self.assertEqual(assignments["a"], ["train"])
        with self.assertRaises(MechanismInvariantError):
            validate_group_split(["a", "a"], ["train", "test"])
        output = grouped_auc_bootstrap(
            np.array([0, 0, 1, 1]),
            np.array([0.1, 0.2, 0.8, 0.9]),
            ["h1", "h2", "d1", "d2"],
            n_bootstrap=20,
            seed=7,
        )
        self.assertEqual(output["bootstrap_unit"], "predeclared_group")
        self.assertEqual(output["roc_auc"], 1.0)

    def test_hdf5_schema_gate_checks_structure_before_signal_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            h5_path = Path(temporary) / "synthetic.h5"
            with h5py.File(h5_path, "w") as handle:
                handle.create_dataset("waveforms", data=np.zeros((3, 2, 16), dtype=np.float32))
                handle.create_dataset("uid", data=np.array([1, 2, 3], dtype=np.int64))
                handle.create_dataset("block", data=np.array([1, 1, 2], dtype=np.int64))
                handle.create_dataset("state", data=np.array([0, 0, 1], dtype=np.int64))
                handle.create_dataset("sampling_rate", data=np.array([1_000_000.0]))
            inventory = inspect_hdf5_metadata(h5_path)
            mapping = {
                "waveform_dataset_path": "/waveforms",
                "sample_axis": 2,
                "measurement_uid_field": "/uid",
                "group_field": "/block",
                "state_label_field": "/state",
                "sampling_rate_field": "/sampling_rate",
            }
            passed = schema_gate_result(inventory, mapping)
            self.assertEqual(passed["status"], "passed")
            mapping["state_label_field"] = "/not_present"
            failed = schema_gate_result(inventory, mapping)
            self.assertEqual(failed["status"], "failed")


class MechanismAuditTests(unittest.TestCase):
    def _valid_result(self) -> dict:
        protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        capacities = protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]
        deltas = protocol["eventization_grid"]["delta_codes"]
        retention = {"20000-60000Hz": 1.0}
        grid_results = []
        for capacity in capacities:
            for delta in deltas:
                event_summary = {
                    "roc_auc": 0.5,
                    "roc_auc_ci95": [0.4, 0.6],
                    "bootstrap_unit": "predeclared_group",
                }
                grid_results.append(
                    {
                        "capacity_bytes": capacity,
                        "delta_codes": delta,
                        "waveform_metrics": {
                            "waveform_correlation_mean": 0.5,
                            "relative_error_mean": 1.0,
                            "peak_cross_correlation_delay_samples_median": 0.0,
                            "peak_cross_correlation_delay_samples_mean_absolute": 0.0,
                            "frequency_band_retention": retention,
                            "event_density": 0.1,
                            "cap_hold_fraction": 0.2,
                        },
                        "event_statistics": {
                            "mean_event_features": {name: 0.0 for name in EVENT_FEATURE_NAMES},
                            "fixed_trace_receipt": {
                                "event_times_sha256": "3" * 64,
                                "event_level_deltas_sha256": "4" * 64,
                            },
                        },
                        "event_diagnostic": {"global": dict(event_summary), "max_path": dict(event_summary)},
                        "loss_decomposition": {
                            "quantization_only": {},
                            "hard_cap_truncation": {},
                            "score_head_mismatch": {},
                        },
                        "cap_evidence": {
                            "all_packets_within_declared_capacity": True,
                            "mean_cap_hold_fraction": 0.2,
                            "cap_saturated_path_fraction": 0.3,
                            "mean_bytes_per_record": capacity / 2,
                            "bits_per_original_sample": 1.0,
                        },
                    }
                )
        probes = []
        for capacity in capacities:
            for delta in deltas:
                probes.append(
                    {
                        "capacity_bytes": capacity,
                        "delta_codes": delta,
                        "proposition": "quantization_collision",
                        "status": "not_applicable" if delta <= 2 else "passed",
                        "same_quantized_levels": delta > 2,
                        "same_serialized_payload": delta > 2,
                    }
                )
                probes.append(
                    {
                        "capacity_bytes": capacity,
                        "delta_codes": delta,
                        "proposition": "terminal_hold",
                        "status": "passed",
                        "first_cap_saturated": True,
                        "second_cap_saturated": True,
                        "same_serialized_payload": True,
                        "same_decoded_output": True,
                    }
                )
        return {
            "protocol_id": "mechanism-v2",
            "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
            "data_manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            "code_revision": "synthetic-test",
            "outcome_type": "confirmation",
            "data": {
                "dataset_id": "ogw_cfrp_temperature_dam_d12",
                "data_role": "same_plate_blind_confirmation",
                "archive_and_content_hashes": [
                    {
                        "filename": "OGW_CFRP_Temperature_dam_D12.zip",
                        "md5": "c4d82a54f813c2863a8202a212116b01",
                        "sha256": "0" * 64,
                        "md5_verified_before_waveform_access": True,
                    }
                ],
                "schema_gate": {"status": "passed", "schema_fingerprint_sha256": "1" * 64},
            },
            "selection_receipt": {
                "discovery_data_used_for_selection": False,
                "posthoc_configuration_selection": False,
                "test_labels_read_after_scoring": True,
                "all_configurations_fixed_before_confirmation": True,
            },
            "configuration": {
                "capacity_bytes_per_record": capacities,
                "delta_codes": deltas,
                "event_features": list(EVENT_FEATURE_NAMES),
                "aggregation_heads": ["global", "max_path"],
            },
            "group_split": {
                "unit_of_analysis": "monitoring_record",
                "split_manifest_sha256": "2" * 64,
                "splits": {"train": ["t1"], "validation": ["v1"], "test": ["x1"]},
                "paths_or_repeats_are_independent_samples": False,
            },
            "grid_results": grid_results,
            "mechanism_probes": probes,
            "control_injections": [
                {"control_id": item["control_id"], "status": "evaluated"}
                for item in control_injection_grid(capacities, deltas, protocol["healthy_control_injections"])
            ],
        }

    def test_audit_accepts_complete_grid_and_rejects_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "result.json"
            result = self._valid_result()
            result_path.write_text(json.dumps(result), encoding="utf-8")
            audit_result(PROTOCOL_PATH, MANIFEST_PATH, result_path)
            result["grid_results"].pop()
            result_path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(AuditError):
                audit_result(PROTOCOL_PATH, MANIFEST_PATH, result_path)

    def test_audit_rejects_discovery_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "result.json"
            result = self._valid_result()
            result["selection_receipt"]["discovery_data_used_for_selection"] = True
            result_path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(AuditError):
                audit_result(PROTOCOL_PATH, MANIFEST_PATH, result_path)


if __name__ == "__main__":
    unittest.main()
