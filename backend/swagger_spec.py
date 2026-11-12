"""OpenAPI 3.0.0 Specification for Trade Pro Trading Platform API."""

SWAGGER_SPEC = {
    "openapi": "3.0.0",
    "info": {
        "title": "Trade Pro API",
        "description": "Comprehensive API specification for Trade Pro: High-frequency institutional algorithmic trading platform with Araa AI (Gemini 2.5/3.8 Flash), live multi-market price feeds, paper trading, 200x intraday leverage, and wallet settlement.",
        "version": "2.4.0",
        "contact": {
            "name": "Trade Pro Engineering",
            "url": "http://localhost:7777"
        }
    },
    "servers": [
        {
            "url": "http://localhost:5050",
            "description": "Local API Server"
        }
    ],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Token",
                "description": "Session authentication token obtained from /api/auth/login or /api/auth/signup"
            }
        },
        "schemas": {
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": False},
                    "error": {"type": "string", "example": "Invalid credentials"}
                }
            },
            "HealthResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "ONLINE"},
                    "app": {"type": "string", "example": "Trade Pro - connected full stack"},
                    "mode": {"type": "string", "example": "PAPER TRADING ON LIVE MARKET PRICES"},
                    "real_money": {"type": "boolean", "example": False},
                    "feed": {"type": "string", "example": "LIVE"},
                    "bot_running": {"type": "boolean", "example": True},
                    "symbols_tracked": {"type": "integer", "example": 976},
                    "uptime_seconds": {"type": "integer", "example": 120}
                }
            },
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 28},
                    "email": {"type": "string", "example": "autotrader_pro@gmail.com"},
                    "name": {"type": "string", "example": "Auto Trader Pro"},
                    "bot_enabled": {"type": "integer", "example": 1},
                    "bot_mode": {"type": "string", "example": "BOOST"},
                    "bot_leverage": {"type": "number", "example": 500.0},
                    "bot_max_positions": {"type": "integer", "example": 3},
                    "bot_risk_pct": {"type": "number", "example": 20.0}
                }
            },
            "Wallet": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "example": 28},
                    "deposit_balance": {"type": "number", "example": 50000.0},
                    "profit_balance": {"type": "number", "example": 739.46},
                    "locked_balance": {"type": "number", "example": 12556.21},
                    "total_deposited": {"type": "number", "example": 51000.0},
                    "starting_balance": {"type": "number", "example": 51000.0},
                    "target_amount": {"type": "number", "example": 76500.0}
                }
            },
            "Position": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 3274},
                    "user_id": {"type": "integer", "example": 28},
                    "symbol": {"type": "string", "example": "AUDUSD"},
                    "source": {"type": "string", "example": "BOT"},
                    "side": {"type": "string", "enum": ["LONG", "SHORT"], "example": "SHORT"},
                    "qty": {"type": "number", "example": 2659390.8},
                    "entry_price": {"type": "number", "example": 0.69213},
                    "current_price": {"type": "number", "example": 0.69209},
                    "margin": {"type": "number", "example": 9203.22},
                    "leverage": {"type": "number", "example": 500.0},
                    "unrealized_pnl": {"type": "number", "example": 109.46},
                    "realized_pnl": {"type": "number", "example": 663.54},
                    "target_pct": {"type": "number", "example": 0.4},
                    "stop_pct": {"type": "number", "example": 0.2},
                    "status": {"type": "string", "enum": ["OPEN", "CLOSED"], "example": "OPEN"},
                    "category": {"type": "string", "example": "FOREX"},
                    "ai_win_prob": {"type": "number", "example": 86.0}
                }
            }
        }
    },
    "paths": {
        "/api/health": {
            "get": {
                "summary": "Platform Health & Engine Status",
                "tags": ["System"],
                "responses": {
                    "200": {
                        "description": "System operational status",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HealthResponse"}}}
                    }
                }
            }
        },
        "/api/ticker": {
            "get": {
                "summary": "Live Top Assets Ticker",
                "tags": ["Market Data"],
                "responses": {
                    "200": {
                        "description": "Real-time scraped asset quotes for ticker tape display",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/coins": {
            "get": {
                "summary": "Tradeable Instruments Catalog",
                "tags": ["Market Data"],
                "responses": {
                    "200": {
                        "description": "List of all active instruments across 7 asset categories",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/countries": {
            "get": {
                "summary": "World Equities Country Listing",
                "tags": ["Market Data"],
                "responses": {
                    "200": {
                        "description": "List of supported countries and exchanges for world stocks",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/markets": {
            "get": {
                "summary": "Full Markets Screener",
                "tags": ["Market Data"],
                "parameters": [
                    {"name": "category", "in": "query", "schema": {"type": "string"}, "description": "Filter by FOREX, METALS, INDICES, STOCKS, COMPANIES, WORLD, CRYPTO"},
                    {"name": "search", "in": "query", "schema": {"type": "string"}, "description": "Search keyword or symbol prefix"},
                    {"name": "country", "in": "query", "schema": {"type": "string"}, "description": "Filter world stocks by country"},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 60}, "description": "Max rows to return"}
                ],
                "responses": {
                    "200": {
                        "description": "Screened instruments with live quotes and 24h change",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/market/{symbol}": {
            "get": {
                "summary": "Live Candlestick Stream & Quote",
                "tags": ["Market Data"],
                "parameters": [
                    {"name": "symbol", "in": "path", "required": True, "schema": {"type": "string"}, "example": "EURUSD"},
                    {"name": "interval", "in": "query", "schema": {"type": "string", "default": "1m"}, "description": "Candle timeframe"},
                    {"name": "candles", "in": "query", "schema": {"type": "integer", "default": 120}, "description": "Number of candle bars"}
                ],
                "responses": {
                    "200": {
                        "description": "Candle history and real-time bid/ask quote",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/auth/signup": {
            "post": {
                "summary": "Create Account",
                "tags": ["Authentication"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "password"],
                                "properties": {
                                    "email": {"type": "string", "example": "trader@gmail.com"},
                                    "password": {"type": "string", "example": "password123"},
                                    "name": {"type": "string", "example": "Trader Pro"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Account created and session token issued"},
                    "400": {"description": "Email already exists or invalid password"}
                }
            }
        },
        "/api/auth/login": {
            "post": {
                "summary": "User Login",
                "tags": ["Authentication"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "password"],
                                "properties": {
                                    "email": {"type": "string", "example": "autotrader_pro@gmail.com"},
                                    "password": {"type": "string", "example": "password123"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Login successful with token and wallet data"},
                    "401": {"description": "Invalid email or password"}
                }
            }
        },
        "/api/auth/logout": {
            "post": {
                "summary": "User Logout",
                "tags": ["Authentication"],
                "security": [{"ApiKeyAuth": []}],
                "responses": {
                    "200": {"description": "Session invalidated"}
                }
            }
        },
        "/api/auth/me": {
            "get": {
                "summary": "Current Session Verification",
                "tags": ["Authentication"],
                "security": [{"ApiKeyAuth": []}],
                "responses": {
                    "200": {"description": "Current user record"}
                }
            }
        },
        "/api/account": {
            "get": {
                "summary": "Live Portfolio & Wallet State",
                "tags": ["Account & Wallet"],
                "security": [{"ApiKeyAuth": []}],
                "responses": {
                    "200": {
                        "description": "User balances, open positions, closed trade history, and analytics",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/deposit": {
            "post": {
                "summary": "Deposit Trading Capital",
                "tags": ["Account & Wallet"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["amount"],
                                "properties": {
                                    "amount": {"type": "number", "example": 50000.0},
                                    "method": {"type": "string", "example": "UPI"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Capital funded instantly to wallet"}
                }
            }
        },
        "/api/withdraw": {
            "post": {
                "summary": "Withdraw Profits",
                "tags": ["Account & Wallet"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["amount"],
                                "properties": {
                                    "amount": {"type": "number", "example": 1000.0},
                                    "method": {"type": "string", "example": "BANK_TRANSFER"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Withdrawal request submitted (30% brokerage applied)"}
                }
            }
        },
        "/api/goal": {
            "post": {
                "summary": "Set Target Profit Goal",
                "tags": ["Account & Wallet"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["target"],
                                "properties": {
                                    "target": {"type": "number", "example": 75000.0}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Target goal updated"}
                }
            }
        },
        "/api/trade": {
            "post": {
                "summary": "Open Manual Trade (1x to 500x Leverage)",
                "tags": ["Trading Engine"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["symbol", "side", "margin"],
                                "properties": {
                                    "symbol": {"type": "string", "example": "BTCUSDT"},
                                    "side": {"type": "string", "enum": ["LONG", "SHORT"], "example": "LONG"},
                                    "margin": {"type": "number", "example": 5000.0},
                                    "leverage": {"type": "number", "default": 500.0, "example": 500.0}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Position filled instantly on live quotes"},
                    "400": {"description": "Insufficient balance or invalid side"}
                }
            }
        },
        "/api/trade/close": {
            "post": {
                "summary": "Close Active Position",
                "tags": ["Trading Engine"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["position_id"],
                                "properties": {
                                    "position_id": {"type": "integer", "example": 3281}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Position closed and net P&L settled to wallet"}
                }
            }
        },
        "/api/order": {
            "post": {
                "summary": "Place Limit Order",
                "tags": ["Trading Engine"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["symbol", "side", "price", "margin"],
                                "properties": {
                                    "symbol": {"type": "string", "example": "ETHUSDT"},
                                    "side": {"type": "string", "enum": ["LONG", "SHORT"], "example": "LONG"},
                                    "price": {"type": "number", "example": 3200.0},
                                    "margin": {"type": "number", "example": 2000.0}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Limit order resting in book"}
                }
            }
        },
        "/api/orders": {
            "get": {
                "summary": "Get Resting Limit Orders",
                "tags": ["Trading Engine"],
                "security": [{"ApiKeyAuth": []}],
                "responses": {
                    "200": {"description": "List of pending limit orders"}
                }
            }
        },
        "/api/order/{oid}": {
            "delete": {
                "summary": "Cancel Pending Limit Order",
                "tags": ["Trading Engine"],
                "security": [{"ApiKeyAuth": []}],
                "parameters": [
                    {"name": "oid", "in": "path", "required": True, "schema": {"type": "integer"}, "example": 10}
                ],
                "responses": {
                    "200": {"description": "Order cancelled and locked margin released"}
                }
            }
        },
        "/api/bot/config": {
            "post": {
                "summary": "Configure AI Bot Settings (Mode & 500x Leverage)",
                "tags": ["AI Bot & Automation"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "enabled": {"type": "boolean", "example": True},
                                    "max_positions": {"type": "integer", "example": 3},
                                    "risk_pct": {"type": "number", "example": 20.0},
                                    "mode": {"type": "string", "enum": ["BOOST", "CONTINUOUS", "SCALP", "AGGRESSIVE", "CONSERVATIVE"], "example": "BOOST"},
                                    "leverage": {"type": "number", "example": 500.0}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Bot configuration updated and immediate trade scan triggered"}
                }
            }
        },
        "/api/bot/analysis": {
            "get": {
                "summary": "A-to-Z Market Analysis Matrix",
                "tags": ["AI Bot & Automation"],
                "responses": {
                    "200": {
                        "description": "Full cycle breakdown of 976 instruments, volatility pass rates, and ranked setups",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/ai/predictions": {
            "get": {
                "summary": "Araa AI Pre-Entry Predictions Audit Trail",
                "tags": ["AI Bot & Automation"],
                "security": [{"ApiKeyAuth": []}],
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}, "description": "Max audit rows to return"}
                ],
                "responses": {
                    "200": {
                        "description": "Complete audit trail of Gemini AI approvals, win probabilities, and rationales",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/api/gemini/status": {
            "get": {
                "summary": "Araa AI & Gemini Neural Connectivity",
                "tags": ["AI Bot & Automation"],
                "responses": {
                    "200": {
                        "description": "Status of Gemini, Claude, and ChatGPT consensus engines"
                    }
                }
            }
        },
        "/api/gemini/config": {
            "post": {
                "summary": "Update AI Engine API Keys & Model",
                "tags": ["AI Bot & Automation"],
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "api_key": {"type": "string", "example": "AIzaSy..."},
                                    "model": {"type": "string", "example": "gemini-2.5-flash"},
                                    "provider": {"type": "string", "example": "gemini"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "AI provider connection validated"}
                }
            }
        },
        "/api/admin/overview": {
            "get": {
                "summary": "Platform Admin Metrics & P&L",
                "tags": ["Admin Portal"],
                "responses": {
                    "200": {"description": "Global deposit, profit, brokerage, and active bot metrics"}
                }
            }
        },
        "/api/admin/users": {
            "get": {
                "summary": "List All Registered Accounts",
                "tags": ["Admin Portal"],
                "responses": {
                    "200": {"description": "User registry with wallet balances, bot modes, and leverage"}
                }
            }
        },
        "/api/admin/bot/start": {
            "post": {
                "summary": "Global Master Switch: Turn Bot ON",
                "tags": ["Admin Portal"],
                "responses": {
                    "200": {"description": "Global autonomous trading started"}
                }
            }
        },
        "/api/admin/bot/stop": {
            "post": {
                "summary": "Global Master Switch: Turn Bot OFF",
                "tags": ["Admin Portal"],
                "responses": {
                    "200": {"description": "Global autonomous trading paused"}
                }
            }
        },
        "/api/admin/create-profit-link": {
            "post": {
                "summary": "Generate Admin Profit Claim Link",
                "tags": ["Admin Portal"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["user_id", "gross"],
                                "properties": {
                                    "user_id": {"type": "integer", "example": 28},
                                    "gross": {"type": "number", "example": 2500.0}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Profit claim link token generated"}
                }
            }
        },
        "/api/admin/withdrawals": {
            "get": {
                "summary": "List User Withdrawal Requests",
                "tags": ["Admin Portal"],
                "responses": {
                    "200": {"description": "Pending and completed user withdrawal requests"}
                }
            }
        },
        "/api/admin/withdrawals/{wid}/{action}": {
            "post": {
                "summary": "Approve or Reject Withdrawal",
                "tags": ["Admin Portal"],
                "parameters": [
                    {"name": "wid", "in": "path", "required": True, "schema": {"type": "integer"}, "example": 1},
                    {"name": "action", "in": "path", "required": True, "schema": {"type": "string", "enum": ["approve", "reject"]}, "example": "approve"}
                ],
                "responses": {
                    "200": {"description": "Withdrawal processed"}
                }
            }
        },
        "/api/admin/brokerage": {
            "get": {
                "summary": "Brokerage Revenue Ledger",
                "tags": ["Admin Portal"],
                "responses": {
                    "200": {"description": "Platform 30% brokerage fee ledger"}
                }
            }
        }
    }
}
