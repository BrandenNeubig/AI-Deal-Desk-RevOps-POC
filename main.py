import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

DATE_FORMAT = "%d-%b-%Y"
APPROVAL_HIERARCHY = ["AE", "Manager", "Director", "Practice Manager", "Legal", "Finance", "CRO", "CEO"]


def load_data(data_dir: Path):
    accounts = pd.read_csv(data_dir / "accounts.csv")
    contracts = pd.read_csv(data_dir / "contracts.csv")
    opportunities = pd.read_csv(data_dir / "opportunities.csv")
    quotes = pd.read_csv(data_dir / "quotes.csv")
    quote_line_items = pd.read_csv(data_dir / "quote_line_items.csv")
    products = pd.read_csv(data_dir / "products.csv")
    consumption_usage = pd.read_csv(data_dir / "consumption_usage.csv")

    quote_memo_path = data_dir / "quote_memo_modifications.csv"
    if quote_memo_path.exists():
        quote_memo_modifications = pd.read_csv(quote_memo_path)
    else:
        quote_memo_modifications = pd.DataFrame(columns=[
            "quote_id",
            "memo_topic",
            "original_clause",
            "modified_clause",
        ])

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
        "quote_memo_modifications": quote_memo_modifications,
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

    requested_deal_investment = float(quote.get("requested_deal_investment", 0) or 0)
    requested_deal_investment_percent = (
        round((requested_deal_investment / annual_commit) * 100, 1)
        if annual_commit > 0
        else 0.0
    )
    deal_investment_preapproved = approval_rules.get("deal_investment_preapproved", {})
    deal_investment_ae_preapproved_percent = float(
        deal_investment_preapproved.get("ae_preapproved_percent_of_annual_commit", 10)
    )
    deal_investment_preapproved_amount = annual_commit * (deal_investment_ae_preapproved_percent / 100)
    deal_investment_ratio_to_ae = (
        round(requested_deal_investment / deal_investment_preapproved_amount, 2)
        if deal_investment_preapproved_amount > 0
        else None
    )

    cross_ratio_to_ae = round(cross_service_requested / cross_ae_limit, 2) if cross_ae_limit > 0 else None
    add_on_ratio_to_ae = round(add_on_requested / add_on_ae_limit, 2) if add_on_ae_limit > 0 else None

    return {
        "annual_commit": annual_commit,
        "demand_planning_complete": str(quote.get("demand_planning_complete", "")),
        "quote_memo_modified": str(quote.get("quote_memo_modified", "")),
        "term_months": int(quote["term_months"]),
        "payment_terms": str(quote.get("payment_terms", "")),
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
        "requested_deal_investment": requested_deal_investment,
        "requested_deal_investment_percent": requested_deal_investment_percent,
        "deal_investment_ae_preapproved_amount": deal_investment_preapproved_amount,
        "deal_investment_ae_preapproved_percent": deal_investment_ae_preapproved_percent,
        "deal_investment_ratio_to_ae_preapproved": deal_investment_ratio_to_ae,
    }


def get_quote_memo_modifications(data, quote_id: str):
    memo_df = data.get("quote_memo_modifications", pd.DataFrame()).copy()
    if memo_df.empty or "quote_id" not in memo_df.columns:
        return []
    quote_rows = memo_df[memo_df["quote_id"].astype(str) == str(quote_id)].copy()
    if quote_rows.empty:
        return []
    return quote_rows.fillna("").to_dict(orient="records")


def classify_clause_modifications(memo_modifications: List[Dict], approval_rules: Dict):
    clause_rules = approval_rules.get("clause_modification_rules", {})
    classifications = []

    for memo in memo_modifications:
        topic = str(memo.get("memo_topic", "")).strip()
        rule = clause_rules.get(topic, {})
        classifications.append({
            "Clause Topic": topic or "Unclassified",
            "Approval Rule": rule.get("approval_rule", "%s Modification" % (topic or "Clause")),
            "Approver": rule.get("approval_required", "Legal"),
            "Reason": rule.get("reason", "Modified order form memo language requires review."),
        })

    return classifications


