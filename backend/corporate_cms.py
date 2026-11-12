"""
ARAA PRIVATE LIMITED — Corporate Website & Owner Super Admin CMS Service.

Provides:
- 17 Public Corporate Pages content delivery (About, Technology, Quantitative Research, Prop Desk,
  Brokerage Ecosystem, Wallet Infrastructure, Leadership, Governance, Security, Careers, News, etc.)
- Owner Visual CMS Management: Edit content, theme colors, typography, menus, news, careers, and contact enquiries.
- Page versioning, draft/publish workflow, and instant rollback.
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from database import query, query_one, write, writes
except ImportError:
    from backend.database import query, query_one, write, writes


DEFAULT_THEME = {
    "primary_color": "#00FF88",        # Neon Lime
    "secondary_color": "#004D25",      # Deep Forest Green
    "background_dark": "#050B08",      # Ultra Dark Obsidian Black
    "surface_dark": "#0A140E",         # Deep Slate Emerald
    "border_color": "rgba(0, 255, 136, 0.2)",
    "text_primary": "#F0FFF4",
    "text_muted": "#85A392",
    "company_tagline": "Architecting Institutional Quantitative Trading & Autonomous Systems",
    "mca_cin": "U72900KA2024PTC189912",
    "registered_office": "Bengaluru, Karnataka, India",
}

CORPORATE_PAGES = [
    ("home", "ARAA Private Limited — Institutional Quantitative Systems", "Pioneering algorithmic execution, proprietary trading and deep-tech fintech infrastructure."),
    ("about", "About ARAA — Corporate Identity & Vision", "Founded on mathematical rigor, enterprise risk controls and sovereign computational infrastructure."),
    ("technology", "Proprietary Architecture & AI Engine", "9-layer deep quantitative stack, sub-millisecond execution and deterministic risk guards."),
    ("quantitative-research", "Quantitative Models & Alpha Research", "Signal generation, volatility regime analysis, stochastic modeling and backtesting infrastructure."),
    ("prop-desk", "Proprietary Trading Operations", "Strictly deploying company balance-sheet capital across Indian equities and digital asset markets."),
    ("brokerage-infrastructure", "Institutional Brokerage Architecture", "Enterprise gateway design, FIX protocol routing, OMS/RMS integration and regulatory telemetry."),
    ("wallet-custody", "Corporate Treasury & Digital Asset Infrastructure", "MPC multi-sig vaults, cold storage isolation, automated liquidity and auditable double-entry ledgers."),
    ("leadership", "Board of Directors & Senior Leadership", "Experienced quant researchers, financial engineers, systems architects and legal compliance experts."),
    ("corporate-governance", "Governance, Ethics & Compliance", "Uncompromising adherence to statutory guidelines, risk segregation and transparent board governance."),
    ("security-compliance", "Cybersecurity & Cryptographic Architecture", "Hardware-isolated keys, zero-trust perimeter, continuous audit logging and real-time reconciliation."),
    ("careers", "Careers at ARAA — Engineering & Quantitative Talent", "Join exceptional researchers, engineers and architects solving high-frequency systemic challenges."),
    ("news-insights", "Research Papers & Corporate Announcements", "Whitepapers, market structure commentary and technical milestones from the ARAA research desk."),
    ("contact", "Corporate Inquiries & Institutional Relations", "Connect with our executive office, investor relations, and institutional technology partnership team."),
    ("disclosures", "Statutory & Regulatory Disclosures", "Corporate registration details, proprietary capital policies and regulatory declarations."),
    ("privacy-policy", "Data Privacy & Information Security Policy", "Enterprise data handling, cryptographic safeguards, and strict confidentiality guidelines."),
    ("terms-of-use", "Corporate Terms of Use & Legal Framework", "Legal boundaries, intellectual property protections, and institutional access parameters."),
    ("system-status", "Live Enterprise Health & Telemetry", "Real-time uptime, OMS latency, gateway telemetry, and market data ingestion status."),
]


class CorporateCmsService:
    """Manages Corporate Website content, themes, careers, and inquiries."""

    @classmethod
    def seed_initial_cms_content(cls):
        """Idempotently seeds all 17 public corporate pages, sections, and theme settings."""
        now = time.time()
        for k, v in DEFAULT_THEME.items():
            write(
                "INSERT INTO cms_theme_settings(setting_key, setting_val, category, updated_at) "
                "VALUES(?, ?, 'THEME', ?) ON CONFLICT(setting_key) DO NOTHING",
                (k, v, now),
            )

        for slug, title, desc in CORPORATE_PAGES:
            pid = f"page_{slug.replace('-', '_')}"
            write(
                """
                INSERT INTO cms_pages(page_id, slug, title, meta_title, meta_description, status, version, published_at, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, 'PUBLISHED', 1, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET title=excluded.title, meta_description=excluded.meta_description
                """,
                (pid, slug, title, f"{title} | ARAA Private Limited", desc, now, now, now),
            )

            # Seed default hero section for each page
            sec_id = f"sec_{slug.replace('-', '_')}_hero"
            content = json.dumps({
                "headline": title,
                "subheadline": desc,
                "badge": "ARAA ENTERPRISE",
                "cta_text": "Explore Architecture" if slug == "home" else "Contact Executive Office",
                "cta_url": "/corporate/technology" if slug == "home" else "/corporate/contact",
            })
            write(
                """
                INSERT INTO cms_sections(section_id, page_id, section_key, section_title, content_json, order_index, is_visible, created_at, updated_at)
                VALUES(?, ?, 'hero', 'Hero Section', ?, 1, 1, ?, ?)
                ON CONFLICT(section_id) DO NOTHING
                """,
                (sec_id, pid, content, now, now),
            )

    @classmethod
    def get_theme_settings(cls) -> Dict[str, str]:
        rows = query("SELECT setting_key, setting_val FROM cms_theme_settings")
        return {r["setting_key"]: r["setting_val"] for r in rows}

    @classmethod
    def get_public_page(cls, slug: str) -> Optional[Dict[str, Any]]:
        page = query_one("SELECT * FROM cms_pages WHERE slug=? AND status='PUBLISHED'", (slug.strip().lower(),))
        if not page:
            return None
        sections = query(
            "SELECT * FROM cms_sections WHERE page_id=? AND is_visible=1 ORDER BY order_index ASC",
            (page["page_id"],),
        )
        for s in sections:
            try:
                s["content"] = json.loads(s["content_json"])
            except Exception:
                s["content"] = {}
        page["sections"] = sections
        return page

    @classmethod
    def list_all_pages(cls) -> List[Dict[str, Any]]:
        return query("SELECT * FROM cms_pages ORDER BY created_at ASC")

    @classmethod
    def submit_contact_enquiry(
        cls, full_name: str, email: str, subject: str, message: str, phone: str = "", category: str = "GENERAL", ip_addr: str = ""
    ) -> Dict[str, Any]:
        eid = f"enq_{uuid.uuid4().hex[:10]}"
        now = time.time()
        write(
            """
            INSERT INTO cms_contact_enquiries(enquiry_id, full_name, email, phone, subject, message, category, ip_address, status, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?)
            """,
            (eid, full_name.strip(), email.strip().lower(), phone.strip(), subject.strip(), message.strip(), category.upper(), ip_addr, now),
        )
        return {"success": True, "enquiry_id": eid, "message": "Enquiry registered successfully"}

    @classmethod
    def list_contact_enquiries(cls, limit: int = 50) -> List[Dict[str, Any]]:
        return query("SELECT * FROM cms_contact_enquiries ORDER BY created_at DESC LIMIT ?", (limit,))
