# Luna y Sol Shepherd Systems

A Streamlit-based proof of concept showing how an AI Deal Desk assistant can augment legacy Deal Desk workflows without replacing human approval authority.

Take a look at: https://shepherdsystems.streamlit.app

If the Streamlit app is suspended when you open it, click **Wake up** and give it a moment to restart.

## Core Concept

This project uses a two-layer model:

- **Luna (Guardrails)**  
  Deterministic rules engine for approval thresholds, policy enforcement, clause modification review, demand planning checks, SLA aging, and routing.

- **Sol (Judgment)**  
  AI-assisted summary layer that explains deal context, compares peer quotes, identifies commercial risks, and recommends next steps.

The system does **not** make approval decisions on behalf of the business.  
It evaluates rules, summarizes context, and supports human reviewers.

---

## Current Positioning

This POC is designed to demonstrate how AI can function as a Deal Desk assistant layered on top of legacy systems, structured quote data, business rules, and unstructured order form memo language.

Key themes:
- deterministic approvals remain in place
- AI provides explanation, triage, and reviewer guidance
- the workflow is designed for human decision support, not autonomous approval
- the system supports both structured quote review and simulated order form memo review
- the interface is branded as **Luna y Sol Shepherd Systems** to reinforce the dual-model concept

---

## Current Features

- Mock Salesforce-style commit / consumption dataset
- Streamlit-based pending quote review queue
- Pending quote aging by region against a 4-hour Deal Desk SLA
- Quote age and SLA status tracking
- Pending Quotes section filtered by selected region
- Business justification pulled directly from `quotes.csv`
- Quote Details section showing:
  - annual commit
  - annualized trailing 3-month consumption run-rate
  - demand planning status
  - term months
  - payment terms
- Cross-service discount review table
- Add-on discount review table
- Customer investment funds review table
- Clause Modifications section showing simulated redlines and classification details
- Approval Details table with rule, approver, and reason
- AI Deal Desk Summary using OpenAI
- AI summary table with cleaner formatting for multi-part recommendations
- Requested Quote vs Industry Peers table using industry peer medians instead of averages
- Quote Preview generated from the selected quote
- Quote Tools section with placeholder workflow action: **Transfer Quote to Customer Schedule (Coming soon)**
- Custom logo and branded header for **Luna y Sol Shepherd Systems**

---

## Approval Rules

Current approval logic includes:

### 1. Cross-Service Preapproved Discount Matrix
Approval authority is determined by:
- annual commit tier
- requested cross-service discount

Approver levels include:
- AE
- Manager
- Director
- CRO
- CEO

### 2. Add-On Preapproved Discount Matrix
Approval authority is also determined for add-on products using a separate matrix.

Add-on discounts are intentionally lower than cross-service discounts to reflect lower-margin products.

### 3. Short-Term High-Commit Rule
A quote requires CRO review when:
- `term_months = 12`
- and `annual_commit >= 500000`

This flags large single-year deals that may represent a missed multi-year opportunity.

### 4. Non-Standard Payment Terms Rule
A quote requires Finance review when:
- payment terms are anything other than `Net 30`

### 5. Customer Investment Funds Rule
A quote requires CRO review when:
- requested customer investment funds exceed the preapproved threshold as a percent of annual commit

### 6. Demand Planning Review Rule
A quote requires Practice Manager review when:
- demand planning is incomplete
- and customer investment funds are requested

This helps validate PS&T capacity, scope, and scheduling impact.

### 7. Annual Commit Below Consumption Run-Rate Rule
A quote requires Finance review when:
- annual commit is below annualized trailing 3-month consumption run-rate

This flags potential under-sizing, demand planning risk, or missed expansion opportunity.

### 8. Clause Modification Review Rules
Simulated order form memo modifications can route to Legal or Finance depending on the clause topic and business impact.

Example clause topics include:
- Publicity / Reference Rights
- Renewal
- Usage / Overages

---

## Updated Data Model

Recent dataset updates include:

- `quotes.csv` includes:
  - `business_justification`
  - `payment_terms`
  - `requested_deal_investment`
  - `demand_planning_complete`
  - `quote_memo_modified`
  - `quote_age_hours`
- `contracts.csv` includes:
  - `trailing_3_months`
  - `annualized_t3m`
- `quote_memo_modifications.csv` includes:
  - `quote_id`
  - `clause_topic`
  - `original_clause`
  - `modified_clause`
  - classification details used for approval routing
- `quote_line_items.csv` uses `discount_type`
- `products.csv` uses `discount_type`
- approval rules now include discount, payment terms, customer investment funds, demand planning, annualized consumption, and clause modification routing

---

## UI / Workflow

The current app is designed around pending deal triage rather than manual account selection.

Current GUI behavior:
- show pending quote aging by region against a 4-hour SLA
- filter pending quotes by selected region
- select a pending quote for review
- display quote details in focused approval-review tables
- show clause modifications and simulated redlines when applicable
- pull justification directly from the quote record
- evaluate the quote through Luna’s rules
- summarize context through Sol’s AI assistant layer
- show industry peer median comparisons across commercial metrics
- generate a customer-facing Quote Preview based on the selected quote
- expose Quote Tools for future workflow actions

The header uses the **Luna y Sol Shepherd Systems** name and custom shepherd logo.

---

## Quote Preview

The Quote Preview is populated from the selected quote and includes customer-facing commercial fields such as:

- Quote ID
- Annual Commit
- Total Contract Amount
- Cross-Service Discount
- Add-On Discount
- Term
- Payment Terms
- Customer Investment Funds

The template also includes:

- a note that discounts are applied to the Company SKU list published on the Company website
- modified memo clauses when a quote has an order form memo modification
- customer investment fund language stating that funds must be used within twelve months or expire
- a scheduling note instructing the customer to contact their Practice Manager for scheduling

---

## Project Structure

```text
AI-Deal-Desk-RevOps-POC/
├── app.py
├── main.py
├── logo.png
├── quote_template.html
├── requirements.txt
├── .env
└── data/
    ├── accounts.csv
    ├── contracts.csv
    ├── opportunities.csv
    ├── quotes.csv
    ├── quote_line_items.csv
    ├── quote_memo_modifications.csv
    ├── products.csv
    ├── consumption_usage.csv
    └── approval_rules.json
```

---

## Note

ChatGPT was used to assist the author with code generation, iteration, and refinement for this proof of concept.
