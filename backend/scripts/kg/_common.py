import json
import sys


def utf8_stdout() -> None:
    """Windows consoles default to cp1252/cp1258; force UTF-8 so Vietnamese text prints."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def load_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
