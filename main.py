import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

DATE_FORMAT = "%d-%b-%Y"


def load_data(data_dir: Path):
    accounts = pd.read_csv(data_dir / "accounts.csv")
    contracts = pd.read_csv(data_dir / "contracts.csv")
    opportunities = pd.read_csv(data_dir / "opportunities.csv")
    quotes = pd.read_csv(data_dir / "quotes.csv")
    quote_line_items = pd.read_csv(data_dir / "quote_line_items.csv")
    consumption_usage = pd.read_csv(data_dir / "consumption_usage.csv")

    with open(data_dir / "approval_rules.json", "r") as f:
        approval_rules = json.load(f)

    return {
        "accounts": accounts,
        "contracts": contracts,
        "opportunities": opportunities,
        "quotes": quotes,
        "quote_line_items": quote_line_items,
        "consumption_usage": consumption_usage,
        "approval_rules": approval_rules,
    }


def get_quote_package(data, quote_id: str):
    quotes = data["quotes"]
    opportunities = data["opportunities"]
    accounts = data["accounts"]
    quote_line_items = data["quote_line_items"]

    quote_match = quotes[quotes["quote_id"] == quote_id]
    if quote_match.empty:
        raise ValueError(f"Quote {quote_id} was not found.")

    quote = quote_match.iloc[0]
    opportunity = opportunities[opportunities["opportunity_id"] == quote["opportunity_id"]].iloc[0]
    account = accounts[accounts["account_id"] == opportunity["account_id"]].iloc[0]
    qli = quote_line_items[quote_line_items["quote_id"] == quote_id].copy()

    return quote, opportunity, account, qli


def check_quote_approvals(quote, qli, approval_rules):
    reasons = []

    cross_service_discount = float(quote["cross_service_discount_percent"])
    annual_commit = float(quote["annual_commit"])
    term_months = int(quote["term_months"])

    if cross_service_discount > 20:
        reasons.append(approval_rules["cross_service_discount_over_20"])

    if cross_service_discount > 25:
        reasons.append(approval_rules["cross_service_discount_over_25"])

    if term_months > 24:
        reasons.append(approval_rules["term_over_24_months"])

    if annual_commit > 500000:
        reasons.append(approval_rules["annual_commit_over_500k"])

    has_non_eligible = (qli["cross_service_discount_eligible"].astype(str).str.strip().str.lower() == "no").any()
    if has_non_eligible:
        reasons.append(approval_rules["contains_non_eligible_skus"])

    if len(qli) > 1:
        reasons.append(approval_rules["multi_product_quote"])

    return reasons


def get_consumption_summary(data, account_id: str):
    contracts = data["contracts"].copy()
    usage = data["consumption_usage"].copy()

    account_contracts = contracts[contracts["account_id"] == account_id].copy()
    if account_contracts.empty:
        return {
            "status": "No contract found",
            "message": "This account has no matching contract records."
        }

    account_contract_ids = account_contracts["contract_id"].tolist()
    account_usage = usage[usage["contract_id"].isin(account_contract_ids)].copy()

    if account_usage.empty:
        return {
            "status": "No usage found",
            "message": "This account has no matching monthly consumption records."
        }

    account_usage["month_dt"] = pd.to_datetime(account_usage["month"], format=DATE_FORMAT)
    total_consumed = float(account_usage["consumed_value"].sum())
    latest_month = account_usage["month_dt"].max()
    months_observed = int(account_usage["month_dt"].nunique())

    latest_contract = account_contracts.sort_values("end_date").iloc[-1]
    total_commit_value = float(latest_contract["total_commit_value"])
    term_months = int(latest_contract["term_months"])

    commit_used_pct = (total_consumed / total_commit_value) if total_commit_value else 0

    if commit_used_pct >= 0.9 and months_observed < term_months:
        status = "Likely expansion opportunity"
    elif commit_used_pct < 0.5 and months_observed >= max(1, term_months // 2):
        status = "Possible under-consumption risk"
    else:
        status = "Consumption appears on track"

    avg_monthly_burn = total_consumed / max(months_observed, 1)
    remaining_commit = max(total_commit_value - total_consumed, 0)
    runway_months = remaining_commit / avg_monthly_burn if avg_monthly_burn > 0 else None

    return {
        "status": status,
        "months_observed": months_observed,
        "latest_usage_month": latest_month.strftime("%d-%b-%Y"),
        "total_commit_value": int(total_commit_value),
        "total_consumed_to_date": int(total_consumed),
        "commit_used_percent": round(commit_used_pct * 100, 1),
        "average_monthly_burn": round(avg_monthly_burn, 2),
        "estimated_runway_months": None if runway_months is None else round(runway_months, 1),
    }


def build_review_payload(data, quote_id: str):
    quote, opportunity, account, qli = get_quote_package(data, quote_id)
    approval_reasons = check_quote_approvals(quote, qli, data["approval_rules"])
    consumption_summary = get_consumption_summary(data, account["account_id"])

    payload = {
        "quote_id": quote["quote_id"],
        "account": {
            "account_id": account["account_id"],
            "account_name": account["account_name"],
            "industry": account["industry"],
            "region": account["region"],
            "current_arr": int(account["current_arr"]),
            "renewal_date": account["renewal_date"],
        },
        "opportunity": {
            "opportunity_id": opportunity["opportunity_id"],
            "stage": opportunity["stage"],
            "type": opportunity["type"],
            "amount": int(opportunity["amount"]),
            "close_date": opportunity["close_date"],
        },
        "quote": {
            "annual_commit": int(quote["annual_commit"]),
            "term_months": int(quote["term_months"]),
            "total_contract_value": int(quote["total_contract_value"]),
            "cross_service_discount_percent": float(quote["cross_service_discount_percent"]),
        },
        "quote_line_items": qli[[
            "product_name",
            "discount_percent",
            "cross_service_discount_eligible"
        ]].to_dict(orient="records"),
        "approval_reasons": approval_reasons,
        "consumption_summary": consumption_summary,
    }
    return payload


def explain_with_openai(payload):
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Put it in a .env file.")

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=f"""
You are a friendly Deal Desk analyst.
Explain the result like the user is brand new to OpenAI and sales operations.

Here is the review payload:
{json.dumps(payload, indent=2)}

Please answer with:
1. Whether approval is needed
2. Why it is needed
3. Whether there is an expansion signal from consumption
4. A short recommended next step

Keep it simple, warm, and under 200 words.
"""
    )
    return response.output_text, response.usage


def main():
    data_dir = Path("data")
    quote_id = "Q0011"

    data = load_data(data_dir)
    payload = build_review_payload(data, quote_id)

    print("\n=== STRUCTURED REVIEW PAYLOAD ===")
    print(json.dumps(payload, indent=2))

    print("\n=== AI DEAL DESK SUMMARY ===")
    summary, usage = explain_with_openai(payload)
    print(summary)

    print("\n=== USAGE ===")
    print(usage)

if __name__ == "__main__":
    main()
