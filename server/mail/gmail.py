"""Gmail implementation of MailProvider.

Structure keeps googleapiclient at the very edge:

- `GmailApi` is a thin wrapper over the built Gmail resource (the only place that
  touches the HTTP client). Tests inject a fake with the same methods.
- `GmailProvider` contains all the provider logic (label sync, history walking,
  message parsing) and depends only on `GmailApi`, so it is fully unit-testable.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parseaddr

from ..triage.body import clean_body
from .provider import IncomingMessage, MailProvider, ProviderLabel


# --- thin transport wrapper -------------------------------------------------------


class GmailApi:
    """Wraps a built googleapiclient Gmail resource. The only class that does HTTP."""

    def __init__(self, service):
        self._svc = service

    def labels_list(self) -> list[dict]:
        return self._svc.users().labels().list(userId="me").execute().get("labels", [])

    def labels_create(self, name: str, color: str | None = None) -> dict:
        body: dict = {"name": name, "labelListVisibility": "labelShow",
                      "messageListVisibility": "show"}
        if color:
            body["color"] = {"backgroundColor": color, "textColor": "#ffffff"}
        return self._svc.users().labels().create(userId="me", body=body).execute()

    def labels_update(self, label_id: str, name: str, color: str | None = None) -> dict:
        body: dict = {"id": label_id, "name": name}
        if color:
            body["color"] = {"backgroundColor": color, "textColor": "#ffffff"}
        return self._svc.users().labels().update(userId="me", id=label_id, body=body).execute()

    def labels_delete(self, label_id: str) -> None:
        self._svc.users().labels().delete(userId="me", id=label_id).execute()

    def messages_modify(self, msg_id: str, add: list[str], remove: list[str]) -> None:
        self._svc.users().messages().modify(
            userId="me", id=msg_id, body={"addLabelIds": add, "removeLabelIds": remove}
        ).execute()

    def messages_get(self, msg_id: str, fmt: str = "full") -> dict:
        return self._svc.users().messages().get(userId="me", id=msg_id, format=fmt).execute()

    def messages_list(self, query: str) -> list[dict]:
        resp = self._svc.users().messages().list(userId="me", q=query).execute()
        return resp.get("messages", [])

    def history_list(self, start_history_id: str, label_id: str = "INBOX") -> list[dict]:
        records: list[dict] = []
        page_token = None
        while True:
            resp = self._svc.users().history().list(
                userId="me", startHistoryId=start_history_id,
                historyTypes=["messageAdded"], labelId=label_id, pageToken=page_token,
            ).execute()
            records.extend(resp.get("history", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return records

    def get_profile(self) -> dict:
        return self._svc.users().getProfile(userId="me").execute()

    def watch(self, topic: str, label_ids: list[str]) -> dict:
        return self._svc.users().watch(
            userId="me", body={"topicName": topic, "labelIds": label_ids, "labelFilterAction": "include"}
        ).execute()

    def stop_watch(self) -> None:
        self._svc.users().stop(userId="me").execute()


# --- message parsing (pure) -------------------------------------------------------


def _b64(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _walk_parts(payload: dict) -> tuple[str, str, bool]:
    """Return (plain_text, html_text, has_attachment) from a message payload."""
    plain, html, has_attachment = "", "", False
    stack = [payload]
    while stack:
        part = stack.pop()
        mime = part.get("mimeType", "")
        filename = part.get("filename") or ""
        body = part.get("body", {})
        if filename:
            has_attachment = True
        if mime == "text/plain" and not plain:
            plain = _b64(body.get("data", ""))
        elif mime == "text/html" and not html:
            html = _b64(body.get("data", ""))
        stack.extend(part.get("parts", []) or [])
    return plain, html, has_attachment


def parse_message(raw: dict) -> IncomingMessage:
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    name, email_addr = parseaddr(headers.get("from", ""))
    subject = headers.get("subject", "")
    delivered = tuple(
        parseaddr(v)[1].lower()
        for v in (headers.get("delivered-to", ""), headers.get("to", ""))
        if v
    )
    is_reply = bool(headers.get("in-reply-to") or headers.get("references")) or subject.lower().startswith("re:")

    plain, html, has_attachment = _walk_parts(payload)
    body = plain if plain else clean_body(html)

    internal_ms = raw.get("internalDate")
    received = (
        datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc)
        if internal_ms else datetime.now(timezone.utc)
    )

    return IncomingMessage(
        message_id=raw["id"],
        thread_id=raw.get("threadId", ""),
        sender_name=name,
        sender_email=email_addr.lower(),
        subject=subject,
        body_text=body,
        received_at=received,
        has_attachment=has_attachment,
        delivered_to=tuple(d for d in delivered if d),
        is_reply=is_reply,
    )


# --- provider ---------------------------------------------------------------------


class GmailProvider(MailProvider):
    def __init__(self, api: GmailApi, parent_label: str = "Paralabel/"):
        self.api = api
        self.parent_label = parent_label
        self._label_cache: dict[str, str] | None = None

    def _full_name(self, name: str) -> str:
        return f"{self.parent_label}{name}" if self.parent_label else name

    def _labels_by_name(self, refresh: bool = False) -> dict[str, str]:
        if self._label_cache is None or refresh:
            self._label_cache = {lb["name"]: lb["id"] for lb in self.api.labels_list()}
        return self._label_cache

    def ensure_label(self, name: str, color: str = "") -> ProviderLabel:
        full = self._full_name(name)
        existing = self._labels_by_name().get(full)
        if existing:
            return ProviderLabel(existing, full)
        created = self.api.labels_create(full, color or None)
        self._labels_by_name(refresh=True)
        return ProviderLabel(created["id"], full)

    def update_label(self, provider_label_id: str, name: str, color: str = "") -> ProviderLabel:
        full = self._full_name(name)
        updated = self.api.labels_update(provider_label_id, full, color or None)
        self._labels_by_name(refresh=True)
        return ProviderLabel(updated["id"], full)

    def delete_label(self, provider_label_id: str) -> None:
        self.api.labels_delete(provider_label_id)
        self._labels_by_name(refresh=True)

    def apply_labels(self, message_id: str, add: list[str], remove: list[str] | None = None) -> None:
        self.api.messages_modify(message_id, add=add, remove=remove or [])

    def history_since(self, start_history_id: str) -> tuple[list[IncomingMessage], str]:
        """Return (new INBOX messages since cursor, latest historyId).

        The caller advances its stored cursor to the returned historyId only after it
        has processed every message successfully.
        """
        records = self.api.history_list(start_history_id)
        latest = start_history_id
        seen: set[str] = set()
        message_ids: list[str] = []
        for rec in records:
            latest = str(rec.get("id", latest))
            for added in rec.get("messagesAdded", []):
                msg = added.get("message", {})
                mid = msg.get("id")
                # messagesAdded includes the label set at add time; keep INBOX only.
                if mid and mid not in seen and "INBOX" in (msg.get("labelIds") or ["INBOX"]):
                    seen.add(mid)
                    message_ids.append(mid)
        messages = [parse_message(self.api.messages_get(mid)) for mid in message_ids]
        return messages, latest

    def fetch_new_messages(self) -> list[IncomingMessage]:  # pragma: no cover - poller uses history_since
        raise NotImplementedError("use history_since(start_history_id) for cursor control")

    def resync_recent(self, query: str = "in:inbox newer_than:1d") -> list[IncomingMessage]:
        refs = self.api.messages_list(query)
        return [parse_message(self.api.messages_get(r["id"])) for r in refs]

    def current_history_id(self) -> str:
        return str(self.api.get_profile()["historyId"])

    def start_watch(self, topic: str) -> tuple[str, datetime]:
        """Register a Gmail push watch on INBOX. Returns (historyId, expiration)."""
        resp = self.api.watch(topic, ["INBOX"])
        history_id = str(resp["historyId"])
        # Gmail returns expiration as epoch milliseconds (string).
        expiration = datetime.fromtimestamp(int(resp["expiration"]) / 1000, tz=timezone.utc)
        return history_id, expiration

    def stop_watch(self) -> None:
        self.api.stop_watch()
