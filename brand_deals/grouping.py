"""Group emails that belong to the same deal, and merge their terms (latest email wins)."""
import re
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher

from .schemas import Category, EmailExtraction, EmailResult
from .utils import norm_brand, parse_date, sender_parts


def _clean_subject(s: str) -> str:
    s = (s or "").lower().strip()
    while True:
        new = re.sub(r"^(re|fwd|fw)\s*:\s*", "", s)
        if new == s:
            break
        s = new
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _addr(r: EmailResult) -> str:
    return sender_parts(r.sender)[1]


def _deliverable_set(ex: EmailExtraction) -> set:
    return {(d.platform.value, d.kind.value) for d in ex.deliverables}


def _related(a: EmailResult, b: EmailResult) -> bool:
    if Category.spam in (a.category, b.category):
        return False
    if a.category == Category.scam_or_phishing or b.category == Category.scam_or_phishing:
        both = a.category == b.category
        return both and bool(_addr(a)) and _addr(a) == _addr(b)
    ea, eb = a.extraction, b.extraction
    if ea is None or eb is None:
        return False
    ba, bb = norm_brand(ea.brand), norm_brand(eb.brand)
    if ba and bb and ba != bb:
        return False                       # an agency can send offers for different brands
    same_party = (ba and ba == bb) or (_addr(a) and _addr(a) == _addr(b))
    if not same_party:
        return False
    similar = SequenceMatcher(None, _clean_subject(a.subject), _clean_subject(b.subject)).ratio() >= 0.6
    later = b if (parse_date(b.date) or date.min) >= (parse_date(a.date) or date.min) else a
    follow_up = later.extraction.mentions_earlier_message
    overlap = bool(_deliverable_set(ea) & _deliverable_set(eb))
    return similar or follow_up or overlap


def group_emails(results: list[EmailResult]) -> list[list[EmailResult]]:
    parent = list(range(len(results)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            if _related(results[i], results[j]):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, r in enumerate(results):
        groups[find(i)].append(r)
    return sorted(groups.values(), key=lambda g: results.index(g[0]))


_SCALARS = ["brand", "agency", "contact_name", "contact_email", "fee", "currency", "deadline",
            "usage_rights", "exclusivity_requested", "product_category"]


def merge_group(group: list[EmailResult]):
    """Start from the latest email and fill any gaps from earlier ones. Returns (merged, latest_result)."""
    ordered = sorted(enumerate(group), key=lambda p: (parse_date(p[1].date) or date.min, p[0]))
    ordered = [r for _, r in ordered]
    latest = ordered[-1]
    withx = [r for r in ordered if r.extraction]
    merged = withx[-1].extraction.model_copy(deep=True) if withx else EmailExtraction.empty()
    for r in reversed(withx[:-1]):
        e = r.extraction
        for f in _SCALARS:
            if getattr(merged, f) in (None, ""):
                setattr(merged, f, getattr(e, f))
        if not merged.deliverables:
            merged.deliverables = e.deliverables
        if merged.payment_type.value in ("unclear", "none") and e.payment_type.value not in ("unclear", "none"):
            merged.payment_type = e.payment_type
        for f in ("matches_exclusivity_categories", "matches_avoid_categories", "other_rule_concerns", "suspicious_signals"):
            setattr(merged, f, list(dict.fromkeys(getattr(merged, f) + getattr(e, f))))
    return merged, latest