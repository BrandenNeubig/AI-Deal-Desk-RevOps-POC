import html
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from main import (
    load_data,
    build_review_payload,
    explain_with_openai,
    get_pending_quotes,
    get_region_quote_counts,
)


def split_recommendations_for_bullets(text: str) -> list:
    if not text or not str(text).strip():
        return []

    cleaned = str(text).strip().rstrip(".")
    if ";" in cleaned:
        parts = re.split(r"\s*;\s*", cleaned)
    elif cleaned.count(",") >= 2:
        parts = re.split(r"\s*,\s*", cleaned)
    else:
        return []

    items = []
    for part in parts:
        item = part.strip().strip("-• ").strip()
        item = re.sub(r"^(and|then)\s+", "", item, flags=re.IGNORECASE).strip()
        if item:
            items.append(item)

    return items if len(items) > 1 else []


def render_ai_summary_table(ai_summary_df: pd.DataFrame) -> str:
    table_style = "border-collapse: collapse; width: 100%; border: 1px solid #e5e7eb;"
    header_style = "background-color: #f8fafc; color: #374151; text-align: left; padding: 10px; border: 1px solid #e5e7eb; font-weight: 600;"
    cell_style = "vertical-align: top; padding: 10px; border: 1px solid #e5e7eb; color: #111827;"
    area_style = cell_style + " width: 28%; font-weight: 500;"

    rows = [
        f'<table style="{table_style}">',
        "<thead><tr>",
        f'<th style="{header_style}">Review Area</th>',
        f'<th style="{header_style}">Summary</th>',
        "</tr></thead><tbody>",
    ]

    for _, row in ai_summary_df.iterrows():
        review_area = str(row.get("Review Area", ""))
        summary = str(row.get("Summary", ""))
        bullet_items = []

        if review_area in ["Potential Deal Levers", "Recommended Next Step", "Clause Modification Signal"]:
            bullet_items = split_recommendations_for_bullets(summary)

        if bullet_items:
            summary_html = "<ul style='margin: 0; padding-left: 1.2rem;'>" + "".join(
                f"<li>{html.escape(item)}</li>" for item in bullet_items
            ) + "</ul>"
        else:
            summary_html = html.escape(summary)

        rows.extend([
            "<tr>",
            f'<td style="{area_style}">{html.escape(review_area)}</td>',
            f'<td style="{cell_style}">{summary_html}</td>',
            "</tr>",
        ])

    rows.append("</tbody></table>")
    return "".join(rows)


def render_wrapped_table(df: pd.DataFrame, column_widths: dict = None) -> str:
    """Render a dataframe as an HTML table with wrapped, vertically expanding cells."""
    column_widths = column_widths or {}
    table_style = (
        "border-collapse: collapse; width: 100%; border: 1px solid #e5e7eb; "
        "table-layout: fixed; margin-bottom: 1rem;"
    )
    header_style = (
        "background-color: #f8fafc; color: #374151; text-align: left; padding: 10px; "
        "border: 1px solid #e5e7eb; font-weight: 600; white-space: normal; "
        "overflow-wrap: break-word; vertical-align: top;"
    )
    cell_style = (
        "vertical-align: top; padding: 10px; border: 1px solid #e5e7eb; color: #111827; "
        "white-space: normal; overflow-wrap: break-word; word-break: normal; line-height: 1.45;"
    )

    rows = [f'<table style="{table_style}">', "<thead><tr>"]
    for col in df.columns:
        width = column_widths.get(col)
        style = header_style + (f" width: {width};" if width else "")
        rows.append(f'<th style="{style}">{html.escape(str(col))}</th>')
    rows.append("</tr></thead><tbody>")

    for _, row in df.iterrows():
        rows.append("<tr>")
        for col in df.columns:
            value = row.get(col, "")
            if pd.isna(value):
                value = ""
            rows.append(f'<td style="{cell_style}">{html.escape(str(value))}</td>')
        rows.append("</tr>")

    rows.append("</tbody></table>")
    return "".join(rows)


