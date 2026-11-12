"""
ARAA Company Trading Platform — Company Governance, RBAC, MFA & Approvals Engine.

Implements:
- Company profile management (company-owned proprietary trading entity)
- 7-role RBAC (COMPANY_DIRECTOR, SUPER_ADMIN, FINANCE_ADMIN, TRADING_ADMIN,
  RISK_MANAGER, TECHNICAL_ADMIN, AUDITOR)
- RFC-6238 TOTP MFA (pure Python HMAC-SHA1, encrypted secret storage via SECRETS_KEY)
- Brute-force lockout, session management, and explicit session revocation
- Maker-checker approval workflows for sensitive trading/capital operations
- Immutable company audit logging (`company_audit_logs`)
"""

import base64
import functools
import hashlib
import hmac
import json
import secrets
import struct
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

from flask import g, jsonify, request

try:
    from database import (
        decrypt_secret,
        encrypt_secret,
        hash_password,
        query,
        query_one,
        verify_password,
        write,
    )
    from migrations import ROLE_PERMISSION_MAP
except ImportError:
    from backend.database import (
        decrypt_secret,
        encrypt_secret,
        hash_password,
        query,
        query_one,
        verify_password,
        write,
    )
    from backend.migrations import ROLE_PERMISSION_MAP


SESSION_TTL_SECONDS = 12 * 3600
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 15 * 60


