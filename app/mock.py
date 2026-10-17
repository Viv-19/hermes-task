"""Canned "model answers" for MOCK_LLM=1 — lets you build and demo the UI with zero API quota.

They are returned in the same raw shape the real model produces, so they still go
through the full validation layer. The UI shows a MOCK badge on these results.
"""
import re


def _generic_freight(subject: str, body: str) -> dict | None:
    """A rough answer for any 'quote me from X to Y' email, so the mock demo handles new samples."""
    text = f"{subject}\n{body}"
    low = text.lower()
    if not any(w in low for w in ("price", "quation", "quotation", "qatation", "quote", "rate")):
        return None
    route = re.search(r"from\s+([A-Za-z][A-Za-z ]{1,30}?)\s+to\s+([A-Za-z][A-Za-z ]{1,30}?)\s*(?:[.,\n]|$)", text, re.I)
    if not route:
        return None
    what = re.search(r"(?:sending|shipping|send|ship|move)\s+([A-Za-z ]{2,30}?)\s+from", text, re.I)
    fields = {
        "origin": {"value": route.group(1).strip(), "unit": None, "evidence": route.group(0).strip()},
        "destination": {"value": route.group(2).strip(), "unit": None, "evidence": route.group(0).strip()},
    }
    if what:
        fields["commodity"] = {"value": what.group(1).strip(), "unit": None, "evidence": what.group(0).strip()}
    return {
        "category": "Freight Quotation Enquiry",
        "category_confidence": "high",
        "category_reason": "The sender asks for a price quotation for moving cargo.",
        "mode_hint": "UNKNOWN",
        "fields": fields,
        "ambiguities": [],
        "conflicts": [],
        "flags": [],
        "recommended_action": "ASK_FOR_INFORMATION",
        "draft_reply": {"subject": "Re: " + subject, "body": ""},
    }


def _f(value, evidence, unit=None):
    return {"value": value, "unit": unit, "evidence": evidence}


def _sign(text: str) -> str:
    return text + "\n\nBest regards,\nHermes Team"


