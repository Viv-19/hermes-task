---
name: shipment_status
category: Shipment Status
description: The sender asks where an existing shipment is, whether it has arrived, or about delays. NOT for new rate requests, documents or payments.
---
## Objective
Answer a customer's question about the progress of an existing shipment. This prototype has NO access to tracking data, so you can never state a status.

## Fields to extract (use exactly these names)
- shipment_reference — AWB, Bill of Lading, booking or container number exactly as written. If there are several, list them all separated by commas.
- question — what the sender wants to know, in a few words

## Reading unclear status emails
- A reference can be an AWB (often written 176-12345675), a Bill of Lading, a booking number or a container number (4 letters + 7 digits). Copy it exactly as written.
- "My shipment", "the cargo", "the container from last week" with no reference → shipment_reference is null; ask for one.
- Several references → keep them all. Add an ambiguity only if it is unclear which one a question is about.
- Questions such as "is it delayed?", "when will it arrive?", "has it cleared customs?" go under customer_questions. Never answer them.

## Reply policy
- Reference present → thank them, repeat the reference, and say the latest status needs to be verified with the tracking system or operations team before a confirmed update can be given. recommended_action: VERIFY_INTERNALLY.
- Reference missing or unclear → ask for the AWB, B/L, booking number or another reference. recommended_action: ASK_FOR_INFORMATION.

## Never
Say a shipment is in transit, delayed, delivered, on schedule or cleared. Give an arrival date.

## Example
Email: "Hi, where are my shipments AWB 176-1111111 and container MSKU1234567? Is anything delayed? Thanks, Arun"
A good answer: shipment_reference "AWB 176-1111111, MSKU1234567"; customer_questions ["where the shipments are", "whether anything is delayed"]; recommended_action VERIFY_INTERNALLY; the reply repeats both references and says the status needs to be verified. It states nothing about delays.
