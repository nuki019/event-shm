"""Mechanism-v2.3 entry point for COQTEL metadata-only hierarchy gating."""

from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import audit_mechanism_hdf5_schema_v2_2 as _impl
from src.experiments import mechanism_v2_3_successor as _successor


_impl.SUCCESSOR_PROTOCOL_ID = _successor.SUCCESSOR_PROTOCOL_ID
_impl.DEFAULT_PROTOCOL = _successor.ROOT / "protocols" / "mechanism_v2_3.json"
_impl.DEFAULT_MANIFEST = _successor.ROOT / "protocols" / "mechanism_v2_3_data_manifest.json"
_impl.DEFAULT_FREEZE_RECEIPT = _successor.ROOT / "protocols" / "mechanism_v2_3_freeze_receipt.json"
_impl.load_successor_manifest = _successor.load_successor_manifest
_impl.load_successor_protocol = _successor.load_successor_protocol
_impl.manifest_entry = _successor.manifest_entry
_impl.external_mapping = _successor.external_mapping
_impl.verify_successor_freeze = _successor.verify_successor_freeze
_impl.sha256_file = _successor.sha256_file


if __name__ == "__main__":
    raise SystemExit(_impl.main())
