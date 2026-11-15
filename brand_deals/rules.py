"""Plain code that must be right: scam patterns, money checks, exclusivity, deadlines, next action."""
import re
from datetime import date
from typing import Optional

from .config import RATE_TOLERANCE
from .schemas import (Action, Category, CreatorProfile, Deliverable, EmailExtraction, Exclusivity,
                      PaymentType, ReplyDraft, RiskFlag)
from .utils import parse_date, rate_key

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com", "aol.com"}
BLOCKING = {"exclusivity_conflict", "avoid_category"}   # these turn an offer into not_a_fit

SCAM_PATTERNS = [
    (r"\b(registration|processing|verification|activation|onboarding|unlock|security)\s+(fee|charge)\b", "Asks you to pay a fee"),
    (r"refundable\s+deposit|security\s+deposit", "Asks for a deposit"),
    (r"(buy|purchase|pay\s+(with|using|via|in))\s+.{0,20}gift\s*cards?", "Payment involves gift cards"),
    (r"\b(bitcoin|btc|usdt)\b|crypto(currency)?\s+wallet", "Mentions crypto payment"),
    (r"western\s+union|moneygram", "Mentions a money-transfer service"),
    (r"(send|share|provide)\s+(us\s+)?(your\s+)?(password|otp|login|pin|cvv|bank\s+(account|details)|aadhaar|passport)",
     "Asks for passwords, ID or bank details"),
    (r"(buy|purchase|pay for)\s+.{0,40}(first|upfront|in advance).{0,60}(reimburs|refund|pay you back)",
     "Asks you to pay first and be reimbursed"),
    (r"(click|open|visit)\s+(this|the)\s+link.{0,40}(claim|verify|unlock|confirm)", "Link to claim or verify something"),
    (r"verify\s+your\s+(account|identity)", "Asks you to verify your account"),
]
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|rules|prompts?)",
    r"disregard\s+.{0,30}instructions",
    r"system\s+prompt",
    r"classify\s+(this|it)\s+as",
]
HIGH_RIGHTS = r"perpetu|forever|in all media|all rights|unlimited|buy-?out|lifetime|irrevocabl|work[- ]for[- ]hire"
MED_RIGHTS = r"whitelist|paid ads?|spark ads?|partnership ads?|dark post|boost|worldwide|\b\d+\s*(months?|years?)\b"


def scam_signals(text: str) -> list[str]:
    return [label for pat, label in SCAM_PATTERNS if re.search(pat, text, re.I | re.S)]


def injection_signals(text: str) -> list[str]:
    if any(re.search(p, text, re.I | re.S) for p in INJECTION_PATTERNS):
        return ["Email contains instructions aimed at an AI system"]
    return []


def money(amount: float, cur: Optional[str]) -> str:
    return f"{cur or ''} {amount:,.0f}".strip()


def describe(deliverables: list[Deliverable]) -> str:
    return ", ".join(f"{d.quantity} x {d.platform.value} {d.kind.value}" for d in deliverables)


def expected_rate(deliverables: list[Deliverable], profile: CreatorProfile):
    """Creator's own price for the whole package, or None if any item has no rate on file."""
    total = 0.0
    for d in deliverables:
        rate = profile.rates.get(rate_key(d.platform.value, d.kind.value))
        if rate is None:
            return None, describe(deliverables)
        total += rate * d.quantity
    return (total if deliverables else None), describe(deliverables)


def _active(e: Exclusivity, today: date) -> bool:
    until = parse_date(e.until)
    return until is None or until >= today


def is_complete(x: EmailExtraction) -> bool:
    return bool(x.deliverables) and (x.fee is not None or x.payment_type in (PaymentType.gifting, PaymentType.affiliate))


def compute_missing(x: EmailExtraction) -> list[str]:
    missing = []
    if not x.deliverables:
        missing.append("deliverables (what content, on which platform, how many)")
    if x.fee is None and x.payment_type not in (PaymentType.gifting, PaymentType.affiliate):
        missing.append("budget or fee")
    if not x.deadline:
        missing.append("deadline")
    if not x.usage_rights:
        missing.append("usage rights (how the brand may use the content)")
    return missing


