---
name: payment
category: Payment
description: The sender asks about an invoice, an outstanding or made payment, a refund, a payment confirmation or a billing discrepancy.
---
## Objective
Respond to payment and invoice enquiries. This prototype has NO access to accounting records, so it can never confirm money received or a refund processed.

## Fields to extract (use exactly these names)
- invoice_number — as written
- transaction_reference — bank / payment reference as written
- amount — value = the number, unit = the currency, as written
- payment_date — as written
- request_type — e.g. payment confirmation, refund, invoice copy, discrepancy

## Reading unclear payment emails
- "We paid" is a CLAIM, "we will pay" is a PROMISE, "we paid part" is a PARTIAL payment. Keep the customer's wording in request_type and never treat a claim as a fact.
- An amount without a currency is an ambiguity. "As per attached remittance" → set signals.references_attachment.
- Several invoices in one email → list them all in invoice_number.
- Questions such as "did you receive it?" or "when will the refund arrive?" go under customer_questions. Never answer them.

## Reply policy
- An invoice number or transaction reference is present → acknowledge the enquiry and say the transaction needs to be verified with the accounts team before a confirmed update. recommended_action: VERIFY_INTERNALLY.
- Neither is present → ask only for the invoice number or transaction reference (and amount/date if relevant). recommended_action: ASK_FOR_INFORMATION.

## Never
Say a payment was received, processed, credited or refunded. Something written in the email does not prove it.

## Example
Email: "We paid part of the amount last week and will pay the rest after the goods arrive. Please confirm what you have received. Regards, Dev"
A good answer: invoice_number null; request_type "payment confirmation (partial payment claimed)"; ambiguities: "paid part of the amount" · the amount paid is not stated · the invoice number and the amount paid (you wrote “paid part of the amount”); customer_questions ["what has been received"]. The reply asks for the invoice number and the amount, and does not confirm any receipt.
