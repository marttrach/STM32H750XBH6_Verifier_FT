"""
MySQL integration scaffolding for MES uploads.
------------------------------------------------
- Provides a lightweight wrapper to connect, insert, and verify test rows.
- Includes smoke-test helpers and a test checklist to run during START TEST
  (especially when Skip Test is enabled so only MES/MySQL connectivity is exercised).
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_DIR = Path("LOG")
LOG_DIR.mkdir(exist_ok=True)


def _build_logger(name: str, filename: str, tag: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_DIR / filename, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] [" + tag + "] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


MYSQL_LOGGER = _build_logger("MySQL", "MySQL.log", "MySQL")

try:
    import mysql.connector as mysql_driver  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mysql_driver = None


@dataclass
class DbTestRecord:
    """Row schema aligned with factory sample table."""

    emp_no: str
    fixture_id: str
    dut_pos: str
    sn: str
    sw_version: str
    start_time: str  # "%Y-%m-%d %H:%M:%S"
    test_duration: int
    dut_result: str
    first_fail: str


class MySQLClient:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        db_name: str,
        table_name: str,
        enable: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.db_name = db_name
        self.table_name = table_name
        self.enable = enable
        self._conn = None

    def connect(self) -> bool:
        if not self.enable:
            MYSQL_LOGGER.info("MySQL disabled; skipping connect.")
            return False
        if not mysql_driver:
            MYSQL_LOGGER.error("mysql-connector-python is not installed; cannot connect.")
            return False
        try:
            self._conn = mysql_driver.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.db_name,
                connection_timeout=5,
            )
            MYSQL_LOGGER.info("Connected to MySQL at %s:%s", self.host, self.port)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            MYSQL_LOGGER.error("MySQL connect failed: %s", exc)
            self._conn = None
            return False

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.close()
                MYSQL_LOGGER.info("MySQL connection closed.")
        finally:
            self._conn = None

    def _ensure_connection(self) -> bool:
        if self._conn:
            return True
        return self.connect()

    def insert_record(self, record: DbTestRecord) -> bool:
        """Insert one record; returns True when successful."""
        if not self._ensure_connection():
            return False
        sql = (
            f"INSERT INTO {self.table_name} "
            "(EMPNo, Fixture_ID, DUT_POS, SN, SW_VERSION, START_TIME, TEST_DURATION, DUT_TEST_RESULT, FIRST_FAIL) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        params = (
            record.emp_no,
            record.fixture_id,
            record.dut_pos,
            record.sn,
            record.sw_version,
            record.start_time,
            record.test_duration,
            record.dut_result,
            record.first_fail,
        )
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            self._conn.commit()
            MYSQL_LOGGER.info("Inserted record for SN=%s", record.sn)
            cursor.close()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            MYSQL_LOGGER.error("Insert failed for SN=%s: %s", record.sn, exc)
            return False

    def fetch_latest_result(self, sn: str) -> Optional[str]:
        """Read back last DUT_TEST_RESULT for the SN."""
        if not self._ensure_connection():
            return None
        sql = (
            f"SELECT DUT_TEST_RESULT FROM `{self.table_name}` "
            "WHERE SN=%s ORDER BY SRC_DATETIME DESC LIMIT 1"
        )
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, (sn,))
            row = cursor.fetchone()
            cursor.close()
            if row:
                MYSQL_LOGGER.info("Fetched latest result for SN=%s -> %s", sn, row[0])
                return row[0]
            MYSQL_LOGGER.warning("No rows found for SN=%s", sn)
            return None
        except Exception as exc:  # pragma: no cover - defensive
            MYSQL_LOGGER.error("Query failed for SN=%s: %s", sn, exc)
            return None

    def insert_and_verify(self, record: DbTestRecord) -> bool:
        """Write then read-back verification, mirroring factory logic."""
        if not self.insert_record(record):
            return False
        read_back = self.fetch_latest_result(record.sn)
        if read_back is None:
            return False
        if read_back != record.dut_result:
            MYSQL_LOGGER.error(
                "Verification mismatch for SN=%s (expected %s, got %s)",
                record.sn,
                record.dut_result,
                read_back,
            )
            return False
        return True

    @staticmethod
    def test_plan() -> List[str]:
        return [
            "Connectivity: open DB connection with provided credentials; log success/failure.",
            "Schema readiness: confirm table exists and has EMPNo/Fixture_ID/DUT_POS/SN/SW_VERSION/START_TIME/TEST_DURATION/DUT_TEST_RESULT/FIRST_FAIL columns.",
            "Insert smoke: write one PASS row with test SN; expect commit success.",
            "Verify read-back: SELECT last row by SN ordered by SRC_DATETIME; compare DUT_TEST_RESULT.",
            "Error handling: simulate wrong credentials or missing table; ensure [MySQL] log captures failure.",
        ]

    def smoke_tests(self, sample_sn: str, sw_version: str = "SMOKE") -> Dict[str, bool]:
        """Run a minimal DB path; safe to call when Skip Test is enabled."""
        outcome: Dict[str, bool] = {"connect": False, "insert_verify": False}
        if not self.connect():
            return outcome
        outcome["connect"] = True
        record = DbTestRecord(
            emp_no="DB_SMOKE",
            fixture_id="FIXTURE_SMOKE",
            dut_pos="1",
            sn=sample_sn,
            sw_version=sw_version,
            start_time="2025-01-01 00:00:00",
            test_duration=1,
            dut_result="PASS",
            first_fail="N/A",
        )
        outcome["insert_verify"] = self.insert_and_verify(record)
        self.close()
        return outcome
