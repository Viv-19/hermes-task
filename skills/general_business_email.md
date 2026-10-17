---
name: general_business_email
category: General Business Email
description: Ordinary business correspondence — meeting requests, introductions, follow-ups, partnership talks, general information requests. Not a freight quote, shipment status, document or payment matter.
---
## Objective
Write a short, relevant, polite reply. There is no fixed checklist for this category.

## Fields to extract (use exactly these names)
- topic — what the email is about, in a few words
- requested_action — what the sender wants from Hermes

## Reading unclear general emails
- "Next Tuesday", "tomorrow", "this week" are relative: never turn them into a confirmed date or time.
- Several requests in one email → handle the main one and list the others as customer_questions.
- If the email is really about a quotation, shipment, document or payment, it belongs to another category — the router decides that, not you.

## Reply policy
- Clear request → acknowledge it. For a meeting request ask for preferred dates and times; do NOT confirm a date, time, agreement or commitment. recommended_action: DRAFT_ACKNOWLEDGEMENT.
- Unclear request → ask one focused question. recommended_action: ASK_FOR_INFORMATION.
- Purely informational, no response expected → recommended_action: NO_REPLY_NEEDED (draft may be empty).

## Never
Apply a freight checklist to this category. Invent a meeting time or promise anything.

## Example
Email: "Hello, we would like to discuss a possible partnership. Are you free next Tuesday afternoon? Also, do you handle project cargo? Regards, Kavita"
A good answer: topic "partnership discussion"; requested_action "meeting next Tuesday afternoon"; customer_questions ["whether Hermes handles project cargo"]; the reply thanks Kavita, asks for preferred times, and does not confirm Tuesday.
