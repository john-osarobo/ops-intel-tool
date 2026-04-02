# homebox Ops Intel

Internal operational intelligence tool for the Homebox Sheffield ops team. Automates TSEG order monitoring, SLA breach detection and supplier performance tracking — replacing manual daily cross-checks across Trevor, the TSEG WIP sheet and Filament that previously consumed up to half a working day.

Built with Python, FastAPI and pandas. Runs in the browser — no installation required per user once deployed.

---

## Modules

### Gas checker
Cross-references Homebox meter data against TSEG supplier data to flag electricity-only properties incorrectly assigned a gas service.

- Auto-detects column names across different Trevor/TSEG export formats
- Joins on TSEG ID with normalised matching
- Three flags: **Electricity only** (action required), **Gas confirmed** (ok), **MPRN mismatch** (review manually)
- Flagged results displayed with orange/green/amber badges
- Download results as CSV or push to a dated Google Sheets tab

### SLA monitor
Filters all orders in "awaiting feedback" status and calculates days elapsed since last update.

- RAG-rated: **Breached** (8+ days, red), **At risk** (6-7 days, amber), **Within SLA** (green)
- Days elapsed shown as large coloured numbers for at-a-glance scanning
- Supplier breakdown with bar chart showing which providers have the most breaches
- Search by order ID with real-time filtering
- Sortable columns — click any header, defaults to worst-first by days elapsed

### WIP cross-reference
Connects directly to the live TSEG WIP Google Sheet, reads all active tabs and joins every row to Trevor data by TSEG ID.

**Tabs read:** Objections, Missing Meter Information, Gas Deleted, Switch Issues, API Order Errors, ET Requests, Missing Tenant Details

- Objections ranked by supplier with horizontal orange bar chart
- Supplier WIP heat map showing blocker breakdown per supplier
- **Supply Status** pulled from WIP sheet — displayed as coloured tags (Submitted = green, Missing Meter Information = amber, other = grey)
- **Services Start** date pulled and formatted (e.g. 2 Apr 2026)
- Filter by blocker type using tab pills
- **"Not on WIP" filter** — isolates orders with no WIP match, highlighted in red when viewing All
- Search by order ID across all columns
- Sortable columns with days elapsed defaulting to worst-first

---

## UI features

- Light/dark mode toggle saved to localStorage
- Homebox brand orange (#F05A28) accent throughout
- Four global metric cards: Orders processed, SLA breached, At risk, Active objections
- Tab badges showing breach count (SLA) and matched count (WIP)
- Flat design with 0.5px borders, no gradients or shadows
- Drag-and-drop CSV upload zones
- Real-time search and column sorting on SLA and WIP tables
- Proper error messages for failed uploads and missing columns

---

## Project structure

```
homebox-tools/
├── app.py                 # FastAPI server — routes, file validation, startup
├── gas_checker.py         # Gas fuel error detection (also standalone CLI)
├── sla_checker.py         # SLA breach monitoring
├── wip_checker.py         # WIP cross-reference (reads live Google Sheets)
├── sheets.py              # Google Sheets push integration
├── utils.py               # Shared — column detection, RAG logic, helpers
├── build_presentation.py  # Standalone PPTX pitch deck generator
├── requirements.txt       # Python dependencies
├── .gitignore
└── static/
    └── index.html         # Single-page frontend (dark/light theme)
```

---

## Setup

### Prerequisites
- Python 3.10+
- Google Cloud service account with Sheets and Drive API access (for Sheets push and WIP sync features)

### Install

```bash
pip install -r requirements.txt
```

### Google credentials

**Option A — Environment variable (recommended for deployment):**
```bash
export GOOGLE_CREDENTIALS='{"type":"service_account","project_id":"..."}'
```

**Option B — Local file (development only):**
Place `credentials.json` in the project root. This file is gitignored.

### Run

```bash
python app.py
```

Opens automatically at `http://localhost:8000`.

---

## Usage

1. **Gas checker** — Upload Homebox Trevor export + TSEG supplier export. Click "Run analysis".
2. **SLA monitor** — Upload Homebox Trevor export. Click "Run analysis".
3. **WIP cross-reference** — Upload Homebox Trevor export, paste the WIP Google Sheets URL. Click "Run analysis".

All modules auto-detect column names so they work across different export formats without manual renaming.

### CLI (gas checker only)

```bash
python gas_checker.py --homebox homebox_export.csv --tseg tseg_data.csv --output flagged.csv
```

---

## Tech stack

| Component | Purpose |
|---|---|
| Python 3.12 | Language |
| FastAPI | Web framework |
| pandas | Data processing |
| gspread + google-auth | Google Sheets integration |
| Tailwind CSS (CDN) | Frontend styling |

---

## Security

- All processing is in-memory per request — no data stored server-side
- Google credentials loaded from environment variable in production
- CORS restricted to localhost by default
- File upload size limited to 20 MB
