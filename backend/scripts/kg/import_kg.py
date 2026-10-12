"""Import a KG JSON file.

    python -m scripts.kg.import_kg examples/kg/kg_import.json --mode upsert
    python -m scripts.kg.import_kg examples/kg/kg_import.json --mode upsert --dry-run
    python -m scripts.kg.import_kg examples/kg/kg_import.json --retry IMP_XXXXXXXXXXXX
"""
import argparse
import logging
import sys

from app.modules.kg_import.config import Settings
from app.modules.kg_import.factory import build_resources
from scripts.kg._common import dump, load_json, utf8_stdout


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--mode", choices=["insert", "upsert", "replace"], default="upsert")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry", metavar="IMPORT_ID")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        payload = load_json(args.file)
    except (OSError, ValueError) as exc:
        print(f"cannot read JSON: {exc}", file=sys.stderr)
        return 2
    res = build_resources(Settings.from_env())
    try:
        result = (res.service.retry(args.retry, payload) if args.retry
                  else res.service.import_kg(payload, args.mode, dry_run=args.dry_run))
    finally:
        res.close()
    dump(result.to_dict())
    return 0 if result.http_status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
