from brand_deals.pipeline import run_pipeline
from brand_deals.schemas import Category, Email, PaymentType
from tests.helpers import TODAY, FakeLLM, make_ex, profile, reel


def E(i, sender, subject, date, body="hi"):
    return Email(id=str(i), sender=sender, subject=subject, date=date, body=body)


def test_end_to_end_grouping_and_latest_terms():
    emails = [
        E(1, "Maya <maya@glow.com>", "Reel collab", "2025-03-01"),
        E(2, "Rhea <rhea@agency.com>", "Re: Reel collab", "2025-03-05", "just following up, budget is now 9000"),
        E(3, "x <x@free.com>", "Fee", "2025-03-06", "Pay registration fee to unlock"),
        E(4, "News <n@spam.com>", "Weekly deals", "2025-03-07"),
        E(5, "Ken <ken@bet.com>", "Casino promo", "2025-03-08"),
        E(6, "z <z@co.com>", "broken", "2025-03-09"),
    ]
    t = {
        "1": make_ex(brand="Glow Labs", deliverables=[reel()], fee=3000, currency="INR", payment_type=PaymentType.cash),
        "2": make_ex(brand="Glow Labs Pvt Ltd", agency="Agency", mentions_earlier_message=True,
                     deliverables=[], fee=9000, currency="INR", payment_type=PaymentType.cash),
        "3": make_ex(category=Category.deal_offer, brand="FakeCo"),
        "4": make_ex(category=Category.spam),
        "5": make_ex(brand="BetKing", deliverables=[reel()], fee=20000, currency="INR",
                     payment_type=PaymentType.cash, matches_avoid_categories=["gambling"]),
    }
    out = run_pipeline(emails, profile(), TODAY, FakeLLM(t), progress=lambda *_: None)
    cats = {e["email_id"]: e["category"] for e in out["emails"]}
    assert cats == {"1": "deal_offer", "2": "deal_offer", "3": "scam_or_phishing",
                    "4": "spam", "5": "not_a_fit", "6": "needs_more_info"}
    glow = next(d for d in out["deals"] if d["email_ids"] == ["1", "2"])
    assert glow["fee"] == 9000 and glow["recommended_action"] == "accept"   # latest terms win, 9000 >= 90% of 8000
    assert glow["reply_draft"] and "POLISHED" not in glow["reply_draft"]["body"]   # template by default
    assert out["stats"]["first_error"].startswith("boom")
    assert out["stats"]["deals"] == 4          # glow, scam, gambling, failed email; spam is not a deal
    assert out["stats"]["analysis_errors"] == 1
    assert next(d for d in out["deals"] if d["email_ids"] == ["3"])["recommended_action"] == "ignore_or_report"


def test_ai_drafts_option_and_regex_fee_fallback():
    emails = [E(1, "Maya <maya@glow.com>", "Reel collab", "2025-03-01", "We can pay Rs 3 lakh for one reel.")]
    t = {"1": make_ex(brand="Glow", deliverables=[reel()], payment_type=PaymentType.unclear)}   # model missed the fee
    out = run_pipeline(emails, profile(), TODAY, FakeLLM(t), progress=lambda *_: None, ai_drafts=True)
    deal = out["deals"][0]
    assert deal["fee"] == 300000 and deal["currency"] == "INR" and deal["payment_type"] == "cash"
    assert deal["reply_draft"]["body"] == "POLISHED"