def mock_response(subject: str, body: str) -> dict:
    t = f"{subject}\n{body}".lower()

    if "air freight" in t and "mumbai" in t and "frankfurt" in t:
        return {
            "category": "Freight Quotation Enquiry",
            "category_confidence": "high",
            "category_reason": "The sender asks for an air freight quotation.",
            "mode_hint": "AIR",
            "fields": {
                "origin": _f("Mumbai", "from Mumbai to Frankfurt"),
                "destination": _f("Frankfurt", "from Mumbai to Frankfurt"),
                "commodity": _f("general cargo", "125 kg general cargo"),
                "gross_weight": _f("125", "125 kg general cargo", "kg"),
                "pieces": _f("5", "packed in 5 cartons", "cartons"),
                "cargo_ready_date": _f("22 October", "Cargo will be ready on 22 October"),
            },
            "ambiguities": [],
            "conflicts": [],
            "flags": [],
            "recommended_action": "ASK_FOR_INFORMATION",
            "draft_reply": {
                "subject": "Re: " + subject,
                "body": _sign(
                    "Dear Customer,\n\nThank you for your air freight enquiry from Mumbai to Frankfurt for 125 kg of "
                    "general cargo in 5 cartons.\n\nTo prepare an accurate quotation, could you please confirm:\n"
                    "- Package dimensions (L × W × H per carton)\n- The Incoterm (e.g. EXW, FCA)\n\n"
                    "We have noted your request for transit time and will address it together with the quotation "
                    "once we have these details."
                ),
            },
        }

    if "nhava sheva" in t and "hamburg" in t:
        return {
            "category": "Freight Quotation Enquiry",
            "category_confidence": "high",
            "category_reason": "The sender asks for an FCL container quotation.",
            "mode_hint": "OCEAN",
            "fields": {
                "origin": _f("Nhava Sheva", "from Nhava Sheva to Hamburg"),
                "destination": _f("Hamburg", "from Nhava Sheva to Hamburg"),
                "gross_weight": _f("18500", "Gross cargo weight is 18,500 kg", "kg"),
                "container": _f("1 x 40HC", "one 40HC container"),
                "incoterm": _f("FOB", "Incoterm: FOB"),
            },
            "ambiguities": [],
            "conflicts": [],
            "flags": [],
            "recommended_action": "ASK_FOR_INFORMATION",
            "draft_reply": {
                "subject": "Re: " + subject,
                "body": _sign(
                    "Dear Customer,\n\nThank you for your enquiry for one 40HC container from Nhava Sheva to Hamburg "
                    "(FOB, gross cargo weight 18,500 kg).\n\nTo prepare an accurate quotation, could you please confirm:\n"
                    "- A description of the cargo (commodity)\n- The cargo-ready date\n\n"
                    "Once we receive these details, our team can proceed with the quotation process."
                ),
            },
        }

    if "shipping documents" in t or "bill of lading" in t and "invoice" in t:
        return {
            "category": "Documentation",
            "category_confidence": "high",
            "category_reason": "The sender asks for shipping documents, not a rate.",
            "mode_hint": "UNKNOWN",
            "fields": {
                "document_type": _f("final bill of lading and invoice", "final bill of lading and invoice"),
                "requested_action": _f("share", "Please share"),
            },
            "ambiguities": ["“the shipment delivered last week” is not a shipment reference."],
            "conflicts": [],
            "flags": [],
            "recommended_action": "ASK_FOR_INFORMATION",
            "draft_reply": {
                "subject": "Re: " + subject,
                "body": _sign(
                    "Dear Customer,\n\nThank you for your request for the final Bill of Lading and invoice.\n\n"
                    "So that we can identify the correct shipment, could you please share the shipment reference "
                    "(AWB, B/L, booking or invoice number)? Once identified, we will check the availability of the "
                    "documents with the relevant team."
                ),
            },
        }

    if "pharmaceutical" in t and "frankfurt" in t:
        return {
            "category": "Freight Quotation Enquiry",
            "category_confidence": "high",
            "category_reason": "The sender wants a rate for moving samples.",
            "mode_hint": "UNKNOWN",
            "fields": {
                "origin": _f("Mumbai", "from Mumbai to Frankfurt"),
                "destination": _f("Frankfurt", "from Mumbai to Frankfurt"),
                "commodity": _f("pharmaceutical samples", "pharmaceutical samples"),
            },
            "ambiguities": ["“urgently” is not a delivery date."],
            "conflicts": [],
            "flags": [],
            "recommended_action": "ASK_FOR_INFORMATION",
            "draft_reply": {
                "subject": "Re: " + subject,
                "body": _sign(
                    "Dear Customer,\n\nThank you for your enquiry about moving pharmaceutical samples from Mumbai to "
                    "Frankfurt. We understand the shipment is urgent.\n\nTo prepare an accurate quotation, could you "
                    "please confirm:\n- The preferred mode of transport (air or ocean freight)\n"
                    "- The total gross weight and unit\n- The number of pieces and package dimensions (or volume in CBM)\n"
                    "- The cargo-ready date\n- The required delivery date / timeline\n- The Incoterm\n"
                    "- Any special handling needs, such as temperature control or dangerous-goods status"
                ),
            },
        }

    if "awb" in t:
        return {
            "category": "Shipment Status",
            "category_confidence": "high",
            "category_reason": "The sender asks where a shipment is.",
            "mode_hint": "UNKNOWN",
            "fields": {"shipment_reference": _f("176-12345675", "AWB 176-12345675")},
            "ambiguities": [],
            "conflicts": [],
            "flags": [],
            "recommended_action": "VERIFY_INTERNALLY",
            "draft_reply": {"subject": "Re: " + subject, "body": ""},
        }

    if any(w in t for w in ("meet", "call", "partnership")):
        return {
            "category": "General Business Email",
            "category_confidence": "high",
            "category_reason": "A request to schedule a conversation.",
            "mode_hint": "UNKNOWN",
            "fields": {"topic": _f("a call to discuss a partnership", "discuss a partnership")},
            "ambiguities": [],
            "conflicts": [],
            "flags": [],
            "recommended_action": "DRAFT_ACKNOWLEDGEMENT",
            "draft_reply": {
                "subject": "Re: " + subject,
                "body": _sign(
                    "Dear Customer,\n\nThank you for reaching out. We would be happy to discuss this further. "
                    "Please share your preferred dates and times so that we can coordinate accordingly."
                ),
            },
        }

    generic = _generic_freight(subject, body)
    if generic:
        return generic

    return {
        "category": "Other",
        "category_confidence": "low",
        "category_reason": "MOCK mode has no canned answer for this email.",
        "mode_hint": "UNKNOWN",
        "fields": {},
        "ambiguities": ["MOCK mode: no canned answer exists for this email — set MOCK_LLM=0 to analyse it with the AI."],
        "conflicts": [],
        "flags": [],
        "recommended_action": "ASK_FOR_INFORMATION",
        "draft_reply": {"subject": "Re: " + subject, "body": ""},
    }
