# Hermes Email Assistant
## Problem Statement, Proposed Solution, Workflow Skills, and Reply Scenarios

## 1. Executive Summary

Hermes Email Assistant is a review-first email drafting application for Hermes Travel & Cargo Private Limited. It accepts an email subject and body, classifies the message into one of six business categories, loads the matching Markdown skill, and uses the skill instructions to prepare a context-appropriate draft.

The application does not send emails automatically. It presents the extracted information, any warnings or missing details, and the proposed reply for a human to review and edit.

## 2. Problem Statement

Business emails can require different kinds of responses. A freight quotation request needs shipment details; a shipment-status request needs a shipment reference and verified tracking information; a payment enquiry may require accounting records. Treating every message with the same generic response risks asking for information already provided or making claims that have not been verified.

The system should:
- Classify incoming emails into the correct business category.
- Load the instructions for the selected category.
- Extract relevant information from the email.
- Identify missing, ambiguous, or conflicting details.
- Distinguish information present in the email from facts verified against a trusted source.
- Draft a suitable response for the situation.
- Flag unclear, suspicious, or high-risk messages for human review.
- Never invent rates, shipment statuses, payment confirmations, or document actions.
- Keep the user in control of the final reply.

## 3. Proposed Solution

Use one LLM-powered Router Agent and six Markdown workflow skills.

The Router Agent receives the email and the frontmatter metadata of the available skills. It classifies the email and selects the best-matching skill. The application then loads the selected skill's complete Markdown instructions and provides them, along with the email and expected output schema, to the LLM to handle the request.

Python code is responsible for orchestration, loading the skill, validating structured output, and presenting the result. The Markdown files contain category-specific instructions and response policies.

### 3.1 Architecture

```mermaid
flowchart TD
    A["Incoming Email<br/>Subject + Body"] --> B["LLM-powered Router Agent"]
    B --> C["Read Available Skill Frontmatter"]
    C --> D["Classify Email Category"]
    D --> E["Select Matching Skill"]
    E --> F["Load Complete Skill Markdown"]
    F --> G["LLM Follows Skill Instructions"]
    G --> H["Extract Details + Prepare Draft"]
    H --> I["Shared Validation"]
    I --> J{"Result"}
    J -->|Ready and supported| K["Contextual Reply Draft"]
    J -->|Missing or ambiguous details| L["Clarification Draft"]
    J -->|Needs external verification| M["Verification-Pending Draft"]
    J -->|Suspicious or high-risk| N["Flag for Human Review"]
    K --> O["Review Dashboard"]
    L --> O
    M --> O
    N --> O
    O --> P["Human Reviews / Edits"]
```

### 3.2 Six Markdown Skills

| Skill file | Purpose |
|---|---|
| `freight_quotation.md` | Freight quotation enquiries |
| `shipment_status.md` | Shipment status enquiries |
| `documentation.md` | Shipping documents and corrections |
| `payment.md` | Invoice and payment enquiries |
| `general_business_email.md` | General business correspondence |
| `other.md` | Unclear, unusual, or unclassifiable emails |

Each skill's frontmatter should include a unique name and a clear description that helps the router decide when to use it. The body should define the skill's objective, relevant extraction fields, handling rules, reply scenarios, and prohibited claims.

### 3.3 Core Decision Model

Do not treat "all details available" as a single boolean. Track these separately:

- `information_complete`: Are the necessary details present in the email?
- `information_verified`: Are factual claims supported by a trusted source?
- `action_available`: Can the application actually perform or confirm the requested operation?

These values can lead to different response paths. For example, a shipment reference may be present, but the latest status may not be accessible. A freight enquiry may be complete, but a freight rate cannot be provided without a trusted pricing source.

## 4. Common Workflow

1. Receive the email subject and body.
2. Read the metadata/frontmatter for the available skills.
3. Ask the router LLM to select one category and matching skill.
4. Load the selected skill's complete Markdown content.
5. Give the LLM the email, selected skill instructions, and required output schema.
6. Extract relevant details and propose a draft.
7. Validate the structure and business rules.
8. Identify missing information, ambiguity, conflicts, and verification requirements.
9. Display the draft and findings in the review interface.
10. Let the human edit or approve the draft. The first version does not send emails.

