# LoyaltyHub — Loyalty Points Management & Audit Platform

A beginner-friendly, end-to-end **Loyalty Points Management System** built with **Python, FastAPI, SQLite/PostgreSQL, Pandas, NumPy, Faker, Chart.js, and Pytest**.

---

## 1. System Architecture (Plain English)

Think of this system like a **bank ledger for reward points**:
1. **Database Layer (`backend/database/`, `loyalty.db` at project root)**: Stores 10 core tables (`customers`, `loyalty_accounts`, `tiers`, `rules`, `orders`, `order_lines`, `rewards`, `redemptions`, `expiry_batches`, `points_transactions`) plus `tier_history` and `id_sequences`.
2. **Business Services (`backend/app/services/`)**: Each core rule lives in its own clean Python module:
   - `accrual.py`: Calculates points from qualifying net spend (excluding tax, shipping, discounts, and ineligible items) and creates an expiry lot.
   - `redemption.py`: Uses atomic database locks + FIFO lot deduction so concurrent requests can never overspend.
   - `reversal.py`: Handles full and partial order returns without modifying historical accrual entries.
   - `expiration.py`: Idempotently expires only remaining unspent points once their expiry date passes.
   - `tier_manager.py`: Upgrades and downgrades customers between Bronze, Silver, and Gold strictly on qualifying net spend.
   - `anomaly_detector.py`: Independently audits all accounts and flags 5 categories of accounting/rule errors without reading `ground_truth.csv`.
3. **REST API (`backend/app/routes/`, `backend/app/main.py`)**: Exposes FastAPI endpoints with automatic validation and Swagger UI at `/docs`.
4. **Frontend Dashboard (`frontend/`)**: Responsive HTML/CSS/JS + Chart.js web app with 7 functional tabs (Dashboard, Customers, Orders, Transactions, Rewards, Analytics, Audit & Validation).
5. **Synthetic Data Generator (`backend/data_generator/`)**: Deterministically creates 20,000 customers, 100,000 orders, and 300,000 points transactions using seed `20261022`, exports CSV + JSON, and injects 50 labelled test anomalies.

---

## 2. Project Folder Structure

```text
c:\CandidateWorkspace\
├── backend\
│   ├── app\
│   │   ├── config.py                  # Central settings, paths, seed=20261022, tier definitions
│   │   ├── database.py                # SQLAlchemy engine, WAL mode, row/write locking
│   │   ├── models.py                  # ORM models for all entities
│   │   ├── schemas.py                 # Pydantic request validation models
│   │   ├── main.py                    # FastAPI app, CORS middleware & static fallback serving
│   │   ├── services\                  # Modular business logic (accrual, redemption, reversal, expiration, tier, audit)
│   │   └── routes\                    # FastAPI REST endpoints
│   ├── data_generator\
│   │   ├── generate_data.py           # Seeded synthetic dataset generator (CSV & JSON)
│   │   ├── inject_anomalies.py        # Injects 5 anomaly scenarios & ground_truth.csv
│   │   └── seed_database.py           # Loads CSVs into SQLite & generates validation reports
│   ├── database\
│   │   ├── schema_sqlite.sql          # SQLite DDL with constraints & indexes
│   │   └── schema_postgres.sql        # PostgreSQL production DDL
│   ├── tests\                         # Automated Pytest suite (21 tests)
│   ├── pytest.ini
│   └── requirements.txt
├── frontend\
│   ├── index.html                     # 7-page responsive dashboard
│   ├── styles.css                     # Clean responsive styling
│   └── app.js                         # API integration (http://127.0.0.1:8001) & Chart.js visualizations
├── data\
│   ├── csv\                           # Generated CSV files + ground_truth.csv
│   └── json\                          # Generated JSON files
├── docs\                              # ER diagram, data dictionary, API docs, reports, presentation
├── loyalty.db                         # Seeded SQLite database (shared at project root, gitignored)
├── .gitignore
└── README.md
```

---

## 3. Running Frontend & Backend Separately (Windows / VS Code)

Open `c:\CandidateWorkspace` in VS Code and use two PowerShell terminals (`Ctrl + ~`).

### Backend Setup & Run (`backend/`)

#### Step 1: Install Backend Dependencies
```powershell
cd backend
pip install -r requirements.txt
```

#### Step 2: Run the Automated Pytest Suite
```powershell
cd backend
pytest -v
```

#### Step 3: (Optional) Regenerate Dataset & Seed the Database
When running locally, [`loyalty.db`](loyalty.db) lives at the project root (`c:\CandidateWorkspace\loyalty.db`) and is resolved automatically via `backend/app/config.py`. On a fresh Git clone (where `loyalty.db` is excluded by `.gitignore`), run the commands below to re-seed `loyalty.db` or regenerate deterministic CSV/JSON datasets (seed `20261022`):
- **Small prototype dataset** (fast dev test):
```powershell
cd backend
python -m data_generator.generate_data --customers 500 --orders 2500 --target-transactions 7500 --anomalies-per-type 3 --no-json
python -m data_generator.seed_database
```
- **Full baseline dataset** (`20,000` customers, `100,000` orders, `300,000` transactions, seed `20261022`):
```powershell
cd backend
python -m data_generator.generate_data
python -m data_generator.seed_database
```

#### Step 4: Start the FastAPI Backend Server
```powershell
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```
- **Backend API Base**: http://127.0.0.1:8001
- **Swagger API Docs**: http://127.0.0.1:8001/docs

### Frontend Setup & Run (`frontend/`)

In a second terminal, serve the static frontend on port `5500` (allowed by CORS in `backend/app/main.py` and wired to `http://127.0.0.1:8001` in `frontend/app.js`):
```powershell
cd frontend
python -m http.server 5500 --bind 127.0.0.1
```
Open in your browser:
- **Frontend Dashboard**: http://127.0.0.1:5500/
- *(Fallback same-origin dashboard when running only the backend: http://127.0.0.1:8001/)*

### Optional: PostgreSQL Switch
To run against PostgreSQL instead of SQLite:
1. Execute `backend/database/schema_postgres.sql` on your PostgreSQL database.
2. Set `DATABASE_URL` and start the backend from `backend/`:
   ```powershell
   cd backend
   $env:DATABASE_URL="postgresql+psycopg2://postgres:password@localhost:5432/loyalty"
   uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```

---

## 4. Documentation Index
- [Entity Relationship Diagram](docs/er_diagram.md)
- [Data Dictionary](docs/data_dictionary.md)
- [API Documentation](docs/api_documentation.md)
- [Validation Summary](docs/validation_summary.md)
- [Reproducibility Report](docs/reproducibility_report.md)
- [Source Manifest](docs/source_manifest.json)
- [Hackathon Presentation Pack](docs/hackathon_presentation.md)

