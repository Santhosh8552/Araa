"""
AraaBot Enterprise QA Automation Engine (Testing & Quality Center Core).

Manages:
- Suite & test case registration (`qa_test_suites`, `qa_test_cases`)
- Background execution queue, worker lifecycle, retries, timeouts, cancellation & duplicate guard
- Isolated subprocess execution (delegating to qa_suite_runners & qa_playwright_runner)
- Real-time log persistence (`qa_test_logs`) & artifact registry (`qa_test_artifacts`)
- Automated Defect creation & strict retest verification (`qa_defects`)
- Deployment regression gating (never enables Real Mode!) & scheduled interval runner
- Live, zero-fake-data component health & dashboard metrics
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from database import connect, query, query_one, write
    from migrations import _MIGRATION_011_SQL
    from qa_suite_runners import SUITE_CATALOG, sanitize_text, sanitize_value
    from qa_playwright_runner import execute_playwright_suite
    from qa_reports import compute_historical_comparison
except ImportError:
    from backend.database import connect, query, query_one, write
    from backend.migrations import _MIGRATION_011_SQL
    from backend.qa_suite_runners import SUITE_CATALOG, sanitize_text, sanitize_value
    from backend.qa_playwright_runner import execute_playwright_suite
    from backend.qa_reports import compute_historical_comparison

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent

DEFAULT_QA_CONFIG: List[Tuple[str, str, str, str]] = [
    ("environment", "ISOLATED_STAGING", "string", "Target environment label (isolated DB for destructive suites)"),
    ("enabled_suites", json.dumps([s["suite_id"] for s in SUITE_CATALOG]), "json", "Comma/JSON list of enabled test suites"),
    ("timeout_sec", "90", "int", "Per-run sandbox timeout in seconds"),
    ("retry_count", "1", "int", "Automatic retry count for transient case failures (0-3)"),
    ("browser", "chromium", "string", "Playwright browser engine: chromium, firefox, webkit"),
    ("parallel_execution", "0", "bool", "Enable parallel execution in performance benchmarks"),
    ("capture_screenshots", "1", "bool", "Automatically capture screenshots on Playwright failures"),
    ("capture_video", "0", "bool", "Capture WebM video recordings for Playwright sessions"),
    ("capture_trace", "1", "bool", "Capture Playwright trace archives for failed/E2E runs"),
    ("api_testing_enabled", "1", "bool", "Include Automated API Discovery & Validation in Run All"),
    ("security_testing_enabled", "1", "bool", "Include Security & Penetration Defense suite in Run All"),
    ("performance_testing_enabled", "1", "bool", "Include Performance & Load Benchmark suite in Run All"),
    ("report_retention_days", "30", "int", "Days to retain persisted QA reports & screenshots"),
    ("scheduled_regression_enabled", "0", "bool", "Run scheduled automated regression suite in background"),
    ("regression_interval_min", "60", "int", "Minutes between scheduled automated regression runs"),
    ("concurrent_users", "4", "int", "Performance benchmark simulated concurrent sessions"),
    ("request_count", "24", "int", "Performance benchmark request count"),
    ("duration_sec", "10", "int", "Performance test target duration window (seconds)"),
    ("ramp_up_sec", "1", "int", "Performance worker ramp-up delay (seconds)"),
    ("live_order_testing_locked", "1", "locked_bool", "IMMUTABLE SAFETY CONTROL: Blocks automated live trading orders"),
]

_VALID_DEFECT_STATUSES = ("Open", "Investigating", "Fixed", "Retesting", "Verified", "Closed")
_VALID_SEVERITIES = ("Critical", "High", "Medium", "Low")

_INIT_LOCK = threading.Lock()
_SCHEMA_READY = False
_RUN_QUEUE: "queue.Queue[str]" = queue.Queue()
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()
_CANCEL_FLAGS: Dict[str, threading.Event] = {}
_ACTIVE_PROCS: Dict[str, subprocess.Popen] = {}
_SCHED_THREAD: Optional[threading.Thread] = None


def ensure_qa_ready(force: bool = False) -> None:
    """Create QA tables idempotently and seed default suites, cases, config & schedules."""
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return
    with _INIT_LOCK:
        if _SCHEMA_READY and not force:
            return
        conn = connect()
        try:
            conn.executescript(_MIGRATION_011_SQL)
            now = time.time()
            for suite in SUITE_CATALOG:
                conn.execute(
                    "INSERT INTO qa_test_suites(suite_id, code, name, category, description, module_path, "
                    "is_enabled, is_safe_live, requires_isolated_db, default_timeout_sec, sort_order, created_by, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(suite_id) DO UPDATE SET "
                    "name=excluded.name, category=excluded.category, description=excluded.description, "
                    "module_path=excluded.module_path, sort_order=excluded.sort_order, updated_at=excluded.updated_at",
                    (
                        suite["suite_id"], suite["code"], suite["name"], suite["category"],
                        suite["description"], suite["module_path"], 1, 1,
                        suite.get("requires_isolated_db", 1), 90, suite.get("sort_order", 100),
                        "SYSTEM", now, now,
                    ),
                )
                for cid, cname, sev, exp in suite["cases"]:
                    conn.execute(
                        "INSERT INTO qa_test_cases(case_id, suite_id, code, name, description, severity, "
                        "test_type, target_ref, expected_behavior, is_enabled, is_destructive_isolated, created_by, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(case_id) DO UPDATE SET "
                        "suite_id=excluded.suite_id, name=excluded.name, severity=excluded.severity, "
                        "expected_behavior=excluded.expected_behavior, updated_at=excluded.updated_at",
                        (
                            cid, suite["suite_id"], cid, cname, exp, sev,
                            "PLAYWRIGHT" if suite["suite_id"] == "FRONTEND" else "AUTOMATED",
                            suite["module_path"], exp, 1, suite.get("requires_isolated_db", 1),
                            "SYSTEM", now, now,
                        ),
                    )
            for k, val, vtype, desc in DEFAULT_QA_CONFIG:
                conn.execute(
                    "INSERT OR IGNORE INTO qa_test_config(config_key, config_value, value_type, description, updated_by, updated_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (k, val, vtype, desc, "SYSTEM", now),
                )
            conn.execute(
                "INSERT OR IGNORE INTO qa_test_schedules(schedule_id, name, suite_ids_json, trigger_mode, "
                "interval_minutes, is_enabled, created_by, created_at, updated_at) "
                "VALUES('SCHED_REGRESSION', 'Automated Full Regression Gate', '[\"REGRESSION\"]', 'INTERVAL', 60, 0, 'SYSTEM', ?, ?)",
                (now, now),
            )
            conn.commit()
        finally:
            conn.close()
        _SCHEMA_READY = True


def reset_schema_cache() -> None:
    """Helpful when isolated tests swap DB_PATH dynamically."""
    global _SCHEMA_READY
    _SCHEMA_READY = False


def get_qa_config() -> Dict[str, Any]:
    ensure_qa_ready()
    rows = query("SELECT * FROM qa_test_config")
    cfg: Dict[str, Any] = {}
    for r in rows:
        cfg[r["config_key"]] = r["config_value"]
    cfg["live_order_testing_locked"] = "1"
    return cfg


def update_qa_config(patch_data: Dict[str, Any], actor: str = "admin") -> Dict[str, Any]:
    """Persist safe QA config updates while enforcing immutable Real Mode risk locks."""
    ensure_qa_ready()
    allowed_keys = {k for k, _, _, _ in DEFAULT_QA_CONFIG} - {"live_order_testing_locked"}
    now = time.time()
    updated = {}
    for k, v in (patch_data or {}).items():
        if k not in allowed_keys:
            continue
        if isinstance(v, (list, dict)):
            val_str = json.dumps(v)
        elif isinstance(v, bool):
            val_str = "1" if v else "0"
        else:
            val_str = str(v)
        if k == "timeout_sec":
            val_str = str(max(10, min(int(float(val_str or 90)), 600)))
        elif k == "retry_count":
            val_str = str(max(0, min(int(float(val_str or 1)), 3)))
        elif k == "browser":
            b = val_str.lower().strip()
            val_str = b if b in ("chromium", "firefox", "webkit") else "chromium"
        elif k == "concurrent_users":
            val_str = str(max(1, min(int(float(val_str or 4)), 25)))
        elif k == "request_count":
            val_str = str(max(5, min(int(float(val_str or 24)), 250)))
        elif k == "duration_sec":
            val_str = str(max(1, min(int(float(val_str or 10)), 120)))
        elif k == "ramp_up_sec":
            val_str = str(max(0, min(int(float(val_str or 1)), 10)))
        elif k == "regression_interval_min":
            val_str = str(max(5, min(int(float(val_str or 60)), 1440)))
        write(
            "INSERT INTO qa_test_config(config_key, config_value, value_type, description, updated_by, updated_at) "
            "VALUES(?, ?, 'string', '', ?, ?) "
            "ON CONFLICT(config_key) DO UPDATE SET config_value=excluded.config_value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (k, val_str, sanitize_text(actor), now),
        )
        updated[k] = val_str

    # Sync scheduled regression enablement cleanly
    if "scheduled_regression_enabled" in updated or "regression_interval_min" in updated:
        cfg_now = get_qa_config()
        sched_on = 1 if str(cfg_now.get("scheduled_regression_enabled", "0")) == "1" else 0
        iv = int(float(cfg_now.get("regression_interval_min", 60)))
        write(
            "UPDATE qa_test_schedules SET is_enabled=?, interval_minutes=?, next_run_at=?, updated_at=? WHERE schedule_id='SCHED_REGRESSION'",
            (sched_on, iv, (now + iv * 60) if sched_on else None, now),
        )
    return {"success": True, "updated": updated, "config": get_qa_config()}


def _log_run(run_id: str, level: str, source: str, message: str, result_id: str = "") -> None:
    try:
        write(
            "INSERT INTO qa_test_logs(run_id, result_id, level, source, message, logged_at) VALUES(?,?,?,?,?,?)",
            (run_id, result_id, level, source, sanitize_text(message), time.time()),
        )
    except Exception:
        pass


def _maybe_create_defect(run_id: str, result_row: Dict[str, Any]) -> str:
    """Create or update a defect automatically for failed Critical (or regression High) tests."""
    sev = str(result_row.get("severity") or "High")
    if sev not in ("Critical", "High"):
        return ""
    case_id = str(result_row.get("case_id") or "")
    existing = query_one(
        "SELECT defect_id FROM qa_defects WHERE case_id=? AND status IN ('Open','Investigating','Fixed','Retesting') "
        "ORDER BY created_at DESC LIMIT 1",
        (case_id,),
    )
    now = time.time()
    evidence_txt = sanitize_text(
        f"Run: {run_id}\nActual: {result_row.get('actual_result', '')}\nError: {result_row.get('error_message', '')}\n"
        f"{str(result_row.get('stack_trace') or '')[:1000]}"
    )
    art_id = str(result_row.get("screenshot_artifact_id") or "")
    if existing:
        did = existing["defect_id"]
        write(
            "UPDATE qa_defects SET run_id=?, result_id=?, evidence=?, screenshot_artifact_id=COALESCE(NULLIF(?,''), screenshot_artifact_id), "
            "retest_passed=0, updated_at=? WHERE defect_id=?",
            (run_id, result_row.get("result_id", ""), evidence_txt, art_id, now, did),
        )
        return did

    did = f"DEF-{time.strftime('%Y%m%d', time.gmtime(now))}-{secrets.token_hex(3).upper()}"
    prio = "P1" if sev == "Critical" else "P2"
    write(
        "INSERT INTO qa_defects(defect_id, title, description, module, run_id, case_id, result_id, "
        "severity, priority, status, assigned_admin, evidence, screenshot_artifact_id, created_by, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,'Open','UNASSIGNED',?,?,'QA_AUTO_TRIAGE',?,?)",
        (
            did,
            sanitize_text(f"[{result_row.get('suite_id')}] {result_row.get('case_name')}"),
            sanitize_text(f"Automated failure detected in test case {case_id}: {result_row.get('error_message')}"),
            sanitize_text(str(result_row.get("module") or result_row.get("suite_id") or "PLATFORM")),
            run_id,
            case_id,
            result_row.get("result_id", ""),
            sev,
            prio,
            evidence_txt,
            art_id,
            now,
            now,
        ),
    )
    return did


def _finalize_run_metrics(run_id: str, final_status_override: Optional[str] = None) -> Dict[str, Any]:
    rows = query("SELECT status, duration_ms, started_at, finished_at FROM qa_test_results WHERE run_id=?", (run_id,))
    counts = {"PASSED": 0, "FAILED": 0, "BLOCKED": 0, "SKIPPED": 0, "QUEUED": 0, "RUNNING": 0, "CANCELLED": 0}
    for r in rows:
        st = str(r.get("status") or "QUEUED").upper()
        counts[st] = counts.get(st, 0) + 1
    total = len(rows)
    executed_denom = max(1, counts["PASSED"] + counts["FAILED"] + counts["BLOCKED"])
    pass_rate = round((counts["PASSED"] / executed_denom) * 100.0, 2) if (counts["PASSED"] + counts["FAILED"] + counts["BLOCKED"]) > 0 else 0.0

    run_row = query_one("SELECT started_at, created_at FROM qa_test_runs WHERE run_id=?", (run_id,)) or {}
    now = time.time()
    started = float(run_row.get("started_at") or run_row.get("created_at") or now)
    dur_ms = round((now - started) * 1000.0, 2)

    if final_status_override:
        overall = final_status_override
    elif counts["FAILED"] > 0:
        overall = "FAILED"
    elif counts["BLOCKED"] > 0:
        overall = "BLOCKED"
    elif counts["CANCELLED"] > 0 and counts["PASSED"] == 0:
        overall = "CANCELLED"
    elif counts["PASSED"] > 0:
        overall = "PASSED"
    elif counts["SKIPPED"] > 0:
        overall = "SKIPPED"
    else:
        overall = "FAILED"

    readiness = "READY_FOR_DEPLOYMENT" if (overall == "PASSED" and counts["FAILED"] == 0 and counts["BLOCKED"] == 0) else "BLOCKED_FAILURES"
    write(
        "UPDATE qa_test_runs SET status=?, total_cases=?, passed_cases=?, failed_cases=?, blocked_cases=?, "
        "skipped_cases=?, pending_cases=?, pass_rate_pct=?, duration_ms=?, deployment_readiness=?, "
        "finished_at=?, updated_at=? WHERE run_id=?",
        (
            overall, total, counts["PASSED"], counts["FAILED"], counts["BLOCKED"],
            counts["SKIPPED"], counts["QUEUED"] + counts["RUNNING"], pass_rate, dur_ms,
            readiness, now, now, run_id,
        ),
    )
    return dict(query_one("SELECT * FROM qa_test_runs WHERE run_id=?", (run_id,)) or {})


def _execute_sandbox_subprocess(run_id: str, tasks: List[Dict[str, Any]], cfg: Dict[str, Any], cancel_ev: threading.Event) -> Dict[str, Dict[str, Any]]:
    """Run non-Playwright suite cases inside an isolated temp SQLite subprocess, streaming live events."""
    timeout_sec = max(15, int(float(cfg.get("timeout_sec") or 90)))
    perf_cfg = {
        "concurrent_users": int(float(cfg.get("concurrent_users") or 4)),
        "request_count": int(float(cfg.get("request_count") or 24)),
        "duration_sec": int(float(cfg.get("duration_sec") or 10)),
        "ramp_up_sec": int(float(cfg.get("ramp_up_sec") or 1)),
    }
    runner_script = str(BACKEND_DIR / "qa_suite_runners.py")
    payload = json.dumps({"tasks": tasks, "perf_cfg": perf_cfg, "cfg": cfg})
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["COMPANY_WORKER_ENABLED"] = "0"

    proc = subprocess.Popen(
        [sys.executable, runner_script, "--sandbox"],
        cwd=str(BASE_DIR),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _ACTIVE_PROCS[run_id] = proc
    results_map: Dict[str, Dict[str, Any]] = {}
    deadline = time.time() + timeout_sec

    try:
        if proc.stdin:
            proc.stdin.write(payload)
            proc.stdin.close()

        assert proc.stdout is not None
        while True:
            if cancel_ev.is_set():
                proc.terminate()
                break
            if time.time() > deadline:
                proc.kill()
                _log_run(run_id, "ERROR", "QA_SANDBOX", f"Sandbox worker exceeded timeout ({timeout_sec}s)")
                break
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                _log_run(run_id, "INFO", "QA_SANDBOX", line)
                continue

            etype = ev.get("type")
            cid = ev.get("case_id", "")
            if etype == "CASE_START":
                write("UPDATE qa_test_results SET status='RUNNING', started_at=? WHERE run_id=? AND case_id=?", (time.time(), run_id, cid))
                _log_run(run_id, "INFO", ev.get("suite_id", "SANDBOX"), f"Running {cid}...")
            elif etype == "CASE_RESULT":
                results_map[cid] = ev
                _record_case_outcome(run_id, ev)
        stderr_out = proc.stderr.read() if proc.stderr else ""
        if stderr_out.strip():
            for err_ln in stderr_out.strip().splitlines()[-8:]:
                if "Traceback" in err_ln or "Error" in err_ln:
                    _log_run(run_id, "WARNING", "QA_SANDBOX_STDERR", err_ln)
    finally:
        _ACTIVE_PROCS.pop(run_id, None)
        if proc.poll() is None:
            proc.kill()
    return results_map


def _record_case_outcome(run_id: str, ev: Dict[str, Any], attempt_num: int = 1) -> None:
    cid = ev["case_id"]
    now = time.time()
    st = str(ev.get("status") or "FAILED").upper()
    row = query_one("SELECT result_id, suite_id, case_name, module, severity FROM qa_test_results WHERE run_id=? AND case_id=?", (run_id, cid))
    if not row:
        return
    did = ""
    if st == "FAILED":
        enriched = {**row, **ev}
        did = _maybe_create_defect(run_id, enriched)

    write(
        "UPDATE qa_test_results SET status=?, attempt_num=?, finished_at=?, duration_ms=?, "
        "expected_result=COALESCE(NULLIF(?,''), expected_result), actual_result=?, error_message=?, "
        "stack_trace=?, api_response_sanitized=?, defect_id=? WHERE run_id=? AND case_id=?",
        (
            st,
            attempt_num,
            now,
            float(ev.get("duration_ms") or 0.0),
            sanitize_text(ev.get("expected_result", "")),
            sanitize_text(ev.get("actual_result", "")),
            sanitize_text(ev.get("error_message", "")),
            sanitize_text(ev.get("stack_trace", "")),
            sanitize_text(ev.get("api_response_sanitized", "")),
            did,
            run_id,
            cid,
        ),
    )
    lvl = "INFO" if st == "PASSED" else ("WARNING" if st in ("SKIPPED", "CANCELLED") else "ERROR")
    _log_run(run_id, lvl, row["suite_id"], f"[{st}] {cid} ({ev.get('duration_ms', 0)}ms) -> {ev.get('actual_result', '')}", result_id=row["result_id"])


def _execute_run_core(run_id: str) -> Dict[str, Any]:
    """Execute all queued cases for run_id across sandbox, Playwright, and Regression stages."""
    ensure_qa_ready()
    cfg = get_qa_config()
    cancel_ev = _CANCEL_FLAGS.setdefault(run_id, threading.Event())
    now = time.time()
    write("UPDATE qa_test_runs SET status='RUNNING', started_at=?, updated_at=? WHERE run_id=?", (now, now, run_id))
    _log_run(run_id, "INFO", "QA_RUNNER", f"Started test run {run_id} (env={cfg.get('environment')})")

    pending_rows = query(
        "SELECT r.result_id, r.suite_id, r.case_id, r.case_name, r.module, r.severity, c.expected_behavior "
        "FROM qa_test_results r LEFT JOIN qa_test_cases c ON c.case_id = r.case_id "
        "WHERE r.run_id=? ORDER BY r.created_at ASC",
        (run_id,),
    )

    sandbox_tasks: List[Dict[str, Any]] = []
    playwright_case_ids: List[str] = []
    regression_cases: List[Dict[str, Any]] = []

    for r in pending_rows:
        if r["suite_id"] == "FRONTEND":
            playwright_case_ids.append(r["case_id"])
        elif r["suite_id"] == "REGRESSION":
            regression_cases.append(dict(r))
        else:
            sandbox_tasks.append({
                "suite_id": r["suite_id"],
                "case_id": r["case_id"],
                "expected_behavior": r.get("expected_behavior") or "",
            })

    retry_max = max(0, min(int(float(cfg.get("retry_count") or 1)), 3))

    # 1. Execute isolated sandbox cases (AUTH, ADMIN_PANEL, BACKEND, API, DATABASE, TRADING_ENGINE, COINDCX, SECURITY, PERFORMANCE)
    if sandbox_tasks and not cancel_ev.is_set():
        outcomes = _execute_sandbox_subprocess(run_id, sandbox_tasks, cfg, cancel_ev)
        # Retry any failed cases automatically when retry_max > 0
        failed_retry_tasks = [t for t in sandbox_tasks if outcomes.get(t["case_id"], {}).get("status") == "FAILED"]
        attempt = 1
        while failed_retry_tasks and attempt <= retry_max and not cancel_ev.is_set():
            attempt += 1
            _log_run(run_id, "INFO", "QA_RETRY", f"Retrying {len(failed_retry_tasks)} failed sandbox case(s) (attempt {attempt})...")
            retry_outcomes = _execute_sandbox_subprocess(run_id, failed_retry_tasks, cfg, cancel_ev)
            for t in failed_retry_tasks:
                cid = t["case_id"]
                if cid in retry_outcomes:
                    _record_case_outcome(run_id, retry_outcomes[cid], attempt_num=attempt)
                    outcomes[cid] = retry_outcomes[cid]
            failed_retry_tasks = [t for t in failed_retry_tasks if outcomes.get(t["case_id"], {}).get("status") == "FAILED"]

    # 2. Execute Playwright Frontend cases (real headless browser against ephemeral isolated WSGI server)
    if playwright_case_ids and not cancel_ev.is_set():
        _log_run(run_id, "INFO", "PLAYWRIGHT", f"Launching Playwright ({cfg.get('browser', 'chromium')}) for {len(playwright_case_ids)} UI test(s)...")
        for cid in playwright_case_ids:
            write("UPDATE qa_test_results SET status='RUNNING', started_at=? WHERE run_id=? AND case_id=?", (time.time(), run_id, cid))
        pw_res = execute_playwright_suite(
            run_id,
            browser_name=str(cfg.get("browser") or "chromium"),
            capture_screenshots=str(cfg.get("capture_screenshots", "1")) == "1",
            capture_video=str(cfg.get("capture_video", "0")) == "1",
            capture_trace=str(cfg.get("capture_trace", "1")) == "1",
            case_filter=playwright_case_ids,
            timeout_sec=int(float(cfg.get("timeout_sec") or 90)),
        )
        for art in pw_res.get("artifacts", []):
            write(
                "INSERT INTO qa_test_artifacts(artifact_id, run_id, result_id, artifact_type, file_name, file_path, mime_type, size_bytes, created_by, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    art["artifact_id"], run_id, art.get("result_id", ""), art["artifact_type"],
                    art["file_name"], art["file_path"], art["mime_type"], int(art.get("size_bytes") or 0),
                    "PLAYWRIGHT", time.time(),
                ),
            )
        for item in pw_res.get("results", []):
            _record_case_outcome(run_id, item)

    # 3. Execute REGRESSION 7-Gate Suite if requested
    if regression_cases and not cancel_ev.is_set():
        gate_map = {
            "REG_01_BACKEND_SMOKE": [{"suite_id": "BACKEND", "case_id": "BE_01_APP_MODULE"}, {"suite_id": "BACKEND", "case_id": "BE_13_GAMMA_ORCHESTRATOR"}],
            "REG_02_DATABASE_INTEGRITY": [{"suite_id": "DATABASE", "case_id": "DB_02_SCHEMA_INTEGRITY"}, {"suite_id": "DATABASE", "case_id": "DB_07_MIGRATIONS_IDEMPOTENCY"}, {"suite_id": "DATABASE", "case_id": "DB_08_BACKUP_RESTORE_ROUNDTRIP"}],
            "REG_03_API_CONTRACTS": [{"suite_id": "API", "case_id": "API_01_ROUTE_DISCOVERY"}, {"suite_id": "API", "case_id": "API_02_SAFE_GET_CONTRACTS"}, {"suite_id": "API", "case_id": "API_03_AUTH_GATE_COVERAGE"}],
            "REG_04_FRONTEND_SMOKE": "PLAYWRIGHT_SMOKE",
            "REG_05_AUTH_RBAC_GATE": [{"suite_id": "AUTH", "case_id": "AUTH_01_ADMIN_LOGIN_VALID"}, {"suite_id": "AUTH", "case_id": "AUTH_10_ROLE_BASED_PERMISSIONS"}],
            "REG_06_TRADING_SIM_GATE": [{"suite_id": "TRADING_ENGINE", "case_id": "TE_05_OMS_LIFECYCLE_TP_SL"}, {"suite_id": "TRADING_ENGINE", "case_id": "TE_06_REJECTED_SIGNAL_NO_ORDER"}, {"suite_id": "TRADING_ENGINE", "case_id": "TE_08_DAILY_LOSS_CIRCUIT_BREAKER"}],
            "REG_07_COINDCX_SAFE_GATE": [{"suite_id": "COINDCX", "case_id": "CDX_01_CONFIG_AND_MAPPING"}, {"suite_id": "COINDCX", "case_id": "CDX_04_MOCK_POSITIONS_RECONCILE"}, {"suite_id": "COINDCX", "case_id": "CDX_08_REAL_MODE_SAFETY_LOCK"}],
        }
        all_sbx_subtasks: List[Dict[str, Any]] = []
        run_pw_smoke = False
        for rc in regression_cases:
            target = gate_map.get(rc["case_id"])
            if target == "PLAYWRIGHT_SMOKE":
                run_pw_smoke = True
            elif isinstance(target, list):
                all_sbx_subtasks.extend(target)

        # Execute batched regression sandbox checks cleanly in isolated temp DB
        sub_outcomes: Dict[str, Dict[str, Any]] = {}
        if all_sbx_subtasks and not cancel_ev.is_set():
            runner_script = str(BACKEND_DIR / "qa_suite_runners.py")
            proc = subprocess.run(
                [sys.executable, runner_script, "--sandbox"],
                cwd=str(BASE_DIR),
                input=json.dumps({"tasks": all_sbx_subtasks, "perf_cfg": {}, "cfg": cfg}),
                capture_output=True,
                text=True,
                timeout=max(20, int(float(cfg.get("timeout_sec") or 90))),
            )
            for ln in (proc.stdout or "").splitlines():
                try:
                    ev = json.loads(ln)
                    if ev.get("type") == "CASE_RESULT":
                        sub_outcomes[ev["case_id"]] = ev
                except Exception:
                    pass

        pw_smoke_res = None
        if run_pw_smoke and not cancel_ev.is_set():
            pw_smoke_res = execute_playwright_suite(
                run_id,
                browser_name=str(cfg.get("browser") or "chromium"),
                capture_screenshots=True,
                capture_video=False,
                capture_trace=False,
                case_filter=["FE_PW_01_ADMIN_LOGIN", "FE_PW_02_SIDEBAR_NAVIGATION", "FE_PW_08_CONSOLE_NETWORK_AUDIT"],
                timeout_sec=int(float(cfg.get("timeout_sec") or 90)),
            )
            for art in pw_smoke_res.get("artifacts", []):
                write(
                    "INSERT INTO qa_test_artifacts(artifact_id, run_id, result_id, artifact_type, file_name, file_path, mime_type, size_bytes, created_by, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        art["artifact_id"], run_id, art.get("result_id", ""), art["artifact_type"],
                        art["file_name"], art["file_path"], art["mime_type"], int(art.get("size_bytes") or 0),
                        "PLAYWRIGHT_REGRESSION", time.time(),
                    ),
                )

        for rc in regression_cases:
            if cancel_ev.is_set():
                break
            cid = rc["case_id"]
            write("UPDATE qa_test_results SET status='RUNNING', started_at=? WHERE run_id=? AND case_id=?", (time.time(), run_id, cid))
            target = gate_map.get(cid)
            t_gate0 = time.time()
            if target == "PLAYWRIGHT_SMOKE" and pw_smoke_res is not None:
                pw_items = pw_smoke_res.get("results", [])
                fails = [x for x in pw_items if x.get("status") != "PASSED"]
                _record_case_outcome(run_id, {
                    "case_id": cid,
                    "status": "PASSED" if (pw_items and not fails) else "FAILED",
                    "duration_ms": round(sum(float(x.get("duration_ms") or 0) for x in pw_items), 2),
                    "expected_result": rc.get("expected_behavior") or "",
                    "actual_result": f"Playwright regression smoke: {len(pw_items) - len(fails)}/{len(pw_items)} passed",
                    "error_message": fails[0].get("error_message", "") if fails else "",
                    "stack_trace": fails[0].get("stack_trace", "") if fails else "",
                    "screenshot_artifact_id": fails[0].get("screenshot_artifact_id", "") if fails else "",
                })
            elif isinstance(target, list):
                gate_checks = [sub_outcomes.get(t["case_id"]) for t in target]
                fails = [g for g in gate_checks if not g or g.get("status") != "PASSED"]
                _record_case_outcome(run_id, {
                    "case_id": cid,
                    "status": "PASSED" if not fails else "FAILED",
                    "duration_ms": round(sum(float((g or {}).get("duration_ms") or 0) for g in gate_checks) or ((time.time() - t_gate0) * 1000), 2),
                    "expected_result": rc.get("expected_behavior") or "",
                    "actual_result": f"Verified {len(target) - len(fails)}/{len(target)} regression checks (Real Mode untouched & locked)",
                    "error_message": (fails[0] or {}).get("error_message", "Check did not complete") if fails else "",
                    "stack_trace": (fails[0] or {}).get("stack_trace", "") if fails else "",
                })

    if cancel_ev.is_set():
        write(
            "UPDATE qa_test_results SET status='CANCELLED', finished_at=?, actual_result='Execution stopped by Admin' "
            "WHERE run_id=? AND status IN ('QUEUED','RUNNING')",
            (time.time(), run_id),
        )
        summary = _finalize_run_metrics(run_id, final_status_override="CANCELLED")
        _log_run(run_id, "WARNING", "QA_RUNNER", f"Run {run_id} cancelled cleanly.")
    else:
        # Mark any uncompleted rows as BLOCKED rather than leaving them hung in QUEUED
        write(
            "UPDATE qa_test_results SET status='BLOCKED', finished_at=?, error_message='Worker terminated before completion' "
            "WHERE run_id=? AND status IN ('QUEUED','RUNNING')",
            (time.time(), run_id),
        )
        summary = _finalize_run_metrics(run_id)
        _log_run(run_id, "INFO", "QA_RUNNER", f"Completed run {run_id}: {summary.get('status')} ({summary.get('pass_rate_pct')}% pass)")

    comp = compute_historical_comparison(run_id)
    write("UPDATE qa_test_runs SET summary_json=?, updated_at=? WHERE run_id=?", (json.dumps(comp, default=str), time.time(), run_id))
    _CANCEL_FLAGS.pop(run_id, None)
    return summary


def _worker_loop() -> None:
    while True:
        run_id = _RUN_QUEUE.get()
        try:
            row = query_one("SELECT status FROM qa_test_runs WHERE run_id=?", (run_id,))
            if not row or row["status"] == "CANCELLED":
                continue
            _execute_run_core(run_id)
        except Exception as exc:
            _log_run(run_id, "ERROR", "QA_WORKER", f"Fatal worker exception: {exc}\n{traceback.format_exc()}")
            try:
                _finalize_run_metrics(run_id, final_status_override="BLOCKED")
            except Exception:
                pass
        finally:
            _RUN_QUEUE.task_done()


def _ensure_worker_started() -> None:
    global _WORKER_THREAD, _SCHED_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(target=_worker_loop, daemon=True, name="araa-qa-worker")
            _WORKER_THREAD.start()
        if _SCHED_THREAD is None or not _SCHED_THREAD.is_alive():
            _SCHED_THREAD = threading.Thread(target=_schedule_loop, daemon=True, name="araa-qa-scheduler")
            _SCHED_THREAD.start()


def _schedule_loop() -> None:
    while True:
        time.sleep(30)
        try:
            check_due_schedules()
        except Exception:
            pass


def check_due_schedules() -> Optional[Dict[str, Any]]:
    """Evaluate enabled scheduled regression jobs cleanly."""
    ensure_qa_ready()
    now = time.time()
    due = query("SELECT * FROM qa_test_schedules WHERE is_enabled=1 AND (next_run_at IS NULL OR next_run_at <= ?)", (now,))
    triggered = None
    for s in due:
        try:
            suite_ids = json.loads(s.get("suite_ids_json") or '["REGRESSION"]')
        except Exception:
            suite_ids = ["REGRESSION"]
        res = enqueue_run(trigger_type="SCHEDULED", suite_ids=suite_ids, triggered_by=f"SCHEDULER:{s['schedule_id']}")
        iv = max(5, int(s.get("interval_minutes") or 60))
        write(
            "UPDATE qa_test_schedules SET last_run_id=?, last_run_at=?, next_run_at=?, updated_at=? WHERE schedule_id=?",
            (res.get("run_id") or s.get("last_run_id") or "", now, now + iv * 60, now, s["schedule_id"]),
        )
        triggered = res
    return triggered


def _prepare_run_records(
    *,
    trigger_type: str = "MANUAL",
    suite_ids: Optional[List[str]] = None,
    case_ids: Optional[List[str]] = None,
    triggered_by: str = "admin",
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve enabled target cases, check duplicate guard, and insert QUEUED run records."""
    ensure_qa_ready()
    cfg = get_qa_config()
    trig = str(trigger_type or "MANUAL").upper()

    # Respect admin feature toggles when running ALL
    disabled_auto_suites = set()
    if trig in ("ALL", "MANUAL") and not suite_ids and not case_ids:
        if str(cfg.get("api_testing_enabled", "1")) != "1":
            disabled_auto_suites.add("API")
        if str(cfg.get("security_testing_enabled", "1")) != "1":
            disabled_auto_suites.add("SECURITY")
        if str(cfg.get("performance_testing_enabled", "1")) != "1":
            disabled_auto_suites.add("PERFORMANCE")

    target_suites = sorted(set(str(x).upper() for x in (suite_ids or [])))
    target_cases = sorted(set(str(x) for x in (case_ids or [])))

    # FAILED_ONLY reruns cases that failed/blocked in most recent run
    if trig == "FAILED_ONLY" and not target_cases:
        latest = query_one("SELECT run_id FROM qa_test_runs ORDER BY created_at DESC LIMIT 1")
        if latest:
            failed_rows = query(
                "SELECT case_id FROM qa_test_results WHERE run_id=? AND status IN ('FAILED','BLOCKED')",
                (latest["run_id"],),
            )
            target_cases = sorted({r["case_id"] for r in failed_rows})
        if not target_cases:
            return None, {"success": False, "error": "No failed or blocked test cases found in latest test run."}

    # Duplicate active execution prevention
    sig = json.dumps({"trigger": trig, "suites": target_suites, "cases": target_cases}, sort_keys=True)
    active = query("SELECT run_id, suite_filter_json, case_filter_json, trigger_type FROM qa_test_runs WHERE status IN ('QUEUED','RUNNING')")
    for a in active:
        a_sig = json.dumps({
            "trigger": str(a.get("trigger_type") or ""),
            "suites": sorted(json.loads(a.get("suite_filter_json") or "[]")),
            "cases": sorted(json.loads(a.get("case_filter_json") or "[]")),
        }, sort_keys=True)
        if a_sig == sig:
            return None, {
                "success": False,
                "duplicate_blocked": True,
                "active_run_id": a["run_id"],
                "error": f"Duplicate test execution prevented: Run {a['run_id']} with the same scope is already active.",
            }

    all_cases = query(
        "SELECT c.*, s.module_path AS suite_mod, s.is_enabled AS suite_enabled "
        "FROM qa_test_cases c JOIN qa_test_suites s ON s.suite_id = c.suite_id "
        "ORDER BY s.sort_order ASC, c.case_id ASC"
    )
    selected_rows = []
    for c in all_cases:
        sid = str(c["suite_id"])
        cid = str(c["case_id"])
        if target_cases:
            if cid in target_cases:
                selected_rows.append(c)
        elif target_suites:
            if sid in target_suites and c.get("is_enabled", 1):
                selected_rows.append(c)
        else:
            # Run All skips REGRESSION meta-suite (already covers those gates cleanly) and disabled suites
            if sid != "REGRESSION" and sid not in disabled_auto_suites and c.get("suite_enabled", 1) and c.get("is_enabled", 1):
                selected_rows.append(c)

    if not selected_rows:
        return None, {"success": False, "error": "No enabled test cases matched your selection."}

    now = time.time()
    run_id = f"RUN-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(now))}-{secrets.token_hex(3).upper()}"
    env_name = str(cfg.get("environment") or "ISOLATED_STAGING")
    write(
        "INSERT INTO qa_test_runs(run_id, trigger_type, environment, status, suite_filter_json, case_filter_json, "
        "total_cases, pending_cases, triggered_by, created_at, updated_at) "
        "VALUES(?,?,?,'QUEUED',?,?,?, ?, ?,?,?)",
        (
            run_id, trig, env_name,
            json.dumps(target_suites), json.dumps(target_cases),
            len(selected_rows), len(selected_rows), sanitize_text(triggered_by), now, now,
        ),
    )

    for idx, c in enumerate(selected_rows):
        res_id = f"RES-{secrets.token_hex(6).upper()}"
        write(
            "INSERT INTO qa_test_results(result_id, run_id, suite_id, case_id, case_name, module, environment, "
            "status, severity, expected_result, created_at) VALUES(?,?,?,?,?,?,?,'QUEUED',?,?,?)",
            (
                res_id, run_id, c["suite_id"], c["case_id"], c["name"],
                c.get("suite_mod") or c.get("target_ref") or c["suite_id"],
                env_name, c.get("severity") or "High", c.get("expected_behavior") or "", now + idx * 0.0001,
            ),
        )
    _log_run(run_id, "INFO", "QA_QUEUE", f"Queued {len(selected_rows)} test case(s) for trigger={trig}")
    return run_id, None


