
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

DATE_FORMAT = "%d-%b-%Y"
APPROVAL_HIERARCHY = ["AE", "Manager", "Director", "CRO", "CEO"]


def load_data(data_dir: Path):
    accounts = pd.read_csv(data_dir / "accounts.csv")
    contracts = pd.read_csv(data_dir / "contracts.csv")
    opportunities = pd.read_csv(data_dir / "opportunities.csv")
    quotes = pd.read_csv(data_dir / "quotes.csv")
    quote_line_items = pd.read_csv(data_dir / "quote_line_items.csv")
    products = pd.read_csv(data_dir / "products.csv")
    consumption_usage = pd.read_csv(data_dir / "consumption_usage.csv")

    with open(data_dir / "approval_rules.json", "r") as f:
        approval_rules = json.load(f)

    return {
        "accounts": accounts,
        "contracts": contracts,
        "opportunities": opportunities,
        "quotes": quotes,
        "quote_line_items": quote_line_items,
        "products": products,
        "consumption_usage": consumption_usage,
        "approval_rules": approval_rules,
    }


def get_quote_package(data, quote_id: str):
    quotes = data["quotes"]
    opportunities = data["opportunities"]
    accounts = data["accounts"]
    quote_line_items = data["quote_line_items"]
    products = data["products"]

    quote_match = quotes[quotes["quote_id"] == quote_id]
    if quote_match.empty:
        raise ValueError("Quote %s was not found." % quote_id)

    quote = quote_match.iloc[0]
    opportunity = opportunities[opportunities["opportunity_id"] == quote["opportunity_id"]].iloc[0]
    account = accounts[accounts["account_id"] == opportunity["account_id"]].iloc[0]

    qli = quote_line_items[quote_line_items["quote_id"] == quote_id].copy()
    qli = qli.merge(
        products[["product_name", "product_category", "discount_type"]],
        on="product_name",
        how="left",
        suffixes=("", "_product"),
    )

    return quote, opportunity, account, qli


def get_pending_quotes(data) -> pd.DataFrame:
    opportunities = data["opportunities"].copy()
    quotes = data["quotes"].copy()
    accounts = data["accounts"].copy()

    pending_opps = opportunities[
        ~opportunities["stage"].astype(str).str.strip().isin(["Closed Won", "Closed Lost"])
    ].copy()

    pending_quotes = quotes.merge(
        pending_opps[["opportunity_id", "account_id", "stage", "type", "close_date"]],
        on="opportunity_id",
        how="inner",
    ).merge(
        accounts[["account_id", "account_name", "industry", "region"]],
        on="account_id",
        how="left",
    )

    pending_quotes["region"] = pending_quotes["region"].fillna("Unknown")
    return pending_quotes.sort_values(["region", "account_name", "quote_id"]).reset_index(drop=True)


def get_region_quote_counts(data) -> pd.DataFrame:
    pending_quotes = get_pending_quotes(data)
    counts = (
        pending_quotes.groupby("region", as_index=False)["quote_id"]
        .count()
        .rename(columns={"quote_id": "Pending Quotes"})
        .sort_values("region")
    )
    return counts


def get_discount_tier(matrix: List[Dict], annual_commit: float) -> Optional[Dict]:
    for tier in matrix:
        min_commit = float(tier["min_annual_commit"])
        max_commit = tier["max_annual_commit"]
        in_range = (
            annual_commit >= min_commit
            if max_commit is None
            else min_commit <= annual_commit < float(max_commit)
        )
        if in_range:
            return tier
    return None


def determine_required_approver(requested_discount: float, approvals: Dict) -> Tuple[str, str]:
    ae_limit = float(approvals.get("AE", 0))
    manager_limit = float(approvals.get("Manager", 0))
    director_limit = float(approvals.get("Director", 0))
    cro_limit = float(approvals.get("CRO", 0))
    ceo_limit = float(approvals.get("CEO", 999))

    if requested_discount <= ae_limit:
        return "AE", "%d%%" % ae_limit
    if requested_discount <= manager_limit:
        return "Manager", "%d%%" % manager_limit
    if requested_discount <= director_limit:
        return "Director", "%d%%" % director_limit
    if requested_discount <= cro_limit:
        return "CRO", "%d%%" % cro_limit
    return "CEO", "%d%%" % ceo_limit


