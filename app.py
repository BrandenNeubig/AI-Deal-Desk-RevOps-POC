
import streamlit as st
from pathlib import Path
import pandas as pd
from main import (
    load_data,
    build_review_payload,
    explain_with_openai,
    get_pending_quotes,
    get_region_quote_counts,
)

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

st.subheader("Pending Quotes by Region")
if region_counts_df.empty:
    st.info("No pending quotes available.")
else:
    chart_df = region_counts_df.set_index("region")
    st.bar_chart(chart_df)

regions = ["All"] + sorted(region_counts_df["region"].dropna().astype(str).unique().tolist())
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

pending_display_df = filtered_pending_quotes[
    [
        "quote_id",
        "account_name",
        "region",
        "industry",
        "stage",
        "type",
        "annual_commit",
        "term_months",
    ]
].copy()

pending_display_df = pending_display_df.rename(
    columns={
        "quote_id": "Quote ID",
        "account_name": "Account",
        "region": "Region",
        "industry": "Industry",
        "stage": "Stage",
        "type": "Opportunity Type",
        "annual_commit": "Annual Commit",
        "term_months": "Term Months",
    }
)
pending_display_df["Annual Commit"] = pending_display_df["Annual Commit"].map(lambda x: "${:,.0f}".format(float(x)))

st.dataframe(pending_display_df, hide_index=True, use_container_width=True)

selected_quote_id = st.selectbox(
    "Select Pending Quote",
    filtered_pending_quotes["quote_id"].tolist(),
)

payload = build_review_payload(data, selected_quote_id)
discount_summary = payload["discount_summary"]
business_justification = payload["quote"].get("business_justification", "")

st.subheader("Quote Details")

table1_df = pd.DataFrame([{
    "Annual Commit": "${:,.0f}".format(discount_summary["annual_commit"]),
    "Term Months": discount_summary["term_months"],
}])

cross_ratio = discount_summary.get("cross_service_ratio_to_ae_preapproved")
add_on_ratio = discount_summary.get("add_on_ratio_to_ae_preapproved")

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

st.dataframe(table1_df, hide_index=True, use_container_width=True)
st.dataframe(table2_df, hide_index=True, use_container_width=True)
st.dataframe(table3_df, hide_index=True, use_container_width=True)

st.subheader("Business Case Justification")
if business_justification and str(business_justification).strip():
    st.write(business_justification)
else:
    st.info("No business justification provided in quotes.csv for this quote.")

if st.button("Evaluate Quote", type="primary"):
    st.subheader("Requested Quote vs Industry Peers")

    industry_context = payload["industry_quote_context"]
    selected_discount = float(payload["quote"]["cross_service_discount_percent"])

    if (
        isinstance(industry_context.get("industry_benchmark_summary"), dict)
        and industry_context["industry_benchmark_summary"].get("peer_quote_count", 0) > 0
    ):
        benchmark = industry_context["industry_benchmark_summary"]

        chart_df = pd.DataFrame({
            "Discount Percent": [
                selected_discount,
                float(benchmark["average_discount_percent"]),
                float(benchmark["max_discount_percent"]),
            ]
        }, index=[
            "Selected Quote",
            "Industry Average",
            "Industry Max",
        ])

        st.bar_chart(chart_df)

        col1, col2, col3 = st.columns(3)
        col1.metric("Selected Discount", "{:.1f}%".format(selected_discount))
        col2.metric("Industry Avg", "{:.1f}%".format(benchmark["average_discount_percent"]))
        col3.metric("Peer Quotes", benchmark["peer_quote_count"])
    else:
        st.info("No industry peer data available.")

    st.subheader("Approval Decision")

    if payload["approval_reasons"]:
        st.error("Approval required")
        if payload.get("highest_required_approval"):
            st.warning("Highest Approval Required: %s" % payload["highest_required_approval"])
        for reason in payload["approval_reasons"]:
            st.write("-", reason)
    else:
        st.success("No approval required")

    st.subheader("AI Deal Desk Summary")

    try:
        summary, usage = explain_with_openai(payload)
        st.write(summary)
    except Exception as e:
        st.warning("OpenAI error: %s" % e)

    with st.expander("Consumption Summary", expanded=False):
        st.json(payload["consumption_summary"])

    with st.expander("Industry Peer Context", expanded=False):
        st.json(payload["industry_quote_context"])

    with st.expander("Structured Review Payload", expanded=False):
        st.json(payload)
