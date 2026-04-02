import pandas as pd

from utils import detect_column, compute_days_elapsed, rag_status, ColumnNotFoundError

AWAITING_KEYWORDS = ["feedback"]

REQUIRED_FIELDS = {
    "order_id":    True,
    "tseg_id":     True,
    "updated_at":  True,
    "status":      True,
}

OPTIONAL_FIELDS = {
    "address":  False,
    "provider": False,
    "issue":    False,
}


def run_sla_check(df: pd.DataFrame) -> dict:

    col_map = {}
    for field, required in {**REQUIRED_FIELDS, **OPTIONAL_FIELDS}.items():
        match = detect_column(df.columns, field, required=required)
        if match:
            col_map[field] = match

    order_col    = col_map["order_id"]
    tseg_col     = col_map["tseg_id"]
    updated_col  = col_map["updated_at"]
    status_col   = col_map["status"]
    address_col  = col_map.get("address")
    provider_col = col_map.get("provider")
    issue_col    = col_map.get("issue")

    df = df.copy()
    df["_status_lower"] = df[status_col].astype(str).str.lower().str.strip()

    awaiting = df[df["_status_lower"].apply(
        lambda s: any(k in s for k in AWAITING_KEYWORDS)
    )].copy()

    awaiting["days_elapsed"] = compute_days_elapsed(awaiting, updated_col)
    awaiting["rag"] = awaiting["days_elapsed"].apply(rag_status)
    awaiting = awaiting.sort_values("days_elapsed", ascending=False)

    out_cols = []
    for c in [order_col, tseg_col, address_col, provider_col, issue_col, updated_col, status_col]:
        if c and c in awaiting.columns and c not in out_cols:
            out_cols.append(c)
    out_cols += ["days_elapsed", "rag"]

    result = awaiting[out_cols].copy().fillna("")

    total_awaiting = len(result)
    breached       = int((result["rag"] == "breached").sum())
    at_risk        = int((result["rag"] == "at_risk").sum())
    ok             = int((result["rag"] == "ok").sum())

    supplier_breakdown = []
    if provider_col and provider_col in result.columns:
        for supplier, group in result.groupby(provider_col):
            if not supplier:
                continue
            supplier_breakdown.append({
                "supplier": supplier,
                "breached": int((group["rag"] == "breached").sum()),
                "at_risk":  int((group["rag"] == "at_risk").sum()),
                "ok":       int((group["rag"] == "ok").sum()),
                "total":    len(group),
            })
        supplier_breakdown.sort(key=lambda x: x["total"], reverse=True)

    return {
        "summary": {
            "total_awaiting": total_awaiting,
            "breached":       breached,
            "at_risk":        at_risk,
            "ok":             ok,
        },
        "supplier_breakdown": supplier_breakdown,
        "columns":            out_cols,
        "rows":               result.to_dict(orient="records"),
    }
