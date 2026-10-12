"""Durable document receipts, bound to content and model; never import authorization."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from threading import RLock
from .config import BACKEND_ROOT
from .utils import sha256_of, utcnow_iso


class DocumentReviewStore:
    def __init__(self, directory=None):
        root = Path(directory) if directory is not None else Path(os.getenv('BATCH_DATA_ROOT', str(BACKEND_ROOT / 'data'))) / 'import_reports' / 'kg'
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / 'document_reviews.sqlite3', timeout=10, check_same_thread=False)
        self.lock = RLock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS document_reviews (
            document_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, profile TEXT NOT NULL,
            reviewed_at TEXT NOT NULL, decision_count INTEGER NOT NULL)''')
        self.db.commit()

    def status(self, payload, profile, *, needs_review=False):
        doc = payload.get('document', {}).get('document_id', '')
        with self.lock:
            row = self.db.execute('SELECT content_hash,profile,reviewed_at,decision_count FROM document_reviews WHERE document_id=?', (doc,)).fetchone()
        if not needs_review and row and row[0] == sha256_of(payload) and row[1] == profile:
            return {'review_status': 'reviewed', 'reviewed_at': row[2], 'review_decision_count': row[3]}
        return {'review_status': 'needs_review' if needs_review or row else 'unreviewed',
                'reviewed_at': None, 'review_decision_count': 0}

    def mark(self, payload, profile):
        doc = payload.get('document', {}).get('document_id')
        if not isinstance(doc, str) or not doc: raise ValueError('Thiếu document_id để lưu trạng thái duyệt.')
        stamp = utcnow_iso(); count = len(payload.get('entity_link_decisions', {}))
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO document_reviews VALUES (?,?,?,?,?)',
                            (doc, sha256_of(payload), profile, stamp, count))
        return {'review_status': 'reviewed', 'reviewed_at': stamp, 'review_decision_count': count}

    def close(self):
        self.db.close()
