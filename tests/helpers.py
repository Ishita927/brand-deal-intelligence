from datetime import date

from brand_deals.schemas import (Category, CreatorProfile, Deliverable, EmailExtraction, Exclusivity,
                                 Kind, PaymentType, Platform, ReplyDraft)

TODAY = date(2025, 3, 10)


def make_ex(**kw) -> EmailExtraction:
    ex = EmailExtraction.empty()
    ex.category = Category.deal_offer
    for k, v in kw.items():
        setattr(ex, k, v)
    return ex


def reel(n=1):
    return Deliverable(platform=Platform.instagram, kind=Kind.reel, quantity=n)


def profile(**kw) -> CreatorProfile:
    base = dict(name="Asha", currency="INR", rates={"instagram:reel": 8000.0},
                exclusivities=[Exclusivity(category="skincare", until="2025-06-01")],
                avoid_categories=["gambling"], min_lead_days=3)
    base.update(kw)
    return CreatorProfile(**base)


class FakeLLM:
    """Same interface as GeminiClient, answers from a table, so tests need no API key."""
    def __init__(self, table):
        self.table = table

    def extract_many(self, emails, profile, today, on_progress=None):
        out = {e.id: self.table.get(e.id, "boom: no result") for e in emails}
        if on_progress:
            on_progress(len(emails), len(emails))
        return out

    def polish_drafts(self, facts_list):
        return {f["deal_id"]: ReplyDraft(subject="Re: " + f["original_subject"], body="POLISHED") for f in facts_list}