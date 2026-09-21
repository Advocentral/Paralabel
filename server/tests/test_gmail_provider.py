from __future__ import annotations

from server.mail.gmail import GmailProvider, parse_message

from .fakes import FakeGmailApi, make_raw_message


def test_parse_message_extracts_fields():
    raw = make_raw_message(
        "m1", sender="Clerk of Court <ecf@txsd.uscourts.gov>",
        subject="Re: Notice", body="The Clerk docketed this.", in_reply_to="<x@y>",
    )
    msg = parse_message(raw)
    assert msg.sender_email == "ecf@txsd.uscourts.gov"
    assert msg.sender_name == "Clerk of Court"
    assert msg.subject == "Re: Notice"
    assert "docketed" in msg.body_text
    assert msg.is_reply is True


def test_parse_message_detects_attachment():
    raw = make_raw_message("m2")
    raw["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": raw["payload"]["headers"],
        "parts": [
            {"mimeType": "text/plain", "body": raw["payload"]["body"]},
            {"mimeType": "application/pdf", "filename": "brief.pdf", "body": {}},
        ],
    }
    msg = parse_message(raw)
    assert msg.has_attachment is True


def test_ensure_label_creates_under_parent_and_caches():
    api = FakeGmailApi()
    provider = GmailProvider(api, parent_label="Paralabel/")
    pl = provider.ensure_label("Clients", "#16a765")
    assert pl.name == "Paralabel/Clients"
    # Second call returns cached id, does not create a duplicate.
    pl2 = provider.ensure_label("Clients")
    assert pl2.provider_label_id == pl.provider_label_id
    assert len(api.labels) == 1


def test_apply_labels_calls_modify():
    api = FakeGmailApi()
    provider = GmailProvider(api)
    provider.apply_labels("m1", add=["Label_1"], remove=[])
    assert api.modified == [("m1", ["Label_1"], [])]


def test_history_since_collects_inbox_messages_and_advances():
    api = FakeGmailApi()
    api.add_inbox_message("m1", history_id="101")
    api.add_inbox_message("m2", history_id="102")
    provider = GmailProvider(api)
    messages, latest = provider.history_since("100")
    assert [m.message_id for m in messages] == ["m1", "m2"]
    assert latest == "102"
