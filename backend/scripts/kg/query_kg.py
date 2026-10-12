"""Query the KG from the command line (Windows CMD friendly).

    python -m scripts.kg.query_kg intents                      # list intents + coverage (no database needed)
    python -m scripts.kg.query_kg find "COPD"
    python -m scripts.kg.query_kg ask "COPD" -i symptom
    python -m scripts.kg.query_kg ask "COPD" -i treatment -t Medication -t DrugClass
    python -m scripts.kg.query_kg chain "COPD" drug_adverse_effects
    python -m scripts.kg.query_kg path "COPD" "suy tim"
    python -m scripts.kg.query_kg spec "{\"mentions\": [\"COPD\"], \"intents\": [\"risk_factor\"]}"
Add --no-evidence to skip the MongoDB lookup.
"""
import argparse
import json
import logging
import sys

from app.modules.kg_import.config import Settings
from app.modules.kg_import.ontology import Ontology
from app.modules.kg_query.factory import build_query_resources
from app.modules.kg_query.intents import PRESET_CHAINS, build_intents, describe_intents, uncovered_relations
from app.modules.kg_query.models import QuerySpec
from scripts.kg._common import dump, utf8_stdout


def _print_intents(ontology: Ontology) -> None:
    intents = build_intents(ontology)
    for name, desc in describe_intents():
        print(f"{name:16s} {len(intents[name].relations):4d} rel  {desc}")
    print("\nchain presets:", ", ".join(PRESET_CHAINS))
    rest = uncovered_relations(ontology)
    print(f"\n{len(rest)} relation(s) only reachable through 'related':\n  " + ", ".join(rest))


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-evidence", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("intents")
    p = sub.add_parser("find"); p.add_argument("mention"); p.add_argument("-t", "--type", action="append")
    p = sub.add_parser("ask"); p.add_argument("mention"); p.add_argument("-i", "--intent", action="append", required=True)
    p.add_argument("-t", "--target-type", action="append"); p.add_argument("--anchor-type", action="append")
    p = sub.add_parser("chain"); p.add_argument("mention"); p.add_argument("preset", choices=sorted(PRESET_CHAINS))
    p = sub.add_parser("path"); p.add_argument("a"); p.add_argument("b"); p.add_argument("--max-hops", type=int, default=3)
    p = sub.add_parser("spec"); p.add_argument("json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    st = Settings.from_env()
    if args.cmd == "intents":
        _print_intents(Ontology.load(st.ontology_path))
        return 0

    res = build_query_resources(st, with_evidence=not args.no_evidence)
    try:
        svc = res.service
        if args.cmd == "find":
            dump([{**vars(a.entity), "matched_by": a.matched_by, "score": a.score}
                  for a in svc.resolve(args.mention, args.type)])
            return 0
        if args.cmd == "ask":
            spec = QuerySpec([args.mention], intents=args.intent, target_types=args.target_type,
                             anchor_types=args.anchor_type)
        elif args.cmd == "chain":
            spec = QuerySpec([args.mention], chain=list(PRESET_CHAINS[args.preset]))
        elif args.cmd == "path":
            spec = QuerySpec([args.a, args.b], path=True, max_hops=args.max_hops)
        else:
            try:
                spec = QuerySpec.from_dict(json.loads(args.json), PRESET_CHAINS)
            except (ValueError, KeyError, TypeError) as exc:
                print(f"invalid spec: {exc}", file=sys.stderr)
                return 2
        dump(svc.run(spec, with_evidence=not args.no_evidence).to_dict())
    finally:
        res.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
