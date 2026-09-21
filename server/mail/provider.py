"""MailProvider interface.

All mail-provider code lives behind this ABC so that a Microsoft 365 / Graph provider
can be added later without touching the triage worker. The Gmail implementation lands
in Milestone 2 (`gmail.py`); this file only fixes the seam.

The worker depends only on these shapes — sender/subject/body metadata in, label
operations out — never on Gmail-specific types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IncomingMessage:
    """Provider-neutral view of one new inbox message."""

    message_id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    body_text: str
    received_at: datetime
    has_attachment: bool = False
    delivered_to: tuple[str, ...] = ()
    is_reply: bool = False


@dataclass(frozen=True)
class ProviderLabel:
    provider_label_id: str
    name: str


class MailProvider(ABC):
    """Read new inbox mail and write labels back. Implemented per provider (M2: Gmail)."""

    @abstractmethod
    def ensure_label(self, name: str, color: str = "") -> ProviderLabel: ...

    @abstractmethod
    def update_label(self, provider_label_id: str, name: str, color: str = "") -> ProviderLabel: ...

    @abstractmethod
    def delete_label(self, provider_label_id: str) -> None: ...

    @abstractmethod
    def apply_labels(self, message_id: str, add: list[str], remove: list[str] | None = None) -> None: ...

    @abstractmethod
    def fetch_new_messages(self) -> list[IncomingMessage]:
        """Return inbox messages since the stored cursor, advancing it on success."""