def get_quote_discount_summary(quote, qli: pd.DataFrame, approval_rules: Dict) -> Dict:
    annual_commit = float(quote["annual_commit"])
    cross_service_requested = float(quote.get("cross_service_discount_percent", 0))

    cross_matrix = approval_rules.get("cross_service_preapproved_discount_matrix", [])
    cross_tier = get_discount_tier(cross_matrix, annual_commit)
    if cross_tier:
        cross_approvals = cross_tier.get("approvals", {})
        cross_required, cross_max = determine_required_approver(
            cross_service_requested,
            cross_approvals,
        )
        cross_ae_limit = float(cross_approvals.get("AE", 0))
    else:
        cross_required, cross_max = "Unknown", "N/A"
        cross_ae_limit = 0.0

    add_on_qli = qli[
        qli["discount_type"].astype(str).str.strip().str.lower() == "add-on"
    ].copy()
    add_on_requested = (
        float(pd.to_numeric(add_on_qli["discount_percent"], errors="coerce").fillna(0).max())
        if not add_on_qli.empty
        else 0.0
    )

    add_on_matrix = approval_rules.get("add_on_preapproved_discount_matrix", [])
    add_on_tier = get_discount_tier(add_on_matrix, annual_commit)
    if add_on_tier:
        add_on_approvals = add_on_tier.get("approvals", {})
        add_on_required, add_on_max = determine_required_approver(
            add_on_requested,
            add_on_approvals,
        )
        add_on_ae_limit = float(add_on_approvals.get("AE", 0))
    else:
        add_on_required, add_on_max = "Unknown", "N/A"
        add_on_ae_limit = 0.0

    cross_ratio_to_ae = round(cross_service_requested / cross_ae_limit, 2) if cross_ae_limit > 0 else None
    add_on_ratio_to_ae = round(add_on_requested / add_on_ae_limit, 2) if add_on_ae_limit > 0 else None

    return {
        "annual_commit": annual_commit,
        "term_months": int(quote["term_months"]),
        "cross_service_requested_discount": cross_service_requested,
        "cross_service_ae_preapproved_discount": cross_ae_limit,
        "cross_service_ratio_to_ae_preapproved": cross_ratio_to_ae,
        "cross_service_approver_required": cross_required,
        "cross_service_approver_max_discount": cross_max,
        "add_on_requested_discount": add_on_requested,
        "add_on_ae_preapproved_discount": add_on_ae_limit,
        "add_on_ratio_to_ae_preapproved": add_on_ratio_to_ae,
        "add_on_approver_required": add_on_required,
        "add_on_approver_max_discount": add_on_max,
    }


def check_quote_approvals(quote, qli, approval_rules):
    reasons = []
    highest_required_approval = None
    discount_summary = get_quote_discount_summary(quote, qli, approval_rules)

    def update_highest(level: str):
        nonlocal highest_required_approval
        if level not in APPROVAL_HIERARCHY:
            return
        if highest_required_approval is None:
            highest_required_approval = level
        elif APPROVAL_HIERARCHY.index(level) > APPROVAL_HIERARCHY.index(highest_required_approval):
            highest_required_approval = level

    cross_required = discount_summary["cross_service_approver_required"]
    if cross_required != "AE" and cross_required != "Unknown":
        reasons.append(
            "%s approval required for cross-service discount request of %.1f%%." % (
                cross_required,
                discount_summary["cross_service_requested_discount"],
            )
        )
        update_highest(cross_required)

    add_on_required = discount_summary["add_on_approver_required"]
    if add_on_required != "AE" and add_on_required != "Unknown":
        reasons.append(
            "%s approval required for add-on discount request of %.1f%%." % (
                add_on_required,
                discount_summary["add_on_requested_discount"],
            )
        )
        update_highest(add_on_required)

    short_term_rule = approval_rules.get("short_term_high_commit")
    if short_term_rule:
        conditions = short_term_rule.get("conditions", {})
        required_term = int(conditions.get("term_months", 0))
        min_annual_commit = float(conditions.get("min_annual_commit", 0))
        approval_required = short_term_rule.get("approval_required", "CRO")
        reason = short_term_rule.get("reason", "Short-term high-value deal requires review.")

        if int(quote["term_months"]) == required_term and float(quote["annual_commit"]) >= min_annual_commit:
            reasons.append("%s approval required: %s" % (approval_required, reason))
            update_highest(approval_required)

    return {
        "reasons": reasons,
        "highest_required_approval": highest_required_approval,
        "discount_summary": discount_summary,
    }


def get_consumption_summary(data, account_id: str):
    contracts = data["contracts"].copy()
    usage = data["consumption_usage"].copy()

    account_contracts = contracts[contracts["account_id"] == account_id].copy()
    if account_contracts.empty:
        return {
            "status": "No contract found",
            "message": "This account has no matching contract records.",
        }

    account_contract_ids = account_contracts["contract_id"].tolist()
    account_usage = usage[usage["contract_id"].isin(account_contract_ids)].copy()

    if account_usage.empty:
        return {
            "status": "No usage found",
            "message": "This account has no matching monthly consumption records.",
        }

    account_usage["month_dt"] = pd.to_datetime(account_usage["month"], format=DATE_FORMAT)
    total_consumed = float(account_usage["consumed_value"].sum())
    latest_month = account_usage["month_dt"].max()
    months_observed = int(account_usage["month_dt"].nunique())

    latest_contract = account_contracts.sort_values("end_date").iloc[-1]
    total_commit_value = float(latest_contract["total_commit_value"])
    term_months = int(latest_contract["term_months"])

    monthly_usage = (
        account_usage.groupby("month_dt", as_index=False)["consumed_value"]
        .sum()
        .sort_values("month_dt")
    )
    trailing_3_avg = float(
        monthly_usage["consumed_value"].tail(3).mean()
    ) if not monthly_usage.empty else 0.0
    annualized_trailing_3_months = trailing_3_avg * 12

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
        "latest_usage_month": latest_month.strftime(DATE_FORMAT),
        "total_commit_value": int(total_commit_value),
        "total_consumed_to_date": int(total_consumed),
        "commit_used_percent": round(commit_used_pct * 100, 1),
        "average_monthly_burn": round(avg_monthly_burn, 2),
        "annualized_trailing_3_months": round(annualized_trailing_3_months, 2),
        "estimated_runway_months": None if runway_months is None else round(runway_months, 1),
    }


