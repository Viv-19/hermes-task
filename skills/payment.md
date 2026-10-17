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

## Reply policy
- An invoice number or transaction reference is present → acknowledge the enquiry and say the transaction needs to be verified with the accounts team before a confirmed update. recommended_action: VERIFY_INTERNALLY.
- Neither is present → ask only for the invoice number or transaction reference (and amount/date if relevant). recommended_action: ASK_FOR_INFORMATION.

## Never
Say a payment was received, processed, credited or refunded. Something written in the email does not prove it.
