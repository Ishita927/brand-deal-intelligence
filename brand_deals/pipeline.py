from collections import Counter
from datetime import date

from . import rules
from .grouping import group_emails, merge_group
from .rules import describe, money
from .schemas import (Action, Category, CreatorProfile, Deal, Email, EmailExtraction, EmailResult,
                      PaymentType, RiskFlag)
from .utils import parse_date, sender_parts


def build_result(email: Email, extracted, profile: CreatorProfile, today: date) -> EmailResult:
    """extracted is an EmailExtraction, or an error string if the model failed for this email."""
    ex, error = (extracted, None) if isinstance(extracted, EmailExtraction) else (None, str(extracted or "No result."))
    text = f"{email.subject}\n{email.body}"

    # Double-check the model's money: if it found no fee but the email has exactly one amount, use it.
    if ex and ex.fee is None and ex.category in (Category.deal_offer, Category.needs_more_info) \
            and ex.payment_type in (PaymentType.cash, PaymentType.unclear):
        found = set(rules.amounts_in(text))
        if len(found) == 1:
            amount, cur = next(iter(found))
            ex.fee, ex.currency = amount, ex.currency or cur
            ex.payment_type = PaymentType.cash

    received = parse_date(email.date) or today
    category, reason, signals = rules.decide_email_category(ex, text, profile, today, received)
    return EmailResult(
        email_id=email.id, sender=email.sender, subject=email.subject, date=email.date,
        category=category, category_reason=reason, llm_category=ex.category if ex else None,
        scam_signals=signals, error=error, extraction=ex,
    )


def build_deal(deal_id: str, group: list[EmailResult], profile: CreatorProfile, today: date) -> Deal:
    merged, latest = merge_group(group)
    received = parse_date(latest.date) or today
    category = rules.deal_category(group, merged, profile, today, received)

    if category == Category.scam_or_phishing:
        signals = []
        for r in group:
            signals += r.scam_signals + (r.extraction.suspicious_signals if r.extraction else [])
        signals = list(dict.fromkeys(signals)) or [latest.category_reason]
        flags = [RiskFlag(code="scam_signal", severity="high", reason=s) for s in signals]
    else:
        flags = rules.risk_flags(merged, profile, today, received)

    action = rules.decide_action(category, flags)
    sender_name, sender_addr = sender_parts(latest.sender)
    domain_name = sender_addr.split("@")[-1].split(".")[0] if sender_addr else None
    brand = merged.brand or merged.agency or domain_name
    pay = money(merged.fee, merged.currency) if merged.fee is not None else merged.payment_type.value
    headline = f"{brand or 'Unknown sender'}: {describe(merged.deliverables) or 'no deliverables stated'} for {pay}"

    deal = Deal(
        deal_id=deal_id, email_ids=[r.email_id for r in group], category=category, headline=headline,
        brand=brand, agency=merged.agency, contact_name=merged.contact_name or sender_name or None,
        contact_email=merged.contact_email or sender_addr or None, deliverables=merged.deliverables,
        fee=merged.fee, currency=merged.currency, payment_type=merged.payment_type, deadline=merged.deadline,
        usage_rights=merged.usage_rights, exclusivity_requested=merged.exclusivity_requested,
        product_category=merged.product_category, missing_info=rules.compute_missing(merged),
        risk_flags=flags, recommended_action=action,
    )
    if action != Action.ignore_or_report:
        deal.reply_draft = rules.template_reply(action, deal, profile, latest.subject)
    return deal


def run_pipeline(emails: list[Email], profile: CreatorProfile, today: date, llm,
                 progress=print, ai_drafts: bool = False) -> dict:
    extracted = llm.extract_many(
        emails, profile, today,
        on_progress=lambda done, total: progress(f"[{done}/{total}] analysed {done} of {total} emails"))
    results = [build_result(e, extracted.get(e.id), profile, today) for e in emails]

    deals = []
    for group in group_emails(results):
        if all(r.category == Category.spam for r in group):
            continue
        deal = build_deal(f"deal_{len(deals) + 1:02d}", group, profile, today)
        for r in group:
            r.deal_id = deal.deal_id
            # A bare follow-up ("any update?") has no details of its own: it takes its deal's category.
            if r.extraction and r.extraction.mentions_earlier_message and r.category == Category.needs_more_info:
                r.category = deal.category
                r.category_reason = f"Follow-up on an earlier message. Deal status: {deal.category.value}."
        deals.append(deal)

    warnings = []
    if ai_drafts:                                       # optional: one extra call to polish all drafts
        by_id = {r.email_id: r for r in results}
        facts = [{"deal_id": d.deal_id, "creator_name": profile.name, "brand": d.brand, "contact_name": d.contact_name,
                  "action": d.recommended_action.value, "original_subject": by_id[d.email_ids[-1]].subject,
                  "points_to_cover": rules.talking_points(d.recommended_action, d, profile)}
                 for d in deals if d.reply_draft]
        try:
            polished = llm.polish_drafts(facts) if facts else {}
            for d in deals:
                if d.deal_id in polished:
                    d.reply_draft = polished[d.deal_id]
        except Exception as e:
            warnings.append(f"AI draft polishing failed, template drafts were kept. {e}")

    act = {Action.accept, Action.negotiate, Action.ask_for_details}
    errors = [r.error for r in results if r.error]
    return {
        "as_of": str(today),
        "creator": profile.name,
        "warnings": warnings,
        "stats": {
            "emails": len(results),
            "deals": len(deals),
            "email_categories": dict(Counter(r.category.value for r in results)),
            "deal_actions": dict(Counter(d.recommended_action.value for d in deals)),
            "needs_attention": sum(d.recommended_action in act for d in deals),
            "analysis_errors": len(errors),
            "first_error": errors[0] if errors else None,
        },
        "emails": [r.model_dump(mode="json") for r in results],
        "deals": [d.model_dump(mode="json") for d in deals],
    }