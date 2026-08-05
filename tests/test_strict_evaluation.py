from __future__ import annotations

import unittest

import numpy as np

from src.methods.strict_alarm import (
    RobustScoreModel,
    evaluate_alarm_threshold,
    incident_starts,
    temperature_support_distance,
)
from src.experiments.audit_strict_evaluation import AuditError, _descriptor_is_listed, _payload_is_within_cap
from src.methods.strict_codecs import (
    HaarDwtCodec,
    Int16SignalQuantizer,
    PcaCodec,
    PcaModel,
    SodTransitionCodec,
    UniformLinearCodec,
    decode_svarint,
    decode_uvarint,
    encode_svarint,
    encode_uvarint,
    haar_forward,
    haar_inverse,
    next_power_of_two,
)


class StrictCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codes = np.array([0, 2, 2, -3, -3, 7, 1, 1], dtype=np.int16)

    def test_varints_round_trip(self) -> None:
        for value in (0, 1, 127, 128, 16384, 1_000_000):
            payload = encode_uvarint(value)
            decoded, offset = decode_uvarint(payload)
            self.assertEqual(decoded, value)
            self.assertEqual(offset, len(payload))
        for value in (-1_000_000, -12, -1, 0, 1, 12, 1_000_000):
            payload = encode_svarint(value)
            decoded, offset = decode_svarint(payload)
            self.assertEqual(decoded, value)
            self.assertEqual(offset, len(payload))

    def test_sod_packet_round_trip_and_energy(self) -> None:
        codec = SodTransitionCodec(delta_codes=2, signal_scale=0.25)
        packet = codec.encode_path(self.codes)
        decoded = codec.decode_path(packet, len(self.codes))
        self.assertTrue(np.array_equal(decoded, np.array([0, 2, 2, -4, -4, 8, 2, 2], dtype=np.int16)))
        expected = float(np.dot(decoded.astype(float) * 0.25, decoded.astype(float) * 0.25))
        self.assertAlmostEqual(codec.reconstruction_energy(self.codes), expected, places=7)

    def test_bounded_sod_record_never_exceeds_its_path_budget(self) -> None:
        codec = SodTransitionCodec(delta_codes=1, signal_scale=0.25, max_path_payload_bytes=3)
        record = np.stack((self.codes, -self.codes))
        packet = codec.encode_record(record)
        score, payload, mse = codec.evaluate_record_metrics(record)
        self.assertEqual(payload, len(packet))
        self.assertLessEqual(payload, codec.maximum_record_bytes(n_paths=2, n_samples=len(self.codes)))
        self.assertEqual(codec.decode_record(packet, n_paths=2, n_samples=len(self.codes)).shape, record.shape)
        self.assertGreaterEqual(score, 0.0)
        self.assertGreaterEqual(mse, 0.0)

    def test_uniform_packet_round_trip_and_energy(self) -> None:
        codec = UniformLinearCodec(stride=3, signal_scale=0.25)
        packet = codec.encode_path(self.codes)
        decoded = codec.decode_path(packet, len(self.codes))
        expected = float(np.dot(decoded.astype(float) * 0.25, decoded.astype(float) * 0.25))
        self.assertAlmostEqual(codec.reconstruction_energy(self.codes), expected, places=7)

    def test_haar_transform_and_packet_round_trip(self) -> None:
        values = np.arange(13, dtype=np.float32) - 6.0
        coefficients = haar_forward(values)
        self.assertEqual(len(coefficients), next_power_of_two(len(values)))
        self.assertTrue(np.allclose(haar_inverse(coefficients)[:len(values)], values, atol=1e-5))
        codec = HaarDwtCodec(top_k=8, coefficient_scale=0.1, signal_scale=0.25, padded_length=16)
        packet = codec.encode_path(self.codes)
        decoded = codec.decode_path(packet, len(self.codes))
        expected = float(np.dot(decoded.astype(float) * 0.25, decoded.astype(float) * 0.25))
        self.assertAlmostEqual(codec.reconstruction_energy(self.codes), expected, places=5)

    def test_quantizer_uses_training_scale_and_reports_clipping(self) -> None:
        quantizer = Int16SignalQuantizer.fit([np.array([-1.0, 1.0], dtype=np.float32)])
        codes, clipped = quantizer.quantize(np.array([-2.0, 0.5, 2.0], dtype=np.float32))
        self.assertEqual(clipped, 2)
        self.assertEqual(int(codes[1]), 16384)

    def test_pca_packet_model(self) -> None:
        rng = np.random.default_rng(7)
        training = rng.integers(-100, 100, size=(3, 2, 8), dtype=np.int16)
        model = PcaModel.fit(training, signal_scale=0.01, max_rank=2, batch_rows=4)
        codec = PcaCodec(model=model, rank=2)
        packet = codec.encode_path(training[0, 0])
        self.assertEqual(len(packet), 4)
        decoded = codec.decode_path(packet, 8)
        self.assertEqual(decoded.shape, (8,))
        self.assertGreater(codec.model_bytes, len(packet))
        batched = model.evaluate_records(training, ranks=[1, 2], batch_records=2)
        for rank in (1, 2):
            scalar_codec = PcaCodec(model=model, rank=rank)
            scalar_scores = np.array([scalar_codec.evaluate_record(record)[0] for record in training])
            self.assertTrue(np.allclose(batched[rank][0], scalar_scores, rtol=1e-5, atol=1e-7))
            self.assertTrue(np.array_equal(batched[rank][1], np.full(len(training), 2 * rank * 2)))


