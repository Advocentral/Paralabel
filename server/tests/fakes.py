"""In-memory fake of the Gmail API surface (GmailApi) for tests."""

from __future__ import annotations

import base64


def encode_part(text: str) -> dict:
    data = base64.urlsafe_b64encode(text.encode()).decode()
    return {"data": data}


def make_raw_message(
    msg_id: str,
    sender: str = "Sender <s@example.com>",
    subject: str = "Hello",
    body: str = "body text",
    thread_id: str | None = None,
    internal_date_ms: int = 1_700_000_000_000,
    label_ids: list[str] | None = None,
    to: str = "firm@example.com",
    in_reply_to: str | None = None,
) -> dict:
    headers = [
        {"name": "From", "value": sender},
        {"name": "Subject", "value": subject},
        {"name": "To", "value": to},
    ]
    if in_reply_to:
        headers.append({"name": "In-Reply-To", "value": in_reply_to})
    return {
        "id": msg_id,
        "threadId": thread_id or msg_id,
        "internalDate": str(internal_date_ms),
        "labelIds": label_ids or ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": encode_part(body),
        },
    }


class FakeGmailApi:
    def __init__(self, profile_history_id: str = "100"):
        self.labels: dict[str, dict] = {}
        self._label_counter = 0
        self.profile_history_id = profile_history_id
        self.messages: dict[str, dict] = {}
        self.history_records: list[dict] = []
        self.modified: list[tuple[str, list[str], list[str]]] = []

    # labels
    def labels_list(self) -> list[dict]:
        return list(self.labels.values())

    def labels_create(self, name: str, color: str | None = None) -> dict:
        self._label_counter += 1
        lid = f"Label_{self._label_counter}"
        self.labels[lid] = {"id": lid, "name": name}
        return self.labels[lid]

    def labels_update(self, label_id: str, name: str, color: str | None = None) -> dict:
        self.labels[label_id] = {"id": label_id, "name": name}
        return self.labels[label_id]

    def labels_delete(self, label_id: str) -> None:
        self.labels.pop(label_id, None)

    # messages
    def messages_modify(self, msg_id: str, add: list[str], remove: list[str]) -> None:
        self.modified.append((msg_id, add, remove))

    def messages_get(self, msg_id: str, fmt: str = "full") -> dict:
        return self.messages[msg_id]

    def messages_list(self, query: str) -> list[dict]:
        return [{"id": mid, "threadId": m.get("threadId", mid)} for mid, m in self.messages.items()]

    def history_list(self, start_history_id: str, label_id: str = "INBOX") -> list[dict]:
        return self.history_records

    def get_profile(self) -> dict:
        return {"emailAddress": "firm@example.com", "historyId": self.profile_history_id}

    # watch
    def watch(self, topic: str, label_ids: list[str]) -> dict:
        self.watched = (topic, tuple(label_ids))
        # expiration ~7 days out, epoch ms
        return {"historyId": self.profile_history_id, "expiration": "1700604800000"}

    def stop_watch(self) -> None:
        self.watched = None

    # test helpers
    def add_inbox_message(self, msg_id: str, history_id: str, **kw) -> None:
        raw = make_raw_message(msg_id, **kw)
        self.messages[msg_id] = raw
        self.history_records.append({
            "id": history_id,
            "messagesAdded": [{"message": {"id": msg_id, "labelIds": ["INBOX"]}}],
        })
