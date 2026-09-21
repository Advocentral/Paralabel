"""Turn a raw email body into the trimmed plain text the classifier is allowed to see.

Data minimization lives here: we strip HTML, quoted replies, and signatures, then cut
to the first N characters. This is the only body text that ever leaves the server, and
it is never persisted. See docs/data-flow.md.
"""

from __future__ import annotations

import re

MAX_BODY_CHARS = 500

_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"[ \t ]+")
_MULTINL_RE = re.compile(r"\n{3,}")

# Lines that mark the start of quoted history or a signature — drop everything after.
_CUTOFF_PATTERNS = [
    re.compile(r"^-{2,}\s*original message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^_{5,}"),
    re.compile(r"^on .+wrote:\s*$", re.IGNORECASE),
    re.compile(r"^from:\s.+", re.IGNORECASE),
    re.compile(r"^sent from my ", re.IGNORECASE),
    re.compile(r"^--\s*$"),  # standard signature delimiter
]


def _strip_html(text: str) -> str:
    if "<" not in text or ">" not in text:
        return text
    text = _STYLE_SCRIPT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    return (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )


def clean_body(raw: str, max_chars: int = MAX_BODY_CHARS) -> str:
    if not raw:
        return ""
    text = _strip_html(raw)

    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(p.match(stripped) for p in _CUTOFF_PATTERNS):
            break  # quoted history / signature starts here
        if stripped.startswith(">"):
            continue  # inline quoted line
        kept.append(line)

    body = "\n".join(kept)
    body = _WS_RE.sub(" ", body)
    body = _MULTINL_RE.sub("\n\n", body).strip()
    return body[:max_chars]
