"""Deterministic checks applied to the model's raw answer.

The model only reads and writes. Everything that decides what is *true*, what is
*missing* and whether a draft is *safe* is decided here, so results are
reproducible and easy to explain:

  1. grounding   - every extracted value must be backed by a quote that really is in the email
  2. mode        - AIR / OCEAN / UNKNOWN comes from explicit wording, never from the route
  3. rules       - weights, Incoterms, dates, containers
  4. missing     - computed from a required-field table, not guessed by the model
  5. draft guard - no prices, transit promises, "attached", status or payment claims
"""
from __future__ import annotations

import re
from datetime import date

from . import schemas as S

NULL_STRINGS = {
    "", "null", "none", "n/a", "na", "nil", "-", "--", "unknown", "not specified",
    "not stated", "not provided", "not mentioned", "unspecified", "undefined",
}

INCOTERMS_2020 = {"EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"}
SEA_ONLY_INCOTERMS = {"FAS", "FOB", "CFR", "CIF"}
OLD_INCOTERMS = {
    "DAT": "DAT was replaced by DPU in Incoterms 2020",
    "CNF": "CNF is an informal form of CFR",
}
_INCOTERM_TOKEN = re.compile(r"\b(EXW|FCA|CPT|CIP|DAP|DPU|DDP|FAS|FOB|CFR|CIF|DAT|CNF)\b")

# --------------------------------------------------------------------------- mode signals
_AIR_PATTERNS = [
    r"\bair\s*-?\s*(?:fr(?:ei|ie)ght|cargo|shipment|shipping|rate|quote|quotation|consignment)s?\b",
    r"\bairfr(?:ei|ie)ght\b",
    r"\b(?:or|either|versus|vs\.?)\s+air\b",  # "container or air"
    r"\bair\s+(?:or|versus|vs\.?)\b",         # "air or sea"
    r"\bby\s+air\b",
    r"\bvia\s+air\b",
    r"\bawb\b",
    r"\bair\s*waybill\b",
    r"\bchargeable\s+weight\b",
]
_OCEAN_PATTERNS = [
    r"\bfcl\b",
    r"\blcl\b",
    r"\b(?:20|40|45)\s?(?:gp|dc|hc|hq|rf|ot|fr)\b",
    r"\b(?:20|40|45)\s?(?:ft|foot|feet)\b",
    r"\bcontainers?\b",
    r"\bteus?\b",
    r"\bsea\s*-?\s*(?:fr(?:ei|ie)ght|cargo|shipment|shipping)\b",
    r"\bocean\b",
    r"\bby\s+sea\b",
    r"\bvia\s+sea\b",
    r"\b(?:or|either|versus|vs\.?)\s+(?:sea|ocean)\b",  # "air or sea"
    r"\b(?:sea|ocean)\s+(?:or|versus|vs\.?)\b",         # "sea or air"
    r"\bvessel\b",
    r"\bbill\s+of\s+lading\b",
    r"\bb/l\b",
]
AIR_RE = [re.compile(p, re.I) for p in _AIR_PATTERNS]
OCEAN_RE = [re.compile(p, re.I) for p in _OCEAN_PATTERNS]
CONTAINER_SIZE_RE = re.compile(r"\b(?:20|40|45)\s?(?:gp|dc|hc|hq|rf|ot|fr|ft|foot|feet)\b", re.I)
FCL_RE = re.compile(r"\bfcl\b|\bfull\s+container\b", re.I)
LCL_RE = re.compile(r"\blcl\b|\bless\s+than\s+(?:a\s+)?container\b|\bconsolidat", re.I)

# --------------------------------------------------------------------------- misc patterns
URGENCY_RE = re.compile(
    r"\burgent(?:ly)?\b|\basap\b|\bas soon as (?:reasonably |humanly )?possible\b|\bat the earliest\b"
    r"|\bearliest (?:possible|available)\b|\bsoonest\b|\bimmediate(?:ly)?\b|\bdeadline\b|\bexpedite\b|\brush\b"
    r"|\btime[- ]sensitive\b|\bcritical\b|\bpriority\b",
    re.I,
)
SPECIAL_CARGO_RE = re.compile(
    r"pharma|medicin|medical|drug|vaccine|chemical|batter|lithium|perishable|frozen|fragile|"
    r"hazard|dangerous|flammable|explosive|radioactive|aerosol|perfume|temperature|cold chain|"
    r"biological|specimen|live animal",
    re.I,
)
ATTACHMENT_REF_RE = re.compile(
    r"\b(?:see|find|refer to|as per|per|check|in the)\s+(?:the\s+)?attach(?:ed|ment|ments)\b"
    r"|\battached\s+(?:file|document|sheet|list|copy|pdf|excel|photo|image)s?\b",
    re.I,
)
INJECTION_RE = re.compile(
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?)"
    r"|disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)"
    r"|forget\s+(?:all\s+|your\s+)?(?:previous|prior)\s+instructions?"
    r"|system\s+prompt|reveal\s+your\s+(?:instructions|prompt)|you\s+are\s+now\s+",
    re.I,
)
WEIGHT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(kgs?|kilograms?|lbs?|pounds?|mts?|tonnes?|tons?)\b", re.I
)