def check_quote_approvals(quote, qli, approval_rules, memo_classifications=None):
    reasons = []
    approval_details = []
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

    def add_approval(rule: str, approver: str, reason: str):
        reasons.append("%s approval required: %s" % (approver, reason))
        approval_details.append({
            "Approval Rule": rule,
            "Approver": approver,
            "Reason": reason,
        })
        update_highest(approver)

    cross_required = discount_summary["cross_service_approver_required"]
    if cross_required != "AE" and cross_required != "Unknown":
        add_approval(
            "Cross-Service Discount",
            cross_required,
            "Cross-service discount request of %.1f%% exceeds AE preapproved authority." % discount_summary["cross_service_requested_discount"],
        )

    add_on_required = discount_summary["add_on_approver_required"]
    if add_on_required != "AE" and add_on_required != "Unknown":
        add_approval(
            "Add-on Discount",
            add_on_required,
            "Add-on discount request of %.1f%% exceeds AE preapproved authority." % discount_summary["add_on_requested_discount"],
        )

    short_term_rule = approval_rules.get("short_term_high_commit")
    if short_term_rule:
        conditions = short_term_rule.get("conditions", {})
        required_term = int(conditions.get("term_months", 0))
        min_annual_commit = float(conditions.get("min_annual_commit", 0))
        approval_required = short_term_rule.get("approval_required", "CRO")
        reason = short_term_rule.get("reason", "Short-term high-value deal requires review.")

        if int(quote["term_months"]) == required_term and float(quote["annual_commit"]) >= min_annual_commit:
            add_approval("Short-Term High Commit", approval_required, reason)

    payment_terms_rule = approval_rules.get("payment_terms_rule", {})
    required_payment_terms = payment_terms_rule.get("condition", {}).get("required_payment_terms", "Net 30")
    payment_terms = str(quote.get("payment_terms", "")).strip()
    if payment_terms.lower().replace(" ", "") != required_payment_terms.lower().replace(" ", ""):
        add_approval(
            payment_terms_rule.get("approval_rule", "Non-standard Payment Terms"),
            payment_terms_rule.get("approval_required", "Finance"),
            "Payment terms are %s; standard policy requires %s." % (payment_terms or "blank", required_payment_terms),
        )

    deal_investment_rule = approval_rules.get("deal_investment_rule", {})
    max_preapproved_percent = float(
        deal_investment_rule.get("conditions", {}).get("max_preapproved_percent_of_annual_commit", 10)
    )
    if discount_summary["requested_deal_investment_percent"] > max_preapproved_percent:
        add_approval(
            deal_investment_rule.get("approval_rule", "Deal Investment Threshold"),
            deal_investment_rule.get("approval_required", "CRO"),
            "Requested deal investment is %.1f%% of annual commit, above the %.1f%% preapproved threshold." % (
                discount_summary["requested_deal_investment_percent"],
                max_preapproved_percent,
            ),
        )

    demand_planning_rule = approval_rules.get("demand_planning_rule", {})
    demand_planning_required_value = str(
        demand_planning_rule.get("conditions", {}).get("demand_planning_complete", "No")
    ).strip().lower()
    demand_planning_value = str(quote.get("demand_planning_complete", "")).strip().lower()
    requested_deal_investment = float(discount_summary.get("requested_deal_investment", 0) or 0)
    if demand_planning_value == demand_planning_required_value and requested_deal_investment > 0:
        add_approval(
            demand_planning_rule.get("approval_rule", "Demand Planning Review"),
            demand_planning_rule.get("approval_required", "Practice Manager"),
            demand_planning_rule.get(
                "reason",
                "Demand planning is incomplete while deal investment funds are requested; Practice Manager review is required to validate PS&T capacity and scope."
            ),
        )

    for classification in memo_classifications or []:
        add_approval(
            classification.get("Approval Rule", "Clause Modification"),
            classification.get("Approver", "Legal"),
            classification.get("Reason", "Modified order form memo language requires review."),
        )

    return {
        "reasons": reasons,
        "approval_details": approval_details,
        "highest_required_approval": highest_required_approval,
        "discount_summary": discount_summary,
    }


def apply_annualized_consumption_rule(approval_result: Dict, quote, consumption_summary: Dict, approval_rules: Dict) -> Dict:
    rule = approval_rules.get("annualized_consumption_rule", {})
    if not rule:
        return approval_result

    try:
        annual_commit = float(quote.get("annual_commit", 0) or 0)
        annualized_t3m = float(consumption_summary.get("annualized_trailing_3_months", 0) or 0)
    except Exception:
        return approval_result

    if annual_commit <= 0 or annualized_t3m <= 0:
        return approval_result

    if annual_commit < annualized_t3m:
        approver = rule.get("approval_required", "Finance")
        approval_rule = rule.get("approval_rule", "Annual Commit Below Annualized T3M")
        reason_template = rule.get(
            "reason",
            "Proposed annual commit is below the customer annualized trailing 3-month run-rate, indicating potential under-sizing, demand planning risk, or missed expansion opportunity."
        )
        reason = "%s Annual commit is $%s versus annualized T3M of $%s." % (
            reason_template,
            format(annual_commit, ",.0f"),
            format(annualized_t3m, ",.0f"),
        )

        approval_result.setdefault("reasons", []).append("%s approval required: %s" % (approver, reason))
        approval_result.setdefault("approval_details", []).append({
            "Approval Rule": approval_rule,
            "Approver": approver,
            "Reason": reason,
        })

        current_highest = approval_result.get("highest_required_approval")
        if approver in APPROVAL_HIERARCHY:
            if current_highest not in APPROVAL_HIERARCHY:
                approval_result["highest_required_approval"] = approver
            elif APPROVAL_HIERARCHY.index(approver) > APPROVAL_HIERARCHY.index(current_highest):
                approval_result["highest_required_approval"] = approver

    return approval_result