class StrictAlarmTests(unittest.TestCase):
    def test_incident_deduplication(self) -> None:
        times = np.array([
            "2021-04-01T00:00:00",
            "2021-04-01T00:10:00",
            "2021-04-01T00:35:00",
            "2021-04-01T01:10:00",
        ], dtype="datetime64[s]")
        starts = incident_starts(times, np.array([True, True, True, True]), merge_gap_minutes=30)
        self.assertEqual(starts.tolist(), [times[0], times[3]])

    def test_alarm_metrics_keep_labels_out_of_threshold_fit(self) -> None:
        calibration = np.array([[1.0, 2.0], [1.2, 2.1], [0.8, 1.9]])
        model = RobustScoreModel.fit(calibration)
        score = model.score(np.array([[1.0, 2.0], [5.0, 2.0]]))
        self.assertGreater(score[1], score[0])
        times = np.array([
            "2021-04-01T00:00:00",
            "2021-04-01T00:10:00",
            "2021-04-01T01:00:00",
            "2021-04-01T01:10:00",
        ], dtype="datetime64[s]")
        result = evaluate_alarm_threshold(times, np.array([0, 0, 1, 1]), np.array([0.0, 2.0, 3.0, 4.0]), 1.0)
        self.assertEqual(result["healthy_incident_count"], 1)
        self.assertEqual(result["first_post_onset_delay_minutes"], 0.0)

    def test_pre_onset_incident_is_not_credited_as_detection(self) -> None:
        times = np.array([
            "2021-04-01T00:00:00",
            "2021-04-01T00:10:00",
            "2021-04-01T00:20:00",
            "2021-04-01T00:30:00",
        ], dtype="datetime64[s]")
        result = evaluate_alarm_threshold(
            times,
            np.array([0, 0, 1, 1]),
            np.array([0.0, 2.0, 3.0, 4.0]),
            threshold=1.0,
            merge_gap_minutes=30,
        )
        self.assertEqual(result["healthy_incident_count"], 1)
        self.assertTrue(result["pre_onset_incident_active_at_onset"])
        self.assertIsNone(result["first_post_onset_delay_minutes"])

    def test_temperature_support_distance(self) -> None:
        distance = temperature_support_distance(np.array([10.0, 0.0]), np.array([-1.0, 5.0, 12.0]))
        self.assertTrue(np.array_equal(distance, np.array([1.0, 5.0, 2.0])))


class StrictOutputAuditTests(unittest.TestCase):
    def test_output_audit_rejects_packet_over_cap(self) -> None:
        with self.assertRaises(AuditError):
            _payload_is_within_cap(
                {"mean_bytes_per_record": 1024.0, "maximum_bytes_per_record": 2049.0},
                2048,
                "synthetic packet",
            )

    def test_output_audit_traces_selected_descriptor(self) -> None:
        selected = {"name": "sod_transition_bounded", "delta_codes": 64}
        candidates = [
            {"name": "sod_transition_bounded", "delta_codes": 1},
            {"name": "sod_transition_bounded", "delta_codes": 64, "mean_bytes_per_record": 1024.0},
        ]
        self.assertTrue(_descriptor_is_listed(selected, candidates))
        self.assertFalse(_descriptor_is_listed({"name": "sod_transition_bounded", "delta_codes": 512}, candidates))


if __name__ == "__main__":
    unittest.main()
