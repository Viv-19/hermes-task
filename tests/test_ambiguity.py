"""Understanding unclear emails: structured ambiguities, AI signals, customer questions, the shared playbook."""
import shutil
from datetime import date

from app import config, skills
from app import schemas as S
from app import validators as V

TODAY = date(2026, 10, 17)
SIGN = "\n\nBest regards,\nHermes Team"


def f(value, evidence, unit=None):
    return {"value": value, "unit": unit, "evidence": evidence}


def freight(fields, body="", **extra):
    raw = {"category": S.FREIGHT, "fields": fields, "draft_reply": {"subject": "Re", "body": body}}
    raw.update(extra)
    return raw


def build(email, raw):
    return V.build_result("Quote", email, raw, today=TODAY)


EMAIL = (
    "Hi, about 100-120 kg of machine parts, 2 pallets and some loose boxes, ready end of the month. "
    "Same terms as last time. Please quote by air."
)
BASE_FIELDS = {
    "origin": f("Pune", "Pune"),
    "destination": f("Dubai", "Dubai"),
    "commodity": f("machine parts", "machine parts"),
    "gross_weight": f("100-120", "100-120 kg", "kg"),
    "pieces": f("2", "2 pallets", "pallets"),
    "cargo_ready_date": f("end of the month", "ready end of the month"),
}
EMAIL_WITH_PLACES = "From Pune to Dubai. " + EMAIL


# ---------------------------------------------------------------- structured ambiguities


def test_an_ambiguity_with_a_real_quote_becomes_a_question_in_the_reply():
    amb = [{"field": "gross_weight", "quote": "100-120 kg", "issue": "a range, not one weight",
            "question": "the total gross weight (you wrote “100-120 kg”)"}]
    ai_draft = "Dear Customer,\n\nThanks.\n\nTo help us proceed, could you please confirm:\n- Dimensions\n- Incoterm" + SIGN
    result = build(EMAIL_WITH_PLACES, freight(BASE_FIELDS, ai_draft, ambiguities=amb))
    assert "“100-120 kg” — a range, not one weight" in result["ambiguities"]
    asked = [m for m in result["missing_information"] if m["field"].startswith("clarify_gross_weight")]
    assert asked and asked[0]["reason"] == "recommended"
    body = result["draft_reply"]["body"]
    assert "total gross weight (you wrote “100-120 kg”)" in body  # appended to the AI's bullet list
    assert body.index("100-120 kg") < body.index("Best regards")


def test_a_quote_that_is_not_in_the_email_is_dropped_and_reported():
    amb = [{"field": "gross_weight", "quote": "about 500 kg", "issue": "vague", "question": "the weight"}]
    result = build(EMAIL_WITH_PLACES, freight(BASE_FIELDS, "", ambiguities=amb))
    assert result["ambiguities"] == [] or all("500" not in a for a in result["ambiguities"])
    assert any("about 500 kg" in r for r in result["removed_unsupported"])
    # no question was built from the invented quote
    assert not any("500" in m["label"] for m in result["missing_information"])


def test_no_duplicate_question_for_a_detail_that_is_missing_anyway():
    fields = dict(BASE_FIELDS)  # no incoterm given
    amb = [{"field": "incoterm", "quote": "Same terms as last time", "issue": "refers to earlier terms",
            "question": "the Incoterm (you wrote “same terms as last time”)"}]
    result = build(EMAIL_WITH_PLACES, freight(fields, "", ambiguities=amb))
    keys = [m["field"] for m in result["missing_information"]]
    assert "incoterm" in keys  # already asked as a required detail
    assert not any(k.startswith("clarify_incoterm") for k in keys)
    assert any("Same terms as last time" in a for a in result["ambiguities"])  # but still shown as unclear


def test_old_style_plain_string_ambiguities_still_work():
    result = build(EMAIL_WITH_PLACES, freight(BASE_FIELDS, "", ambiguities=["The weight could be gross or net, the email does not say"]))
    assert any(a.startswith("The weight could be") for a in result["ambiguities"])


def test_at_most_three_questions_are_asked():
    amb = [{"field": "general", "quote": q, "issue": "unclear", "question": f"details about “{q}”"}
           for q in ("100-120 kg", "some loose boxes", "end of the month", "Same terms as last time")]
    result = build(EMAIL_WITH_PLACES, freight(BASE_FIELDS, "", ambiguities=amb))
    assert len([m for m in result["missing_information"] if m["field"].startswith("clarify_")]) == 3


# ---------------------------------------------------------------- signals from the AI