def get_consumption_summary(data, account_id: str):
    contracts = data["contracts"].copy()
    usage = data["consumption_usage"].copy()

    account_contracts = contracts[contracts["account_id"] == account_id].copy()
    if account_contracts.empty:
        return {
            "status": "No contract found",
            "message": "This account has no matching contract records.",
            "annualized_trailing_3_months": 0,
        }

    account_contract_ids = account_contracts["contract_id"].tolist()
    account_usage = usage[usage["contract_id"].isin(account_contract_ids)].copy()

    latest_contract = account_contracts.sort_values("end_date").iloc[-1]
    total_commit_value = float(latest_contract["total_commit_value"])
    term_months = int(latest_contract["term_months"])

    trailing_3_months = float(latest_contract.get("trailing_3_months", 0) or 0)
    annualized_t3m = float(latest_contract.get("annualized_t3m", 0) or 0)

    if annualized_t3m <= 0 and trailing_3_months > 0:
        annualized_t3m = trailing_3_months * 4

    if account_usage.empty:
        return {
            "status": "No usage found",
            "message": "This account has no matching monthly consumption records.",
            "total_commit_value": int(total_commit_value),
            "trailing_3_months": round(trailing_3_months, 2),
            "annualized_trailing_3_months": round(annualized_t3m, 2),
        }

    account_usage["month_dt"] = pd.to_datetime(account_usage["month"], format=DATE_FORMAT)
    total_consumed = float(account_usage["consumed_value"].sum())
    latest_month = account_usage["month_dt"].max()
    months_observed = int(account_usage["month_dt"].nunique())

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
        "trailing_3_months": round(trailing_3_months, 2),
        "annualized_trailing_3_months": round(annualized_t3m, 2),
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

    median_discount = round(float(peer_quotes["cross_service_discount_percent"].median()), 2)
    max_discount = round(float(peer_quotes["cross_service_discount_percent"].max()), 2)
    median_annual_commit = round(float(peer_quotes["annual_commit"].median()), 2)
    peer_count = int(len(peer_quotes))

    sample_columns = [
        "quote_id",
        "account_name",
        "industry",
        "region",
        "annual_commit",
        "term_months",
        "payment_terms",
        "demand_planning_complete",
        "quote_memo_modified",
        "total_contract_value",
        "requested_deal_investment",
        "cross_service_discount_percent",
    ]
    sample_columns = [col for col in sample_columns if col in peer_quotes.columns]

    peer_quotes_sample = peer_quotes.head(limit)[sample_columns].to_dict(orient="records")

    return {
        "selected_industry": selected_industry,
        "industry_benchmark_summary": {
            "peer_quote_count": peer_count,
            "median_discount_percent": median_discount,
            "max_discount_percent": max_discount,
            "median_annual_commit": median_annual_commit,
        },
        "peer_quotes": peer_quotes_sample,
    }


def build_review_payload(data, quote_id: str):
    quote, opportunity, account, qli = get_quote_package(data, quote_id)
    memo_modifications = get_quote_memo_modifications(data, quote_id)
    memo_classifications = classify_clause_modifications(memo_modifications, data["approval_rules"])

    approval_result = check_quote_approvals(
        quote,
        qli,
        data["approval_rules"],
        memo_classifications=memo_classifications,
    )
    consumption_summary = get_consumption_summary(data, account["account_id"])
    approval_result = apply_annualized_consumption_rule(
        approval_result,
        quote,
        consumption_summary,
        data["approval_rules"],
    )
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
            "demand_planning_complete": str(quote.get("demand_planning_complete", "")),
            "quote_memo_modified": str(quote.get("quote_memo_modified", "")),
            "term_months": int(quote["term_months"]),
            "payment_terms": str(quote.get("payment_terms", "")),
            "total_contract_value": int(quote["total_contract_value"]),
            "requested_deal_investment": float(quote.get("requested_deal_investment", 0) or 0),
            "cross_service_discount_percent": float(quote["cross_service_discount_percent"]),
            "business_justification": str(quote.get("business_justification", "")),
        },
        "quote_line_items": qli[[
            "product_name",
            "discount_percent",
            "discount_type",
        ]].to_dict(orient="records"),
        "approval_reasons": approval_result["reasons"],
        "approval_details": approval_result["approval_details"],
        "highest_required_approval": approval_result["highest_required_approval"],
        "discount_summary": approval_result["discount_summary"],
        "consumption_summary": consumption_summary,
        "industry_quote_context": industry_context,
        "clause_modifications": memo_modifications,
        "clause_modification_classification": memo_classifications,
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
4. Industry peer median comparison
5. Consumption and demand planning signal
6. Clause modification signal
7. Potential deal levers to explore before routing for approval
8. Recommended next step

Important:
- Do not override the business rules decision
- Use the business_justification from the quote as context
- Recommend potential deal levers before recommending approval routing when possible
- Use industry peer medians rather than averages when comparing against peer quotes
- Consider annualized trailing 3-month values from the contracts data
- Consider clause modifications and route Legal or Finance review where applicable
- Consider demand planning completeness when requested deal investment funds may affect PS&T capacity or non-product delivery
- Consider flexible one-time investments, ramped commitment models, true-up terms and conditions, renewal pricing protection, limitations on scope of use, and inclusion of publicity rights
- Keep the tone practical and executive-friendly
- Keep the response under 140 words
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
