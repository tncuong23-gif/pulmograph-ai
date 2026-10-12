"""Validate a KG import file without touching any database.

    python -m scripts.kg.validate_kg examples/kg/kg_import.json
"""
import argparse
import sys

from app.modules.kg_import.config import Settings
from app.modules.kg_import.ontology import Ontology
from app.modules.kg_import.service import KGImportService
from scripts.kg._common import dump, load_json, utf8_stdout


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--ontology", default=None)
    args = ap.parse_args()
    st = Settings.from_env()
    try:
        payload = load_json(args.file)
    except (OSError, ValueError) as exc:
        print(f"cannot read JSON: {exc}", file=sys.stderr)
        return 2
    svc = KGImportService(Ontology.load(args.ontology or st.ontology_path), None, None, None, st.limits)  # type: ignore[arg-type]
    issues = svc.validate_payload(payload)
    dump({"valid": not issues, "errors": [i.to_dict() for i in issues]})
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
