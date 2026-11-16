"""
ARAA Company Trading Platform — Versioned Database Migrations Engine.

Supports:
- Idempotent forward SQL migrations tracked in `schema_migrations`
- Checksum verification for applied migrations
- Clean separation between legacy tables and Phase 2+ Company Proprietary schema
- SQLite dev & PostgreSQL production compatibility path
"""

import hashlib
import time
from typing import List, Tuple, Dict, Any

try:
    from database import connect, query, query_one, write
except ImportError:
    from backend.database import connect, query, query_one, write


ROLE_DEFINITIONS: List[Tuple[str, str, str, int]] = [
    ("COMPANY_DIRECTOR", "Company Director", "Top governance authority; final signer for capital, live activation, and risk policy approvals.", 100),
    ("MANAGING_DIRECTOR", "Managing Director", "Executive board leadership overseeing all ARAA business divisions and strategic capital.", 98),
    ("CEO", "Chief Executive Officer", "Executive head of ARAA Private Limited across corporate, prop, brokerage, and technology.", 95),
    ("SUPER_ADMIN", "Super Admin", "Full platform administration, employee management, and company configuration control.", 90),
    ("CTO", "Chief Technology Officer", "Head of engineering, AI trading systems, infrastructure, and cybersecurity.", 88),
    ("CFO", "Chief Financial Officer", "Head of corporate finance, accounting, general ledger, tax, and treasury.", 88),
    ("COMPLIANCE_OFFICER", "Compliance Officer", "Owns statutory registers, regulatory readiness, KYC/AML reviews, and authorization gates.", 85),
    ("RISK_MANAGER", "Risk Manager", "Independent risk guardian owner; configures risk policies, kill switches, and reconciliation halts.", 80),
    ("FINANCE_ADMIN", "Finance Admin", "Manages company capital pools, ledger postings, expenses, and accounting exports.", 75),
    ("FINANCE_MANAGER", "Finance Manager", "Manages corporate accounting, vendor invoices, payroll, TDS/GST, and bank reconciliation.", 75),
    ("TRADING_HEAD", "Trading Head", "Leads ARAA Prop Desk strategies, capital deployment, and autonomous bot operations.", 72),
    ("TRADING_ADMIN", "Trading Admin", "Controls trading sessions, strategy activation, paper/live workflow, and OMS supervision.", 70),
    ("BROKERAGE_OPS_MANAGER", "Brokerage Operations Manager", "Manages brokerage product catalogue, onboarding workflows, and order routing operations.", 68),
    ("WALLET_OPS_MANAGER", "Wallet Operations Manager", "Manages internal treasury wallet operations, address allowlists, and wallet reconciliation.", 68),
    ("HR_MANAGER", "HR Manager", "Manages departments, employee directory, recruitment, payroll records, and leave workflows.", 66),
    ("TECHNICAL_ADMIN", "Technical Administrator", "Manages broker adapters, encrypted API configurations, health monitoring, and deployment ops.", 65),
    ("CMS_ADMIN", "Website CMS Administrator", "Manages corporate website pages, media, news, careers, and SEO (strictly isolated from broker/wallet keys).", 50),
    ("INTERNAL_AUDITOR", "Internal Auditor", "Read-only compliance and financial audit access across all ledgers, logs, and registers.", 25),
    ("AUDITOR", "Auditor (Read-Only)", "Read-only compliance access across ledger, audit logs, trades, positions, and reconciliation runs.", 20),
]

PERMISSION_DEFINITIONS: List[Tuple[str, str, str]] = [
    ("company.view", "COMPANY", "View company profile and organizational overview"),
    ("company.manage", "COMPANY", "Edit company registration, legal profile, and settings"),
    ("governance.manage", "GOVERNANCE", "Manage directors, shareholders, board meetings, resolutions, and statutory registers"),
    ("hr.manage", "HR", "Manage departments, employees, recruitment, payroll, and leave"),
    ("vendors.manage", "ERP", "Manage company assets, vendors, purchase orders, and expenses"),
    ("accounting.manage", "ACCOUNTING", "Manage chart of accounts, journal entries, tax/TDS/GST, and bank reconciliation"),
    ("cms.manage", "CMS", "Manage corporate website pages, theme, media, news, careers, and SEO"),
    ("brokerage.manage", "BROKERAGE", "Manage brokerage configuration, KYC/AML workflows, and customer accounts"),
    ("wallet.manage", "WALLET", "Manage internal treasury wallet and wallet infrastructure"),
    ("compliance.manage", "COMPLIANCE", "Manage regulatory assessment, compliance calendar, and service authorization gates"),
    ("employees.view", "RBAC", "View company employee directory and roles"),
    ("employees.manage", "RBAC", "Create, update roles, or suspend company employees"),
    ("capital.view", "FINANCE", "View independent India and Crypto capital pools"),
    ("capital.allocate", "FINANCE", "Allocate capital across strategies within a pool"),
    ("capital.move", "FINANCE", "Record capital additions, withdrawals, and adjustments"),
    ("brokers.view", "BROKERS", "Inspect company broker accounts and connection health"),
    ("brokers.manage", "BROKERS", "Connect, verify, sync, or revoke broker credentials"),
    ("trading.control", "TRADING", "Start, pause, resume, or stop trading strategies"),
    ("trading.live_enable", "TRADING", "Approve and activate live money execution mode"),
    ("strategy.manage", "STRATEGY", "Create, edit, and version trading strategies"),
    ("risk.view", "RISK", "View risk policies, events, and circuit breaker status"),
    ("risk.manage", "RISK", "Modify risk limits and policies"),
    ("risk.emergency_stop", "RISK", "Trigger or release emergency kill switch / controlled flatten"),
    ("orders.create", "OMS", "Submit manual or strategy order intents"),
    ("orders.cancel", "OMS", "Cancel eligible open broker orders"),
    ("reconciliation.run", "RECON", "Run and resolve broker reconciliation mismatches"),
    ("audit.view", "AUDIT", "Inspect immutable audit logs, ledger, and compliance evidence"),
    ("approvals.decide", "GOVERNANCE", "Approve or reject dual-control sensitive actions"),
]

_ALL_PERMS = [p[0] for p in PERMISSION_DEFINITIONS]

ROLE_PERMISSION_MAP: Dict[str, List[str]] = {
    "COMPANY_DIRECTOR": _ALL_PERMS,
    "MANAGING_DIRECTOR": _ALL_PERMS,
    "CEO": _ALL_PERMS,
    "SUPER_ADMIN": _ALL_PERMS,
    "CTO": [
        "company.view", "employees.view", "brokers.view", "brokers.manage",
        "trading.control", "strategy.manage", "risk.view", "reconciliation.run",
        "audit.view", "cms.manage",
    ],
    "CFO": [
        "company.view", "governance.manage", "vendors.manage", "accounting.manage",
        "capital.view", "capital.allocate", "capital.move", "wallet.manage",
        "brokers.view", "risk.view", "reconciliation.run", "audit.view", "approvals.decide",
    ],
    "COMPLIANCE_OFFICER": [
        "company.view", "governance.manage", "compliance.manage", "brokerage.manage",
        "employees.view", "capital.view", "brokers.view", "risk.view",
        "reconciliation.run", "audit.view", "approvals.decide",
    ],
    "FINANCE_ADMIN": [
        "company.view", "vendors.manage", "accounting.manage", "capital.view",
        "capital.allocate", "capital.move", "brokers.view", "risk.view",
        "reconciliation.run", "audit.view", "approvals.decide",
    ],
    "FINANCE_MANAGER": [
        "company.view", "vendors.manage", "accounting.manage", "capital.view",
        "capital.allocate", "capital.move", "wallet.manage", "brokers.view",
        "risk.view", "reconciliation.run", "audit.view", "approvals.decide",
    ],
    "TRADING_HEAD": [
        "company.view", "capital.view", "brokers.view", "trading.control",
        "strategy.manage", "risk.view", "risk.emergency_stop", "orders.create",
        "orders.cancel", "audit.view", "approvals.decide",
    ],
    "TRADING_ADMIN": [
        "company.view", "capital.view", "brokers.view", "trading.control",
        "strategy.manage", "risk.view", "risk.emergency_stop", "orders.create",
        "orders.cancel", "audit.view",
    ],
    "RISK_MANAGER": [
        "company.view", "capital.view", "brokers.view", "trading.control",
        "risk.view", "risk.manage", "risk.emergency_stop", "orders.cancel",
        "reconciliation.run", "audit.view", "approvals.decide",
    ],
    "BROKERAGE_OPS_MANAGER": [
        "company.view", "brokerage.manage", "brokers.view", "orders.create",
        "orders.cancel", "reconciliation.run", "audit.view",
    ],
    "WALLET_OPS_MANAGER": [
        "company.view", "wallet.manage", "capital.view", "reconciliation.run", "audit.view",
    ],
    "HR_MANAGER": [
        "company.view", "hr.manage", "employees.view", "employees.manage", "audit.view",
    ],
    "TECHNICAL_ADMIN": [
        "company.view", "employees.view", "brokers.view", "brokers.manage",
        "risk.view", "reconciliation.run", "audit.view",
    ],
    "CMS_ADMIN": [
        "company.view", "cms.manage",
    ],
    "INTERNAL_AUDITOR": [
        "company.view", "employees.view", "capital.view", "brokers.view",
        "risk.view", "audit.view",
    ],
    "AUDITOR": [
        "company.view", "employees.view", "capital.view", "brokers.view",
        "risk.view", "audit.view",
    ],
}


