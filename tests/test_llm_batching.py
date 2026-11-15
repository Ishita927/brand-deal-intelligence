import re

from brand_deals.llm import GeminiClient
from brand_deals.rules import amounts_in, template_reply
from brand_deals.schemas import Action, BatchExtraction, BatchItem, Email, PaymentType
from tests.helpers import TODAY, make_ex, profile, reel


class FakeGemini(GeminiClient):
    """Skips the network. Drops the last email of any multi-email batch to test the retry."""
    def __init__(self):
        self._model = "test"
        self.calls = []

    def _call(self, kind, system, prompt, schema, attempts=3):
        ids = re.findall(r'<email id="([^"]+)"', prompt)
        self.calls.append(ids)
        if len(ids) > 1:
            ids = ids[:-1]
        return BatchExtraction(results=[BatchItem(email_id=i, **make_ex().model_dump()) for i in ids])


def test_batches_and_retries_missing_emails(monkeypatch):
    monkeypatch.setattr("brand_deals.llm.BATCH_SIZE", 3)
    emails = [Email(id=str(i), sender="a@b.com", subject="s", date="2025-03-01", body="hi") for i in range(1, 8)]
    g = FakeGemini()
    seen = []
    out = g.extract_many(emails, profile(), TODAY, on_progress=lambda d, t: seen.append((d, t)))
    assert set(out) == {str(i) for i in range(1, 8)}
    assert all(not isinstance(v, str) for v in out.values())        # every email got a result after the retry
    assert seen[-1] == (7, 7)
    assert len([c for c in g.calls if len(c) == 3]) == 2             # 7 emails -> batches of 3, 3, 1


def test_amounts_regex():
    assert amounts_in("Rs 3 lakh") == [(300000.0, "INR")]
    assert amounts_in("budget $1,200") == [(1200.0, "USD")]
    assert amounts_in("we have 5 hours and 100k followers") == []


def test_template_reply_mentions_the_rate():
    from brand_deals.pipeline import build_deal, build_result
    e = Email(id="1", sender="Maya <maya@glow.com>", subject="Collab", date="2025-03-01", body="hi")
    ex = make_ex(brand="Glow", deliverables=[reel()], fee=3000, currency="INR", payment_type=PaymentType.cash)
    r = build_result(e, ex, profile(), TODAY)
    deal = build_deal("deal_01", [r], profile(), TODAY)
    assert deal.recommended_action == Action.negotiate
    body = template_reply(deal.recommended_action, deal, profile(), "Collab").body
    assert "INR 8,000" in body and body.startswith("Hi Maya,")