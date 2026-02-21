from __future__ import annotations

import boto3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen



def _subtract_months(base_date: date, months: int) -> date:
    year = base_date.year
    month = base_date.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(base_date.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


def _add_months(base_date: date, months: int) -> date:
    year = base_date.year
    month = base_date.month + months
    while month > 12:
        month -= 12
        year += 1
    day = min(base_date.day, _days_in_month(year, month))
    return date(year, month, day)


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _get_account_id() -> str:
    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    return identity["Account"]


def _list_invoice_summaries_last_3_months(client):
    end_date = date.today()
    start_date = _subtract_months(end_date, 3)
    end_exclusive = end_date + timedelta(days=1)

    account_id = _get_account_id()

    summaries = []
    current = start_date
    while current < end_exclusive:
        month_start = _month_start(current)
        next_month_start = _add_months(month_start, 1)
        window_start = current
        window_end = min(next_month_start, end_exclusive)

        start_dt = datetime.combine(window_start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(window_end, time.min, tzinfo=timezone.utc)

        request = {
            "Selector": {
                "ResourceType": "ACCOUNT_ID",
                "Value": account_id,
            },
            "Filter": {
                "TimeInterval": {
                    "StartDate": start_dt,
                    "EndDate": end_dt,
                }
            },
        }

        try:
            paginator = client.get_paginator("list_invoice_summaries")
            for page in paginator.paginate(**request):
                summaries.extend(page.get("InvoiceSummaries", []))
        except client.exceptions.OperationNotPageableException:
            response = client.list_invoice_summaries(**request)
            summaries.extend(response.get("InvoiceSummaries", []))

        current = window_end

    return summaries


def _extract_invoice_id(summary: dict) -> str | None:
    return summary.get("InvoiceId") or summary.get("invoiceId")


def _format_summary(summary: dict) -> str:
    invoice_id = _extract_invoice_id(summary) or "(unknown)"
    invoice_type = summary.get("InvoiceType") or summary.get("invoiceType")
    billing_period = summary.get("BillingPeriod") or summary.get("billingPeriod")
    amount_due = summary.get("AmountDue") or summary.get("amountDue")
    currency = summary.get("CurrencyCode") or summary.get("currencyCode")

    period_str = ""
    if isinstance(billing_period, dict):
        start = billing_period.get("Start") or billing_period.get("start")
        end = billing_period.get("End") or billing_period.get("end")
        month = billing_period.get("Month") or billing_period.get("month")
        year = billing_period.get("Year") or billing_period.get("year")
        if start or end:
            period_str = f"{start} - {end}"
        elif year and month:
            period_str = f"{int(year):04d}-{int(month):02d}"

    amount_str = ""
    if amount_due is not None:
        amount_str = f"{amount_due} {currency or ''}".strip()

    parts = [invoice_id]
    if invoice_type:
        parts.append(str(invoice_type))
    if period_str:
        parts.append(period_str)
    if amount_str:
        parts.append(amount_str)
    return " | ".join(parts)


def _summary_sort_key(summary: dict) -> datetime:
    issued_date = summary.get("IssuedDate") or summary.get("issuedDate")
    if isinstance(issued_date, datetime):
        return issued_date

    billing_period = summary.get("BillingPeriod") or summary.get("billingPeriod")
    if isinstance(billing_period, dict):
        year = billing_period.get("Year") or billing_period.get("year")
        month = billing_period.get("Month") or billing_period.get("month")
        if year and month:
            return datetime(int(year), int(month), 1, tzinfo=timezone.utc)

    return datetime.min.replace(tzinfo=timezone.utc)


def _prompt_selection(summaries: list[dict]) -> dict | None:
    if not summaries:
        print("No invoices found in the last 3 months.")
        return None

    summaries = sorted(summaries, key=_summary_sort_key, reverse=True)

    print("Select an invoice to download:")
    for idx, summary in enumerate(summaries, start=1):
        print(f"{idx}. {_format_summary(summary)}")

    while True:
        choice = input("Enter number (or 'q' to quit): ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            return None
        if not choice.isdigit():
            print("Please enter a valid number.")
            continue
        index = int(choice)
        if 1 <= index <= len(summaries):
            return summaries[index - 1]
        print("Number out of range.")


def _safe_filename(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name)
    return safe or "invoice"


def _ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not find a unique filename.")


def _download_invoice_pdf(client, invoice_id: str, output_dir: Path) -> Path | None:
    response = client.get_invoice_pdf(InvoiceId=invoice_id)
    invoice_pdf = response.get("InvoicePDF", {})
    url = invoice_pdf.get("DocumentUrl")
    if not url:
        print("No DocumentUrl found for the selected invoice.")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(invoice_id) + ".pdf"
    output_path = _ensure_unique_path(output_dir / filename)

    with urlopen(url) as resp, output_path.open("wb") as f:
        f.write(resp.read())

    return output_path


def main():
    client = boto3.client("invoicing")
    summaries = _list_invoice_summaries_last_3_months(client)
    selected = _prompt_selection(summaries)
    if not selected:
        return

    invoice_id = _extract_invoice_id(selected)
    if not invoice_id:
        print("Selected invoice does not have an invoiceId.")
        return

    output_path = _download_invoice_pdf(client, invoice_id, Path("downloads"))
    if output_path:
        print(f"Downloaded to: {output_path}")


if __name__ == "__main__":
    main()
