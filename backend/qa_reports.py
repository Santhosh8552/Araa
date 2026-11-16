"""
AraaBot Enterprise QA Reporting Engine.
Generates sanitized Excel (.xlsx), PDF (.pdf), HTML (.html), JSON (.json), and Log (.log)
reports with historical trend comparisons, failure diagnostics, and defect references.
"""

from __future__ import annotations

import html
import io
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from database import query, query_one, write
except ImportError:
    from backend.database import query, query_one, write

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"


def _fmt_ts(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(float(ts)))
    except Exception:
        return "—"


def compute_historical_comparison(run_id: str) -> Dict[str, Any]:
    """Compare current run against previous run and compute pass%/duration trends."""
    current = query_one("SELECT * FROM qa_test_runs WHERE run_id=?", (run_id,))
    if not current:
        return {}

    prev = query_one(
        "SELECT * FROM qa_test_runs WHERE created_at < ? AND status IN ('PASSED','FAILED','BLOCKED','CANCELLED') "
        "ORDER BY created_at DESC LIMIT 1",
        (float(current.get("created_at") or time.time()),),
    )

    cur_results = query("SELECT case_id, case_name, suite_id, status FROM qa_test_results WHERE run_id=?", (run_id,))
    cur_map = {r["case_id"]: r for r in cur_results}

    prev_map: Dict[str, Dict[str, Any]] = {}
    if prev:
        prev_results = query("SELECT case_id, case_name, suite_id, status FROM qa_test_results WHERE run_id=?", (prev["run_id"],))
        prev_map = {r["case_id"]: r for r in prev_results}

    newly_failed: List[Dict[str, str]] = []
    regression_defects: List[Dict[str, str]] = []
    fixed_tests: List[Dict[str, str]] = []

    for cid, cr in cur_map.items():
        pr = prev_map.get(cid)
        cst = str(cr.get("status") or "").upper()
        pst = str(pr.get("status") or "").upper() if pr else ""
        if cst == "FAILED":
            if pst == "PASSED":
                regression_defects.append({"case_id": cid, "case_name": cr.get("case_name", cid), "suite_id": cr.get("suite_id", "")})
            elif not pst or pst != "FAILED":
                newly_failed.append({"case_id": cid, "case_name": cr.get("case_name", cid), "suite_id": cr.get("suite_id", "")})
        elif cst == "PASSED" and pst == "FAILED":
            fixed_tests.append({"case_id": cid, "case_name": cr.get("case_name", cid), "suite_id": cr.get("suite_id", "")})

    # Fixed defects marked Verified/Closed since previous run window
    prev_ts = float(prev.get("created_at") or 0.0) if prev else 0.0
    fixed_defect_rows = query(
        "SELECT defect_id, title, module, status FROM qa_defects WHERE status IN ('Verified','Closed') AND updated_at >= ?",
        (prev_ts,),
    ) if prev else []

    trend_runs = query(
        "SELECT run_id, trigger_type, status, pass_rate_pct, duration_ms, created_at "
        "FROM qa_test_runs ORDER BY created_at DESC LIMIT 12"
    )
    trend_runs = list(reversed(trend_runs))

    return {
        "current_run": {
            "run_id": current["run_id"],
            "status": current["status"],
            "pass_rate_pct": float(current.get("pass_rate_pct") or 0.0),
            "duration_ms": float(current.get("duration_ms") or 0.0),
            "created_at": _fmt_ts(current.get("created_at")),
        },
        "previous_run": {
            "run_id": prev["run_id"],
            "status": prev["status"],
            "pass_rate_pct": float(prev.get("pass_rate_pct") or 0.0),
            "duration_ms": float(prev.get("duration_ms") or 0.0),
            "created_at": _fmt_ts(prev.get("created_at")),
        } if prev else None,
        "pass_rate_delta_pct": round(
            float(current.get("pass_rate_pct") or 0.0) - float(prev.get("pass_rate_pct") or 0.0), 2
        ) if prev else 0.0,
        "duration_delta_ms": round(
            float(current.get("duration_ms") or 0.0) - float(prev.get("duration_ms") or 0.0), 2
        ) if prev else 0.0,
        "newly_failed_tests": newly_failed,
        "regression_defects": regression_defects,
        "fixed_tests": fixed_tests,
        "fixed_defects": [dict(d) for d in fixed_defect_rows],
        "pass_percentage_trend": [
            {"run_id": r["run_id"], "pass_rate_pct": float(r.get("pass_rate_pct") or 0.0), "created_at": _fmt_ts(r.get("created_at"))}
            for r in trend_runs
        ],
        "execution_duration_trend": [
            {"run_id": r["run_id"], "duration_ms": float(r.get("duration_ms") or 0.0), "created_at": _fmt_ts(r.get("created_at"))}
            for r in trend_runs
        ],
    }