def risk_flags(x: EmailExtraction, profile: CreatorProfile, today: date, received: date) -> list[RiskFlag]:
    flags: list[RiskFlag] = []

    def add(code, severity, reason):
        flags.append(RiskFlag(code=code, severity=severity, reason=reason))

    cur = (x.currency or "").upper()

    # 1. money
    if x.fee is not None and x.payment_type in (PaymentType.cash, PaymentType.unclear):
        if not cur:
            add("currency_unclear", "medium", "The currency is not stated.")
        elif cur != profile.currency.upper():
            add("currency_mismatch", "medium", f"Offer is in {cur} but your rates are in {profile.currency}. Compare manually.")
        else:
            need, desc = expected_rate(x.deliverables, profile)
            if need is None:
                add("no_rate_on_file", "low", "No rate on file for these deliverables, so the fee could not be checked.")
            elif x.fee < need * RATE_TOLERANCE:
                gap = round((1 - x.fee / need) * 100)
                sev = "high" if x.fee < need * 0.5 else "medium"
                add("below_rate", sev, f"Offer is {money(x.fee, cur)} for {desc}. Your rate is {money(need, cur)} ({gap}% below).")
    elif x.payment_type == PaymentType.gifting:
        add("gifting_only", "low" if profile.accepts_gifting else "medium", "Product only, no cash fee.")
    elif x.payment_type == PaymentType.affiliate:
        add("commission_only", "medium", "Paid only by commission on sales, with no guaranteed fee.")

    # 2. usage rights and brand-requested exclusivity
    rights = x.usage_rights or ""
    if re.search(HIGH_RIGHTS, rights, re.I):
        add("unusual_usage_rights", "high", f"Very broad usage rights requested: {rights}")
    elif re.search(MED_RIGHTS, rights, re.I):
        add("usage_rights_extra", "medium", f"Usage beyond normal posting: {rights}. This should be priced separately.")
    if x.exclusivity_requested:
        sev = "high" if re.search(r"perpetu|lifetime|year|12\s*month|annual", x.exclusivity_requested, re.I) else "medium"
        add("brand_exclusivity_request", sev, f"Brand asks for exclusivity: {x.exclusivity_requested}")

    # 3. creator's own commitments and rules (model picks the category, code checks dates and the list)
    active = {e.category.strip().lower(): e for e in profile.exclusivities if _active(e, today)}
    for c in x.matches_exclusivity_categories:
        e = active.get(c.strip().lower())
        if e:
            until = f" (until {e.until})" if e.until else ""
            add("exclusivity_conflict", "high", f"Conflicts with your active exclusivity in '{e.category}'{until}.")
    avoid = {c.strip().lower(): c for c in profile.avoid_categories}
    for c in x.matches_avoid_categories:
        if c.strip().lower() in avoid:
            add("avoid_category", "high", f"'{avoid[c.strip().lower()]}' is a category you do not promote.")
    for concern in x.other_rule_concerns:
        add("content_rule_concern", "medium", concern)

    # 4. deadline
    dl = parse_date(x.deadline)
    if dl:
        if dl < today:
            add("deadline_passed", "high", f"The deadline ({dl}) has already passed.")
        elif (dl - received).days < profile.min_lead_days:
            add("tight_deadline", "high",
                f"Only {(dl - received).days} day(s) between the email and the deadline. You need at least {profile.min_lead_days}.")

    # 5. suspicion
    if x.suspicious_signals:
        add("suspicious_request", "high", "; ".join(x.suspicious_signals))
    domain = (x.contact_email or "").split("@")[-1].lower()
    if domain in FREE_MAIL and x.brand:
        add("free_mail_sender", "low", f"{x.brand} is writing from a free email address ({domain}), not a company domain.")
    return flags


def decide_email_category(ex: Optional[EmailExtraction], text: str, profile: CreatorProfile,
                          today: date, received: date):
    """Returns (category, reason, scam_signals). Code overrides the model where it must be right."""
    signals = scam_signals(text) + injection_signals(text)
    if signals:
        return Category.scam_or_phishing, "; ".join(signals), signals
    if ex is None:
        return Category.needs_more_info, "Automatic analysis failed. Please read this email yourself.", []
    cat = ex.category
    if cat in (Category.deal_offer, Category.needs_more_info):
        blocking = [f for f in risk_flags(ex, profile, today, received) if f.code in BLOCKING]
        if blocking:
            return Category.not_a_fit, " ".join(f.reason for f in blocking), []
    if cat == Category.deal_offer and not is_complete(ex):
        return Category.needs_more_info, "Offer is missing: " + ", ".join(compute_missing(ex)), []
    return cat, ex.category_reason, []


def decide_action(category: Category, flags: list[RiskFlag]) -> Action:
    if category in (Category.scam_or_phishing, Category.spam):
        return Action.ignore_or_report
    if category == Category.not_a_fit:
        return Action.decline
    if category == Category.needs_more_info:
        return Action.ask_for_details
    codes = {f.code for f in flags}
    if "suspicious_request" in codes:
        return Action.ask_for_details
    if any(f.severity in ("medium", "high") for f in flags):
        return Action.negotiate
    return Action.accept


