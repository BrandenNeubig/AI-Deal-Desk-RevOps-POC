# AI Deal Desk / RevOps POC

A Streamlit-based proof of concept showing how AI can augment legacy Deal Desk workflows without replacing human approval authority.

## Core Concept

This project uses a two-layer model:

- **Luna (Guardrails)**  
  Deterministic rules engine for approval thresholds, policy enforcement, and routing.

- **Sol (Judgment)**  
  AI-assisted summary layer that explains deal context, compares peer quotes, and recommends next steps.

The system does **not** make approval decisions on behalf of the business.  
It evaluates rules, summarizes context, and supports human reviewers.

---

## Current Features

- Mock Salesforce-style commit / consumption dataset
- Quote selection by account and quote in Streamlit
- Structured review payload combining:
  - account context
  - opportunity context
  - quote details
  - quote line items
  - consumption summary
  - industry peer quote context
- Cross-service preapproved discount approval matrix
- Short-term high-commit CRO review rule
- Approval decision section with highest required approver
- AI Deal Desk summary using OpenAI
- Requested Quote vs Industry Peers chart

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

### 2. Short-Term High-Commit Rule
A quote requires CRO review when:
- `term_months = 12`
- and `annual_commit >= 500000`

This is intended to flag large single-year deals that may represent a missed multi-year opportunity.

---

## Project Structure

```text
AI-Deal-Desk-RevOps-POC/
├── app.py
├── main.py
├── requirements.txt
├── .env
└── data/
    ├── accounts.csv
    ├── contracts.csv
    ├── opportunities.csv
    ├── quotes.csv
    ├── quote_line_items.csv
    ├── consumption_usage.csv
    └── approval_rules.json