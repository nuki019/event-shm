"""Record MORPHO's official document semantics without opening its HDF5 file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_4_metadata_discovery import DiscoveryError, ROOT, resolve_within_root, sha256_file
from src.experiments.mechanism_v2_4_morpho_semantic_discovery import verify_semantic_freeze, validate_semantic_provenance


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4_morpho_semantic_discovery.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_morpho_semantic_discovery_freeze_receipt.json"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_4_morpho_semantic_discovery.json"
KEYWORDS = ("fatigue", "healthy", "failed", "failure", "impact", "cycle", "repeat", "block", "active", "fod7")


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _keyword_lines(value: str) -> dict[str, list[str]]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return {
        keyword: [line for line in lines if keyword in line.casefold()][:25]
        for keyword in KEYWORDS
    }


def _structure_summary(structural_result: dict) -> dict[str, object]:
    inventory = structural_result.get("inventory", {})
    objects = inventory.get("objects", []) if isinstance(inventory, dict) else []
    paths = [item.get("path") for item in objects if isinstance(item, dict) and isinstance(item.get("path"), str)]
    top_level = sorted({path.split("/")[1] for path in paths if path.count("/") >= 1 and path != "/"})
    active_blocks = sorted({path.split("/")[2] for path in paths if path.startswith("/5_Active/") and len(path.split("/")) > 2})
    return {"top_level_groups": top_level, "active_path_tokens": active_blocks, "schema_fingerprint_sha256": inventory.get("schema_fingerprint_sha256") if isinstance(inventory, dict) else None}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.output = resolve_within_root(args.output, "semantic-discovery output", must_exist=False)
        if args.output.exists():
            raise DiscoveryError(f"refusing to overwrite semantic-discovery output: {args.output}")
        protocol = verify_semantic_freeze(args.protocol, args.freeze_receipt)
        protocol_path = resolve_within_root(args.protocol, "semantic-discovery protocol")
        freeze_path = resolve_within_root(args.freeze_receipt, "semantic-discovery freeze receipt")
        structural_path, structural_result, paths = validate_semantic_provenance(protocol)
        for key, path in paths.items():
            if sha256_file(path) != protocol["input_documents"][key]["sha256"]:
                raise DiscoveryError(f"{key} SHA-256 differs from the frozen semantic-discovery contract")
        readme = PdfReader(str(paths["readme_pdf"]))
        readme_text = "\n".join(page.extract_text() or "" for page in readme.pages)
        reader_example_text = paths["reader_example"].read_text(encoding="utf-8")
        result = {
            "discovery_id": "mechanism-v2.4-morpho-document-semantic-discovery-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256_file(protocol_path),
            "freeze_receipt_sha256": sha256_file(freeze_path),
            "structural_discovery_result": str(structural_path.relative_to(ROOT)),
            "structural_discovery_result_sha256": sha256_file(structural_path),
            "documents": {
                key: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
                for key, path in paths.items()
            },
            "readme_page_count": len(readme.pages),
            "readme_text_sha256": _text_hash(readme_text),
            "readme_text": readme_text,
            "reader_example_text_sha256": _text_hash(reader_example_text),
            "reader_example_text": reader_example_text,
            "keyword_lines": {"readme": _keyword_lines(readme_text), "reader_example": _keyword_lines(reader_example_text)},
            "structural_path_summary": _structure_summary(structural_result),
            "access_receipt": {
                "hdf5_opened": False,
                "waveform_values_read": False,
                "metadata_values_read": False,
                "labels_read_for_scoring": False,
                "signal_metrics_computed": False,
                "mapping_selected": False,
                "schema_eligibility_decided": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (DiscoveryError, OSError, ValueError) as error:
        print(f"MORPHO SEMANTIC DISCOVERY FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