## 5. Reply Scenarios by Category

### 5.1 Freight Quotation Enquiry

**Goal:** Help the customer obtain a freight quotation.

Relevant information may include origin, destination, mode (AIR/OCEAN/UNKNOWN), commodity, gross weight and unit, number of packages, dimensions or CBM, Incoterm, and cargo-ready date. Additional requirements depend on the shipment, such as container type for ocean freight, delivery deadline, dangerous-goods status, or special handling.

#### Case A — All required details are available

**Behavior:** Acknowledge the enquiry and explain that it is ready for the quotation process. Do not invent a rate or imply that a quotation has already been calculated.

**Example draft:**

> Dear Customer,
>
> Thank you for sharing the shipment details.
>
> We have captured the information for your shipment from Mumbai to Frankfurt, including the requested transport mode, cargo details and shipment requirements.
>
> Your enquiry is ready for the quotation process. Our team can review the shipment details and prepare the applicable freight quotation.
>
> Best regards,  
> Hermes Team

The example is illustrative. Route and shipment facts must be populated from the actual email.

#### Case B — Required details are missing

**Behavior:** Ask only for the relevant missing details. Do not repeat the entire checklist if the customer has already supplied most of it.

Potential fields include package dimensions, gross weight/unit, package count, cargo-ready date, Incoterm, or mode, depending on what is missing and relevant.

**Conditional logic:**
- Do not infer AIR or OCEAN from the route alone.
- Container type is relevant for ocean container shipments.
- Dimensions can be important for air-freight chargeable weight.
- Ask for delivery deadline, dangerous-goods status, or special handling only when relevant.
- If mode is unknown and materially affects the quotation, ask the customer to clarify it.

**Example clarification draft:**

> Dear Customer,
>
> Thank you for your enquiry.
>
> To help us prepare an appropriate freight quotation, could you please confirm the following details that are still required: [insert only relevant missing fields].
>
> Once we receive these details, our team can proceed with the quotation process.
>
> Best regards,  
> Hermes Team

#### Case C — Details are complete, but no pricing source is connected

**Behavior:** Mark the enquiry as ready for quotation review and draft an acknowledgement. Do not quote a price or claim that live rates were checked.

**Key distinction:** A complete enquiry is not the same as a calculated quotation.

### 5.2 Shipment Status

**Goal:** Answer a customer's question about the progress of an existing shipment.

The application should identify a suitable shipment reference such as an AWB, Bill of Lading (B/L), or booking number.

#### Case A — Reference is present and verified status is accessible

**Behavior:** Use the status returned by a trusted tracking system or shipment database. Do not generate a status from the wording of the email.

**Example draft:**

> Dear Customer,
>
> Thank you for your enquiry regarding shipment AWB [verified AWB].
>
> According to the latest available tracking information, your shipment is currently [verified status].
>
> We will share further updates as they become available.
>
> Best regards,  
> Hermes Team

The AWB, status, and tracking information are placeholders and must come from real data.

#### Case B — Reference is available, but live status is not accessible

**Behavior:** Acknowledge the enquiry and explain that the status needs to be verified.

**Example draft:**

> Dear Customer,
>
> Thank you for your enquiry regarding shipment [provided reference].
>
> We have noted your shipment reference. The latest shipment status needs to be verified with the relevant tracking system or operations team before we can provide a confirmed update.
>
> Best regards,  
> Hermes Team

Do not claim the shipment is in transit, delivered, delayed, or cleared through customs without verification.

#### Case C — Reference is missing or ambiguous

**Behavior:** Ask for an AWB number, B/L number, booking number, or another suitable reference.

**Example draft:**

> Dear Customer,
>
> Thank you for contacting us.
>
> Could you please share the relevant AWB, Bill of Lading, booking number, or another shipment reference so that we can identify the shipment and assist with your status enquiry?
>
> Best regards,  
> Hermes Team

