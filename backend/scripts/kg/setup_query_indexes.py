"""Create the full-text index used for entity lookup (names + aliases, accent-folding). Idempotent.

    python -m scripts.kg.setup_query_indexes
"""
import re

from neo4j import GraphDatabase

from app.modules.kg_import.config import Settings
from app.modules.kg_query.cypher import FULLTEXT_INDEX_DDL
from scripts.kg._common import utf8_stdout

NAME = "entity_names"
assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", NAME)  # DDL cannot take parameters


def main() -> int:
    utf8_stdout()
    st = Settings.from_env()
    driver = GraphDatabase.driver(st.neo4j_uri, auth=(st.neo4j_username, st.neo4j_password))
    try:
        with driver.session(database=st.neo4j_database) as s:
            s.run(FULLTEXT_INDEX_DDL.format(name=NAME)).consume()
        print(f"[neo4j] ensured full-text index: {NAME}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
