import os
import tempfile
from pathlib import Path

_TEST_DATA = tempfile.TemporaryDirectory(prefix='medical-integrated-tests-')
os.environ['CONTEXT_GRAPH_BACKEND'] = 'memory'
os.environ['CONTEXT_NLP_BACKEND'] = 'rule'
os.environ['CONTEXT_EMBEDDING_BACKEND'] = 'hash'
os.environ['CONTEXT_TERMINOLOGY_MODE'] = 'off'
os.environ['RAG_MODE'] = 'demo'
os.environ['RAG_DEMO_DB'] = str(Path(_TEST_DATA.name) / 'rag.sqlite3')
os.environ['DATABASE_PATH'] = str(Path(_TEST_DATA.name) / 'assistant.sqlite3')
os.environ['UPLOAD_DIR'] = str(Path(_TEST_DATA.name) / 'uploads')

os.environ['BATCH_DATA_ROOT'] = str(Path(_TEST_DATA.name) / 'batch-data')
