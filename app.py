import streamlit as st
from pathlib import Path
import pandas as pd
from main import load_data, build_review_payload, explain_with_openai

st.set_page_config(page_title="AI Deal Desk POC", layout="wide")

st.title("AI Deal Desk POC")

data_dir = Path("data")
data = load_data(data_dir)

accounts_df = data["accounts"]
opportunities_df = data["opportunities"]
quotes_df = data["quotes"]

account_names = accounts_df["account_name"].sort_values().tolist()

selected_account_name = st.selectbox("Select an Account", account_names)

selected_account_row = accounts_df[
    accounts_df["account_name"] == selected_account_name
].iloc[0]

selected_account_id = selected_account_row["account_id"]

account_opportunities = opportunities_df[
    opportunities_df["account_id"] == selected_account_id
]

account_opportunity_ids = account_opportunities["opportunity_id"].tolist()

account_quotes = quotes_df[
    quotes_df["opportunity_id"].isin(account_opportunity_ids)
]

if account_quotes.empty:
    st.warning("No quotes found for this account.")
else:
    quote_ids = account_quotes["quote_id"].tolist()

    selected_quote_id = st.selectbox("Select a Quote", quote_ids)

    selected_quote = account_quotes[
        account_quotes["quote_id"] == selected_quote_id
    ].iloc[0]

    st.subheader("Quote Details")

    annual_commit = float(selected_quote["annual_commit"])
    requested_discount = float(selected_quote["cross_service_discount_percent"])
    term_months = int(selected_quote["term_months"])

    matrix = data["approval_rules"].get("cross_service_preapproved_discount_matrix", [])
    approver_required = "Unknown"
    approver_max_discount = "N/A"

    for tier in matrix:
        min_commit = float(tier["min_annual_commit"])
        max_commit = tier["max_annual_commit"]

        in_range = (
            annual_commit >= min_commit
            if max_commit is None
            else min_commit <= annual_commit < float(max_commit)
        )

        if in_range:
            approvals = tier.get("approvals", {})

            ae_limit = float(approvals.get("AE", 0))
            manager_limit = float(approvals.get("Manager", 0))
            director_limit = float(approvals.get("Director", 0))
            cro_limit = float(approvals.get("CRO", 0))
            ceo_limit = float(approvals.get("CEO", 999))

            if requested_discount <= ae_limit:
                approver_required = "AE"
                approver_max_discount = f"{ae_limit:.0f}%"
            elif requested_discount <= manager_limit:
                approver_required = "Manager"
                approver_max_discount = f"{manager_limit:.0f}%"
            elif requested_discount <= director_limit:
                approver_required = "Director"
                approver_max_discount = f"{director_limit:.0f}%"
            elif requested_discount <= cro_limit:
                approver_required = "CRO"
                approver_max_discount = f"{cro_limit:.0f}%"
            else:
                approver_required = "CEO"
                approver_max_discount = f"{ceo_limit:.0f}%"

            break

    quote_details_df = pd.DataFrame([{
        "Annual Commit": f"${annual_commit:,.0f}",
        "Term (months)": term_months,
        "Requested Discount": f"{requested_discount:.1f}%",
        "Approver Required": approver_required,
        "Approver Max Discount": approver_max_discount
    }])

    st.dataframe(quote_details_df, hide_index=True, use_container_width=True)

    business_case_justification = st.text_area(
        "Business Case Justification",
        height=140
    )

    if st.button("Evaluate Quote", type="primary"):

        payload = build_review_payload(data, selected_quote_id)
        payload["business_case_justification"] = business_case_justification

        # ✅ 1. CHART FIRST
        st.subheader("Requested Quote vs Industry Peers")

        industry_context = payload["industry_quote_context"]
        selected_discount = float(
            payload["quote"]["cross_service_discount_percent"]
        )

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
            col1.metric("Selected Discount", f"{selected_discount:.1f}%")
            col2.metric("Industry Avg", f"{benchmark['average_discount_percent']:.1f}%")
            col3.metric("Peer Quotes", benchmark["peer_quote_count"])

        else:
            st.info("No industry peer data available.")

        # ✅ 2. DECISION SECOND
        st.subheader("Approval Decision")

        if payload["approval_reasons"]:
            st.error("Approval required")

            if payload.get("highest_required_approval"):
                st.warning(f"Highest Approval Required: {payload['highest_required_approval']}")

            for reason in payload["approval_reasons"]:
                st.write("-", reason)

        else:
            st.success("No approval required")

        # ✅ 3. AI LAST
        st.subheader("AI Deal Desk Summary")

        try:
            summary, usage = explain_with_openai(payload)
            st.write(summary)
        except Exception as e:
            st.warning(f"OpenAI error: {e}")

        # Collapsed sections
        with st.expander("Consumption Summary", expanded=False):
            st.json(payload["consumption_summary"])

        with st.expander("Industry Peer Context", expanded=False):
            st.json(payload["industry_quote_context"])

        with st.expander("Structured Review Payload", expanded=False):
            st.json(payload)