import re
from datetime import date
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

_COMPANY_WORDS = {"inc", "ltd", "llc", "pvt", "private", "limited", "co", "corp", "the", "official", "india"}
_PLATFORM = {"ig": "instagram", "insta": "instagram", "yt": "youtube", "twitter": "x"}
_KIND = {"reels": "reel", "stories": "story", "videos": "video", "posts": "post",
         "shorts": "short", "carousels": "carousel", "integrations": "integration"}


def norm_brand(name: Optional[str]) -> str:
    """'Nykaa India Pvt. Ltd.' and 'nykaa' -> 'nykaa'."""
    if not name:
        return ""
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _COMPANY_WORDS]
    return "".join(words)


def parse_date(value) -> Optional[date]:
    """Accepts ISO dates ('2025-03-04', '2025-03-04T10:00:00Z') and RFC-2822 email dates."""
    if not value:
        return None
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).date()
    except (TypeError, ValueError):
        return None


def sender_parts(sender: str):
    """'Maya <maya@x.com>' -> ('Maya', 'maya@x.com')"""
    name, addr = parseaddr(sender or "")
    return name, addr.lower()


def rate_key(platform: str, kind: str) -> str:
    p = (platform or "").strip().lower()
    k = (kind or "").strip().lower()
    return f"{_PLATFORM.get(p, p)}:{_KIND.get(k, k)}"