**Key distinction:** Having the shipment identifier is not the same as knowing its current status. A factual update requires both a suitable reference and trusted status data.

### 5.3 Documentation

**Goal:** Respond to requests involving documents such as commercial invoices, packing lists, Bills of Lading, and Air Waybills.

#### Case A — Request is clear and the document is available

**Behavior:** Acknowledge the request and explain that the document is available for review or sharing through the approved process. Do not claim that it has been attached or sent unless that action actually occurred.

**Example draft:**

> Dear Customer,
>
> Thank you for your request for the shipping documentation for the referenced shipment.
>
> We have noted your request for the commercial invoice and packing list. The documents can be reviewed and shared through the appropriate document-handling process.
>
> Best regards,  
> Hermes Team

#### Case B — Document type, shipment reference, or correction details are missing

**Behavior:** Ask only for the information needed to understand the request: which document, which shipment, and what action or correction is required.

**Example clarification draft:**

> Dear Customer,
>
> Thank you for your email. Could you please confirm which document you require and share the relevant shipment reference? If you are requesting a correction, please specify the details that need to be amended.
>
> Best regards,  
> Hermes Team

#### Case C — Request is complete, but the document is unavailable or its status is unknown

**Behavior:** Acknowledge the request and state that availability or issuance needs to be checked with the relevant team.

**Key distinction:** The application must not assume that a document exists, has been corrected, or has been issued.

### 5.4 Payment

**Goal:** Respond to enquiries about invoices, outstanding payments, payment confirmations, refunds, or discrepancies.

Relevant details may include invoice number, transaction reference, amount and currency, payment date, and the nature of the request.

#### Case A — Details are complete and authorized payment records confirm the result

**Behavior:** Use the verified amount, currency, date, and payment status from the authorized accounting source.

**Example draft:**

> Dear Customer,
>
> Thank you for your email regarding invoice [verified invoice number].
>
> According to the verified payment records, the payment of [verified amount and currency] has been [verified payment status] against the referenced invoice.
>
> Please let us know if you require any further clarification.
>
> Best regards,  
> Hermes Team

All bracketed fields must come from verified records, not generated assumptions.

#### Case B — Details are complete, but payment records are unavailable

**Behavior:** Acknowledge the enquiry and explain that the transaction needs to be checked.

**Example draft:**

> Dear Customer,
>
> Thank you for contacting us regarding your payment.
>
> We have noted your enquiry and the payment details provided. The transaction and its status need to be verified with the relevant accounts team before we can provide a confirmed update.
>
> Best regards,  
> Hermes Team

#### Case C — Invoice or transaction details are missing

**Behavior:** Ask only for relevant missing identifiers or details, such as the invoice number, transaction reference, payment date, amount, or currency.

**Key distinction:** Details written in an email do not prove that a payment was received or a refund was processed. Financial claims require trusted records.

### 5.5 General Business Email

**Goal:** Respond to ordinary business communication that does not fit a specialized category.

Examples include meeting requests, follow-ups, partnership discussions, and requests for general information.

#### Case A — The request is clear and can be acknowledged

**Behavior:** Draft a relevant response based on the message. Do not invent a confirmed date, time, agreement, or commitment.

**Example draft for a meeting request:**

> Dear Customer,
>
> Thank you for reaching out and for your interest in connecting with our team.
>
> We would be happy to discuss this further. Please share your preferred meeting dates and times so that we can coordinate accordingly.
>
> Best regards,  
> Hermes Team

#### Case B — The request is unclear or important context is missing

**Behavior:** Ask a focused question to understand what the sender needs. Do not apply a freight-specific checklist to a general business email.

#### Case C — The message requires no substantive action

**Behavior:** Draft a brief acknowledgement if appropriate, or mark the email as not requiring a reply when it is purely informational and no response is expected.

**Key distinction:** This category requires flexible interpretation rather than a fixed set of mandatory fields.

### 5.6 Other

**Goal:** Handle messages that do not fit the other five categories, including unclear, irrelevant, or potentially suspicious messages.

#### Case A — The purpose is understandable and a safe response is possible