def build_run_report_bundle(run_id: str) -> Optional[Dict[str, Any]]:
    """Assemble full sanitized report bundle for a given run_id."""
    run_row = query_one("SELECT * FROM qa_test_runs WHERE run_id=?", (run_id,))
    if not run_row:
        return None

    results = query(
        "SELECT r.*, s.name AS suite_name, s.category AS suite_category "
        "FROM qa_test_results r LEFT JOIN qa_test_suites s ON s.suite_id = r.suite_id "
        "WHERE r.run_id=? ORDER BY r.created_at ASC, r.case_id ASC",
        (run_id,),
    )
    artifacts = query("SELECT * FROM qa_test_artifacts WHERE run_id=? ORDER BY created_at ASC", (run_id,))
    logs = query("SELECT * FROM qa_test_logs WHERE run_id=? ORDER BY log_id ASC LIMIT 1000", (run_id,))
    defects = query(
        "SELECT * FROM qa_defects WHERE run_id=? OR defect_id IN (SELECT defect_id FROM qa_test_results WHERE run_id=? AND defect_id != '')",
        (run_id, run_id),
    )

    art_by_result: Dict[str, List[Dict[str, Any]]] = {}
    for a in artifacts:
        rid = str(a.get("result_id") or "")
        art_by_result.setdefault(rid, []).append(dict(a))

    enriched_results = []
    for r in results:
        d = dict(r)
        cid = str(d.get("case_id") or "")
        rid = str(d.get("result_id") or "")
        linked_arts = art_by_result.get(cid, []) + art_by_result.get(rid, [])
        d["screenshots"] = [a for a in linked_arts if a.get("artifact_type") == "SCREENSHOT"]
        d["screenshot_ref"] = d["screenshots"][0]["file_path"] if d["screenshots"] else ""
        d["start_time_iso"] = _fmt_ts(d.get("started_at"))
        d["end_time_iso"] = _fmt_ts(d.get("finished_at"))
        enriched_results.append(d)

    comparison = compute_historical_comparison(run_id)
    run_dict = dict(run_row)
    run_dict["start_time_iso"] = _fmt_ts(run_dict.get("started_at"))
    run_dict["end_time_iso"] = _fmt_ts(run_dict.get("finished_at"))

    return {
        "generated_at": _fmt_ts(time.time()),
        "run": run_dict,
        "results": enriched_results,
        "defects": [dict(d) for d in defects],
        "artifacts": [dict(a) for a in artifacts],
        "logs": [dict(l) for l in logs],
        "historical_comparison": comparison,
    }


def _save_report_artifact(run_id: str, atype: str, fpath: Path, mime: str) -> None:
    try:
        write(
            "INSERT INTO qa_test_artifacts(artifact_id, run_id, result_id, artifact_type, file_name, file_path, mime_type, size_bytes, created_by, created_at) "
            "VALUES(?, ?, '', ?, ?, ?, ?, ?, 'QA_REPORTER', ?)",
            (
                f"ART-{secrets.token_hex(6).upper()}",
                run_id,
                atype,
                fpath.name,
                str(fpath.relative_to(BASE_DIR)),
                mime,
                fpath.stat().st_size,
                time.time(),
            ),
        )
    except Exception:
        pass


def generate_json_report(run_id: str) -> Optional[Tuple[bytes, str, str]]:
    bundle = build_run_report_bundle(run_id)
    if not bundle:
        return None
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"qa_report_{run_id}.json"
    fpath = REPORTS_DIR / fname
    raw = json.dumps(bundle, indent=2, default=str).encode("utf-8")
    fpath.write_bytes(raw)
    _save_report_artifact(run_id, "JSON", fpath, "application/json")
    return raw, "application/json", fname


