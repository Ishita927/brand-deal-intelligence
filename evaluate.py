"""Compare outputs/analysis.json with your hand-written data/expected.json.

  python evaluate.py --init     # writes data/expected_template.json (fill it in by reading the emails)
  python evaluate.py            # prints the scores and writes outputs/evaluation_report.json
"""
import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from brand_deals.loader import load_emails
from brand_deals.utils import norm_brand


def _same(field, exp, got):
    if field == "brand":
        a, b = norm_brand(exp), norm_brand(got)
        return bool(a and b) and (a == b or a in b or b in a)
    if field == "fee":
        return got is not None and abs(float(exp) - float(got)) < 1
    return str(exp).lower() == str(got).lower()


def _pairs(mapping):
    """mapping: email_id -> group label (or None). Returns the set of same-group email pairs."""
    by = {}
    for k, g in mapping.items():
        if g is not None:
            by.setdefault(g, []).append(k)
    return {frozenset(p) for ids in by.values() for p in combinations(sorted(ids), 2)}


def evaluate(analysis: dict, expected: dict) -> dict:
    emails = {e["email_id"]: e for e in analysis["emails"]}
    deals = {d["deal_id"]: d for d in analysis["deals"]}
    exp_emails = expected["emails"]

    # 1. category per email
    confusion, mismatches, correct = Counter(), [], 0
    for eid, exp in exp_emails.items():
        got = emails.get(str(eid))
        if got is None:
            mismatches.append({"email_id": eid, "problem": "missing from analysis"})
            continue
        confusion[f"{exp['category']} -> {got['category']}"] += 1
        if got["category"] == exp["category"]:
            correct += 1
        else:
            mismatches.append({"email_id": eid, "subject": got["subject"], "expected": exp["category"],
                               "got": got["category"], "system_reason": got["category_reason"]})

    # 2. grouping (pairwise precision / recall)
    exp_group = {str(k): v.get("deal") for k, v in exp_emails.items()}
    got_group = {k: emails[k]["deal_id"] for k in exp_group if k in emails}
    ep, gp = _pairs(exp_group), _pairs(got_group)
    precision = len(ep & gp) / len(gp) if gp else 1.0
    recall = len(ep & gp) / len(ep) if ep else 1.0

    # 3. deal fields and action
    field_hits, field_total, deal_problems = Counter(), Counter(), []
    for label, exp in expected.get("deals", {}).items():
        member_ids = [str(k) for k, v in exp_emails.items() if v.get("deal") == label]
        votes = Counter(emails[m]["deal_id"] for m in member_ids if m in emails and emails[m]["deal_id"])
        if not votes:
            deal_problems.append({"expected_deal": label, "problem": "no predicted deal for its emails"})
            continue
        deal = deals[votes.most_common(1)[0][0]]
        for field in ("brand", "fee", "currency", "payment_type"):
            if exp.get(field) is None:
                continue
            field_total[field] += 1
            if _same(field, exp[field], deal.get(field)):
                field_hits[field] += 1
            else:
                deal_problems.append({"expected_deal": label, "field": field, "expected": exp[field], "got": deal.get(field)})
        if exp.get("action"):
            field_total["action"] += 1
            if exp["action"] == deal["recommended_action"]:
                field_hits["action"] += 1
            else:
                deal_problems.append({"expected_deal": label, "field": "action", "expected": exp["action"],
                                      "got": deal["recommended_action"]})
    return {
        "category_accuracy": f"{correct}/{len(exp_emails)}",
        "category_confusion": dict(confusion),
        "grouping": {"pair_precision": round(precision, 2), "pair_recall": round(recall, 2)},
        "deal_fields": {f: f"{field_hits[f]}/{field_total[f]}" for f in field_total},
        "category_mismatches": mismatches,
        "deal_problems": deal_problems,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", default="outputs/analysis.json")
    ap.add_argument("--expected", default="data/expected.json")
    ap.add_argument("--inbox", default="data/inbox.json")
    ap.add_argument("--out", default="outputs/evaluation_report.json")
    ap.add_argument("--init", action="store_true", help="write an empty expected-answers template")
    args = ap.parse_args()

    if args.init:
        template = {"emails": {e.id: {"category": None, "deal": None, "subject": e.subject} for e in load_emails(args.inbox)},
                    "deals": {"A": {"brand": None, "fee": None, "currency": None, "payment_type": None, "action": None}}}
        Path("data/expected_template.json").write_text(json.dumps(template, indent=2), encoding="utf-8")
        print("Wrote data/expected_template.json. Read each email yourself and fill it in, then save as data/expected.json.")
        return

    try:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8-sig"))
        expected = json.loads(Path(args.expected).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as e:
        raise SystemExit(f"File not found: {e.filename}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"A JSON file is empty or invalid ({e.msg}, line {e.lineno}). "
                         "Fill in data/expected.json (python evaluate.py --init makes a template).")
    report = evaluate(analysis, expected)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("category_mismatches", "deal_problems")}, indent=2))
    print(f"\n{len(report['category_mismatches'])} category mismatches, {len(report['deal_problems'])} deal problems.")
    print(f"Details in {args.out}")


if __name__ == "__main__":
    main()