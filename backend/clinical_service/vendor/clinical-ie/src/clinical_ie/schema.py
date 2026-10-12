from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ClinicalSchema:
    raw: dict[str, Any]

    @property
    def entity_types(self) -> set[str]:
        return set(self.raw["entity_types"])

    @property
    def relation_types(self) -> set[str]:
        return set(self.raw["relation_types"])

    def attribute_values(self, attribute: str) -> set[str]:
        config = self.raw.get("attributes", {}).get(attribute, {})
        return set(config.get("values", []))

    def default_attribute(self, attribute: str) -> str | None:
        return self.raw.get("attributes", {}).get(attribute, {}).get("default")

    def allowed_subjects(self, relation: str) -> set[str]:
        return set(self.raw["relation_types"][relation]["subject"])

    def allowed_objects(self, relation: str) -> set[str]:
        return set(self.raw["relation_types"][relation]["object"])


def get_default_schema_path() -> Path:
    pkg_resource = Path(__file__).resolve().parent / "resources" / "schema.yaml"
    if pkg_resource.is_file():
        return pkg_resource
    repo_config = Path(__file__).resolve().parents[2] / "configs" / "schema.yaml"
    if repo_config.is_file():
        return repo_config
    return pkg_resource


def load_schema(path: str | Path | None = None) -> ClinicalSchema:
    schema_path = Path(path) if path is not None else get_default_schema_path()
    with schema_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Schema must be a mapping: {schema_path}")
    for required in ("entity_types", "attributes", "relation_types"):
        if required not in raw:
            raise ValueError(f"Schema is missing '{required}': {schema_path}")
    return ClinicalSchema(raw=raw)