CALM = "Please quote air freight Pune to Dubai, 100 kg of items, 2 cartons, 40x30x20 cm, EXW. Ready 28 October 2026."
CALM_FIELDS = {
    "origin": f("Pune", "Pune"), "destination": f("Dubai", "Dubai"), "commodity": f("items", "100 kg of items"),
    "gross_weight": f("100", "100 kg", "kg"), "pieces": f("2", "2 cartons", "cartons"),
    "dimensions": f("40x30x20 cm", "40x30x20 cm"), "incoterm": f("EXW", "EXW"),
    "cargo_ready_date": f("28 October 2026", "Ready 28 October 2026"),
}


def test_an_ai_signal_triggers_questions_even_without_any_listed_word():
    plain = build(CALM, freight(CALM_FIELDS, ""))
    assert [m["field"] for m in plain["missing_information"]] == []  # nothing to ask

    signalled = build(CALM, freight(CALM_FIELDS, "", signals={"urgent": True, "special_handling": True}))
    keys = {m["field"]: m["reason"] for m in signalled["missing_information"]}
    assert keys == {"delivery_deadline": "recommended", "special_handling": "recommended"}
    assert signalled["information_complete"] is True  # these are optional questions


def test_a_vague_date_signal_asks_for_an_exact_date_but_a_real_date_does_not():
    vague = dict(CALM_FIELDS, cargo_ready_date=f("in two weeks or so", "Ready in two weeks or so"))
    text = CALM.replace("Ready 28 October 2026", "Ready in two weeks or so")
    asked = build(text, freight(vague, "", signals={"vague_dates": True}))
    assert any(m["field"] == "cargo_ready_date_exact" for m in asked["missing_information"])
    exact = build(CALM, freight(CALM_FIELDS, "", signals={"vague_dates": True}))  # AI false alarm on a real date
    assert not any(m["field"] == "cargo_ready_date_exact" for m in exact["missing_information"])


def test_several_shipments_are_flagged_and_the_customer_is_asked_which_first():
    result = build(CALM, freight(CALM_FIELDS, "", signals={"multiple_shipments": True}))
    assert "MULTIPLE_SHIPMENTS" in result["flags"]
    assert any(m["field"] == "which_shipment" for m in result["missing_information"])


def test_an_attachment_reference_is_noticed_by_wording_or_by_the_ai():
    text = CALM + " See attached packing list for details."
    by_words = build(text, freight(CALM_FIELDS, ""))
    assert "ATTACHMENT_REFERENCED" in by_words["flags"]
    assert any("attachment" in n for n in by_words["notes"])
    assert any(m["field"] == "attachment_details" for m in by_words["missing_information"])
    by_ai = build(CALM, freight(CALM_FIELDS, "", signals={"references_attachment": True}))
    assert "ATTACHMENT_REFERENCED" in by_ai["flags"]


def test_signals_are_read_safely_when_the_ai_sends_nonsense():
    assert V._read_signals("yes")["urgent"] is False
    assert V._read_signals({"urgent": "true"})["urgent"] is True
    assert V._read_signals({"urgent": "false"})["urgent"] is False


# ---------------------------------------------------------------- customer questions


def test_a_customer_question_the_draft_ignores_gets_an_acknowledging_line():
    draft = "Dear Customer,\n\nThanks.\n\nTo help us proceed, could you please confirm:\n- Delivery deadline" + SIGN
    result = build(CALM, freight(CALM_FIELDS, draft, customer_questions=["what options we have", "estimated transit time"]))
    body = result["draft_reply"]["body"]
    assert "We have also noted your question: “what options we have”." in body
    assert body.index("what options we have") < body.index("Best regards")
    assert "transit" not in body.split("We have also noted")[1]  # the transit question has its own rule, not this one


def test_a_question_the_draft_already_covers_is_not_repeated():
    draft = "Dear Customer,\n\nWe will include the available options in the quotation.\n\n- Delivery deadline" + SIGN
    result = build(CALM, freight(CALM_FIELDS, draft, customer_questions=["what options we have"]))
    assert "We have also noted" not in result["draft_reply"]["body"]


# ---------------------------------------------------------------- defects found on real emails


def test_a_bare_air_alternative_counts_as_air_wording():
    assert V.detect_mode("Either container or air, depends on cost", {})[0] == "UNKNOWN"  # container + air = both named
    assert V.detect_mode("Please quote air or sea, whichever is cheaper", {})[0] == "UNKNOWN"
    assert V.detect_mode("Please quote air freight", {})[0] == "AIR"  # unchanged


