"""
Centralized configuration settings for the Loyalty Points Management System.

Keeping settings in one file makes it easy to switch between SQLite (for local
prototyping and hackathons) and PostgreSQL (for production), and ensures the
random seed and business constants are consistent across the whole codebase.
"""

from __future__ import annotations

import os
from pathlib import Path

# Backend & project root directories (backend: c:\CandidateWorkspace\backend, root: c:\CandidateWorkspace)
BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = BACKEND_DIR.parent
DATABASE_DIR = BACKEND_DIR / "database"

# Data & documentation output directories
DATA_DIR = BASE_DIR / "data"
CSV_DIR = DATA_DIR / "csv"
JSON_DIR = DATA_DIR / "json"
DOCS_DIR = BASE_DIR / "docs"
FRONTEND_DIR = BASE_DIR / "frontend"

# Default SQLite database path; override with DATABASE_URL env var for PostgreSQL
DEFAULT_DB_PATH = BASE_DIR / "loyalty.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}")

# Reproducibility constant required by project specification
RANDOM_SEED = 20261022

# Default reference date for deterministic simulation & expiry evaluation
DEFAULT_SIMULATION_END_DATE = "2026-11-11T00:00:00"

# Default business rule constants (mirrored in the `rules` and `tiers` tables)
DEFAULT_BASE_POINTS_PER_DOLLAR = 10
DEFAULT_EXPIRY_DAYS = 365
DEFAULT_TAX_RATE = 0.08

# Tier thresholds based strictly on qualifying net spend (never gross spend)
TIER_DEFINITIONS = [
    {
        "tier_id": "TIER-BRONZE",
        "tier_name": "Bronze",
        "tier_level": 1,
        "min_qualifying_spend": 0.00,
        "max_qualifying_spend": 999.99,
        "earn_rate_multiplier": 1.0,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "is_active": 1,
    },
    {
        "tier_id": "TIER-SILVER",
        "tier_name": "Silver",
        "tier_level": 2,
        "min_qualifying_spend": 1000.00,
        "max_qualifying_spend": 4999.99,
        "earn_rate_multiplier": 1.5,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "is_active": 1,
    },
    {
        "tier_id": "TIER-GOLD",
        "tier_name": "Gold",
        "tier_level": 3,
        "min_qualifying_spend": 5000.00,
        "max_qualifying_spend": None,
        "earn_rate_multiplier": 2.0,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "is_active": 1,
    },
]

