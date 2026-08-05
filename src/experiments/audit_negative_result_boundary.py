"""Read-only eligibility, manuscript-source, and build-snapshot audit.

The source audit binds the strict negative-result paper to strict-evaluation-v1
plus the completed E7/E8 artifacts. mechanism-v2.6 is inspected only as an
exclusion record. A later build receipt can bind one rendered XeLaTeX snapshot
to a preceding Git source commit. Neither audit proves execution chronology,
raw-data provenance, unrecorded access, or scientific generalization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.experiments.audit_strict_evaluation import AuditError as StrictAuditError
from src.experiments.audit_strict_evaluation import audit_e7, audit_e8


DEFAULT_MANIFEST = ROOT / "paper" / "NEGATIVE_RESULT_BOUNDARY_EVIDENCE_MANIFEST.json"
BUILD_RECEIPT_ID = "strict-negative-result-boundary-build-receipt-v1"
MANIFEST_ID = "strict-negative-result-boundary-paper-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

EXPECTED_EVIDENCE_ARTIFACTS = {
    "strict_evaluation_protocol": (
        "only_paper_eligible_evaluation_protocol",
        "protocols/strict_evaluation_v1.json",
    ),
    "e7_result": (
        "paper_eligible_empirical_result",
        "results/e7_strict_codec_benchmark_v1.json",
    ),
    "e8_result": (
        "paper_eligible_empirical_result",
        "results/e8_cold_start_alarm_v1.json",
    ),
    "mechanism_v2_6_invalidation": (
        "exclusion_only_integrity_record",
        "protocols/mechanism_v2_6_invalidation_receipt.json",
    ),
}

EXPECTED_MANUSCRIPT_INPUTS = {
    "main_tex": ("manuscript_tex", "paper/main.tex"),
    "intro_tex": ("manuscript_tex", "paper/sections/intro.tex"),
    "related_tex": ("manuscript_tex", "paper/sections/related.tex"),
    "method_tex": ("manuscript_tex", "paper/sections/method.tex"),
    "data_tex": ("manuscript_tex", "paper/sections/data.tex"),
    "experiments_tex": ("manuscript_tex", "paper/sections/experiments.tex"),
    "results_tex": ("manuscript_tex", "paper/sections/results.tex"),
    "discussion_tex": ("manuscript_tex", "paper/sections/discussion.tex"),
    "conclusion_tex": ("manuscript_tex", "paper/sections/conclusion.tex"),
    "references_bib": ("manuscript_bibliography", "paper/refs.bib"),
    "e7_figure": ("manuscript_figure", "paper/e7_strict_codec_benchmark_v1.png"),
    "e8_figure": ("manuscript_figure", "paper/e8_cold_start_alarm_v1.png"),
}

REQUIRED_PAPER_EVIDENCE = (
    "strict_evaluation_protocol",
    "e7_result",
    "e8_result",
)
REQUIRED_EXCLUSION_EVIDENCE = ("mechanism_v2_6_invalidation",)
REQUIRED_V26_EXCLUSION_FLAGS = {
    "v2_6_d16_output_is_historical_integrity_evidence_only": True,
    "v2_6_terminal_hold_receipt_is_not_mechanism_performance_evidence": True,
    "v2_6_external_schema_gate_is_not_external_confirmation_evidence": True,
    "morpho_waveform_access_is_treated_as_consumed": True,
    "morpho_is_not_an_untouched_blind_confirmation_source_for_any_successor": True,
    "morpho_auc_reconstruction_loss_control_injection_or_partial_grid_claims_are_not_eligible": True,
    "d16_and_morpho_must_not_be_resumed_rerun_overwritten_or_recast": True,
    "d04_d24_remain_discovery_only": True,
    "e7_e8_remain_independent_strict_negative_result_evidence": True,
    "pod_field_far_hardware_power_realtime_and_deployment_claims_remain_prohibited": True,
}
REQUIRED_V26_FLAG_INTERPRETATIONS = {
    "d04_d24_remain_discovery_only": (
        "Within the invalidated mechanism-v2.6 chain, this flag prohibits D04/D24 "
        "from being reused as fresh blind-confirmation sources; it does not alter "
        "their completed strict-evaluation-v1 E7 role."
    )
}
ALLOWED_SCOPE_BOUNDED_CLAIMS = (
    "Under strict-evaluation-v1, bounded SoD does not lead held-out record AUC among the four tested codecs at any declared record capacity for the held-out D04 and D24 conditions.",
    "Under the frozen March-to-April cold-start replay, the two tested alarm features cannot establish an operational-alarm claim.",
    "The conclusions apply only to post-compensation software replay on the declared data splits and codec/alarm families.",
)
PROHIBITED_CLAIMS = (
    "A mechanism result, external confirmation, or performance conclusion derived from mechanism-v2.x artifacts.",
    "Population probability of detection, calibrated field false-alarm rate, multi-structure generalization, hardware energy, MCU performance, real-time latency, or deployment readiness.",
    "A universal statement about all Send-on-Delta implementations, structures, damage morphologies, or dense/learned alternatives.",
)
FORBIDDEN_HISTORICAL_IDENTIFIERS = (
    "D12",
    "D16",
    "MORPHO",
    "COQTEL",
    "COPV",
    "mechanism-v2",
    "terminal-hold",
)
REQUIRED_MANUSCRIPT_SCOPE_PHRASES = (
    "bounded sod does not lead the held-out record-auc comparison",
    "cannot establish an operational-alarm claim",
    "does not assert a universal sod mechanism, external confirmation, or deployment performance",
    "not a shared mechanism study or a deployment validation",
)
REQUIRED_BUILD_COMMANDS = (
    "xelatex -interaction=nonstopmode -halt-on-error -file-line-error -recorder main.tex",
    "bibtex main",
    "xelatex -interaction=nonstopmode -halt-on-error -file-line-error -recorder main.tex",
    "xelatex -interaction=nonstopmode -halt-on-error -file-line-error -recorder main.tex",
)
EXPECTED_BUILD_OUTPUTS = {
    "pdf": "paper/main.pdf",
    "bbl": "paper/main.bbl",
    "fls": "paper/main.fls",
    "log": "paper/main.log",
}
LOG_FAILURE_MARKERS = (
    "LaTeX Warning: There were undefined references",
    "LaTeX Warning: Citation",
    "Undefined control sequence",
    "Emergency stop",
    "Fatal error occurred",
)


class BoundaryAuditError(ValueError):
    """Raised when a paper-evidence boundary is violated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BoundaryAuditError(message)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BoundaryAuditError(f"cannot read {path}: {error}") from error
    _require(isinstance(payload, dict), f"{path} must contain a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise BoundaryAuditError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _resolve_within_root(root: Path, relative_path: Any, context: str) -> Path:
    _require(isinstance(relative_path, str) and relative_path, f"{context} path is missing")
    candidate = Path(relative_path)
    _require(not candidate.is_absolute(), f"{context} path must be relative to the workspace")
    root_resolved = root.resolve()
    target = (root_resolved / candidate).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as error:
        raise BoundaryAuditError(f"{context} path escapes the workspace") from error
    return target


def _artifact_index(
    document: dict[str, Any],
    field: str,
    expected: dict[str, tuple[str, str]],
    root: Path,
) -> dict[str, Path]:
    artifacts = document.get(field)
    _require(isinstance(artifacts, list), f"{field} must be a list")
    indexed: dict[str, Path] = {}
    for artifact in artifacts:
        _require(isinstance(artifact, dict), f"each {field} entry must be an object")
        identifier = artifact.get("id")
        _require(isinstance(identifier, str) and identifier not in indexed,
                 f"{field} identifiers must be unique strings")
        _require(identifier in expected, f"unexpected {field} identifier: {identifier}")
        expected_role, expected_path = expected[identifier]
        _require(artifact.get("role") == expected_role, f"{identifier} has the wrong role")
        _require(artifact.get("path") == expected_path, f"{identifier} has the wrong workspace path")
        expected_hash = artifact.get("sha256")
        _require(isinstance(expected_hash, str) and SHA256_RE.fullmatch(expected_hash) is not None,
                 f"{identifier} has an invalid SHA-256")
        path = _resolve_within_root(root, expected_path, identifier)
        observed_hash = _sha256_file(path)
        _require(observed_hash == expected_hash, f"{identifier} SHA-256 does not match the manifest")
        indexed[identifier] = path
    _require(set(indexed) == set(expected), f"{field} must contain exactly the required artifacts")
    return indexed


def _require_exact_id_list(document: dict[str, Any], field: str, expected: tuple[str, ...]) -> None:
    values = document.get(field)
    _require(values == list(expected), f"{field} does not match the frozen evidence role")


def _normalise_source(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _resolve_paper_dependency(root: Path, value: str, suffix: str, context: str) -> Path:
    candidate = Path(value)
    _require(not candidate.is_absolute(), f"{context} must be relative")
    if candidate.suffix == "":
        candidate = candidate.with_suffix(suffix)
    return _resolve_within_root(root, (Path("paper") / candidate).as_posix(), context)


def _audit_manuscript_inputs(manifest: dict[str, Any], root: Path) -> dict[str, Path]:
    inputs = _artifact_index(manifest, "manuscript_inputs", EXPECTED_MANUSCRIPT_INPUTS, root)
    paper_root = (root / "paper").resolve()
    expected_paths = set(inputs.values())
    visited_tex: set[Path] = set()
    discovered_paths: set[Path] = set()
    source_text: dict[Path, str] = {}
    pending = [inputs["main_tex"]]

    while pending:
        source_path = pending.pop()
        if source_path in visited_tex:
            continue
        _require(source_path.suffix == ".tex", f"{source_path} is not a TeX source")
        visited_tex.add(source_path)
        discovered_paths.add(source_path)
        try:
            text = source_path.read_text(encoding="utf-8")
        except OSError as error:
            raise BoundaryAuditError(f"cannot read manuscript source {source_path}: {error}") from error
        source_text[source_path] = text
        _require(r"\write18" not in text, f"{source_path} enables shell escape")
        for match in re.finditer(r"\\(input|include|includegraphics|bibliography)\b", text):
            command = match.group(1)
            remainder = text[match.end():].lstrip()
            if command == "includegraphics" and remainder.startswith("["):
                option_end = remainder.find("]")
                _require(option_end >= 0, f"{source_path} has an unterminated \\includegraphics option")
                remainder = remainder[option_end + 1:].lstrip()
            _require(remainder.startswith("{"), f"{source_path} has a dynamic \\{command} dependency")
        for target in re.findall(r"\\(?:input|include)\{([^{}]+)\}", text):
            dependency = _resolve_paper_dependency(root, target, ".tex", f"{source_path} TeX dependency")
            _require(dependency in expected_paths, f"{source_path} imports an unlisted manuscript source")
            pending.append(dependency)
        for target in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^{}]+)\}", text):
            dependency = _resolve_paper_dependency(root, target, ".png", f"{source_path} figure dependency")
            _require(dependency in expected_paths, f"{source_path} imports an unlisted manuscript figure")
            discovered_paths.add(dependency)
        for targets in re.findall(r"\\bibliography\{([^{}]+)\}", text):
            for target in targets.split(","):
                dependency = _resolve_paper_dependency(root, target.strip(), ".bib", f"{source_path} bibliography dependency")
                _require(dependency in expected_paths, f"{source_path} imports an unlisted bibliography")
                discovered_paths.add(dependency)

    styles = re.findall(r"\\bibliographystyle\{([^{}]+)\}", source_text[inputs["main_tex"]])
    _require(styles == ["ieeetr"], "manuscript bibliography style is not frozen to ieeetr")
    _require(discovered_paths == expected_paths,
             "manuscript dependency closure does not match the frozen input list")
    combined_source = _normalise_source("\n".join(source_text.values()))
    for identifier in FORBIDDEN_HISTORICAL_IDENTIFIERS:
        identifier_pattern = re.compile(
            rf"(?<![a-z0-9_-]){re.escape(identifier.lower())}(?![a-z0-9_-])"
        )
        _require(identifier_pattern.search(combined_source) is None,
                 f"manuscript source mentions excluded historical identifier {identifier}")
    for phrase in REQUIRED_MANUSCRIPT_SCOPE_PHRASES:
        _require(phrase in combined_source, f"manuscript source lacks required scope phrase: {phrase}")
    _require(all(path.is_relative_to(paper_root) for path in expected_paths),
             "manuscript input list escapes the paper directory")
    return inputs