def enqueue_run(
    *,
    trigger_type: str = "MANUAL",
    suite_ids: Optional[List[str]] = None,
    case_ids: Optional[List[str]] = None,
    triggered_by: str = "admin",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Queue asynchronous background test execution cleanly."""
    if overrides:
        update_qa_config(overrides, actor=triggered_by)
    run_id, err = _prepare_run_records(
        trigger_type=trigger_type, suite_ids=suite_ids, case_ids=case_ids, triggered_by=triggered_by
    )
    if err:
        return err
    _ensure_worker_started()
    _RUN_QUEUE.put(run_id)  # type: ignore[arg-type]
    return {"success": True, "run_id": run_id, "status": "QUEUED", "queued": True}


def run_sync(
    *,
    trigger_type: str = "SYNC",
    suite_ids: Optional[List[str]] = None,
    case_ids: Optional[List[str]] = None,
    triggered_by: str = "admin",
) -> Dict[str, Any]:
    """Execute selected suites/cases synchronously in isolated sandboxes and persist results."""
    run_id, err = _prepare_run_records(
        trigger_type=trigger_type, suite_ids=suite_ids, case_ids=case_ids, triggered_by=triggered_by
    )
    if err:
        return err
    summary = _execute_run_core(run_id)  # type: ignore[arg-type]
    results = query("SELECT * FROM qa_test_results WHERE run_id=? ORDER BY created_at ASC", (run_id,))
    return {"success": summary.get("status") == "PASSED", "run_id": run_id, "summary": summary, "results": [dict(r) for r in results]}


def stop_run(run_id: str, actor: str = "admin") -> Dict[str, Any]:
    ensure_qa_ready()
    row = query_one("SELECT status FROM qa_test_runs WHERE run_id=?", (run_id,))
    if not row:
        return {"success": False, "error": "Test run not found"}
    if row["status"] not in ("QUEUED", "RUNNING"):
        return {"success": False, "error": f"Run is already finalized ({row['status']})"}
    ev = _CANCEL_FLAGS.setdefault(run_id, threading.Event())
    ev.set()
    proc = _ACTIVE_PROCS.get(run_id)
    if proc and proc.poll() is None:
        proc.terminate()
    write("UPDATE qa_test_runs SET status='CANCELLED', updated_at=? WHERE run_id=? AND status='QUEUED'", (time.time(), run_id))
    write("UPDATE qa_test_results SET status='CANCELLED', finished_at=?, actual_result='Stopped by Admin' WHERE run_id=? AND status='QUEUED'", (time.time(), run_id))
    _log_run(run_id, "WARNING", "QA_CONTROL", f"Stop requested by {sanitize_text(actor)}")
    return {"success": True, "run_id": run_id, "status": "CANCELLED"}


def update_defect(defect_id: str, patch_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update defect triage fields while strictly enforcing retest before Verified/Closed."""
    ensure_qa_ready()
    row = query_one("SELECT * FROM qa_defects WHERE defect_id=?", (defect_id,))
    if not row:
        return {"success": False, "error": "Defect not found"}

    new_status = str(patch_data.get("status") or row["status"])
    if new_status not in _VALID_DEFECT_STATUSES:
        return {"success": False, "error": f"Invalid defect status: {new_status}"}
    if new_status in ("Verified", "Closed") and not int(row.get("retest_passed") or 0):
        return {
            "success": False,
            "error": "Retest Gate Enforced: Cannot mark defect Verified or Closed without a passing retest.",
        }

    new_sev = str(patch_data.get("severity") or row["severity"])
    if new_sev not in _VALID_SEVERITIES:
        new_sev = row["severity"]

    now = time.time()
    resolved_at = now if new_status in ("Verified", "Closed") else row.get("resolved_at")
    write(
        "UPDATE qa_defects SET title=?, description=?, severity=?, priority=?, status=?, "
        "assigned_admin=?, root_cause=?, resolution_notes=?, resolved_at=?, updated_at=? WHERE defect_id=?",
        (
            sanitize_text(patch_data.get("title") or row["title"]),
            sanitize_text(patch_data.get("description") or row["description"]),
            new_sev,
            sanitize_text(patch_data.get("priority") or row["priority"]),
            new_status,
            sanitize_text(patch_data.get("assigned_admin") or row["assigned_admin"]),
            sanitize_text(patch_data.get("root_cause") if "root_cause" in patch_data else row["root_cause"]),
            sanitize_text(patch_data.get("resolution_notes") if "resolution_notes" in patch_data else row["resolution_notes"]),
            resolved_at,
            now,
            defect_id,
        ),
    )
    return {"success": True, "defect": dict(query_one("SELECT * FROM qa_defects WHERE defect_id=?", (defect_id,)) or {})}


def retest_defect(defect_id: str, triggered_by: str = "admin") -> Dict[str, Any]:
    """Re-execute the defect's linked test case in isolation before permitting resolution."""
    ensure_qa_ready()
    d = query_one("SELECT * FROM qa_defects WHERE defect_id=?", (defect_id,))
    if not d:
        return {"success": False, "error": "Defect not found"}
    cid = str(d.get("case_id") or "")
    if not cid:
        return {"success": False, "error": "Defect is not mapped to an executable automated test case ID."}

    write("UPDATE qa_defects SET status='Retesting', updated_at=? WHERE defect_id=?", (time.time(), defect_id))
    res = run_sync(trigger_type="DEFECT_RETEST", case_ids=[cid], triggered_by=triggered_by)
    case_items = res.get("results") or []
    passed = bool(case_items and case_items[0].get("status") == "PASSED")
    now = time.time()
    new_status = "Verified" if passed else "Open"
    write(
        "UPDATE qa_defects SET status=?, retest_run_id=?, retest_passed=?, resolved_at=?, updated_at=? WHERE defect_id=?",
        (new_status, res.get("run_id") or "", 1 if passed else 0, now if passed else None, now, defect_id),
    )
    return {
        "success": True,
        "retest_passed": passed,
        "retest_run_id": res.get("run_id"),
        "defect": dict(query_one("SELECT * FROM qa_defects WHERE defect_id=?", (defect_id,)) or {}),
    }


def compute_real_component_health() -> Dict[str, Any]:
    """
    Compute live component health exclusively from actual DB probes, Flask/Feed telemetry,
    and persisted QA test results. Never fabricates fake health or hardcoded pass scores.
    """
    ensure_qa_ready()

    # 1. Database runtime probe
    db_ok = False
    db_lat_ms = 0.0
    table_cnt = 0
    try:
        t0 = time.time()
        conn = connect()
        try:
            conn.execute("SELECT 1").fetchone()
            table_cnt = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            db_lat_ms = round((time.time() - t0) * 1000.0, 2)
            db_ok = True
        finally:
            conn.close()
    except Exception:
        db_ok = False

    # 2. Latest suite test results from DB (NOT_TESTED until an actual test run executes)
    suite_latest: Dict[str, Dict[str, Any]] = {}
    for s in SUITE_CATALOG:
        sid = s["suite_id"]
        row = query_one(
            "SELECT r.run_id, r.status, r.created_at FROM qa_test_results r "
            "WHERE r.suite_id=? ORDER BY r.created_at DESC LIMIT 1",
            (sid,),
        )
        run_cnt_row = query_one(
            "SELECT COUNT(*) c, SUM(CASE WHEN status='PASSED' THEN 1 ELSE 0 END) p, "
            "SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) f "
            "FROM qa_test_results WHERE run_id=(SELECT run_id FROM qa_test_results WHERE suite_id=? ORDER BY created_at DESC LIMIT 1) "
            "AND suite_id=?",
            (sid, sid),
        ) if row else None
        if row and run_cnt_row and run_cnt_row["c"]:
            f_n = int(run_cnt_row["f"] or 0)
            p_n = int(run_cnt_row["p"] or 0)
            suite_latest[sid] = {
                "status": "FAILED" if f_n > 0 else ("PASSED" if p_n > 0 else str(row["status"])),
                "passed": p_n,
                "failed": f_n,
                "total": int(run_cnt_row["c"] or 0),
                "last_run_id": row["run_id"],
                "last_at": row["created_at"],
            }
        else:
            suite_latest[sid] = {"status": "NOT_TESTED", "passed": 0, "failed": 0, "total": 0, "last_run_id": "", "last_at": None}

    # 3. Real feed / broker / engine runtime counts
    active_bots = int((query_one("SELECT COUNT(*) c FROM users WHERE bot_enabled=1") or {}).get("c") or 0)
    open_pos = int((query_one("SELECT COUNT(*) c FROM positions WHERE status IN ('OPEN','PENDING_BROKER')") or {}).get("c") or 0)
    cdx_connected = int((query_one("SELECT COUNT(*) c FROM broker_connections WHERE broker_name='COINDCX' AND status='CONNECTED'") or {}).get("c") or 0)
    cdx_live = int((query_one("SELECT COUNT(*) c FROM broker_connections WHERE broker_name='COINDCX' AND is_live_active=1") or {}).get("c") or 0)

    def _combine(runtime_ok: bool, suite_key: str, ok_label: str = "HEALTHY") -> str:
        if not runtime_ok:
            return "UNHEALTHY"
        st = suite_latest.get(suite_key, {}).get("status", "NOT_TESTED")
        if st == "FAILED":
            return "DEGRADED"
        if st == "PASSED":
            return ok_label
        return f"{ok_label} (UNVERIFIED)"

    return {
        "api_health": {"status": _combine(True, "API"), "suite": suite_latest["API"]},
        "backend_health": {"status": _combine(True, "BACKEND"), "suite": suite_latest["BACKEND"]},
        "database_health": {
            "status": _combine(db_ok, "DATABASE"),
            "latency_ms": db_lat_ms,
            "tables": table_cnt,
            "suite": suite_latest["DATABASE"],
        },
        "frontend_health": {"status": suite_latest["FRONTEND"]["status"], "suite": suite_latest["FRONTEND"]},
        "trading_engine_health": {
            "status": _combine(db_ok, "TRADING_ENGINE"),
            "active_bots": active_bots,
            "open_positions": open_pos,
            "suite": suite_latest["TRADING_ENGINE"],
        },
        "coindcx_connectivity": {
            "status": _combine(True, "COINDCX", ok_label="CONFIGURED" if cdx_connected == 0 else "CONNECTED"),
            "connected_accounts": cdx_connected,
            "live_active_accounts": cdx_live,
            "suite": suite_latest["COINDCX"],
        },
        "suite_statuses": suite_latest,
    }


def get_qa_dashboard_data() -> Dict[str, Any]:
    """Return real Testing & Quality Center dashboard metrics + historical deltas."""
    ensure_qa_ready()
    latest_run = query_one("SELECT * FROM qa_test_runs ORDER BY created_at DESC LIMIT 1")
    last_reg = query_one("SELECT * FROM qa_test_runs WHERE trigger_type IN ('REGRESSION','DEPLOYMENT','SCHEDULED') OR suite_filter_json LIKE '%REGRESSION%' ORDER BY created_at DESC LIMIT 1")
    last_sec = query_one(
        "SELECT r.run_id, r.status, r.created_at, r.duration_ms FROM qa_test_runs r "
        "WHERE r.run_id IN (SELECT DISTINCT run_id FROM qa_test_results WHERE suite_id='SECURITY') ORDER BY r.created_at DESC LIMIT 1"
    )
    active_runs = query("SELECT run_id, trigger_type, status, total_cases, passed_cases, failed_cases, started_at, created_at FROM qa_test_runs WHERE status IN ('QUEUED','RUNNING') ORDER BY created_at DESC")

    crit_defects = int((query_one("SELECT COUNT(*) c FROM qa_defects WHERE severity='Critical' AND status NOT IN ('Verified','Closed')") or {}).get("c") or 0)
    high_defects = int((query_one("SELECT COUNT(*) c FROM qa_defects WHERE severity='High' AND status NOT IN ('Verified','Closed')") or {}).get("c") or 0)
    open_defects = int((query_one("SELECT COUNT(*) c FROM qa_defects WHERE status NOT IN ('Verified','Closed')") or {}).get("c") or 0)

    total_registered_cases = int((query_one("SELECT COUNT(*) c FROM qa_test_cases") or {}).get("c") or 0)
    health = compute_real_component_health()
    recent_runs = query("SELECT * FROM qa_test_runs ORDER BY created_at DESC LIMIT 15")
    comparison = compute_historical_comparison(latest_run["run_id"]) if latest_run else {}

    lr = dict(latest_run) if latest_run else {}
    return {
        "metrics": {
            "total_test_cases": int(lr.get("total_cases") or 0),
            "registered_test_cases": total_registered_cases,
            "passed_tests": int(lr.get("passed_cases") or 0),
            "failed_tests": int(lr.get("failed_cases") or 0),
            "blocked_tests": int(lr.get("blocked_cases") or 0),
            "skipped_tests": int(lr.get("skipped_cases") or 0),
            "pending_tests": int(lr.get("pending_cases") or 0),
            "pass_percentage": float(lr.get("pass_rate_pct") or 0.0),
            "critical_defects": crit_defects,
            "high_severity_defects": high_defects,
            "open_defects": open_defects,
        },
        "health": health,
        "latest_run": lr or None,
        "latest_execution_duration_ms": float(lr.get("duration_ms") or 0.0),
        "last_regression_test": dict(last_reg) if last_reg else None,
        "last_security_test": dict(last_sec) if last_sec else None,
        "active_runs": [dict(a) for a in active_runs],
        "recent_runs": [dict(r) for r in recent_runs],
        "historical_comparison": comparison,
        "deployment_readiness": lr.get("deployment_readiness") or ("READY_FOR_DEPLOYMENT" if (last_reg and last_reg.get("status") == "PASSED" and crit_defects == 0) else "UNVERIFIED"),
    }


def list_discovered_api_endpoints(app_obj) -> List[Dict[str, Any]]:
    """Inspect Flask api.url_map safely for the API Testing submenu."""
    unsafe_keywords = ("withdraw", "deposit", "close", "wipe", "delete", "trade", "orders", "sell", "buy", "reset", "approve")
    endpoints = []
    for rule in sorted(app_obj.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/"):
            continue
        methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
        auth_scope = "ADMIN" if rule.rule.startswith(("/api/admin/", "/api/v3/admin/", "/api/central-admin/")) else (
            "COMPANY" if "/company/" in rule.rule else "PUBLIC_OR_USER"
        )
        is_financial = any(k in rule.rule for k in unsafe_keywords)
        endpoints.append({
            "path": rule.rule,
            "endpoint": rule.endpoint,
            "methods": methods,
            "auth_scope": auth_scope,
            "safety_class": "PROTECTED_FINANCIAL" if is_financial else "SAFE_PROBE",
        })
    return endpoints
