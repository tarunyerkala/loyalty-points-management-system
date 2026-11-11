"""
Database Seeder & Validation Report Generator.

Loads the synthetic CSV datasets from `data/csv/` into SQLite (or PostgreSQL)
in strict parent-to-child order so every foreign key constraint is satisfied,
synchronizes `id_sequences`, runs independent anomaly detection, and writes
`docs/validation_summary.md` and `docs/reproducibility_report.md`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import CSV_DIR, DATABASE_DIR, DEFAULT_DB_PATH, DOCS_DIR
from app.database import SessionLocal, engine, init_db_schema
from app.services.anomaly_detector import detect_anomalies, run_reconciliation_audit
from app.services.pandas_analytics import profile_csv_integrity

TABLE_LOAD_SPECS: list[tuple[str, list[str], set[str], set[str]]] = [
    # (table_name, columns, int_cols, float_cols)
    (
        "tiers",
        [
            "tier_id", "tier_name", "tier_level", "min_qualifying_spend",
            "max_qualifying_spend", "earn_rate_multiplier",
            "effective_from", "effective_to", "is_active",
        ],
        {"tier_level", "is_active"},
        {"min_qualifying_spend", "max_qualifying_spend", "earn_rate_multiplier"},
    ),
    (
        "rules",
        [
            "rule_id", "rule_name", "rule_type", "tier_id",
            "base_points_per_currency", "multiplier", "expiry_days",
            "min_spend", "exclude_tax", "exclude_shipping", "exclude_discount",
            "effective_from", "effective_to", "status", "created_at",
        ],
        {"expiry_days", "exclude_tax", "exclude_shipping", "exclude_discount"},
        {"base_points_per_currency", "multiplier", "min_spend"},
    ),
    (
        "rewards",
        [
            "reward_id", "reward_name", "description", "category",
            "points_required", "min_tier_level", "stock_quantity",
            "is_active", "effective_from", "effective_to", "created_at",
        ],
        {"points_required", "min_tier_level", "stock_quantity", "is_active"},
        set(),
    ),
    (
        "customers",
        [
            "customer_id", "full_name", "email", "phone", "city",
            "segment", "status", "joined_at", "created_at",
        ],
        set(),
        set(),
    ),
    (
        "loyalty_accounts",
        [
            "account_id", "customer_id", "tier_id", "points_balance",
            "lifetime_points_earned", "lifetime_points_redeemed",
            "lifetime_points_expired", "qualifying_spend", "status",
            "created_at", "updated_at",
        ],
        {
            "points_balance",
            "lifetime_points_earned",
            "lifetime_points_redeemed",
            "lifetime_points_expired",
        },
        {"qualifying_spend"},
    ),
    (
        "orders",
        [
            "order_id", "customer_id", "order_date", "gross_amount",
            "discount_amount", "tax_amount", "shipping_amount",
            "net_eligible_amount", "returned_amount", "status", "created_at",
        ],
        set(),
        {
            "gross_amount",
            "discount_amount",
            "tax_amount",
            "shipping_amount",
            "net_eligible_amount",
            "returned_amount",
        },
    ),
    (
        "order_lines",
        [
            "order_line_id", "order_id", "sku", "product_name", "category",
            "quantity", "unit_price", "discount_amount", "line_net_amount",
            "is_points_eligible", "returned_quantity", "status",
        ],
        {"quantity", "is_points_eligible", "returned_quantity"},
        {"unit_price", "discount_amount", "line_net_amount"},
    ),
    (
        "redemptions",
        [
            "redemption_id", "account_id", "reward_id", "quantity",
            "points_used", "status", "failure_reason", "idempotency_key", "redeemed_at",
        ],
        {"quantity", "points_used"},
        set(),
    ),
    (
        "expiry_batches",
        [
            "expiry_batch_id", "account_id", "source_transaction_id",
            "original_points", "remaining_points", "expired_points",
            "expiry_date", "status", "expired_at", "created_at",
        ],
        {"original_points", "remaining_points", "expired_points"},
        set(),
    ),
    (
        "points_transactions",
        [
            "transaction_id", "account_id", "order_id", "redemption_id",
            "expiry_batch_id", "reference_transaction_id", "rule_id",
            "transaction_type", "points_delta", "balance_after", "status",
            "idempotency_key", "description", "created_at",
        ],
        {"points_delta", "balance_after"},
        set(),
    ),
    (
        "tier_history",
        [
            "history_id", "account_id", "old_tier_id", "new_tier_id",
            "qualifying_spend_at_change", "change_type", "reason", "changed_at",
        ],
        {"history_id"},
        {"qualifying_spend_at_change"},
    ),
]


def _parse_csv_rows(
    csv_path: Path,
    cols: list[str],
    int_cols: set[str],
    float_cols: set[str],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed: list[Any] = []
            for col in cols:
                val = row[col]
                if val == "" or val is None:
                    parsed.append(None)
                elif col in int_cols:
                    parsed.append(int(val))
                elif col in float_cols:
                    parsed.append(float(val))
                else:
                    parsed.append(val)
            rows.append(tuple(parsed))
    return rows


def seed_sqlite_from_csv(
    csv_dir: Path = CSV_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    reset_db: bool = True,
) -> dict[str, int]:
    """
    Bulk load generated CSVs into SQLite in <5 seconds with full FK integrity.
    """
    if reset_db:
        for suffix in ("", "-wal", "-shm"):
            p = Path(f"{db_path}{suffix}")
            if p.exists():
                p.unlink()

    schema_sql = (DATABASE_DIR / "schema_sqlite.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    loaded_counts: dict[str, int] = {}

    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.executescript(schema_sql)

        with conn:
            for table, cols, int_cols, float_cols in TABLE_LOAD_SPECS:
                csv_file = csv_dir / f"{table}.csv"
                if not csv_file.exists():
                    continue
                placeholders = ", ".join("?" for _ in cols)
                col_list = ", ".join(cols)
                sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
                batch = _parse_csv_rows(csv_file, cols, int_cols, float_cols)
                conn.executemany(sql, batch)
                loaded_counts[table] = len(batch)

            manifest_path = DOCS_DIR / "source_manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                seq_map = manifest.get("sequence_next_values", {})
                conn.executemany(
                    "INSERT OR REPLACE INTO id_sequences (seq_name, next_value) VALUES (?, ?)",
                    list(seq_map.items()),
                )
    finally:
        conn.close()

    return loaded_counts


def validate_and_write_reports(csv_dir: Path = CSV_DIR) -> dict[str, Any]:
    """
    Run independent anomaly detection against the loaded database, compare findings
    with `ground_truth.csv` (evaluation only!), update `detection_status`, and generate
    `docs/validation_summary.md` and `docs/reproducibility_report.md`.
    """
    db = SessionLocal()
    try:
        reconcile = run_reconciliation_audit(db)
        anomaly_res = detect_anomalies(db, limit=2000)
    finally:
        db.close()

    detected_pairs = {
        (item["record_id"], item["issue_type"]): item
        for item in anomaly_res["anomalies"]
    }

    gt_path = csv_dir / "ground_truth.csv"
    gt_rows: list[dict[str, str]] = []
    if gt_path.exists():
        with gt_path.open("r", encoding="utf-8", newline="") as f:
            gt_rows = list(csv.DictReader(f))

    tp = 0
    fn = 0
    gt_pairs: set[tuple[str, str]] = set()
    by_type_stats: dict[str, dict[str, int]] = {}

    for row in gt_rows:
        pair = (row["record_id"], row["issue_type"])
        gt_pairs.add(pair)
        t = row["issue_type"]
        by_type_stats.setdefault(t, {"injected": 0, "detected": 0, "missed": 0})
        by_type_stats[t]["injected"] += 1
        if pair in detected_pairs:
            row["detection_status"] = "DETECTED"
            tp += 1
            by_type_stats[t]["detected"] += 1
        else:
            row["detection_status"] = "MISSED"
            fn += 1
            by_type_stats[t]["missed"] += 1

    # Write updated detection_status back to ground_truth.csv and ground_truth.json
    if gt_rows:
        with gt_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "record_id",
                    "issue_type",
                    "expected_outcome",
                    "actual_outcome",
                    "detection_status",
                ],
            )
            writer.writeheader()
            writer.writerows(gt_rows)
        gt_json = csv_dir.parent / "json" / "ground_truth.json"
        if gt_json.parent.exists():
            gt_json.write_text(json.dumps(gt_rows, indent=2), encoding="utf-8")

    fp = len([p for p in detected_pairs if p not in gt_pairs])
    precision = round((tp / (tp + fp)) * 100, 2) if (tp + fp) else 100.0
    recall = round((tp / (tp + fn)) * 100, 2) if (tp + fn) else 100.0

    # Write Validation Summary Markdown
    val_lines = [
        "# Validation & Anomaly Detection Summary",
        "",
        "## Independent Evaluation vs Ground Truth",
        "",
        "> Detection ran strictly on operational database tables without reading `ground_truth.csv`.",
        "",
        f"- **Total Accounts Checked**: `{reconcile['total_accounts_checked']:,}`",
        f"- **Accounts Reconciled Cleanly**: `{reconcile['matched_accounts']:,}`",
        f"- **Balance Mismatches Found**: `{reconcile['mismatched_accounts_count']:,}`",
        f"- **Total Anomalies Injected (Ground Truth)**: `{len(gt_rows)}`",
        f"- **Total Anomalies Detected**: `{anomaly_res['total_anomalies']}`",
        f"- **True Positives (TP)**: `{tp}`",
        f"- **False Positives (FP)**: `{fp}`",
        f"- **False Negatives (FN)**: `{fn}`",
        f"- **Precision**: `{precision:.2f}%`",
        f"- **Recall**: `{recall:.2f}%`",
        f"- **Rejected Insufficient-Balance Attempts Logged**: `{anomaly_res['rejected_redemption_attempts_count']:,}`",
        "",
        "## Breakdown by Anomaly Type",
        "",
        "| Issue Type | Injected | Detected | Missed | Recall |",
        "|---|---:|---:|---:|---:|",
    ]
    for issue_type, st in sorted(by_type_stats.items()):
        rec = (st["detected"] / st["injected"] * 100.0) if st["injected"] else 0.0
        val_lines.append(
            f"| `{issue_type}` | {st['injected']} | {st['detected']} | {st['missed']} | {rec:.1f}% |"
        )

    csv_profile = profile_csv_integrity(csv_dir)
    if csv_profile:
        val_lines.extend(
            [
                "",
                "## Pandas Primary-Key & Null Integrity Profile",
                "",
                "| CSV File | Rows | Unique PKs | Null PKs | Valid |",
                "|---|---:|---:|---:|---|",
            ]
        )
        for fname, info in csv_profile.items():
            val_lines.append(
                f"| `{fname}` | {info['rows']:,} | {info['unique_pks']:,} | {info['null_pks']} | {info['pk_valid']} |"
            )

    (DOCS_DIR / "validation_summary.md").write_text("\n".join(val_lines) + "\n", encoding="utf-8")

    # Write Reproducibility Report Markdown
    manifest_path = DOCS_DIR / "source_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rep_lines = [
            "# Reproducibility Report",
            "",
            f"- **Fixed Random Seed**: `{manifest['random_seed']}`",
            f"- **Generator Script**: `{manifest['generator']}`",
            f"- **Simulation Window**: `{manifest['simulation_window']['start']}` to `{manifest['simulation_window']['end']}`",
            "",
            "## Table Row Counts & CSV SHA-256 Checksums",
            "",
            "| Table | Row Count | CSV File | SHA-256 Checksum |",
            "|---|---:|---|---|",
        ]
        for table, cnt in manifest["row_counts"].items():
            fname = f"{table}.csv"
            sha = manifest["csv_sha256_checksums"].get(fname, "-")
            rep_lines.append(f"| `{table}` | {cnt:,} | `{fname}` | `{sha}` |")
        gt_sha = manifest["csv_sha256_checksums"].get("ground_truth.csv", "-")
        rep_lines.append(
            f"| `ground_truth` | {manifest['ground_truth_count']:,} | `ground_truth.csv` | `{gt_sha}` |"
        )
        (DOCS_DIR / "reproducibility_report.md").write_text(
            "\n".join(rep_lines) + "\n", encoding="utf-8"
        )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "by_type": by_type_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed SQLite database from generated CSVs.")
    parser.add_argument("--csv-dir", type=Path, default=CSV_DIR)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    engine.dispose()
    counts = seed_sqlite_from_csv(csv_dir=args.csv_dir, db_path=args.db_path, reset_db=True)
    init_db_schema()
    eval_res = validate_and_write_reports(csv_dir=args.csv_dir)
    print("Database seeded:", json.dumps(counts, indent=2))
    print("Validation report:", json.dumps(eval_res, indent=2))


if __name__ == "__main__":
    main()