# Draft guard
PRICE_RE = re.compile(
    r"[$€£₹]\s?\d|\b(?:usd|eur|inr|gbp|aed|rs\.?)\s?\d|\d[\d,\.]*\s?(?:usd|eur|inr|gbp|aed|dollars|euros|rupees)\b",
    re.I,
)
TRANSIT_RE = re.compile(
    r"\b(?:transit(?:\s+time)?|deliver\w*|arriv\w*)\b[^.\n]{0,40}\b\d+\s*(?:-\s*\d+\s*)?(?:hours?|days?|weeks?)\b",
    re.I,
)
# Only OUR claims count ("we have attached", "please find attached"); "the attached packing list" is the
# customer's own attachment being mentioned.
ATTACH_RE = re.compile(
    r"\b(?:we|i)(?:\s+have|'ve)?\s+(?:attached|enclosed|sent)\b"
    r"|\bplease\s+find\s+(?:the\s+)?(?:attached|enclosed)\b"
    r"|\b(?:is|are)\s+(?:attached|enclosed)\b"
    r"|\b(?:has|have)\s+been\s+(?:sent|attached)\b",
    re.I,
)
STATUS_CLAIM_RE = re.compile(
    r"\b(?:is|are|was|has|have)\s+(?:currently\s+|now\s+)?(?:in\s+transit|delivered|delayed|cleared|on\s+its\s+way|"
    r"on\s+schedule|dispatched)\b"
    r"|\b(?:payment|amount|refund)\b[^.\n]{0,30}\b(?:has|have)\s+been\s+(?:received|processed|credited|confirmed|refunded)\b"
    r"|\bwe\s+(?:have\s+)?received\s+your\s+payment\b",
    re.I,
)
GUARANTEE_RE = re.compile(r"\bguarantee[ds]?\b", re.I)
# This tool reads only the text of an email, so a reply must never promise to look at an attachment.
ATTACH_READ_RE = re.compile(r"\b(?:review|check|open|read|look at|examine|go through)\b[^.\n]{0,40}\battach", re.I)

# Words a draft must contain to count as "asking for" a missing item.
COVERAGE = {
    "mode": r"\b(air|ocean|sea|mode|transport)\b",
    "origin": r"\b(origin|pick-?up|collection|loading|from)\b",
    "destination": r"\b(destination|deliver\w*|discharge)\b",
    "commodity": r"\b(commodity|cargo|goods|nature of|product|description)\b",
    "gross_weight": r"\bweight\b",
    "pieces": r"\b(pieces?|packages?|cartons?|pallets?|boxes|quantity|packing|number of)\b",
    "dimensions": r"\b(dimensions?|measurements?|size)\b",
    "dimensions_or_cbm": r"\b(dimensions?|measurements?|cbm|volume|size)\b",
    "cbm": r"\b(cbm|volume)\b",
    "container": r"\bcontainer\b",
    "container_type": r"\bcontainer\b",
    "shipment_type": r"\b(fcl|lcl|full container|part[- ]?load|less than)\b",
    "incoterm": r"\bincoterms?\b",
    "cargo_ready_date": r"\bready\b",
    "delivery_deadline": r"\b(deadline|required delivery|delivery (?:date|timeline|time)|timeline|by when|needed by|arrive)\b",
    "special_handling": r"\b(dangerous|hazardous|dg|temperature|special handling|handling|cold chain|refrigerat\w*)\b",
    "shipment_reference": r"\b(reference|awb|bill of lading|b/l|booking)\b",
    "document_type": r"\bdocument",
    "invoice_or_transaction": r"\b(invoice|transaction|reference)\b",
    "correction_details": r"\b(correct\w*|amend\w*|detail\w*)\b",
    "cargo_ready_date_exact": r"\b(exact|specific|precise)\b",
    "which_shipment": r"\b(which shipment|more than one|first shipment|each shipment|both shipments)\b",
    "attachment_details": r"\b(?:cannot|can't|unable to|only)\b[^.\n]{0,60}\battach|\bin the (?:body|text)\b|\bwritten in\b",
}

NUMERIC_FIELDS = {"gross_weight", "pieces", "cbm"}
RANGE_RE = re.compile(r"\d\s*(?:-|–|—|to|or)\s*\d", re.I)  # "100-120", "4 or 5"

# Clear wording that shows a request of each kind. Used to catch emails that ask for two things.
_INTENT_SIGNALS = {
    S.FREIGHT: re.compile(r"\b(?:quote|quotation|quoting|rate request|rates? for|best rate|price for|pricing for)\b", re.I),
    S.STATUS: re.compile(
        r"\b(?:status of|tracking|track (?:my|the|this)|where is|eta|etd|delayed"
        r"|update on (?:my|the|this) (?:shipment|cargo|container))\b",
        re.I,
    ),
    # a document counts as REQUESTED only when a request word comes before it ("please send the B/L"),
    # not when it is merely mentioned ("the packing list is attached")
    S.DOCS: re.compile(
        r"\b(?:send|share|provide|resend|need|require|issue|correct|copy of|request(?:ing)?|get|forward)\b[^.\n]{0,40}"
        r"\b(?:bill of lading|b/l|packing list|commercial invoice|shipping documents?|awb copy|certificate of origin)\b",
        re.I,
    ),
    S.PAYMENT: re.compile(r"\bpayment(?!\s+terms?)\b|\b(?:remittance|refund|outstanding|overdue|utr|paid)\b", re.I),
}
_INTENT_WORD = {
    S.FREIGHT: "a freight quotation",
    S.STATUS: "shipment status",
    S.DOCS: "shipping documents",
    S.PAYMENT: "payment",
}


def detect_mixed_intent(text: str, category: str) -> list[str]:
    """Other kinds of request found in the email besides the main category (deterministic, no AI)."""
    strong = [c for c, rx in _INTENT_SIGNALS.items() if rx.search(text)]
    if category in strong:
        return [c for c in strong if c != category]
    return strong if len(strong) >= 2 else []

