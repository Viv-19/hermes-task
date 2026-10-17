"""Email clean-up (reply threads) and the mixed-intent check."""
import asyncio

from app import pipeline, preprocess
from app import schemas as S
from app import validators as V

REPLY = (
    "Please share the final bill of lading and invoice for the shipment delivered last week.\n\n"
    "Thanks,\nRohit\n\n"
    "On Mon, 5 Oct 2026 at 10:15, Ops Desk <ops@hermes.example> wrote:\n"
    "> Hello Rohit,\n> We shipped your cargo on 2 October.\n"
)


def test_reply_history_is_cut_off():
    clean, removed = preprocess.strip_quoted(REPLY)
    assert "bill of lading" in clean and "Rohit" in clean
    assert "wrote:" not in clean and "shipped your cargo" not in clean
    assert removed == 3


def test_wrote_on_the_next_line_and_original_message_are_handled():
    two_line = "Please quote.\n\nOn Mon, 5 Oct 2026 at 10:15 Someone\n<x@y.com> wrote:\nold text"
    assert preprocess.strip_quoted(two_line)[0] == "Please quote."
    outlook = "Need a rate.\n\n-----Original Message-----\nFrom: Ops\nold text"
    assert preprocess.strip_quoted(outlook)[0] == "Need a rate."


def test_forwarded_messages_are_kept_because_the_request_is_inside():
    forwarded = "Please quote this.\n\n---------- Forwarded message ---------\nFrom: Customer\nAir freight 100 kg Pune to Rotterdam."
    assert preprocess.strip_quoted(forwarded) == (forwarded, 0)


def test_a_normal_sentence_starting_with_on_is_not_cut():
    text = "On arrival please call me.\nWe need 5 cartons moved."
    assert preprocess.strip_quoted(text) == (text, 0)


def test_an_email_is_never_reduced_to_nothing():
    only_quote = "> everything here is quoted"
    assert preprocess.strip_quoted(only_quote) == (only_quote, 0)


def test_the_pipeline_analyses_only_the_new_message_and_says_so():
    async def run():
        return [e async for e in pipeline.analyze_events("Request for shipping documents", REPLY)]

    result = asyncio.run(run())[-1]["result"]
    assert result["category"] == "Documentation"
    assert any("ignored" in n for n in result["notes"])


# ---------------------------------------------------------------- urgency wording and transit time

ROHIT = (
    "Please prepare a freight quotation for the following shipment:\n- Origin: Pune, India\n- Destination: Rotterdam\n"
    "- Mode: Air freight\n- Commodity: Precision-machined aluminium components\n- Gross weight: 320 kg\n"
    "- Packages: 8 wooden crates\n- Dimensions per crate: 80 x 60 x 55 cm\n- Incoterm: EXW Pune\n"
    "- Cargo-ready date: 28 October 2026\n- Required delivery: As soon as reasonably possible\n"
    "Please provide the applicable quotation and estimated transit time if these can be confirmed.\n"
    "Regards,\nRohit Mehra, Supply Chain Manager"
)


def _rohit_raw(draft_body):
    def f(value, evidence, unit=None):
        return {"value": value, "unit": unit, "evidence": evidence}

    return {
        "category": S.FREIGHT,
        "fields": {
            "origin": f("Pune, India", "Origin: Pune, India"),
            "destination": f("Rotterdam", "Destination: Rotterdam"),
            "commodity": f("Precision-machined aluminium components", "Commodity: Precision-machined aluminium components"),
            "gross_weight": f("320", "Gross weight: 320 kg", "kg"),
            "pieces": f("8", "Packages: 8 wooden crates", "wooden crates"),
            "dimensions": f("80 x 60 x 55 cm", "Dimensions per crate: 80 x 60 x 55 cm"),
            "incoterm": f("EXW", "Incoterm: EXW Pune"),
            "cargo_ready_date": f("28 October 2026", "Cargo-ready date: 28 October 2026"),
        },
        "draft_reply": {"subject": "Re", "body": draft_body},
    }


def test_as_soon_as_reasonably_possible_counts_as_urgent():
    for phrase in ("as soon as reasonably possible", "at the earliest", "ASAP", "please deliver immediately"):
        assert V.URGENCY_RE.search(phrase), phrase


def test_complete_enquiry_with_vague_delivery_gets_a_recommended_delivery_question():
    draft = "Dear Customer,\n\nThanks.\n\nTo help us proceed, could you please confirm:\n- Delivery deadline\n\nBest regards,\nHermes Team"
    result = V.build_result("Rate request", ROHIT, _rohit_raw(draft))
    assert result["information_complete"] is True  # nothing *required* is missing
    deadline = [m for m in result["missing_information"] if m["field"] == "delivery_deadline"]
    assert deadline and deadline[0]["reason"] == "recommended"
    assert result["recommended_action"] == "ASK_FOR_INFORMATION"  # matches the draft, which asks a question
    assert result["draft_reply"]["body"].startswith("Dear Rohit,")


def test_transit_time_request_is_not_ignored_by_an_ai_draft():
    draft = "Dear Customer,\n\nThanks.\n\nTo help us proceed, could you please confirm:\n- Delivery deadline\n\nBest regards,\nHermes Team"
    body = V.build_result("Rate request", ROHIT, _rohit_raw(draft))["draft_reply"]["body"]
    assert "estimated transit time" in body
    assert body.index("transit time") < body.index("Best regards")  # inserted above the sign-off
    assert "days" not in body  # no figure is promised


def test_an_ai_draft_that_already_answers_the_transit_request_is_left_alone():
    draft = "Dear Customer,\n\nThanks. Transit time will follow with the quotation.\n\n- Delivery deadline\n\nBest regards,\nHermes Team"
    result = V.build_result("Rate request", ROHIT, _rohit_raw(draft))
    assert result["draft_reply"]["body"].lower().count("transit") == 1
    assert not any("transit" in n for n in result["draft_reply"]["notes"])


# ---------------------------------------------------------------- mixed intent


def test_documents_plus_payment_is_mixed():
    text = "Please send the final Bill of Lading and also confirm that you received our payment for invoice INV-2231."
    assert V.detect_mixed_intent(text, S.DOCS) == [S.PAYMENT]


def test_single_purpose_emails_are_not_mixed():
    t1 = "Please quote air freight from Mumbai to Frankfurt for 125 kg. Please advise the transit time."
    t3 = "Please share the final bill of lading and invoice for the shipment delivered last week."
    t4 = "We need to move pharmaceutical samples from Mumbai to Frankfurt urgently. Please share your best rate."
    assert V.detect_mixed_intent(t1, S.FREIGHT) == []
    assert V.detect_mixed_intent(t3, S.DOCS) == []
    assert V.detect_mixed_intent(t4, S.FREIGHT) == []


def test_payment_terms_in_a_quotation_are_not_a_payment_request():
    text = "Please quote 2 x 40HC from Chennai to Rotterdam. Our payment terms are 30 days net."
    assert V.detect_mixed_intent(text, S.FREIGHT) == []


def test_mixed_intent_is_flagged_in_the_result():
    raw = {
        "category": S.DOCS,
        "fields": {"document_type": {"value": "Bill of Lading", "evidence": "Bill of Lading"}},
        "draft_reply": {"subject": "Re", "body": ""},
    }
    text = "Please send the final Bill of Lading and also confirm that you received our payment for invoice INV-2231."
    result = V.build_result("BL and payment", text, raw)
    assert "MIXED_INTENT" in result["flags"]
    assert any("payment" in a for a in result["ambiguities"])
