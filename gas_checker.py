import pandas as pd
import argparse
import sys
from datetime import date

from utils import detect_column, detect_all_columns, ColumnNotFoundError, PATTERNS


# ── Core logic ────────────────────────────────────────────────────────────────

NULL_MPRN_VALUES = {"unknown", "n/a", "none", "null", "not found", "-", ""}


def is_electricity_only(mprn_value):
    """
    Returns True if the MPRN value indicates no gas meter is present.
    Catches: blank, None/NaN, 'unknown', 'N/A', 'none', 'null', '-'
    """
    if pd.isna(mprn_value):
        return True
    return str(mprn_value).strip().lower() in NULL_MPRN_VALUES


def flag_order(row, homebox_map, tseg_map):
    """
    Determine the flag for a single merged row.
    Electricity-only = MPRN is null/unknown on Homebox side.
    Extra confidence check: if TSEG data also has an MPRN column, cross-reference it.
    """
    hb_mprn_col = homebox_map.get("mprn")
    tseg_mprn_col = tseg_map.get("mprn")

    hb_mprn = row.get(hb_mprn_col) if hb_mprn_col else None
    tseg_mprn = row.get(tseg_mprn_col) if tseg_mprn_col else None

    hb_elec_only = is_electricity_only(hb_mprn)

    if tseg_mprn_col:
        tseg_elec_only = is_electricity_only(tseg_mprn)
        if hb_elec_only and tseg_elec_only:
            return "electricity only - action required"
        elif hb_elec_only and not tseg_elec_only:
            return "mprn mismatch - review manually"
        else:
            return "gas confirmed - ok"
    else:
        if hb_elec_only:
            return "electricity only - action required"
        return "gas confirmed - ok"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TSEG gas fuel checker - flags electricity-only orders."
    )
    parser.add_argument("--homebox", required=True, help="Path to Homebox Trevor export CSV")
    parser.add_argument("--tseg",    required=True, help="Path to TSEG supplier CSV")
    parser.add_argument("--output",  default=None,  help="Output CSV path (optional)")
    args = parser.parse_args()

    output_path = args.output or f"flagged_orders_{date.today()}.csv"

    # ── Load files ────────────────────────────────────────────────────────────
    print(f"\nLoading Homebox file: {args.homebox}")
    try:
        hb = pd.read_csv(args.homebox)
    except Exception as e:
        print(f"  ERROR reading Homebox file: {e}")
        sys.exit(1)

    print(f"Loading TSEG file:    {args.tseg}")
    try:
        tseg = pd.read_csv(args.tseg)
    except Exception as e:
        print(f"  ERROR reading TSEG file: {e}")
        sys.exit(1)

    print(f"\n  Homebox: {len(hb)} rows, {len(hb.columns)} columns")
    print(f"  TSEG:    {len(tseg)} rows, {len(tseg.columns)} columns")

    # ── Detect columns ────────────────────────────────────────────────────────
    hb_fields = {
        "tseg_id":   True,
        "order_id":  True,
        "address":   False,
        "mprn":      True,
        "mpan":      False,
        "fuel_type": False,
    }
    tseg_fields = {
        "tseg_id": True,
        "mprn":    False,
    }

    try:
        print(f"\n  Detecting columns in Homebox file...")
        hb_map = detect_all_columns(hb, "Homebox file", hb_fields)
        for field, col in hb_map.items():
            print(f"    '{field}' -> '{col}'")

        print(f"\n  Detecting columns in TSEG file...")
        tseg_map = detect_all_columns(tseg, "TSEG file", tseg_fields)
        for field, col in tseg_map.items():
            print(f"    '{field}' -> '{col}'")
    except ColumnNotFoundError as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

    # ── Normalise join key ────────────────────────────────────────────────────
    print("\n  Normalising TSEG ID columns...")
    hb["_join_key"]   = hb[hb_map["tseg_id"]].astype(str).str.strip().str.upper()
    tseg["_join_key"] = tseg[tseg_map["tseg_id"]].astype(str).str.strip().str.upper()

    # ── Join ──────────────────────────────────────────────────────────────────
    print("  Joining on TSEG ID...")
    tseg_cols = ["_join_key"] + [v for k, v in tseg_map.items() if k != "tseg_id" and v]
    merged = hb.merge(
        tseg[tseg_cols].rename(columns={v: f"tseg_{v}" for k, v in tseg_map.items() if k != "tseg_id" and v}),
        on="_join_key",
        how="left"
    )

    tseg_map_merged = {k: f"tseg_{v}" for k, v in tseg_map.items() if k != "tseg_id" and v}

    print(f"  Matched {len(merged)} rows | {len(tseg) - len(merged[merged['_join_key'].isin(tseg['_join_key'])])} TSEG orders not in Homebox file")

    # ── Flag ──────────────────────────────────────────────────────────────────
    print("  Flagging orders...")
    merged["flag"] = merged.apply(
        lambda row: flag_order(row, hb_map, tseg_map_merged), axis=1
    )

    # ── Build output ──────────────────────────────────────────────────────────
    output_cols = []
    for field, col in hb_map.items():
        if col and col in merged.columns:
            output_cols.append(col)

    for field, col in tseg_map_merged.items():
        if col and col in merged.columns:
            output_cols.append(col)

    output_cols.append("flag")
    output_cols = list(dict.fromkeys(output_cols))

    result = merged[output_cols].copy()
    result.to_csv(output_path, index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    total          = len(result)
    action_needed  = (result["flag"] == "electricity only - action required").sum()
    gas_ok         = (result["flag"] == "gas confirmed - ok").sum()
    review         = (result["flag"] == "mprn mismatch - review manually").sum()

    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TSEG Gas Checker - Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total orders processed : {total}
  Electricity only       : {action_needed}  (action required)
  Gas confirmed          : {gas_ok}  (ok)
  MPRN mismatch          : {review}  (review manually)

  Output saved to: {output_path}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


if __name__ == "__main__":
    main()