def test_ranges_in_numbers_are_flagged_even_if_the_ai_did_not_say_so():
    text = "Roughly 2-3 tonnes of tiles, probably 4 or 5 pallets, from Morbi to Jebel Ali."
    fields = {
        "origin": f("Morbi", "Morbi"), "destination": f("Jebel Ali", "Jebel Ali"), "commodity": f("tiles", "tiles"),
        "gross_weight": f("2-3", "2-3 tonnes", "tonnes"), "pieces": f("4 or 5", "4 or 5 pallets", "pallets"),
    }
    result = build(text, freight(fields, ""))
    asks = [m["label"] for m in result["missing_information"] if m["field"].startswith("clarify_")]
    assert any("2-3 tonnes" in a for a in asks) and any("4 or 5" in a for a in asks)
    assert any("a range" in a for a in result["ambiguities"])


def test_mentioning_an_attachment_is_not_a_document_request_and_not_our_claim():
    text = "Please quote 150 kg leather Kanpur to Milan by air. The packing list is attached, please check the attached sheet."
    assert V.detect_mixed_intent(text, S.FREIGHT) == []
    assert not V.ATTACH_RE.search("Thank you for the attached packing list. We cannot open attachments.")
    assert V.ATTACH_RE.search("Please find attached our quotation.")
    assert V.ATTACH_RE.search("We have attached the documents.")


def test_a_long_quote_for_a_missing_detail_is_not_shown_as_unclear_but_a_second_shipment_is():
    text = "Please quote 150 kg of leather samples from Kanpur to Milan by air. Also a 40HC of finished shoes from Chennai to Hamburg in December."
    fields = {"origin": f("Kanpur", "Kanpur"), "destination": f("Milan", "Milan"), "commodity": f("leather samples", "leather samples"),
              "gross_weight": f("150", "150 kg", "kg")}
    amb = [
        {"field": "incoterm", "quote": "Please quote 150 kg of leather samples from Kanpur to Milan by air", "issue": "Incoterm not specified", "question": "the Incoterm"},
        {"field": "general", "quote": "a 40HC of finished shoes from Chennai to Hamburg in December", "issue": "a second shipment is described", "question": "which shipment to quote first"},
    ]
    result = build(text, freight(fields, "", ambiguities=amb))
    assert not any("Incoterm not specified" in a for a in result["ambiguities"])
    assert any("second shipment" in a for a in result["ambiguities"])
    assert "incoterm" in [m["field"] for m in result["missing_information"]]  # still asked, as a missing detail


def test_the_shipment_question_is_not_asked_twice():
    text = CALM + " Also a 40HC of shoes from Chennai."
    amb = [{"field": "general", "quote": "a 40HC of shoes from Chennai", "issue": "a second shipment",
            "question": "which shipment to quote first (you also wrote “a 40HC of shoes from Chennai”)"}]
    result = build(text, freight(CALM_FIELDS, "", ambiguities=amb, signals={"multiple_shipments": True}))
    keys = [m["field"] for m in result["missing_information"]]
    assert "which_shipment" not in keys
    assert any(k.startswith("clarify_general") for k in keys)


def test_a_missing_detail_filed_as_unclear_is_not_shown_as_unclear():
    fields = {k: v for k, v in CALM_FIELDS.items() if k != "dimensions"}
    amb = [
        {"field": "dimensions", "quote": "2 cartons", "issue": "dimensions not provided", "question": "the dimensions"},
        {"field": "incoterm", "quote": "EXW", "issue": "could mean ex-works or ex-warehouse", "question": "the Incoterm"},
    ]
    result = build(CALM, freight(fields, "", ambiguities=amb))
    assert not any("dimensions not provided" in a for a in result["ambiguities"])
    assert any("ex-works or ex-warehouse" in a for a in result["ambiguities"])  # a real unclear point stays


def test_a_paraphrased_question_is_not_asked_a_second_time():
    amb = [{"field": "general", "quote": "the other left Chennai on a vessel last month", "issue": "no reference",
            "question": "the reference for the other shipment (you wrote “the other left Chennai on a vessel last month”)"}]
    text = "AWB 098-7654321 is one. The other left Chennai on a vessel last month. Where are they? Please quote by air."
    draft = ("Dear Customer,\n\nThanks.\n\nTo help us proceed, could you please confirm:\n"
             "- the reference for the shipment that left Chennai on a vessel last month" + SIGN)
    result = build(text, freight(CALM_FIELDS, draft, ambiguities=amb))
    assert result["draft_reply"]["body"].lower().count("left chennai on a vessel") == 1  # not appended again


def test_the_ai_mixed_intent_flag_is_ignored_unless_the_wording_shows_a_second_request():
    result = build(CALM, freight(CALM_FIELDS, "", flags=["MIXED_INTENT"]))
    assert "MIXED_INTENT" not in result["flags"]
    both = "Please send the final Bill of Lading and confirm that you received our payment for INV-1."
    raw = {"category": S.DOCS, "fields": {}, "flags": ["MIXED_INTENT"], "draft_reply": {"subject": "Re", "body": ""}}
    assert "MIXED_INTENT" in V.build_result("BL", both, raw, today=TODAY)["flags"]


