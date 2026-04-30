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
    recommend_pending_quote,
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
            if isinstance(value, (list, tuple, set)):
                value = ", ".join(str(item) for item in value)
            else:
                try:
                    if pd.isna(value):
                        value = ""
                except Exception:
                    value = str(value)
            rows.append(f'<td style="{cell_style}">{html.escape(str(value))}</td>')
        rows.append("</tr>")

    rows.append("</tbody></table>")
    return "".join(rows)


def build_approval_packet_pdf(payload: dict, discount_summary: dict, support_reason: str, ai_summary_df: pd.DataFrame = None) -> bytes:
    """Build a lightweight PDF approval packet for download and future Slack upload."""
    try:
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError as exc:
        raise ImportError("reportlab is required to generate approval packet PDFs. Install it with: python3 -m pip install reportlab") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]
    body_style.wordWrap = "CJK"

    def clean(value) -> str:
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        return str(value)

    def money(value) -> str:
        try:
            return "${:,.0f}".format(float(value or 0))
        except Exception:
            return "$0"

    def pct(value) -> str:
        try:
            return "{:.1f}%".format(float(value or 0))
        except Exception:
            return "0.0%"

    def para(value):
        return Paragraph(clean(value).replace("\n", "<br/>") or "-", body_style)

    def section(title: str):
        story.append(Spacer(1, 0.16 * inch))
        story.append(Paragraph(title, heading_style))

    def simple_table(rows, col_widths=None):
        table = Table(rows, colWidths=col_widths, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)

    account = payload.get("account", {})
    quote = payload.get("quote", {})
    opportunity = payload.get("opportunity", {})
    consumption = payload.get("consumption_summary", {})

    story = []
    story.append(Paragraph("Luna y Sol Approval Packet", title_style))
    story.append(Paragraph("Generated approval support packet for human-reviewed Deal Desk workflow routing.", body_style))

    section("Support Request")
    story.append(para(support_reason))

    section("Quote Overview")
    simple_table([
        [para("Field"), para("Value")],
        [para("Quote ID"), para(payload.get("quote_id", quote.get("quote_id", "")))],
        [para("Account"), para(account.get("account_name", ""))],
        [para("Region"), para(account.get("region", ""))],
        [para("Industry"), para(account.get("industry", ""))],
        [para("Opportunity Type"), para(opportunity.get("type", ""))],
        [para("Annual Commit"), para(money(discount_summary.get("annual_commit", quote.get("annual_commit", 0))))],
        [para("Total Contract Value"), para(money(discount_summary.get("total_contract_value", quote.get("total_contract_value", 0))))],
        [para("Annualized T3M"), para(money(consumption.get("annualized_trailing_3_months", 0)))],
        [para("Term Months"), para(discount_summary.get("term_months", quote.get("term_months", "")))],
        [para("Payment Terms"), para(discount_summary.get("payment_terms", quote.get("payment_terms", "")))],
        [para("Rollover %"), para(pct(discount_summary.get("requested_rollover", quote.get("requested_rollover", 0))))],
        [para("Demand Planning Complete"), para(discount_summary.get("demand_planning_complete", quote.get("demand_planning_complete", "")))],
        [para("Quote Memo Modified"), para(discount_summary.get("quote_memo_modified", quote.get("quote_memo_modified", "")))],
    ], [2.0 * inch, 5.0 * inch])

    section("Commercial Review")
    simple_table([
        [para("Commercial Metric"), para("Requested"), para("vs AE Preapproved"), para("Approver Required"), para("Approver Max")],
        [
            para("Cross-Service Discount"),
            para(pct(discount_summary.get("cross_service_requested_discount", 0))),
            para("{:.2f}x".format(discount_summary.get("cross_service_ratio_to_ae_preapproved")) if discount_summary.get("cross_service_ratio_to_ae_preapproved") is not None else "N/A"),
            para(discount_summary.get("cross_service_approver_required", "")),
            para(discount_summary.get("cross_service_approver_max_discount", "")),
        ],
        [
            para("Add-on Discount"),
            para(pct(discount_summary.get("add_on_requested_discount", 0))),
            para("{:.2f}x".format(discount_summary.get("add_on_ratio_to_ae_preapproved")) if discount_summary.get("add_on_ratio_to_ae_preapproved") is not None else "N/A"),
            para(discount_summary.get("add_on_approver_required", "")),
            para(discount_summary.get("add_on_approver_max_discount", "")),
        ],
        [
            para("Requested Rollover"),
            para(pct(discount_summary.get("requested_rollover", quote.get("requested_rollover", 0)))),
            para("N/A"),
            para("Finance Review" if float(discount_summary.get("requested_rollover", quote.get("requested_rollover", 0)) or 0) > 0 else "N/A"),
            para("N/A"),
        ],
        [
            para("Requested Deal Investment"),
            para(money(discount_summary.get("requested_deal_investment", 0))),
            para("{:.2f}x".format(discount_summary.get("deal_investment_ratio_to_ae_preapproved")) if discount_summary.get("deal_investment_ratio_to_ae_preapproved") is not None else "N/A"),
            para("Policy Review"),
            para(money(discount_summary.get("deal_investment_ae_preapproved_amount", 0))),
        ],
    ], [1.6 * inch, 1.2 * inch, 1.2 * inch, 1.5 * inch, 1.2 * inch])

    section("Approval Requests")
    approval_details = payload.get("approval_details", [])
    if approval_details:
        approval_rows = [[para("Approval Rule"), para("Approver"), para("Reason")]]
        for item in approval_details:
            approval_rows.append([
                para(item.get("Approval Rule", "")),
                para(item.get("Approver", "")),
                para(item.get("Reason", "")),
            ])
        simple_table(approval_rows, [1.7 * inch, 1.3 * inch, 4.0 * inch])
    else:
        story.append(para("No approval required."))

    section("Business Case Justification")
    story.append(para(quote.get("business_justification", "No business justification provided.")))

    section("Clause / Legal Review")
    clause_modifications = payload.get("clause_modifications", [])
    if clause_modifications:
        clause_rows = [[para("Clause Topic"), para("Original Clause"), para("Modified Clause")]]
        for item in clause_modifications:
            clause_rows.append([
                para(item.get("clause_topic", item.get("memo_topic", ""))),
                para(item.get("original_clause", "")),
                para(item.get("modified_clause", "")),
            ])
        simple_table(clause_rows, [1.2 * inch, 2.9 * inch, 2.9 * inch])
    else:
        story.append(para("No clause modifications found for this quote."))

    if ai_summary_df is not None and not ai_summary_df.empty:
        section("Sol AI Deal Desk Summary")
        ai_rows = [[para("Review Area"), para("Summary")]]
        for _, row in ai_summary_df.iterrows():
            ai_rows.append([para(row.get("Review Area", "")), para(row.get("Summary", ""))])
        simple_table(ai_rows, [2.0 * inch, 5.0 * inch])

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()



