from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .schemas import iso_now


class ConversationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    createdAt TEXT NOT NULL,
                    updatedAt TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversationId TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    createdAt TEXT NOT NULL,
                    attachments TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(conversationId) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversationId, createdAt);
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            conn.execute("CREATE TABLE IF NOT EXISTS assessments (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_assessment_conversation ON assessments(conversation_id)")
            message_columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            if "metadata" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")

            # Additive migration: existing uploads have not yet been analyzed.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(attachments)")}
            for name, definition in {
                "status": "TEXT NOT NULL DEFAULT 'pending'",
                "analysis_json": "TEXT",
                "analysis_answer": "TEXT",
                "analysis_sources": "TEXT NOT NULL DEFAULT '[]'",
                "error": "TEXT",
                "attachment_type": "TEXT NOT NULL DEFAULT 'medical_record'",
                "clinical_input": "TEXT",
                "conversation_id": "TEXT",
                "user_message_id": "TEXT",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE attachments ADD COLUMN {name} {definition}")

    def mark_interrupted_uploads(self) -> None:
        # This service runs one worker; background work cannot survive a restart.
        with self._connect() as conn:
            conn.execute("UPDATE attachments SET status='error', error=? WHERE status='processing'",
                         ("Xử lý bị gián đoạn do backend khởi động lại. Vui lòng tải lại tệp.",))

    def set_attachment_analysis(self, attachment_id: str, status: str, result=None, answer=None, error=None, sources=None) -> None:
        if status not in {"pending", "processing", "processed", "error"}:
            raise ValueError("Invalid attachment status")
        with self._connect() as conn:
            conn.execute("UPDATE attachments SET status=?, analysis_json=?, analysis_answer=?, error=?, analysis_sources=COALESCE(?,analysis_sources) WHERE id=?",
                         (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                          answer, error, json.dumps(sources,ensure_ascii=False) if sources is not None else None, attachment_id))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def save_exchange(self, conversation_id: str, user: dict, assistant: dict) -> None:
        now = iso_now()
        title = (user.get("content") or "Cuộc trò chuyện mới").strip()[:80]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations(id,title,createdAt,updatedAt) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updatedAt=excluded.updatedAt",
                (conversation_id, title or "Cuộc trò chuyện mới", now, now),
            )
            for message in (user, assistant):
                conn.execute(
                    "INSERT OR IGNORE INTO messages(id,conversationId,role,content,createdAt,attachments,metadata) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        message["id"], conversation_id, message["role"], message.get("content", ""),
                        message.get("createdAt", now),
                        json.dumps(message.get("attachments", []), ensure_ascii=False),
                        json.dumps(message.get("metadata", {}), ensure_ascii=False),
                    ),
                )

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,title,createdAt,updatedAt FROM conversations ORDER BY updatedAt DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row is None:
                return None
            messages = conn.execute(
                "SELECT id,role,content,createdAt,attachments,metadata FROM messages "
                "WHERE conversationId=? ORDER BY createdAt",
                (conversation_id,),
            ).fetchall()
        result = dict(row)
        result["messages"] = [
            {**dict(message), "attachments": json.loads(message["attachments"]), "metadata": json.loads(message["metadata"])}
            for message in messages
        ]
        result["assessment"] = self.latest_assessment(conversation_id)
        return result

    def rename(self, conversation_id: str, title: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversations SET title=?,updatedAt=? WHERE id=?",
                (title.strip()[:120], iso_now(), conversation_id),
            )
        return cursor.rowcount > 0

    def delete(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversationId=?", (conversation_id,))
            cursor = conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        return cursor.rowcount > 0

    def add_attachment(self, row: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO attachments(id,file_name,mime_type,file_size,stored_path,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (row["id"], row["file_name"], row["mime_type"], row["file_size"], row["stored_path"], iso_now()),
            )

    def add_clinical_job(self, row, payload, conversation_id, user_message_id, modality):
        with self._connect() as conn:
            conn.execute("INSERT INTO attachments(id,file_name,mime_type,file_size,stored_path,created_at,attachment_type,clinical_input,conversation_id,user_message_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (row['id'], row['file_name'], row['mime_type'], row['file_size'], row['stored_path'], iso_now(),
                 'xray' if modality == 'xray' else 'medical_record', json.dumps(payload, ensure_ascii=False),
                 conversation_id, user_message_id, 'processing'))

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
        return dict(row) if row else None

    def latest_assessment(self, conversation_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM assessments WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1", (conversation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_assessment(self, assessment_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM assessments WHERE id=?", (assessment_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def commit_assessment(self, state: dict, *, expected_version: int | None, messages: list[dict] = ()) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if expected_version is None:
                now = iso_now()
                conn.execute("INSERT OR IGNORE INTO conversations(id,title,createdAt,updatedAt) VALUES(?,?,?,?)",
                             (state["conversation_id"], state["question"][:80], now, now))
                conn.execute("INSERT INTO assessments(id,conversation_id,version,data) VALUES(?,?,?,?)",
                             (state["id"], state["conversation_id"], state["version"], json.dumps(state, ensure_ascii=False)))
            else:
                cursor = conn.execute("UPDATE assessments SET version=?,data=? WHERE id=? AND version=?",
                                      (state["version"], json.dumps(state, ensure_ascii=False), state["id"], expected_version))
                if cursor.rowcount != 1:
                    raise ValueError("Assessment changed; reload before submitting.")
            for message in messages:
                conn.execute("INSERT OR IGNORE INTO messages(id,conversationId,role,content,createdAt,attachments,metadata) VALUES(?,?,?,?,?,'[]',?)",
                             (message["id"], state["conversation_id"], message["role"], message["content"], message["createdAt"], json.dumps(message.get("metadata", {}), ensure_ascii=False)))
            conn.execute("UPDATE conversations SET updatedAt=? WHERE id=?", (iso_now(), state["conversation_id"]))

    def recover_assessments(self) -> None:
        with self._connect() as conn:
            states = [json.loads(r[0]) for r in conn.execute("SELECT data FROM assessments")]
        from .services.assessment_facts import migrate_pending
        for state in states:
            if migrate_pending(state):
                version = state["version"]
                state["version"] += 1
                self.commit_assessment(state, expected_version=version)
            if state["status"] == "running":
                version = state["version"]
                state.update(status="failed", version=version+1, error="Backend đã khởi động lại. Có thể thử lại với cùng bản dữ kiện đã xác nhận.")
                self.commit_assessment(state, expected_version=version)
