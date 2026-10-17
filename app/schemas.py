"""Fixed vocabulary shared by the prompt, the validators and the UI."""
from pydantic import BaseModel

FREIGHT = "Freight Quotation Enquiry"
STATUS = "Shipment Status"
DOCS = "Documentation"
PAYMENT = "Payment"
GENERAL = "General Business Email"
OTHER = "Other"

CATEGORIES = [FREIGHT, STATUS, DOCS, PAYMENT, GENERAL, OTHER]

MODES = ["AIR", "OCEAN", "UNKNOWN"]

ACTIONS = [
    "DRAFT_ACKNOWLEDGEMENT",
    "ASK_FOR_INFORMATION",
    "VERIFY_INTERNALLY",
    "FLAG_FOR_REVIEW",
    "NO_REPLY_NEEDED",
]

# Flags the model may raise itself, and flags only the Python checks raise.
LLM_FLAGS = {"SUSPICIOUS", "PROMPT_INJECTION", "MIXED_INTENT"}
PYTHON_FLAGS = {"INCOTERM_MODE_MISMATCH", "PAST_DATE", "DRAFT_CONTAINS_UNSUPPORTED_CLAIM"}

# category -> [(field name, label shown in the UI, phrase used when asking the customer for it)]
FIELDS = {
    FREIGHT: [
        ("origin", "Origin", "origin (city / port / airport)"),
        ("destination", "Destination", "destination (city / port / airport)"),
        ("commodity", "Commodity", "description of the cargo (commodity)"),
        ("gross_weight", "Gross weight", "total gross weight and unit (kg or lb)"),
        ("pieces", "Pieces", "number of pieces / packages"),
        ("dimensions", "Dimensions", "package dimensions (L × W × H per piece)"),
        ("cbm", "Volume (CBM)", "total volume in CBM"),
        ("container", "Container", "container type and quantity (e.g. 1 × 40HC)"),
        ("incoterm", "Incoterm", "Incoterm (e.g. EXW, FOB, CIF)"),
        ("cargo_ready_date", "Cargo-ready date", "cargo-ready date"),
        ("delivery_deadline", "Delivery deadline", "required delivery date / timeline"),
        (
            "special_handling",
            "Special handling",
            "special handling needs (dangerous-goods status, temperature control)",
        ),
    ],
    STATUS: [
        ("shipment_reference", "Shipment reference", "AWB, Bill of Lading or booking number"),
        ("question", "Question asked", "what you would like to know about the shipment"),
    ],
    DOCS: [
        (
            "document_type",
            "Document(s) requested",
            "which document(s) you need (e.g. Bill of Lading, invoice, packing list)",
        ),
        (
            "shipment_reference",
            "Shipment reference",
            "the shipment reference (AWB / B/L / booking / invoice number)",
        ),
        ("requested_action", "Requested action", "whether the document should be shared or corrected"),
        ("correction_details", "Correction details", "the details that need to be corrected"),
    ],
    PAYMENT: [
        ("invoice_number", "Invoice number", "the invoice number"),
        ("transaction_reference", "Transaction reference", "the payment / transaction reference"),
        ("amount", "Amount", "the amount and currency"),
        ("payment_date", "Payment date", "the payment date"),
        ("request_type", "Type of request", "what you need regarding the payment"),
    ],
    GENERAL: [
        ("topic", "Topic", "the topic you would like to discuss"),
        ("requested_action", "Requested action", "what you would like us to do"),
    ],
    OTHER: [
        ("topic", "Topic", "more detail about your request"),
    ],
}

# "Any of these" requirement groups and synthetic requirements that are not plain fields.
GROUP_DIMS_OR_CBM = ("dimensions", "cbm")
GROUP_INVOICE_OR_TXN = ("invoice_number", "transaction_reference")

GROUP_KEY = {
    GROUP_DIMS_OR_CBM: "dimensions_or_cbm",
    GROUP_INVOICE_OR_TXN: "invoice_or_transaction",
}
GROUP_ASK = {
    GROUP_DIMS_OR_CBM: "package dimensions (L × W × H) or the total volume in CBM",
    GROUP_INVOICE_OR_TXN: "the invoice number or the payment / transaction reference",
}
EXTRA_ASK = {
    "mode": "preferred mode of transport (air freight or ocean freight)",
    "shipment_type": "whether this is a full container (FCL) or a part-load (LCL) shipment",
    "container_type": "container type / size (e.g. 20GP, 40HC)",
}
SHORT_LABEL = {
    "dimensions_or_cbm": "dimensions or CBM",
    "invoice_or_transaction": "invoice / transaction reference",
    "mode": "transport mode",
    "shipment_type": "FCL or LCL",
    "container_type": "container type",
    "cargo_ready_date_exact": "exact ready date",
}


def canonical_category(value) -> str | None:
    """Map whatever the model wrote to one of the six exact category names."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    for c in CATEGORIES:
        if v == c.lower():
            return c
    if "freight" in v or "quot" in v or "rate" in v:
        return FREIGHT
    if "status" in v or "track" in v:
        return STATUS
    if "document" in v:
        return DOCS
    if "payment" in v or "invoice" in v:
        return PAYMENT
    if "general" in v:
        return GENERAL
    if "other" in v:
        return OTHER
    return None


def field_ask(category: str, name: str) -> str:
    for n, _label, ask in FIELDS[category]:
        if n == name:
            return ask
    return name


def field_label(category: str, name: str) -> str:
    if name in SHORT_LABEL:
        return SHORT_LABEL[name]
    for n, label, _ask in FIELDS.get(category, []):
        if n == name:
            return label.lower()
    return name


class AnalyzeRequest(BaseModel):
    subject: str = ""
    body: str = ""
    fresh: bool = False  # True = skip the in-memory cache