def get_industry_quote_context(data, selected_quote_id: str, limit: int = 10):
    quotes = data["quotes"].copy()
    opportunities = data["opportunities"].copy()
    accounts = data["accounts"].copy()

    quote_context = quotes.merge(
        opportunities[["opportunity_id", "account_id"]],
        on="opportunity_id",
        how="left"
    ).merge(
        accounts[["account_id", "account_name", "industry", "region"]],
        on="account_id",
        how="left"
    )

    selected_row = quote_context[quote_context["quote_id"] == selected_quote_id]
    if selected_row.empty:
        return {
            "selected_industry": None,
            "industry_benchmark_summary": "No industry context found.",
            "peer_quotes": [],
        }

    selected_industry = selected_row.iloc[0]["industry"]

    peer_quotes = quote_context[
        (quote_context["industry"] == selected_industry) &
        (quote_context["quote_id"] != selected_quote_id)
    ].copy()

    if peer_quotes.empty:
        return {
            "selected_industry": selected_industry,
            "industry_benchmark_summary": "No peer quotes found in this industry.",
            "peer_quotes": [],
        }

    peer_quotes = peer_quotes.sort_values(
        by=["cross_service_discount_percent", "annual_commit"],
        ascending=[False, False]
    )

    avg_discount = round(float(peer_quotes["cross_service_discount_percent"].mean()), 2)
    max_discount = round(float(peer_quotes["cross_service_discount_percent"].max()), 2)
    avg_annual_commit = round(float(peer_quotes["annual_commit"].mean()), 2)
    peer_count = int(len(peer_quotes))

    peer_quotes_sample = peer_quotes.head(limit)[[
        "quote_id",
        "account_name",
        "industry",
        "region",
        "annual_commit",
        "term_months",
        "total_contract_value",
        "cross_service_discount_percent"
    ]].to_dict(orient="records")

    return {
        "selected_industry": selected_industry,
        "industry_benchmark_summary": {
            "peer_quote_count": peer_count,
            "average_discount_percent": avg_discount,
            "max_discount_percent": max_discount,
            "average_annual_commit": avg_annual_commit,
        },
        "peer_quotes": peer_quotes_sample,
    }


def build_review_payload(data, quote_id: str):
    quote, opportunity, account, qli = get_quote_package(data, quote_id)
    approval_result = check_quote_approvals(quote, qli, data["approval_rules"])
    consumption_summary = get_consumption_summary(data, account["account_id"])
    industry_context = get_industry_quote_context(data, quote_id)

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
            "quote_id": quote["quote_id"],
            "annual_commit": int(quote["annual_commit"]),
            "term_months": int(quote["term_months"]),
            "total_contract_value": int(quote["total_contract_value"]),
            "cross_service_discount_percent": float(quote["cross_service_discount_percent"]),
            "business_justification": str(quote.get("business_justification", "")),
        },
        "quote_line_items": qli[[
            "product_name",
            "discount_percent",
            "discount_type",
        ]].to_dict(orient="records"),
        "approval_reasons": approval_result["reasons"],
        "highest_required_approval": approval_result["highest_required_approval"],
        "discount_summary": approval_result["discount_summary"],
        "consumption_summary": consumption_summary,
        "industry_quote_context": industry_context,
    }
    return payload


def explain_with_openai(payload):
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")

    try:
        import streamlit as st
        if not api_key and "OPENAI_API_KEY" in st.secrets:
            api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=f"""
You are a Deal Desk assistant for a proof of concept.
Be concise. Prefer a single sentence when possible.
If more than one sentence is needed, use very short bullet points.
Do not be verbose.

Here is the review payload:
{json.dumps(payload, indent=2)}

Please answer with:
1. Approval status
2. Key reason or reasons
3. Business justification quality
4. Peer discount comparison
5. Consumption signal
6. Recommended next step

Important:
- Do not override the business rules decision
- Use the business_justification from the quote as context
- Keep the tone practical and executive-friendly
- Keep the response under 90 words
"""
    )
    return response.output_text, response.usage


def main():
    data_dir = Path("data")
    pending_quotes = load_data(data_dir)
    quote_id = "Q0021"

    payload = build_review_payload(pending_quotes, quote_id)

    print("\n=== STRUCTURED REVIEW PAYLOAD ===")
    print(json.dumps(payload, indent=2))

    print("\n=== AI DEAL DESK SUMMARY ===")
    summary, usage = explain_with_openai(payload)
    print(summary)

    print("\n=== USAGE ===")
    print(usage)


if __name__ == "__main__":
    main()
