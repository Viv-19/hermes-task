# Test results

The four assessment emails, run through the live workflow (router agent, skill agent, Python validation) on 2026-10-17.
Everything below is the app's real output. Nothing was edited by hand.

## Test 1 · AIR enquiry

**Subject:** Air freight rate request – Mumbai to Frankfurt

> Please quote air freight from Mumbai to Frankfurt for 125 kg general cargo, packed in 5 cartons. Cargo will be ready on 22 October. Please advise the transit time.

**Expected:** Freight Quotation Enquiry · AIR · origin, destination, 125 kg, 5 cartons, general cargo, ready date · identify missing details

**Result:** Freight Quotation Enquiry (high confidence) · mode **AIR**, from “Air freight”

| Extracted field | Value | Quote from the email |
|---|---|---|
| Origin | Mumbai | “from Mumbai” |
| Destination | Frankfurt | “to Frankfurt” |
| Commodity | general cargo | “125 kg general cargo” |
| Gross weight | 125 kg | “125 kg general cargo” |
| Pieces | 5 cartons | “packed in 5 cartons” |
| Cargo-ready date | 22 October | “Cargo will be ready on 22 October” |

**Missing:** package dimensions (L × W × H per piece), Incoterm (e.g. EXW, FOB, CIF)

**Draft reply** (AI draft, passed all checks):

```
Dear Customer,

Thank you for your enquiry regarding air freight from Mumbai to Frankfurt for 125 kg general cargo in 5 cartons, ready on 22 October.

To help us proceed, could you please confirm:
- the dimensions of each carton (you wrote "packed in 5 cartons")
- the Incoterm (e.g. EXW, FOB, CIF)

We will advise the transit time once the quotation is prepared.

Best regards,
Hermes Team
```

*Models: router nemotron-3-super-120b-a12b (paid), skill agent nemotron-3-super-120b-a12b (paid). Total 20.6 s.*

## Test 2 · OCEAN enquiry

**Subject:** FCL shipment – Nhava Sheva to Hamburg

> Kindly quote one 40HC container from Nhava Sheva to Hamburg. Gross cargo weight is 18,500 kg. Incoterm: FOB.

**Expected:** Freight Quotation Enquiry · OCEAN · origin, destination, FCL, 40HC, weight, FOB · flag other missing details

**Result:** Freight Quotation Enquiry (high confidence) · mode **OCEAN (FCL)**, from “FCL”

| Extracted field | Value | Quote from the email |
|---|---|---|
| Origin | Nhava Sheva | “from Nhava Sheva” |
| Destination | Hamburg | “to Hamburg” |
| Gross weight | 18,500 kg | “Gross cargo weight is 18,500 kg” |
| Container | 1 x 40HC | “one 40HC container” |
| Incoterm | FOB | “Incoterm: FOB” |

**Missing:** description of the cargo (commodity), cargo-ready date

**Draft reply** (AI draft, passed all checks):

```
Dear Customer,

Thank you for your enquiry regarding a 40HC container from Nhava Sheva to Hamburg with a gross weight of 18,500 kg on FOB terms.

To help us proceed, could you please confirm:
- the commodity (you wrote "FCL shipment")
- the cargo-ready date

We will prepare a quotation once these details are confirmed.

Best regards,
Hermes Team
```

*Models: router nemotron-3-super-120b-a12b (paid), skill agent nemotron-3-super-120b-a12b (paid). Total 22.9 s.*

## Test 3 · Documentation

**Subject:** Request for shipping documents

> Please share the final bill of lading and invoice for the shipment delivered last week.

**Expected:** Documentation · not a freight quotation enquiry

**Result:** Documentation (high confidence)

| Extracted field | Value | Quote from the email |
|---|---|---|
| Document(s) requested | final bill of lading, invoice | “final bill of lading and invoice” |
| Requested action | share | “Please share” |

**Missing:** the shipment reference (AWB / B/L / booking / invoice number)

**Draft reply** (AI draft, passed all checks):

```
Dear Customer,

Thank you for your request for the final bill of lading and invoice.

To help us proceed, could you please confirm:
- the shipment reference such as AWB, B/L, booking or invoice number

We will check availability with the relevant team and share the documents through the approved process.

Best regards,
Hermes Team
```

*Models: router nemotron-3-super-120b-a12b (paid), skill agent nemotron-3-super-120b-a12b (paid). Total 14.3 s.*

## Test 4 · Ambiguous enquiry

**Subject:** Urgent shipment of pharmaceutical samples

> We need to move pharmaceutical samples from Mumbai to Frankfurt urgently. Please share your best rate.

**Expected:** Freight Quotation Enquiry · mode UNKNOWN · ask for weight, dimensions/packages, delivery timeline

**Result:** Freight Quotation Enquiry (high confidence) · mode **UNKNOWN**, no explicit air/ocean wording

| Extracted field | Value | Quote from the email |
|---|---|---|
| Origin | Mumbai | “from Mumbai” |
| Destination | Frankfurt | “to Frankfurt” |
| Commodity | pharmaceutical samples | “pharmaceutical samples” |

**Missing:** preferred mode of transport (air freight or ocean freight), total gross weight and unit (kg or lb), number of pieces / packages, package dimensions (L × W × H) or the total volume in CBM, Incoterm (e.g. EXW, FOB, CIF), cargo-ready date, required delivery date / timeline *(recommended)*, special handling needs (dangerous-goods status, temperature control) *(recommended)*

**Unclear / conflicting:** “pharmaceutical samples” — temperature control or other handling unclear; The email says it is urgent but gives no required delivery date.

**Draft reply** (safe template):

```
Dear Customer,

Thank you for your enquiry regarding your shipment of pharmaceutical samples from Mumbai to Frankfurt.

To prepare an accurate freight quotation, could you please confirm the following details:
- Preferred mode of transport (air freight or ocean freight)
- Total gross weight and unit (kg or lb)
- Number of pieces / packages
- Package dimensions (L × W × H) or the total volume in CBM
- Incoterm (e.g. EXW, FOB, CIF)
- Cargo-ready date
- Required delivery date / timeline
- Special handling needs (dangerous-goods status, temperature control)

Once we receive these details, our team can proceed with the quotation process.

Best regards,
Hermes Team
```

*Models: router nemotron-3-super-120b-a12b (paid), skill agent nemotron-3-super-120b-a12b (paid). Total 21.0 s.*

