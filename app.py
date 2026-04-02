import io
import pandas as pd
import uvicorn
import webbrowser
import threading

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from datetime import date
from pathlib import Path

from gas_checker import flag_order
from sheets import push_to_sheets
from sla_checker import run_sla_check
from wip_checker import run_wip_check
from utils import detect_all_columns, ColumnNotFoundError, clean_nan_in_rows

BASE_DIR = Path(__file__).parent

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
def root():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


async def read_csv(upload: UploadFile, label: str = "file") -> pd.DataFrame:
    """Read an uploaded CSV with size validation."""
    contents = await upload.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(400, f"{label} exceeds maximum size of {MAX_FILE_SIZE // (1024*1024)} MB.")
    try:
        return pd.read_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(400, f"Could not read {label}: {e}")


def run_gas_check(hb: pd.DataFrame, ts: pd.DataFrame):
    hb_fields = {
        "tseg_id":   True,
        "order_id":  True,
        "address":   False,
        "mprn":      True,
        "mpan":      False,
        "fuel_type": False,
    }
    tseg_fields = {"tseg_id": True, "mprn": False}

    hb_map   = detect_all_columns(hb, "Homebox file", hb_fields)
    tseg_map = detect_all_columns(ts, "TSEG file", tseg_fields)

    hb["_join_key"] = hb[hb_map["tseg_id"]].astype(str).str.strip().str.upper()
    ts["_join_key"] = ts[tseg_map["tseg_id"]].astype(str).str.strip().str.upper()

    tseg_extra   = [v for k, v in tseg_map.items() if k != "tseg_id" and v]
    tseg_renamed = {v: f"tseg_{v}" for v in tseg_extra}

    merged = hb.merge(
        ts[["_join_key"] + tseg_extra].rename(columns=tseg_renamed),
        on="_join_key", how="left"
    )

    tseg_map_merged = {k: f"tseg_{v}" for k, v in tseg_map.items() if k != "tseg_id" and v}
    merged["flag"] = merged.apply(lambda row: flag_order(row, hb_map, tseg_map_merged), axis=1)

    output_cols = list(dict.fromkeys(
        [c for c in [
            hb_map.get("order_id"), hb_map.get("tseg_id"), hb_map.get("address"),
            hb_map.get("mprn"), hb_map.get("mpan"), hb_map.get("fuel_type"),
        ] if c] + list(tseg_map_merged.values()) + ["flag"]
    ))
    output_cols = [c for c in output_cols if c in merged.columns]
    return merged[output_cols].copy().fillna("")


@app.post("/run-gas")
async def run_gas(
    homebox:   UploadFile = File(...),
    tseg:      UploadFile = File(...),
    sheet_url: str = Form(default=""),
):
    hb = await read_csv(homebox, "Homebox file")
    ts = await read_csv(tseg, "TSEG file")

    try:
        result = run_gas_check(hb, ts)
    except ColumnNotFoundError as e:
        raise HTTPException(400, str(e))

    total     = len(result)
    elec_only = int((result["flag"] == "electricity only - action required").sum())
    gas_ok    = int((result["flag"] == "gas confirmed - ok").sum())
    mismatch  = int((result["flag"] == "mprn mismatch - review manually").sum())

    sheet_tab = sheet_error = None
    if sheet_url.strip():
        try:
            sheet_tab = push_to_sheets(result, sheet_url.strip())
        except Exception as e:
            sheet_error = str(e)

    return {
        "summary":     {"total": total, "elec_only": elec_only, "gas_ok": gas_ok, "mismatch": mismatch},
        "columns":     result.columns.tolist(),
        "rows":        result.to_dict(orient="records"),
        "sheet_tab":   sheet_tab,
        "sheet_error": sheet_error,
    }


@app.post("/run-sla")
async def run_sla(
    homebox:   UploadFile = File(...),
    sheet_url: str = Form(default=""),
):
    df = await read_csv(homebox, "Homebox file")

    try:
        result = run_sla_check(df)
    except ColumnNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))

    if sheet_url.strip() and result["rows"]:
        try:
            out_df = pd.DataFrame(result["rows"])[result["columns"]]
            sheet_tab = push_to_sheets(out_df, sheet_url.strip())
            result["sheet_tab"] = sheet_tab
        except Exception as e:
            result["sheet_error"] = str(e)

    clean_nan_in_rows(result["rows"])

    return result


@app.post("/run-wip")
async def run_wip(
    homebox:   UploadFile = File(...),
    wip_url:   str = Form(...),
    sheet_url: str = Form(default=""),
):
    df = await read_csv(homebox, "Homebox file")

    try:
        result = run_wip_check(df, wip_url)
    except ColumnNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))

    if sheet_url.strip() and result["rows"]:
        try:
            out_df    = pd.DataFrame(result["rows"])
            sheet_tab = push_to_sheets(out_df, sheet_url.strip())
            result["sheet_tab"] = sheet_tab
        except Exception as e:
            result["sheet_error"] = str(e)

    clean_nan_in_rows(result["rows"])

    return result


@app.post("/download-gas")
async def download_gas(
    homebox: UploadFile = File(...),
    tseg:    UploadFile = File(...),
):
    hb = await read_csv(homebox, "Homebox file")
    ts = await read_csv(tseg, "TSEG file")

    try:
        result = run_gas_check(hb, ts)
    except ColumnNotFoundError as e:
        raise HTTPException(400, str(e))

    buf = io.StringIO()
    result.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gas_flagged_{date.today()}.csv"}
    )


def open_browser():
    webbrowser.open("http://localhost:8000")


if __name__ == "__main__":
    threading.Timer(1.5, open_browser).start()
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