# Greeting by name: "Thanks,\nRohit" -> "Dear Rohit,"
_CLOSING_RE = re.compile(
    r"^(?:thanks(?: and regards)?|thank you|many thanks|regards|best regards|kind regards|warm regards|"
    r"best wishes|sincerely|yours sincerely|yours faithfully|cheers|best)\s*(?:[,.!]+\s*(.*))?$",
    re.I,
)
_NAME_RE = re.compile(r"^[A-Z][A-Za-z'’\-]{1,20}(?:\s+[A-Z][A-Za-z'’\-]{1,20}){0,2}$")
_NOT_A_NAME = re.compile(
    r"team|dept|department|operations|logistics|support|sales|customer|pvt|ltd|\binc\b|company|services|group|hermes|desk|office|manager",
    re.I,
)


# --------------------------------------------------------------------------- small helpers


def norm(value) -> str:
    """Lower-case, punctuation-free form used for matching quotes against the email."""
    return re.sub(r"[\W_]+", " ", str(value).lower()).strip()


def contains(norm_text: str, norm_needle: str) -> bool:
    """Token-boundary containment: '5' is NOT found inside '125'."""
    return bool(norm_needle) and f" {norm_needle} " in f" {norm_text} "


def clean_str(value, limit: int = 300) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(x) for x in value if x is not None)
    elif isinstance(value, dict):
        return None
    text = str(value).strip()
    if text.lower() in NULL_STRINGS:
        return None
    return text[:limit]


