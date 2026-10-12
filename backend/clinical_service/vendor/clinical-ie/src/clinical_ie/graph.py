import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .inference import RELATION_SIGNATURES
from .rules import CASE_RELATIONS

ENTITY_TYPES = {"SYMPTOM", "SIGN", "CONDITION", "TEST", "RESULT", "ANATOMY", "TREATMENT", "TIME"}
QUALIFIERS = ("assertion", "temporality", "severity", "course", "laterality")


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    doc_id: str
    node_count: int
    edge_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "doc_id": self.doc_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "errors": self.errors,
            "warnings": self.warnings,
            "schema_version": self.schema_version,
        }


def uid(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def read_predictions(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    values = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(text)
    if isinstance(values, dict):
        values = [values]
    records = []
    for value in values:
        if "segments" in value:
            for segment in value["segments"]:
                records.append({"doc_id": value["doc_id"], **segment})
        else:
            records.append(value)
    return records


def cypher_literal(value):
    """Encode literals, never interpolate user text as Cypher identifiers."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Non-finite graph property")
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(map(cypher_literal, value)) + "]"
    if isinstance(value, dict):
        return "{" + ",".join("`" + k.replace("`", "``") + "`:" + cypher_literal(v) for k, v in value.items()) + "}"
    raise ValueError(f"Unsupported property type: {type(value)}")


def build_graphs(records: list[dict], namespace: str) -> list[dict]:
    if not namespace.strip():
        raise ValueError("namespace must not be empty")
    graphs, seen = {}, {}
    for record in records:
        doc = record["doc_id"]
        if not isinstance(doc, str) or not doc:
            raise ValueError("Missing doc_id")
        scope = record.get("segment_id") or "document"
        key = (doc, scope)
        fingerprint = json.dumps(record, sort_keys=True, ensure_ascii=False)
        if key in seen:
            if seen[key] != fingerprint:
                raise ValueError(f"Conflicting prediction records: {key}")
            continue
        seen[key] = fingerprint
        case_id = uid(namespace, doc, "case")
        if doc not in graphs:
            graphs[doc] = {"doc_id": doc, "namespace": namespace, "source_record_count": 0,
                           "nodes": [{"uid": case_id, "kind": "Case", "properties": {"doc_id": doc, "namespace": namespace}}], "edges": []}
        graph = graphs[doc]
        graph["source_record_count"] += 1
        entities = {}
        for entity in record["entities"]:
            local_id, label = entity["id"], entity["label"]
            if local_id in entities or label not in ENTITY_TYPES:
                raise ValueError(f"Duplicate entity ID or unknown type: {doc}/{local_id}/{label}")
            entity_id = uid(namespace, doc, scope, local_id)
            props = {"doc_id": doc, "namespace": namespace, "text": entity["text"], "entity_type": label}
            for name in ("canonical", "source"):
                if entity.get(name) is not None:
                    props[name] = entity[name]
            if entity.get("score") is not None:
                props["confidence"] = entity["score"]
            for name in ("assertion", "temporality", "severity", "course", "laterality"):
                if entity.get("qualifiers", {}).get(name) is not None:
                    props[name] = entity["qualifiers"][name]
            if any(not isinstance(v, (str, int, float, bool)) for v in props.values()):
                raise ValueError("Entity properties must be scalar")
            cypher_literal(props)
            entities[local_id] = (entity_id, label, props)
            graph["nodes"].append({"uid": entity_id, "kind": "Entity", "properties": props})

        edges = {}

        def add_edge(subject, predicate, obj, properties):
            edge_id = uid(namespace, subject, predicate, obj)
            cypher_literal(properties)
            edge = {"uid": edge_id, "source": subject, "target": obj, "predicate": predicate, "properties": properties}
            if edge_id in edges and edges[edge_id] != edge:
                raise ValueError(f"Conflicting duplicate relation: {predicate}")
            edges[edge_id] = edge

        for triple in record.get("triples", []):
            predicate = triple["predicate"].upper()
            s_id = triple.get("subject_id") or triple.get("subject")
            o_id = triple.get("object_id") or triple.get("object")
            if triple.get("subject_label") == "CASE" or s_id == doc or predicate in CASE_RELATIONS.values() or predicate == "HAS_HISTORY":
                # Validate upstream structural triples, then regenerate consistently below.
                if o_id not in entities:
                    raise ValueError(f"Dangling Case relation in {doc}: {predicate}")
                continue
            if s_id not in entities or o_id not in entities:
                raise ValueError(f"Dangling relation in {doc}: {predicate}")
            subject, slabel, _ = entities[s_id]
            obj, olabel, _ = entities[o_id]
            signature = RELATION_SIGNATURES.get(predicate)
            if not signature or slabel not in signature[0] or olabel not in signature[1]:
                raise ValueError(f"Invalid relation signature: {slabel}-{predicate}-{olabel}")
            props = {"doc_id": doc, "namespace": namespace, "source": str(triple.get("source", "unspecified"))}
            if triple.get("confidence") is not None:
                props["confidence"] = float(triple["confidence"])
            add_edge(subject, predicate, obj, props)
        for entity_id, label, props in entities.values():
            predicate = "HAS_HISTORY" if label == "CONDITION" and props.get("temporality") == "HISTORY" else CASE_RELATIONS.get(label)
            if predicate:
                edge_props = {"doc_id": doc, "namespace": namespace, "source": "derived_from_entity_type", "rule_confidence": 1.0}
                for name in ("assertion", "temporality"):
                    if name in props:
                        edge_props[name] = props[name]
                add_edge(case_id, predicate, entity_id, edge_props)
        graph["edges"].extend(edges.values())
    for graph in graphs.values():
        graph["nodes"].sort(key=lambda n: n["uid"])
        graph["edges"].sort(key=lambda e: e["uid"])
    return [graphs[key] for key in sorted(graphs)]


SCHEMA = """CREATE CONSTRAINT clinical_node_uid IF NOT EXISTS
FOR (n:ClinicalNode) REQUIRE n.uid IS UNIQUE;
CREATE INDEX clinical_node_case IF NOT EXISTS
FOR (n:ClinicalNode) ON (n.namespace, n.doc_id);
"""


def export_graphs(input_path: Path, output_dir: Path, namespace: str) -> dict:
    from .cli import _atomic_write_json, _atomic_write_jsonl

    records = read_predictions(input_path)
    graphs = build_graphs(records, namespace)
    nodes = [n for g in graphs for n in g["nodes"]]
    edges = [e for g in graphs for e in g["edges"]]
    statements = [SCHEMA]
    for kind in ("Case", "Entity"):
        rows = [n for n in nodes if n["kind"] == kind]
        for start in range(0, len(rows), 250):
            statements.append(f"UNWIND {cypher_literal(rows[start:start+250])} AS row\nMERGE (n:ClinicalNode:{kind} {{uid: row.uid}})\nSET n = row.properties, n.uid = row.uid;\n")
    for predicate in sorted({e["predicate"] for e in edges}):
        rows = [e for e in edges if e["predicate"] == predicate]
        for start in range(0, len(rows), 250):
            statements.append(f"UNWIND {cypher_literal(rows[start:start+250])} AS row\nMATCH (s:ClinicalNode {{uid: row.source}}), (t:ClinicalNode {{uid: row.target}})\nMERGE (s)-[r:{predicate} {{uid: row.uid}}]->(t)\nSET r = row.properties, r.uid = row.uid;\n")
    manifest = {"schema_version": "1.0", "namespace": namespace,
                "input": str(input_path.resolve()), "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                "input_records": len(records), "cases": len(graphs), "nodes": len(nodes), "edges": len(edges),
                "entity_types": dict(Counter(n["properties"]["entity_type"] for n in nodes if n["kind"] == "Entity")),
                "relations": dict(Counter(e["predicate"] for e in edges)),
                "coverage": "Only supplied predictions; not necessarily complete medical records.",
                "validation": "Offline structural validation only; no live Neo4j execution."}
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_jsonl(output_dir / "clinical_graphs.jsonl", graphs)
    _atomic_write_json(output_dir / "manifest.json", manifest)
    # Generated artifacts, not source edits.
    (output_dir / "schema.cypher").write_text(SCHEMA, encoding="utf-8")
    (output_dir / "import.cypher").write_text("\n".join(statements), encoding="utf-8")
    (output_dir / "queries.cypher").write_text(
        "// Replace parameters with the desired namespace and doc_id.\n"
        "// OPTIONAL MATCH retains isolated entities; no section/segment nodes.\n"
        "MATCH (n:ClinicalNode {namespace: $namespace, doc_id: $doc_id})\n"
        "OPTIONAL MATCH (n)-[r]->(m:ClinicalNode {namespace: $namespace, doc_id: $doc_id})\n"
        "RETURN n, r, m;\n", encoding="utf-8")
    return manifest


def validate_case_graph(graph: dict[str, Any]) -> ValidationReport:
    """Validate structural constraints, case isolation, and absence of target leakage."""
    doc_id = str(graph.get("doc_id", ""))
    errors: list[str] = []
    warnings: list[str] = []

    if not doc_id:
        errors.append("Missing doc_id in graph root")

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    node_uids = [n.get("uid") for n in nodes if isinstance(n, dict)]
    edge_uids = [e.get("uid") for e in edges if isinstance(e, dict)]

    if len(node_uids) != len(set(node_uids)):
        errors.append("Duplicate node UID detected")
    if len(edge_uids) != len(set(edge_uids)):
        errors.append("Duplicate edge UID detected")

    case_nodes = [n for n in nodes if isinstance(n, dict) and n.get("kind") == "Case"]
    if len(case_nodes) != 1:
        errors.append(f"Expected exactly 1 Case node, found {len(case_nodes)}")

    known_uids = set(node_uids)
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("Edge is not a dictionary")
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        pred = str(edge.get("predicate", ""))
        if src not in known_uids:
            errors.append(f"Dangling edge source UID: {src}")
        if tgt not in known_uids:
            errors.append(f"Dangling edge target UID: {tgt}")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", pred):
            errors.append(f"Invalid edge predicate format: {pred}")

    forbidden_keys = {"disease_label", "class_id", "target_disease", "target_class", "split"}
    for item in nodes + edges:
        if isinstance(item, dict):
            props = item.get("properties", {})
            if isinstance(props, dict):
                item_doc = props.get("doc_id")
                if item_doc is not None and str(item_doc) != doc_id:
                    errors.append(f"Cross-patient component found: {item_doc} != {doc_id}")
                leakage = forbidden_keys.intersection(props.keys())
                if leakage:
                    errors.append(f"Forbidden target label/split property detected: {leakage}")

    is_valid = len(errors) == 0
    return ValidationReport(
        is_valid=is_valid,
        doc_id=doc_id,
        node_count=len(nodes),
        edge_count=len(edges),
        errors=errors,
        warnings=warnings,
        schema_version="1.0",
    )


def _entity_key(node: dict[str, Any]) -> tuple[Any, ...]:
    if node.get("kind") == "Case":
        return ("CASE", "CASE", *("UNKNOWN" for _ in QUALIFIERS))
    p = node.get("properties", {})
    raw_text = str(p.get("text", ""))
    norm_text = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw_text)).strip().casefold()
    if not norm_text:
        norm_text = "unknown"
    etype = str(p.get("entity_type", "UNKNOWN")).upper()
    qualifiers = tuple(str(p.get(k) or "UNKNOWN") for k in QUALIFIERS)
    return (etype, norm_text, *qualifiers)


def _merge_properties(items: list[dict[str, Any]], namespace: str) -> dict[str, Any]:
    props = [x.get("properties", {}) for x in items if isinstance(x.get("properties"), dict)]
    result: dict[str, Any] = {}
    if not props:
        return {"namespace": namespace}

    all_keys = sorted(set().union(*(p.keys() for p in props)))
    for key in all_keys:
        present = [p[key] for p in props if key in p]
        if key == "namespace":
            result[key] = namespace
        elif key in ("confidence", "rule_confidence", "score"):
            result[key] = max(present)
        elif all(key in p and p[key] == present[0] for p in props):
            result[key] = deepcopy(present[0])
        elif key == "source":
            result[key] = "multiple"
            result["sources"] = sorted(set(str(v) for v in present))

    return result


def deduplicate_case_graph(graph: dict[str, Any], *, namespace: str | None = None) -> dict[str, Any]:
    """Deduplicate entities and parallel edges within a SINGLE patient case.

    Guarantees:
    - Merges identical entity concepts within the case.
    - Rewires edges to merged node UIDs.
    - Merges parallel edges between the same endpoints, retaining highest confidence.
    - Preserves case isolation: strictly no cross-patient merging.
    """
    initial_validation = validate_case_graph(graph)
    if not initial_validation.is_valid:
        raise ValueError(f"Cannot deduplicate invalid case graph: {initial_validation.errors}")

    doc_id = graph["doc_id"]
    source_ns = graph.get("namespace", "source")
    target_ns = namespace if namespace else f"{source_ns}_dedup"

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for node in graph.get("nodes", []):
        groups[_entity_key(node)].append(node)

    old_to_new: dict[str, str] = {}
    new_nodes: list[dict[str, Any]] = []

    for key, members in sorted(groups.items()):
        kind = members[0]["kind"]
        new_id = uid(target_ns, doc_id, kind, json.dumps(key, ensure_ascii=False))
        props = _merge_properties(members, target_ns)
        props["doc_id"] = doc_id
        if kind == "Entity":
            props["entity_type"] = key[0]
            props["text"] = key[1]
            for idx, q_name in enumerate(QUALIFIERS):
                props[q_name] = key[2 + idx]
        new_nodes.append({"uid": new_id, "kind": kind, "properties": props})
        for m in members:
            old_to_new[m["uid"]] = new_id

    edge_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        s_new = old_to_new.get(edge["source"])
        t_new = old_to_new.get(edge["target"])
        pred = str(edge.get("predicate", "UNKNOWN")).upper()
        if s_new and t_new:
            edge_groups[(s_new, pred, t_new)].append(edge)

    new_edges: list[dict[str, Any]] = []
    for (subject, predicate, obj), members in sorted(edge_groups.items()):
        new_edge_id = uid(target_ns, subject, predicate, obj)
        props = _merge_properties(members, target_ns)
        props["doc_id"] = doc_id
        new_edges.append({
            "uid": new_edge_id,
            "source": subject,
            "target": obj,
            "predicate": predicate,
            "properties": props,
        })

    result: dict[str, Any] = {
        **deepcopy(graph),
        "namespace": target_ns,
        "doc_id": doc_id,
        "nodes": sorted(new_nodes, key=lambda n: n["uid"]),
        "edges": sorted(new_edges, key=lambda e: e["uid"]),
    }

    final_validation = validate_case_graph(result)
    if not final_validation.is_valid:
        raise ValueError(f"Deduplicated graph failed validation: {final_validation.errors}")

    return result


def build_case_graph(extraction: dict[str, Any] | Any, *, namespace: str = "case") -> dict[str, Any]:
    """Construct an isolated single-case Neo4j property graph from an extraction result."""
    if hasattr(extraction, "to_dict"):
        record = extraction.to_dict()
    elif isinstance(extraction, dict):
        record = extraction
    else:
        record = dict(extraction)

    graphs = build_graphs([record], namespace)
    if not graphs:
        raise ValueError("Failed to build case graph from extraction record")
    return graphs[0]


def export_graph_jsonl(graphs: list[dict[str, Any]], path: Path | str) -> int:
    """Safely export graphs to JSONL format."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with dest.open("w", encoding="utf-8") as handle:
        for g in graphs:
            handle.write(json.dumps(g, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def export_neo4j_cypher(graphs: list[dict[str, Any]], output_dir: Path | str) -> dict[str, Any]:
    """Export offline Neo4j Cypher scripts (schema, import, queries) for in-memory graphs."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    nodes = [n for g in graphs for n in g.get("nodes", [])]
    edges = [e for g in graphs for e in g.get("edges", [])]
    statements = [SCHEMA]

    for kind in ("Case", "Entity"):
        rows = [n for n in nodes if n.get("kind") == kind]
        for start in range(0, len(rows), 250):
            batch = rows[start:start + 250]
            statements.append(
                f"UNWIND {cypher_literal(batch)} AS row\n"
                f"MERGE (n:ClinicalNode:{kind} {{uid: row.uid}})\n"
                f"SET n = row.properties, n.uid = row.uid;\n"
            )

    for predicate in sorted({e.get("predicate") for e in edges if e.get("predicate")}):
        rows = [e for e in edges if e.get("predicate") == predicate]
        for start in range(0, len(rows), 250):
            batch = rows[start:start + 250]
            statements.append(
                f"UNWIND {cypher_literal(batch)} AS row\n"
                f"MATCH (s:ClinicalNode {{uid: row.source}}), (t:ClinicalNode {{uid: row.target}})\n"
                f"MERGE (s)-[r:{predicate} {{uid: row.uid}}]->(t)\n"
                f"SET r = row.properties, r.uid = row.uid;\n"
            )

    (out / "schema.cypher").write_text(SCHEMA, encoding="utf-8")
    (out / "import.cypher").write_text("\n".join(statements), encoding="utf-8")
    (out / "queries.cypher").write_text(
        "// Offline template queries\n"
        "MATCH (n:ClinicalNode {namespace: $namespace, doc_id: $doc_id})\n"
        "OPTIONAL MATCH (n)-[r]->(m:ClinicalNode {namespace: $namespace, doc_id: $doc_id})\n"
        "RETURN n, r, m;\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "1.0",
        "cases": len(graphs),
        "nodes": len(nodes),
        "edges": len(edges),
        "entity_types": dict(Counter(n.get("properties", {}).get("entity_type") for n in nodes if n.get("kind") == "Entity")),
        "relations": dict(Counter(e.get("predicate") for e in edges)),
    }
    with (out / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    return manifest


def build_graphs_cli(args) -> int:
    print(json.dumps(export_graphs(Path(args.input), Path(args.output_dir), args.namespace), ensure_ascii=False, indent=2))
    return 0