_MIGRATION_001_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations(
  version TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at REAL NOT NULL,
  checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_code TEXT NOT NULL UNIQUE,
  legal_name TEXT NOT NULL,
  cin_or_reg_no TEXT DEFAULT '',
  pan TEXT DEFAULT '',
  gstin TEXT DEFAULT '',
  base_currency TEXT NOT NULL DEFAULT 'INR',
  proprietary_only INTEGER NOT NULL DEFAULT 1,
  compliance_status TEXT NOT NULL DEFAULT 'REVIEW_PENDING',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS roles(
  role_code TEXT PRIMARY KEY,
  role_name TEXT NOT NULL,
  description TEXT DEFAULT '',
  hierarchy_level INTEGER NOT NULL DEFAULT 10,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS company_permissions(
  permission_code TEXT PRIMARY KEY,
  module TEXT NOT NULL,
  description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS role_permissions(
  role_code TEXT NOT NULL,
  permission_code TEXT NOT NULL,
  PRIMARY KEY (role_code, permission_code),
  FOREIGN KEY (role_code) REFERENCES roles(role_code) ON DELETE CASCADE,
  FOREIGN KEY (permission_code) REFERENCES company_permissions(permission_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  pw_salt TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  role_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  mfa_enabled INTEGER NOT NULL DEFAULT 0,
  mfa_secret_enc TEXT DEFAULT '',
  mfa_backup_hashes_json TEXT DEFAULT '[]',
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0,
  last_login_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (role_code) REFERENCES roles(role_code)
);
CREATE INDEX IF NOT EXISTS ix_company_users_cid_role ON company_users(company_id, role_code, status);

CREATE TABLE IF NOT EXISTS company_sessions(
  token TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  company_user_id INTEGER NOT NULL,
  role_code TEXT NOT NULL,
  ip_address TEXT DEFAULT '',
  user_agent TEXT DEFAULT '',
  mfa_verified INTEGER NOT NULL DEFAULT 0,
  revoked INTEGER NOT NULL DEFAULT 0,
  expires_at REAL NOT NULL,
  created_at REAL NOT NULL,
  last_seen REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (company_user_id) REFERENCES company_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_company_sessions_uid ON company_sessions(company_user_id, revoked, expires_at);

CREATE TABLE IF NOT EXISTS trading_approvals(
  approval_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  approval_type TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  requested_by INTEGER NOT NULL,
  approved_by INTEGER,
  status TEXT NOT NULL DEFAULT 'PENDING',
  payload_json TEXT NOT NULL DEFAULT '{}',
  decision_note TEXT DEFAULT '',
  created_at REAL NOT NULL,
  decided_at REAL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (requested_by) REFERENCES company_users(id)
);
CREATE INDEX IF NOT EXISTS ix_trading_approvals_status ON trading_approvals(company_id, status, created_at);

CREATE TABLE IF NOT EXISTS company_audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_uuid TEXT NOT NULL UNIQUE,
  company_id INTEGER NOT NULL,
  actor_user_id INTEGER,
  actor_email TEXT DEFAULT '',
  actor_role TEXT DEFAULT '',
  action TEXT NOT NULL,
  resource_type TEXT DEFAULT '',
  resource_id TEXT DEFAULT '',
  before_json TEXT DEFAULT '{}',
  after_json TEXT DEFAULT '{}',
  ip_address TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'SUCCESS',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_company_audit_cid_at ON company_audit_logs(company_id, created_at);

CREATE TABLE IF NOT EXISTS system_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_uuid TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'INFO',
  source TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_system_events_at ON system_events(severity, created_at);
"""


_MIGRATION_002_SQL = """
CREATE TABLE IF NOT EXISTS company_trading_accounts(
  account_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  market_scope TEXT NOT NULL,
  account_name TEXT NOT NULL,
  legal_holder TEXT NOT NULL,
  broker_user_id TEXT DEFAULT '',
  ownership_verified INTEGER NOT NULL DEFAULT 0,
  trading_approved INTEGER NOT NULL DEFAULT 0,
  connection_status TEXT NOT NULL DEFAULT 'DISCONNECTED',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  api_permission_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
  token_expires_at REAL,
  last_synced_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_cta_company_scope ON company_trading_accounts(company_id, market_scope, provider);

CREATE TABLE IF NOT EXISTS broker_account_secrets(
  account_id TEXT PRIMARY KEY,
  api_key_enc TEXT NOT NULL,
  api_secret_enc TEXT NOT NULL,
  access_token_enc TEXT DEFAULT '',
  key_fingerprint TEXT NOT NULL,
  static_egress_ip TEXT DEFAULT '',
  withdrawal_disabled INTEGER NOT NULL DEFAULT 1,
  updated_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES company_trading_accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS broker_capabilities(
  account_id TEXT PRIMARY KEY,
  supports_spot INTEGER NOT NULL DEFAULT 1,
  supports_equity INTEGER NOT NULL DEFAULT 0,
  supports_futures INTEGER NOT NULL DEFAULT 0,
  supports_options INTEGER NOT NULL DEFAULT 0,
  leverage_allowed INTEGER NOT NULL DEFAULT 0,
  max_leverage TEXT NOT NULL DEFAULT '1',
  allowed_segments_json TEXT NOT NULL DEFAULT '[]',
  allowed_order_types_json TEXT NOT NULL DEFAULT '["MARKET","LIMIT"]',
  updated_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES company_trading_accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_capital_pools(
  pool_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_name TEXT NOT NULL,
  market_scope TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  account_id TEXT DEFAULT '',
  base_currency TEXT NOT NULL DEFAULT 'INR',
  allocated_capital_paise INTEGER NOT NULL DEFAULT 0,
  broker_confirmed_equity_paise INTEGER NOT NULL DEFAULT 0,
  free_funds_paise INTEGER NOT NULL DEFAULT 0,
  locked_funds_paise INTEGER NOT NULL DEFAULT 0,
  open_exposure_paise INTEGER NOT NULL DEFAULT 0,
  realized_pnl_paise INTEGER NOT NULL DEFAULT 0,
  unrealized_pnl_paise INTEGER NOT NULL DEFAULT 0,
  fees_paise INTEGER NOT NULL DEFAULT 0,
  taxes_expenses_paise INTEGER NOT NULL DEFAULT 0,
  daily_loss_paise INTEGER NOT NULL DEFAULT 0,
  available_risk_budget_paise INTEGER NOT NULL DEFAULT 0,
  open_positions_count INTEGER NOT NULL DEFAULT 0,
  pending_orders_count INTEGER NOT NULL DEFAULT 0,
  reconciliation_status TEXT NOT NULL DEFAULT 'NOT_RUN',
  last_broker_sync_at REAL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ccp_company_scope ON company_capital_pools(company_id, market_scope);

CREATE TABLE IF NOT EXISTS capital_allocations(
  allocation_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  strategy_code TEXT NOT NULL,
  allocated_paise INTEGER NOT NULL,
  used_paise INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_by INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE (pool_id, strategy_code),
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (pool_id) REFERENCES company_capital_pools(pool_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_capital_movements(
  movement_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  movement_type TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  source_classification TEXT NOT NULL,
  reference_no TEXT DEFAULT '',
  note TEXT DEFAULT '',
  approval_id TEXT DEFAULT '',
  created_by INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (pool_id) REFERENCES company_capital_pools(pool_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ccm_pool_at ON company_capital_movements(pool_id, created_at);
"""


_MIGRATION_003_SQL = """
CREATE TABLE IF NOT EXISTS company_strategies(
  strategy_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  strategy_code TEXT NOT NULL UNIQUE,
  strategy_name TEXT NOT NULL,
  market_scope TEXT NOT NULL,
  provider TEXT NOT NULL,
  active_version_id TEXT DEFAULT '',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  status TEXT NOT NULL DEFAULT 'PAUSED',
  created_by INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_strategy_versions(
  version_id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  instruments_json TEXT NOT NULL DEFAULT '[]',
  timeframe TEXT NOT NULL DEFAULT '15m',
  entry_rules_json TEXT NOT NULL DEFAULT '{}',
  exit_rules_json TEXT NOT NULL DEFAULT '{}',
  stop_loss_pct TEXT NOT NULL DEFAULT '1.00',
  take_profit_pct TEXT NOT NULL DEFAULT '2.50',
  trailing_stop_pct TEXT NOT NULL DEFAULT '0.75',
  max_position_paise INTEGER NOT NULL DEFAULT 2500000,
  max_exposure_paise INTEGER NOT NULL DEFAULT 10000000,
  risk_profile TEXT NOT NULL DEFAULT 'CONSERVATIVE',
  trading_hours_json TEXT NOT NULL DEFAULT '{}',
  is_immutable INTEGER NOT NULL DEFAULT 1,
  paper_validated INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE (strategy_id, version_number),
  FOREIGN KEY (strategy_id) REFERENCES company_strategies(strategy_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_signals(
  signal_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  strategy_version_id TEXT NOT NULL,
  pool_id TEXT NOT NULL,
  market_scope TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange TEXT NOT NULL,
  direction TEXT NOT NULL,
  entry_price_str TEXT NOT NULL,
  stop_loss_str TEXT NOT NULL,
  target_price_str TEXT NOT NULL,
  risk_reward_ratio TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '15m',
  confidence_score INTEGER NOT NULL DEFAULT 0,
  explanation TEXT NOT NULL,
  risk_assessment TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_csig_pool_at ON company_signals(pool_id, created_at);

CREATE TABLE IF NOT EXISTS company_risk_policies(
  policy_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL UNIQUE,
  max_capital_paise INTEGER NOT NULL DEFAULT 10000000,
  max_order_value_paise INTEGER NOT NULL DEFAULT 2500000,
  max_position_size_paise INTEGER NOT NULL DEFAULT 5000000,
  max_open_positions INTEGER NOT NULL DEFAULT 5,
  max_daily_loss_paise INTEGER NOT NULL DEFAULT 500000,
  max_drawdown_bps INTEGER NOT NULL DEFAULT 1000,
  max_quote_age_sec INTEGER NOT NULL DEFAULT 60,
  require_stop_loss INTEGER NOT NULL DEFAULT 1,
  trading_window_enabled INTEGER NOT NULL DEFAULT 0,
  session_start_ist TEXT NOT NULL DEFAULT '09:15',
  session_end_ist TEXT NOT NULL DEFAULT '15:25',
  paused INTEGER NOT NULL DEFAULT 0,
  emergency_stop INTEGER NOT NULL DEFAULT 0,
  updated_by INTEGER,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (pool_id) REFERENCES company_capital_pools(pool_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_risk_events(
  event_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  intent_id TEXT DEFAULT '',
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'WARNING',
  rule_code TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cre_pool_at ON company_risk_events(pool_id, created_at);

CREATE TABLE IF NOT EXISTS order_intents(
  intent_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  strategy_id TEXT DEFAULT '',
  strategy_version_id TEXT DEFAULT '',
  signal_id TEXT DEFAULT '',
  market_scope TEXT NOT NULL,
  provider TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL DEFAULT 'MARKET',
  product TEXT NOT NULL DEFAULT 'CNC',
  quantity_str TEXT NOT NULL,
  limit_price_str TEXT DEFAULT '',
  stop_price_str TEXT DEFAULT '',
  stop_loss_str TEXT DEFAULT '',
  target_price_str TEXT DEFAULT '',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'CREATED',
  rejection_reason TEXT DEFAULT '',
  created_by INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_oi_pool_status ON order_intents(pool_id, status, created_at);

CREATE TABLE IF NOT EXISTS broker_orders(
  order_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  strategy_id TEXT DEFAULT '',
  strategy_version_id TEXT DEFAULT '',
  market_scope TEXT NOT NULL,
  provider TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL,
  quantity_str TEXT NOT NULL,
  filled_qty_str TEXT NOT NULL DEFAULT '0',
  avg_fill_price_str TEXT NOT NULL DEFAULT '0',
  limit_price_str TEXT DEFAULT '',
  stop_price_str TEXT DEFAULT '',
  fees_paise INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT NOT NULL UNIQUE,
  provider_order_id TEXT DEFAULT '',
  provider_response_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'CREATED',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bo_pool_status ON broker_orders(pool_id, status, created_at);

CREATE TABLE IF NOT EXISTS broker_executions(
  execution_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  provider_trade_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  fill_qty_str TEXT NOT NULL,
  fill_price_str TEXT NOT NULL,
  fill_value_paise INTEGER NOT NULL DEFAULT 0,
  fee_paise INTEGER NOT NULL DEFAULT 0,
  tax_paise INTEGER NOT NULL DEFAULT 0,
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  executed_at REAL NOT NULL,
  FOREIGN KEY (order_id) REFERENCES broker_orders(order_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_be_order ON broker_executions(order_id);

CREATE TABLE IF NOT EXISTS company_positions(
  position_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  strategy_id TEXT DEFAULT '',
  strategy_version_id TEXT DEFAULT '',
  market_scope TEXT NOT NULL,
  provider TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity_str TEXT NOT NULL,
  avg_entry_price_str TEXT NOT NULL,
  current_price_str TEXT NOT NULL,
  stop_loss_str TEXT DEFAULT '',
  take_profit_str TEXT DEFAULT '',
  realized_pnl_paise INTEGER NOT NULL DEFAULT 0,
  unrealized_pnl_paise INTEGER NOT NULL DEFAULT 0,
  fees_paise INTEGER NOT NULL DEFAULT 0,
  exit_reason TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'OPEN',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  opened_at REAL NOT NULL,
  closed_at REAL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cp_pool_status ON company_positions(pool_id, status, execution_mode);

CREATE TABLE IF NOT EXISTS company_ledger_entries(
  entry_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT DEFAULT '',
  entry_type TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_classification TEXT NOT NULL DEFAULT 'BROKER_CONFIRMED',
  debit_account TEXT NOT NULL,
  credit_account TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  fee_paise INTEGER NOT NULL DEFAULT 0,
  tax_paise INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'INR',
  execution_mode TEXT NOT NULL DEFAULT 'LIVE',
  narration TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cle_pool_at ON company_ledger_entries(pool_id, created_at);

CREATE TABLE IF NOT EXISTS reconciliation_runs(
  run_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  trigger_source TEXT NOT NULL,
  status TEXT NOT NULL,
  discrepancies_count INTEGER NOT NULL DEFAULT 0,
  raw_broker_snapshot_json TEXT NOT NULL DEFAULT '{}',
  summary_json TEXT NOT NULL DEFAULT '{}',
  started_at REAL NOT NULL,
  completed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_differences(
  diff_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  pool_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  diff_type TEXT NOT NULL,
  entity_ref TEXT NOT NULL,
  local_value_json TEXT NOT NULL,
  broker_value_json TEXT NOT NULL,
  raw_broker_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'OPEN',
  resolution_note TEXT DEFAULT '',
  resolved_by INTEGER,
  created_at REAL NOT NULL,
  resolved_at REAL,
  FOREIGN KEY (run_id) REFERENCES reconciliation_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS compliance_records(
  record_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  authority TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'REQUIRES_REVIEW',
  evidence_ref TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  updated_by INTEGER,
  updated_at REAL NOT NULL
);
"""


_MIGRATION_004_SQL = """
-- 1. Directors & Corporate Governance
CREATE TABLE IF NOT EXISTS directors(
  director_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  full_name TEXT NOT NULL,
  din TEXT NOT NULL UNIQUE,
  pan TEXT NOT NULL,
  designation TEXT NOT NULL,
  director_type TEXT NOT NULL DEFAULT 'EXECUTIVE',
  appointment_date TEXT NOT NULL,
  cessation_date TEXT DEFAULT '',
  email TEXT NOT NULL,
  phone TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shareholders(
  shareholder_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  entity_type TEXT NOT NULL DEFAULT 'INDIVIDUAL',
  name TEXT NOT NULL,
  pan TEXT NOT NULL,
  address TEXT DEFAULT '',
  share_count INTEGER NOT NULL DEFAULT 0,
  face_value_paise INTEGER NOT NULL DEFAULT 1000,
  paid_up_value_paise INTEGER NOT NULL DEFAULT 1000,
  ownership_pct TEXT NOT NULL DEFAULT '0.00',
  voting_power_pct TEXT NOT NULL DEFAULT '0.00',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS share_capital_records(
  record_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  capital_type TEXT NOT NULL,
  share_class TEXT NOT NULL DEFAULT 'EQUITY',
  total_shares INTEGER NOT NULL,
  nominal_value_paise INTEGER NOT NULL,
  total_amount_paise INTEGER NOT NULL,
  authorized_at REAL NOT NULL,
  roc_filing_ref TEXT DEFAULT '',
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS board_meetings(
  meeting_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  meeting_no TEXT NOT NULL,
  meeting_date TEXT NOT NULL,
  start_time_ist TEXT NOT NULL DEFAULT '11:00',
  end_time_ist TEXT NOT NULL DEFAULT '12:30',
  location TEXT NOT NULL DEFAULT 'Registered Office / Video Conference',
  chairman_id TEXT DEFAULT '',
  attendees_json TEXT NOT NULL DEFAULT '[]',
  agenda_json TEXT NOT NULL DEFAULT '[]',
  minutes_text TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'SCHEDULED',
  created_by INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS board_resolutions(
  resolution_id TEXT PRIMARY KEY,
  meeting_id TEXT DEFAULT '',
  company_id INTEGER NOT NULL,
  resolution_code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  matter TEXT NOT NULL,
  resolution_type TEXT NOT NULL DEFAULT 'BOARD',
  voting_result TEXT NOT NULL DEFAULT 'UNANIMOUSLY_PASSED',
  effective_date TEXT NOT NULL,
  signatory_director_id TEXT DEFAULT '',
  filing_status TEXT NOT NULL DEFAULT 'PENDING',
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS statutory_registers(
  register_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  register_type TEXT NOT NULL,
  entry_ref TEXT NOT NULL,
  particulars TEXT NOT NULL,
  legal_reference TEXT NOT NULL,
  entered_at REAL NOT NULL,
  entered_by INTEGER,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS director_disclosures(
  disclosure_id TEXT PRIMARY KEY,
  director_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  financial_year TEXT NOT NULL,
  form_type TEXT NOT NULL DEFAULT 'MBP_1',
  interest_details TEXT NOT NULL,
  is_verified INTEGER NOT NULL DEFAULT 1,
  submitted_at REAL NOT NULL,
  FOREIGN KEY (director_id) REFERENCES directors(director_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS compliance_calendar(
  item_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  authority TEXT NOT NULL,
  due_date TEXT NOT NULL,
  form_number TEXT DEFAULT '',
  recurrence TEXT NOT NULL DEFAULT 'ANNUAL',
  status TEXT NOT NULL DEFAULT 'UPCOMING',
  completed_at REAL,
  acknowledgement_ref TEXT DEFAULT '',
  assigned_to INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- 2. Company Treasury, Bank Accounts, Vendors & Assets
CREATE TABLE IF NOT EXISTS company_bank_accounts(
  account_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  bank_name TEXT NOT NULL,
  account_number_masked TEXT NOT NULL,
  ifsc_code TEXT NOT NULL,
  branch TEXT NOT NULL,
  account_type TEXT NOT NULL DEFAULT 'CURRENT',
  balance_paise INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'INR',
  is_primary INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_assets(
  asset_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  asset_tag TEXT NOT NULL UNIQUE,
  asset_name TEXT NOT NULL,
  category TEXT NOT NULL,
  purchase_date TEXT NOT NULL,
  cost_paise INTEGER NOT NULL,
  current_book_value_paise INTEGER NOT NULL,
  depreciation_rate_pct TEXT NOT NULL DEFAULT '15.00',
  location TEXT NOT NULL DEFAULT 'Bangalore HQ',
  status TEXT NOT NULL DEFAULT 'IN_USE',
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vendors(
  vendor_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  vendor_name TEXT NOT NULL,
  gstin TEXT DEFAULT '',
  pan TEXT DEFAULT '',
  contact_email TEXT DEFAULT '',
  contact_phone TEXT DEFAULT '',
  service_category TEXT NOT NULL,
  payment_terms TEXT NOT NULL DEFAULT 'NET_30',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS purchase_orders(
  po_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  po_number TEXT NOT NULL UNIQUE,
  vendor_id TEXT NOT NULL,
  description TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  tax_paise INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'APPROVED',
  issued_at REAL NOT NULL,
  created_by INTEGER,
  FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expense_records(
  expense_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  category TEXT NOT NULL,
  vendor_id TEXT DEFAULT '',
  description TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  tax_paise INTEGER NOT NULL DEFAULT 0,
  tds_paise INTEGER NOT NULL DEFAULT 0,
  payment_status TEXT NOT NULL DEFAULT 'PAID',
  paid_date TEXT NOT NULL,
  approval_ref TEXT DEFAULT '',
  created_by INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- 3. Departments, Employees, HR & Payroll
CREATE TABLE IF NOT EXISTS departments(
  dept_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  dept_code TEXT NOT NULL UNIQUE,
  dept_name TEXT NOT NULL,
  head_user_id INTEGER,
  budget_paise INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS employees(
  employee_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  emp_code TEXT NOT NULL UNIQUE,
  user_id INTEGER UNIQUE,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  phone TEXT NOT NULL,
  dept_id TEXT NOT NULL,
  designation TEXT NOT NULL,
  date_of_joining TEXT NOT NULL,
  ctc_annual_paise INTEGER NOT NULL,
  pan TEXT NOT NULL,
  uan TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (dept_id) REFERENCES departments(dept_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS payroll_records(
  payroll_id TEXT PRIMARY KEY,
  employee_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  month_year TEXT NOT NULL,
  gross_pay_paise INTEGER NOT NULL,
  basic_paise INTEGER NOT NULL,
  hra_paise INTEGER NOT NULL,
  special_allowance_paise INTEGER NOT NULL,
  pf_deduction_paise INTEGER NOT NULL DEFAULT 0,
  tds_deduction_paise INTEGER NOT NULL DEFAULT 0,
  prof_tax_paise INTEGER NOT NULL DEFAULT 20000,
  net_pay_paise INTEGER NOT NULL,
  payment_status TEXT NOT NULL DEFAULT 'PROCESSED',
  disbursed_at REAL,
  created_at REAL NOT NULL,
  UNIQUE(employee_id, month_year),
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS leave_requests(
  leave_id TEXT PRIMARY KEY,
  employee_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  leave_type TEXT NOT NULL DEFAULT 'PRIVILEGE',
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  days_count REAL NOT NULL DEFAULT 1.0,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'APPROVED',
  approved_by INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS internal_announcements(
  announcement_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'NORMAL',
  target_dept TEXT DEFAULT 'ALL',
  published_by INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_projects(
  project_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  project_code TEXT NOT NULL UNIQUE,
  project_name TEXT NOT NULL,
  description TEXT NOT NULL,
  lead_employee_id TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
  start_date TEXT NOT NULL,
  target_completion_date TEXT DEFAULT '',
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
"""

_MIGRATION_005_SQL = """
-- ============================================================================
-- ARAABOT MULTI-BROKER API CONNECTION CENTER SCHEMA (Migration 005)
-- Supports multiple accounts per broker, encrypted secrets, capabilities,
-- health monitoring, synchronization logs, and live trading safety checks.
-- ============================================================================

CREATE TABLE IF NOT EXISTS broker_providers(
  provider_code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  market_category TEXT NOT NULL, -- 'INDIAN_EQUITY', 'CRYPTO', 'FOREX'
  adapter_class TEXT NOT NULL,
  integration_status TEXT NOT NULL, -- 'OPERATIONAL_TESTED', 'ADAPTER_READY', 'PLANNED', 'DISABLED_AUTH_PENDING'
  auth_type TEXT NOT NULL, -- 'API_KEY_SECRET', 'OAUTH_KITE', 'HMAC_SHA256'
  docs_url TEXT NOT NULL DEFAULT '',
  ip_allowlist_required INTEGER NOT NULL DEFAULT 0,
  logo_svg TEXT DEFAULT '',
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_accounts(
  account_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  provider_code TEXT NOT NULL,
  account_name TEXT NOT NULL,
  broker_user_id TEXT DEFAULT '',
  account_profile_name TEXT DEFAULT '',
  market_category TEXT NOT NULL DEFAULT 'INDIAN_EQUITY',
  connection_status TEXT NOT NULL DEFAULT 'DISCONNECTED', -- 'DISCONNECTED', 'CONNECTED', 'REVOKED_OR_INVALID', 'SYNC_ERROR'
  live_trading_approved INTEGER NOT NULL DEFAULT 0,
  market_data_enabled INTEGER NOT NULL DEFAULT 1,
  paper_trading_enabled INTEGER NOT NULL DEFAULT 1,
  pool_id TEXT DEFAULT '',
  strategy_id TEXT DEFAULT '',
  risk_policy_id TEXT DEFAULT '',
  max_capital_paise INTEGER NOT NULL DEFAULT 5000000,
  max_daily_loss_paise INTEGER NOT NULL DEFAULT 500000,
  created_by INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  last_synced_at REAL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (provider_code) REFERENCES broker_providers(provider_code) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ba_co_prov ON broker_accounts(company_id, provider_code);

CREATE TABLE IF NOT EXISTS broker_account_credentials(
  account_id TEXT PRIMARY KEY,
  api_key_masked TEXT NOT NULL,
  api_key_enc TEXT NOT NULL,
  api_secret_enc TEXT NOT NULL,
  access_token_enc TEXT DEFAULT '',
  token_expiry_ts REAL,
  static_egress_ip TEXT DEFAULT '',
  whitelisted_ips_json TEXT NOT NULL DEFAULT '[]',
  withdrawal_disabled INTEGER NOT NULL DEFAULT 1,
  key_fingerprint TEXT NOT NULL,
  updated_by INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS broker_account_capabilities(
  account_id TEXT PRIMARY KEY,
  allowed_segments_json TEXT NOT NULL DEFAULT '["NSE_EQ"]',
  allowed_products_json TEXT NOT NULL DEFAULT '["CNC"]',
  order_types_json TEXT NOT NULL DEFAULT '["MARKET", "LIMIT"]',
  max_leverage_multiplier INTEGER NOT NULL DEFAULT 1,
  shorting_allowed INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS broker_account_balances(
  account_id TEXT PRIMARY KEY,
  currency TEXT NOT NULL DEFAULT 'INR',
  starting_capital_paise INTEGER NOT NULL DEFAULT 0,
  available_funds_paise INTEGER NOT NULL DEFAULT 0,
  used_margin_paise INTEGER NOT NULL DEFAULT 0,
  open_position_value_paise INTEGER NOT NULL DEFAULT 0,
  realized_pnl_paise INTEGER NOT NULL DEFAULT 0,
  unrealized_pnl_paise INTEGER NOT NULL DEFAULT 0,
  fees_paise INTEGER NOT NULL DEFAULT 0,
  account_equity_paise INTEGER NOT NULL DEFAULT 0,
  crypto_raw_json TEXT NOT NULL DEFAULT '{}',
  updated_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS broker_connection_logs(
  log_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  provider_code TEXT NOT NULL,
  event_type TEXT NOT NULL, -- 'CONNECT', 'DISCONNECT', 'TOKEN_REFRESH', 'VERIFY_FAIL', 'REVOKED'
  status TEXT NOT NULL, -- 'SUCCESS', 'FAILED', 'WARNING'
  message TEXT NOT NULL,
  ip_address TEXT DEFAULT '',
  created_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_bcl_acct ON broker_connection_logs(account_id, created_at);

CREATE TABLE IF NOT EXISTS broker_sync_logs(
  sync_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  sync_type TEXT NOT NULL, -- 'BALANCES', 'POSITIONS', 'ORDERS', 'FULL'
  status TEXT NOT NULL, -- 'SUCCESS', 'FAILED'
  latency_ms INTEGER NOT NULL DEFAULT 0,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_bsl_acct ON broker_sync_logs(account_id, created_at);

CREATE TABLE IF NOT EXISTS broker_health_events(
  event_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  provider_code TEXT NOT NULL,
  check_type TEXT NOT NULL, -- 'PING', 'AUTH_VALIDITY', 'RATE_LIMIT', 'BALANCE_CHECK'
  status TEXT NOT NULL, -- 'HEALTHY', 'DEGRADED', 'UNREACHABLE', 'EXPIRED'
  latency_ms INTEGER NOT NULL DEFAULT 0,
  error_message TEXT DEFAULT '',
  created_at REAL NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_bhe_acct ON broker_health_events(account_id, created_at);
"""

_MIGRATION_006_SQL = """
-- ============================================================================
-- ARAA CENTRALIZED SUPER ADMIN, SSO & APPLICATION REGISTRY (Migration 006)
-- Centralizes authentication, OpenID/SSO tokens, RBAC permissions, approval inboxes,
-- audit logs, and integration health across all 10 ARAA ecosystem applications.
-- ============================================================================

CREATE TABLE IF NOT EXISTS central_users(
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  phone TEXT DEFAULT '',
  department_id TEXT DEFAULT '',
  role_code TEXT NOT NULL DEFAULT 'EMPLOYEE',
  is_super_admin INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE', 'SUSPENDED', 'PENDING_MFA'
  pw_salt TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  mfa_enabled INTEGER NOT NULL DEFAULT 0,
  mfa_secret_enc TEXT DEFAULT '',
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0,
  approval_limit_paise INTEGER NOT NULL DEFAULT 0,
  access_expiry_ts REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  last_login_at REAL
);
CREATE INDEX IF NOT EXISTS ix_cu_role ON central_users(role_code, status);

CREATE TABLE IF NOT EXISTS application_registry(
  app_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  base_url TEXT NOT NULL,
  health_endpoint TEXT NOT NULL DEFAULT '/api/health',
  version TEXT NOT NULL DEFAULT '4.0.0',
  integration_status TEXT NOT NULL DEFAULT 'OPERATIONAL', -- 'OPERATIONAL', 'DEGRADED', 'OFFLINE'
  last_synced_at REAL,
  error_status TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS application_sessions(
  session_id TEXT PRIMARY KEY,
  sso_token TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL,
  app_id TEXT NOT NULL,
  ip_address TEXT DEFAULT '',
  user_agent TEXT DEFAULT '',
  is_revoked INTEGER NOT NULL DEFAULT 0,
  expires_at REAL NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY (user_id) REFERENCES central_users(user_id) ON DELETE CASCADE,
  FOREIGN KEY (app_id) REFERENCES application_registry(app_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_as_sso_tok ON application_sessions(sso_token);
CREATE INDEX IF NOT EXISTS ix_as_user ON application_sessions(user_id, is_revoked);

CREATE TABLE IF NOT EXISTS approval_requests(
  request_id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL,
  category TEXT NOT NULL, -- 'FINANCE', 'PAYROLL', 'PROCUREMENT', 'TRADING', 'BROKER', 'WALLET', 'COMPANY'
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  amount_paise INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'INR',
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'APPROVED', 'REJECTED'
  required_role TEXT NOT NULL DEFAULT 'SUPER_ADMIN',
  request_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (requested_by) REFERENCES central_users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ar_status ON approval_requests(status, category);

CREATE TABLE IF NOT EXISTS approval_actions(
  action_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  action TEXT NOT NULL, -- 'APPROVE', 'REJECT', 'REQUEST_CHANGES'
  actor_user_id TEXT NOT NULL,
  comments TEXT DEFAULT '',
  created_at REAL NOT NULL,
  FOREIGN KEY (request_id) REFERENCES approval_requests(request_id) ON DELETE CASCADE,
  FOREIGN KEY (actor_user_id) REFERENCES central_users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admin_audit_logs(
  log_id TEXT PRIMARY KEY,
  user_id TEXT DEFAULT '',
  user_email TEXT DEFAULT '',
  action TEXT NOT NULL,
  module TEXT NOT NULL,
  app_id TEXT DEFAULT '',
  resource_type TEXT DEFAULT '',
  resource_id TEXT DEFAULT '',
  before_json TEXT,
  after_json TEXT,
  status TEXT NOT NULL DEFAULT 'SUCCESS',
  ip_address TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_aal_act_at ON admin_audit_logs(action, created_at);

CREATE TABLE IF NOT EXISTS security_events(
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL, -- 'LOGIN_SUCCESS', 'LOGIN_FAILED', 'SUSPICIOUS_LOGIN', 'MFA_CHALLENGE', 'SESSION_REVOKED'
  severity TEXT NOT NULL DEFAULT 'INFO', -- 'INFO', 'WARNING', 'CRITICAL'
  user_id TEXT DEFAULT '',
  email TEXT DEFAULT '',
  ip_address TEXT DEFAULT '',
  user_agent TEXT DEFAULT '',
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_se_type_at ON security_events(event_type, created_at);

CREATE TABLE IF NOT EXISTS application_health(
  health_id TEXT PRIMARY KEY,
  app_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'HEALTHY',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  details_json TEXT NOT NULL DEFAULT '{}',
  checked_at REAL NOT NULL,
  FOREIGN KEY (app_id) REFERENCES application_registry(app_id) ON DELETE CASCADE
);
"""


MIGRATIONS: List[Tuple[str, str, str]] = [
    ("001", "company_rbac_mfa_and_audit", _MIGRATION_001_SQL),
    ("002", "company_finance_and_pools", _MIGRATION_002_SQL),
    ("003", "company_trading_oms_ledger_recon", _MIGRATION_003_SQL),
    ("004", "company_foundation_governance_hr_erp", _MIGRATION_004_SQL),
    ("005", "araabot_multi_broker_connection_center", _MIGRATION_005_SQL),
    ("006", "central_super_admin_sso_and_apps", _MIGRATION_006_SQL),
]


def _seed_company_governance() -> None:
    """Idempotently seeds the default ARAA company profile, 7 roles, and RBAC permission matrix."""
    now = time.time()
    existing_co = query_one("SELECT id FROM companies WHERE company_code=?", ("ARAA-PROP-01",))
    if not existing_co:
        write(
            "INSERT INTO companies(company_code, legal_name, cin_or_reg_no, pan, gstin, base_currency, "
            "proprietary_only, compliance_status, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, 'INR', 1, 'REVIEW_PENDING', ?, ?)",
            ("ARAA-PROP-01", "ARAA Proprietary Trading Pvt. Ltd.", "", "", "", now, now),
        )
        existing_co = query_one("SELECT id FROM companies WHERE company_code=?", ("ARAA-PROP-01",))

    co_id = existing_co["id"]

    # Seed the three strictly independent capital pools with 0 balance (never migrate demo funds)
    for pool_id, pool_name, scope, provider in (
        ("POOL_INDIA_INR", "India Equities Capital Pool (Zerodha)", "INDIA", "ZERODHA"),
        ("POOL_CRYPTO_SPOT", "Crypto Spot Capital Pool (CoinDCX)", "CRYPTO", "COINDCX"),
        ("POOL_CRYPTO_FUTURES", "Crypto Derivatives Capital Pool (CoinDCX Futures)", "CRYPTO_FUTURES", "COINDCX_FUTURES"),
    ):
        write(
            "INSERT OR IGNORE INTO company_capital_pools("
            "pool_id, company_id, pool_name, market_scope, provider, base_currency, updated_at"
            ") VALUES(?, ?, ?, ?, ?, 'INR', ?)",
            (pool_id, co_id, pool_name, scope, provider, now),
        )

    # Seed conservative independent risk policies per pool
    for pol_id, pool_id, win_en in (
        ("POL_INDIA_INR", "POOL_INDIA_INR", 0),
        ("POL_CRYPTO_SPOT", "POOL_CRYPTO_SPOT", 0),
        ("POL_CRYPTO_FUTURES", "POOL_CRYPTO_FUTURES", 0),
    ):
        write(
            "INSERT OR IGNORE INTO company_risk_policies("
            "policy_id, company_id, pool_id, trading_window_enabled, updated_at"
            ") VALUES(?, ?, ?, ?, ?)",
            (pol_id, co_id, pool_id, win_en, now),
        )

    # Seed compliance readiness review items (explicitly unverified until legal/CA sign-off)
    for rec_id, cat, title, auth, note in (
        ("COMP-CORP-01", "CORPORATE", "Company Incorporation, PAN & Board Resolution for Proprietary Desk", "MCA / Income Tax", "Required before onboarding institutional broker accounts"),
        ("COMP-ZERODHA-01", "BROKER_INDIA", "Zerodha Kite Connect Corporate App, Static IP & NSE/BSE Algo Approval", "Zerodha / NSE / BSE / SEBI", "Static egress IP & algo rules must be verified prior to live India activation"),
        ("COMP-COINDCX-01", "BROKER_CRYPTO", "CoinDCX Spot-Only Company Key (Withdrawals Disabled, IP Allowlist)", "CoinDCX / FIU-IND", "Verify VDA tax / 1% TDS / FIU-IND compliance obligations with CA/legal counsel"),
        ("COMP-SECURITY-01", "CYBERSECURITY", "SECRETS_KEY Encryption, TOTP MFA & Offsite Postgres Backup Drill", "ARAA Security Governance", "Enforce TOTP MFA on all operators and test database recovery"),
    ):
        write(
            "INSERT OR IGNORE INTO compliance_records("
            "record_id, company_id, category, title, authority, status, notes, updated_at"
            ") VALUES(?,?,?,?,?,'REQUIRES_REVIEW',?,?)",
            (rec_id, co_id, cat, title, auth, note, now),
        )

    for code, name, desc, level in ROLE_DEFINITIONS:
        write(
            "INSERT INTO roles(role_code, role_name, description, hierarchy_level, created_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(role_code) DO UPDATE SET role_name=excluded.role_name, "
            "description=excluded.description, hierarchy_level=excluded.hierarchy_level",
            (code, name, desc, level, now),
        )

    for perm_code, mod, desc in PERMISSION_DEFINITIONS:
        write(
            "INSERT INTO company_permissions(permission_code, module, description) VALUES(?, ?, ?) "
            "ON CONFLICT(permission_code) DO UPDATE SET module=excluded.module, description=excluded.description",
            (perm_code, mod, desc),
        )

    for role_code, perms in ROLE_PERMISSION_MAP.items():
        for perm_code in perms:
            write(
                "INSERT OR IGNORE INTO role_permissions(role_code, permission_code) VALUES(?, ?)",
                (role_code, perm_code),
            )




def run_migrations() -> List[Dict[str, Any]]:
    """Executes all pending versioned migrations inside SQLite transactions."""
    conn = connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            "version TEXT PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL, checksum TEXT NOT NULL)"
        )
        applied_rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        applied = {r["version"]: r["checksum"] for r in applied_rows}

        newly_applied: List[Dict[str, Any]] = []
        for version, name, sql_script in MIGRATIONS:
            checksum = hashlib.sha256(sql_script.encode("utf-8")).hexdigest()[:16]
            if version in applied:
                continue
            conn.executescript(sql_script)
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at, checksum) VALUES(?, ?, ?, ?)",
                (version, name, time.time(), checksum),
            )
            conn.commit()
            newly_applied.append({"version": version, "name": name, "checksum": checksum})
    finally:
        conn.close()

    _seed_company_governance()
    return newly_applied


def list_applied_migrations() -> List[Dict[str, Any]]:
    """Returns all applied schema migrations in chronological order."""
    return query("SELECT version, name, applied_at, checksum FROM schema_migrations ORDER BY version ASC")


# =============================================================================
# MIGRATION 007 — ARAA CORPORATE WEBSITE & OWNER SUPER ADMIN CMS
# =============================================================================
_MIGRATION_007_SQL = """
CREATE TABLE IF NOT EXISTS cms_theme_settings(
  setting_key TEXT PRIMARY KEY,
  setting_val TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'THEME',
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_pages(
  page_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  meta_title TEXT NOT NULL,
  meta_description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PUBLISHED',
  version INTEGER NOT NULL DEFAULT 1,
  published_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_sections(
  section_id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL,
  section_key TEXT NOT NULL,
  section_title TEXT NOT NULL,
  content_json TEXT NOT NULL,
  order_index INTEGER NOT NULL DEFAULT 0,
  is_visible INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (page_id) REFERENCES cms_pages(page_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_menus(
  menu_id TEXT PRIMARY KEY,
  menu_location TEXT NOT NULL,
  label TEXT NOT NULL,
  url TEXT NOT NULL,
  order_index INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cms_news(
  article_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  summary TEXT NOT NULL,
  body TEXT NOT NULL,
  author TEXT NOT NULL,
  published_date TEXT NOT NULL,
  is_published INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_careers(
  job_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  department TEXT NOT NULL,
  location TEXT NOT NULL,
  employment_type TEXT NOT NULL DEFAULT 'FULL_TIME',
  experience_level TEXT NOT NULL,
  description TEXT NOT NULL,
  requirements TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_contact_enquiries(
  enquiry_id TEXT PRIMARY KEY,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT,
  subject TEXT NOT NULL,
  message TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'GENERAL',
  ip_address TEXT,
  status TEXT NOT NULL DEFAULT 'NEW',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_page_versions(
  version_id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  content_snapshot_json TEXT NOT NULL,
  saved_by TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY (page_id) REFERENCES cms_pages(page_id) ON DELETE CASCADE
);
"""

MIGRATIONS.append(("007", "corporate_website_and_owner_cms", _MIGRATION_007_SQL))

# =============================================================================
# MIGRATION 008 — COMPANY FINANCE & CORPORATE DOUBLE-ENTRY ACCOUNTING
# =============================================================================
_MIGRATION_008_SQL = """
CREATE TABLE IF NOT EXISTS chart_of_accounts(
  account_code TEXT PRIMARY KEY,
  account_name TEXT NOT NULL,
  account_type TEXT NOT NULL, -- ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
  currency TEXT NOT NULL DEFAULT 'INR',
  parent_code TEXT DEFAULT '',
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS general_ledger_journals(
  journal_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  journal_number TEXT NOT NULL UNIQUE,
  posting_date TEXT NOT NULL,
  period_key TEXT NOT NULL,
  narrative TEXT NOT NULL,
  source_document_ref TEXT DEFAULT '',
  posted_by TEXT NOT NULL,
  is_posted INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS general_ledger_entries(
  entry_id TEXT PRIMARY KEY,
  journal_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  account_code TEXT NOT NULL,
  debit_paise INTEGER NOT NULL DEFAULT 0,
  credit_paise INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'INR',
  created_at REAL NOT NULL,
  FOREIGN KEY (journal_id) REFERENCES general_ledger_journals(journal_id) ON DELETE CASCADE,
  FOREIGN KEY (account_code) REFERENCES chart_of_accounts(account_code)
);

CREATE TABLE IF NOT EXISTS vendor_invoices(
  invoice_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  vendor_id TEXT NOT NULL,
  invoice_number TEXT NOT NULL,
  invoice_date TEXT NOT NULL,
  due_date TEXT NOT NULL,
  subtotal_paise INTEGER NOT NULL,
  gst_paise INTEGER NOT NULL DEFAULT 0,
  tds_paise INTEGER NOT NULL DEFAULT 0,
  total_paise INTEGER NOT NULL,
  payment_status TEXT NOT NULL DEFAULT 'UNPAID', -- UNPAID, PARTIAL, PAID
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tax_compliance_filings(
  filing_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  tax_type TEXT NOT NULL, -- GST_GSTR1, GST_GSTR3B, TDS_26Q, ADVANCE_TAX, INCOME_TAX
  financial_year TEXT NOT NULL,
  period TEXT NOT NULL,
  due_date TEXT NOT NULL,
  filing_date TEXT DEFAULT '',
  acknowledgment_no TEXT DEFAULT '',
  tax_paid_paise INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
"""

MIGRATIONS.append(("008", "company_finance_and_corporate_accounting", _MIGRATION_008_SQL))

# =============================================================================
# MIGRATION 009 — ARAA BROKERAGE ARCHITECTURE (PROP + GATED CUSTOMER)
# =============================================================================
_MIGRATION_009_SQL = """
CREATE TABLE IF NOT EXISTS brokerage_products(
  product_code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  exchange TEXT NOT NULL, -- NSE, BSE, MCX, COINDCX
  asset_class TEXT NOT NULL, -- EQUITY_CASH, EQUITY_DERIVATIVE, COMMODITY, CRYPTO_SPOT
  brokerage_mode TEXT NOT NULL DEFAULT 'PROP_ONLY', -- PROP_ONLY, CUSTOMER_RETAIL
  is_trading_enabled INTEGER NOT NULL DEFAULT 1,
  margin_multiplier REAL NOT NULL DEFAULT 1.0,
  stt_tax_bps REAL NOT NULL DEFAULT 10.0,
  sebi_turnover_bps REAL NOT NULL DEFAULT 0.1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_brokerage_accounts(
  customer_account_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  pan_masked TEXT NOT NULL,
  kyc_status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, VERIFIED, REJECTED
  aml_risk_score REAL NOT NULL DEFAULT 0.0,
  margin_trading_authorized INTEGER NOT NULL DEFAULT 0,
  account_status TEXT NOT NULL DEFAULT 'SUSPENDED_PENDING_REGULATORY_LICENSE',
  opened_at REAL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS service_authorization_register(
  service_code TEXT PRIMARY KEY,
  service_name TEXT NOT NULL,
  division TEXT NOT NULL,
  is_authorized INTEGER NOT NULL DEFAULT 0, -- STRICT LEGAL GATE
  regulatory_license_ref TEXT DEFAULT '',
  legal_signoff_by TEXT DEFAULT '',
  authorized_at REAL,
  reason_for_gate TEXT NOT NULL,
  updated_at REAL NOT NULL
);
"""

MIGRATIONS.append(("009", "araa_brokerage_architecture_and_gates", _MIGRATION_009_SQL))

# =============================================================================
# MIGRATION 010 — ARAA WALLET INFRASTRUCTURE & 11-STATE IMMUTABLE LEDGER
# =============================================================================
_MIGRATION_010_SQL = """
CREATE TABLE IF NOT EXISTS company_treasury_vaults(
  vault_id TEXT PRIMARY KEY,
  vault_name TEXT NOT NULL,
  vault_type TEXT NOT NULL, -- FIAT_INR, CRYPTO_COLD_MPC, CRYPTO_WARM_OPERATIONAL
  currency TEXT NOT NULL, -- INR, USDT, BTC, ETH
  balance_paise INTEGER NOT NULL DEFAULT 0,
  crypto_balance_atomic TEXT NOT NULL DEFAULT '0',
  multisig_threshold TEXT NOT NULL DEFAULT '2-of-3',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_deposit_addresses(
  address_id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  blockchain_network TEXT NOT NULL, -- TRON_TRC20, ETH_ERC20, BSC_BEP20, BTC_MAINNET
  public_address TEXT NOT NULL UNIQUE,
  derivation_index INTEGER NOT NULL,
  is_whitelisted INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  FOREIGN KEY (vault_id) REFERENCES company_treasury_vaults(vault_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wallet_immutable_ledger(
  entry_id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL,
  transaction_ref TEXT NOT NULL UNIQUE,
  currency TEXT NOT NULL,
  entry_type TEXT NOT NULL, -- DEPOSIT, WITHDRAWAL, INTERNAL_SWAP, BROKER_ALLOCATION, FEE_DEDUCTION
  state TEXT NOT NULL, -- CREATED, PENDING_APPROVAL, SIGNED, BROADCAST, CONFIRMED, COMPLETED, REJECTED, EXPIRED, FAILED, REFUNDED, RECONCILED
  amount_paise INTEGER NOT NULL DEFAULT 0,
  crypto_amount TEXT NOT NULL DEFAULT '0',
  blockchain_txid TEXT DEFAULT '',
  confirmation_count INTEGER NOT NULL DEFAULT 0,
  authorized_by TEXT NOT NULL,
  signoff_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (vault_id) REFERENCES company_treasury_vaults(vault_id) ON DELETE CASCADE
);
"""

MIGRATIONS.append(("010", "araa_wallet_infrastructure_and_ledger", _MIGRATION_010_SQL))

# =============================================================================
# MIGRATION 011 — ENTERPRISE QA AUTOMATION FRAMEWORK (TESTING & QUALITY CENTER)
# =============================================================================
_MIGRATION_011_SQL = """
CREATE TABLE IF NOT EXISTS qa_test_suites(
  suite_id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  module_path TEXT NOT NULL DEFAULT '',
  is_enabled INTEGER NOT NULL DEFAULT 1,
  is_safe_live INTEGER NOT NULL DEFAULT 1,
  requires_isolated_db INTEGER NOT NULL DEFAULT 1,
  default_timeout_sec INTEGER NOT NULL DEFAULT 60,
  sort_order INTEGER NOT NULL DEFAULT 100,
  created_by TEXT NOT NULL DEFAULT 'SYSTEM',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_qa_suites_cat ON qa_test_suites(category, sort_order);

CREATE TABLE IF NOT EXISTS qa_test_cases(
  case_id TEXT PRIMARY KEY,
  suite_id TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'High',
  test_type TEXT NOT NULL DEFAULT 'AUTOMATED',
  target_ref TEXT NOT NULL DEFAULT '',
  expected_behavior TEXT NOT NULL DEFAULT '',
  is_enabled INTEGER NOT NULL DEFAULT 1,
  is_destructive_isolated INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT 'SYSTEM',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (suite_id) REFERENCES qa_test_suites(suite_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_qa_cases_suite ON qa_test_cases(suite_id, is_enabled);

CREATE TABLE IF NOT EXISTS qa_test_runs(
  run_id TEXT PRIMARY KEY,
  trigger_type TEXT NOT NULL DEFAULT 'MANUAL',
  environment TEXT NOT NULL DEFAULT 'ISOLATED_STAGING',
  status TEXT NOT NULL DEFAULT 'QUEUED',
  suite_filter_json TEXT NOT NULL DEFAULT '[]',
  case_filter_json TEXT NOT NULL DEFAULT '[]',
  total_cases INTEGER NOT NULL DEFAULT 0,
  passed_cases INTEGER NOT NULL DEFAULT 0,
  failed_cases INTEGER NOT NULL DEFAULT 0,
  blocked_cases INTEGER NOT NULL DEFAULT 0,
  skipped_cases INTEGER NOT NULL DEFAULT 0,
  pending_cases INTEGER NOT NULL DEFAULT 0,
  pass_rate_pct REAL NOT NULL DEFAULT 0.0,
  duration_ms REAL NOT NULL DEFAULT 0.0,
  deployment_readiness TEXT NOT NULL DEFAULT 'PENDING',
  summary_json TEXT NOT NULL DEFAULT '{}',
  triggered_by TEXT NOT NULL DEFAULT 'admin',
  started_at REAL,
  finished_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_qa_runs_status ON qa_test_runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_qa_runs_trigger ON qa_test_runs(trigger_type, created_at DESC);

CREATE TABLE IF NOT EXISTS qa_test_results(
  result_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  suite_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_name TEXT NOT NULL,
  module TEXT NOT NULL DEFAULT '',
  environment TEXT NOT NULL DEFAULT 'ISOLATED_STAGING',
  status TEXT NOT NULL DEFAULT 'QUEUED',
  severity TEXT NOT NULL DEFAULT 'High',
  attempt_num INTEGER NOT NULL DEFAULT 1,
  started_at REAL,
  finished_at REAL,
  duration_ms REAL NOT NULL DEFAULT 0.0,
  expected_result TEXT NOT NULL DEFAULT '',
  actual_result TEXT NOT NULL DEFAULT '',
  error_message TEXT NOT NULL DEFAULT '',
  stack_trace TEXT NOT NULL DEFAULT '',
  api_response_sanitized TEXT NOT NULL DEFAULT '',
  defect_id TEXT DEFAULT '',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  FOREIGN KEY (run_id) REFERENCES qa_test_runs(run_id) ON DELETE CASCADE,
  FOREIGN KEY (suite_id) REFERENCES qa_test_suites(suite_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_qa_results_run ON qa_test_results(run_id, status);
CREATE INDEX IF NOT EXISTS ix_qa_results_case ON qa_test_results(case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS qa_test_logs(
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  result_id TEXT DEFAULT '',
  level TEXT NOT NULL DEFAULT 'INFO',
  source TEXT NOT NULL DEFAULT 'QA_RUNNER',
  message TEXT NOT NULL,
  logged_at REAL NOT NULL,
  FOREIGN KEY (run_id) REFERENCES qa_test_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_qa_logs_run ON qa_test_logs(run_id, log_id);

CREATE TABLE IF NOT EXISTS qa_test_artifacts(
  artifact_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  result_id TEXT DEFAULT '',
  artifact_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
  size_bytes INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT 'QA_RUNNER',
  created_at REAL NOT NULL,
  FOREIGN KEY (run_id) REFERENCES qa_test_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_qa_artifacts_run ON qa_test_artifacts(run_id, artifact_type);

CREATE TABLE IF NOT EXISTS qa_defects(
  defect_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  module TEXT NOT NULL DEFAULT '',
  run_id TEXT DEFAULT '',
  case_id TEXT DEFAULT '',
  result_id TEXT DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'High',
  priority TEXT NOT NULL DEFAULT 'P1',
  status TEXT NOT NULL DEFAULT 'Open',
  assigned_admin TEXT NOT NULL DEFAULT 'UNASSIGNED',
  evidence TEXT NOT NULL DEFAULT '',
  screenshot_artifact_id TEXT DEFAULT '',
  root_cause TEXT NOT NULL DEFAULT '',
  resolution_notes TEXT NOT NULL DEFAULT '',
  retest_run_id TEXT DEFAULT '',
  retest_passed INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT 'QA_RUNNER',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  resolved_at REAL
);
CREATE INDEX IF NOT EXISTS ix_qa_defects_status ON qa_defects(status, severity, created_at DESC);

CREATE TABLE IF NOT EXISTS qa_test_config(
  config_key TEXT PRIMARY KEY,
  config_value TEXT NOT NULL,
  value_type TEXT NOT NULL DEFAULT 'string',
  description TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL DEFAULT 'SYSTEM',
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS qa_test_schedules(
  schedule_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  suite_ids_json TEXT NOT NULL DEFAULT '[]',
  trigger_mode TEXT NOT NULL DEFAULT 'INTERVAL',
  interval_minutes INTEGER NOT NULL DEFAULT 60,
  is_enabled INTEGER NOT NULL DEFAULT 0,
  last_run_id TEXT DEFAULT '',
  last_run_at REAL,
  next_run_at REAL,
  created_by TEXT NOT NULL DEFAULT 'admin',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_qa_sched_enabled ON qa_test_schedules(is_enabled, next_run_at);
"""

MIGRATIONS.append(("011", "qa_automation_framework", _MIGRATION_011_SQL))