def _require_paper_e8_compatibility(e8: dict[str, Any]) -> None:
    features = e8.get("feature_results")
    _require(isinstance(features, dict), "E8 paper compatibility check lacks feature results")
    for feature_name, feature in features.items():
        _require(isinstance(feature, dict), f"E8 {feature_name} is not an object")
        curve = feature.get("blind_test_curve")
        _require(isinstance(curve, list), f"E8 {feature_name} lacks a blind-test curve")
        for index, point in enumerate(curve):
            _require(isinstance(point, dict), f"E8 {feature_name} point {index} is not an object")
            _require(point.get("pre_onset_incident_active_at_onset") is False,
                     f"E8 {feature_name} point {index} conflicts with the manuscript's all-new-alarm statement")


def audit_negative_result_boundary(manifest: dict[str, Any], *, root: Path = ROOT) -> dict[str, str]:
    """Validate paper eligibility, manuscript closure, and scope exclusions."""
    _require(manifest.get("manifest_id") == MANIFEST_ID, "unsupported negative-result boundary manifest")
    _require(manifest.get("paper_route") == "strict_negative_result_and_applicability_boundary",
             "manifest does not select the strict negative-result paper route")
    _require_exact_id_list(manifest, "paper_eligible_empirical_artifacts", REQUIRED_PAPER_EVIDENCE)
    _require_exact_id_list(manifest, "exclusion_only_artifacts", REQUIRED_EXCLUSION_EVIDENCE)

    artifacts = _artifact_index(manifest, "artifacts", EXPECTED_EVIDENCE_ARTIFACTS, root)
    manuscript_inputs = _audit_manuscript_inputs(manifest, root)
    protocol = _load_json(artifacts["strict_evaluation_protocol"])
    e7 = _load_json(artifacts["e7_result"])
    e8 = _load_json(artifacts["e8_result"])
    _require(protocol.get("protocol_id") == "strict-evaluation-v1", "strict protocol identifier is wrong")
    try:
        audit_e7(protocol, e7)
        audit_e8(protocol, e8)
    except StrictAuditError as error:
        raise BoundaryAuditError(f"strict paper result contract failed: {error}") from error
    _require_paper_e8_compatibility(e8)

    invalidation = _load_json(artifacts["mechanism_v2_6_invalidation"])
    _require(invalidation.get("invalidated_protocol_id") == "mechanism-v2.6",
             "the exclusion record does not invalidate mechanism-v2.6")
    _require(invalidation.get("invalidation_status") ==
             "invalidated_after_pre_freeze_d16_output_and_interrupted_morpho_waveform_access",
             "the exclusion record has an unexpected terminal status")
    _require(manifest.get("required_invalidation_flags") == REQUIRED_V26_EXCLUSION_FLAGS,
             "required_invalidation_flags differs from the frozen v2.6 exclusion set")
    _require(manifest.get("required_invalidation_flag_interpretations") == REQUIRED_V26_FLAG_INTERPRETATIONS,
             "required_invalidation_flag_interpretations differs from the frozen scope")
    boundary = invalidation.get("evidence_boundary")
    _require(boundary == REQUIRED_V26_EXCLUSION_FLAGS,
             "v2.6 invalidation record does not contain the frozen exclusion set")
    _require(manifest.get("allowed_scope_bounded_claims") == list(ALLOWED_SCOPE_BOUNDED_CLAIMS),
             "allowed_scope_bounded_claims differs from the frozen boundary text")
    _require(manifest.get("prohibited_claims") == list(PROHIBITED_CLAIMS),
             "prohibited_claims differs from the frozen boundary text")

    hashes = {
        "protocol_sha256": _sha256_file(artifacts["strict_evaluation_protocol"]),
        "e7_sha256": _sha256_file(artifacts["e7_result"]),
        "e8_sha256": _sha256_file(artifacts["e8_result"]),
        "v2_6_invalidation_sha256": _sha256_file(artifacts["mechanism_v2_6_invalidation"]),
    }
    hashes.update({f"manuscript_{identifier}_sha256": _sha256_file(path)
                   for identifier, path in manuscript_inputs.items()})
    return hashes


