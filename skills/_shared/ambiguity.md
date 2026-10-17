# How to read unclear emails (applies to every skill)

Customers write quickly and loosely. Your job is to UNDERSTAND them, not to guess for them.
When something is unclear: keep the customer's own words, say what is unclear, and ask. Never fill the gap yourself.

1. **Vague dates** ("end of this month", "next week", "soon", "ASAP", "as soon as reasonably possible"): keep the words as the value, never invent a date, add an ambiguity, set `signals.vague_dates` (or `signals.urgent` for urgency), and ask for the exact date.
2. **Ranges and estimates** ("100-120 kg", "around 5 pallets", "approx."): keep the range as written, add an ambiguity, ask for the confirmed figure.
3. **Two different values for the same thing** ("100 kg" in one place, "gross weight 120 kg" in another): put it under `conflicts` and do not choose.
4. **Vague quantities** ("some boxes", "a few pallets", "a couple of cartons"): there is no number, so the value is null. Add an ambiguity.
5. **Things you cannot see** ("same terms as last time", "as discussed", "as per our call", "see attached"): never fill these in. Add an ambiguity and a question. For attachments also set `signals.references_attachment`.
6. **Alternatives** ("air or sea, whichever is cheaper"): do not choose. Both are options, so the mode stays unknown. Ask which one, or say we can quote both.
7. **Unclear units** ("20 feet", "10 tons", "cft"): keep them as written. If the unit changes the meaning (ton or tonne, kg or lb), ask.
8. **More than one shipment** (different routes, cargo or dates in one email): set `signals.multiple_shipments`, handle the first or main one, and ask which one to quote first.
9. **Doubt and negation** ("no dangerous goods" is an answer; "maybe", "not sure yet", "TBD", "to be confirmed" are NOT answers): treat doubt as unanswered, add an ambiguity, and ask.
10. **Questions the customer asks** (transit time, best rate, available options, "can you do it by Friday?"): list each under `customer_questions`. Never answer with facts you do not have. The reply says it will be addressed.
11. **Be precise and brief:** at most 4 ambiguities, only real ones. Write each `question` as a short phrase that completes "could you please confirm ..." and include the customer's own words in quotation marks, so they can see you read their email.
12. **Never guess to be helpful.** An honest "we need to confirm this" is always better than a confident wrong detail.