def _clean_list(value, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = clean_str(item, 220)
        if text and text not in out:
            out.append(text)
    return out[:limit]


def _read_ambiguities(value, ntext: str, removed: list[str], fields: dict | None = None) -> tuple[list[str], list[dict]]:
    """Ambiguities arrive as plain strings or as {field, quote, issue, question}.

    A quote must really appear in the email; otherwise the whole point is dropped (it may be invented).
    Returns (lines to show, questions to ask the customer — at most 3).
    """
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return [], []
    lines: list[str] = []
    questions: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            quote = clean_str(item.get("quote"), 160)
            issue = clean_str(item.get("issue"), 200)
            question = clean_str(item.get("question"), 220)
            field = clean_str(item.get("field"), 40)
            if not (issue or question):
                continue
            if quote and not contains(ntext, norm(quote)):
                removed.append(f"An unclear point was dropped because the quote “{quote}” is not in the email.")
                continue
            # A whole sentence quoted for a detail that is simply missing is a missing detail (asked about
            # separately), not an unclear one. "general" points (such as a second shipment) are kept.
            if quote and len(quote.split()) > 10 and field != "general" and fields and field in fields and not fields[field]["found"]:
                continue
            # "dimensions not provided" for a detail that is simply missing is not an unclear point either
            if fields and field in fields and not fields[field]["found"] and re.search(
                r"\b(?:not|no|missing|unknown|unspecified)\b", issue or "", re.I
            ):
                continue
            line = (f"“{quote}” — " if quote else "") + (issue or question)
            if line not in lines:
                lines.append(line)
            if question and len(questions) < 3:
                questions.append({"field": field, "quote": quote, "issue": issue, "question": question})
        else:
            text = clean_str(item, 220)
            # a short phrase copied verbatim from the email ("price quation", "urgent") explains nothing
            if text and not (len(text.split()) <= 6 and contains(ntext, norm(text))) and text not in lines:
                lines.append(text)
    return lines[:8], questions


def _read_signals(value) -> dict:
    """What the AI noticed in the wording. These are combined with the word lists, never trusted alone."""
    value = value if isinstance(value, dict) else {}
    keys = ("urgent", "vague_dates", "special_handling", "multiple_shipments", "references_attachment")
    return {k: value.get(k) is True or str(value.get(k)).strip().lower() == "true" for k in keys}


def _unanswered_questions(questions: list[str], draft_body: str) -> list[str]:
    """Customer questions the draft does not touch (transit time has its own rule)."""
    ndraft = norm(draft_body)
    out = []
    for q in questions:
        if re.search(r"\btransit\b", q, re.I):
            continue
        words = [w for w in norm(q).split() if len(w) >= 5]
        if words and not any(w in ndraft for w in words):
            out.append(q)
    return out


def _numbers(text: str) -> set[str]:
    out = set()
    for match in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        number = match.replace(",", "")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        out.add(number)
    return out


def sender_name(body: str) -> str | None:
    """First name from the email signature ("Thanks,\\nRohit"), or None. Never guesses from the subject."""
    lines = [line.strip() for line in body.splitlines()]
    for i, line in enumerate(lines):
        match = _CLOSING_RE.match(line)
        if not match:
            continue
        candidate = (match.group(1) or "").strip() or next((nxt for nxt in lines[i + 1 : i + 3] if nxt), "")
        # "Rohit Mehra, Supply Chain Manager" / "Priya | Sales" -> keep only the name part
        candidate = re.split(r"\s*[,|]\s*|\s+[–—-]\s+", candidate)[0].strip()
        if candidate and _NAME_RE.match(candidate) and not _NOT_A_NAME.search(candidate):
            return candidate.split()[0]
    return None


def _personalize(draft_body: str, name: str | None) -> str:
    """'Dear Customer,' -> 'Dear Rohit,' when the sender signed with a name."""
    if name and draft_body.lstrip().startswith("Dear Customer"):
        return draft_body.replace("Dear Customer", f"Dear {name}", 1)
    return draft_body


def _split_value_unit(value: str, unit: str | None) -> tuple[str, str | None]:
    match = re.fullmatch(r"\s*(\d[\d,]*(?:\.\d+)?)\s*([A-Za-z][A-Za-z\.]*)?\s*", value)
    if match:
        return match.group(1), unit or match.group(2)
    return value, unit


def _unit_key(unit: str | None) -> str | None:
    if not unit:
        return None
    u = unit.lower().strip(". ")
    if u.startswith("kg") or u.startswith("kilo"):
        return "kg"
    if u.startswith("lb") or u.startswith("pound"):
        return "lb"
    if u in {"mt", "mts", "t", "ton", "tons", "tonne", "tonnes"}:
        return "t"
    return None


# --------------------------------------------------------------------------- 1. grounding


def _clean_fields(category: str, raw_fields, text: str, removed: list[str]) -> dict:
    """Keep a value only if the email really contains it (or the quote the model gave)."""
    ntext = norm(text)
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
    out: dict[str, dict] = {}
    for name, label, _ask in S.FIELDS[category]:
        item = raw_fields.get(name)
        if isinstance(item, dict):
            value, unit, evidence = item.get("value"), item.get("unit"), item.get("evidence")
        else:
            value, unit, evidence = item, None, None
        value = clean_str(value)
        unit = clean_str(unit, 40)
        evidence = clean_str(evidence, 200)
        note = None

        if value is not None:
            if name in NUMERIC_FIELDS:
                value, unit = _split_value_unit(value, unit)
            evidence_ok = evidence is not None and contains(ntext, norm(evidence))
            value_ok = contains(ntext, norm(value))
            if not (evidence_ok or value_ok):
                removed.append(
                    f"{label}: the model returned “{value}” but that is not in the email — removed."
                )
                value = unit = evidence = None
            else:
                if not evidence_ok:
                    evidence = value
                elif name in NUMERIC_FIELDS and re.search(r"\d", evidence) and not (
                    _numbers(value) <= _numbers(evidence)
                ):
                    removed.append(
                        f"{label}: “{value}” does not match the quoted text “{evidence}” — removed."
                    )
                    value = unit = evidence = None

        out[name] = {
            "label": label,
            "value": value,
            "unit": unit,
            "evidence": evidence,
            "note": note,
            "found": value is not None,
        }
    return out


# --------------------------------------------------------------------------- 2. mode


def _first_hit(patterns: list[re.Pattern], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return None


def detect_mode(text: str, fields: dict) -> tuple[str, str | None, str | None, list[str]]:
    """Return (mode, submode, evidence, conflicts) using explicit wording only."""
    conflicts: list[str] = []
    air = _first_hit(AIR_RE, text)
    ocean = _first_hit(OCEAN_RE, text)

    if air and ocean:
        conflicts.append(
            f"The email mentions both air (“{air}”) and ocean (“{ocean}”) wording — the mode is unclear."
        )
        return "UNKNOWN", None, None, conflicts
    if air:
        return "AIR", None, air, conflicts
    if not ocean:
        return "UNKNOWN", None, None, conflicts

    fcl = bool(FCL_RE.search(text) or CONTAINER_SIZE_RE.search(text))
    lcl = bool(LCL_RE.search(text))
    if fcl and lcl:
        conflicts.append("The email mentions both FCL (full container) and LCL (part-load).")
        return "OCEAN", None, ocean, conflicts
    if fcl:
        return "OCEAN", "FCL", ocean, conflicts
    if lcl or (fields.get("cbm", {}).get("found") and not fields.get("container", {}).get("found")):
        return "OCEAN", "LCL", ocean, conflicts
    return "OCEAN", None, ocean, conflicts


# --------------------------------------------------------------------------- 3. freight rules

_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b\.?,?\s*(\d{{4}})?", re.I)
_DATE_MDY = re.compile(rf"\b{_MONTH}\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b,?\s*(\d{{4}})?", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def _parse_date(text: str) -> tuple[int, int, int | None] | None:
    match = _DATE_DMY.search(text)
    if match:
        day, month, year = match.group(1), match.group(2), match.group(3)
    else:
        match = _DATE_MDY.search(text)
        if not match:
            return None
        month, day, year = match.group(1), match.group(2), match.group(3)
    return int(day), _MONTHS[month.lower()[:3]], int(year) if year else None


def _freight_checks(fields, text, mode, ambiguities, conflicts, flags, today: date, urgent: bool = False) -> None:
    # --- weights: unit present? several different weights in the email?
    weight = fields["gross_weight"]
    if weight["found"]:
        if not weight["unit"]:
            weight["note"] = "unit not stated"
            ambiguities.append("Gross weight is given without a unit (kg or lb?).")
        elif _unit_key(weight["unit"]) is None:
            weight["note"] = "unit not recognised"
    seen: dict[tuple[str, str], str] = {}
    for number, unit in WEIGHT_RE.findall(text):
        seen.setdefault((number.replace(",", ""), _unit_key(unit) or unit.lower()), f"{number} {unit}")
    if len(seen) > 1:
        conflicts.append(
            "Several different weights appear in the email: "
            + ", ".join(seen.values())
            + " — confirm which is the total gross weight."
        )

    # --- Incoterm
    incoterm = fields["incoterm"]
    if incoterm["found"]:
        token = _INCOTERM_TOKEN.search(incoterm["value"].upper())
        if not token:
            incoterm["note"] = "not a standard Incoterm"
            ambiguities.append(f"“{incoterm['value']}” is not a recognised Incoterms 2020 term.")
        elif token.group(1) in OLD_INCOTERMS:
            incoterm["note"] = "outdated term"
            ambiguities.append(f"{token.group(1)}: {OLD_INCOTERMS[token.group(1)]}.")
        elif token.group(1) in SEA_ONLY_INCOTERMS and mode == "AIR":
            flags.add("INCOTERM_MODE_MISMATCH")
            incoterm["note"] = "sea-only term with air freight"
            ambiguities.append(
                f"{token.group(1)} is normally used for sea freight only, but the email asks for air "
                "freight — confirm the intended Incoterm (for example FCA)."
            )

    # --- cargo-ready date: never invent a year, flag past dates
    ready = fields["cargo_ready_date"]
    if ready["found"]:
        value = ready["value"]
        years_in_text = set(re.findall(r"\b(?:19|20)\d{2}\b", text))
        for year in re.findall(r"\b(?:19|20)\d{2}\b", value):
            if year not in years_in_text:
                value = re.sub(rf",?\s*{year}\b", "", value).strip()
                ready["note"] = "year removed — not stated in the email"
        ready["value"] = value or ready["value"]
        parsed = _parse_date(ready["value"])
        if parsed:
            day, month, year = parsed
            if year is None:
                ready["note"] = ready["note"] or "year not stated"
            else:
                try:
                    if date(year, month, day) < today:
                        flags.add("PAST_DATE")
                        ambiguities.append(f"The cargo-ready date “{ready['value']}” is in the past.")
                except ValueError:
                    pass
        elif not re.search(r"\d", ready["value"]):
            ready["note"] = "not an exact date"
            ambiguities.append(
                f"The cargo-ready date is relative (“{ready['value']}”) — ask for an exact date."
            )

    # --- urgency without a real deadline
    if (
        (URGENCY_RE.search(text) or urgent)
        and not fields["delivery_deadline"]["found"]
        and not any(len(a) > 25 and re.search(r"urgent|deadline|delivery", a, re.I) for a in ambiguities)
    ):
        ambiguities.append("The email says it is urgent but gives no required delivery date.")


# --------------------------------------------------------------------------- 4. missing information


def _container_has_size(fields: dict) -> bool:
    container = fields["container"]
    if not container["found"]:
        return True
    return bool(CONTAINER_SIZE_RE.search(f"{container['value']} {container['evidence'] or ''}"))


def compute_missing(
    category: str, fields: dict, mode: str | None, submode: str | None, text: str, signals: dict | None = None
) -> list[dict]:
    """What to ask the customer. Word lists AND the AI's signals can both trigger the optional questions."""
    signals = signals or {}
    found = lambda key: bool(fields.get(key, {}).get("found"))  # noqa: E731
    missing: list[dict] = []

    def add(key: str, ask: str, reason: str = "required") -> None:
        if not any(m["field"] == key for m in missing):
            missing.append({"field": key, "label": ask, "reason": reason})

    if category == S.FREIGHT:
        core = ["origin", "destination", "commodity", "gross_weight"]
        tail = ["incoterm", "cargo_ready_date"]
        if mode == "AIR":
            items = core + ["pieces", "dimensions"] + tail
        elif mode == "OCEAN":
            if submode == "FCL":
                items = core + ["container"] + tail
            elif submode == "LCL":
                items = core + ["pieces", S.GROUP_DIMS_OR_CBM] + tail
            else:
                items = core + ["shipment_type"] + tail
        else:
            items = ["mode"] + core + ["pieces", S.GROUP_DIMS_OR_CBM] + tail
    elif category == S.STATUS:
        items = ["shipment_reference"]
    elif category == S.DOCS:
        items = ["document_type", "shipment_reference"]
    elif category == S.PAYMENT:
        items = [S.GROUP_INVOICE_OR_TXN]
    else:
        items = []

    for item in items:
        if isinstance(item, tuple):
            if not any(found(k) for k in item):
                add(S.GROUP_KEY[item], S.GROUP_ASK[item])
        elif item in S.EXTRA_ASK:
            add(item, S.EXTRA_ASK[item])
        elif not found(item):
            add(item, S.field_ask(category, item))

    if category == S.FREIGHT:
        if not _container_has_size(fields):
            add("container_type", S.EXTRA_ASK["container_type"])
        # Conditional asks — recommended, not blocking
        if (URGENCY_RE.search(text) or signals.get("urgent")) and not found("delivery_deadline"):
            add("delivery_deadline", S.field_ask(category, "delivery_deadline"), "recommended")
        ready = fields["cargo_ready_date"]
        if ready["found"] and (
            ready["note"] == "not an exact date" or (signals.get("vague_dates") and not _parse_date(ready["value"]))
        ):
            add("cargo_ready_date_exact", f"the exact cargo-ready date (you wrote “{ready['value']}”)", "recommended")
        commodity = fields["commodity"]["value"] or ""
        if (SPECIAL_CARGO_RE.search(f"{commodity} {text}") or signals.get("special_handling")) and not found("special_handling"):
            add("special_handling", S.field_ask(category, "special_handling"), "recommended")
    if category == S.DOCS and re.search(
        r"correct|amend|revis|change", fields["requested_action"]["value"] or "", re.I
    ) and not found("correction_details"):
        add("correction_details", S.field_ask(category, "correction_details"), "recommended")

    return missing


# --------------------------------------------------------------------------- 5. draft guard


def _asks_for(body: str, key: str, item: dict | None = None) -> bool:
    """Does the draft already ask for this? Questions from the AI count as asked when they quote the customer."""
    if key.startswith("clarify_"):
        # asked if the draft repeats most of the customer's words (the AI often paraphrases a little)
        quote = norm((item or {}).get("quote") or "")
        words = [w for w in quote.split() if len(w) >= 4]
        if not words:  # a short quote such as "100-120 kg": it must appear as written
            return contains(norm(body), quote) if quote else True
        in_draft = set(norm(body).split())
        return sum(w in in_draft for w in words) / len(words) >= 0.6
    pattern = COVERAGE.get(key)
    return True if pattern is None else bool(re.search(pattern, body, re.I))


def _ask_name(category: str, item: dict) -> str:
    """A short human name for a missing item, used in notes."""
    if item["field"].startswith("clarify_") and item.get("quote"):
        return f"“{item['quote']}”"
    return S.field_label(category, item["field"])


def _draft_problems(body: str, missing: list[dict], category: str) -> list[str]:
    problems = []
    if PRICE_RE.search(body):
        problems.append("it contained a price or rate")
    if TRANSIT_RE.search(body):
        problems.append("it promised a transit or delivery time")
    if ATTACH_RE.search(body):
        problems.append("it claimed something was attached or sent")
    if STATUS_CLAIM_RE.search(body):
        problems.append("it claimed a shipment or payment status")
    if GUARANTEE_RE.search(body):
        problems.append("it made a guarantee")
    if ATTACH_READ_RE.search(body):
        problems.append("it promised to read an attachment, which this tool cannot open")
    # Only *required* gaps force a template; "recommended" asks are a bonus, not a failure.
    unasked = [m for m in missing if m["reason"] == "required" and not _asks_for(body, m["field"])]
    if unasked:
        problems.append("it did not ask for: " + ", ".join(S.field_label(category, m["field"]) for m in unasked))
    return problems


def _append_asks(body: str, items: list[dict]) -> str | None:
    """Add bullets to the AI draft's existing bullet list. None if the draft has no list."""
    lines = body.split("\n")
    bullets = [i for i, line in enumerate(lines) if line.lstrip().startswith("- ")]
    if not bullets:
        return None
    new = [f"- {m['label'][:1].upper()}{m['label'][1:]}" for m in items]
    lines[bullets[-1] + 1 : bullets[-1] + 1] = new
    return "\n".join(lines)


def _insert_before_signoff(body: str, line: str) -> str:
    """Put one extra sentence just above 'Best regards' (or at the end if there is no sign-off)."""
    match = None
    for match in re.finditer(r"\n\s*(?:best regards|kind regards|regards|sincerely)\s*,", body, re.I):
        pass
    if match:
        return body[: match.start()].rstrip() + "\n\n" + line + "\n\n" + body[match.start() :].lstrip("\n")
    return body.rstrip() + "\n\n" + line


def _template_body(category: str, fields: dict, missing: list[dict], text: str, flags: set[str]) -> str:
    value = lambda key: fields.get(key, {}).get("value")  # noqa: E731
    asks = "\n".join(f"- {m['label'][:1].upper()}{m['label'][1:]}" for m in missing)
    sign = "Best regards,\nHermes Team"

    if category == S.FREIGHT:
        route = f" from {value('origin')} to {value('destination')}" if value("origin") and value("destination") else ""
        what = f" of {value('commodity')}" if value("commodity") else ""
        ship = f"your shipment{what}{route}"
        transit = (
            "\n\nWe have noted your request for transit time; it will be addressed together with the quotation."
            if re.search(r"\btransit\b", text, re.I)
            else ""
        )
        if missing:
            core = (
                f"Thank you for your enquiry regarding {ship}.\n\n"
                "To prepare an accurate freight quotation, could you please confirm the following details:\n"
                f"{asks}\n\nOnce we receive these details, our team can proceed with the quotation process."
            )
        else:
            core = (
                f"Thank you for sharing the details of {ship}.\n\n"
                "We have noted the cargo and shipment requirements you provided. Your enquiry is ready for the "
                "quotation process, and our team will review the details and prepare the applicable freight quotation."
            )
        return f"Dear Customer,\n\n{core}{transit}\n\n{sign}"

    if category == S.STATUS:
        ref = value("shipment_reference")
        if ref:
            core = (
                f"Thank you for your enquiry regarding shipment {ref}.\n\n"
                "We have noted your shipment reference. The latest shipment status needs to be verified with the "
                "relevant tracking system or operations team before we can provide a confirmed update."
            )
        else:
            core = (
                "Thank you for contacting us.\n\nCould you please share the relevant AWB, Bill of Lading, booking "
                "number or another shipment reference so that we can identify the shipment and assist with your status enquiry?"
            )
        return f"Dear Customer,\n\n{core}\n\n{sign}"

    if category == S.DOCS:
        if missing:
            core = (
                "Thank you for your email. To help us with your document request, could you please confirm:\n"
                f"{asks}"
            )
        else:
            core = (
                f"Thank you for your request for {value('document_type')} for shipment {value('shipment_reference')}.\n\n"
                "We have noted your request. The availability of the document needs to be checked with the relevant "
                "team, after which it can be shared through the appropriate document-handling process."
            )
        return f"Dear Customer,\n\n{core}\n\n{sign}"

    if category == S.PAYMENT:
        if missing:
            core = (
                "Thank you for contacting us regarding your payment. To help us look into this, could you please share:\n"
                f"{asks}"
            )
        else:
            core = (
                "Thank you for contacting us regarding your payment.\n\n"
                "We have noted your enquiry and the details provided. The transaction and its status need to be "
                "verified with the relevant accounts team before we can provide a confirmed update."
            )
        return f"Dear Customer,\n\n{core}\n\n{sign}"

    if category == S.GENERAL:
        core = (
            "Thank you for reaching out.\n\nWe have noted your message and will review it with the relevant team. "
            "Please let us know if there is any additional information that would help us respond."
        )
        return f"Dear Customer,\n\n{core}\n\n{sign}"

    core = (
        "Thank you for contacting Hermes.\n\nCould you please provide a little more information about your request "
        "so that we can direct it to the appropriate team and assist you accordingly?"
    )
    return f"Dear Customer,\n\n{core}\n\n{sign}"


def _read_draft(raw_draft) -> tuple[str | None, str | None]:
    if isinstance(raw_draft, str):
        return None, clean_str(raw_draft, 4000)
    if isinstance(raw_draft, dict):
        return clean_str(raw_draft.get("subject"), 200), clean_str(raw_draft.get("body"), 4000)
    return None, None


def _decide_action(category: str, missing: list[dict], flags: set[str], model_action) -> str:
    if flags & {"SUSPICIOUS", "PROMPT_INJECTION"}:
        return "FLAG_FOR_REVIEW"
    if category in (S.FREIGHT, S.STATUS, S.DOCS, S.PAYMENT):
        if missing:
            return "ASK_FOR_INFORMATION"
        return "DRAFT_ACKNOWLEDGEMENT" if category == S.FREIGHT else "VERIFY_INTERNALLY"
    if model_action in {"DRAFT_ACKNOWLEDGEMENT", "ASK_FOR_INFORMATION", "NO_REPLY_NEEDED"}:
        return model_action
    return "ASK_FOR_INFORMATION" if category == S.OTHER else "DRAFT_ACKNOWLEDGEMENT"


# --------------------------------------------------------------------------- workflow summary


def summarize_checks(result: dict) -> list[dict]:
    """The validation step as a short list for the workflow view. status: ok | info | warn | fail."""
    checks: list[dict] = []
    found = [f for f in result["fields"].values() if f["found"]]
    removed = result["removed_unsupported"]
    checks.append({
        "name": "Grounding",
        "status": "warn" if removed else "ok",
        "detail": f"{len(removed)} unsupported value(s) removed" if removed
        else f"{len(found)} extracted value(s), each backed by a quote from the email",
    })

    if result["category"] == S.FREIGHT:
        mode, sub, evidence = result["mode"], result["submode"], result["mode_evidence"]
        label = mode + (f" · {sub}" if sub else "")
        checks.append({
            "name": "Transport mode",
            "status": "info" if mode == "UNKNOWN" else "ok",
            "detail": f"{label} — from “{evidence}”" if evidence
            else f"{label} — no explicit air/ocean wording, so no mode is assumed",
        })

    missing = result["missing_information"]
    required = [m for m in missing if m["reason"] == "required"]
    recommended = [m for m in missing if m["reason"] != "required"]
    checks.append({
        "name": "Missing information",
        "status": "warn" if required else ("info" if recommended else "ok"),
        "detail": f"{len(required)} required and {len(recommended)} recommended detail(s) missing" if missing
        else "Nothing required is missing",
    })

    conflicts, ambiguities = result["conflicts"], result["ambiguities"]
    rule_flags = {"PAST_DATE", "INCOTERM_MODE_MISMATCH"} & set(result["flags"])
    checks.append({
        "name": "Conflicts & rules",
        "status": "warn" if conflicts or rule_flags else ("info" if ambiguities else "ok"),
        "detail": f"{len(conflicts)} conflict(s), {len(ambiguities)} ambiguity(ies)"
        + (f", rule flag: {', '.join(sorted(rule_flags))}" if rule_flags else ""),
    })

    draft = result["draft_reply"]
    if draft["source"] == "ai":
        checks.append({"name": "Draft guard", "status": "ok",
                       "detail": "AI draft passed: no prices, promises, attachments or status claims"})
    elif draft["source"] == "template":
        checks.append({"name": "Draft guard", "status": "warn",
                       "detail": (draft["notes"] or ["AI draft replaced by a template"])[0]})
    else:
        checks.append({"name": "Draft guard", "status": "info",
                       "detail": (draft["notes"] or ["No draft"])[0]})

    injected = "PROMPT_INJECTION" in result["flags"]
    checks.append({
        "name": "Instruction scan",
        "status": "fail" if injected else "ok",
        "detail": "Instructions hidden in the email were ignored" if injected else "No instructions found inside the email",
    })
    return checks


# --------------------------------------------------------------------------- entry point


def build_result(subject: str, body: str, raw: dict, today: date | None = None) -> dict:
    """Turn the model's raw JSON into the validated result shown in the UI."""
    today = today or date.today()
    text = f"{subject}\n{body}".strip()
    category = raw["category"]  # already mapped to a canonical name by the pipeline
    removed: list[str] = []

    fields = _clean_fields(category, raw.get("fields"), text, removed)
    ntext = norm(text)
    ambiguities, clarifications = _read_ambiguities(raw.get("ambiguities"), ntext, removed, fields)
    # A range or an "either/or" number is not one figure — caught by rule even if the AI did not say so.
    for name in NUMERIC_FIELDS:
        item = fields.get(name)
        if not item or not item["found"] or not RANGE_RE.search(item["value"]):
            continue
        if any(c["field"] == name for c in clarifications) or len(clarifications) >= 3:
            continue
        shown = f"{item['value']} {item['unit'] or ''}".strip()
        quote = shown if contains(ntext, norm(shown)) else (item["evidence"] or item["value"])
        ambiguities.append(f"“{quote}” — a range, not one figure")
        clarifications.append({
            "field": name, "quote": quote, "issue": "a range, not one figure",
            "question": f"the confirmed {item['label'].lower()} (you wrote “{quote}”)",
        })
    signals = _read_signals(raw.get("signals"))
    customer_questions = _clean_list(raw.get("customer_questions"))[:3]
    notes_out: list[str] = []
    conflicts = _clean_list(raw.get("conflicts"))
    flags = {str(f).strip().upper() for f in _clean_list(raw.get("flags"))} & S.LLM_FLAGS
    if INJECTION_RE.search(text):
        flags.add("PROMPT_INJECTION")

    mode = submode = mode_evidence = mode_note = None
    if category == S.FREIGHT:
        mode, submode, mode_evidence, mode_conflicts = detect_mode(text, fields)
        conflicts += [c for c in mode_conflicts if c not in conflicts]
        hint = str(raw.get("mode_hint") or "").strip().upper()
        if hint in ("AIR", "OCEAN") and hint != mode:
            mode_note = (
                f"The AI suggested {hint}, but the email has no explicit air/ocean wording, so the mode stays UNKNOWN."
                if mode == "UNKNOWN"
                else f"The AI suggested {hint}; the wording in the email says {mode}, which takes priority."
            )
        _freight_checks(fields, text, mode, ambiguities, conflicts, flags, today, urgent=signals["urgent"])

    others = detect_mixed_intent(text, category)
    if not others:
        flags.discard("MIXED_INTENT")  # the AI over-flags; a second request counts only when the wording shows it
    if others:
        flags.add("MIXED_INTENT")
        ambiguities.append(
            "The email also asks about " + " and ".join(_INTENT_WORD[c] for c in others)
            + " — the main request is handled first."
        )

    # Things the AI noticed in the wording (several shipments, attachments we cannot open)
    extra_asks: list[dict] = []
    if category == S.FREIGHT and signals["multiple_shipments"]:
        flags.add("MULTIPLE_SHIPMENTS")
        ambiguities.append("The email seems to describe more than one shipment.")
        if not any("shipment" in (c["question"] or "").lower() for c in clarifications):  # the AI may have asked already
            extra_asks.append({
                "field": "which_shipment", "reason": "recommended",
                "label": "which shipment you would like us to quote first (the email describes more than one)",
            })
    if signals["references_attachment"] or ATTACHMENT_REF_RE.search(text):
        flags.add("ATTACHMENT_REFERENCED")
        notes_out.append("The email refers to an attachment. This tool reads only the text, so details inside it are not included.")
        extra_asks.append({
            "field": "attachment_details", "reason": "recommended",
            "label": "the key details from the attachment, written in the body of your email (we can only read the text)",
        })

    missing = compute_missing(category, fields, mode, submode, text, signals)
    covered = {m["field"] for m in missing}
    # The AI's questions about unclear points: only for details that WERE given (unanswered fields are already asked)
    for index, clar in enumerate(clarifications):
        target = clar["field"]
        if target in fields and not fields[target]["found"]:
            continue
        if target in covered or (target == "cargo_ready_date" and "cargo_ready_date_exact" in covered):
            continue
        missing.append({
            "field": f"clarify_{target or 'general'}_{index}", "label": clar["question"],
            "reason": "recommended", "quote": clar["quote"],
        })
    missing += [m for m in extra_asks if m["field"] not in covered]

    action = _decide_action(category, missing, flags, raw.get("recommended_action"))
    name = sender_name(body)

    # --- the draft
    draft_subject, draft_body = _read_draft(raw.get("draft_reply"))
    notes: list[str] = []
    if action == "FLAG_FOR_REVIEW":
        draft = {"subject": "", "body": "", "source": "none", "notes": ["Flagged for human review — no reply was drafted."]}
    elif action == "NO_REPLY_NEEDED" and not draft_body:
        draft = {"subject": "", "body": "", "source": "none", "notes": ["The model judged that no reply is needed."]}
    else:
        problems = _draft_problems(draft_body, missing, category) if draft_body else []
        if not draft_body or problems:
            if problems and any(not p.startswith("it did not ask") for p in problems):
                flags.add("DRAFT_CONTAINS_UNSUPPORTED_CLAIM")
            notes = (
                ["The AI draft was empty, so a standard template is shown."]
                if not draft_body
                else ["The AI draft was replaced by a safe template because " + "; ".join(problems) + "."]
            )
            draft_body = _template_body(category, fields, missing, text, flags)
            source = "template"
        else:
            source = "ai"
            extra = [m for m in missing if m["reason"] == "recommended" and not _asks_for(draft_body, m["field"], m)]
            appended = _append_asks(draft_body, extra) if extra else None
            if appended:
                draft_body = appended
                notes.append(
                    "Validation added these recommended questions to the AI draft: "
                    + ", ".join(_ask_name(category, m) for m in extra)
                    + "."
                )
            # The customer asked about transit time: the reply must not ignore it (and must not state one).
            if category == S.FREIGHT and re.search(r"\btransit\b", text, re.I) and not re.search(r"\btransit\b", draft_body, re.I):
                draft_body = _insert_before_signoff(
                    draft_body,
                    "We have noted your request for the estimated transit time and will address it together with the quotation.",
                )
                notes.append("Added a line about the transit time the customer asked for.")
        # Direct questions from the customer must not be ignored (and are never answered with facts we lack)
        unanswered = _unanswered_questions(customer_questions, draft_body)
        if unanswered:
            draft_body = _insert_before_signoff(
                draft_body,
                "We have also noted your question" + ("s" if len(unanswered) > 1 else "") + ": "
                + "; ".join(f"“{q}”" for q in unanswered) + ".",
            )
            notes.append("Added a line acknowledging the customer's own questions.")
        draft = {
            "subject": draft_subject or (f"Re: {subject}" if subject else "Re: your email"),
            "body": _personalize(draft_body, name),
            "source": source,
            "notes": notes,
        }

    return {
        "category": category,
        "sender_name": name,
        "category_confidence": raw.get("category_confidence") if raw.get("category_confidence") in ("high", "medium", "low") else "medium",
        "category_reason": clean_str(raw.get("category_reason"), 220),
        "mode": mode,
        "submode": submode,
        "mode_evidence": mode_evidence,
        "mode_note": mode_note,
        "fields": fields,
        "missing_information": missing,
        "ambiguities": ambiguities[:8],
        "clarifications": clarifications,
        "customer_questions": customer_questions,
        "signals": signals,
        "notes": notes_out,
        "conflicts": conflicts[:8],
        "removed_unsupported": removed,
        "information_complete": not any(m["reason"] == "required" for m in missing),
        "information_verified": False,
        "action_available": False,
        "verification_note": (
            "This prototype has no tracking, pricing, accounting or document system connected, so nothing "
            "in the reply can be verified or actioned — drafts only acknowledge or ask for information."
        ),
        "recommended_action": action,
        "human_review_required": True,
        "flags": sorted(flags),
        "draft_reply": draft,
    }
