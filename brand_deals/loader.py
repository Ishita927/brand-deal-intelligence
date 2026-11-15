"""Reads the two input files and converts them to our own models.

The exact key names in your JSON files may differ from what I assumed.
If so, only this file needs editing.
"""
import json
from pathlib import Path

from .schemas import CreatorProfile, Email, Exclusivity
from .utils import rate_key


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in v]
    return [str(v)]


def load_emails(path) -> list[Email]:
    return parse_emails(json.loads(Path(path).read_text(encoding="utf-8")))


def parse_emails(raw) -> list[Email]:
    items = raw if isinstance(raw, list) else (_pick(raw, "emails", "inbox", "messages", default=[]))
    emails = []
    for i, it in enumerate(items, 1):
        sender = _pick(it, "from", "sender", "from_email", default="")
        if isinstance(sender, dict):
            sender = f"{sender.get('name', '')} <{sender.get('email', '')}>".strip()
        emails.append(Email(
            id=str(_pick(it, "id", "email_id", "message_id", default=i)),
            sender=str(sender),
            subject=str(_pick(it, "subject", "title", default="")),
            date=_pick(it, "date", "received_at", "sent_at", "timestamp"),
            body=str(_pick(it, "body", "text", "content", "message", default="")),
        ))
    return emails


def _rates(raw: dict) -> dict[str, float]:
    rates: dict[str, float] = {}
    r = raw.get("rates")
    if isinstance(r, dict):
        for k, v in r.items():
            if isinstance(v, (int, float)):
                p, _, kind = k.partition(":") if ":" in k else k.replace(" ", "_").partition("_")
                rates[rate_key(p, kind)] = float(v)
            elif isinstance(v, dict):                      # {"instagram": {"reel": 8000}}
                for kind, amount in v.items():
                    if isinstance(amount, (int, float)):
                        rates[rate_key(k, kind)] = float(amount)
    for plat in raw.get("platforms") or []:                # [{"platform": "instagram", "rates": {...}}]
        if isinstance(plat, dict):
            name = plat.get("platform") or plat.get("name")
            for kind, amount in (plat.get("rates") or {}).items():
                if name and isinstance(amount, (int, float)):
                    rates[rate_key(name, kind)] = float(amount)
    return rates


def _exclusivities(raw: dict) -> list[Exclusivity]:
    items = _pick(raw, "exclusivities", "current_exclusivities", "exclusivity", default=[])
    if isinstance(items, dict):
        items = [items]
    out = []
    for item in items or []:
        if isinstance(item, str):
            out.append(Exclusivity(category=item))
        elif isinstance(item, dict):
            out.append(Exclusivity(
                category=str(_pick(item, "category", "product_category", "type", default="")),
                brands=_as_list(_pick(item, "brands", "brand", "with")),
                until=_pick(item, "until", "end_date", "ends", "expires"),
            ))
    return out


def load_profile(path) -> CreatorProfile:
    return parse_profile(json.loads(Path(path).read_text(encoding="utf-8")))


def parse_profile(raw: dict) -> CreatorProfile:
    return CreatorProfile(
        name=str(_pick(raw, "name", "creator_name", "handle", default="Creator")),
        currency=str(_pick(raw, "currency", default="INR")),
        rates=_rates(raw),
        exclusivities=_exclusivities(raw),
        avoid_categories=_as_list(_pick(raw, "avoid_categories", "blocked_categories", "never_promote")),
        rules_text=_as_list(_pick(raw, "content_rules", "rules")),
        accepts_gifting=bool(_pick(raw, "accepts_gifting", "open_to_barter", default=False)),
        min_lead_days=int(_pick(raw, "min_lead_days", "min_turnaround_days", default=3)),
        raw=raw,
    )