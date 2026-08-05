"""Write a metadata-only schema inventory and gate receipt for one HDF5 file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.mechanism_hdf5_schema import Hdf5SchemaError, inspect_hdf5_metadata, schema_gate_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True, help="Frozen JSON semantic mapping, not waveform content.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict):
            raise Hdf5SchemaError("mapping must be a JSON object")
        inventory = inspect_hdf5_metadata(args.h5)
        gate = schema_gate_result(inventory, mapping)
    except (OSError, json.JSONDecodeError, Hdf5SchemaError) as error:
        print(f"HDF5 SCHEMA AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    output = {"inventory": inventory, "schema_gate": gate}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"saved {args.output} ({gate['status']})")
    return 0 if gate["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
