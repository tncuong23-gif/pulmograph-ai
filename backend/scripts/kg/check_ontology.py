"""Check an ontology JSON for references to undeclared entity types.

    python -m scripts.kg.check_ontology examples/kg/kg_ontology.example.json
    python -m scripts.kg.check_ontology examples/kg/kg_ontology.example.json --fix

Without --fix the file is never modified. With --fix, the missing names are appended to
"entity_types" and a backup <file>.bak is written first.
"""
import argparse
import json
import re
import shutil
import sys

from scripts.kg._common import utf8_stdout

ENTITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
REL_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--fix", action="store_true", help="append missing entity types (writes a .bak backup)")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    types = data.get("entity_types", [])
    declared = set(types)
    problems = 0

    dupes = sorted({t for t in types if types.count(t) > 1})
    if dupes:
        print(f"[warn] duplicate entity_types: {dupes}")
    for t in types:
        if not ENTITY_RE.match(t):
            print(f"[error] invalid entity type name: {t!r}")
            problems += 1

    missing: dict[str, list[str]] = {}
    for rel, spec in data.get("relation_types", {}).items():
        if not REL_RE.match(rel):
            print(f"[error] invalid relation type name: {rel!r}")
            problems += 1
        spec = spec or {}
        for side in ("domain", "range"):
            for t in spec.get(side, []):
                if t not in declared:
                    missing.setdefault(t, []).append(f"{rel}.{side}")

    for name, where in sorted(missing.items()):
        print(f"[missing] {name}  <- {', '.join(where)}")
    print(f"\n{len(types)} entity types, {len(data.get('relation_types', {}))} relation types, "
          f"{len(missing)} undeclared type(s), {problems} naming error(s)")

    if missing and args.fix:
        shutil.copyfile(args.file, args.file + ".bak")
        data["entity_types"] = types + sorted(missing)
        with open(args.file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"added {sorted(missing)} to entity_types; backup: {args.file}.bak")
        return 0 if not problems else 1
    return 1 if (missing or problems) else 0


if __name__ == "__main__":
    sys.exit(main())