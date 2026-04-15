<<<<<<< HEAD
# AI Deal Desk / RevOps POC

A lightweight proof of concept that simulates Deal Desk and RevOps workflows using a mock Salesforce-style dataset, Python business rules, and the OpenAI API.

## What it does

This project:
- loads mock CRM-style account, contract, quote, and consumption data
- evaluates quote approval requirements using Python rules
- analyzes customer consumption against committed spend
- uses OpenAI to generate a plain-English Deal Desk summary

## Example workflow

Given a selected quote, the app:
1. finds the related opportunity and account
2. checks approval rules
3. reviews consumption trends
4. produces an AI-generated recommendation

## Tech stack

- Python
- pandas
- OpenAI API
- python-dotenv

## Project structure

```text
.
├── main.py
├── requirements.txt
├── README.md
├── .gitignore
└── data/
    ├── accounts.csv
    ├── contracts.csv
    ├── opportunities.csv
    ├── quotes.csv
    ├── quote_line_items.csv
    ├── products.csv
    ├── consumption_usage.csv
    └── approval_rules.json
=======
# AI-Deal-Desk-RevOps-POC
A lightweight proof of concept that simulates Deal Desk and RevOps workflows using a mock Salesforce-style dataset, Python business rules, and the OpenAI API.
>>>>>>> b6d54100c35d7eb7ae8e4f24326e339cac922f69
