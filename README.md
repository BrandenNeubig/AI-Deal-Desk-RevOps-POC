# Luna y Sol Shepherd Systems

**Luna y Sol Shepherd Systems** is a Streamlit-based AI Deal Desk / RevOps proof of concept that demonstrates how AI can augment quote review workflows without replacing human approval authority.

The app combines deterministic approval rules, mock Salesforce-style quote data, AI-assisted deal summaries, peer comparison context, and workflow integrations to simulate a modern Deal Desk review experience.

**Live app:** https://shepherdsystems.streamlit.app  
**GitHub repo:** https://github.com/BrandenNeubig/AI-Deal-Desk-RevOps-POC

If the Streamlit app is suspended when you open it, click **Wake up** and give it a moment to restart.

## Core Concept

The project is built around a two-layer model:

- **Luna (Guardrails)**  
  A deterministic rules engine for approval thresholds, policy enforcement, clause modification review, demand planning checks, SLA aging, and routing.

- **Sol (Judgment)**  
  An AI-assisted insights layer that summarizes deal context, compares peer quotes, identifies commercial risks, and recommends next steps.

The system does **not** make approval decisions on behalf of the business.  
It evaluates rules, summarizes context, and supports human reviewers.

---

## Portfolio Positioning

This project was built as a portfolio demonstration during a job search to show practical AI application in a real Deal Desk workflow.

Rather than using AI as an autonomous approver, the POC shows how AI can be layered on top of legacy systems, structured quote data, business rules, and unstructured order form memo language to help reviewers move faster with better context.

Key themes:
- deterministic approval logic remains the source of truth
- AI provides explanation, triage, peer context, and reviewer guidance
- human approvers retain final decision authority
- the workflow supports both structured quote review and simulated order form memo review
- downstream actions such as Slack support requests and office-hours scheduling are connected to the review workflow
- the **Luna y Sol Shepherd Systems** branding reinforces the dual-model concept: rules-based guardrails plus AI-assisted judgment

---

## Current Features

- Mock Salesforce-style commit / consumption dataset
- Streamlit-based pending quote review queue
- Pending quote aging by region against a 4-hour Deal Desk SLA
- Quote age and SLA status tracking
- Pending Quotes section filtered by selected region
- Quote prioritization button that recommends the next quote to review and updates the selected quote
- Business justification pulled directly from `quotes.csv`
- Quote Details section showing:
  - annual commit
  - annualized trailing 3-month consumption run-rate
  - demand planning status
  - term months
  - payment terms
  - rollover percentage
- Cross-service discount review table
- Add-on discount review table
- Customer investment funds review table
- Clause Modifications section showing simulated redlines and classification details
- Approval Details table with rule, approver, and reason
- AI Deal Desk Summary using OpenAI
- AI summary table with cleaner formatting for multi-part recommendations
- Requested Quote vs Industry Peers table using industry peer medians instead of averages
- Quote Preview generated from the selected quote
- Quote Tools section with downstream workflow actions:
  - Quote Preview
  - Transfer Quote to Customer Schedule Template
  - Reserve Deal Desk Open Office Hours via Calendly
  - Request Support via Slack
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

### 8. Rollover Review Rule
A quote requires review when:
- rollover percentage is greater than 0%

This flags situations where unused prior-period commitment is being carried into a new commercial period and may require Finance, Deal Desk, or leadership review depending on policy.

### 9. Clause Modification Review Rules
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
  - `rollover_percentage`
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
- recommend the highest-priority quote for review
- select a pending quote for review
- display quote details in focused approval-review tables
- show clause modifications and simulated redlines when applicable
- pull justification directly from the quote record
- evaluate the quote through Luna’s rules
- summarize context through Sol’s AI assistant layer
- show industry peer median comparisons across commercial metrics
- generate a customer-facing Quote Preview based on the selected quote
- expose Quote Tools for customer-facing quote preview, schedule template generation, Calendly office-hours scheduling, and Slack support requests

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

## Demo Workflow

A typical demo flow:

1. Review pending quote aging by region and SLA status.
2. Use **Recommend Quote to Prioritize** to identify the next quote for review.
3. Review quote details, discount authority, rollover, deal investment funds, clause modifications, and business justification.
4. Click **Evaluate Quote** to run Luna’s approval rules and Sol’s AI-assisted summary.
5. Compare the requested quote against same-industry peer medians.
6. Review the approval matrix, approval details, and AI-generated Deal Desk summary.
7. Use Quote Tools to preview a customer-facing quote, generate or upload a customer schedule, reserve Deal Desk office hours, or request support via Slack.

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

ChatGPT was used to assist the author with code generation, debugging, iteration, documentation, and refinement for this proof of concept. The business logic, workflow design, validation, and final implementation decisions were reviewed and directed by the author.
