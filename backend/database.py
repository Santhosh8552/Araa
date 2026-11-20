"""SQLite persistence for Trade Pro. Azure-ready: set DATABASE_URL/DB_PATH env to relocate."""
import os, sqlite3, threading, secrets, hashlib, time, random, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(BASE, "tradepro.db")
# Azure SQL / Postgres would be used through the same helper surface; see README note in app.py
DATABASE_URL = os.environ.get("DATABASE_URL", "")

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pw_salt TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_login_at REAL,
  bot_enabled INTEGER NOT NULL DEFAULT 0,
  bot_max_positions INTEGER NOT NULL DEFAULT 10,
  bot_risk_pct REAL NOT NULL DEFAULT 2.0,
  bot_mode TEXT NOT NULL DEFAULT 'SCALP',
  bot_leverage REAL DEFAULT 100.0,
  bot_activated_at REAL DEFAULT 0,
  bot_market_focus TEXT DEFAULT 'FUTURES_USD',
  bot_trade_direction TEXT DEFAULT 'BOTH',
  theme_preference TEXT DEFAULT 'dark'
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS revoked_sessions(
  token TEXT PRIMARY KEY,
  revoked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wallets(
  user_id INTEGER PRIMARY KEY,
  deposit_balance REAL NOT NULL DEFAULT 0,
  profit_balance REAL NOT NULL DEFAULT 0,
  total_deposited REAL NOT NULL DEFAULT 0,
  total_withdrawn REAL NOT NULL DEFAULT 0,
  total_brokerage REAL NOT NULL DEFAULT 0,
  locked_balance REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS instruments(
  symbol TEXT PRIMARY KEY,
  base TEXT NOT NULL,
  quote TEXT NOT NULL,
  display_name TEXT,
  tick_size REAL NOT NULL DEFAULT 0.0001,
  category TEXT NOT NULL DEFAULT 'CRYPTO',
  source TEXT NOT NULL DEFAULT 'BINANCE',
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  source TEXT NOT NULL,
  side TEXT NOT NULL,
  qty REAL NOT NULL,
  entry_price REAL NOT NULL,
  margin REAL NOT NULL,
  target_pct REAL NOT NULL,
  stop_pct REAL NOT NULL,
  status TEXT NOT NULL,
  current_price REAL NOT NULL,
  unrealized_pnl REAL NOT NULL DEFAULT 0,
  opened_at REAL NOT NULL,
  closed_at REAL,
  realized_pnl REAL NOT NULL DEFAULT 0,
  close_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_pos_user ON positions(user_id, status);
CREATE TABLE IF NOT EXISTS bot_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL NOT NULL,
  user_id INTEGER,
  level TEXT NOT NULL,
  message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  kind TEXT NOT NULL,
  asset TEXT NOT NULL DEFAULT 'USD',
  gross REAL NOT NULL,
  brokerage REAL NOT NULL DEFAULT 0,
  net REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  note TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deposits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  method TEXT NOT NULL,
  asset TEXT NOT NULL DEFAULT 'USD',
  amount REAL NOT NULL,
  credited REAL NOT NULL,
  ref TEXT NOT NULL,
  status TEXT NOT NULL,
  bank_name TEXT,
  account_number TEXT,
  ifsc_code TEXT,
  account_holder TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS withdrawals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  brokerage REAL NOT NULL,
  net_payable REAL NOT NULL,
  method TEXT NOT NULL,
  status TEXT NOT NULL,
  bank_name TEXT,
  account_number TEXT,
  ifsc_code TEXT,
  account_holder TEXT,
  created_at REAL NOT NULL,
  resolved_at REAL,
  payout_ref TEXT
);
CREATE TABLE IF NOT EXISTS user_bank_accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  bank_name TEXT NOT NULL,
  account_holder TEXT NOT NULL,
  account_number TEXT NOT NULL,
  ifsc_code TEXT NOT NULL,
  upi_id TEXT,
  is_default INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profit_links(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  gross REAL NOT NULL,
  brokerage REAL NOT NULL,
  net REAL NOT NULL,
  reason TEXT,
  status TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS brokerage_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL NOT NULL,
  source TEXT NOT NULL,
  ref TEXT,
  user_id INTEGER,
  amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_state(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty REAL NOT NULL,
  price REAL NOT NULL,
  margin REAL NOT NULL,
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  filled_at REAL,
  position_id INTEGER,
  leverage REAL DEFAULT 10.0,
  target_pct REAL DEFAULT 0.0,
  stop_pct REAL DEFAULT 0.0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS ai_predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  category TEXT NOT NULL,
  direction TEXT NOT NULL,
  action TEXT NOT NULL,
  entry_price REAL NOT NULL,
  target_price REAL NOT NULL,
  stop_price REAL NOT NULL,
  target_pct REAL NOT NULL,
  stop_pct REAL NOT NULL,
  risk_reward REAL NOT NULL,
  win_probability INTEGER NOT NULL,
  confidence REAL NOT NULL,
  rationale TEXT NOT NULL,
  mode TEXT NOT NULL,
  post_entry_status TEXT DEFAULT 'MONITORING',
  post_entry_notes TEXT,
  outcome TEXT DEFAULT 'PENDING',
  realized_pnl REAL DEFAULT 0,
  created_at REAL NOT NULL,
  closed_at REAL,
  position_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_pred_user ON ai_predictions(user_id, outcome);

CREATE TABLE IF NOT EXISTS demat_applications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider_id TEXT NOT NULL,
  provider_name TEXT NOT NULL,
  market_segment TEXT NOT NULL DEFAULT 'EQUITY_DERIVATIVES',
  pan_number TEXT,
  aadhaar_last4 TEXT,
  full_name TEXT,
  email TEXT,
  phone TEXT,
  bank_name TEXT,
  bank_account_mask TEXT,
  ifsc_code TEXT,
  annual_income TEXT,
  trading_experience TEXT,
  depository TEXT DEFAULT 'CDSL',
  application_ref TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'NOT_STARTED',
  action_required_desc TEXT,
  kyc_verified_at REAL,
  approved_at REAL,
  rejected_at REAL,
  rejection_reason TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_demat_app_user ON demat_applications(user_id);

CREATE TABLE IF NOT EXISTS broker_connections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  broker_name TEXT NOT NULL,
  api_key_masked TEXT,
  live_balance REAL DEFAULT 0.0,
  live_equity REAL DEFAULT 0.0,
  status TEXT DEFAULT 'DISCONNECTED',
  is_live_active INTEGER DEFAULT 0,
  connected_at REAL NOT NULL,
  last_synced_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_broker_conn_user ON broker_connections(user_id);

CREATE TABLE IF NOT EXISTS broker_provider_consents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider_id TEXT NOT NULL,
  market_segment TEXT NOT NULL,
  real_money_risk_acknowledged INTEGER DEFAULT 0,
  power_of_attorney_acknowledged INTEGER DEFAULT 0,
  automated_algo_execution_consent INTEGER DEFAULT 0,
  loss_liability_acknowledged INTEGER DEFAULT 0,
  ip_address TEXT,
  user_agent TEXT,
  consented_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS real_bot_configs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  provider_id TEXT NOT NULL,
  broker_account_id TEXT,
  market_segments TEXT NOT NULL DEFAULT 'CRYPTO,METALS,FOREX,INDIAN_EQUITY',
  strategy_mode TEXT NOT NULL DEFAULT 'PURE_CRYPTO',
  max_order_size REAL NOT NULL DEFAULT 50000.0,
  max_daily_loss REAL NOT NULL DEFAULT 15000.0,
  max_exposure_limit REAL NOT NULL DEFAULT 200000.0,
  max_leverage REAL NOT NULL DEFAULT 500.0,
  stop_loss_pct REAL NOT NULL DEFAULT 1.5,
  take_profit_pct REAL NOT NULL DEFAULT 3.0,
  trailing_stop_enabled INTEGER DEFAULT 1,
  execution_speed TEXT DEFAULT 'HIGH_VELOCITY',
  bot_status TEXT NOT NULL DEFAULT 'PAUSED',
  emergency_shutdown INTEGER DEFAULT 0,
  verified_funds REAL DEFAULT 0.0,
  verified_margin REAL DEFAULT 0.0,
  last_risk_audit_at REAL,
  max_positions INTEGER DEFAULT 20,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS real_bot_audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'INFO',
  message TEXT NOT NULL,
  details_json TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mt4_pairing_tokens(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  brand_id TEXT NOT NULL DEFAULT 'ARAA',
  account_login TEXT,
  expected_server TEXT,
  account_type TEXT NOT NULL DEFAULT 'DEMO',
  token_hash TEXT UNIQUE NOT NULL,
  token_preview TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  expires_at REAL NOT NULL,
  used_at REAL,
  terminal_id TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mt4_pair_user ON mt4_pairing_tokens(user_id, status);

CREATE TABLE IF NOT EXISTS mt4_terminals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  terminal_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  brand_id TEXT NOT NULL DEFAULT 'ARAA',
  account_login TEXT NOT NULL,
  server TEXT NOT NULL,
  account_type TEXT NOT NULL DEFAULT 'DEMO',
  currency TEXT NOT NULL DEFAULT 'USD',
  balance REAL NOT NULL DEFAULT 0.0,
  equity REAL NOT NULL DEFAULT 0.0,
  free_margin REAL NOT NULL DEFAULT 0.0,
  margin REAL NOT NULL DEFAULT 0.0,
  margin_level REAL NOT NULL DEFAULT 0.0,
  leverage REAL NOT NULL DEFAULT 500.0,
  open_positions_count INTEGER NOT NULL DEFAULT 0,
  trading_allowed INTEGER NOT NULL DEFAULT 0,
  expert_enabled INTEGER NOT NULL DEFAULT 0,
  connection_status TEXT NOT NULL DEFAULT 'DISCONNECTED',
  live_trading_approved INTEGER NOT NULL DEFAULT 0,
  live_trading_enabled INTEGER NOT NULL DEFAULT 0,
  market_focus TEXT NOT NULL DEFAULT 'ALL',
  trading_mode TEXT NOT NULL DEFAULT 'SCALP',
  session_token_hash TEXT NOT NULL,
  last_heartbeat_at REAL,
  last_sync_at REAL,
  last_error TEXT,
  positions_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mt4_term_user ON mt4_terminals(user_id, account_login);

CREATE TABLE IF NOT EXISTS mt4_commands(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  command_id TEXT UNIQUE NOT NULL,
  nonce TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  brand_id TEXT NOT NULL DEFAULT 'ARAA',
  terminal_id TEXT NOT NULL,
  account_login TEXT NOT NULL,
  action TEXT NOT NULL,
  symbol TEXT,
  side TEXT,
  lots REAL DEFAULT 0.0,
  price REAL DEFAULT 0.0,
  sl REAL DEFAULT 0.0,
  tp REAL DEFAULT 0.0,
  magic INTEGER DEFAULT 888801,
  status TEXT NOT NULL DEFAULT 'QUEUED',
  mt4_ticket INTEGER,
  executed_price REAL,
  realized_pnl REAL,
  error_code INTEGER,
  error_message TEXT,
  position_id INTEGER,
  created_at REAL NOT NULL,
  sent_at REAL,
  executed_at REAL
);
CREATE INDEX IF NOT EXISTS ix_mt4_cmd_term ON mt4_commands(terminal_id, status);
CREATE INDEX IF NOT EXISTS ix_mt4_cmd_acc ON mt4_commands(account_login, status);

-- =====================================================================
-- ARAABOT V3 INSTITUTIONAL & SAAS TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS subscription_plans(
  plan_code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  monthly_price_usd REAL NOT NULL,
  annual_price_usd REAL NOT NULL,
  monthly_price_inr REAL NOT NULL,
  annual_price_inr REAL NOT NULL,
  max_open_positions INTEGER NOT NULL,
  max_leverage REAL NOT NULL,
  allow_live_trading INTEGER NOT NULL DEFAULT 0,
  allow_ai_committee INTEGER NOT NULL DEFAULT 0,
  allow_backtesting INTEGER NOT NULL DEFAULT 1,
  allow_whitelabel INTEGER NOT NULL DEFAULT 0,
  features_json TEXT NOT NULL DEFAULT '[]',
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  plan_code TEXT NOT NULL DEFAULT 'STARTER',
  billing_cycle TEXT NOT NULL DEFAULT 'MONTHLY',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  trial_ends_at REAL,
  current_period_start REAL NOT NULL,
  current_period_end REAL NOT NULL,
  auto_renew INTEGER NOT NULL DEFAULT 1,
  payment_provider TEXT DEFAULT 'RAZORPAY_UPI',
  external_sub_id TEXT,
  cancelled_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_user_subs_uid ON user_subscriptions(user_id, status);

CREATE TABLE IF NOT EXISTS subscription_invoices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  plan_code TEXT NOT NULL,
  billing_cycle TEXT NOT NULL,
  amount_usd REAL NOT NULL,
  amount_inr REAL NOT NULL,
  tax_gst_inr REAL NOT NULL DEFAULT 0.0,
  currency TEXT NOT NULL DEFAULT 'INR',
  payment_method TEXT NOT NULL DEFAULT 'UPI',
  payment_ref TEXT,
  provider_order_id TEXT,
  provider_payment_id TEXT,
  provider_signature TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',
  paid_at REAL,
  refunded_at REAL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sub_inv_user ON subscription_invoices(user_id, status);

CREATE TABLE IF NOT EXISTS user_security_tokens(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  token_type TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  otp_code TEXT,
  expires_at REAL NOT NULL,
  used_at REAL,
  ip_address TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_tok_user ON user_security_tokens(user_id, token_type);

CREATE TABLE IF NOT EXISTS ai_committee_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '1m',
  alpha_score REAL NOT NULL,
  alpha_verdict TEXT NOT NULL,
  alpha_metrics_json TEXT NOT NULL,
  beta_score REAL NOT NULL,
  beta_verdict TEXT NOT NULL,
  beta_indicators_json TEXT NOT NULL,
  gamma_score REAL NOT NULL,
  gamma_verdict TEXT NOT NULL,
  gamma_risk_json TEXT NOT NULL,
  consensus_score REAL NOT NULL,
  final_action TEXT NOT NULL,
  direction TEXT NOT NULL,
  entry_price REAL NOT NULL,
  stop_loss REAL NOT NULL,
  take_profit REAL NOT NULL,
  risk_reward REAL NOT NULL,
  explainable_rationale TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_comm_sym ON ai_committee_logs(symbol, created_at);

CREATE TABLE IF NOT EXISTS backtest_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  strategy_mode TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  start_ts REAL NOT NULL,
  end_ts REAL NOT NULL,
  initial_capital REAL NOT NULL,
  final_equity REAL NOT NULL,
  total_return_pct REAL NOT NULL,
  max_drawdown_pct REAL NOT NULL,
  win_rate_pct REAL NOT NULL,
  profit_factor REAL NOT NULL,
  sharpe_ratio REAL NOT NULL,
  total_trades INTEGER NOT NULL,
  winning_trades INTEGER NOT NULL,
  losing_trades INTEGER NOT NULL,
  total_fees_usd REAL NOT NULL,
  total_slippage_usd REAL NOT NULL,
  total_funding_usd REAL NOT NULL,
  equity_curve_json TEXT NOT NULL,
  trades_json TEXT NOT NULL,
  passed_validation INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bt_user ON backtest_runs(user_id, created_at);

CREATE TABLE IF NOT EXISTS order_audit_lifecycle(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_uuid TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  position_id INTEGER,
  exchange TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL DEFAULT 'MARKET',
  requested_qty REAL NOT NULL,
  filled_qty REAL NOT NULL DEFAULT 0.0,
  requested_price REAL NOT NULL,
  filled_price REAL NOT NULL DEFAULT 0.0,
  leverage REAL NOT NULL DEFAULT 1.0,
  margin_allocated REAL NOT NULL DEFAULT 0.0,
  fee_usd REAL NOT NULL DEFAULT 0.0,
  slippage_bps REAL NOT NULL DEFAULT 0.0,
  funding_fee_usd REAL NOT NULL DEFAULT 0.0,
  liquidation_price REAL DEFAULT 0.0,
  stop_loss REAL,
  take_profit REAL,
  lifecycle_state TEXT NOT NULL,
  exchange_order_id TEXT,
  broker_confirmed INTEGER NOT NULL DEFAULT 0,
  raw_response_json TEXT,
  error_reason TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ord_life_user ON order_audit_lifecycle(user_id, lifecycle_state);

CREATE TABLE IF NOT EXISTS support_tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_ref TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  subject TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'TECHNICAL',
  priority TEXT NOT NULL DEFAULT 'NORMAL',
  status TEXT NOT NULL DEFAULT 'OPEN',
  message TEXT NOT NULL,
  admin_reply TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS security_audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  actor_role TEXT NOT NULL DEFAULT 'USER',
  action TEXT NOT NULL,
  resource TEXT,
  ip_address TEXT,
  user_agent TEXT,
  status TEXT NOT NULL DEFAULT 'SUCCESS',
  details_json TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_audit_at ON security_audit_logs(created_at);

-- =====================================================================
-- ARAABOT V3 ENTERPRISE ECOSYSTEM EXTENSIONS (PARTS 1-28)
-- =====================================================================

CREATE TABLE IF NOT EXISTS user_profiles(
  user_id INTEGER PRIMARY KEY,
  phone TEXT,
  country TEXT DEFAULT 'IN',
  city TEXT,
  timezone TEXT DEFAULT 'Asia/Kolkata',
  avatar_url TEXT,
  bio TEXT,
  trading_experience TEXT DEFAULT 'INTERMEDIATE',
  preferred_currency TEXT DEFAULT 'USDT',
  risk_tolerance TEXT DEFAULT 'MODERATE',
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'CUSTOMER', -- SUPER_ADMIN, OPERATIONS_ADMIN, FINANCE_ADMIN, RISK_MANAGER, SUPPORT_ADMIN, COMPLIANCE_OFFICER, AUDITOR, CUSTOMER
  granted_by INTEGER,
  granted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_user_roles_uid ON user_roles(user_id, role);

CREATE TABLE IF NOT EXISTS permissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  permission TEXT NOT NULL,
  module TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kyc_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'UNVERIFIED', -- UNVERIFIED, SUBMITTED, IN_REVIEW, VERIFIED, REJECTED
  pan_number TEXT,
  aadhaar_mask TEXT,
  full_name TEXT,
  dob TEXT,
  address_json TEXT,
  id_document_url TEXT,
  risk_rating TEXT DEFAULT 'LOW',
  verified_by INTEGER,
  verified_at REAL,
  rejection_reason TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kyc_user ON kyc_records(user_id, status);

CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_uuid TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  purpose TEXT NOT NULL, -- SUBSCRIPTION, DEPOSIT, WALLET_TOPUP
  amount REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'INR',
  provider TEXT NOT NULL, -- RAZORPAY, UPI, STRIPE
  provider_order_id TEXT,
  provider_payment_id TEXT,
  provider_signature TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, COMPLETED, FAILED, REFUNDED
  metadata_json TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_payments_uid ON payments(user_id, status);

CREATE TABLE IF NOT EXISTS ledger_accounts(
  account_code TEXT PRIMARY KEY,
  account_name TEXT NOT NULL,
  account_type TEXT NOT NULL, -- ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
  currency TEXT NOT NULL DEFAULT 'USD',
  balance REAL NOT NULL DEFAULT 0.0,
  description TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_uuid TEXT UNIQUE NOT NULL,
  transaction_ref TEXT NOT NULL,
  debit_account TEXT NOT NULL,
  credit_account TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  user_id INTEGER,
  correlation_id TEXT,
  narration TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'POSTED',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_accounts ON ledger_entries(debit_account, credit_account);
CREATE INDEX IF NOT EXISTS ix_ledger_ref ON ledger_entries(transaction_ref);

CREATE TABLE IF NOT EXISTS broker_accounts(
  account_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  provider_code TEXT NOT NULL,
  account_name TEXT NOT NULL,
  broker_user_id TEXT DEFAULT '',
  account_profile_name TEXT DEFAULT '',
  market_category TEXT NOT NULL DEFAULT 'INDIAN_EQUITY',
  connection_status TEXT NOT NULL DEFAULT 'DISCONNECTED',
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
  last_synced_at REAL
);
CREATE INDEX IF NOT EXISTS ix_ba_co_prov ON broker_accounts(company_id, provider_code);

CREATE TABLE IF NOT EXISTS encrypted_credentials(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  service_name TEXT NOT NULL,
  key_identifier TEXT NOT NULL,
  encrypted_payload TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_enc_creds ON encrypted_credentials(user_id, service_name);

CREATE TABLE IF NOT EXISTS market_assets(
  symbol TEXT PRIMARY KEY,
  base_asset TEXT NOT NULL,
  quote_asset TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_class TEXT NOT NULL, -- CRYPTO, FOREX, METALS, INDICES, STOCKS
  exchange TEXT NOT NULL DEFAULT 'COINDCX',
  min_qty REAL NOT NULL DEFAULT 0.0001,
  max_leverage REAL NOT NULL DEFAULT 100.0,
  tick_size REAL NOT NULL DEFAULT 0.0001,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS market_prices(
  symbol TEXT PRIMARY KEY,
  price REAL NOT NULL,
  bid REAL,
  ask REAL,
  high_24h REAL,
  low_24h REAL,
  volume_24h REAL,
  change_24h REAL,
  data_source TEXT NOT NULL DEFAULT 'COINDCX_REST',
  is_delayed INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlists(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  symbols_json TEXT NOT NULL DEFAULT '[]',
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_watchlists_uid ON watchlists(user_id);

CREATE TABLE IF NOT EXISTS strategies(
  strategy_id TEXT PRIMARY KEY,
  author_user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  category TEXT NOT NULL DEFAULT 'MOMENTUM', -- MOMENTUM, ARBITRAGE, MEAN_REVERSION, SCALPING, TREND
  risk_level TEXT NOT NULL DEFAULT 'MODERATE', -- LOW, MODERATE, HIGH, AGGRESSIVE
  strategy_type TEXT NOT NULL DEFAULT 'AI_NEURAL',
  is_approved INTEGER NOT NULL DEFAULT 1,
  is_public INTEGER NOT NULL DEFAULT 1,
  win_rate_live REAL DEFAULT 78.5,
  win_rate_paper REAL DEFAULT 82.0,
  win_rate_backtest REAL DEFAULT 85.4,
  profit_factor REAL DEFAULT 2.45,
  max_drawdown REAL DEFAULT 8.5,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id TEXT NOT NULL,
  version_num TEXT NOT NULL,
  code_ref TEXT,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  change_notes TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  subscribed_at REAL NOT NULL,
  expires_at REAL
);
CREATE INDEX IF NOT EXISTS ix_strat_subs ON strategy_subscriptions(user_id, strategy_id);

CREATE TABLE IF NOT EXISTS trading_bots(
  bot_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  strategy_id TEXT NOT NULL DEFAULT 'QUANTUM_MOMENTUM',
  broker_code TEXT NOT NULL DEFAULT 'COINDCX',
  symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
  timeframe TEXT NOT NULL DEFAULT '1m',
  capital_allocated REAL NOT NULL DEFAULT 100.0,
  risk_pct REAL NOT NULL DEFAULT 2.0,
  leverage REAL NOT NULL DEFAULT 100.0,
  max_positions INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL DEFAULT 'STOPPED', -- STOPPED, RUNNING, PAUSED
  execution_mode TEXT NOT NULL DEFAULT 'PAPER', -- PAPER, REAL
  last_heartbeat_at REAL,
  last_error TEXT,
  supervisor_pid INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trading_bots_uid ON trading_bots(user_id, status);

CREATE TABLE IF NOT EXISTS bot_configs(
  bot_id TEXT PRIMARY KEY,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  custom_rules_json TEXT NOT NULL DEFAULT '{}',
  tp_pct REAL NOT NULL DEFAULT 0.85,
  sl_pct REAL NOT NULL DEFAULT 0.45,
  trailing_stop_pct REAL NOT NULL DEFAULT 0.25,
  schedule_json TEXT NOT NULL DEFAULT '{}',
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_execution_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot_id TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  level TEXT NOT NULL DEFAULT 'INFO',
  message TEXT NOT NULL,
  details_json TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bot_logs ON bot_execution_logs(bot_id, created_at);

CREATE TABLE IF NOT EXISTS ai_models(
  model_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  provider TEXT NOT NULL, -- GOOGLE, ANTHROPIC, OPENAI, DETERMINISTIC
  version TEXT NOT NULL,
  model_type TEXT NOT NULL DEFAULT 'MULTIMODAL_REASONING',
  approval_status TEXT NOT NULL DEFAULT 'APPROVED', -- APPROVED, PENDING_REVIEW, DEPRECATED
  accuracy_score REAL DEFAULT 88.5,
  drift_metric REAL DEFAULT 0.02,
  cost_per_1k_tokens REAL DEFAULT 0.00015,
  is_default INTEGER NOT NULL DEFAULT 0,
  approved_by INTEGER,
  approved_at REAL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_signals(
  signal_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  asset_class TEXT NOT NULL DEFAULT 'CRYPTO',
  timeframe TEXT NOT NULL DEFAULT '1m',
  direction TEXT NOT NULL, -- BUY, SELL, HOLD
  entry_zone_low REAL NOT NULL,
  entry_zone_high REAL NOT NULL,
  stop_loss REAL NOT NULL,
  target_1 REAL NOT NULL,
  target_2 REAL,
  target_3 REAL,
  risk_reward_ratio REAL NOT NULL,
  strategy_name TEXT NOT NULL,
  technical_rationale TEXT NOT NULL,
  ai_explanation TEXT NOT NULL,
  confidence_score REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, EXPIRED, TARGET_HIT, STOP_HIT, CANCELLED
  actual_outcome TEXT DEFAULT 'PENDING',
  win_loss TEXT DEFAULT 'PENDING',
  pnl_pct REAL DEFAULT 0.0,
  expires_at REAL NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_signals_sym ON ai_signals(symbol, status);

CREATE TABLE IF NOT EXISTS ai_decisions(
  decision_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  bot_id TEXT,
  symbol TEXT NOT NULL,
  signal_id TEXT,
  recommendation TEXT NOT NULL,
  risk_guardian_verdict TEXT NOT NULL, -- APPROVED, REJECTED
  risk_rule_applied TEXT,
  execution_allowed INTEGER NOT NULL DEFAULT 0,
  final_action TEXT NOT NULL,
  explainability_json TEXT NOT NULL DEFAULT '{}',
  token_cost_est REAL DEFAULT 0.0,
  latency_ms REAL DEFAULT 0.0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_decisions ON ai_decisions(user_id, created_at);

CREATE TABLE IF NOT EXISTS ai_evaluations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_id TEXT NOT NULL,
  period_start REAL NOT NULL,
  period_end REAL NOT NULL,
  total_predictions INTEGER NOT NULL DEFAULT 0,
  correct_predictions INTEGER NOT NULL DEFAULT 0,
  win_rate_pct REAL NOT NULL DEFAULT 0.0,
  brier_score REAL DEFAULT 0.0,
  drift_detected INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fill_id TEXT UNIQUE NOT NULL,
  order_uuid TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  exchange_fill_id TEXT,
  fill_qty REAL NOT NULL,
  fill_price REAL NOT NULL,
  fee_amount REAL NOT NULL DEFAULT 0.0,
  fee_currency TEXT NOT NULL DEFAULT 'USDT',
  is_partial INTEGER NOT NULL DEFAULT 0,
  executed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_fills_uuid ON order_fills(order_uuid);

CREATE TABLE IF NOT EXISTS trades(
  trade_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  bot_id TEXT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  entry_price REAL NOT NULL,
  exit_price REAL NOT NULL,
  qty REAL NOT NULL,
  leverage REAL NOT NULL DEFAULT 1.0,
  margin REAL NOT NULL DEFAULT 0.0,
  realized_pnl REAL NOT NULL DEFAULT 0.0,
  pnl_pct REAL NOT NULL DEFAULT 0.0,
  fee_total REAL NOT NULL DEFAULT 0.0,
  duration_seconds REAL DEFAULT 0.0,
  entry_reason TEXT,
  exit_reason TEXT,
  strategy_id TEXT,
  broker_code TEXT NOT NULL DEFAULT 'COINDCX',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  opened_at REAL NOT NULL,
  closed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trades_user ON trades(user_id, closed_at);

CREATE TABLE IF NOT EXISTS backtest_jobs(
  job_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '1m',
  start_date REAL NOT NULL,
  end_date REAL NOT NULL,
  initial_capital REAL NOT NULL DEFAULT 10000.0,
  commission_pct REAL NOT NULL DEFAULT 0.04,
  slippage_pct REAL NOT NULL DEFAULT 0.02,
  status TEXT NOT NULL DEFAULT 'QUEUED', -- QUEUED, RUNNING, COMPLETED, FAILED
  progress_pct INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at REAL NOT NULL,
  completed_at REAL
);

CREATE TABLE IF NOT EXISTS backtest_results(
  job_id TEXT PRIMARY KEY,
  total_return_pct REAL NOT NULL DEFAULT 0.0,
  net_profit REAL NOT NULL DEFAULT 0.0,
  win_rate REAL NOT NULL DEFAULT 0.0,
  loss_rate REAL NOT NULL DEFAULT 0.0,
  profit_factor REAL NOT NULL DEFAULT 0.0,
  sharpe_ratio REAL NOT NULL DEFAULT 0.0,
  max_drawdown_pct REAL NOT NULL DEFAULT 0.0,
  avg_win REAL NOT NULL DEFAULT 0.0,
  avg_loss REAL NOT NULL DEFAULT 0.0,
  equity_curve_json TEXT NOT NULL DEFAULT '[]',
  monthly_returns_json TEXT NOT NULL DEFAULT '[]',
  trade_history_json TEXT NOT NULL DEFAULT '[]',
  walk_forward_json TEXT NOT NULL DEFAULT '{}',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_limits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  max_daily_loss_usd REAL NOT NULL DEFAULT 250.0,
  max_weekly_loss_usd REAL NOT NULL DEFAULT 750.0,
  max_monthly_loss_usd REAL NOT NULL DEFAULT 2000.0,
  max_account_exposure_usd REAL NOT NULL DEFAULT 50000.0,
  max_position_size_usd REAL NOT NULL DEFAULT 10000.0,
  max_concurrent_positions INTEGER NOT NULL DEFAULT 5,
  max_leverage REAL NOT NULL DEFAULT 100.0,
  per_asset_limits_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  bot_id TEXT,
  symbol TEXT,
  event_type TEXT NOT NULL, -- LIMIT_BREACH, CIRCUIT_BREAKER, VOLATILITY_ALERT, KILL_SWITCH, ORDER_VETO
  severity TEXT NOT NULL DEFAULT 'WARNING', -- INFO, WARNING, CRITICAL
  rule_name TEXT NOT NULL,
  details_json TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_risk_events_uid ON risk_events(user_id, created_at);

CREATE TABLE IF NOT EXISTS trading_journals(
  journal_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  trade_id TEXT,
  symbol TEXT NOT NULL,
  strategy_name TEXT,
  emotional_state TEXT DEFAULT 'CALM',
  mistakes_detected_json TEXT DEFAULT '[]',
  lessons_learned TEXT,
  rating INTEGER DEFAULT 5,
  notes TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_journal_uid ON trading_journals(user_id);

CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notification_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  channel TEXT NOT NULL DEFAULT 'IN_APP', -- IN_APP, EMAIL, TELEGRAM, SMS, PUSH
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'INFO', -- INFO, SUCCESS, WARNING, CRITICAL
  category TEXT NOT NULL DEFAULT 'TRADE', -- TRADE, BOT, RISK, BROKER, PAYMENT, SYSTEM
  is_read INTEGER NOT NULL DEFAULT 0,
  delivery_status TEXT NOT NULL DEFAULT 'SENT', -- PENDING, SENT, DELIVERED, FAILED
  retry_count INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notif_uid ON notifications(user_id, is_read);

CREATE TABLE IF NOT EXISTS audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_uuid TEXT UNIQUE NOT NULL,
  user_id INTEGER,
  actor_role TEXT NOT NULL DEFAULT 'USER',
  action TEXT NOT NULL,
  resource TEXT,
  ip_address TEXT,
  user_agent TEXT,
  status TEXT NOT NULL DEFAULT 'SUCCESS',
  details_json TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_at ON audit_logs(created_at);

CREATE TABLE IF NOT EXISTS system_incidents(
  incident_id TEXT PRIMARY KEY,
  service_name TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'WARNING', -- LOW, MEDIUM, HIGH, CRITICAL
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN', -- OPEN, INVESTIGATING, RESOLVED
  detected_at REAL NOT NULL,
  resolved_at REAL,
  resolution_notes TEXT
);

CREATE TABLE IF NOT EXISTS event_outbox(
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  correlation_id TEXT,
  user_id INTEGER,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSED, FAILED
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at REAL NOT NULL,
  processed_at REAL
);
CREATE INDEX IF NOT EXISTS ix_event_outbox_st ON event_outbox(status, created_at);

CREATE TABLE IF NOT EXISTS strategy_configs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'CUSTOM', -- AI, TRADINGVIEW, CUSTOM
  market_type TEXT NOT NULL DEFAULT 'FUTURES', -- FUTURES, SPOT, MARGIN
  enabled INTEGER NOT NULL DEFAULT 1,
  entry_rules_json TEXT NOT NULL DEFAULT '{}',
  exit_rules_json TEXT NOT NULL DEFAULT '{}',
  risk_per_trade_pct REAL NOT NULL DEFAULT 2.0,
  max_open_positions INTEGER NOT NULL DEFAULT 3,
  max_daily_loss_usd REAL NOT NULL DEFAULT 15.0,
  cooldown_seconds REAL NOT NULL DEFAULT 60.0,
  stop_loss_pct REAL NOT NULL DEFAULT 0.50,
  take_profit_pct REAL NOT NULL DEFAULT 1.00,
  trailing_stop_pct REAL NOT NULL DEFAULT 0.25,
  position_size_usd REAL NOT NULL DEFAULT 8.0,
  leverage REAL NOT NULL DEFAULT 20.0,
  allowed_directions TEXT NOT NULL DEFAULT 'BOTH', -- BOTH, LONG, SHORT
  updated_at REAL NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(user_id, strategy_id)
);
CREATE INDEX IF NOT EXISTS ix_strategy_cfg_user ON strategy_configs(user_id, enabled);

CREATE TABLE IF NOT EXISTS webhook_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  strategy_id TEXT NOT NULL DEFAULT '',
  signal_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  market_type TEXT NOT NULL DEFAULT 'FUTURES',
  price REAL NOT NULL DEFAULT 0.0,
  signal_timestamp REAL NOT NULL DEFAULT 0.0,
  status TEXT NOT NULL, -- EXECUTED_PAPER, EXECUTED_LIVE, REJECTED_AUTH, REJECTED_EXPIRED, REJECTED_DUPLICATE, REJECTED_RISK, REJECTED_SYMBOL, FAILED_EXCHANGE
  error_detail TEXT NOT NULL DEFAULT '',
  payload_sanitized TEXT NOT NULL DEFAULT '{}',
  order_id TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_webhook_events_user ON webhook_events(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_webhook_signal ON webhook_events(user_id, signal_id);

CREATE TABLE IF NOT EXISTS order_mappings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  client_order_id TEXT NOT NULL UNIQUE,
  exchange_order_id TEXT NOT NULL DEFAULT '',
  position_id TEXT NOT NULL DEFAULT '',
  strategy_id TEXT NOT NULL DEFAULT '',
  symbol TEXT NOT NULL,
  market_type TEXT NOT NULL DEFAULT 'FUTURES',
  side TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'PAPER', -- PAPER, REAL
  requested_qty REAL NOT NULL DEFAULT 0.0,
  filled_qty REAL NOT NULL DEFAULT 0.0,
  avg_fill_price REAL NOT NULL DEFAULT 0.0,
  fee_usd REAL NOT NULL DEFAULT 0.0,
  status TEXT NOT NULL DEFAULT 'NEW', -- NEW, PARTIALLY_FILLED, FILLED, REJECTED, CANCELLED
  rejection_reason TEXT NOT NULL DEFAULT '',
  endpoint TEXT NOT NULL DEFAULT '',
  sanitized_request TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_map_user ON order_mappings(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS position_protections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  position_id TEXT NOT NULL,
  exchange_position_id TEXT NOT NULL DEFAULT '',
  symbol TEXT NOT NULL,
  market_type TEXT NOT NULL DEFAULT 'FUTURES',
  entry_price REAL NOT NULL DEFAULT 0.0,
  filled_qty REAL NOT NULL DEFAULT 0.0,
  stop_loss_price REAL NOT NULL DEFAULT 0.0,
  take_profit_price REAL NOT NULL DEFAULT 0.0,
  trailing_stop_pct REAL NOT NULL DEFAULT 0.0,
  sl_order_id TEXT NOT NULL DEFAULT '',
  tp_order_id TEXT NOT NULL DEFAULT '',
  protection_verified INTEGER NOT NULL DEFAULT 0,
  protection_status TEXT NOT NULL DEFAULT 'UNPROTECTED', -- VERIFIED, MONITORED_BACKEND, UNPROTECTED, FAILED, CANCELLED
  failure_reason TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL,
  UNIQUE(user_id, position_id)
);
CREATE INDEX IF NOT EXISTS ix_pos_prot_user ON position_protections(user_id, protection_status);
"""


_wal_initialized = False
_db_init_lock = threading.Lock()
_read_tls = threading.local()

def connect():
    global _wal_initialized
    conn = sqlite3.connect(DB_PATH, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")
    if not _wal_initialized:
        with _db_init_lock:
            if not _wal_initialized:
                conn.execute("PRAGMA journal_mode=WAL")
                _wal_initialized = True
    return conn


def _get_read_conn():
    conn = getattr(_read_tls, "conn", None)
    if conn is not None:
        return conn
    conn = connect()
    _read_tls.conn = conn
    return conn


def query(sql, params=()):
    conn = _get_read_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass
        _read_tls.conn = None
        conn = _get_read_conn()
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def write(sql, params=()):
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def writes(statements):
    with _lock:
        conn = connect()
        try:
            for sql, params in statements:
                conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return salt, digest


def verify_password(password, salt, expected_hash):
    _, digest = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


# ---- Secrets at rest ---------------------------------------------------------
# Broker API keys/secrets are encrypted with Fernet when the SECRETS_KEY environment variable is
# set (any long random string). Values written before the key was set stay readable (plaintext).
_SECRET_PREFIX = "enc1:"
_fernet_cache = {}

def _get_fernet():
    key = os.environ.get("SECRETS_KEY", "").strip()
    if not key:
        return None
    if key not in _fernet_cache:
        try:
            import base64, hashlib
            from cryptography.fernet import Fernet
            _fernet_cache[key] = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
        except Exception:
            _fernet_cache[key] = None
    return _fernet_cache[key]

def encrypt_secret(value):
    if not value or str(value).startswith(_SECRET_PREFIX):
        return value
    f = _get_fernet()
    if not f:
        return value
    return _SECRET_PREFIX + f.encrypt(str(value).encode()).decode()

def decrypt_secret(value):
    if not value or not str(value).startswith(_SECRET_PREFIX):
        return value
    f = _get_fernet()
    if not f:
        raise RuntimeError("Stored broker credentials are encrypted but SECRETS_KEY is not set")
    return f.decrypt(str(value)[len(_SECRET_PREFIX):].encode()).decode()


def get_state(key, default=None):
    row = query_one("SELECT value FROM platform_state WHERE key=?", (key,))
    return row["value"] if row else default


def set_state(key, value):
    write("INSERT INTO platform_state(key,value) VALUES(?,?) "
          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def init_schema():
    with _lock:
        conn = connect()
        try:
            conn.executescript(SCHEMA)
            for table, cols in (("instruments", (("category", "TEXT NOT NULL DEFAULT 'CRYPTO'"),
                                                 ("source", "TEXT NOT NULL DEFAULT 'BINANCE'"),
                                                 # Country equities: where the company is listed, the
                                                 # TradingView code the quote sweep asks for, and the
                                                 # real close discovery saw, so a restart primes sane
                                                 # prices instead of random ones.
                                                 ("country", "TEXT"),
                                                 ("currency", "TEXT"),
                                                 ("tv_code", "TEXT"),
                                                 ("ref_price", "REAL"))),
                                ("wallets", (("starting_balance", "REAL NOT NULL DEFAULT 0"),
                                             ("target_amount", "REAL NOT NULL DEFAULT 0"),
                                             ("locked_balance", "REAL NOT NULL DEFAULT 0"))),
                                ("positions", (("category", "TEXT"),
                                               ("signal_score", "REAL"),
                                               ("signal_reason", "TEXT"),
                                               ("feed_source", "TEXT"),
                                               ("peak_pnl_pct", "REAL NOT NULL DEFAULT 0"),
                                               ("peak_cash_pnl", "REAL NOT NULL DEFAULT 0"),
                                               ("ai_win_prob", "REAL"),
                                               ("leverage", "REAL DEFAULT 10.0"),
                                               ("is_live", "INTEGER DEFAULT 0"),
                                               ("magic_id", "TEXT"),
                                               ("mt4_ticket", "INTEGER"),
                                               ("terminal_id", "TEXT"),
                                               ("command_id", "TEXT"),
                                               ("account_login", "TEXT"),
                                               ("account_type", "TEXT DEFAULT 'DEMO'"),
                                               ("order_uuid", "TEXT"),
                                               ("fee_usd", "REAL DEFAULT 0.0"),
                                               ("slippage_bps", "REAL DEFAULT 0.0"),
                                               ("funding_fee_usd", "REAL DEFAULT 0.0"),
                                               ("liquidation_price", "REAL DEFAULT 0.0"),
                                               ("trailing_stop_pct", "REAL DEFAULT 0.0"),
                                               ("partial_tp_booked", "INTEGER DEFAULT 0"))),
                                ("users", (("bot_leverage", "REAL DEFAULT 100.0"),
                                           ("bot_activated_at", "REAL DEFAULT 0"),
                                           ("bot_market_focus", "TEXT DEFAULT 'ALL'"),
                                           ("bot_trade_direction", "TEXT DEFAULT 'BOTH'"),
                                           ("theme_preference", "TEXT DEFAULT 'dark'"),
                                           ("brand_id", "TEXT DEFAULT 'ARAA'"),
                                           ("role", "TEXT DEFAULT 'CUSTOMER'"),
                                           ("account_status", "TEXT DEFAULT 'ACTIVE'"),
                                           ("email_verified", "INTEGER DEFAULT 1"),
                                           ("two_factor_enabled", "INTEGER DEFAULT 0"),
                                           ("two_factor_secret", "TEXT"),
                                           ("plan_code", "TEXT DEFAULT 'PRO'"),
                                           ("phone", "TEXT"),
                                           ("backtest_validated", "INTEGER DEFAULT 1"),
                                           ("paper_validated", "INTEGER DEFAULT 1"),
                                           ("consecutive_losses", "INTEGER DEFAULT 0"),
                                           ("max_daily_loss_usd", "REAL DEFAULT 250.0"),
                                           ("max_weekly_loss_usd", "REAL DEFAULT 750.0"),
                                           ("max_drawdown_pct", "REAL DEFAULT 15.0"),
                                           ("notify_telegram", "INTEGER DEFAULT 1"),
                                           ("notify_email", "INTEGER DEFAULT 1"),
                                           ("notify_inapp", "INTEGER DEFAULT 1"))),
                                ("orders", (("leverage", "REAL DEFAULT 10.0"),
                                            ("target_pct", "REAL DEFAULT 0.0"),
                                            ("stop_pct", "REAL DEFAULT 0.0"),
                                            ("is_live", "INTEGER DEFAULT 0"))),
                                ("deposits", (("bank_name", "TEXT"),
                                              ("account_number", "TEXT"),
                                              ("ifsc_code", "TEXT"),
                                              ("account_holder", "TEXT"))),
                                ("withdrawals", (("bank_name", "TEXT"),
                                                 ("account_number", "TEXT"),
                                                 ("ifsc_code", "TEXT"),
                                                 ("account_holder", "TEXT"))),
                                ("broker_connections", (("mt4_login", "TEXT"),
                                                        ("mt4_server", "TEXT"),
                                                        ("mt4_password_enc", "TEXT"),
                                                        ("leverage", "REAL DEFAULT 500.0"),
                                                        ("max_positions", "INTEGER DEFAULT 10"),
                                                        ("today_pnl", "REAL DEFAULT 0.0"),
                                                        ("market_focus", "TEXT DEFAULT 'ALL'"),
                                                        ("terminal_id", "TEXT"),
                                                        ("account_type", "TEXT DEFAULT 'DEMO'"),
                                                        ("currency", "TEXT DEFAULT 'USD'"),
                                                        ("free_margin", "REAL DEFAULT 0.0"),
                                                        ("margin", "REAL DEFAULT 0.0"),
                                                        ("margin_level", "REAL DEFAULT 0.0"),
                                                        ("trading_allowed", "INTEGER DEFAULT 0"),
                                                        ("expert_enabled", "INTEGER DEFAULT 0"),
                                                        ("live_trading_approved", "INTEGER DEFAULT 0"),
                                                        ("brand_id", "TEXT DEFAULT 'ARAA'"),
                                                        ("coindcx_key", "TEXT"),
                                                        ("coindcx_secret", "TEXT"),
                                                        ("account_name", "TEXT"),
                                                        ("account_email", "TEXT"),
                                                        ("last_heartbeat_at", "REAL"))),
                                ("real_bot_configs", (("max_positions", "INTEGER DEFAULT 20"),)),
                                ("subscription_invoices", (("provider_order_id", "TEXT"),
                                                           ("provider_payment_id", "TEXT"),
                                                           ("provider_signature", "TEXT")))):
                have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, decl in cols:
                    if col not in have:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            # Post-migration backfills wrapped safely in try/except to prevent deployment lockups
            try:
                conn.execute(
                    "UPDATE positions SET category="
                    "(SELECT i.category FROM instruments i WHERE i.symbol=positions.symbol) "
                    "WHERE category IS NULL AND EXISTS(SELECT 1 FROM instruments i "
                    " WHERE i.symbol=positions.symbol)")
                conn.execute("UPDATE positions SET category='CRYPTO' WHERE category IS NULL "
                             "AND symbol LIKE '%USDT'")
            except Exception:
                pass

            try:
                # The goal tracker compares today's equity with the money that started the account,
                # so backfill it from the first deposit (or the current balance for older wallets).
                conn.execute(
                    "UPDATE wallets SET starting_balance=COALESCE(("
                    "SELECT d.credited FROM deposits d WHERE d.user_id=wallets.user_id "
                    "ORDER BY d.created_at ASC LIMIT 1), deposit_balance) WHERE starting_balance<=0")
                conn.execute(
                    "UPDATE wallets SET target_amount=ROUND(starting_balance*1.5,2) WHERE target_amount<=0")
            except Exception:
                pass

            # One-off reconciliation. Earlier builds credited a closed trade's P&L into both
            # deposit_balance and profit_balance, and left position margin outside locked_balance,
            # so every wallet drifted away from the trade ledger. Rebuild the three pools from
            # deposits, closed trades, profit links and withdrawals. Guarded by state so it runs
            # once per version; bump the key if the formula changes again.
            try:
                done = conn.execute("SELECT value FROM platform_state WHERE key='wallets_reconciled_v2'") \
                               .fetchone()
                if not done or done[0] != "1":
                    conn.execute(
                        "UPDATE wallets SET locked_balance="
                        "(SELECT COALESCE(SUM(margin),0) FROM positions p WHERE p.user_id=wallets.user_id "
                        " AND p.status='OPEN')+"
                        "(SELECT COALESCE(SUM(margin),0) FROM orders o WHERE o.user_id=wallets.user_id "
                        " AND o.status='PENDING')")
                    # Withdrawals debit profit_balance by the gross amount the user asked for; the
                    # 30% brokerage is platform revenue and never returns to the user. A pending
                    # request has already been debited, a rejected one was refunded.
                    conn.execute(
                        "UPDATE wallets SET profit_balance=MAX(0, "
                        "(SELECT COALESCE(SUM(realized_pnl),0) FROM positions p "
                        " WHERE p.user_id=wallets.user_id AND p.status='CLOSED' AND p.realized_pnl>0)+"
                        "(SELECT COALESCE(SUM(net),0) FROM profit_links l WHERE l.user_id=wallets.user_id)-"
                        "(SELECT COALESCE(SUM(amount),0) FROM withdrawals w "
                        " WHERE w.user_id=wallets.user_id AND w.status IN ('APPROVED','PENDING')))")
                    conn.execute(
                        "UPDATE wallets SET deposit_balance=total_deposited+"
                        "(SELECT COALESCE(SUM(realized_pnl),0) FROM positions p "
                        " WHERE p.user_id=wallets.user_id AND p.status='CLOSED' AND p.realized_pnl<0)"
                        "-locked_balance")
                    conn.execute("UPDATE wallets SET deposit_balance=MAX(0, deposit_balance)")
                    # An earlier build wrote position_id with the wrong parameter count, leaving
                    # filled limit orders detached from the positions they opened.
                    conn.execute(
                        "UPDATE orders SET position_id=(SELECT p.id FROM positions p WHERE p.user_id=orders.user_id "
                        " AND p.symbol=orders.symbol AND p.source='LIMIT' AND p.entry_price=orders.price "
                        " ORDER BY p.opened_at LIMIT 1) "
                        "WHERE status='FILLED' AND position_id IS NULL AND "
                        "EXISTS(SELECT 1 FROM positions p WHERE p.user_id=orders.user_id "
                        " AND p.symbol=orders.symbol AND p.source='LIMIT' AND p.entry_price=orders.price)")
                    conn.execute("INSERT INTO platform_state(key,value) VALUES('wallets_reconciled_v2','1') "
                                 "ON CONFLICT(key) DO UPDATE SET value='1'")
            except Exception:
                pass
            # High-Concurrency Multi-User Scaling Indices
            conn.execute("CREATE INDEX IF NOT EXISTS ix_pos_status ON positions(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_pos_user_status ON positions(user_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_orders_user_status ON orders(user_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_login_events_user ON login_events(user_id)")
            
            # Seed Default SaaS Subscription Plans
            now_ts = time.time()
            plans = [
                ("STARTER", "Starter Plan", 29.0, 290.0, 2499.0, 24990.0, 5, 25.0, 0, 1, 1, 0,
                 '["Basic trading dashboard", "Limited strategies", "Paper trading", "Standard alerts"]', now_ts),
                ("PRO", "Pro Trader Plan", 79.0, 790.0, 6499.0, 64990.0, 15, 100.0, 1, 1, 1, 0,
                 '["Advanced 3-Agent AI trading", "CoinDCX 100x Live Futures", "Advanced risk configuration", "Trading analytics & Telegram alerts"]', now_ts),
                ("PREMIUM", "Premium Institutional", 199.0, 1990.0, 15999.0, 159990.0, 50, 200.0, 1, 1, 1, 0,
                 '["All quantitative strategies", "Walk-forward AI Trainer & Backtesting", "Exportable PDF/CSV audit reports", "Priority 24/7 execution support"]', now_ts),
                ("ENTERPRISE", "Enterprise White-Label", 499.0, 4990.0, 39999.0, 399990.0, 100, 500.0, 1, 1, 1, 1,
                 '["White-label custom branding", "Dedicated multi-account API access", "Custom institutional risk governance", "Dedicated SLA & deployment"]', now_ts),
            ]
            for p in plans:
                conn.execute(
                    "INSERT INTO subscription_plans(plan_code, name, monthly_price_usd, annual_price_usd, "
                    "monthly_price_inr, annual_price_inr, max_open_positions, max_leverage, allow_live_trading, "
                    "allow_ai_committee, allow_backtesting, allow_whitelabel, features_json, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(plan_code) DO UPDATE SET "
                    "name=excluded.name, monthly_price_usd=excluded.monthly_price_usd, "
                    "annual_price_usd=excluded.annual_price_usd, monthly_price_inr=excluded.monthly_price_inr, "
                    "annual_price_inr=excluded.annual_price_inr, max_open_positions=excluded.max_open_positions, "
                    "max_leverage=excluded.max_leverage, allow_live_trading=excluded.allow_live_trading, "
                    "features_json=excluded.features_json, updated_at=excluded.updated_at",
                    p
                )
            conn.commit()
        finally:
            conn.close()
    try:
        from migrations import run_migrations
    except ImportError:
        from backend.migrations import run_migrations
    run_migrations()


def is_secrets_encryption_enabled():
    """Returns True when SECRETS_KEY is configured and Fernet encryption is active."""
    return _get_fernet() is not None


def day_start(ts=None):
    d = datetime.date.fromtimestamp(ts if ts is not None else time.time())
    return datetime.datetime.combine(d, datetime.time.min).timestamp()


def seed_users():
    """Demo accounts so the admin panel and bot have real data on first run."""
    now = time.time()
    people = [
        ("user@gmail.com", "Rahul Sharma"), ("priya@gmail.com", "Priya Nair"),
        ("arjun@gmail.com", "Arjun Reddy"), ("fatima@gmail.com", "Fatima Khan"),
        ("vikram@gmail.com", "Vikram Singh"), ("neha@gmail.com", "Neha Gupta"),
        ("karan@gmail.com", "Karan Mehta"), ("divya@gmail.com", "Divya Iyer"),
        ("rohan@gmail.com", "Rohan Das"), ("anita@gmail.com", "Anita Bose"),
        ("sameer@gmail.com", "Sameer Ali"), ("lakshmi@gmail.com", "Lakshmi Menon"),
        ("dev@gmail.com", "Dev Patel"), ("zoya@gmail.com", "Zoya Sheikh"),
    ]
    ids = []
    for i, (email, name) in enumerate(people):
        exists = query_one("SELECT id FROM users WHERE email=?", (email,))
        if exists:
            ids.append(exists["id"])
            continue
        salt, digest = hash_password("demo1234")
        uid = write("INSERT INTO users(email,name,pw_salt,pw_hash,created_at,last_login_at,"
                    "bot_enabled,bot_max_positions,bot_risk_pct,bot_mode) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (email, name, salt, digest, now - 86400 * (30 - i),
                     now - random.uniform(0, 6) * 3600, 1 if i % 2 == 0 else 0,
                     random.choice([5, 8, 10, 10]), round(random.uniform(1.5, 4), 1),
                     random.choice(["SCALP", "SCALP", "SWING"])))
        # starting_balance is what the goal tracker measures against and target_amount the .5x
        # it aims for; the boot migration only backfills them on the run after the seed, so a
        # freshly created database would show an empty goal panel for one launch.
        capital = round(random.uniform(8000, 60000), 2)
        write("INSERT INTO wallets(user_id,deposit_balance,profit_balance,total_deposited,"
              "starting_balance,target_amount) VALUES(?,?,?,?,?,?)",
              (uid, capital, round(random.uniform(1500, 22000), 2),
               round(random.uniform(20000, 90000), 2), capital, round(capital * 1.5, 2)))
        writes([("INSERT INTO login_events(user_id,at) VALUES(?,?)", (uid, now - random.uniform(0, 5) * 3600))
                for _ in range(random.randint(1, 3))])
        ids.append(uid)
    # The ,000 → ,000 goal story the README documents (goal.demo@gmail.com / goal1234), seeded
    # here so a machine that has never seen this app shows the same goal tracker on first launch.
    if not query_one("SELECT id FROM users WHERE email='goal.demo@gmail.com'"):
        salt, digest = hash_password("goal1234")
        gid = write("INSERT INTO users(email,name,pw_salt,pw_hash,created_at,last_login_at,bot_enabled,"
                    "bot_max_positions,bot_risk_pct,bot_mode) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("goal.demo@gmail.com", "Goal Demo", salt, digest, now - 86400, now - 600, 1, 3,
                     2.0, "SCALP"))
        ref = "DEP" + secrets.token_hex(5).upper()
        writes([
            ("INSERT INTO wallets(user_id,deposit_balance,profit_balance,total_deposited,"
             "starting_balance,target_amount) VALUES(?,?,?,?,?,?)",
             (gid, 1000.0, 0.0, 1000.0, 1000.0, 1500.0)),
            ("INSERT INTO deposits(user_id,method,asset,amount,credited,ref,status,created_at) "
             "VALUES(?,?,?,?,?,?,?,?)", (gid, "UPI", "USD", 1000.0, 1000.0, ref, "CREDITED", now - 86400)),
            ("INSERT INTO transactions(user_id,kind,asset,gross,brokerage,net,status,note,created_at) "
             "VALUES(?,?,?,?,?,?,?,?,?)",
             (gid, "DEPOSIT", "USD", 1000.0, 0, 1000.0, "CREDITED", ref, now - 86400)),
            ("INSERT INTO login_events(user_id,at) VALUES(?,?)", (gid, now - 600)),
        ])
        ids.append(gid)
    # Seed the primary demo account displayed on the sign-in screen (newtrader@gmail.com / password123)
    if not query_one("SELECT id FROM users WHERE email='newtrader@gmail.com'"):
        salt, digest = hash_password("password123")
        nid = write("INSERT INTO users(email,name,pw_salt,pw_hash,created_at,last_login_at,bot_enabled,"
                    "bot_max_positions,bot_risk_pct,bot_mode) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("newtrader@gmail.com", "Demo Trader", salt, digest, now - 86400, now - 300, 1, 10,
                     2.0, "SCALP"))
        ref = "DEP" + secrets.token_hex(5).upper()
        writes([
            ("INSERT INTO wallets(user_id,deposit_balance,profit_balance,total_deposited,"
             "starting_balance,target_amount) VALUES(?,?,?,?,?,?)",
             (nid, 25000.0, 4250.0, 25000.0, 25000.0, 37500.0)),
            ("INSERT INTO deposits(user_id,method,asset,amount,credited,ref,status,created_at) "
             "VALUES(?,?,?,?,?,?,?,?)", (nid, "UPI", "USD", 25000.0, 25000.0, ref, "CREDITED", now - 86400)),
            ("INSERT INTO transactions(user_id,kind,asset,gross,brokerage,net,status,note,created_at) "
             "VALUES(?,?,?,?,?,?,?,?,?)",
             (nid, "DEPOSIT", "USD", 25000.0, 0, 25000.0, "CREDITED", ref, now - 86400)),
            ("INSERT INTO login_events(user_id,at) VALUES(?,?)", (nid, now - 300)),
        ])
        ids.append(nid)
    return ids


def seed_history(user_ids):
    """Deposits, approved withdrawals (with 30% brokerage), profit links and closed bot trades."""
    now = time.time()
    symbols = [r["symbol"] for r in query("SELECT symbol FROM instruments WHERE enabled=1 LIMIT 200")] or ["BTCUSDT"]
    for uid in user_ids:
        if query_one("SELECT id FROM transactions WHERE user_id=?", (uid,)):
            continue
        wallet = query_one("SELECT * FROM wallets WHERE user_id=?", (uid,))
        for _ in range(random.randint(1, 3)):
            amt = round(random.choice([5000, 10000, 20000, 25000, 50000]), 2)
            when = now - random.uniform(1, 25) * 86400
            ref = "DEP" + secrets.token_hex(5).upper()
            writes([
                ("INSERT INTO deposits(user_id,method,asset,amount,credited,ref,status,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?)", (uid, random.choice(["UPI", "NETBANKING", "CARD"]), "USD",
                                            amt, amt, ref, "CREDITED", when)),
                ("INSERT INTO transactions(user_id,kind,asset,gross,brokerage,net,status,note,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)", (uid, "DEPOSIT", "USD", amt, 0, amt, "CREDITED", ref, when)),
            ])
        for _ in range(random.randint(0, 2)):
            amt = round(random.uniform(1000, 8000), 2)
            fee = round(amt * 0.30, 2)
            net = round(amt - fee, 2)
            when = now - random.uniform(1, 20) * 86400
            payout = "PAYOUT" + secrets.token_hex(4).upper()
            writes([
                ("INSERT INTO withdrawals(user_id,amount,brokerage,net_payable,method,status,created_at,"
                 "resolved_at,payout_ref) VALUES(?,?,?,?,?,?,?,?,?)",
                 (uid, amt, fee, net, "UPI", "APPROVED", when, when + 7200, payout)),
                ("INSERT INTO transactions(user_id,kind,asset,gross,brokerage,net,status,note,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)", (uid, "WITHDRAW", "USD", amt, fee, net, "PAID", payout, when)),
                ("INSERT INTO brokerage_ledger(at,source,ref,user_id,amount) VALUES(?,?,?,?,?)",
                 (when, "WITHDRAWAL", payout, uid, fee)),
                ("UPDATE wallets SET total_withdrawn=total_withdrawn+?, total_brokerage=total_brokerage+?, "
                 "profit_balance=MAX(0, profit_balance-?) WHERE user_id=?", (net, fee, amt, uid)),
            ])
        for _ in range(random.randint(0, 2)):
            gross = round(random.choice([500, 1000, 2000, 2500]), 2)
            fee = round(gross * 0.30, 2)
            net = round(gross - fee, 2)
            when = now - random.uniform(1, 15) * 86400
            tok = secrets.token_hex(8)
            writes([
                ("INSERT INTO profit_links(token,user_id,email,gross,brokerage,net,reason,status,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)",
                 (tok, uid, query_one("SELECT email FROM users WHERE id=?", (uid,))["email"], gross, fee,
                  net, random.choice(["Admin bonus", "Referral reward", "Campaign payout"]),
                  "CLAIMED", when)),
                ("INSERT INTO transactions(user_id,kind,asset,gross,brokerage,net,status,note,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)", (uid, "PROFIT_LINK", "USD", gross, fee, net, "CREDITED", tok, when)),
                ("INSERT INTO brokerage_ledger(at,source,ref,user_id,amount) VALUES(?,?,?,?,?)",
                 (when, "PROFIT_LINK", tok, uid, fee)),
                ("UPDATE wallets SET profit_balance=profit_balance+? WHERE user_id=?", (net, uid)),
            ])
        for _ in range(random.randint(4, 12)):
            sym = random.choice(symbols)
            side = random.choice(["LONG", "LONG", "SHORT"])
            entry = round(random.uniform(0.4, 90000), 6)
            margin = round(random.uniform(1500, 6000), 2)
            qty = round(margin / entry, 6)
            win = random.random() < 0.68
            when = now - random.uniform(0.2, 10) * 86400
            if win:
                move = random.uniform(0.004, 0.012)
                pnl = round(margin * move, 2)
                exit_price = entry * (1 + move) if side == "LONG" else entry * (1 - move)
                reason = "TARGET_HIT"
            else:
                move = random.uniform(0.002, 0.006)
                pnl = -round(margin * move, 2)
                exit_price = entry * (1 - move) if side == "LONG" else entry * (1 + move)
                reason = "STOP_LOSS"
            writes([
                ("INSERT INTO positions(user_id,symbol,source,side,qty,entry_price,margin,target_pct,"
                 "stop_pct,status,current_price,unrealized_pnl,opened_at,closed_at,realized_pnl,close_reason) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (uid, sym, "BOT", side, qty, entry, margin, 0.9, 0.5, "CLOSED",
                  round(exit_price, 6), 0, when, when + random.uniform(40, 900), pnl, reason)),
                ("UPDATE wallets SET profit_balance=profit_balance+? WHERE user_id=?", (pnl, uid)),
            ])
    set_state("seeded", "1")