def test_a_draft_that_promises_to_read_an_attachment_is_replaced():
    text = CALM + " The packing list is attached."
    draft = "Dear Customer,\n\nWe will review the attached packing list and prepare the quotation.\n\nBest regards,\nHermes Team"
    result = build(text, freight(CALM_FIELDS, draft))
    assert result["draft_reply"]["source"] == "template"
    assert "attached packing list" not in result["draft_reply"]["body"]
    assert "DRAFT_CONTAINS_UNSUPPORTED_CLAIM" in result["flags"]


# ---------------------------------------------------------------- the draft guard on complete emails

PAYMENT_EMAIL = (
    "We have paid invoice INV-2026-0457 for USD 4,250.00 on 12 October 2026 by bank transfer, "
    "reference UTR 4567890123. Please confirm that the payment has been received.\n\nRegards,\nImran Shah"
)


def payment(draft_body):
    raw = {
        "category": S.PAYMENT,
        "fields": {
            "invoice_number": f("INV-2026-0457", "invoice INV-2026-0457"),
            "amount": f("4,250.00", "USD 4,250.00", "USD"),
        },
        "draft_reply": {"subject": "Re", "body": draft_body},
    }
    return V.build_result("Payment confirmation", PAYMENT_EMAIL, raw, today=TODAY)


def test_a_payment_reply_may_repeat_the_customers_own_amount():
    draft = ("Dear Customer,\n\nThank you for your email about invoice INV-2026-0457 for USD 4,250.00.\n\n"
             "We will verify the transaction with our accounts team." + SIGN)
    result = payment(draft)
    assert result["draft_reply"]["source"] == "ai"
    assert "DRAFT_CONTAINS_UNSUPPORTED_CLAIM" not in result["flags"]


def test_a_payment_reply_may_not_state_a_different_amount():
    result = payment("Dear Customer,\n\nWe received USD 9,999.00 from you." + SIGN)
    assert result["draft_reply"]["source"] == "template"
    assert "9,999" not in result["draft_reply"]["body"]


def test_a_freight_reply_may_not_repeat_a_price_even_if_the_customer_wrote_it():
    text = CALM + " Our budget is USD 3 per kg."
    draft = "Dear Customer,\n\nWe can do it at USD 3 per kg." + SIGN
    result = build(text, freight(CALM_FIELDS, draft))
    assert result["draft_reply"]["source"] == "template"  # agreeing to a price is a commitment


def test_a_reply_that_asks_for_none_is_replaced():
    draft = "Dear Customer,\n\nThanks.\n\nTo help us proceed, could you please confirm:\n- None\n\nWe will verify this." + SIGN
    result = payment(draft)
    assert result["draft_reply"]["source"] == "template"
    assert "None" not in result["draft_reply"]["body"]


# ---------------------------------------------------------------- the skills themselves


def test_every_skill_gets_the_shared_playbook_but_the_router_does_not():
    skill_prompt = skills.build_skill_prompt(S.FREIGHT)
    assert "SHARED PLAYBOOK" in skill_prompt and "Vague dates" in skill_prompt and 'SKILL "freight_quotation"' in skill_prompt
    assert "SHARED PLAYBOOK" not in skills.build_router_prompt()
    assert "SHARED PLAYBOOK" in skills.build_system_prompt()  # single-call mode too


def test_the_output_format_asks_for_the_structured_ambiguities_and_signals():
    prompt = skills.build_skill_prompt(S.PAYMENT)
    for word in ('"quote"', '"issue"', '"question"', '"signals"', '"customer_questions"', "references_attachment"):
        assert word in prompt


def test_every_category_has_a_skill_with_an_example_and_the_shared_file_is_not_a_skill():
    loaded = skills.load_skills()
    assert sorted(s["category"] for s in loaded) == sorted(S.CATEGORIES)
    assert all("## Example" in s["body"] for s in loaded)
    assert all(s["name"] != "ambiguity" for s in loaded)


def test_editing_the_shared_playbook_changes_the_cache_fingerprint(tmp_path, monkeypatch):
    copy = tmp_path / "skills"
    shutil.copytree(config.SKILLS_DIR, copy)
    monkeypatch.setattr(config, "SKILLS_DIR", copy)
    before = skills.skills_fingerprint()
    (copy / "_shared" / "ambiguity.md").write_text("# changed\n", encoding="utf-8")
    assert skills.skills_fingerprint() != before
