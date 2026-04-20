# Luna y Sol Shepherd Systems

A Streamlit-based proof of concept showing how an AI Deal Desk assistant can augment legacy Deal Desk workflows without replacing human approval authority.

## Core Concept

This project uses a two-layer model:

- **Luna (Guardrails)**  
  Deterministic rules engine for approval thresholds, policy enforcement, and routing.

- **Sol (Judgment)**  
  AI-assisted summary layer that explains deal context, compares peer quotes, and recommends next steps.

The system does **not** make approval decisions on behalf of the business.  
It evaluates rules, summarizes context, and supports human reviewers.

---

## Current Positioning

This POC is designed to demonstrate how AI can function as a Deal Desk assistant layered on top of legacy systems and structured business rules.

Key themes:
- deterministic approvals remain in place
- AI provides explanation, triage, and reviewer guidance
- the workflow is designed for human decision support, not autonomous approval
- the interface is branded as **Luna y Sol Shepherd Systems** to reinforce the dual-model concept

---

## Current Features

- Mock Salesforce-style commit / consumption dataset
- Region-based pending quote queue in Streamlit
- Pending Quotes by Region chart
- Pending Quotes section filtered by selected region
- Business justification pulled directly from `quotes.csv`
- Structured review payload combining:
  - account context
  - opportunity context
  - quote details
  - quote line items
  - consumption summary
  - industry peer quote context
- Cross-service preapproved discount approval matrix
- Add-on preapproved discount approval matrix
- Short-term high-commit CRO review rule
- Quote Details section split into focused tables
- Approval decision section with highest required approver
- Requested discount vs AE preapproved ratio to show how far the request is from go-in authority
- AI Deal Desk assistant summary using OpenAI
- Requested Quote vs Industry Peers chart
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

This is intended to flag large single-year deals that may represent a missed multi-year opportunity.

---

## Updated Data Model

Recent dataset updates include:
- `quotes.csv` includes `business_justification`
- `quote_line_items.csv` uses `discount_type`
- add-on rows can be evaluated separately from cross-service family rows
- `products.csv` uses `discount_type`
- blank account regions were populated for better queueing and dashboard behavior
- approval rules now include both cross-service and add-on discount matrices

---

## UI / Workflow

The current app is designed around pending deal triage rather than manual account selection.

Current GUI behavior:
- show pending quotes by region
- filter pending quotes by selected region
- select a pending quote for review
- display quote details in multiple small approval-focused tables
- pull justification directly from the quote record
- evaluate the quote through Luna’s rules
- summarize context through Sol’s AI assistant layer

The header now uses the **Luna y Sol Shepherd Systems** name and custom shepherd logo.

---

## Project Structure

```text
AI-Deal-Desk-RevOps-POC/
├── app.py
├── main.py
├── logo.png
├── requirements.txt
├── .env
└── data/
    ├── accounts.csv
    ├── contracts.csv
    ├── opportunities.csv
    ├── quotes.csv
    ├── quote_line_items.csv
    ├── products.csv
    ├── consumption_usage.csv
    └── approval_rules.json
```

---

## Note

ChatGPT was used to assist the author with code generation, iteration, and refinement for this proof of concept.