def build_customer_schedule_pdf(payload: dict, discount_summary: dict) -> bytes:
    """Build a simulated customer schedule PDF using the selected quote fields."""
    try:
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError as exc:
        raise ImportError("reportlab is required to generate Customer Schedule PDFs. Install it with: python3 -m pip install reportlab") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ScheduleTitle",
        parent=styles["Title"],
        fontName="Times-Bold",
        fontSize=18,
        leading=22,
        alignment=0,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ScheduleSubtitle",
        parent=styles["BodyText"],
        fontName="Times-Bold",
        fontSize=11,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )
    heading_style = ParagraphStyle(
        "ScheduleHeading",
        parent=styles["Heading2"],
        fontName="Times-Bold",
        fontSize=11,
        leading=14,
        spaceBefore=10,
        spaceAfter=6,
        textTransform="uppercase",
    )
    body_style = ParagraphStyle(
        "ScheduleBody",
        parent=styles["BodyText"],
        fontName="Times-Roman",
        fontSize=9,
        leading=12,
        alignment=4,
    )
    small_style = ParagraphStyle(
        "ScheduleSmall",
        parent=body_style,
        fontSize=8,
        leading=10,
        alignment=0,
    )

    def clean(value) -> str:
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        return str(value)

    def money(value) -> str:
        try:
            return "${:,.0f}".format(float(value or 0))
        except Exception:
            return "$0"

    def pct(value) -> str:
        try:
            return "{:.1f}%".format(float(value or 0))
        except Exception:
            return "0.0%"

    def para(value, style=body_style):
        return Paragraph(html.escape(clean(value)).replace("\n", "<br/>") or "-", style)

    def raw_para(value, style=body_style):
        return Paragraph(clean(value).replace("\n", "<br/>") or "-", style)

    def schedule_table(rows, col_widths=None):
        table = Table(rows, colWidths=col_widths, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9ca3af")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)

    account = payload.get("account", {})
    opportunity = payload.get("opportunity", {})
    quote = payload.get("quote", {})

    account_name = account.get("account_name", "Customer")
    quote_id = payload.get("quote_id", quote.get("quote_id", ""))
    close_date = opportunity.get("close_date", "")
    term_months = discount_summary.get("term_months", quote.get("term_months", ""))
    payment_terms = discount_summary.get("payment_terms", quote.get("payment_terms", ""))
    demand_planning = discount_summary.get("demand_planning_complete", quote.get("demand_planning_complete", ""))

    story = []
    header_table = Table(
        [[
            [Paragraph(html.escape(account_name), title_style), Paragraph("Customer Schedule Template", subtitle_style), Paragraph("Enterprise Subscription and Consumption Services", small_style)],
            [Paragraph(f"<b>Schedule Number:</b> {html.escape(clean(quote_id))}<br/><b>Effective Date:</b> {html.escape(clean(close_date))}<br/><b>Related Master Agreement:</b> Customer Master Subscription Agreement<br/><b>Prepared By:</b> Luna y Sol Shepherd Systems", small_style)],
        ]],
        colWidths=[3.6 * inch, 3.1 * inch],
    )
    header_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#111827")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.12 * inch))

    story.append(raw_para(
        f"This Customer Schedule (the \"<b>Schedule</b>\") is entered into by and between Luna y Sol Shepherd Systems "
        f"(\"<b>Company</b>\") and {html.escape(clean(account_name))} (\"<b>Customer</b>\") pursuant to the applicable master agreement "
        "between the parties (the \"<b>Agreement</b>\"). This Schedule sets forth the commercial terms applicable to "
        "Customer's purchase of subscription, consumption, support, and related services from Company.",
        body_style,
    ))

    story.append(Paragraph("1. Schedule Information", heading_style))
    schedule_table([
        [para("Customer Name"), para(account_name), para("Schedule / Quote ID"), para(quote_id)],
        [para("Effective Date"), para(close_date), para("Term"), para(f"{term_months} months")],
        [para("Payment Terms"), para(payment_terms), para("Demand Planning Status"), para(demand_planning)],
    ], [1.25 * inch, 2.1 * inch, 1.45 * inch, 1.9 * inch])

    story.append(Paragraph("2. Commercial Terms", heading_style))
    schedule_table([
        [para("Annual Commit"), para(money(discount_summary.get("annual_commit", quote.get("annual_commit", 0)))), para("Total Contract Amount"), para(money(discount_summary.get("total_contract_value", quote.get("total_contract_value", 0))))],
        [para("Cross-Service Discount"), para(pct(discount_summary.get("cross_service_requested_discount", quote.get("cross_service_discount_percent", 0)))), para("Add-on Discount"), para(pct(discount_summary.get("add_on_requested_discount", 0)))],
        [para("Customer Investment Funds"), para(money(discount_summary.get("requested_deal_investment", quote.get("requested_deal_investment", 0)))), para("Requested Rollover"), para(pct(discount_summary.get("requested_rollover", quote.get("requested_rollover", 0))))],
    ], [1.25 * inch, 2.1 * inch, 1.45 * inch, 1.9 * inch])

    story.append(Paragraph("3. Subscription and Usage Commit", heading_style))
    story.append(para(
        "Subject to the Agreement, Customer commits to purchase the services identified in this Schedule for the term and total contract amount set forth above. Customer's prepaid consumption commitment will be decremented based on Customer's actual usage of eligible services during the applicable term."
    ))
    story.append(Spacer(1, 0.05 * inch))
    story.append(para(
        "Unless otherwise stated in this Schedule, unused prepaid consumption amounts expire at the end of the applicable term and are not refundable. Any approved rollover amount shall be limited to the rollover percentage stated above and must be consumed during the renewal or successor schedule period, subject to Company approval and the Agreement."
    ))

    story.append(Paragraph("4. Memo", heading_style))
    memo_rows = [[para("Memo Topic"), para("Memo Language")]]
    for row in payload.get("clause_modifications", []):
        modified_clause = row.get("modified_clause", "")
        if str(modified_clause).strip():
            memo_rows.append([
                para(row.get("memo_topic") or row.get("clause_topic") or row.get("topic") or "Modified Terms"),
                para(modified_clause),
            ])

    requested_deal_investment_value = 0.0
    try:
        requested_deal_investment_value = float(quote.get("requested_deal_investment", discount_summary.get("requested_deal_investment", 0)) or 0)
    except Exception:
        requested_deal_investment_value = 0.0

    if requested_deal_investment_value > 0:
        memo_rows.append([
            para("Customer Investment Funds"),
            para("Customer investment funds must be used within twelve (12) months of the Order Form effective date. Any unused customer investment funds will expire after that period and will not roll over, convert to cash, or reduce future fees unless otherwise agreed in writing by Company. Please contact your Practice Manager for scheduling."),
        ])

    if len(memo_rows) == 1:
        memo_rows.append([para("No Special Terms"), para("No special memo terms generated for this schedule.")])

    schedule_table(memo_rows, [1.45 * inch, 5.25 * inch])

    story.append(Paragraph("5. Signatures", heading_style))
    story.append(para("IN WITNESS WHEREOF, the parties have caused this Schedule to be executed by their duly authorized representatives as of the effective date set forth above."))
    story.append(Spacer(1, 0.12 * inch))

    signature_table = Table([
        [para("Luna y Sol Shepherd Systems"), para(account_name)],
        [para("By: ________________________________"), para("By: ________________________________")],
        [para("Printed Name: ______________________"), para("Printed Name: ______________________")],
        [para("Title: ______________________________"), para("Title: ______________________________")],
        [para("Date: ______________________________"), para("Date: ______________________________")],
    ], colWidths=[3.25 * inch, 3.25 * inch])
    signature_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(signature_table)

    story.append(Spacer(1, 0.14 * inch))
    story.append(para("Demo customer schedule template. Generated for Luna y Sol Shepherd Systems POC review. This document is a simulation and does not constitute legal advice or an approved customer agreement.", small_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def upload_approval_packet_to_slack(slack_bot_token: str, slack_channel_id: str, pdf_bytes: bytes, filename: str, title: str, initial_comment: str) -> dict:
    """Upload an approval packet PDF to Slack using Slack's external file upload flow."""
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    def call_slack_form_api(method_name: str, payload: dict) -> dict:
        encoded_payload = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            f"https://slack.com/api/{method_name}",
            data=encoded_payload,
            headers={
                "Authorization": f"Bearer {slack_bot_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    upload_url_response = call_slack_form_api(
        "files.getUploadURLExternal",
        {
            "filename": filename,
            "length": str(len(pdf_bytes)),
        },
    )

    if not upload_url_response.get("ok"):
        return upload_url_response

    upload_url = upload_url_response.get("upload_url")
    file_id = upload_url_response.get("file_id")

    upload_request = urllib.request.Request(
        upload_url,
        data=pdf_bytes,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(pdf_bytes)),
        },
        method="POST",
    )

    with urllib.request.urlopen(upload_request) as upload_response:
        upload_response.read()

    complete_response = call_slack_form_api(
        "files.completeUploadExternal",
        {
            "files": json.dumps([
                {
                    "id": file_id,
                    "title": title,
                }
            ]),
            "channel_id": slack_channel_id,
            "initial_comment": initial_comment,
        },
    )

    return complete_response


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
            f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;'>{_escape(row.get('memo_topic') or row.get('clause_topic') or row.get('topic') or 'Modified Terms')}</td>"
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
                f"<td style='padding:8px;border:1px solid #e5e7eb;vertical-align:top;overflow-wrap:break-word;width:22%;'>{_escape(row.get('memo_topic') or row.get('clause_topic') or row.get('topic') or 'Modified Terms')}</td>"
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
        "{{requested_rollover}}": _percent(quote.get("requested_rollover", summary.get("requested_rollover", 0))),
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




def get_approval_matrix_tier(matrix: list, annual_commit: float) -> dict:
    """Return the approval matrix row that applies to the selected annual commit."""
    for tier in matrix or []:
        min_commit = float(tier.get("min_annual_commit") or 0)
        max_commit = tier.get("max_annual_commit")
        if max_commit is None:
            if annual_commit >= min_commit:
                return tier
        else:
            if annual_commit >= min_commit and annual_commit < float(max_commit):
                return tier
    return {}


def build_approval_matrix_plain_text(data: dict, discount_summary: dict) -> str:
    """Build a simple plain-text view of requested discounts against the approval matrix."""
    approval_rules = data.get("approval_rules", {})
    annual_commit = float(discount_summary.get("annual_commit", 0) or 0)

    cross_tier = get_approval_matrix_tier(
        approval_rules.get("cross_service_preapproved_discount_matrix", []),
        annual_commit,
    )
    add_on_tier = get_approval_matrix_tier(
        approval_rules.get("add_on_preapproved_discount_matrix", []),
        annual_commit,
    )

    def tier_label(tier: dict) -> str:
        if not tier:
            return "Unknown annual commit band"
        min_commit = float(tier.get("min_annual_commit") or 0)
        max_commit = tier.get("max_annual_commit")
        if max_commit is None:
            return f"${min_commit:,.0f}+ annual commit band"
        return f"${min_commit:,.0f} - ${float(max_commit):,.0f} annual commit band"

    def approval_path(tier: dict) -> str:
        approvals = tier.get("approvals", {}) if tier else {}
        ordered_roles = ["AE", "Manager", "Director", "CRO"]
        parts = []
        for role in ordered_roles:
            if role in approvals:
                parts.append(f"{role} {float(approvals[role]):.1f}%")
        return " → ".join(parts) if parts else "No approval matrix found"

    lines = [
        "Requested Discount vs Approval Matrix",
        f"Annual Commit Band: {tier_label(cross_tier or add_on_tier)}",
        "",
        "Cross-Service Discount",
        f"Requested: {float(discount_summary.get('cross_service_requested_discount', 0) or 0):.1f}%",
        f"Approval path: {approval_path(cross_tier)}",
        f"Required approver: {discount_summary.get('cross_service_approver_required', 'N/A')}",
        "",
        "Add-on Discount",
        f"Requested: {float(discount_summary.get('add_on_requested_discount', 0) or 0):.1f}%",
        f"Approval path: {approval_path(add_on_tier)}",
        f"Required approver: {discount_summary.get('add_on_approver_required', 'N/A')}",
    ]
    return "\n".join(lines)


def render_approval_matrix_html(data: dict, discount_summary: dict) -> str:
    """Render requested discounts against the approval matrix with approver emphasis."""
    approval_rules = data.get("approval_rules", {})
    annual_commit = float(discount_summary.get("annual_commit", 0) or 0)

    cross_tier = get_approval_matrix_tier(
        approval_rules.get("cross_service_preapproved_discount_matrix", []),
        annual_commit,
    )
    add_on_tier = get_approval_matrix_tier(
        approval_rules.get("add_on_preapproved_discount_matrix", []),
        annual_commit,
    )

    def clean_percent(value) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def tier_label(tier: dict) -> str:
        if not tier:
            return "Unknown annual commit band"
        min_commit = float(tier.get("min_annual_commit") or 0)
        max_commit = tier.get("max_annual_commit")
        if max_commit is None:
            return f"${min_commit:,.0f}+ annual commit band"
        return f"${min_commit:,.0f} - ${float(max_commit):,.0f} annual commit band"

    def render_approval_path(tier: dict, required_approver: str) -> str:
        approvals = tier.get("approvals", {}) if tier else {}
        approver_order = ["AE", "Manager", "Director", "CRO", "CEO"]
        required_index = approver_order.index(required_approver) if required_approver in approver_order else len(approver_order)
        parts = []

        for approver in approver_order:
            if approver not in approvals:
                continue

            label = f"{html.escape(approver)} {clean_percent(approvals.get(approver)):.1f}%"
            approver_index = approver_order.index(approver)

            if approver == required_approver:
                parts.append(f"<span style='color:#dc2626;font-weight:700;'>{label}</span>")
            elif approver_index > required_index:
                parts.append(f"<span style='color:#9ca3af;font-weight:500;'>{label}</span>")
            else:
                parts.append(f"<span style='color:#111827;font-weight:500;'>{label}</span>")

        return " <span style='color:#9ca3af;'>→</span> ".join(parts) if parts else "No approval matrix found"

    def render_discount_block(title: str, requested: float, required_approver: str, tier: dict) -> str:
        required_label = html.escape(required_approver or "N/A")
        return (
            "<div style='border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin-top:10px;background:#ffffff;'>"
            f"<div style='font-weight:700;color:#111827;margin-bottom:6px;'>{html.escape(title)}</div>"
            f"<div style='font-size:14px;color:#374151;margin-bottom:4px;'>Requested: <strong>{requested:.1f}%</strong></div>"
            f"<div style='font-size:14px;color:#374151;margin-bottom:4px;'>Approval path: {render_approval_path(tier, required_approver)}</div>"
            f"<div style='font-size:14px;color:#374151;'>Required approver: <span style='color:#dc2626;font-weight:700;'>{required_label}</span></div>"
            "</div>"
        )

    cross_required = str(discount_summary.get("cross_service_approver_required", "") or "")
    add_on_required = str(discount_summary.get("add_on_approver_required", "") or "")

    return "".join([
        "<div style='margin-top:16px;margin-bottom:16px;'>",
        "<h4 style='margin-bottom:4px;'>Requested Discount vs Approval Matrix</h4>",
        f"<div style='font-size:14px;color:#6b7280;margin-bottom:8px;'>Annual Commit Band: {html.escape(tier_label(cross_tier or add_on_tier))}</div>",
        render_discount_block(
            "Cross-Service Discount",
            clean_percent(discount_summary.get("cross_service_requested_discount", 0)),
            cross_required,
            cross_tier,
        ),
        render_discount_block(
            "Add-on Discount",
            clean_percent(discount_summary.get("add_on_requested_discount", 0)),
            add_on_required,
            add_on_tier,
        ),
        "</div>",
    ])


def build_redline_display_rows(clause_modifications):
    rows = []
    for item in clause_modifications:
        topic = (
            item.get("memo_topic")
            or item.get("clause_topic")
            or item.get("topic")
            or item.get("approval_rule")
            or "Modified Terms"
        )
        rows.append({
            "Clause Topic": topic,
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
    "requested_rollover",
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
        "requested_rollover": "Rollover %",
    }
)
if "Annual Commit" in pending_display_df.columns:
    pending_display_df["Annual Commit"] = pending_display_df["Annual Commit"].map(lambda x: "${:,.0f}".format(float(x)))
if "Quote Age Hours" in pending_display_df.columns:
    pending_display_df["Quote Age Hours"] = pending_display_df["Quote Age Hours"].map(lambda x: "{:.0f}".format(float(x)))
if "Rollover %" in pending_display_df.columns:
    pending_display_df["Rollover %"] = pending_display_df["Rollover %"].map(lambda x: "{:.1f}%".format(float(x or 0)))

st.dataframe(pending_display_df, hide_index=True, use_container_width=True)

pending_quote_options = filtered_pending_quotes["quote_id"].astype(str).tolist()
if "selected_pending_quote_id" not in st.session_state or st.session_state["selected_pending_quote_id"] not in pending_quote_options:
    st.session_state["selected_pending_quote_id"] = pending_quote_options[0]

if st.button("Recommend Quote to Prioritize", key="recommend_quote_to_prioritize"):
    st.session_state["priority_recommendation"] = recommend_pending_quote(filtered_pending_quotes)
    recommended_quote_id = str(st.session_state["priority_recommendation"].get("quote_id", ""))
    if recommended_quote_id in pending_quote_options:
        st.session_state["selected_pending_quote_id"] = recommended_quote_id
        st.rerun()

priority_recommendation = st.session_state.get("priority_recommendation")
if priority_recommendation:
    recommended_quote_id = priority_recommendation.get("quote_id")
    if recommended_quote_id:
        st.success(
            "Sol recommends prioritizing %s — %s priority, score %s/100."
            % (
                recommended_quote_id,
                priority_recommendation.get("priority_level", ""),
                priority_recommendation.get("priority_score", 0),
            )
        )
        st.write(priority_recommendation.get("summary", ""))
    else:
        st.info(priority_recommendation.get("summary", "No recommendation available."))

selected_quote_id = st.selectbox(
    "Select Pending Quote",
    pending_quote_options,
    key="selected_pending_quote_id",
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
    "Rollover %": "{:.1f}%".format(float(discount_summary.get("requested_rollover", payload.get("quote", {}).get("requested_rollover", 0)) or 0)),
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

st.subheader("Quote Clause Modifications")
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

if "evaluated_quote_id" not in st.session_state:
    st.session_state["evaluated_quote_id"] = None

if selected_quote_id != st.session_state.get("evaluated_quote_id"):
    st.session_state["evaluated_quote_id"] = None
    st.session_state[f"show_quote_preview_{selected_quote_id}"] = False
    st.session_state[f"show_schedule_upload_{selected_quote_id}"] = False
    st.session_state[f"customer_schedule_pdf_{selected_quote_id}"] = None
    st.session_state[f"customer_schedule_pdf_{selected_quote_id}"] = None

if st.button("Evaluate Quote", type="primary"):
    st.session_state["evaluated_quote_id"] = selected_quote_id
    st.session_state[f"show_quote_preview_{selected_quote_id}"] = False
    st.session_state[f"show_schedule_upload_{selected_quote_id}"] = False

if st.session_state.get("evaluated_quote_id") == selected_quote_id:
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

    st.caption("Luna compares the requested discounts against the deterministic approval matrix for this quote's annual commit band.")
    st.markdown(render_approval_matrix_html(data, discount_summary), unsafe_allow_html=True)

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
        with st.spinner("Sol is reviewing the quote and preparing the AI Deal Desk Summary..."):
            summary, usage = explain_with_openai(payload)
            ai_summary_df = build_ai_summary_table(summary)
        st.markdown(render_ai_summary_table(ai_summary_df), unsafe_allow_html=True)
    except Exception as e:
        st.warning("OpenAI error: %s" % e)

    st.subheader("Quote Tools")
    st.caption("One-click assisted actions for downstream Deal Desk workflows.")

    st.info("Quote Preview")
    st.caption("Preview the simulated customer-facing quote generated from the selected quote data.")

    if st.button("Preview Quote", key=f"preview_quote_{selected_quote_id}"):
        st.session_state[f"show_quote_preview_{selected_quote_id}"] = True

    if st.session_state.get(f"show_quote_preview_{selected_quote_id}", False):
        quote_template_html = render_quote_template(payload, Path(__file__).with_name("quote_template.html"))
        st.markdown(quote_template_html, unsafe_allow_html=True)

    st.info("Transfer Quote to Customer Schedule Template")
    st.caption(
        "Upload a customer-provided schedule template. Luna will simulate transferring the selected quote fields "
        "into the customer schedule for downstream review."
    )

    existing_col, upload_col, spacer_col = st.columns([1, 1, 6])
    with existing_col:
        if st.button("Use Existing", key=f"use_existing_customer_schedule_{selected_quote_id}"):
            try:
                st.session_state[f"customer_schedule_pdf_{selected_quote_id}"] = build_customer_schedule_pdf(
                    payload,
                    discount_summary,
                )
            except ImportError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Unable to generate Customer Schedule PDF: {e}")

    with upload_col:
        if st.button("Upload New", key=f"upload_customer_schedule_{selected_quote_id}"):
            st.session_state[f"show_schedule_upload_{selected_quote_id}"] = True

    generated_schedule_pdf = st.session_state.get(f"customer_schedule_pdf_{selected_quote_id}")
    if generated_schedule_pdf:
        st.success("Existing Customer Schedule Template Updated")
        st.download_button(
            "Download Customer Schedule PDF",
            data=generated_schedule_pdf,
            file_name=f"customer_schedule_{selected_quote_id}.pdf",
            mime="application/pdf",
            key=f"download_customer_schedule_{selected_quote_id}",
        )

    if st.session_state.get(f"show_schedule_upload_{selected_quote_id}", False):
        uploaded_schedule = st.file_uploader(
            "Upload Customer Schedule",
            type=["pdf", "docx", "xlsx", "xls", "html", "txt"],
            key=f"customer_schedule_file_{selected_quote_id}",
            help="Upload the customer's schedule template so the POC can simulate field transfer from the selected quote.",
        )

        if uploaded_schedule is not None:
            st.success(
                "Customer Schedule uploaded. Luna transferred the selected quote fields to the Customer Schedule Template for review."
            )
            transferred_fields_df = pd.DataFrame([
                {"Schedule Field": "Customer Name", "Transferred Value": payload.get("account", {}).get("account_name", "")},
                {"Schedule Field": "Quote ID", "Transferred Value": payload.get("quote_id", selected_quote_id)},
                {"Schedule Field": "Annual Commit", "Transferred Value": f"${float(discount_summary.get('annual_commit', 0)):,.0f}"},
                {"Schedule Field": "Total Contract Amount", "Transferred Value": f"${float(discount_summary.get('total_contract_value', 0)):,.0f}"},
                {"Schedule Field": "Term", "Transferred Value": f"{discount_summary.get('term_months', '')} months"},
                {"Schedule Field": "Payment Terms", "Transferred Value": discount_summary.get("payment_terms", "")},
                {"Schedule Field": "Requested Rollover", "Transferred Value": f"{float(discount_summary.get('requested_rollover', payload.get('quote', {}).get('requested_rollover', 0)) or 0):.1f}%"},
                {"Schedule Field": "Cross-Service Discount", "Transferred Value": f"{float(discount_summary.get('cross_service_requested_discount', 0) or 0):.1f}%"},
                {"Schedule Field": "Add-on Discount", "Transferred Value": f"{float(discount_summary.get('add_on_requested_discount', 0) or 0):.1f}%"},
            ])
            st.dataframe(transferred_fields_df, hide_index=True, use_container_width=True)


    st.info("Reserve Deal Desk Open Office Hours")
    st.caption("Reserve a 15-minute support window in hosted Deal Desk office hours for Sales to review the quote with cross-functional teams.")
    st.link_button(
        "Reserve Office Hours",
        "https://calendly.com/branden-neubig/deal-desk-office-hours?month=2026-06&date=2026-06-29",
    )

    st.info("Request Support via Slack")
    st.caption("Post a human-reviewed support request and approval packet to the configured Slack channel.")

    support_reason = st.text_area(
        "Reason for Support",
        "Please review this quote for approval routing, commercial risk, and any missing inputs before customer-facing quote finalization.",
        height=120,
    )

    support_message = f"""
:sos: Deal Desk Support Requested

Quote: {payload.get("quote_id", selected_quote_id)}
Account: {payload.get("account", {}).get("account_name", "")}
Region: {payload.get("account", {}).get("region", "")}
Annual Commit: ${float(discount_summary.get("annual_commit", 0)):,.0f}
Requested Cross-Service Discount: {float(discount_summary.get("cross_service_requested_discount", 0)):.1f}%
Approver Required: {discount_summary.get("cross_service_approver_required", "")}

Reason for Support:
{support_reason}
""".strip()

    edited_support_message = support_message

    try:
        approval_packet_pdf = build_approval_packet_pdf(
            payload,
            discount_summary,
            support_reason,
            ai_summary_df if "ai_summary_df" in locals() else None,
        )
    except ImportError as e:
        approval_packet_pdf = None
        st.warning(str(e))
    except Exception as e:
        approval_packet_pdf = None
        st.error(f"Unable to generate approval packet PDF: {e}")

    if st.button("Post Support Request + Approval Packet to Slack", key=f"post_support_to_slack_{selected_quote_id}"):
        slack_bot_token = st.secrets.get("SLACK_BOT_TOKEN", "")
        slack_channel_id = st.secrets.get("SLACK_CHANNEL_ID", "")

        if not slack_bot_token or not slack_channel_id:
            st.error("Slack is not configured. Add SLACK_BOT_TOKEN and SLACK_CHANNEL_ID to .streamlit/secrets.toml.")
        elif approval_packet_pdf is None:
            st.error("Approval packet PDF could not be generated, so the Slack request was not posted.")
        else:
            try:
                import json
                import urllib.error
                import urllib.request

                slack_payload = {
                    "channel": slack_channel_id,
                    "text": edited_support_message,
                }

                request = urllib.request.Request(
                    "https://slack.com/api/chat.postMessage",
                    data=json.dumps(slack_payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {slack_bot_token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(request) as response:
                    slack_response = json.loads(response.read().decode("utf-8"))

                if not slack_response.get("ok"):
                    st.error(f"Slack message error: {slack_response.get('error', 'Unknown error')}")
                else:
                    packet_filename = f"approval_packet_{selected_quote_id}.pdf"
                    packet_title = f"Approval Packet - {selected_quote_id}"
                    upload_response = upload_approval_packet_to_slack(
                        slack_bot_token=slack_bot_token,
                        slack_channel_id=slack_channel_id,
                        pdf_bytes=approval_packet_pdf,
                        filename=packet_filename,
                        title=packet_title,
                        initial_comment=f"Attached approval packet for {selected_quote_id}.",
                    )

                    if upload_response.get("ok"):
                        st.success("Support request and approval packet posted to Slack.")
                    else:
                        st.warning(
                            "Support request posted, but the approval packet upload failed: "
                            f"{upload_response.get('error', 'Unknown error')}"
                        )
            except urllib.error.HTTPError as e:
                st.error(f"Slack HTTP error: {e.code} {e.reason}")
            except Exception as e:
                st.error(f"Unable to post to Slack: {e}")

