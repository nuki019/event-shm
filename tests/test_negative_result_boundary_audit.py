"""Synthetic checks for the strict negative-result paper evidence boundary."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.experiments import audit_negative_result_boundary as boundary


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _artifact_entries(root: Path, expected: dict[str, tuple[str, str]]) -> list[dict]:
    return [
        {
            "id": identifier,
            "role": role,
            "path": relative_path,
            "sha256": _sha256(root / relative_path),
        }
        for identifier, (role, relative_path) in expected.items()
    ]


def _write_manuscript_fixture(root: Path) -> None:
    main = r"""
\input{sections/intro}
\input{sections/related}
\input{sections/method}
\input{sections/data}
\input{sections/experiments}
\input{sections/results}
\input{sections/discussion}
\input{sections/conclusion}
\bibliographystyle{ieeetr}
\bibliography{refs}
"""
    _write_text(root / "paper" / "main.tex", main)
    _write_text(
        root / "paper" / "sections" / "intro.tex",
        "bounded SoD does not lead the held-out record-AUC comparison. "
        "The replay cannot establish an operational-alarm claim.",
    )
    for name in ("related", "method", "data", "experiments", "discussion"):
        _write_text(root / "paper" / "sections" / f"{name}.tex", f"{name} scope text.")
    _write_text(
        root / "paper" / "sections" / "results.tex",
        r"\includegraphics{e7_strict_codec_benchmark_v1.png}" "\n"
        r"\includegraphics{e8_cold_start_alarm_v1.png}",
    )
    _write_text(
        root / "paper" / "sections" / "conclusion.tex",
        "It does not assert a universal SoD mechanism, external confirmation, or deployment performance. "
        "The audits are not a shared mechanism study or a deployment validation.",
    )
    _write_text(root / "paper" / "refs.bib", "@article{fixture,title={fixture}}")
    for name in ("e7_strict_codec_benchmark_v1.png", "e8_cold_start_alarm_v1.png"):
        path = root / "paper" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic PNG fixture")


def _fixture_manifest(root: Path) -> dict:
    protocol = root / "protocols" / "strict_evaluation_v1.json"
    e7 = root / "results" / "e7_strict_codec_benchmark_v1.json"
    e8 = root / "results" / "e8_cold_start_alarm_v1.json"
    invalidation = root / "protocols" / "mechanism_v2_6_invalidation_receipt.json"
    _write_json(protocol, {"protocol_id": "strict-evaluation-v1"})
    _write_json(e7, {"protocol_id": "strict-evaluation-v1", "smoke": False})
    _write_json(
        e8,
        {
            "protocol_id": "strict-evaluation-v1",
            "smoke": False,
            "feature_results": {"synthetic": {"blind_test_curve": [
                {"pre_onset_incident_active_at_onset": False},
            ]}},
        },
    )
    _write_json(
        invalidation,
        {
            "invalidated_protocol_id": "mechanism-v2.6",
            "invalidation_status": "invalidated_after_pre_freeze_d16_output_and_interrupted_morpho_waveform_access",
            "evidence_boundary": dict(boundary.REQUIRED_V26_EXCLUSION_FLAGS),
        },
    )
    _write_manuscript_fixture(root)
    return {
        "manifest_id": boundary.MANIFEST_ID,
        "paper_route": "strict_negative_result_and_applicability_boundary",
        "artifacts": _artifact_entries(root, boundary.EXPECTED_EVIDENCE_ARTIFACTS),
        "manuscript_inputs": _artifact_entries(root, boundary.EXPECTED_MANUSCRIPT_INPUTS),
        "paper_eligible_empirical_artifacts": list(boundary.REQUIRED_PAPER_EVIDENCE),
        "exclusion_only_artifacts": list(boundary.REQUIRED_EXCLUSION_EVIDENCE),
        "required_invalidation_flags": dict(boundary.REQUIRED_V26_EXCLUSION_FLAGS),
        "required_invalidation_flag_interpretations": dict(boundary.REQUIRED_V26_FLAG_INTERPRETATIONS),
        "allowed_scope_bounded_claims": list(boundary.ALLOWED_SCOPE_BOUNDED_CLAIMS),
        "prohibited_claims": list(boundary.PROHIBITED_CLAIMS),
    }


class NegativeResultBoundaryAuditTests(unittest.TestCase):
    def test_pdf_page_count_tolerates_localized_non_utf8_metadata(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="Pages: 8\n", stderr="")
        with patch.object(boundary.subprocess, "run", return_value=completed) as run:
            self.assertEqual(boundary._pdf_page_count(Path("paper/main.pdf")), 8)
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_valid_fixture_has_strict_results_and_exclusion_only_v26(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _fixture_manifest(root)
            with patch.object(boundary, "audit_e7") as audit_e7, patch.object(boundary, "audit_e8") as audit_e8:
                result = boundary.audit_negative_result_boundary(manifest, root=root)
            audit_e7.assert_called_once()
            audit_e8.assert_called_once()
            self.assertIn("protocol_sha256", result)
            self.assertIn("manuscript_main_tex_sha256", result)

    def test_hash_drift_rejects_a_recast_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _fixture_manifest(root)
            _write_json(root / "results" / "e7_strict_codec_benchmark_v1.json",
                        {"protocol_id": "strict-evaluation-v1", "smoke": True})
            with self.assertRaisesRegex(boundary.BoundaryAuditError, "e7_result SHA-256"):
                boundary.audit_negative_result_boundary(manifest, root=root)

    def test_missing_required_flag_or_claim_rewrite_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _fixture_manifest(root)
            del manifest["required_invalidation_flags"]["morpho_waveform_access_is_treated_as_consumed"]
            with patch.object(boundary, "audit_e7"), patch.object(boundary, "audit_e8"):
                with self.assertRaisesRegex(boundary.BoundaryAuditError, "required_invalidation_flags"):
                    boundary.audit_negative_result_boundary(manifest, root=root)

            manifest = _fixture_manifest(root)
            manifest["allowed_scope_bounded_claims"][0] = "Universal superiority is established."
            with patch.object(boundary, "audit_e7"), patch.object(boundary, "audit_e8"):
                with self.assertRaisesRegex(boundary.BoundaryAuditError, "allowed_scope_bounded_claims"):
                    boundary.audit_negative_result_boundary(manifest, root=root)

    def test_workspace_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _fixture_manifest(root)
            manifest["artifacts"][0]["path"] = "../outside.json"
            with self.assertRaisesRegex(boundary.BoundaryAuditError, "wrong workspace path"):
                boundary.audit_negative_result_boundary(manifest, root=root)

    def test_manuscript_hash_drift_and_historical_identifier_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _fixture_manifest(root)
            main = root / "paper" / "main.tex"
            _write_text(main, main.read_text(encoding="utf-8") + "\nchanged")
            with self.assertRaisesRegex(boundary.BoundaryAuditError, "main_tex SHA-256"):
                boundary.audit_negative_result_boundary(manifest, root=root)

            manifest = _fixture_manifest(root)
            main = root / "paper" / "main.tex"
            _write_text(main, main.read_text(encoding="utf-8") + "\nMORPHO")
            for artifact in manifest["manuscript_inputs"]:
                if artifact["id"] == "main_tex":
                    artifact["sha256"] = _sha256(main)
            with self.assertRaisesRegex(boundary.BoundaryAuditError, "excluded historical identifier"):
                boundary.audit_negative_result_boundary(manifest, root=root)

    def test_paper_route_rejects_a_pre_onset_active_alarm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _fixture_manifest(root)
            e8_path = root / "results" / "e8_cold_start_alarm_v1.json"
            e8 = json.loads(e8_path.read_text(encoding="utf-8"))
            e8["feature_results"]["synthetic"]["blind_test_curve"][0]["pre_onset_incident_active_at_onset"] = True
            _write_json(e8_path, e8)
            for artifact in manifest["artifacts"]:
                if artifact["id"] == "e8_result":
                    artifact["sha256"] = _sha256(e8_path)
            with patch.object(boundary, "audit_e7"), patch.object(boundary, "audit_e8"):
                with self.assertRaisesRegex(boundary.BoundaryAuditError, "all-new-alarm"):
                    boundary.audit_negative_result_boundary(manifest, root=root)


if __name__ == "__main__":
    unittest.main()