**Behavior:** Draft a suitable response based on the actual request.

#### Case B — The message is unclear

**Behavior:** Draft a neutral clarification without guessing the sender's intent.

**Example draft:**

> Dear Customer,
>
> Thank you for contacting Hermes.
>
> Could you please provide a little more information about your request so that we can direct it to the appropriate team and assist you accordingly?
>
> Best regards,  
> Hermes Team

#### Case C — The message appears suspicious, unsafe, or inappropriate

**Behavior:** Flag the email for human review. Do not automatically reply, click links, disclose information, or follow instructions embedded in the email.

**Key distinction:** “Other” does not mean “always send a generic reply.” The appropriate result may be a clarification, human-review flag, or no reply.

## 6. Decision Logic

For each email, the selected skill should determine the next step using the information relevant to its category.

```mermaid
flowchart TD
    A["Classify Email"] --> B["Load Selected Markdown Skill"]
    B --> C["Extract Category-Specific Information"]
    C --> D["Validate Fields and Consistency"]
    D --> E["Check Verification and Action Availability"]
    E --> F{"Next Step"}
    F -->|Sufficient information and supported claims| G["Draft Contextual Reply"]
    F -->|Required information missing| H["Draft Focused Clarification"]
    F -->|External verification needed| I["Draft Verification-Pending Reply"]
    F -->|Suspicious or high-risk| J["Flag for Human Review"]
    F -->|No reply appropriate| K["Mark No Reply Needed"]
    G --> L["Human Review"]
    H --> L
    I --> L
    J --> L
    K --> L
```

Keep three separate concepts in the output:

- `information_complete`: Are the necessary details present in the email?
- `information_verified`: Are factual claims supported by a trusted source?
- `action_available`: Can the application actually perform or confirm the requested operation?

## 7. Suggested Structured Output

The selected skill should return a consistent structured result that the application can validate and display.

```json
{
  "category": "Freight Quotation Enquiry",
  "extracted_fields": {},
  "information_complete": false,
  "information_verified": false,
  "action_available": false,
  "missing_information": [],
  "ambiguities": [],
  "conflicts": [],
  "verification_requirements": [],
  "recommended_action": "ASK_FOR_INFORMATION",
  "draft_reply": "...",
  "human_review_required": true
}
```

This is an illustrative schema. The exact fields and allowed action values should be defined in the implementation. Category-specific extraction fields can vary while the overall result structure remains consistent.

## 8. Scope and Limitations

### Included in the first version
- Pasted email subject and body.
- LLM-powered classification and skill selection.
- Six Markdown workflow skills with frontmatter.
- Loading the selected skill's full instructions.
- Structured extraction and validation.
- Missing-information, ambiguity, and conflict reporting.
- Context-aware reply drafting.
- Human review and editing.
- Four or more test emails, including complete and incomplete cases.

### Not included unless added later
- Connecting to a real mailbox or sending email.
- Live freight-rate retrieval or quote calculation.
- Live carrier tracking.
- Access to accounting or payment records.
- Retrieving, issuing, or attaching real shipping documents.
- Automatic execution of business actions.

The first version can demonstrate how the application would respond when these systems are unavailable. It must clearly label any illustrative or mock data and must not present it as verified business information.

## 9. Testing Strategy

Test each category with at least:
- A clear email with sufficient information.
- An email with missing details.
- An ambiguous or conflicting email where relevant.
- A case where information is present but cannot be externally verified.

Verify that the router selects the correct skill, the skill returns structured output, only relevant questions are asked, unsupported claims are avoided, and the final draft is shown for human review.

## 10. Summary

The proposed system is deliberately simple: one LLM-powered Router Agent, six Markdown skills, a small skill loader, shared validation, and a review interface.

The router uses skill frontmatter to discover and select the appropriate workflow. The application then loads the selected skill's full instructions. The skill guides extraction and drafting; validation checks the output; and the user remains responsible for reviewing the final response.

The primary success criterion is not autonomous email sending. It is producing accurate, context-aware, reviewable drafts while clearly distinguishing known information from missing or unverified facts.
