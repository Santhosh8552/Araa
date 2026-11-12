"""
ARAA PRIVATE LIMITED — Company Foundation, Corporate Governance & HR ERP Service.

Modules:
- CorporateGovernanceService: Directors (DIN), Shareholders, Board Meetings, Resolutions, Disclosures.
- CompanyTreasuryService: Company Bank Accounts, Assets, Vendors, Purchase Orders, Expenses.
- HumanResourcesService: Departments, Employees, Payroll Processing, Leave Management, Announcements, Projects.
- StatutoryComplianceService: Statutory Registers & Regulatory Compliance Calendar.
"""

import hashlib
import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

try:
    from company_auth import log_company_audit
    from company_finance import paise_to_inr_str, to_paise
    from database import query, query_one, write
except ImportError:
    from backend.company_auth import log_company_audit
    from backend.company_finance import paise_to_inr_str, to_paise
    from backend.database import query, query_one, write


# =============================================================================
# 1. CORPORATE GOVERNANCE SERVICE
# =============================================================================
class CorporateGovernanceService:
    """Manages legal directors, share capital, meetings, and board resolutions."""

    @classmethod
    def list_directors(cls, company_id: int) -> List[Dict[str, Any]]:
        return query(
            "SELECT * FROM directors WHERE company_id=? ORDER BY is_active DESC, appointment_date ASC",
            (company_id,),
        )

    @classmethod
    def add_director(
        cls,
        company_id: int,
        full_name: str,
        din: str,
        pan: str,
        designation: str,
        appointment_date: str,
        email: str,
        phone: str = "",
        director_type: str = "EXECUTIVE",
        actor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        director_id = f"dir_{uuid.uuid4().hex[:8]}"
        now = time.time()
        din_clean = din.strip().upper()
        pan_clean = pan.strip().upper()

        existing = query_one("SELECT director_id FROM directors WHERE din=?", (din_clean,))
        if existing:
            return {"success": False, "error": f"Director with DIN '{din_clean}' already registered"}

        write(
            """
            INSERT INTO directors(
                director_id, company_id, full_name, din, pan, designation, director_type,
                appointment_date, email, phone, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                director_id,
                company_id,
                full_name.strip(),
                din_clean,
                pan_clean,
                designation.strip(),
                director_type.upper(),
                appointment_date.strip(),
                email.strip().lower(),
                phone.strip(),
                now,
                now,
            ),
        )

        # Log audit entry
        log_company_audit(
            company_id=company_id,
            action="DIRECTOR_APPOINTED",
            actor=actor,
            resource_type="DIRECTOR",
            resource_id=director_id,
            after={"full_name": full_name, "din": din_clean, "designation": designation},
        )

        return {"success": True, "director_id": director_id, "full_name": full_name, "din": din_clean}

    @classmethod
    def list_shareholders(cls, company_id: int) -> List[Dict[str, Any]]:
        return query("SELECT * FROM shareholders WHERE company_id=? ORDER BY share_count DESC", (company_id,))

    @classmethod
    def add_shareholder(
        cls,
        company_id: int,
        name: str,
        pan: str,
        share_count: int,
        face_value_paise: int = 1000,
        ownership_pct: str = "0.00",
        voting_power_pct: str = "0.00",
        entity_type: str = "INDIVIDUAL",
        address: str = "",
        actor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sh_id = f"sh_{uuid.uuid4().hex[:8]}"
        now = time.time()

        write(
            """
            INSERT INTO shareholders(
                shareholder_id, company_id, entity_type, name, pan, address, share_count,
                face_value_paise, paid_up_value_paise, ownership_pct, voting_power_pct, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sh_id,
                company_id,
                entity_type.upper(),
                name.strip(),
                pan.strip().upper(),
                address.strip(),
                int(share_count),
                int(face_value_paise),
                int(face_value_paise),
                str(ownership_pct),
                str(voting_power_pct),
                now,
                now,
            ),
        )

        log_company_audit(
            company_id=company_id,
            action="SHAREHOLDER_ADDED",
            actor=actor,
            resource_type="SHAREHOLDER",
            resource_id=sh_id,
            after={"name": name, "share_count": share_count, "ownership_pct": ownership_pct},
        )

        return {"success": True, "shareholder_id": sh_id, "name": name, "share_count": share_count}

    @classmethod
    def record_board_meeting(
        cls,
        company_id: int,
        meeting_no: str,
        meeting_date: str,
        location: str = "Registered Office / Video Conference",
        attendees: Optional[List[str]] = None,
        agenda: Optional[List[str]] = None,
        minutes_text: str = "",
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        mid = f"bm_{uuid.uuid4().hex[:8]}"
        now = time.time()

        write(
            """
            INSERT INTO board_meetings(
                meeting_id, company_id, meeting_no, meeting_date, location,
                attendees_json, agenda_json, minutes_text, status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
            """,
            (
                mid,
                company_id,
                meeting_no.strip(),
                meeting_date.strip(),
                location.strip(),
                json.dumps(attendees or []),
                json.dumps(agenda or []),
                minutes_text.strip(),
                created_by,
                now,
            ),
        )
        return {"success": True, "meeting_id": mid, "meeting_no": meeting_no}

    @classmethod
    def pass_resolution(
        cls,
        company_id: int,
        resolution_code: str,
        title: str,
        matter: str,
        effective_date: str,
        resolution_type: str = "BOARD",
        voting_result: str = "UNANIMOUSLY_PASSED",
        meeting_id: str = "",
        signatory_director_id: str = "",
        actor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        res_id = f"res_{uuid.uuid4().hex[:8]}"
        now = time.time()

        existing = query_one("SELECT resolution_id FROM board_resolutions WHERE resolution_code=?", (resolution_code,))
        if existing:
            return {"success": False, "error": f"Resolution code '{resolution_code}' already exists"}

        write(
            """
            INSERT INTO board_resolutions(
                resolution_id, meeting_id, company_id, resolution_code, title, matter,
                resolution_type, voting_result, effective_date, signatory_director_id,
                filing_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FILED', ?)
            """,
            (
                res_id,
                meeting_id.strip(),
                company_id,
                resolution_code.strip().upper(),
                title.strip(),
                matter.strip(),
                resolution_type.upper(),
                voting_result.upper(),
                effective_date.strip(),
                signatory_director_id.strip(),
                now,
            ),
        )

        log_company_audit(
            company_id=company_id,
            action="RESOLUTION_PASSED",
            actor=actor,
            resource_type="BOARD_RESOLUTION",
            resource_id=res_id,
            after={"code": resolution_code, "title": title},
        )

        return {"success": True, "resolution_id": res_id, "resolution_code": resolution_code, "title": title}


# =============================================================================
# 2. COMPANY TREASURY, ASSETS & VENDORS
# =============================================================================
class CompanyTreasuryService:
    """Manages company bank accounts, operational assets, vendors, and expenses."""

    @classmethod
    def list_bank_accounts(cls, company_id: int) -> List[Dict[str, Any]]:
        accounts = query("SELECT * FROM company_bank_accounts WHERE company_id=? ORDER BY is_primary DESC", (company_id,))
        for a in accounts:
            a["balance_inr"] = paise_to_inr_str(a["balance_paise"])
        return accounts

    @classmethod
    def add_bank_account(
        cls,
        company_id: int,
        bank_name: str,
        account_number: str,
        ifsc_code: str,
        branch: str = "Bangalore Main",
        account_type: str = "CURRENT",
        balance_paise: int = 0,
        is_primary: bool = False,
    ) -> Dict[str, Any]:
        aid = f"cba_{uuid.uuid4().hex[:8]}"
        now = time.time()
        masked = account_number[-4:].rjust(len(account_number), "X")

        write(
            """
            INSERT INTO company_bank_accounts(
                account_id, company_id, bank_name, account_number_masked, ifsc_code,
                branch, account_type, balance_paise, currency, is_primary, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'INR', ?, 1, ?)
            """,
            (
                aid,
                company_id,
                bank_name.strip(),
                masked,
                ifsc_code.strip().upper(),
                branch.strip(),
                account_type.upper(),
                int(balance_paise),
                1 if is_primary else 0,
                now,
            ),
        )
        return {"success": True, "account_id": aid, "bank_name": bank_name, "account_masked": masked}

    @classmethod
    def add_vendor(
        cls,
        company_id: int,
        vendor_name: str,
        service_category: str,
        gstin: str = "",
        pan: str = "",
        contact_email: str = "",
        contact_phone: str = "",
    ) -> Dict[str, Any]:
        vid = f"vnd_{uuid.uuid4().hex[:8]}"
        now = time.time()

        write(
            """
            INSERT INTO vendors(
                vendor_id, company_id, vendor_name, gstin, pan, contact_email,
                contact_phone, service_category, payment_terms, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'NET_30', 'ACTIVE', ?)
            """,
            (
                vid,
                company_id,
                vendor_name.strip(),
                gstin.strip().upper(),
                pan.strip().upper(),
                contact_email.strip().lower(),
                contact_phone.strip(),
                service_category.strip(),
                now,
            ),
        )
        return {"success": True, "vendor_id": vid, "vendor_name": vendor_name}

    @classmethod
    def record_expense(
        cls,
        company_id: int,
        category: str,
        description: str,
        amount_paise: int,
        paid_date: str,
        vendor_id: str = "",
        tax_paise: int = 0,
        tds_paise: int = 0,
        approval_ref: str = "",
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        exp_id = f"exp_{uuid.uuid4().hex[:8]}"
        now = time.time()

        write(
            """
            INSERT INTO expense_records(
                expense_id, company_id, category, vendor_id, description,
                amount_paise, tax_paise, tds_paise, payment_status, paid_date,
                approval_ref, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PAID', ?, ?, ?, ?)
            """,
            (
                exp_id,
                company_id,
                category.strip().upper(),
                vendor_id.strip(),
                description.strip(),
                int(amount_paise),
                int(tax_paise),
                int(tds_paise),
                paid_date.strip(),
                approval_ref.strip(),
                created_by,
                now,
            ),
        )
        return {"success": True, "expense_id": exp_id, "amount_inr": paise_to_inr_str(amount_paise)}


# =============================================================================
# 3. HUMAN RESOURCES & PAYROLL SERVICE
# =============================================================================
class HumanResourcesService:
    """Manages departments, employees, CTC payroll processing, and leave requests."""

    @classmethod
    def list_departments(cls, company_id: int) -> List[Dict[str, Any]]:
        return query("SELECT * FROM departments WHERE company_id=? ORDER BY dept_name ASC", (company_id,))

    @classmethod
    def create_department(
        cls, company_id: int, dept_code: str, dept_name: str, budget_paise: int = 0
    ) -> Dict[str, Any]:
        did = f"dept_{uuid.uuid4().hex[:6]}"
        now = time.time()

        write(
            """
            INSERT INTO departments(dept_id, company_id, dept_code, dept_name, budget_paise, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dept_code) DO UPDATE SET dept_name=excluded.dept_name, budget_paise=excluded.budget_paise
            """,
            (did, company_id, dept_code.strip().upper(), dept_name.strip(), int(budget_paise), now),
        )
        return {"success": True, "dept_id": did, "dept_code": dept_code.upper(), "dept_name": dept_name}

    @classmethod
    def list_employees(cls, company_id: int) -> List[Dict[str, Any]]:
        emps = query(
            """
            SELECT e.*, d.dept_name 
            FROM employees e
            LEFT JOIN departments d ON d.dept_id=e.dept_id
            WHERE e.company_id=?
            ORDER BY e.status ASC, e.date_of_joining DESC
            """,
            (company_id,),
        )
        for e in emps:
            e["ctc_annual_inr"] = paise_to_inr_str(e["ctc_annual_paise"])
        return emps

    @classmethod
    def onboard_employee(
        cls,
        company_id: int,
        emp_code: str,
        full_name: str,
        email: str,
        phone: str,
        dept_id: str,
        designation: str,
        date_of_joining: str,
        ctc_annual_paise: int,
        pan: str,
        uan: str = "",
        user_id: Optional[int] = None,
        actor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        eid = f"emp_{uuid.uuid4().hex[:8]}"
        now = time.time()

        existing = query_one("SELECT employee_id FROM employees WHERE emp_code=?", (emp_code.strip().upper(),))
        if existing:
            return {"success": False, "error": f"Employee with code '{emp_code}' already exists"}

        write(
            """
            INSERT INTO employees(
                employee_id, company_id, emp_code, user_id, full_name, email, phone,
                dept_id, designation, date_of_joining, ctc_annual_paise, pan, uan,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                eid,
                company_id,
                emp_code.strip().upper(),
                user_id,
                full_name.strip(),
                email.strip().lower(),
                phone.strip(),
                dept_id.strip(),
                designation.strip(),
                date_of_joining.strip(),
                int(ctc_annual_paise),
                pan.strip().upper(),
                uan.strip(),
                now,
                now,
            ),
        )

        log_company_audit(
            company_id=company_id,
            action="EMPLOYEE_ONBOARDED",
            actor=actor,
            resource_type="EMPLOYEE",
            resource_id=eid,
            after={"emp_code": emp_code, "full_name": full_name, "designation": designation},
        )

        return {"success": True, "employee_id": eid, "emp_code": emp_code, "full_name": full_name}

    @classmethod
    def calculate_and_process_payroll(
        cls, company_id: int, employee_id: str, month_year: str
    ) -> Dict[str, Any]:
        """Calculates Indian statutory salary breakdown (Basic, HRA, PF, TDS, Prof Tax)."""
        emp = query_one(
            "SELECT * FROM employees WHERE company_id=? AND employee_id=?",
            (company_id, employee_id),
        )
        if not emp:
            return {"success": False, "error": "Employee not found"}

        annual_paise = emp["ctc_annual_paise"]
        monthly_paise = annual_paise // 12

        # Standard Indian salary structuring
        basic_paise = int(monthly_paise * 0.50)
        hra_paise = int(monthly_paise * 0.25)
        special_paise = monthly_paise - basic_paise - hra_paise

        # Statutory deductions
        pf_paise = min(int(basic_paise * 0.12), 216000)  # Capped or 12% of basic
        prof_tax_paise = 20000  # ₹200 standard monthly PT
        tds_paise = int(monthly_paise * 0.05) if monthly_paise > 6000000 else 0

        net_pay_paise = monthly_paise - pf_paise - prof_tax_paise - tds_paise
        now = time.time()
        pid = f"pay_{uuid.uuid4().hex[:8]}"

        write(
            """
            INSERT INTO payroll_records(
                payroll_id, employee_id, company_id, month_year, gross_pay_paise,
                basic_paise, hra_paise, special_allowance_paise, pf_deduction_paise,
                tds_deduction_paise, prof_tax_paise, net_pay_paise, payment_status,
                disbursed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROCESSED', ?, ?)
            ON CONFLICT(employee_id, month_year) DO UPDATE SET
                net_pay_paise=excluded.net_pay_paise,
                payment_status='PROCESSED',
                disbursed_at=excluded.disbursed_at
            """,
            (
                pid,
                employee_id,
                company_id,
                month_year.strip(),
                monthly_paise,
                basic_paise,
                hra_paise,
                special_paise,
                pf_paise,
                tds_paise,
                prof_tax_paise,
                net_pay_paise,
                now,
                now,
            ),
        )

        return {
            "success": True,
            "payroll_id": pid,
            "employee_id": employee_id,
            "month_year": month_year,
            "gross_inr": paise_to_inr_str(monthly_paise),
            "net_pay_inr": paise_to_inr_str(net_pay_paise),
            "deductions": {
                "pf_inr": paise_to_inr_str(pf_paise),
                "prof_tax_inr": paise_to_inr_str(prof_tax_paise),
                "tds_inr": paise_to_inr_str(tds_paise),
            },
        }


# =============================================================================
# 4. STATUTORY COMPLIANCE & CALENDAR SERVICE
# =============================================================================
class StatutoryComplianceService:
    """Tracks statutory registers (ROC) and mandatory regulatory compliance deadlines."""

    @classmethod
    def list_compliance_calendar(cls, company_id: int) -> List[Dict[str, Any]]:
        return query(
            "SELECT * FROM compliance_calendar WHERE company_id=? ORDER BY due_date ASC",
            (company_id,),
        )

    @classmethod
    def seed_statutory_calendar(cls, company_id: int) -> None:
        """Seeds mandatory MCA, Income Tax, GST & SEBI statutory compliance dates."""
        now = time.time()
        statutory_items = [
            ("Annual Return Filing (MGT-7)", "MCA", "2026-11-29", "MGT-7", "ANNUAL"),
            ("Financial Statements Filing (AOC-4)", "MCA", "2026-10-30", "AOC-4", "ANNUAL"),
            ("Director KYC Verification (DIR-3 KYC)", "MCA", "2026-09-30", "DIR-3 KYC", "ANNUAL"),
            ("Quarterly TDS Return (Form 26Q)", "INCOME_TAX", "2026-10-31", "26Q", "QUARTERLY"),
            ("Monthly GST Return (GSTR-3B)", "GSTN", "2026-11-20", "GSTR-3B", "MONTHLY"),
            ("Corporate Tax Return (ITR-6)", "INCOME_TAX", "2026-10-31", "ITR-6", "ANNUAL"),
        ]
        for title, auth, due, form_no, rec in statutory_items:
            iid = f"comp_{hashlib.sha256((title + due).encode()).hexdigest()[:8]}"
            write(
                """
                INSERT OR IGNORE INTO compliance_calendar(
                    item_id, company_id, title, authority, due_date, form_number, recurrence, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'UPCOMING', ?)
                """,
                (iid, company_id, title, auth, due, form_no, rec, now),
            )

