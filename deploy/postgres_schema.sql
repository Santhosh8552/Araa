-- ARAA Company Proprietary Trading Platform — PostgreSQL 16 Production Schema
-- Generated automatically from backend/database.py + backend/migrations.py

CREATE TABLE IF NOT EXISTS schema_migrations(
  version TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at DOUBLE PRECISION NOT NULL,
  checksum TEXT NOT NULL
);

-- === BASE CORE SCHEMA ===

CREATE TABLE IF NOT EXISTS users(
  id BIGSERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pw_salt TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  last_login_at DOUBLE PRECISION,
  bot_enabled INTEGER NOT NULL DEFAULT 0,
  bot_max_positions INTEGER NOT NULL DEFAULT 10,
  bot_risk_pct DOUBLE PRECISION NOT NULL DEFAULT 2.0,
  bot_mode TEXT NOT NULL DEFAULT 'SCALP',
  bot_leverage DOUBLE PRECISION DEFAULT 100.0,
  bot_activated_at DOUBLE PRECISION DEFAULT 0,
  bot_market_focus TEXT DEFAULT 'FUTURES_USD',
  bot_trade_direction TEXT DEFAULT 'BOTH'
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  last_seen DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS login_events(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS wallets(
  user_id INTEGER PRIMARY KEY,
  deposit_balance DOUBLE PRECISION NOT NULL DEFAULT 0,
  profit_balance DOUBLE PRECISION NOT NULL DEFAULT 0,
  total_deposited DOUBLE PRECISION NOT NULL DEFAULT 0,
  total_withdrawn DOUBLE PRECISION NOT NULL DEFAULT 0,
  total_brokerage DOUBLE PRECISION NOT NULL DEFAULT 0,
  locked_balance DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS instruments(
  symbol TEXT PRIMARY KEY,
  base TEXT NOT NULL,
  quote TEXT NOT NULL,
  display_name TEXT,
  tick_size DOUBLE PRECISION NOT NULL DEFAULT 0.0001,
  category TEXT NOT NULL DEFAULT 'CRYPTO',
  source TEXT NOT NULL DEFAULT 'BINANCE',
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS positions(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  source TEXT NOT NULL,
  side TEXT NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  margin DOUBLE PRECISION NOT NULL,
  target_pct DOUBLE PRECISION NOT NULL,
  stop_pct DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL,
  current_price DOUBLE PRECISION NOT NULL,
  unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
  opened_at DOUBLE PRECISION NOT NULL,
  closed_at DOUBLE PRECISION,
  realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
  close_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_pos_user ON positions(user_id, status);
CREATE TABLE IF NOT EXISTS bot_log(
  id BIGSERIAL PRIMARY KEY,
  at DOUBLE PRECISION NOT NULL,
  user_id INTEGER,
  level TEXT NOT NULL,
  message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER,
  kind TEXT NOT NULL,
  asset TEXT NOT NULL DEFAULT 'USD',
  gross DOUBLE PRECISION NOT NULL,
  brokerage DOUBLE PRECISION NOT NULL DEFAULT 0,
  net DOUBLE PRECISION NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  note TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS deposits(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  method TEXT NOT NULL,
  asset TEXT NOT NULL DEFAULT 'USD',
  amount DOUBLE PRECISION NOT NULL,
  credited DOUBLE PRECISION NOT NULL,
  ref TEXT NOT NULL,
  status TEXT NOT NULL,
  bank_name TEXT,
  account_number TEXT,
  ifsc_code TEXT,
  account_holder TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS withdrawals(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  amount DOUBLE PRECISION NOT NULL,
  brokerage DOUBLE PRECISION NOT NULL,
  net_payable DOUBLE PRECISION NOT NULL,
  method TEXT NOT NULL,
  status TEXT NOT NULL,
  bank_name TEXT,
  account_number TEXT,
  ifsc_code TEXT,
  account_holder TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  resolved_at DOUBLE PRECISION,
  payout_ref TEXT
);
CREATE TABLE IF NOT EXISTS user_bank_accounts(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  bank_name TEXT NOT NULL,
  account_holder TEXT NOT NULL,
  account_number TEXT NOT NULL,
  ifsc_code TEXT NOT NULL,
  upi_id TEXT,
  is_default INTEGER DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS profit_links(
  id BIGSERIAL PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  gross DOUBLE PRECISION NOT NULL,
  brokerage DOUBLE PRECISION NOT NULL,
  net DOUBLE PRECISION NOT NULL,
  reason TEXT,
  status TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS brokerage_ledger(
  id BIGSERIAL PRIMARY KEY,
  at DOUBLE PRECISION NOT NULL,
  source TEXT NOT NULL,
  ref TEXT,
  user_id INTEGER,
  amount DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_state(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  price DOUBLE PRECISION NOT NULL,
  margin DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  filled_at DOUBLE PRECISION,
  position_id INTEGER,
  leverage DOUBLE PRECISION DEFAULT 10.0,
  target_pct DOUBLE PRECISION DEFAULT 0.0,
  stop_pct DOUBLE PRECISION DEFAULT 0.0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS ai_predictions(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  category TEXT NOT NULL,
  direction TEXT NOT NULL,
  action TEXT NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  target_price DOUBLE PRECISION NOT NULL,
  stop_price DOUBLE PRECISION NOT NULL,
  target_pct DOUBLE PRECISION NOT NULL,
  stop_pct DOUBLE PRECISION NOT NULL,
  risk_reward DOUBLE PRECISION NOT NULL,
  win_probability INTEGER NOT NULL,
  confidence DOUBLE PRECISION NOT NULL,
  rationale TEXT NOT NULL,
  mode TEXT NOT NULL,
  post_entry_status TEXT DEFAULT 'MONITORING',
  post_entry_notes TEXT,
  outcome TEXT DEFAULT 'PENDING',
  realized_pnl DOUBLE PRECISION DEFAULT 0,
  created_at DOUBLE PRECISION NOT NULL,
  closed_at DOUBLE PRECISION,
  position_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_pred_user ON ai_predictions(user_id, outcome);

CREATE TABLE IF NOT EXISTS demat_applications(
  id BIGSERIAL PRIMARY KEY,
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
  kyc_verified_at DOUBLE PRECISION,
  approved_at DOUBLE PRECISION,
  rejected_at DOUBLE PRECISION,
  rejection_reason TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_demat_app_user ON demat_applications(user_id);

CREATE TABLE IF NOT EXISTS broker_connections(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE,
  broker_name TEXT NOT NULL,
  api_key_masked TEXT,
  live_balance DOUBLE PRECISION DEFAULT 0.0,
  live_equity DOUBLE PRECISION DEFAULT 0.0,
  status TEXT DEFAULT 'DISCONNECTED',
  is_live_active INTEGER DEFAULT 0,
  connected_at DOUBLE PRECISION NOT NULL,
  last_synced_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_broker_conn_user ON broker_connections(user_id);

CREATE TABLE IF NOT EXISTS broker_provider_consents(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  provider_id TEXT NOT NULL,
  market_segment TEXT NOT NULL,
  real_money_risk_acknowledged INTEGER DEFAULT 0,
  power_of_attorney_acknowledged INTEGER DEFAULT 0,
  automated_algo_execution_consent INTEGER DEFAULT 0,
  loss_liability_acknowledged INTEGER DEFAULT 0,
  ip_address TEXT,
  user_agent TEXT,
  consented_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS real_bot_configs(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE,
  provider_id TEXT NOT NULL,
  broker_account_id TEXT,
  market_segments TEXT NOT NULL DEFAULT 'CRYPTO,METALS,FOREX,INDIAN_EQUITY',
  strategy_mode TEXT NOT NULL DEFAULT 'PURE_CRYPTO',
  max_order_size DOUBLE PRECISION NOT NULL DEFAULT 50000.0,
  max_daily_loss DOUBLE PRECISION NOT NULL DEFAULT 15000.0,
  max_exposure_limit DOUBLE PRECISION NOT NULL DEFAULT 200000.0,
  max_leverage DOUBLE PRECISION NOT NULL DEFAULT 500.0,
  stop_loss_pct DOUBLE PRECISION NOT NULL DEFAULT 1.5,
  take_profit_pct DOUBLE PRECISION NOT NULL DEFAULT 3.0,
  trailing_stop_enabled INTEGER DEFAULT 1,
  execution_speed TEXT DEFAULT 'HIGH_VELOCITY',
  bot_status TEXT NOT NULL DEFAULT 'PAUSED',
  emergency_shutdown INTEGER DEFAULT 0,
  verified_funds DOUBLE PRECISION DEFAULT 0.0,
  verified_margin DOUBLE PRECISION DEFAULT 0.0,
  last_risk_audit_at DOUBLE PRECISION,
  max_positions INTEGER DEFAULT 20,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS real_bot_audit_logs(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'INFO',
  message TEXT NOT NULL,
  details_json TEXT,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS mt4_pairing_tokens(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  brand_id TEXT NOT NULL DEFAULT 'ARAA',
  account_login TEXT,
  expected_server TEXT,
  account_type TEXT NOT NULL DEFAULT 'DEMO',
  token_hash TEXT UNIQUE NOT NULL,
  token_preview TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  expires_at DOUBLE PRECISION NOT NULL,
  used_at DOUBLE PRECISION,
  terminal_id TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mt4_pair_user ON mt4_pairing_tokens(user_id, status);

CREATE TABLE IF NOT EXISTS mt4_terminals(
  id BIGSERIAL PRIMARY KEY,
  terminal_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  brand_id TEXT NOT NULL DEFAULT 'ARAA',
  account_login TEXT NOT NULL,
  server TEXT NOT NULL,
  account_type TEXT NOT NULL DEFAULT 'DEMO',
  currency TEXT NOT NULL DEFAULT 'USD',
  balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  equity DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  free_margin DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  margin DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  margin_level DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  leverage DOUBLE PRECISION NOT NULL DEFAULT 500.0,
  open_positions_count INTEGER NOT NULL DEFAULT 0,
  trading_allowed INTEGER NOT NULL DEFAULT 0,
  expert_enabled INTEGER NOT NULL DEFAULT 0,
  connection_status TEXT NOT NULL DEFAULT 'DISCONNECTED',
  live_trading_approved INTEGER NOT NULL DEFAULT 0,
  live_trading_enabled INTEGER NOT NULL DEFAULT 0,
  market_focus TEXT NOT NULL DEFAULT 'ALL',
  trading_mode TEXT NOT NULL DEFAULT 'SCALP',
  session_token_hash TEXT NOT NULL,
  last_heartbeat_at DOUBLE PRECISION,
  last_sync_at DOUBLE PRECISION,
  last_error TEXT,
  positions_json TEXT NOT NULL DEFAULT '[]',
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mt4_term_user ON mt4_terminals(user_id, account_login);

CREATE TABLE IF NOT EXISTS mt4_commands(
  id BIGSERIAL PRIMARY KEY,
  command_id TEXT UNIQUE NOT NULL,
  nonce TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  brand_id TEXT NOT NULL DEFAULT 'ARAA',
  terminal_id TEXT NOT NULL,
  account_login TEXT NOT NULL,
  action TEXT NOT NULL,
  symbol TEXT,
  side TEXT,
  lots DOUBLE PRECISION DEFAULT 0.0,
  price DOUBLE PRECISION DEFAULT 0.0,
  sl DOUBLE PRECISION DEFAULT 0.0,
  tp DOUBLE PRECISION DEFAULT 0.0,
  magic INTEGER DEFAULT 888801,
  status TEXT NOT NULL DEFAULT 'QUEUED',
  mt4_ticket INTEGER,
  executed_price DOUBLE PRECISION,
  realized_pnl DOUBLE PRECISION,
  error_code INTEGER,
  error_message TEXT,
  position_id INTEGER,
  created_at DOUBLE PRECISION NOT NULL,
  sent_at DOUBLE PRECISION,
  executed_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_mt4_cmd_term ON mt4_commands(terminal_id, status);
CREATE INDEX IF NOT EXISTS ix_mt4_cmd_acc ON mt4_commands(account_login, status);

-- =====================================================================
-- ARAABOT V3 INSTITUTIONAL & SAAS TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS subscription_plans(
  plan_code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  monthly_price_usd DOUBLE PRECISION NOT NULL,
  annual_price_usd DOUBLE PRECISION NOT NULL,
  monthly_price_inr DOUBLE PRECISION NOT NULL,
  annual_price_inr DOUBLE PRECISION NOT NULL,
  max_open_positions INTEGER NOT NULL,
  max_leverage DOUBLE PRECISION NOT NULL,
  allow_live_trading INTEGER NOT NULL DEFAULT 0,
  allow_ai_committee INTEGER NOT NULL DEFAULT 0,
  allow_backtesting INTEGER NOT NULL DEFAULT 1,
  allow_whitelabel INTEGER NOT NULL DEFAULT 0,
  features_json TEXT NOT NULL DEFAULT '[]',
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS user_subscriptions(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE,
  plan_code TEXT NOT NULL DEFAULT 'STARTER',
  billing_cycle TEXT NOT NULL DEFAULT 'MONTHLY',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  trial_ends_at DOUBLE PRECISION,
  current_period_start DOUBLE PRECISION NOT NULL,
  current_period_end DOUBLE PRECISION NOT NULL,
  auto_renew INTEGER NOT NULL DEFAULT 1,
  payment_provider TEXT DEFAULT 'RAZORPAY_UPI',
  external_sub_id TEXT,
  cancelled_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_user_subs_uid ON user_subscriptions(user_id, status);

CREATE TABLE IF NOT EXISTS subscription_invoices(
  id BIGSERIAL PRIMARY KEY,
  invoice_number TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  plan_code TEXT NOT NULL,
  billing_cycle TEXT NOT NULL,
  amount_usd DOUBLE PRECISION NOT NULL,
  amount_inr DOUBLE PRECISION NOT NULL,
  tax_gst_inr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  currency TEXT NOT NULL DEFAULT 'INR',
  payment_method TEXT NOT NULL DEFAULT 'UPI',
  payment_ref TEXT,
  provider_order_id TEXT,
  provider_payment_id TEXT,
  provider_signature TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',
  paid_at DOUBLE PRECISION,
  refunded_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sub_inv_user ON subscription_invoices(user_id, status);

CREATE TABLE IF NOT EXISTS user_security_tokens(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  token_type TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  otp_code TEXT,
  expires_at DOUBLE PRECISION NOT NULL,
  used_at DOUBLE PRECISION,
  ip_address TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_tok_user ON user_security_tokens(user_id, token_type);

CREATE TABLE IF NOT EXISTS ai_committee_logs(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '1m',
  alpha_score DOUBLE PRECISION NOT NULL,
  alpha_verdict TEXT NOT NULL,
  alpha_metrics_json TEXT NOT NULL,
  beta_score DOUBLE PRECISION NOT NULL,
  beta_verdict TEXT NOT NULL,
  beta_indicators_json TEXT NOT NULL,
  gamma_score DOUBLE PRECISION NOT NULL,
  gamma_verdict TEXT NOT NULL,
  gamma_risk_json TEXT NOT NULL,
  consensus_score DOUBLE PRECISION NOT NULL,
  final_action TEXT NOT NULL,
  direction TEXT NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  stop_loss DOUBLE PRECISION NOT NULL,
  take_profit DOUBLE PRECISION NOT NULL,
  risk_reward DOUBLE PRECISION NOT NULL,
  explainable_rationale TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_comm_sym ON ai_committee_logs(symbol, created_at);

CREATE TABLE IF NOT EXISTS backtest_runs(
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  strategy_mode TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  start_ts DOUBLE PRECISION NOT NULL,
  end_ts DOUBLE PRECISION NOT NULL,
  initial_capital DOUBLE PRECISION NOT NULL,
  final_equity DOUBLE PRECISION NOT NULL,
  total_return_pct DOUBLE PRECISION NOT NULL,
  max_drawdown_pct DOUBLE PRECISION NOT NULL,
  win_rate_pct DOUBLE PRECISION NOT NULL,
  profit_factor DOUBLE PRECISION NOT NULL,
  sharpe_ratio DOUBLE PRECISION NOT NULL,
  total_trades INTEGER NOT NULL,
  winning_trades INTEGER NOT NULL,
  losing_trades INTEGER NOT NULL,
  total_fees_usd DOUBLE PRECISION NOT NULL,
  total_slippage_usd DOUBLE PRECISION NOT NULL,
  total_funding_usd DOUBLE PRECISION NOT NULL,
  equity_curve_json TEXT NOT NULL,
  trades_json TEXT NOT NULL,
  passed_validation INTEGER NOT NULL DEFAULT 0,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bt_user ON backtest_runs(user_id, created_at);

CREATE TABLE IF NOT EXISTS order_audit_lifecycle(
  id BIGSERIAL PRIMARY KEY,
  order_uuid TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  position_id INTEGER,
  exchange TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL DEFAULT 'MARKET',
  requested_qty DOUBLE PRECISION NOT NULL,
  filled_qty DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  requested_price DOUBLE PRECISION NOT NULL,
  filled_price DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  leverage DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  margin_allocated DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  fee_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  funding_fee_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  liquidation_price DOUBLE PRECISION DEFAULT 0.0,
  stop_loss DOUBLE PRECISION,
  take_profit DOUBLE PRECISION,
  lifecycle_state TEXT NOT NULL,
  exchange_order_id TEXT,
  broker_confirmed INTEGER NOT NULL DEFAULT 0,
  raw_response_json TEXT,
  error_reason TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ord_life_user ON order_audit_lifecycle(user_id, lifecycle_state);

CREATE TABLE IF NOT EXISTS support_tickets(
  id BIGSERIAL PRIMARY KEY,
  ticket_ref TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  subject TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'TECHNICAL',
  priority TEXT NOT NULL DEFAULT 'NORMAL',
  status TEXT NOT NULL DEFAULT 'OPEN',
  message TEXT NOT NULL,
  admin_reply TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS security_audit_logs(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER,
  actor_role TEXT NOT NULL DEFAULT 'USER',
  action TEXT NOT NULL,
  resource TEXT,
  ip_address TEXT,
  user_agent TEXT,
  status TEXT NOT NULL DEFAULT 'SUCCESS',
  details_json TEXT,
  created_at DOUBLE PRECISION NOT NULL
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
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'CUSTOMER', -- SUPER_ADMIN, OPERATIONS_ADMIN, FINANCE_ADMIN, RISK_MANAGER, SUPPORT_ADMIN, COMPLIANCE_OFFICER, AUDITOR, CUSTOMER
  granted_by INTEGER,
  granted_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_user_roles_uid ON user_roles(user_id, role);

CREATE TABLE IF NOT EXISTS permissions(
  id BIGSERIAL PRIMARY KEY,
  role TEXT NOT NULL,
  permission TEXT NOT NULL,
  module TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kyc_records(
  id BIGSERIAL PRIMARY KEY,
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
  verified_at DOUBLE PRECISION,
  rejection_reason TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kyc_user ON kyc_records(user_id, status);

CREATE TABLE IF NOT EXISTS payments(
  id BIGSERIAL PRIMARY KEY,
  payment_uuid TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  purpose TEXT NOT NULL, -- SUBSCRIPTION, DEPOSIT, WALLET_TOPUP
  amount DOUBLE PRECISION NOT NULL,
  currency TEXT NOT NULL DEFAULT 'INR',
  provider TEXT NOT NULL, -- RAZORPAY, UPI, STRIPE
  provider_order_id TEXT,
  provider_payment_id TEXT,
  provider_signature TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, COMPLETED, FAILED, REFUNDED
  metadata_json TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_payments_uid ON payments(user_id, status);

CREATE TABLE IF NOT EXISTS ledger_accounts(
  account_code TEXT PRIMARY KEY,
  account_name TEXT NOT NULL,
  account_type TEXT NOT NULL, -- ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
  currency TEXT NOT NULL DEFAULT 'USD',
  balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  description TEXT,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries(
  id BIGSERIAL PRIMARY KEY,
  entry_uuid TEXT UNIQUE NOT NULL,
  transaction_ref TEXT NOT NULL,
  debit_account TEXT NOT NULL,
  credit_account TEXT NOT NULL,
  amount DOUBLE PRECISION NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  user_id INTEGER,
  correlation_id TEXT,
  narration TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'POSTED',
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  last_synced_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_ba_co_prov ON broker_accounts(company_id, provider_code);

CREATE TABLE IF NOT EXISTS encrypted_credentials(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  service_name TEXT NOT NULL,
  key_identifier TEXT NOT NULL,
  encrypted_payload TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_enc_creds ON encrypted_credentials(user_id, service_name);

CREATE TABLE IF NOT EXISTS market_assets(
  symbol TEXT PRIMARY KEY,
  base_asset TEXT NOT NULL,
  quote_asset TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_class TEXT NOT NULL, -- CRYPTO, FOREX, METALS, INDICES, STOCKS
  exchange TEXT NOT NULL DEFAULT 'COINDCX',
  min_qty DOUBLE PRECISION NOT NULL DEFAULT 0.0001,
  max_leverage DOUBLE PRECISION NOT NULL DEFAULT 100.0,
  tick_size DOUBLE PRECISION NOT NULL DEFAULT 0.0001,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS market_prices(
  symbol TEXT PRIMARY KEY,
  price DOUBLE PRECISION NOT NULL,
  bid DOUBLE PRECISION,
  ask DOUBLE PRECISION,
  high_24h DOUBLE PRECISION,
  low_24h DOUBLE PRECISION,
  volume_24h DOUBLE PRECISION,
  change_24h DOUBLE PRECISION,
  data_source TEXT NOT NULL DEFAULT 'COINDCX_REST',
  is_delayed INTEGER NOT NULL DEFAULT 0,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlists(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  symbols_json TEXT NOT NULL DEFAULT '[]',
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
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
  win_rate_live DOUBLE PRECISION DEFAULT 78.5,
  win_rate_paper DOUBLE PRECISION DEFAULT 82.0,
  win_rate_backtest DOUBLE PRECISION DEFAULT 85.4,
  profit_factor DOUBLE PRECISION DEFAULT 2.45,
  max_drawdown DOUBLE PRECISION DEFAULT 8.5,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_versions(
  id BIGSERIAL PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  version_num TEXT NOT NULL,
  code_ref TEXT,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  change_notes TEXT,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_subscriptions(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  strategy_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  subscribed_at DOUBLE PRECISION NOT NULL,
  expires_at DOUBLE PRECISION
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
  capital_allocated DOUBLE PRECISION NOT NULL DEFAULT 100.0,
  risk_pct DOUBLE PRECISION NOT NULL DEFAULT 2.0,
  leverage DOUBLE PRECISION NOT NULL DEFAULT 100.0,
  max_positions INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL DEFAULT 'STOPPED', -- STOPPED, RUNNING, PAUSED
  execution_mode TEXT NOT NULL DEFAULT 'PAPER', -- PAPER, DOUBLE PRECISION
  last_heartbeat_at DOUBLE PRECISION,
  last_error TEXT,
  supervisor_pid INTEGER,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trading_bots_uid ON trading_bots(user_id, status);

CREATE TABLE IF NOT EXISTS bot_configs(
  bot_id TEXT PRIMARY KEY,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  custom_rules_json TEXT NOT NULL DEFAULT '{}',
  tp_pct DOUBLE PRECISION NOT NULL DEFAULT 0.85,
  sl_pct DOUBLE PRECISION NOT NULL DEFAULT 0.45,
  trailing_stop_pct DOUBLE PRECISION NOT NULL DEFAULT 0.25,
  schedule_json TEXT NOT NULL DEFAULT '{}',
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_execution_logs(
  id BIGSERIAL PRIMARY KEY,
  bot_id TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  level TEXT NOT NULL DEFAULT 'INFO',
  message TEXT NOT NULL,
  details_json TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bot_logs ON bot_execution_logs(bot_id, created_at);

CREATE TABLE IF NOT EXISTS ai_models(
  model_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  provider TEXT NOT NULL, -- GOOGLE, ANTHROPIC, OPENAI, DETERMINISTIC
  version TEXT NOT NULL,
  model_type TEXT NOT NULL DEFAULT 'MULTIMODAL_REASONING',
  approval_status TEXT NOT NULL DEFAULT 'APPROVED', -- APPROVED, PENDING_REVIEW, DEPRECATED
  accuracy_score DOUBLE PRECISION DEFAULT 88.5,
  drift_metric DOUBLE PRECISION DEFAULT 0.02,
  cost_per_1k_tokens DOUBLE PRECISION DEFAULT 0.00015,
  is_default INTEGER NOT NULL DEFAULT 0,
  approved_by INTEGER,
  approved_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_signals(
  signal_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  asset_class TEXT NOT NULL DEFAULT 'CRYPTO',
  timeframe TEXT NOT NULL DEFAULT '1m',
  direction TEXT NOT NULL, -- BUY, SELL, HOLD
  entry_zone_low DOUBLE PRECISION NOT NULL,
  entry_zone_high DOUBLE PRECISION NOT NULL,
  stop_loss DOUBLE PRECISION NOT NULL,
  target_1 DOUBLE PRECISION NOT NULL,
  target_2 DOUBLE PRECISION,
  target_3 DOUBLE PRECISION,
  risk_reward_ratio DOUBLE PRECISION NOT NULL,
  strategy_name TEXT NOT NULL,
  technical_rationale TEXT NOT NULL,
  ai_explanation TEXT NOT NULL,
  confidence_score DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, EXPIRED, TARGET_HIT, STOP_HIT, CANCELLED
  actual_outcome TEXT DEFAULT 'PENDING',
  win_loss TEXT DEFAULT 'PENDING',
  pnl_pct DOUBLE PRECISION DEFAULT 0.0,
  expires_at DOUBLE PRECISION NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
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
  token_cost_est DOUBLE PRECISION DEFAULT 0.0,
  latency_ms DOUBLE PRECISION DEFAULT 0.0,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_decisions ON ai_decisions(user_id, created_at);

CREATE TABLE IF NOT EXISTS ai_evaluations(
  id BIGSERIAL PRIMARY KEY,
  model_id TEXT NOT NULL,
  period_start DOUBLE PRECISION NOT NULL,
  period_end DOUBLE PRECISION NOT NULL,
  total_predictions INTEGER NOT NULL DEFAULT 0,
  correct_predictions INTEGER NOT NULL DEFAULT 0,
  win_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  brier_score DOUBLE PRECISION DEFAULT 0.0,
  drift_detected INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS order_fills(
  id BIGSERIAL PRIMARY KEY,
  fill_id TEXT UNIQUE NOT NULL,
  order_uuid TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  exchange_fill_id TEXT,
  fill_qty DOUBLE PRECISION NOT NULL,
  fill_price DOUBLE PRECISION NOT NULL,
  fee_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  fee_currency TEXT NOT NULL DEFAULT 'USDT',
  is_partial INTEGER NOT NULL DEFAULT 0,
  executed_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_fills_uuid ON order_fills(order_uuid);

CREATE TABLE IF NOT EXISTS trades(
  trade_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  bot_id TEXT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  exit_price DOUBLE PRECISION NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  leverage DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  margin DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  pnl_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  fee_total DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  duration_seconds DOUBLE PRECISION DEFAULT 0.0,
  entry_reason TEXT,
  exit_reason TEXT,
  strategy_id TEXT,
  broker_code TEXT NOT NULL DEFAULT 'COINDCX',
  execution_mode TEXT NOT NULL DEFAULT 'PAPER',
  opened_at DOUBLE PRECISION NOT NULL,
  closed_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trades_user ON trades(user_id, closed_at);

CREATE TABLE IF NOT EXISTS backtest_jobs(
  job_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '1m',
  start_date DOUBLE PRECISION NOT NULL,
  end_date DOUBLE PRECISION NOT NULL,
  initial_capital DOUBLE PRECISION NOT NULL DEFAULT 10000.0,
  commission_pct DOUBLE PRECISION NOT NULL DEFAULT 0.04,
  slippage_pct DOUBLE PRECISION NOT NULL DEFAULT 0.02,
  status TEXT NOT NULL DEFAULT 'QUEUED', -- QUEUED, RUNNING, COMPLETED, FAILED
  progress_pct INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  completed_at DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS backtest_results(
  job_id TEXT PRIMARY KEY,
  total_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  net_profit DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  win_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  loss_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  profit_factor DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  sharpe_ratio DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  max_drawdown_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  avg_win DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  avg_loss DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  equity_curve_json TEXT NOT NULL DEFAULT '[]',
  monthly_returns_json TEXT NOT NULL DEFAULT '[]',
  trade_history_json TEXT NOT NULL DEFAULT '[]',
  walk_forward_json TEXT NOT NULL DEFAULT '{}',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_limits(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE,
  max_daily_loss_usd DOUBLE PRECISION NOT NULL DEFAULT 250.0,
  max_weekly_loss_usd DOUBLE PRECISION NOT NULL DEFAULT 750.0,
  max_monthly_loss_usd DOUBLE PRECISION NOT NULL DEFAULT 2000.0,
  max_account_exposure_usd DOUBLE PRECISION NOT NULL DEFAULT 50000.0,
  max_position_size_usd DOUBLE PRECISION NOT NULL DEFAULT 10000.0,
  max_concurrent_positions INTEGER NOT NULL DEFAULT 5,
  max_leverage DOUBLE PRECISION NOT NULL DEFAULT 100.0,
  per_asset_limits_json TEXT NOT NULL DEFAULT '{}',
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events(
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  bot_id TEXT,
  symbol TEXT,
  event_type TEXT NOT NULL, -- LIMIT_BREACH, CIRCUIT_BREAKER, VOLATILITY_ALERT, KILL_SWITCH, ORDER_VETO
  severity TEXT NOT NULL DEFAULT 'WARNING', -- INFO, WARNING, CRITICAL
  rule_name TEXT NOT NULL,
  details_json TEXT,
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_journal_uid ON trading_journals(user_id);

CREATE TABLE IF NOT EXISTS notifications(
  id BIGSERIAL PRIMARY KEY,
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
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notif_uid ON notifications(user_id, is_read);

CREATE TABLE IF NOT EXISTS audit_logs(
  id BIGSERIAL PRIMARY KEY,
  log_uuid TEXT UNIQUE NOT NULL,
  user_id INTEGER,
  actor_role TEXT NOT NULL DEFAULT 'USER',
  action TEXT NOT NULL,
  resource TEXT,
  ip_address TEXT,
  user_agent TEXT,
  status TEXT NOT NULL DEFAULT 'SUCCESS',
  details_json TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_at ON audit_logs(created_at);

CREATE TABLE IF NOT EXISTS system_incidents(
  incident_id TEXT PRIMARY KEY,
  service_name TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'WARNING', -- LOW, MEDIUM, HIGH, CRITICAL
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN', -- OPEN, INVESTIGATING, RESOLVED
  detected_at DOUBLE PRECISION NOT NULL,
  resolved_at DOUBLE PRECISION,
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
  created_at DOUBLE PRECISION NOT NULL,
  processed_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_event_outbox_st ON event_outbox(status, created_at);


-- === MIGRATION 001: company_rbac_mfa_and_audit ===

CREATE TABLE IF NOT EXISTS schema_migrations(
  version TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at DOUBLE PRECISION NOT NULL,
  checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies(
  id BIGSERIAL PRIMARY KEY,
  company_code TEXT NOT NULL UNIQUE,
  legal_name TEXT NOT NULL,
  cin_or_reg_no TEXT DEFAULT '',
  pan TEXT DEFAULT '',
  gstin TEXT DEFAULT '',
  base_currency TEXT NOT NULL DEFAULT 'INR',
  proprietary_only INTEGER NOT NULL DEFAULT 1,
  compliance_status TEXT NOT NULL DEFAULT 'REVIEW_PENDING',
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS roles(
  role_code TEXT PRIMARY KEY,
  role_name TEXT NOT NULL,
  description TEXT DEFAULT '',
  hierarchy_level INTEGER NOT NULL DEFAULT 10,
  created_at DOUBLE PRECISION NOT NULL
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
  id BIGSERIAL PRIMARY KEY,
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
  locked_until DOUBLE PRECISION NOT NULL DEFAULT 0,
  last_login_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  expires_at DOUBLE PRECISION NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  last_seen DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  decided_at DOUBLE PRECISION,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (requested_by) REFERENCES company_users(id)
);
CREATE INDEX IF NOT EXISTS ix_trading_approvals_status ON trading_approvals(company_id, status, created_at);

CREATE TABLE IF NOT EXISTS company_audit_logs(
  id BIGSERIAL PRIMARY KEY,
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
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_company_audit_cid_at ON company_audit_logs(company_id, created_at);

CREATE TABLE IF NOT EXISTS system_events(
  id BIGSERIAL PRIMARY KEY,
  event_uuid TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'INFO',
  source TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT DEFAULT '{}',
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_system_events_at ON system_events(severity, created_at);


-- === MIGRATION 002: company_finance_and_pools ===

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
  token_expires_at DOUBLE PRECISION,
  last_synced_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  updated_at DOUBLE PRECISION NOT NULL,
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
  updated_at DOUBLE PRECISION NOT NULL,
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
  last_broker_sync_at DOUBLE PRECISION,
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (pool_id) REFERENCES company_capital_pools(pool_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ccm_pool_at ON company_capital_movements(pool_id, created_at);


-- === MIGRATION 003: company_trading_oms_ledger_recon ===

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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL
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
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
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
  executed_at DOUBLE PRECISION NOT NULL,
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
  opened_at DOUBLE PRECISION NOT NULL,
  closed_at DOUBLE PRECISION,
  updated_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL
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
  started_at DOUBLE PRECISION NOT NULL,
  completed_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
  resolved_at DOUBLE PRECISION,
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
  updated_at DOUBLE PRECISION NOT NULL
);


-- === MIGRATION 004: company_foundation_governance_hr_erp ===

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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  authorized_at DOUBLE PRECISION NOT NULL,
  roc_filing_ref TEXT DEFAULT '',
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS statutory_registers(
  register_id TEXT PRIMARY KEY,
  company_id INTEGER NOT NULL,
  register_type TEXT NOT NULL,
  entry_ref TEXT NOT NULL,
  particulars TEXT NOT NULL,
  legal_reference TEXT NOT NULL,
  entered_at DOUBLE PRECISION NOT NULL,
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
  submitted_at DOUBLE PRECISION NOT NULL,
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
  completed_at DOUBLE PRECISION,
  acknowledgement_ref TEXT DEFAULT '',
  assigned_to INTEGER,
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  issued_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  disbursed_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
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
  days_count DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'APPROVED',
  approved_by INTEGER,
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);


-- === MIGRATION 005: araabot_multi_broker_connection_center ===

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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  last_synced_at DOUBLE PRECISION,
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
  token_expiry_ts DOUBLE PRECISION,
  static_egress_ip TEXT DEFAULT '',
  whitelisted_ips_json TEXT NOT NULL DEFAULT '[]',
  withdrawal_disabled INTEGER NOT NULL DEFAULT 1,
  key_fingerprint TEXT NOT NULL,
  updated_by INTEGER,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS broker_account_capabilities(
  account_id TEXT PRIMARY KEY,
  allowed_segments_json TEXT NOT NULL DEFAULT '["NSE_EQ"]',
  allowed_products_json TEXT NOT NULL DEFAULT '["CNC"]',
  order_types_json TEXT NOT NULL DEFAULT '["MARKET", "LIMIT"]',
  max_leverage_multiplier INTEGER NOT NULL DEFAULT 1,
  shorting_allowed INTEGER NOT NULL DEFAULT 0,
  updated_at DOUBLE PRECISION NOT NULL,
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
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (account_id) REFERENCES broker_accounts(account_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_bhe_acct ON broker_health_events(account_id, created_at);


-- === MIGRATION 006: central_super_admin_sso_and_apps ===

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
  locked_until DOUBLE PRECISION NOT NULL DEFAULT 0,
  approval_limit_paise INTEGER NOT NULL DEFAULT 0,
  access_expiry_ts DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  last_login_at DOUBLE PRECISION
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
  last_synced_at DOUBLE PRECISION,
  error_status TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS application_sessions(
  session_id TEXT PRIMARY KEY,
  sso_token TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL,
  app_id TEXT NOT NULL,
  ip_address TEXT DEFAULT '',
  user_agent TEXT DEFAULT '',
  is_revoked INTEGER NOT NULL DEFAULT 0,
  expires_at DOUBLE PRECISION NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (requested_by) REFERENCES central_users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ar_status ON approval_requests(status, category);

CREATE TABLE IF NOT EXISTS approval_actions(
  action_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  action TEXT NOT NULL, -- 'APPROVE', 'REJECT', 'REQUEST_CHANGES'
  actor_user_id TEXT NOT NULL,
  comments TEXT DEFAULT '',
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_se_type_at ON security_events(event_type, created_at);

CREATE TABLE IF NOT EXISTS application_health(
  health_id TEXT PRIMARY KEY,
  app_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'HEALTHY',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  details_json TEXT NOT NULL DEFAULT '{}',
  checked_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (app_id) REFERENCES application_registry(app_id) ON DELETE CASCADE
);


-- === MIGRATION 007: corporate_website_and_owner_cms ===

CREATE TABLE IF NOT EXISTS cms_theme_settings(
  setting_key TEXT PRIMARY KEY,
  setting_val TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'THEME',
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_pages(
  page_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  meta_title TEXT NOT NULL,
  meta_description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PUBLISHED',
  version INTEGER NOT NULL DEFAULT 1,
  published_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_sections(
  section_id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL,
  section_key TEXT NOT NULL,
  section_title TEXT NOT NULL,
  content_json TEXT NOT NULL,
  order_index INTEGER NOT NULL DEFAULT 0,
  is_visible INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS cms_page_versions(
  version_id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  content_snapshot_json TEXT NOT NULL,
  saved_by TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (page_id) REFERENCES cms_pages(page_id) ON DELETE CASCADE
);


-- === MIGRATION 008: company_finance_and_corporate_accounting ===

CREATE TABLE IF NOT EXISTS chart_of_accounts(
  account_code TEXT PRIMARY KEY,
  account_name TEXT NOT NULL,
  account_type TEXT NOT NULL, -- ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
  currency TEXT NOT NULL DEFAULT 'INR',
  parent_code TEXT DEFAULT '',
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);


-- === MIGRATION 009: araa_brokerage_architecture_and_gates ===

CREATE TABLE IF NOT EXISTS brokerage_products(
  product_code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  exchange TEXT NOT NULL, -- NSE, BSE, MCX, COINDCX
  asset_class TEXT NOT NULL, -- EQUITY_CASH, EQUITY_DERIVATIVE, COMMODITY, CRYPTO_SPOT
  brokerage_mode TEXT NOT NULL DEFAULT 'PROP_ONLY', -- PROP_ONLY, CUSTOMER_RETAIL
  is_trading_enabled INTEGER NOT NULL DEFAULT 1,
  margin_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  stt_tax_bps DOUBLE PRECISION NOT NULL DEFAULT 10.0,
  sebi_turnover_bps DOUBLE PRECISION NOT NULL DEFAULT 0.1,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_brokerage_accounts(
  customer_account_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  pan_masked TEXT NOT NULL,
  kyc_status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, VERIFIED, REJECTED
  aml_risk_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  margin_trading_authorized INTEGER NOT NULL DEFAULT 0,
  account_status TEXT NOT NULL DEFAULT 'SUSPENDED_PENDING_REGULATORY_LICENSE',
  opened_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS service_authorization_register(
  service_code TEXT PRIMARY KEY,
  service_name TEXT NOT NULL,
  division TEXT NOT NULL,
  is_authorized INTEGER NOT NULL DEFAULT 0, -- STRICT LEGAL GATE
  regulatory_license_ref TEXT DEFAULT '',
  legal_signoff_by TEXT DEFAULT '',
  authorized_at DOUBLE PRECISION,
  reason_for_gate TEXT NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);


-- === MIGRATION 010: araa_wallet_infrastructure_and_ledger ===

CREATE TABLE IF NOT EXISTS company_treasury_vaults(
  vault_id TEXT PRIMARY KEY,
  vault_name TEXT NOT NULL,
  vault_type TEXT NOT NULL, -- FIAT_INR, CRYPTO_COLD_MPC, CRYPTO_WARM_OPERATIONAL
  currency TEXT NOT NULL, -- INR, USDT, BTC, ETH
  balance_paise INTEGER NOT NULL DEFAULT 0,
  crypto_balance_atomic TEXT NOT NULL DEFAULT '0',
  multisig_threshold TEXT NOT NULL DEFAULT '2-of-3',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_deposit_addresses(
  address_id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  blockchain_network TEXT NOT NULL, -- TRON_TRC20, ETH_ERC20, BSC_BEP20, BTC_MAINNET
  public_address TEXT NOT NULL UNIQUE,
  derivation_index INTEGER NOT NULL,
  is_whitelisted INTEGER NOT NULL DEFAULT 1,
  created_at DOUBLE PRECISION NOT NULL,
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
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  FOREIGN KEY (vault_id) REFERENCES company_treasury_vaults(vault_id) ON DELETE CASCADE
);