def talking_points(action: Action, deal, profile: CreatorProfile) -> list[str]:
    """First-person sentences a reply may use. Private details (e.g. which brand you are exclusive with) are never included."""
    flags = {f.code: f for f in deal.risk_flags}
    pts: list[str] = []
    if action == Action.accept:
        pts += ["I'm interested and would be happy to move forward.",
                "Could you please confirm the deliverables, fee and deadline in writing, along with the contract and "
                "when and how I will be paid?"]
    elif action == Action.negotiate:
        if "below_rate" in flags:
            need, desc = expected_rate(deal.deliverables, profile)
            pts.append(f"My rate for {desc} is {money(need, profile.currency)}. Would you be able to revise the budget to match?")
        if "gifting_only" in flags:
            pts.append("I mainly take paid collaborations. Is there a cash budget in addition to the product?")
        if "commission_only" in flags:
            pts.append("Is there a fixed fee in addition to the commission?")
        if "unusual_usage_rights" in flags or "usage_rights_extra" in flags:
            pts.append("Usage beyond normal posting (ads, whitelisting, long periods) is priced separately. "
                       "Could we limit it, or quote it as an add-on?")
        if "brand_exclusivity_request" in flags:
            pts.append("Exclusivity is priced separately, so I can't include it in this fee.")
        if "tight_deadline" in flags or "deadline_passed" in flags:
            pts.append(f"I need at least {profile.min_lead_days} days to make good content. Could we agree on a later date?")
        if "currency_unclear" in flags or "currency_mismatch" in flags:
            pts.append("Could you confirm the currency of the budget?")
        for f in deal.risk_flags:
            if f.code == "content_rule_concern":
                pts.append(f"One thing I'd like to check: {f.reason}")
        if not pts:
            pts.append("Could we go over the terms together before I confirm?")
    elif action == Action.ask_for_details:
        if deal.missing_info:
            pts.append("Before I can decide, could you please share: " + "; ".join(deal.missing_info) + "?")
        else:
            pts.append("Could you please share the full brief and budget?")
        if "suspicious_request" in flags:
            pts.append("Could you also share your official website and confirm that you represent the brand?")
    elif action == Action.decline:
        pts.append("Thank you for thinking of me, but I have to decline this one.")
        if "exclusivity_conflict" in flags:
            pts.append("I have an existing exclusive partnership in this category.")
        if "avoid_category" in flags:
            pts.append("This is not a category I promote.")
        pts.append("I'd be glad to hear about other opportunities that fit.")
    return pts


def template_reply(action: Action, deal, profile: CreatorProfile, subject: str) -> ReplyDraft:
    """Instant, deterministic draft. No model call needed."""
    pts = talking_points(action, deal, profile)
    first = (deal.contact_name or "").split()[0] if deal.contact_name else ""
    parts = [f"Hi {first}," if first else "Hi there,"]
    if action != Action.decline:
        parts.append(f"Thank you for reaching out{f' about {deal.brand}' if deal.brand else ''}.")
    parts.append(" ".join(pts) if len(pts) <= 2 else "\n".join(f"- {p}" for p in pts))
    parts.append(f"Best,\n{profile.name}")
    return ReplyDraft(subject=f"Re: {subject}", body="\n\n".join(parts))


_CURRENCY = {"₹": "INR", "rs": "INR", "inr": "INR", "rupees": "INR", "$": "USD", "usd": "USD", "dollars": "USD",
             "€": "EUR", "euros": "EUR", "£": "GBP"}
_MULT = {"k": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "million": 1e6}
_AMT = r"(\d[\d,]*(?:\.\d+)?)\s?(k|lakhs?|lacs?|crores?|cr|million)?"
_AMOUNT_BEFORE = re.compile(r"(₹|\$|€|£|(?<![a-z])rs\.?|(?<![a-z])inr|(?<![a-z])usd)\s?" + _AMT + r"\b", re.I)
_AMOUNT_AFTER = re.compile(r"(?<![\d.,])" + _AMT + r"\s?(inr|usd|rupees|dollars|euros)\b", re.I)


def amounts_in(text: str) -> list[tuple[float, str]]:
    """Money amounts written with a currency, e.g. 'Rs 3 lakh', '$1,200', '5k INR'. Used to double-check the model."""
    found = []
    for m in _AMOUNT_BEFORE.finditer(text):
        cur, num, mult = m.group(1).lower().rstrip("."), m.group(2), m.group(3)
        found.append((float(num.replace(",", "")) * _MULT.get((mult or "").lower(), 1), _CURRENCY[cur]))
    for m in _AMOUNT_AFTER.finditer(text):
        num, mult, cur = m.group(1), m.group(2), m.group(3)
        found.append((float(num.replace(",", "")) * _MULT.get((mult or "").lower(), 1), _CURRENCY[cur.lower()]))
    return found


def deal_category(group, merged: EmailExtraction, profile: CreatorProfile, today: date, received: date) -> Category:
    """Category of the whole deal, using the merged (latest) terms."""
    cats = [r.category for r in group]
    if Category.scam_or_phishing in cats:
        return Category.scam_or_phishing
    if all(c == Category.spam for c in cats):
        return Category.spam
    if any(f.code in BLOCKING for f in risk_flags(merged, profile, today, received)):
        return Category.not_a_fit
    return Category.deal_offer if is_complete(merged) else Category.needs_more_info