# ---------------------------------------------------------------------------
# Pure-Python RFC-6238 TOTP MFA Helpers
# ---------------------------------------------------------------------------
def generate_totp_secret(length_bytes: int = 20) -> str:
    """Generates a Base32-encoded TOTP shared secret."""
    raw = secrets.token_bytes(length_bytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _normalize_b32(secret: str) -> bytes:
    cleaned = secret.strip().replace(" ", "").upper()
    padding = (-len(cleaned)) % 8
    return base64.b32decode(cleaned + ("=" * padding), casefold=True)


def totp_code(secret: str, for_time: Optional[float] = None, step: int = 30, digits: int = 6) -> str:
    """Computes RFC-6238 TOTP code for the given time step."""
    ts = time.time() if for_time is None else float(for_time)
    counter = int(ts // step)
    key = _normalize_b32(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code_int).zfill(digits)


def verify_totp_code(secret: str, code: str, window: int = 1, step: int = 30) -> bool:
    """Verifies a 6-digit TOTP code allowing +/- `window` 30s steps."""
    if not secret or not code:
        return False
    candidate = str(code).strip()
    if not candidate.isdigit() or len(candidate) != 6:
        return False
    now = time.time()
    for offset in range(-window, window + 1):
        expected = totp_code(secret, for_time=now + (offset * step), step=step)
        if secrets.compare_digest(candidate, expected):
            return True
    return False


def totp_provisioning_uri(secret: str, email: str, issuer: str = "ARAA Company Trading") -> str:
    label = urllib.parse.quote(f"{issuer}:{email}")
    qs = urllib.parse.urlencode({"secret": secret, "issuer": issuer, "digits": "6", "period": "30"})
    return f"otpauth://totp/{label}?{qs}"


# ---------------------------------------------------------------------------
# Audit Logging
# ---------------------------------------------------------------------------
def log_company_audit(
    company_id: int,
    action: str,
    actor: Optional[Dict[str, Any]] = None,
    resource_type: str = "",
    resource_id: str = "",
    before: Any = None,
    after: Any = None,
    status: str = "SUCCESS",
    ip_address: str = "",
) -> str:
    """Writes an immutable audit record to `company_audit_logs`."""
    log_uuid = f"aud_{uuid.uuid4().hex[:16]}"
    actor_id = actor.get("id") if actor else None
    actor_email = (actor.get("email") if actor else "") or ""
    actor_role = (actor.get("role_code") if actor else "") or ""
    write(
        "INSERT INTO company_audit_logs(log_uuid, company_id, actor_user_id, actor_email, actor_role, "
        "action, resource_type, resource_id, before_json, after_json, ip_address, status, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            log_uuid,
            company_id,
            actor_id,
            actor_email,
            actor_role,
            action,
            resource_type,
            str(resource_id),
            json.dumps(before if before is not None else {}, default=str),
            json.dumps(after if after is not None else {}, default=str),
            ip_address,
            status,
            time.time(),
        ),
    )
    return log_uuid


# ---------------------------------------------------------------------------
# Company Authentication, RBAC, MFA & Maker-Checker Service
# ---------------------------------------------------------------------------
class CompanyAuthService:
    """Manages company profile, employee accounts, RBAC permissions, MFA, and approvals."""

    @staticmethod
    def get_default_company() -> Dict[str, Any]:
        row = query_one("SELECT * FROM companies ORDER BY id ASC LIMIT 1")
        if not row:
            raise RuntimeError("Default ARAA company record missing; run migrations first")
        return dict(row)

    @staticmethod
    def get_company_profile(company_id: Optional[int] = None) -> Dict[str, Any]:
        co = (
            query_one("SELECT * FROM companies WHERE id=?", (company_id,))
            if company_id
            else CompanyAuthService.get_default_company()
        )
        if not co:
            return {}
        emp_count = query_one("SELECT COUNT(*) as c FROM company_users WHERE company_id=?", (co["id"],))["c"]
        res = dict(co)
        res["employee_count"] = emp_count
        return res

    @staticmethod
    def update_company_profile(
        company_id: int, updates: Dict[str, Any], actor: Dict[str, Any], ip_address: str = ""
    ) -> Dict[str, Any]:
        before = query_one("SELECT * FROM companies WHERE id=?", (company_id,))
        if not before:
            return {"success": False, "error": "Company not found"}

        allowed = ("legal_name", "cin_or_reg_no", "pan", "gstin", "compliance_status")
        fields: List[str] = []
        values: List[Any] = []
        for k in allowed:
            if k in updates and updates[k] is not None:
                fields.append(f"{k}=?")
                values.append(str(updates[k]).strip())
        if not fields:
            return {"success": False, "error": "No editable fields supplied"}

        fields.append("updated_at=?")
        values.append(time.time())
        values.append(company_id)
        write(f"UPDATE companies SET {', '.join(fields)} WHERE id=?", tuple(values))
        after = query_one("SELECT * FROM companies WHERE id=?", (company_id,))
        log_company_audit(
            company_id=company_id,
            action="COMPANY_PROFILE_UPDATED",
            actor=actor,
            resource_type="COMPANY",
            resource_id=str(company_id),
            before=before,
            after=after,
            ip_address=ip_address,
        )
        return {"success": True, "company": after}

    @staticmethod
    def list_roles() -> List[Dict[str, Any]]:
        roles = query("SELECT * FROM roles ORDER BY hierarchy_level DESC, role_code ASC")
        out = []
        for r in roles:
            perms = query(
                "SELECT permission_code FROM role_permissions WHERE role_code=? ORDER BY permission_code ASC",
                (r["role_code"],),
            )
            item = dict(r)
            item["permissions"] = [p["permission_code"] for p in perms]
            out.append(item)
        return out

    @staticmethod
    def get_user_permissions(role_code: str) -> List[str]:
        rows = query("SELECT permission_code FROM role_permissions WHERE role_code=?", (role_code,))
        if rows:
            return [r["permission_code"] for r in rows]
        return list(ROLE_PERMISSION_MAP.get(role_code, []))

    @staticmethod
    def has_permission(user: Dict[str, Any], permission_code: str) -> bool:
        if not user or user.get("status") != "ACTIVE":
            return False
        return permission_code in CompanyAuthService.get_user_permissions(user.get("role_code", ""))

    @staticmethod
    def create_employee(
        company_id: int,
        email: str,
        full_name: str,
        password: str,
        role_code: str,
        actor: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        clean_email = (email or "").strip().lower()
        clean_name = (full_name or "").strip()
        clean_role = (role_code or "").strip().upper()
        if not clean_email or "@" not in clean_email:
            return {"success": False, "error": "Valid company email required"}
        if len(password or "") < 8:
            return {"success": False, "error": "Password must be at least 8 characters"}
        if not query_one("SELECT role_code FROM roles WHERE role_code=?", (clean_role,)):
            return {"success": False, "error": f"Unknown role_code: {clean_role}"}
        if query_one("SELECT id FROM company_users WHERE email=?", (clean_email,)):
            return {"success": False, "error": "Employee email already registered"}

        salt, pw_h = hash_password(password)
        now = time.time()
        emp_id = write(
            "INSERT INTO company_users(company_id, email, full_name, pw_salt, pw_hash, role_code, "
            "status, mfa_enabled, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (company_id, clean_email, clean_name or clean_email, salt, pw_h, clean_role, "ACTIVE", 0, now, now),
        )
        emp = CompanyAuthService.sanitize_employee(query_one("SELECT * FROM company_users WHERE id=?", (emp_id,)))
        log_company_audit(
            company_id=company_id,
            action="EMPLOYEE_CREATED",
            actor=actor,
            resource_type="COMPANY_USER",
            resource_id=str(emp_id),
            after=emp,
            ip_address=ip_address,
        )
        return {"success": True, "employee": emp}

    @staticmethod
    def sanitize_employee(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        d = dict(row)
        d.pop("pw_salt", None)
        d.pop("pw_hash", None)
        d.pop("mfa_secret_enc", None)
        d.pop("mfa_backup_hashes_json", None)
        d["permissions"] = CompanyAuthService.get_user_permissions(d.get("role_code", ""))
        return d

    @staticmethod
    def list_employees(company_id: int) -> List[Dict[str, Any]]:
        rows = query("SELECT * FROM company_users WHERE company_id=? ORDER BY id ASC", (company_id,))
        return [CompanyAuthService.sanitize_employee(r) for r in rows]

    @staticmethod
    def update_employee(
        company_id: int,
        emp_id: int,
        updates: Dict[str, Any],
        actor: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        target = query_one("SELECT * FROM company_users WHERE id=? AND company_id=?", (emp_id, company_id))
        if not target:
            return {"success": False, "error": "Employee not found"}

        before = CompanyAuthService.sanitize_employee(target)
        fields: List[str] = []
        values: List[Any] = []

        if "role_code" in updates and updates["role_code"]:
            rc = str(updates["role_code"]).strip().upper()
            if not query_one("SELECT role_code FROM roles WHERE role_code=?", (rc,)):
                return {"success": False, "error": f"Invalid role_code: {rc}"}
            fields.append("role_code=?")
            values.append(rc)

        if "status" in updates and updates["status"]:
            st = str(updates["status"]).strip().upper()
            if st not in ("ACTIVE", "SUSPENDED", "DISABLED"):
                return {"success": False, "error": "Invalid status"}
            fields.append("status=?")
            values.append(st)

        if "full_name" in updates and updates["full_name"]:
            fields.append("full_name=?")
            values.append(str(updates["full_name"]).strip())

        if not fields:
            return {"success": False, "error": "No valid updates supplied"}

        fields.append("updated_at=?")
        values.append(time.time())
        values.extend([emp_id, company_id])
        write(f"UPDATE company_users SET {', '.join(fields)} WHERE id=? AND company_id=?", tuple(values))

        if updates.get("status") in ("SUSPENDED", "DISABLED"):
            CompanyAuthService.revoke_all_user_sessions(emp_id)

        after = CompanyAuthService.sanitize_employee(
            query_one("SELECT * FROM company_users WHERE id=? AND company_id=?", (emp_id, company_id))
        )
        log_company_audit(
            company_id=company_id,
            action="EMPLOYEE_UPDATED",
            actor=actor,
            resource_type="COMPANY_USER",
            resource_id=str(emp_id),
            before=before,
            after=after,
            ip_address=ip_address,
        )
        return {"success": True, "employee": after}

    @staticmethod
    def enroll_mfa(emp_id: int) -> Dict[str, Any]:
        emp = query_one("SELECT * FROM company_users WHERE id=?", (emp_id,))
        if not emp:
            return {"success": False, "error": "Employee not found"}
        secret = generate_totp_secret()
        write(
            "UPDATE company_users SET mfa_secret_enc=?, updated_at=? WHERE id=?",
            (encrypt_secret(secret), time.time(), emp_id),
        )
        return {
            "success": True,
            "secret": secret,
            "provisioning_uri": totp_provisioning_uri(secret, emp["email"]),
            "mfa_enabled": bool(emp.get("mfa_enabled")),
        }

    @staticmethod
    def confirm_mfa_enrollment(emp_id: int, totp: str, ip_address: str = "") -> Dict[str, Any]:
        emp = query_one("SELECT * FROM company_users WHERE id=?", (emp_id,))
        if not emp or not emp.get("mfa_secret_enc"):
            return {"success": False, "error": "MFA enrollment not initiated"}
        secret = decrypt_secret(emp["mfa_secret_enc"])
        if not verify_totp_code(secret, totp):
            return {"success": False, "error": "Invalid 6-digit TOTP verification code"}

        backup_codes = [secrets.token_hex(4).upper() for _ in range(6)]
        backup_hashes = [hashlib.sha256(c.encode("utf-8")).hexdigest() for c in backup_codes]
        write(
            "UPDATE company_users SET mfa_enabled=1, mfa_backup_hashes_json=?, updated_at=? WHERE id=?",
            (json.dumps(backup_hashes), time.time(), emp_id),
        )
        log_company_audit(
            company_id=emp["company_id"],
            action="MFA_ENABLED",
            actor=emp,
            resource_type="COMPANY_USER",
            resource_id=str(emp_id),
            ip_address=ip_address,
        )
        return {"success": True, "mfa_enabled": True, "backup_codes": backup_codes}

    @staticmethod
    def authenticate_employee(
        email: str,
        password: str,
        totp: str = "",
        ip_address: str = "",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        clean_email = (email or "").strip().lower()
        emp = query_one("SELECT * FROM company_users WHERE email=?", (clean_email,))
        if not emp:
            return {"success": False, "error": "Invalid credentials", "code": 401}

        now = time.time()
        if emp.get("status") != "ACTIVE":
            return {"success": False, "error": f"Account status is {emp.get('status')}", "code": 403}

        if float(emp.get("locked_until") or 0) > now:
            wait_sec = int(float(emp["locked_until"]) - now)
            return {"success": False, "error": f"Account temporarily locked ({wait_sec}s remaining)", "code": 423}

        if not verify_password(password or "", emp["pw_salt"], emp["pw_hash"]):
            fails = int(emp.get("failed_attempts") or 0) + 1
            locked_until = now + LOCKOUT_DURATION_SECONDS if fails >= MAX_FAILED_LOGIN_ATTEMPTS else 0
            write(
                "UPDATE company_users SET failed_attempts=?, locked_until=?, updated_at=? WHERE id=?",
                (fails, locked_until, now, emp["id"]),
            )
            log_company_audit(
                company_id=emp["company_id"],
                action="LOGIN_FAILED",
                actor=emp,
                resource_type="COMPANY_USER",
                resource_id=str(emp["id"]),
                status="FAILED",
                ip_address=ip_address,
            )
            return {"success": False, "error": "Invalid credentials", "code": 401}

        mfa_verified = 0
        if int(emp.get("mfa_enabled") or 0) == 1:
            if not totp:
                return {"success": False, "mfa_required": True, "error": "MFA TOTP code required", "code": 401}
            secret = decrypt_secret(emp.get("mfa_secret_enc") or "")
            if verify_totp_code(secret, totp):
                mfa_verified = 1
            else:
                # Check backup code match (single use)
                code_hash = hashlib.sha256(str(totp).strip().upper().encode("utf-8")).hexdigest()
                try:
                    backups = json.loads(emp.get("mfa_backup_hashes_json") or "[]")
                except Exception:
                    backups = []
                if code_hash in backups:
                    backups.remove(code_hash)
                    write("UPDATE company_users SET mfa_backup_hashes_json=? WHERE id=?", (json.dumps(backups), emp["id"]))
                    mfa_verified = 1
                else:
                    return {"success": False, "mfa_required": True, "error": "Invalid MFA code", "code": 401}

        token = "cmp_" + secrets.token_hex(32)
        expires_at = now + SESSION_TTL_SECONDS
        write(
            "INSERT INTO company_sessions(token, company_id, company_user_id, role_code, ip_address, "
            "user_agent, mfa_verified, revoked, expires_at, created_at, last_seen) "
            "VALUES(?,?,?,?,?,?,?,0,?,?,?)",
            (token, emp["company_id"], emp["id"], emp["role_code"], ip_address, user_agent, mfa_verified, expires_at, now, now),
        )
        write(
            "UPDATE company_users SET failed_attempts=0, locked_until=0, last_login_at=?, updated_at=? WHERE id=?",
            (now, now, emp["id"]),
        )
        sanitized = CompanyAuthService.sanitize_employee(query_one("SELECT * FROM company_users WHERE id=?", (emp["id"],)))
        log_company_audit(
            company_id=emp["company_id"],
            action="LOGIN_SUCCESS",
            actor=sanitized,
            resource_type="SESSION",
            resource_id=token[:12],
            ip_address=ip_address,
        )
        return {
            "success": True,
            "token": token,
            "expires_at": expires_at,
            "mfa_verified": bool(mfa_verified),
            "employee": sanitized,
        }

    @staticmethod
    def validate_session(token: str) -> Optional[Dict[str, Any]]:
        if not token or not token.startswith("cmp_"):
            return None
        sess = query_one("SELECT * FROM company_sessions WHERE token=?", (token,))
        if not sess or int(sess.get("revoked") or 0) == 1:
            return None
        if float(sess.get("expires_at") or 0) <= time.time():
            return None
        emp = query_one("SELECT * FROM company_users WHERE id=?", (sess["company_user_id"],))
        if not emp or emp.get("status") != "ACTIVE":
            return None
        write("UPDATE company_sessions SET last_seen=? WHERE token=?", (time.time(), token))
        user = CompanyAuthService.sanitize_employee(emp)
        user["session_mfa_verified"] = bool(sess.get("mfa_verified"))
        user["session_token"] = token
        return user

    @staticmethod
    def revoke_session(token: str, actor: Optional[Dict[str, Any]] = None, ip_address: str = "") -> None:
        if not token:
            return
        write("UPDATE company_sessions SET revoked=1 WHERE token=?", (token,))
        if actor:
            log_company_audit(
                company_id=actor["company_id"],
                action="SESSION_REVOKED",
                actor=actor,
                resource_type="SESSION",
                resource_id=token[:12],
                ip_address=ip_address,
            )

    @staticmethod
    def revoke_all_user_sessions(emp_id: int) -> int:
        write("UPDATE company_sessions SET revoked=1 WHERE company_user_id=?", (emp_id,))
        return 1

    # -----------------------------------------------------------------------
    # Dual-Control Sensitive Operation Approval Workflow
    # -----------------------------------------------------------------------
    @staticmethod
    def request_approval(
        company_id: int,
        approval_type: str,
        target_ref: str,
        requested_by: Dict[str, Any],
        payload: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        approval_id = f"apr_{uuid.uuid4().hex[:14].upper()}"
        now = time.time()
        write(
            "INSERT INTO trading_approvals(approval_id, company_id, approval_type, target_ref, "
            "requested_by, status, payload_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                approval_id,
                company_id,
                approval_type.strip().upper(),
                str(target_ref),
                requested_by["id"],
                "PENDING",
                json.dumps(payload or {}),
                now,
            ),
        )
        log_company_audit(
            company_id=company_id,
            action="APPROVAL_REQUESTED",
            actor=requested_by,
            resource_type="TRADING_APPROVAL",
            resource_id=approval_id,
            after={"approval_type": approval_type, "target_ref": target_ref, "payload": payload or {}},
            ip_address=ip_address,
        )
        return {"success": True, "approval": query_one("SELECT * FROM trading_approvals WHERE approval_id=?", (approval_id,))}

    @staticmethod
    def decide_approval(
        company_id: int,
        approval_id: str,
        decision: str,
        approver: Dict[str, Any],
        note: str = "",
        ip_address: str = "",
    ) -> Dict[str, Any]:
        row = query_one(
            "SELECT * FROM trading_approvals WHERE approval_id=? AND company_id=?",
            (approval_id, company_id),
        )
        if not row:
            return {"success": False, "error": "Approval request not found"}
        if row["status"] != "PENDING":
            return {"success": False, "error": f"Approval already finalized ({row['status']})"}
        if int(row["requested_by"]) == int(approver["id"]):
            return {"success": False, "error": "Dual-control violation: requester cannot self-approve"}

        clean_decision = str(decision or "").strip().upper()
        if clean_decision not in ("APPROVED", "REJECTED"):
            return {"success": False, "error": "Decision must be APPROVED or REJECTED"}

        now = time.time()
        write(
            "UPDATE trading_approvals SET status=?, approved_by=?, decision_note=?, decided_at=? WHERE approval_id=?",
            (clean_decision, approver["id"], note, now, approval_id),
        )
        updated = query_one("SELECT * FROM trading_approvals WHERE approval_id=?", (approval_id,))
        log_company_audit(
            company_id=company_id,
            action=f"APPROVAL_{clean_decision}",
            actor=approver,
            resource_type="TRADING_APPROVAL",
            resource_id=approval_id,
            before=row,
            after=updated,
            ip_address=ip_address,
        )
        return {"success": True, "approval": updated}


# ---------------------------------------------------------------------------
# Strict Fail-Closed Flask Route Decorators
# ---------------------------------------------------------------------------
def extract_company_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    if request.headers.get("X-Company-Token"):
        return request.headers.get("X-Company-Token", "").strip()
    return ""


def require_company_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        tok = extract_company_token()
        emp = CompanyAuthService.validate_session(tok)
        if not emp:
            return jsonify({"success": False, "error": "Company authentication required"}), 401
        g.company_user = emp
        return fn(*args, **kwargs)

    return wrapper


def require_permission(permission_code: str):
    def decorator(fn):
        @functools.wraps(fn)
        @require_company_auth
        def wrapper(*args, **kwargs):
            emp = g.company_user
            if not CompanyAuthService.has_permission(emp, permission_code):
                log_company_audit(
                    company_id=emp["company_id"],
                    action="PERMISSION_DENIED",
                    actor=emp,
                    resource_type="PERMISSION",
                    resource_id=permission_code,
                    status="DENIED",
                    ip_address=request.remote_addr or "",
                )
                return jsonify({
                    "success": False,
                    "error": f"Forbidden: missing permission '{permission_code}' for role {emp.get('role_code')}",
                }), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator

