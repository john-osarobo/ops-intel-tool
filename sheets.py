import json
import os

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pandas as pd
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"


def get_client():
    env_creds = os.environ.get("GOOGLE_CREDENTIALS")
    if env_creds:
        info = json.loads(env_creds)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif CREDENTIALS_PATH.exists():
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    else:
        raise RuntimeError(
            "No Google credentials found. Set the GOOGLE_CREDENTIALS env var "
            "or place credentials.json in the project root."
        )
    return gspread.authorize(creds)


def push_to_sheets(df: pd.DataFrame, sheet_url: str) -> str:
    client = get_client()
    spreadsheet = client.open_by_url(sheet_url)
    tab_name = datetime.now().strftime("%Y-%m-%d %H:%M")
    worksheet = spreadsheet.add_worksheet(title=tab_name, rows=len(df) + 10, cols=len(df.columns) + 2)

    # Convert values to native Python types to avoid gspread serialization issues
    header = df.columns.tolist()
    rows = df.astype(object).where(df.notna(), "").values.tolist()
    worksheet.update([header] + rows)
    worksheet.freeze(rows=1)
    return tab_name