def build_ai_summary_table(summary: str) -> pd.DataFrame:
    review_areas = [
        "Approval Status",
        "Key Reason(s)",
        "Business Justification Quality",
        "Industry Peer Median Comparison",
        "Consumption and Demand Planning Signal",
        "Clause Modification Signal",
        "Potential Deal Levers",
        "Recommended Next Step",
    ]

    label_aliases = {
        "approval status": "Approval Status",
        "key reason": "Key Reason(s)",
        "key reasons": "Key Reason(s)",
        "business justification quality": "Business Justification Quality",
        "peer discount comparison": "Industry Peer Median Comparison",
        "industry peer median comparison": "Industry Peer Median Comparison",
        "consumption signal": "Consumption and Demand Planning Signal",
        "consumption and demand planning signal": "Consumption and Demand Planning Signal",
        "clause modification signal": "Clause Modification Signal",
        "potential deal levers": "Potential Deal Levers",
        "recommended next step": "Recommended Next Step",
    }

    if not summary or not str(summary).strip():
        return pd.DataFrame([{
            "Review Area": "AI Summary",
            "Summary": "No AI summary was returned.",
        }])

    lines = [line.strip() for line in str(summary).splitlines() if line.strip()]
    rows = []

    for line in lines:
        cleaned = line.lstrip("-• ").strip()

        if len(cleaned) > 2 and cleaned[0].isdigit() and cleaned[1] in [".", ")"]:
            cleaned = cleaned[2:].strip()

        cleaned = cleaned.replace("**", "").strip()

        review_area = None
        summary_text = cleaned

        if ":" in cleaned:
            label, value = cleaned.split(":", 1)
            normalized_label = label.strip().lower()
            review_area = label_aliases.get(normalized_label)
            summary_text = value.strip()

        if not review_area:
            area_index = len(rows)
            review_area = review_areas[area_index] if area_index < len(review_areas) else "Additional Note"

        rows.append({
            "Review Area": review_area,
            "Summary": summary_text,
        })

    if not rows:
        rows.append({
            "Review Area": "AI Summary",
            "Summary": str(summary).strip(),
        })

    return pd.DataFrame(rows)


def format_currency(value) -> str:
    try:
        if pd.isna(value):
            return "N/A"
        return "${:,.0f}".format(float(value))
    except Exception:
        return "N/A"


def format_percent(value) -> str:
    try:
        if pd.isna(value):
            return "N/A"
        return "{:.1f}%".format(float(value))
    except Exception:
        return "N/A"


def format_number(value) -> str:
    try:
        if pd.isna(value):
            return "N/A"
        return "{:.1f}".format(float(value))
    except Exception:
        return "N/A"



