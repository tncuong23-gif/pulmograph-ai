import unittest

from pydantic import ValidationError

from app.schemas import ChatMessage


class ChatMessageSchemaTests(unittest.TestCase):
    def test_text_message_is_accepted(self):
        message = ChatMessage(id="m1", role="user", content="COPD là gì?")
        self.assertEqual(message.content, "COPD là gì?")

    def test_attachment_only_is_accepted_by_schema(self):
        message = ChatMessage(
            id="m2", role="user", content="",
            attachments=[{
                "id": "a1", "type": "medical_record", "fileName": "record.pdf",
                "fileSize": 10, "mimeType": "application/pdf", "status": "processed", "progress": 100,
            }],
        )
        self.assertEqual(len(message.attachments), 1)

    def test_empty_message_is_rejected(self):
        with self.assertRaises(ValidationError):
            ChatMessage(id="m3", role="user", content="   ")


if __name__ == "__main__":
    unittest.main()