def generate_logs_report(run_id: str) -> Optional[Tuple[bytes, str, str]]:
    run_row = query_one("SELECT run_id, status, environment, started_at, finished_at FROM qa_test_runs WHERE run_id=?", (run_id,))
    if not run_row:
        return None
    logs = query("SELECT * FROM qa_test_logs WHERE run_id=? ORDER BY log_id ASC", (run_id,))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"qa_logs_{run_id}.log"
    fpath = REPORTS_DIR / fname
    lines = [
        f"=== AraaBot Enterprise QA Execution Log: {run_id} ===",
        f"Status: {run_row['status']} | Env: {run_row['environment']} | Started: {_fmt_ts(run_row.get('started_at'))} | Finished: {_fmt_ts(run_row.get('finished_at'))}",
        "-" * 88,
    ]
    for l in logs:
        lines.append(f"[{_fmt_ts(l.get('logged_at'))}] [{l.get('level','INFO')}] [{l.get('source','QA')}] {l.get('message','')}")
    raw = "\n".join(lines).encode("utf-8")
    fpath.write_bytes(raw)
    _save_report_artifact(run_id, "LOG", fpath, "text/plain; charset=utf-8")
    return raw, "text/plain; charset=utf-8", fname


def generate_html_report(run_id: str) -> Optional[Tuple[bytes, str, str]]:
    bundle = build_run_report_bundle(run_id)
    if not bundle:
        return None
    r = bundle["run"]
    comp = bundle["historical_comparison"]
    rows_html = []
    for item in bundle["results"]:
        st = str(item.get("status") or "")
        clr = "#22c55e" if st == "PASSED" else ("#ef4444" if st == "FAILED" else ("#f59e0b" if st in ("BLOCKED", "SKIPPED") else "#94a3b8"))
        err_block = ""
        if item.get("error_message") or item.get("stack_trace"):
            err_block = (
                f"<details><summary style='color:#fca5a5;cursor:pointer;'>Diagnostics</summary>"
                f"<pre style='white-space:pre-wrap;font-size:11px;color:#fecaca;'>{html.escape(str(item.get('error_message') or ''))}\n"
                f"{html.escape(str(item.get('stack_trace') or '')[:1200])}</pre>"
                f"<pre style='white-space:pre-wrap;font-size:10px;color:#93c5fd;'>API: {html.escape(str(item.get('api_response_sanitized') or '')[:600])}</pre></details>"
            )
        rows_html.append(
            f"<tr>"
            f"<td><b>{html.escape(str(item.get('suite_id')))}</b><br><small>{html.escape(str(item.get('module')))}</small></td>"
            f"<td><b>{html.escape(str(item.get('case_id')))}</b><br><small>{html.escape(str(item.get('case_name')))}</small></td>"
            f"<td><span style='color:{clr};font-weight:800;'>{html.escape(st)}</span></td>"
            f"<td>{html.escape(str(item.get('severity') or 'High'))}</td>"
            f"<td>{item.get('duration_ms', 0)} ms</td>"
            f"<td><b>Exp:</b> {html.escape(str(item.get('expected_result') or ''))}<br><b>Act:</b> {html.escape(str(item.get('actual_result') or ''))}{err_block}</td>"
            f"<td>{html.escape(str(item.get('defect_id') or '—'))}<br><small>{html.escape(str(item.get('screenshot_ref') or ''))}</small></td>"
            f"</tr>"
        )

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AraaBot QA Report {html.escape(run_id)}</title>
<style>
body{{background:#0b0f14;color:#f4f7fa;font-family:Inter,system-ui,sans-serif;margin:24px;}}
.hdr{{background:#151d28;border:1px solid #263241;border-radius:12px;padding:18px;margin-bottom:18px;}}
.grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px;}}
.kpi{{background:#111821;border:1px solid #263241;border-radius:10px;padding:12px;}}
.kpi b{{font-size:20px;display:block;margin-top:4px;}}
table{{width:100%;border-collapse:collapse;background:#111821;border:1px solid #263241;font-size:12px;}}
th,td{{padding:9px 10px;border-bottom:1px solid #1e293b;text-align:left;vertical-align:top;}}
th{{background:#151d28;color:#94a3b8;text-transform:uppercase;font-size:11px;}}
</style></head><body>
<div class="hdr">
  <h2 style="margin:0 0 6px 0;">AraaBot Enterprise QA Report — {html.escape(run_id)}</h2>
  <div>Trigger: <b>{html.escape(str(r.get('trigger_type')))}</b> · Env: <b>{html.escape(str(r.get('environment')))}</b> · Status: <b>{html.escape(str(r.get('status')))}</b> · Readiness: <b>{html.escape(str(r.get('deployment_readiness')))}</b></div>
  <div style="color:#94a3b8;font-size:12px;margin-top:4px;">Start: {html.escape(r['start_time_iso'])} · End: {html.escape(r['end_time_iso'])} · Duration: {r.get('duration_ms',0)} ms · Historical Pass Delta: {comp.get('pass_rate_delta_pct',0):+.2f}%</div>
</div>
<div class="grid">
  <div class="kpi"><small>TOTAL</small><b>{r.get('total_cases',0)}</b></div>
  <div class="kpi"><small>PASSED</small><b style="color:#22c55e;">{r.get('passed_cases',0)}</b></div>
  <div class="kpi"><small>FAILED</small><b style="color:#ef4444;">{r.get('failed_cases',0)}</b></div>
  <div class="kpi"><small>BLOCKED</small><b style="color:#f59e0b;">{r.get('blocked_cases',0)}</b></div>
  <div class="kpi"><small>SKIPPED</small><b style="color:#94a3b8;">{r.get('skipped_cases',0)}</b></div>
  <div class="kpi"><small>PASS %</small><b style="color:#38bdf8;">{r.get('pass_rate_pct',0)}%</b></div>
</div>
<table><thead><tr><th>Suite / Module</th><th>Test Case</th><th>Status</th><th>Severity</th><th>Duration</th><th>Expected / Actual &amp; Trace</th><th>Defect / Screenshot</th></tr></thead>
<tbody>{''.join(rows_html)}</tbody></table>
</body></html>"""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"qa_report_{run_id}.html"
    fpath = REPORTS_DIR / fname
    raw = doc.encode("utf-8")
    fpath.write_bytes(raw)
    _save_report_artifact(run_id, "HTML", fpath, "text/html; charset=utf-8")
    return raw, "text/html; charset=utf-8", fname


def generate_excel_report(run_id: str) -> Optional[Tuple[bytes, str, str]]:
    bundle = build_run_report_bundle(run_id)
    if not bundle:
        return None
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Executive Summary"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="0F172A")

    r = bundle["run"]
    comp = bundle["historical_comparison"]
    summary_rows = [
        ("Test Run ID", r.get("run_id")),
        ("Environment", r.get("environment")),
        ("Trigger Type", r.get("trigger_type")),
        ("Status", r.get("status")),
        ("Deployment Readiness", r.get("deployment_readiness")),
        ("Start Time", r.get("start_time_iso")),
        ("End Time", r.get("end_time_iso")),
        ("Duration (ms)", r.get("duration_ms")),
        ("Total Test Cases", r.get("total_cases")),
        ("Passed", r.get("passed_cases")),
        ("Failed", r.get("failed_cases")),
        ("Blocked", r.get("blocked_cases")),
        ("Skipped", r.get("skipped_cases")),
        ("Pending", r.get("pending_cases")),
        ("Pass Percentage (%)", r.get("pass_rate_pct")),
        ("Pass Delta vs Prior Run (%)", comp.get("pass_rate_delta_pct", 0.0)),
        ("Newly Failed Count", len(comp.get("newly_failed_tests", []))),
        ("Regression Count", len(comp.get("regression_defects", []))),
    ]
    ws_sum.append(["Metric", "Value"])
    for cell in ws_sum[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
    for k, v in summary_rows:
        ws_sum.append([k, v])
    ws_sum.column_dimensions["A"].width = 30
    ws_sum.column_dimensions["B"].width = 45

    ws_res = wb.create_sheet("Test Results")
    headers = [
        "Run ID", "Suite", "Case ID", "Case Name", "Module", "Environment",
        "Start Time", "End Time", "Duration (ms)", "Status", "Severity",
        "Expected Result", "Actual Result", "Error Message", "Stack Trace",
        "API Response (Sanitized)", "Screenshot Ref", "Defect Ref",
    ]
    ws_res.append(headers)
    for cell in ws_res[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
    for item in bundle["results"]:
        ws_res.append([
            run_id,
            item.get("suite_id"),
            item.get("case_id"),
            item.get("case_name"),
            item.get("module"),
            item.get("environment"),
            item.get("start_time_iso"),
            item.get("end_time_iso"),
            item.get("duration_ms"),
            item.get("status"),
            item.get("severity"),
            item.get("expected_result"),
            item.get("actual_result"),
            item.get("error_message"),
            (item.get("stack_trace") or "")[:3000],
            (item.get("api_response_sanitized") or "")[:2000],
            item.get("screenshot_ref") or "",
            item.get("defect_id") or "",
        ])

    ws_def = wb.create_sheet("Defects")
    ws_def.append(["Defect ID", "Title", "Module", "Severity", "Priority", "Status", "Assigned Admin", "Evidence", "Resolution Notes"])
    for cell in ws_def[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
    for d in bundle["defects"]:
        ws_def.append([
            d.get("defect_id"), d.get("title"), d.get("module"), d.get("severity"),
            d.get("priority"), d.get("status"), d.get("assigned_admin"),
            (d.get("evidence") or "")[:1500], d.get("resolution_notes") or "",
        ])

    ws_hist = wb.create_sheet("Historical Comparison")
    ws_hist.append(["Run ID", "Pass Rate (%)", "Duration (ms)", "Timestamp"])
    for cell in ws_hist[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
    for p_item, d_item in zip(comp.get("pass_percentage_trend", []), comp.get("execution_duration_trend", [])):
        ws_hist.append([p_item["run_id"], p_item["pass_rate_pct"], d_item["duration_ms"], p_item["created_at"]])

    ws_logs = wb.create_sheet("Execution Logs")
    ws_logs.append(["Timestamp", "Level", "Source", "Message"])
    for cell in ws_logs[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
    for lg in bundle["logs"][:500]:
        ws_logs.append([_fmt_ts(lg.get("logged_at")), lg.get("level"), lg.get("source"), lg.get("message")])

    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"qa_report_{run_id}.xlsx"
    fpath = REPORTS_DIR / fname
    fpath.write_bytes(raw)
    _save_report_artifact(run_id, "EXCEL", fpath, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fname


def generate_pdf_report(run_id: str) -> Optional[Tuple[bytes, str, str]]:
    bundle = build_run_report_bundle(run_id)
    if not bundle:
        return None
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    story = []

    r = bundle["run"]
    comp = bundle["historical_comparison"]
    story.append(Paragraph(f"<b>AraaBot Enterprise QA Test Report — {html.escape(run_id)}</b>", styles["Title"]))
    story.append(Paragraph(
        f"Environment: <b>{html.escape(str(r.get('environment')))}</b> | "
        f"Trigger: <b>{html.escape(str(r.get('trigger_type')))}</b> | "
        f"Status: <b>{html.escape(str(r.get('status')))}</b> | "
        f"Readiness: <b>{html.escape(str(r.get('deployment_readiness')))}</b> | "
        f"Duration: {r.get('duration_ms', 0)} ms | "
        f"Pass Delta: {comp.get('pass_rate_delta_pct', 0.0):+.2f}%",
        styles["Normal"],
    ))
    story.append(Spacer(1, 10))

    kpi_table = Table(
        [
            ["Total", "Passed", "Failed", "Blocked", "Skipped", "Pending", "Pass %", "Newly Failed", "Regressions"],
            [
                r.get("total_cases", 0), r.get("passed_cases", 0), r.get("failed_cases", 0),
                r.get("blocked_cases", 0), r.get("skipped_cases", 0), r.get("pending_cases", 0),
                f"{r.get('pass_rate_pct', 0)}%", len(comp.get("newly_failed_tests", [])), len(comp.get("regression_defects", [])),
            ],
        ],
        colWidths=[70] * 9,
    )
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    res_rows = [["Suite", "Case ID", "Status", "Severity", "Duration", "Actual / Error", "Defect / Artifact"]]
    for item in bundle["results"][:120]:
        msg = item.get("actual_result") or ""
        if item.get("error_message"):
            msg += f" | ERR: {item['error_message'][:120]}"
        res_rows.append([
            Paragraph(html.escape(str(item.get("suite_id") or "")), styles["Normal"]),
            Paragraph(html.escape(str(item.get("case_id") or "")), styles["Normal"]),
            str(item.get("status") or ""),
            str(item.get("severity") or ""),
            f"{item.get('duration_ms', 0)}ms",
            Paragraph(html.escape(msg[:220]), styles["Normal"]),
            Paragraph(html.escape(str(item.get("defect_id") or item.get("screenshot_ref") or "—")[:60]), styles["Normal"]),
        ])

    res_tbl = Table(res_rows, colWidths=[72, 130, 56, 52, 54, 280, 110], repeatRows=1)
    res_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]))
    story.append(res_tbl)

    doc.build(story)
    raw = buf.getvalue()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"qa_report_{run_id}.pdf"
    fpath = REPORTS_DIR / fname
    fpath.write_bytes(raw)
    _save_report_artifact(run_id, "PDF", fpath, "application/pdf")
    return raw, "application/pdf", fname
