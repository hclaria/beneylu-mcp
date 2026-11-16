import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

NOTIFICATION_KINDS = {
    "FAMILY": "mot",
    "CARDBOARD": "pancarte",
    "CALENDAR": "calendrier",
    "MEDIA_LIBRARY": "médiathèque",
}
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html or "")
    parser.close()
    text = unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def post_date(raw: dict) -> datetime:
    return parse_dt(raw.get("visibleAt") or raw["createdAt"])


def _item_id(item: dict) -> str:
    # Embeds also carry a timestamp and signature regenerated on every request: never hash those.
    for key in ("id", "embedId", "mediaId", "uuid"):
        if item.get(key) is not None:
            return str(item[key])
    return "?"


def post_fingerprint(raw: dict) -> str:
    parts = [
        raw.get("content") or "",
        raw.get("visibleAt") or "",
        ",".join(sorted(str(c) for c in raw.get("signableFor") or [])),
        ",".join(sorted(_item_id(a) for a in raw.get("postAttachments") or [])),
        ",".join(sorted(_item_id(e) for e in raw.get("postEmbeds") or [])),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Lookups:
    users: Mapping[int, str]
    groups: Mapping[int, str]
    children: Mapping[int, str]


def _name(mapping: Mapping[int, str], key: int) -> str:
    return mapping.get(key) or f"inconnu ({key})"


def post_from_api(raw: dict, lk: Lookups, base_url: str) -> dict:
    audience = (raw.get("linkedAudience") or {}).get("audience") or []
    signatures = raw.get("postSignatures") or []
    signed_for = {s.get("signedForId") for s in signatures}
    signable_for = raw.get("signableFor") or []
    return {
        "id": raw["id"],
        "date": post_date(raw).isoformat(),
        "author": _name(lk.users, raw.get("authorId")),
        "children": [_name(lk.children, a["userId"]) for a in audience if "userId" in a],
        "groups": [_name(lk.groups, a["groupId"]) for a in audience if "groupId" in a],
        "text": html_to_text(raw.get("content") or ""),
        "signature_required": bool(signable_for),
        "pending_signature_for": [_name(lk.children, c) for c in signable_for if c not in signed_for],
        "signatures": [
            {
                "child": _name(lk.children, s.get("signedForId")),
                "by": _name(lk.users, s.get("signedById")),
                "at": s.get("createdAt"),
            }
            for s in signatures
        ],
        "replies_allowed": bool(raw.get("allowReplies")),
        "attachments": len(raw.get("postAttachments") or []) + len(raw.get("postEmbeds") or []),
        "url": f"{base_url}/family-information/{raw['id']}",
    }


def notification_from_api(raw: dict, base_url: str) -> dict:
    app = raw.get("appName") or ""
    url = raw.get("url") or ""
    return {
        "id": raw["id"],
        "date": parse_dt(raw["createdAt"]).isoformat(),
        "kind": NOTIFICATION_KINDS.get(app, app.lower()),
        "text": raw.get("content") or "",
        "url": f"{base_url}{url}" if url.startswith("/") else url,
        "read": bool(raw.get("read")),
    }
