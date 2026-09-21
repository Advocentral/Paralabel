from __future__ import annotations

from server.triage.body import clean_body


def test_strips_html():
    out = clean_body("<p>Hello <b>world</b></p><script>evil()</script>")
    assert "Hello world" in out
    assert "evil" not in out
    assert "<" not in out


def test_drops_quoted_reply():
    raw = "My new message.\n> quoted old line\n> more quoted"
    out = clean_body(raw)
    assert "My new message." in out
    assert "quoted old line" not in out


def test_cuts_at_original_message_marker():
    raw = "Please advise.\n-----Original Message-----\nFrom: someone\nold body"
    out = clean_body(raw)
    assert "Please advise." in out
    assert "old body" not in out


def test_cuts_at_signature_delimiter():
    raw = "Thanks.\n-- \nJane Doe, Esq.\nBig Firm LLP"
    out = clean_body(raw)
    assert "Thanks." in out
    assert "Big Firm" not in out


def test_trims_to_max_chars():
    out = clean_body("x" * 1000, max_chars=500)
    assert len(out) == 500


def test_empty_is_safe():
    assert clean_body("") == ""
