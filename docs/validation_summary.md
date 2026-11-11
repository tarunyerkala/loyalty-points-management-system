# Validation & Anomaly Detection Summary

## Independent Evaluation vs Ground Truth

> Detection ran strictly on operational database tables without reading `ground_truth.csv`.

- **Total Accounts Checked**: `20,000`
- **Accounts Reconciled Cleanly**: `19,990`
- **Balance Mismatches Found**: `10`
- **Total Anomalies Injected (Ground Truth)**: `50`
- **Total Anomalies Detected**: `50`
- **True Positives (TP)**: `50`
- **False Positives (FP)**: `0`
- **False Negatives (FN)**: `0`
- **Precision**: `100.00%`
- **Recall**: `100.00%`
- **Rejected Insufficient-Balance Attempts Logged**: `309`

## Breakdown by Anomaly Type

| Issue Type | Injected | Detected | Missed | Recall |
|---|---:|---:|---:|---:|
| `BALANCE_MISMATCH` | 10 | 10 | 0 | 100.0% |
| `DOUBLE_EXPIRATION` | 10 | 10 | 0 | 100.0% |
| `INCORRECT_TIER_GROSS_SPEND` | 10 | 10 | 0 | 100.0% |
| `INVALID_REDEMPTION_OVERDRAFT` | 10 | 10 | 0 | 100.0% |
| `MISSING_REVERSAL` | 10 | 10 | 0 | 100.0% |

## Pandas Primary-Key & Null Integrity Profile

| CSV File | Rows | Unique PKs | Null PKs | Valid |
|---|---:|---:|---:|---|
| `customers.csv` | 20,000 | 20,000 | 0 | True |
| `loyalty_accounts.csv` | 20,000 | 20,000 | 0 | True |
| `orders.csv` | 100,000 | 100,000 | 0 | True |
| `order_lines.csv` | 200,285 | 200,285 | 0 | True |
| `points_transactions.csv` | 300,000 | 300,000 | 0 | True |
| `redemptions.csv` | 168,074 | 168,074 | 0 | True |
| `expiry_batches.csv` | 100,000 | 100,000 | 0 | True |
