import csv
import datetime as dt
from pathlib import Path
from typing import Dict

from global_utility import RESULTS_FILE, TestResult


def submit_results(user: str, results: Dict[str, TestResult]) -> Path:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "timestamp": timestamp,
        "user": user,
    }
    for key, result in results.items():
        row[result.name] = result.status
    row["remark"] = "; ".join(
        f"{r.name}:{r.detail}" for r in results.values() if r.detail
    )

    write_header = not RESULTS_FILE.exists()
    with RESULTS_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return RESULTS_FILE
