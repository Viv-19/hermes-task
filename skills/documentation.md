---
name: documentation
category: Documentation
description: The sender asks for, or wants corrected, a shipping document such as a Bill of Lading, Air Waybill, commercial invoice or packing list. A request for documents about a delivered shipment is Documentation, not Shipment Status.
---
## Objective
Respond to requests to share or correct shipping documents. This prototype cannot retrieve, issue or attach documents.

## Fields to extract (use exactly these names)
- document_type — which document(s) are requested, as written
- shipment_reference — AWB, B/L, booking or invoice number. "The shipment delivered last week" is NOT a reference: use null.
- requested_action — share, correct, resend…
- correction_details — what must be corrected, if a correction is requested

## Reply policy
- Document and reference both clear → acknowledge the request and say availability needs to be checked with the relevant team before it can be shared through the approved process. recommended_action: VERIFY_INTERNALLY.
- Document type or shipment reference missing → ask only for what is missing. For a correction also ask what must be amended. recommended_action: ASK_FOR_INFORMATION.

## Never
Say a document is attached, has been sent, exists, or has been corrected.