def _escape(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return html.escape(str(value))


def _currency(value) -> str:
    try:
        return "${:,.0f}".format(float(value or 0))
    except Exception:
        return "$0"


def _percent(value) -> str:
    try:
        return "{:.1f}%".format(float(value or 0))
    except Exception:
        return "0.0%"


def render_quote_template(payload: dict, template_path: Path) -> str:
    """Render the external quote template using the selected quote payload."""
    if template_path.exists():
        template = template_path.read_text()
    else:
        template = """
        <div style='border:1px solid #e5e7eb;border-radius:12px;padding:16px;'>
            <h3>Luna y Sol Shepherd Systems Quote Template</h3>
            <p><strong>Quote ID:</strong> {{quote_id}}</p>
            <p><strong>Account:</strong> {{account_name}}</p>
            <p><strong>Annual Commit:</strong> {{annual_commit}}</p>
        </div>
        """

    account = payload.get("account", {})
    opportunity = payload.get("opportunity", {})
    quote = payload.get("quote", {})
    summary = payload.get("discount_summary", {})
    consumption_summary = payload.get("consumption_summary", {})

    clause_rows = []
    for row in payload.get("clause_modifications", []):
        clause_rows.append(
            "<tr>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;'>{_escape(row.get('clause_topic', ''))}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;line-height:1.45;'>{_escape(row.get('original_clause', ''))}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;line-height:1.45;'>{_escape(row.get('modified_clause', ''))}</td>"
            "</tr>"
        )
    if not clause_rows:
        clause_rows.append("<tr><td colspan='3' style='padding:8px;border:1px solid #e5e7eb;'>No clause modifications.</td></tr>")

    approval_rows = []
    for row in payload.get("approval_details", []):
        approval_rows.append(
            "<tr>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;'>{_escape(row.get('Approval Rule', ''))}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;'>{_escape(row.get('Approver', ''))}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;line-height:1.45;'>{_escape(row.get('Reason', ''))}</td>"
            "</tr>"
        )
    if not approval_rows:
        approval_rows.append("<tr><td colspan='3' style='padding:8px;border:1px solid #e5e7eb;'>No approval required.</td></tr>")

    memo_rows = []
    for row in payload.get("clause_modifications", []):
        modified_clause = row.get("modified_clause", "")
        if str(modified_clause).strip():
            memo_rows.append(
                "<tr>"
                f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;width:22%;'>{_escape(row.get('clause_topic', ''))}</td>"
                f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;line-height:1.45;'>{_escape(modified_clause)}</td>"
                "</tr>"
            )

    requested_deal_investment_value = 0.0
    try:
        requested_deal_investment_value = float(quote.get("requested_deal_investment", summary.get("requested_deal_investment", 0)) or 0)
    except Exception:
        requested_deal_investment_value = 0.0

    if requested_deal_investment_value > 0:
        memo_rows.append(
            "<tr>"
            "<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;width:22%;'>Customer Investment Funds</td>"
            "<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;line-height:1.45;'>Customer investment funds must be used within twelve (12) months of the Order Form effective date. Any unused customer investment funds will expire after that period and will not roll over, convert to cash, or reduce future fees unless otherwise agreed in writing by Company. Please contact your Practice Manager for scheduling.</td>"
            "</tr>"
        )

    if not memo_rows:
        memo_rows.append("<tr><td colspan='2' style='padding:8px;border:1px solid #e5e7eb;'>No special memo terms generated for this quote.</td></tr>")

    replacements = {
        "{{quote_id}}": _escape(payload.get("quote_id", quote.get("quote_id", ""))),
        "{{opportunity_id}}": _escape(opportunity.get("opportunity_id", "")),
        "{{close_date}}": _escape(opportunity.get("close_date", "")),
        "{{account_name}}": _escape(account.get("account_name", "")),
        "{{industry}}": _escape(account.get("industry", "")),
        "{{region}}": _escape(account.get("region", "")),
        "{{opportunity_type}}": _escape(opportunity.get("type", "")),
        "{{annual_commit}}": _currency(quote.get("annual_commit", summary.get("annual_commit", 0))),
        "{{total_contract_value}}": _currency(quote.get("total_contract_value", summary.get("total_contract_value", 0))),
        "{{annualized_t3m}}": _currency(consumption_summary.get("annualized_trailing_3_months", 0)),
        "{{term_months}}": _escape(quote.get("term_months", summary.get("term_months", ""))),
        "{{payment_terms}}": _escape(quote.get("payment_terms", summary.get("payment_terms", ""))),
        "{{demand_planning_complete}}": _escape(quote.get("demand_planning_complete", summary.get("demand_planning_complete", ""))),
        "{{quote_memo_modified}}": _escape(quote.get("quote_memo_modified", summary.get("quote_memo_modified", ""))),
        "{{cross_service_discount}}": _percent(quote.get("cross_service_discount_percent", summary.get("cross_service_requested_discount", 0))),
        "{{add_on_discount}}": _percent(summary.get("add_on_requested_discount", 0)),
        "{{requested_deal_investment}}": _currency(quote.get("requested_deal_investment", summary.get("requested_deal_investment", 0))),
        "{{requested_deal_investment_percent}}": _percent(summary.get("requested_deal_investment_percent", 0)),
        "{{clause_rows}}": "".join(clause_rows),
        "{{memo_rows}}": "".join(memo_rows),
        "{{approval_rows}}": "".join(approval_rows),
    }

    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
def build_industry_peer_comparison_table(data, payload, industry_context, discount_summary) -> pd.DataFrame:
    quotes = data["quotes"].copy()
    opportunities = data["opportunities"].copy()
    accounts = data["accounts"].copy()

    selected_quote_id = payload.get("quote_id")
    selected_industry = industry_context.get("selected_industry") or payload.get("account", {}).get("industry")

    quote_context = quotes.merge(
        opportunities[["opportunity_id", "account_id"]],
        on="opportunity_id",
        how="left",
    ).merge(
        accounts[["account_id", "account_name", "industry", "region"]],
        on="account_id",
        how="left",
    )

    peer_quotes = quote_context[
        (quote_context["industry"].astype(str) == str(selected_industry))
        & (quote_context["quote_id"].astype(str) != str(selected_quote_id))
    ].copy()

    for col in [
        "annual_commit",
        "total_contract_value",
        "term_months",
        "cross_service_discount_percent",
        "requested_deal_investment",
    ]:
        if col in peer_quotes.columns:
            peer_quotes[col] = pd.to_numeric(peer_quotes[col], errors="coerce")

    if "requested_deal_investment" in peer_quotes.columns and "annual_commit" in peer_quotes.columns:
        peer_quotes["requested_deal_investment_percent"] = peer_quotes.apply(
            lambda row: (row["requested_deal_investment"] / row["annual_commit"] * 100)
            if pd.notna(row.get("annual_commit")) and float(row.get("annual_commit", 0)) > 0
            else None,
            axis=1,
        )

    peer_count = int(len(peer_quotes))

    selected_quote = payload.get("quote", {})
    selected_annual_commit = float(selected_quote.get("annual_commit", discount_summary.get("annual_commit", 0)))
    selected_deal_investment = float(discount_summary.get("requested_deal_investment", selected_quote.get("requested_deal_investment", 0)) or 0)
    selected_deal_investment_percent = discount_summary.get("requested_deal_investment_percent")
    if selected_deal_investment_percent is None and selected_annual_commit > 0:
        selected_deal_investment_percent = selected_deal_investment / selected_annual_commit * 100

    metric_definitions = [
        ("Cross-Service Discount %", float(selected_quote.get("cross_service_discount_percent", 0)), "cross_service_discount_percent", format_percent),
        ("Annual Commit", selected_annual_commit, "annual_commit", format_currency),
        ("Total Contract Value", float(selected_quote.get("total_contract_value", 0)), "total_contract_value", format_currency),
        ("Term Months", float(selected_quote.get("term_months", discount_summary.get("term_months", 0))), "term_months", format_number),
        ("Requested Deal Investment", selected_deal_investment, "requested_deal_investment", format_currency),
        ("Requested Deal Investment %", selected_deal_investment_percent, "requested_deal_investment_percent", format_percent),
    ]

    rows = []
    for metric, selected, column, formatter in metric_definitions:
        if peer_count > 0 and column in peer_quotes.columns:
            peer_median = peer_quotes[column].median()
            peer_high = peer_quotes[column].max()
        else:
            peer_median = None
            peer_high = None

        rows.append({
            "Commercial Metric": metric,
            "Selected Quote": formatter(selected),
            "Industry Peer Median": formatter(peer_median),
            "Industry Peer High": formatter(peer_high),
            "Peer Count": peer_count,
        })

    return pd.DataFrame(rows)


def build_redline_display_rows(clause_modifications):
    rows = []
    for item in clause_modifications:
        rows.append({
            "Clause Topic": item.get("memo_topic", ""),
            "Original Clause": item.get("original_clause", ""),
            "Modified Clause": item.get("modified_clause", ""),
        })
    return pd.DataFrame(rows)


st.set_page_config(page_title="Luna y Sol Shepherd Systems", page_icon="🐕", layout="wide")

logo_path = Path(__file__).with_name("logo.png")

header_col1, header_col2 = st.columns([1, 8])
with header_col1:
    if logo_path.exists():
        st.image(str(logo_path), width=110)
with header_col2:
    st.title("Luna y Sol Shepherd Systems")
    st.caption("AI Deal Desk Assistant POC")

data_dir = Path("data")
data = load_data(data_dir)

pending_quotes_df = get_pending_quotes(data)
region_counts_df = get_region_quote_counts(data)

DEAL_DESK_SLA_HOURS = 4

if "quote_age_hours" in pending_quotes_df.columns:
    pending_quotes_df["quote_age_hours"] = pd.to_numeric(
        pending_quotes_df["quote_age_hours"],
        errors="coerce",
    ).fillna(0)
else:
    pending_quotes_df["quote_age_hours"] = 0

pending_quotes_df["sla_status"] = pending_quotes_df["quote_age_hours"].apply(
    lambda age: "Past SLA (>4h)" if float(age) > DEAL_DESK_SLA_HOURS else "Within SLA (≤4h)"
)

st.subheader("Pending Quote Aging by Region")
st.caption("Deal Desk SLA target: 4 hours. The chart shows pending quote volume by region, split between quotes still within SLA and quotes past SLA.")

if pending_quotes_df.empty:
    st.info("No pending quotes available.")
else:
    sla_chart_df = (
        pending_quotes_df.groupby(["region", "sla_status"], as_index=False)["quote_id"]
        .count()
        .rename(columns={"quote_id": "Pending Quotes"})
        .pivot(index="region", columns="sla_status", values="Pending Quotes")
        .fillna(0)
    )

    for col in ["Within SLA (≤4h)", "Past SLA (>4h)"]:
        if col not in sla_chart_df.columns:
            sla_chart_df[col] = 0

    sla_chart_df = sla_chart_df[["Within SLA (≤4h)", "Past SLA (>4h)"]]
    st.bar_chart(sla_chart_df)

    region_age_summary_df = (
        pending_quotes_df.groupby("region", as_index=False)
        .agg(
            **{
                "Pending Quotes": ("quote_id", "count"),
                "Average Age Hours": ("quote_age_hours", "mean"),
                "Oldest Quote Age": ("quote_age_hours", "max"),
                "Past SLA Quotes": ("sla_status", lambda values: int((values == "Past SLA (>4h)").sum())),
            }
        )
        .sort_values("region")
    )

    region_age_summary_df["Average Age Hours"] = region_age_summary_df["Average Age Hours"].map(lambda x: "{:.1f}".format(float(x)))
    region_age_summary_df["Oldest Quote Age"] = region_age_summary_df["Oldest Quote Age"].map(lambda x: "{:.0f}".format(float(x)))
    st.dataframe(region_age_summary_df, hide_index=True, use_container_width=True)

regions = ["All"] + sorted(pending_quotes_df["region"].dropna().astype(str).unique().tolist())
selected_region = st.selectbox("Select Region", regions)

filtered_pending_quotes = pending_quotes_df.copy()
if selected_region != "All":
    filtered_pending_quotes = filtered_pending_quotes[
        filtered_pending_quotes["region"].astype(str) == selected_region
    ].copy()

st.subheader("Pending Quotes")

if filtered_pending_quotes.empty:
    st.warning("No pending quotes found for the selected region.")
    st.stop()

pending_columns = [
    "quote_id",
    "account_name",
    "region",
    "industry",
    "stage",
    "type",
    "annual_commit",
    "quote_age_hours",
    "sla_status",
    "demand_planning_complete",
    "quote_memo_modified",
    "term_months",
    "payment_terms",
]
pending_columns = [col for col in pending_columns if col in filtered_pending_quotes.columns]

pending_display_df = filtered_pending_quotes[pending_columns].copy()

pending_display_df = pending_display_df.rename(
    columns={
        "quote_id": "Quote ID",
        "account_name": "Account",
        "region": "Region",
        "industry": "Industry",
        "stage": "Stage",
        "type": "Opportunity Type",
        "annual_commit": "Annual Commit",
        "quote_age_hours": "Quote Age Hours",
        "sla_status": "SLA Status",
        "demand_planning_complete": "Demand Planning Complete",
        "quote_memo_modified": "Quote Memo Modified",
        "term_months": "Term Months",
        "payment_terms": "Payment Terms",
    }
)
if "Annual Commit" in pending_display_df.columns:
    pending_display_df["Annual Commit"] = pending_display_df["Annual Commit"].map(lambda x: "${:,.0f}".format(float(x)))
if "Quote Age Hours" in pending_display_df.columns:
    pending_display_df["Quote Age Hours"] = pending_display_df["Quote Age Hours"].map(lambda x: "{:.0f}".format(float(x)))

st.dataframe(pending_display_df, hide_index=True, use_container_width=True)

selected_quote_id = st.selectbox(
    "Select Pending Quote",
    filtered_pending_quotes["quote_id"].tolist(),
)

payload = build_review_payload(data, selected_quote_id)
discount_summary = payload["discount_summary"]
business_justification = payload["quote"].get("business_justification", "")
annualized_t3m = payload.get("consumption_summary", {}).get("annualized_trailing_3_months", 0)

st.subheader("Quote Details")

table1_df = pd.DataFrame([{
    "Annual Commit": "${:,.0f}".format(discount_summary["annual_commit"]),
    "Annualized T3M": "${:,.0f}".format(float(annualized_t3m or 0)),
    "Demand Planning Complete": discount_summary.get("demand_planning_complete", ""),
    "Quote Memo Modified": discount_summary.get("quote_memo_modified", ""),
    "Term Months": discount_summary["term_months"],
    "Payment Terms": discount_summary.get("payment_terms", ""),
}])

cross_ratio = discount_summary.get("cross_service_ratio_to_ae_preapproved")
add_on_ratio = discount_summary.get("add_on_ratio_to_ae_preapproved")
deal_investment_ratio = discount_summary.get("deal_investment_ratio_to_ae_preapproved")

table2_df = pd.DataFrame([{
    "Cross Service Discount": "Cross Service Family",
    "Requested Discount": "{:.1f}%".format(discount_summary["cross_service_requested_discount"]),
    "vs AE Preapproved": "{:.2f}x".format(cross_ratio) if cross_ratio is not None else "N/A",
    "Approver Required": discount_summary["cross_service_approver_required"],
    "Approver Max Discount": discount_summary["cross_service_approver_max_discount"],
}])

table3_df = pd.DataFrame([{
    "Add-on Discount": "Add-on",
    "Requested Discount": "{:.1f}%".format(discount_summary["add_on_requested_discount"]),
    "vs AE Preapproved": "{:.2f}x".format(add_on_ratio) if add_on_ratio is not None else "N/A",
    "Approver Required": discount_summary["add_on_approver_required"],
    "Approver Max Discount": discount_summary["add_on_approver_max_discount"],
}])

table4_df = pd.DataFrame([{
    "Requested Amount": "${:,.0f}".format(discount_summary.get("requested_deal_investment", 0)),
    "Preapproved Amount": "${:,.0f}".format(discount_summary.get("deal_investment_ae_preapproved_amount", 0)),
    "Requested %": "{:.1f}%".format(discount_summary.get("requested_deal_investment_percent", 0)),
    "Preapproved %": "{:.1f}%".format(discount_summary.get("deal_investment_ae_preapproved_percent", 0)),
    "vs AE Preapproved": "{:.2f}x".format(deal_investment_ratio) if deal_investment_ratio is not None else "N/A",
}])

st.dataframe(table1_df, hide_index=True, use_container_width=True)
st.dataframe(table2_df, hide_index=True, use_container_width=True)
st.dataframe(table3_df, hide_index=True, use_container_width=True)

st.subheader("Deal Investment Details")
st.caption("Deal investment amounts are a pool of funds that can be applied as discounts for PS&T products and other non-product based products.")
st.dataframe(table4_df, hide_index=True, use_container_width=True)

st.subheader("Clause Modifications")
clause_modifications = payload.get("clause_modifications", [])
clause_classifications = payload.get("clause_modification_classification", [])
if clause_modifications:
    st.caption("Simulated redline showing customer modifications to company-favorable order form memo language.")
    redline_df = build_redline_display_rows(clause_modifications)
    st.markdown(
        render_wrapped_table(
            redline_df,
            {
                "Clause Topic": "12%",
                "Original Clause": "44%",
                "Modified Clause": "44%",
            },
        ),
        unsafe_allow_html=True,
    )
    st.caption("Classification and routing based on the modified clause topic.")
    classification_df = pd.DataFrame(clause_classifications)
    st.markdown(
        render_wrapped_table(
            classification_df,
            {
                "Clause Topic": "14%",
                "Approval Rule": "24%",
                "Approver": "14%",
                "Reason": "48%",
            },
        ),
        unsafe_allow_html=True,
    )
else:
    st.info("No clause modifications found for this quote.")

st.subheader("Business Case Justification")
if business_justification and str(business_justification).strip():
    st.write(business_justification)
else:
    st.info("No business justification provided in quotes.csv for this quote.")

if st.button("Evaluate Quote", type="primary"):
    industry_context = payload["industry_quote_context"]
    selected_industry = industry_context.get("selected_industry") or payload.get("account", {}).get("industry")
    if selected_industry and str(selected_industry).strip():
        st.subheader("Requested Quote vs %s Industry Peers" % selected_industry)
    else:
        st.subheader("Requested Quote vs Industry Peers")

    if (
        isinstance(industry_context.get("industry_benchmark_summary"), dict)
        and industry_context["industry_benchmark_summary"].get("peer_quote_count", 0) > 0
    ):
        peer_comparison_df = build_industry_peer_comparison_table(
            data,
            payload,
            industry_context,
            discount_summary,
        )
        st.caption(
            "This comparison helps with demand planning by comparing the selected quote against same-industry peer medians. "
            "Deal investment amounts are a pool of funds that can be applied as discounts for PS&T products and other non-product based products."
        )
        st.dataframe(peer_comparison_df, hide_index=True, use_container_width=True)
    else:
        st.info("No industry peer data available.")

    st.subheader("Approval Details")

    if payload["approval_details"]:
        approval_details_df = pd.DataFrame(payload["approval_details"])
        st.markdown(
            render_wrapped_table(
                approval_details_df,
                {
                    "Approval Rule": "24%",
                    "Approver": "16%",
                    "Reason": "60%",
                },
            ),
            unsafe_allow_html=True,
        )
    else:
        st.success("No approval required")

    st.subheader("AI Deal Desk Summary")

    try:
        summary, usage = explain_with_openai(payload)
        ai_summary_df = build_ai_summary_table(summary)
        st.markdown(render_ai_summary_table(ai_summary_df), unsafe_allow_html=True)
    except Exception as e:
        st.warning("OpenAI error: %s" % e)

    st.subheader("Quote Preview")
    st.caption("Customer quote template fields update from the selected quote when Evaluate Quote is clicked.")
    quote_template_html = render_quote_template(payload, Path(__file__).with_name("quote_template.html"))
    st.markdown(quote_template_html, unsafe_allow_html=True)

    st.subheader("Quote Tools")
    st.info("Transfer Quote to Customer Schedule (Coming soon)")

