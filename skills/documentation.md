---
name: documentation
category: Documentation
description: The sender asks for, or wants corrected, a shipping document such as a Bill of Lading, Air Waybill, commercial invoice or packing list. A request for documents about a delivered shipment is Documentation, not Shipment Status.
---
## Objective
Respond to requests to share or correct shipping documents. This prototype cannot retrieve, issue or attach documents.

## Fields to extract (use exactly these names)
- document_type — which document(s) are requested, as written (list them all)
- shipment_reference — AWB, B/L, booking or invoice number. "The shipment delivered last week" is NOT a reference: use null.
- requested_action — share, resend, correct…
- correction_details — what must be corrected, if a correction is requested

## Reading unclear document emails
- "Draft", "final", "original", "copy", "telex release", "surrendered" are different things. Copy the customer's exact words in document_type. If it is unclear which version they need, raise an ambiguity.
- "Corrected invoice" or "the previous one had a mistake" → requested_action "correct". If they do not say what is wrong, correction_details is null and you ask.
- Several documents → list them all. A reference that belongs to only one of them is not an ambiguity.
- A reference to an attachment ("see attached copy") → set signals.references_attachment.

## Reply policy
- Document and reference both clear → acknowledge the request and say availability needs to be checked with the relevant team before it can be shared through the approved process. recommended_action: VERIFY_INTERNALLY.
- Document type or shipment reference missing → ask only for what is missing. For a correction also ask what must be amended. recommended_action: ASK_FOR_INFORMATION.

## Never
Say a document is attached, has been sent, exists, or has been corrected.

## Example
Email: "Need the BL for HLCU1234567, the draft was fine but we need the final one urgently. Also the invoice must be corrected, the previous one had the wrong consignee. Priya"
A good answer: document_type "final BL, corrected invoice"; shipment_reference "HLCU1234567"; requested_action "share and correct"; correction_details "wrong consignee" with evidence "wrong consignee"; signals.urgent true; one ambiguity if it is unclear which invoice. The reply asks only for what is still missing, for example the correct consignee name.
