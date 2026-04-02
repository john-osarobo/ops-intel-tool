import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path

from utils import detect_column, compute_days_elapsed, rag_status, ColumnNotFoundError

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"

SKIP_TABS = ["completed wip"]

PATTERNS = {
    "tseg_id":        ["TSEG ID", "tseg id", "tseg_id", "bill_payment_reference", "payment_reference"],
    "order_id":       ["order_id", "orderid"],
    "address":        ["Address 1", "address", "property_line1"],
    "provider":       ["Supplier", "supplier", "provider", "bill_provider"],
    "reason":         ["Notes", "notes", "reason", "comment", "status", "issue"],
    "supply_status":  ["Supply Status", "supply_status", "supply status"],
    "services_start": ["Services Start", "services_start", "services start", "service start"],
}


def detect_col(headers, field, required=False):
    patterns = PATTERNS[field]
    for pattern in patterns:
        for h in headers:
            if h.strip() == pattern:
                return h
    for pattern in patterns:
        for h in headers:
            if pattern.lower() in h.lower():
                return h
    return None


def get_wip_data(wip_url: str) -> list[dict]:
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(wip_url)

    all_rows = []
    for ws in sheet.worksheets():
        tab_name = ws.title.strip()
        if tab_name.lower() in SKIP_TABS:
            continue

        try:
            records = ws.get_all_records()
        except Exception:
            raw = ws.get_all_values()
            if not raw:
                continue
            headers_row = raw[0]
            seen = {}
            clean_headers = []
            for h in headers_row:
                h = h.strip()
                if not h:
                    h = f"_col_{len(clean_headers)}"
                if h in seen:
                    seen[h] += 1
                    h = f"{h}_{seen[h]}"
                else:
                    seen[h] = 0
                clean_headers.append(h)
            records = [dict(zip(clean_headers, row)) for row in raw[1:] if any(row)]

        df = pd.DataFrame(records)
        headers = df.columns.tolist()

        tseg_col          = detect_col(headers, "tseg_id")
        order_col         = detect_col(headers, "order_id")
        address_col       = detect_col(headers, "address")
        provider_col      = detect_col(headers, "provider")
        reason_col        = detect_col(headers, "reason")
        supply_status_col = detect_col(headers, "supply_status")
        services_start_col = detect_col(headers, "services_start")

        if not tseg_col:
            continue

        for _, row in df.iterrows():
            tseg_val = str(row.get(tseg_col, "")).strip().upper()
            if not tseg_val or tseg_val in ("", "NAN", "NONE"):
                continue
            all_rows.append({
                "wip_tseg_id":        tseg_val,
                "wip_order_id":       str(row.get(order_col, "")).strip() if order_col else "",
                "wip_address":        str(row.get(address_col, "")).strip() if address_col else "",
                "wip_provider":       str(row.get(provider_col, "")).strip() if provider_col else "",
                "wip_reason":         str(row.get(reason_col, "")).strip() if reason_col else "",
                "wip_supply_status":  str(row.get(supply_status_col, "")).strip() if supply_status_col else "",
                "wip_services_start": str(row.get(services_start_col, "")).strip() if services_start_col else "",
                "wip_tab":            tab_name,
            })

    return all_rows


def _clean_tseg_id(val):
    """Normalise a TSEG ID value to a clean uppercase string."""
    try:
        return str(int(float(str(val).strip())))
    except (ValueError, TypeError):
        return ""


def run_wip_check(trevor_df: pd.DataFrame, wip_url: str) -> dict:

    trevor_fields = {
        "tseg_id":    True,
        "order_id":   True,
        "address":    False,
        "provider":   False,
        "updated_at": True,
        "status":     True,
    }

    col_map = {}
    for field, required in trevor_fields.items():
        match = detect_column(trevor_df.columns, field, required=required)
        if match:
            col_map[field] = match

    tseg_col     = col_map["tseg_id"]
    order_col    = col_map["order_id"]
    updated_col  = col_map["updated_at"]
    status_col   = col_map["status"]
    address_col  = col_map.get("address")
    provider_col = col_map.get("provider")

    trevor = trevor_df.copy()

    trevor["_join_key"] = trevor[tseg_col].apply(_clean_tseg_id).str.upper()
    trevor["days_elapsed"] = compute_days_elapsed(trevor, updated_col)
    trevor["rag"] = trevor["days_elapsed"].apply(rag_status)

    wip_rows = get_wip_data(wip_url)
    wip_df   = pd.DataFrame(wip_rows) if wip_rows else pd.DataFrame(
        columns=["wip_tseg_id", "wip_order_id", "wip_address", "wip_provider", "wip_reason",
                 "wip_supply_status", "wip_services_start", "wip_tab"]
    )

    if not wip_df.empty:
        wip_df["_join_key"] = wip_df["wip_tseg_id"].astype(str).str.strip().str.upper()

    keep = [c for c in [order_col, tseg_col, address_col, provider_col, updated_col, status_col,
                         "days_elapsed", "rag"] if c]
    merged = trevor[keep + ["_join_key"]].merge(
        wip_df, on="_join_key", how="left"
    ).drop(columns=["_join_key"])
    merged = merged.fillna("")

    out_cols = [c for c in keep if c in merged.columns] + \
               ["wip_tab", "wip_reason", "wip_provider", "wip_supply_status", "wip_services_start"]

    result = merged[out_cols].copy()

    tabs_present = [t for t in result["wip_tab"].unique() if t and t != ""]

    objection_rows = result[result["wip_tab"] == "Objections"].copy()
    objection_by_supplier = []
    if not objection_rows.empty and provider_col:
        grp = objection_rows.groupby(provider_col).agg(
            count=(provider_col, "count"),
            orders=(order_col, lambda x: list(x)),
        ).reset_index()
        grp = grp.sort_values("count", ascending=False)
        objection_by_supplier = [
            {
                "supplier": row[provider_col],
                "count":    int(row["count"]),
                "orders":   row["orders"],
            }
            for _, row in grp.iterrows()
            if row[provider_col]
        ]

    supplier_wip_breakdown = []
    if provider_col and provider_col in result.columns:
        wip_only = result[result["wip_tab"] != ""]
        if not wip_only.empty:
            grp = wip_only.groupby([provider_col, "wip_tab"]).size().reset_index(name="count")
            for supplier, sub in grp.groupby(provider_col):
                supplier_wip_breakdown.append({
                    "supplier": supplier,
                    "total":    int(sub["count"].sum()),
                    "by_tab":  {row["wip_tab"]: int(row["count"]) for _, row in sub.iterrows()},
                })
            supplier_wip_breakdown.sort(key=lambda x: x["total"], reverse=True)

    return {
        "summary": {
            "total":          len(result),
            "matched_to_wip": int((result["wip_tab"] != "").sum()),
            "objections":     int((result["wip_tab"] == "Objections").sum()),
            "unmatched":      int((result["wip_tab"] == "").sum()),
        },
        "tabs":                    tabs_present,
        "objection_by_supplier":   objection_by_supplier,
        "supplier_wip_breakdown":  supplier_wip_breakdown,
        "columns":                 out_cols,
        "rows":                    result.to_dict(orient="records"),
    }