def _git(root: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=text,
    )


def _git_text(root: Path, *args: str) -> str:
    result = _git(root, *args)
    _require(result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = _git(root, *args, text=False)
    _require(result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _snapshot_input_hashes(manifest: dict[str, Any], root: Path) -> dict[str, str]:
    evidence = _artifact_index(manifest, "artifacts", EXPECTED_EVIDENCE_ARTIFACTS, root)
    manuscript = _artifact_index(manifest, "manuscript_inputs", EXPECTED_MANUSCRIPT_INPUTS, root)
    hashes = {path.relative_to(root).as_posix(): _sha256_file(path)
              for path in [*evidence.values(), *manuscript.values()]}
    manifest_path = _resolve_within_root(root, "paper/NEGATIVE_RESULT_BOUNDARY_EVIDENCE_MANIFEST.json",
                                         "evidence manifest")
    hashes[manifest_path.relative_to(root).as_posix()] = _sha256_file(manifest_path)
    return dict(sorted(hashes.items()))


def _receipt_output(root: Path, path: Path, entry: Any, identifier: str) -> None:
    _require(isinstance(entry, dict), f"build receipt {identifier} entry is missing")
    _require(entry.get("path") == path.as_posix(), f"build receipt {identifier} path is wrong")
    expected_hash = entry.get("sha256")
    _require(isinstance(expected_hash, str) and SHA256_RE.fullmatch(expected_hash) is not None,
             f"build receipt {identifier} hash is invalid")
    local_path = root / path
    _require(_sha256_file(local_path) == expected_hash, f"build receipt {identifier} hash drifted")
    _require(entry.get("bytes") == local_path.stat().st_size, f"build receipt {identifier} byte count drifted")


def _pdf_page_count(path: Path) -> int:
    # Windows-localized pdfinfo metadata can contain bytes outside the active
    # Python console codec.  Page parsing needs the ASCII ``Pages`` line, so
    # preserve it with replacement rather than failing before the audit.
    result = subprocess.run(
        ["pdfinfo", str(path)], check=False, capture_output=True, text=True, errors="replace"
    )
    stderr = result.stderr or ""
    _require(result.returncode == 0, f"pdfinfo failed for {path}: {stderr.strip()}")
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout or "", flags=re.MULTILINE)
    _require(match is not None, "pdfinfo did not report a page count")
    return int(match.group(1))


def audit_build_receipt(receipt: dict[str, Any], manifest: dict[str, Any], *, root: Path = ROOT) -> None:
    """Verify a local XeLaTeX build against its preceding, committed source tree."""
    _require(receipt.get("receipt_id") == BUILD_RECEIPT_ID, "unsupported build receipt")
    source_commit = receipt.get("source_commit")
    source_tree = receipt.get("source_tree")
    _require(isinstance(source_commit, str) and COMMIT_RE.fullmatch(source_commit) is not None,
             "build receipt source_commit is invalid")
    _require(isinstance(source_tree, str) and COMMIT_RE.fullmatch(source_tree) is not None,
             "build receipt source_tree is invalid")
    _require(_git_text(root, "rev-parse", f"{source_commit}^{{tree}}") == source_tree,
             "build receipt source_tree does not match source_commit")
    _require(_git_text(root, "rev-parse", "HEAD^") == source_commit,
             "build receipt must be audited from the direct receipt commit above its source commit")
    absent = _git(root, "cat-file", "-e",
                  f"{source_commit}:paper/NEGATIVE_RESULT_BOUNDARY_BUILD_RECEIPT.json")
    _require(absent.returncode != 0, "build receipt is incorrectly present in its source commit")

    expected_hashes = _snapshot_input_hashes(manifest, root)
    _require(receipt.get("input_sha256") == expected_hashes,
             "build receipt input hashes do not match the frozen source snapshot")
    _require(receipt.get("evidence_manifest_sha256") ==
             expected_hashes["paper/NEGATIVE_RESULT_BOUNDARY_EVIDENCE_MANIFEST.json"],
             "build receipt evidence-manifest hash is wrong")
    for relative_path, expected_hash in expected_hashes.items():
        frozen_bytes = _git_bytes(root, "show", f"{source_commit}:{relative_path}")
        observed_hash = hashlib.sha256(frozen_bytes).hexdigest()
        _require(observed_hash == expected_hash,
                 f"source commit does not contain the frozen bytes for {relative_path}")

    _require(receipt.get("build_commands") == list(REQUIRED_BUILD_COMMANDS),
             "build receipt command sequence is not the frozen XeLaTeX sequence")
    outputs = receipt.get("outputs")
    _require(isinstance(outputs, dict) and set(outputs) == set(EXPECTED_BUILD_OUTPUTS),
             "build receipt output set is incomplete")
    for identifier, relative_path in EXPECTED_BUILD_OUTPUTS.items():
        _receipt_output(root, Path(relative_path), outputs[identifier], identifier)
    log_text = (root / EXPECTED_BUILD_OUTPUTS["log"]).read_text(encoding="utf-8", errors="replace")
    _require(all(marker not in log_text for marker in LOG_FAILURE_MARKERS),
             "build log contains an undefined-reference or fatal-error marker")
    _require(receipt.get("log_checks") == {
        "no_undefined_references": True,
        "no_undefined_citations": True,
        "no_fatal_errors": True,
    }, "build receipt log_checks is incomplete")
    _require(receipt.get("pdf_page_count") == _pdf_page_count(root / EXPECTED_BUILD_OUTPUTS["pdf"]),
             "build receipt PDF page count drifted")
    runtime = receipt.get("tex_runtime")
    _require(isinstance(runtime, dict) and set(runtime) == {"xelatex", "bibtex", "ieeetr_bst"},
             "build receipt TeX runtime record is incomplete")
    for identifier, entry in runtime.items():
        _require(isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"],
                 f"build receipt {identifier} path is missing")
        _require(isinstance(entry.get("version"), str) and entry["version"],
                 f"build receipt {identifier} version is missing")
        _require(isinstance(entry.get("sha256"), str) and SHA256_RE.fullmatch(entry["sha256"]) is not None,
                 f"build receipt {identifier} hash is invalid")


def _require_clean_worktree(root: Path) -> None:
    status = _git(root, "status", "--porcelain")
    _require(status.returncode == 0, f"git status failed: {status.stderr.strip()}")
    _require(not status.stdout.strip(), "worktree is dirty; commit the audited snapshot before release verification")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path,
                        help="verify a post-commit local XeLaTeX build receipt")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="skip the clean-worktree requirement for a pre-commit source audit")
    args = parser.parse_args()
    try:
        manifest = _load_json(DEFAULT_MANIFEST)
        audit_negative_result_boundary(manifest)
        if args.build_receipt is not None:
            receipt = _load_json(args.build_receipt)
            audit_build_receipt(receipt, manifest)
        if not args.allow_dirty:
            _require_clean_worktree(ROOT)
    except BoundaryAuditError as error:
        print(f"NEGATIVE-RESULT-BOUNDARY AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    if args.build_receipt is None:
        print("NEGATIVE-RESULT-BOUNDARY SOURCE AUDIT PASSED: E7/E8 are the only paper-eligible empirical results; mechanism-v2.6 is exclusion-only.")
    else:
        print("NEGATIVE-RESULT-BOUNDARY RELEASE AUDIT PASSED: frozen source, XeLaTeX build receipt, E7/E8 evidence, and v2.6 exclusion boundary agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
