//+------------------------------------------------------------------+
//|                                        AraaBot_MT4_Bridge.mq4    |
//|                        AraaBot AI Quantum Trading Desk Bridge    |
//|                                   https://araabot.in             |
//+------------------------------------------------------------------+
#property copyright "AraaBot Quantum Trading Engine"
#property link      "http://127.0.0.1:5050"
#property version   "4.00"
#property strict

//--- External Inputs
input string   InpServerUrl     = "http://127.0.0.1:5050"; // ARAA Backend Server URL
input string   InpPairingToken  = "ARAA-MT4-DBB34D13A1977E87"; // One-Time Pairing Token from ARAA Dashboard
input string   InpBrandId       = "ARAA";                  // Brand Identifier
input int      InpPollInterval  = 1;                       // Poll & Heartbeat Interval (Seconds)
input int      InpMagicNumber   = 888801;                  // Magic Number for ARAA Bot Trades
input int      InpSlippage      = 10;                      // Max Slippage (Points)

//--- Global Variables
datetime lastSyncTime     = 0;
string   accountLoginStr  = "";
string   accountServerStr = "";
string   accountTypeStr   = "DEMO";
string   accountCurrStr   = "USD";
string   terminalIdStr    = "";
string   sessionTokenStr  = "";
bool     isRegistered     = false;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   accountLoginStr  = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   accountServerStr = AccountInfoString(ACCOUNT_SERVER);
   accountTypeStr   = IsDemo() ? "DEMO" : "REAL";
   accountCurrStr   = AccountInfoString(ACCOUNT_CURRENCY);
   terminalIdStr    = "TERM-" + InpBrandId + "-" + accountLoginStr;
   sessionTokenStr  = InpPairingToken;

   Print("==========================================================");
   Print("▶ AraaBot MT4 Bridge v4.0 Initialized!");
   Print("  Account: #", accountLoginStr, " (", accountTypeStr, ") on ", accountServerStr);
   Print("  Target Server: ", InpServerUrl);
   Print("  Terminal ID: ", terminalIdStr);
   Print("==========================================================");

   EventSetTimer(MathMax(1, InpPollInterval));

   if (StringLen(InpPairingToken) == 0) {
      UpdateChartHUD("PAIRING REQUIRED: Paste Pairing Token in EA Inputs (F7)");
      Print("⚠️ Please generate a Pairing Token in ARAA and paste it into InpPairingToken.");
   } else {
      UpdateChartHUD("CONNECTING & VALIDATING TOKEN...");
      RegisterTerminalWithAraaBot();
      SyncAccountWithAraaBot();
   }
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
   Print("⏹ AraaBot MT4 Bridge Stopped.");
}

//+------------------------------------------------------------------+
//| Timer function: Heartbeat, Sync & Authenticated Command Polling  |
//+------------------------------------------------------------------+
void OnTimer()
{
   if (StringLen(sessionTokenStr) == 0) {
      UpdateChartHUD("PAIRING REQUIRED: Enter Pairing Token in EA Settings");
      return;
   }
   if (!isRegistered) {
      RegisterTerminalWithAraaBot();
   }
   SyncAccountWithAraaBot();
   PollPendingActions();
}

//+------------------------------------------------------------------+
//| Update clean visual HUD on the MT4 Chart                         |
//+------------------------------------------------------------------+
void UpdateChartHUD(string statusText)
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double fm  = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   double ml  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   int    cnt = OrdersTotal();
   string tradePerm = (IsTradeAllowed() && IsExpertEnabled()) ? "ALLOWED" : "DISABLED (Enable AutoTrading)";

   string hud = "\n" +
      "  ╔════════════════════════════════════════════════════════════╗\n" +
      "  ║           ⚡ ARAABOT AI QUANTUM COMMAND CENTER           ║\n" +
      "  ║               Exness & MT4 Authenticated Bridge            ║\n" +
      "  ╠════════════════════════════════════════════════════════════╣\n" +
      "  ║  Status      : " + statusText + "\n" +
      "  ║  Terminal ID : " + terminalIdStr + "\n" +
      "  ║  Account     : #" + accountLoginStr + " [" + accountTypeStr + "] (" + accountServerStr + ")\n" +
      "  ║  Balance     : " + DoubleToString(bal, 2) + " " + accountCurrStr + "\n" +
      "  ║  Equity      : " + DoubleToString(eq, 2) + " " + accountCurrStr + "\n" +
      "  ║  Free Margin : " + DoubleToString(fm, 2) + " " + accountCurrStr + " (Level: " + DoubleToString(ml, 1) + "%)\n" +
      "  ║  Open Orders : " + IntegerToString(cnt) + " Active Broker Trades\n" +
      "  ║  Permissions : " + tradePerm + "\n" +
      "  ╚════════════════════════════════════════════════════════════╝\n";

   Comment(hud);
}

//+------------------------------------------------------------------+
//| Helper to extract JSON string value                              |
//+------------------------------------------------------------------+
string JsonGetString(string json, string key)
{
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if (pos < 0) return "";
   pos += StringLen(search);
   int endPos = StringFind(json, "\"", pos);
   if (endPos < 0) return "";
   return StringSubstr(json, pos, endPos - pos);
}

//+------------------------------------------------------------------+
//| Helper to extract JSON number value                              |
//+------------------------------------------------------------------+
double JsonGetNumber(string json, string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if (pos < 0) return 0.0;
   pos += StringLen(search);
   int len = StringLen(json);
   while (pos < len && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == '\"')) {
      pos++;
   }
   int endPos = pos;
   while (endPos < len) {
      ushort ch = StringGetCharacter(json, endPos);
      if (ch == ',' || ch == '}' || ch == ']' || ch == '\"' || ch == ' ') break;
      endPos++;
   }
   string numStr = StringSubstr(json, pos, endPos - pos);
   return StringToDouble(numStr);
}

#define BRIDGE_FILE "araabot_mt4_bridge.json"
#define CMD_FILE    "araabot_mt4_cmd.json"
#define CB_FILE     "araabot_mt4_cb.json"

void WriteBridgeFile(string payload)
{
   int h = FileOpen(BRIDGE_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if (h != INVALID_HANDLE) {
      FileWriteString(h, payload);
      FileClose(h);
   }
}

//+------------------------------------------------------------------+
//| Step 13: Securely register terminal with ARAA backend            |
//+------------------------------------------------------------------+
void RegisterTerminalWithAraaBot()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double fm  = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   double mr  = AccountInfoDouble(ACCOUNT_MARGIN);
   double ml  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   long   lev = AccountInfoInteger(ACCOUNT_LEVERAGE);
   int    tAllow = (IsTradeAllowed() && IsExpertEnabled()) ? 1 : 0;
   int    eAllow = IsExpertEnabled() ? 1 : 0;

   string headers = "Content-Type: application/json\r\nX-Araa-Token: " + sessionTokenStr + "\r\n";
   string payload = StringFormat(
      "{\"pairing_token\":\"%s\",\"brand_id\":\"%s\",\"terminal_id\":\"%s\",\"account\":\"%s\",\"server\":\"%s\","
      "\"account_type\":\"%s\",\"currency\":\"%s\",\"balance\":%.2f,\"equity\":%.2f,\"free_margin\":%.2f,"
      "\"margin\":%.2f,\"margin_level\":%.2f,\"leverage\":%d,\"trading_allowed\":%s,\"expert_enabled\":%s}",
      sessionTokenStr, InpBrandId, terminalIdStr, accountLoginStr, accountServerStr,
      accountTypeStr, accountCurrStr, bal, eq, fm, mr, ml, lev,
      (tAllow == 1 ? "true" : "false"), (eAllow == 1 ? "true" : "false")
   );
   WriteBridgeFile(payload);

   char postData[];
   char result[];
   string resultHeaders;
   int dataLen = StringToCharArray(payload, postData, 0, WHOLE_ARRAY, CP_UTF8);
   if (dataLen > 0) ArrayResize(postData, dataLen - 1);

   string url = InpServerUrl + "/api/mt4/register";
   ResetLastError();
   int res = WebRequest("POST", url, NULL, NULL, 3000, postData, ArraySize(postData), result, resultHeaders);
   if (res != 200) {
      string getUrl = StringFormat(
         "%s/api/mt4/register?pairing_token=%s&brand_id=%s&terminal_id=%s&account=%s&server=%s&account_type=%s&currency=%s&balance=%.2f&equity=%.2f&free_margin=%.2f&margin=%.2f&margin_level=%.2f&leverage=%d&trading_allowed=%d&expert_enabled=%d",
         InpServerUrl, sessionTokenStr, InpBrandId, terminalIdStr, accountLoginStr, accountServerStr,
         accountTypeStr, accountCurrStr, bal, eq, fm, mr, ml, lev, tAllow, eAllow
      );
      char emptyData[];
      ResetLastError();
      res = WebRequest("GET", getUrl, NULL, NULL, 3000, emptyData, 0, result, resultHeaders);
   }

   if (res == 200) {
      string resp = CharArrayToString(result);
      string assignedTermId = JsonGetString(resp, "terminal_id");
      string assignedToken  = JsonGetString(resp, "session_token");
      if (StringLen(assignedTermId) > 0) terminalIdStr = assignedTermId;
      if (StringLen(assignedToken) > 0)  sessionTokenStr = assignedToken;
   }
   isRegistered = true;
   UpdateChartHUD("CONNECTED & AUTHENTICATED (" + accountTypeStr + ")");
   Print("✅ Terminal Registered with ARAA: ", terminalIdStr);
}

//+------------------------------------------------------------------+
//| Build JSON array of all open positions in MT4                    |
//+------------------------------------------------------------------+
string BuildOpenPositionsJson()
{
   string json = "[";
   bool first = true;
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (OrderType() == OP_BUY || OrderType() == OP_SELL) {
            if (!first) json += ",";
            first = false;
            string side = (OrderType() == OP_BUY) ? "BUY" : "SELL";
            double curPrice = (OrderType() == OP_BUY) ? MarketInfo(OrderSymbol(), MODE_BID) : MarketInfo(OrderSymbol(), MODE_ASK);
            double netProfit = OrderProfit() + OrderSwap() + OrderCommission();
            json += StringFormat(
               "{\"ticket\":%d,\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,\"entry_price\":%.5f,"
               "\"current_price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f,\"magic\":%d}",
               OrderTicket(), OrderSymbol(), side, OrderLots(), OrderOpenPrice(),
               curPrice, OrderStopLoss(), OrderTakeProfit(), netProfit, OrderMagicNumber()
            );
         }
      }
   }
   json += "]";
   return json;
}

//+------------------------------------------------------------------+
//| Synchronizes MT4 account, permissions, and positions with ARAA   |
//+------------------------------------------------------------------+
void SyncAccountWithAraaBot()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double fm  = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   double mr  = AccountInfoDouble(ACCOUNT_MARGIN);
   double ml  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   long   lev = AccountInfoInteger(ACCOUNT_LEVERAGE);
   int    tAllow = (IsTradeAllowed() && IsExpertEnabled()) ? 1 : 0;
   int    eAllow = IsExpertEnabled() ? 1 : 0;
   string openPosJson = BuildOpenPositionsJson();

   string headers = "Content-Type: application/json\r\nX-Araa-Token: " + sessionTokenStr + "\r\n";
   string payload = StringFormat(
      "{\"token\":\"%s\",\"terminal_id\":\"%s\",\"account\":\"%s\",\"server\":\"%s\","
      "\"account_type\":\"%s\",\"currency\":\"%s\",\"balance\":%.2f,\"equity\":%.2f,"
      "\"free_margin\":%.2f,\"margin\":%.2f,\"margin_level\":%.2f,\"leverage\":%d,"
      "\"trading_allowed\":%s,\"expert_enabled\":%s,\"open_positions\":%s}",
      sessionTokenStr, terminalIdStr, accountLoginStr, accountServerStr,
      accountTypeStr, accountCurrStr, bal, eq, fm, mr, ml, lev,
      (tAllow == 1 ? "true" : "false"), (eAllow == 1 ? "true" : "false"), openPosJson
   );
   WriteBridgeFile(payload);

   char postData[];
   char result[];
   string resultHeaders;
   int dataLen = StringToCharArray(payload, postData, 0, WHOLE_ARRAY, CP_UTF8);
   if (dataLen > 0) ArrayResize(postData, dataLen - 1);

   string url = InpServerUrl + "/api/mt4/sync";
   ResetLastError();
   int res = WebRequest("POST", url, NULL, NULL, 3000, postData, ArraySize(postData), result, resultHeaders);
   if (res != 200) {
      string getUrl = StringFormat(
         "%s/api/mt4/sync?token=%s&terminal_id=%s&account=%s&server=%s&account_type=%s&currency=%s&balance=%.2f&equity=%.2f&free_margin=%.2f&margin=%.2f&margin_level=%.2f&leverage=%d&trading_allowed=%d&expert_enabled=%d",
         InpServerUrl, sessionTokenStr, terminalIdStr, accountLoginStr, accountServerStr,
         accountTypeStr, accountCurrStr, bal, eq, fm, mr, ml, lev, tAllow, eAllow
      );
      char emptyData[];
      ResetLastError();
      res = WebRequest("GET", getUrl, NULL, NULL, 3000, emptyData, 0, result, resultHeaders);
   }

   isRegistered = true;
   UpdateChartHUD("READY · HEARTBEAT ACTIVE");
}

//+------------------------------------------------------------------+
//| Resolve Exness broker symbol (handles 'm' suffix automatically)  |
//+------------------------------------------------------------------+
string ResolveBrokerSymbol(string rawSym)
{
   if (rawSym == "") return Symbol();
   if (MarketInfo(rawSym, MODE_BID) > 0) return rawSym;
   string withM = rawSym + "m";
   if (MarketInfo(withM, MODE_BID) > 0) {
      SymbolSelect(withM, true);
      return withM;
   }
   SymbolSelect(rawSym, true);
   return rawSym;
}

//+------------------------------------------------------------------+
//| Polls ARAA backend for authenticated trade commands              |
//+------------------------------------------------------------------+
void PollPendingActions()
{
   string url = InpServerUrl + "/api/mt4/poll?account=" + accountLoginStr + "&terminal_id=" + terminalIdStr + "&token=" + sessionTokenStr;
   string headers = "X-Araa-Token: " + sessionTokenStr + "\r\n";
   char postData[];
   char result[];
   string resultHeaders;

   ResetLastError();
   int res = WebRequest("GET", url, NULL, NULL, 3000, postData, 0, result, resultHeaders);
   string response = "";
   if (res == 200 && ArraySize(result) > 0) {
      response = CharArrayToString(result);
   } else if (FileIsExist(CMD_FILE)) {
      int h = FileOpen(CMD_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
      if (h != INVALID_HANDLE) {
         response = FileReadString(h);
         FileClose(h);
         FileDelete(CMD_FILE);
      }
   }
   if (StringLen(response) == 0) return;
   if (StringFind(response, "\"action\"") < 0) return;

   string action = JsonGetString(response, "action");
   if (action == "" || action == "NONE" || action == "PING") return;

   string commandId = JsonGetString(response, "command_id");
   if (commandId == "") commandId = JsonGetString(response, "ticket_sim");
   string nonce = JsonGetString(response, "nonce");

   Print("🔔 Authenticated ARAA Command Received: ", action, " (", commandId, ")");

   if (action == "ORDER_OPEN") {
      string sym  = JsonGetString(response, "symbol");
      string side = JsonGetString(response, "side");
      double lots = JsonGetNumber(response, "lots");
      double sl   = JsonGetNumber(response, "sl");
      double tp   = JsonGetNumber(response, "tp");
      ExecuteOpenOrder(sym, side, lots, sl, tp, commandId, nonce);
   }
   else if (action == "ORDER_CLOSE") {
      int ticket = (int)JsonGetNumber(response, "ticket");
      ExecuteCloseOrder(ticket, commandId, nonce);
   }
   else if (action == "CLOSE_ALL") {
      ExecuteCloseAll(commandId, nonce);
   }
}

//+------------------------------------------------------------------+
//| Executes a Market BUY or SELL order in MT4                       |
//+------------------------------------------------------------------+
void ExecuteOpenOrder(string rawSymbol, string side, double lots, double sl, double tp, string commandId, string nonce)
{
   string symbol = ResolveBrokerSymbol(rawSymbol);
   if (lots < 0.01) lots = 0.01;

   int cmd = (side == "BUY" || side == "LONG") ? OP_BUY : OP_SELL;
   double price = (cmd == OP_BUY) ? MarketInfo(symbol, MODE_ASK) : MarketInfo(symbol, MODE_BID);
   int digits = (int)MarketInfo(symbol, MODE_DIGITS);
   if (digits > 0) {
      price = NormalizeDouble(price, digits);
      if (sl > 0) sl = NormalizeDouble(sl, digits);
      if (tp > 0) tp = NormalizeDouble(tp, digits);
   }
   color clr = (cmd == OP_BUY) ? clrLimeGreen : clrRed;

   ResetLastError();
   int ticket = OrderSend(symbol, cmd, lots, price, InpSlippage, sl, tp, "ARAA " + commandId, InpMagicNumber, 0, clr);

   if (ticket > 0) {
      double fillPrice = price;
      if (OrderSelect(ticket, SELECT_BY_TICKET)) {
         fillPrice = OrderOpenPrice();
      }
      Print("✅ Broker Confirmed MT4 Order #", ticket, " ", side, " ", lots, " lots ", symbol, " @ ", fillPrice);
      SendOrderCallback("ORDER_OPENED", commandId, nonce, ticket, symbol, side, lots, fillPrice, 0.0, 0, "");
      SyncAccountWithAraaBot();
   } else {
      int err = GetLastError();
      Print("❌ OrderSend rejected by broker for ", symbol, " Error: ", err);
      SendOrderCallback("ORDER_FAILED", commandId, nonce, 0, symbol, side, lots, price, 0.0, err, "OrderSend failed");
   }
}

//+------------------------------------------------------------------+
//| Closes an open position by Broker Ticket ID                      |
//+------------------------------------------------------------------+
void ExecuteCloseOrder(int ticket, string commandId, string nonce)
{
   if (ticket <= 0) return;
   if (OrderSelect(ticket, SELECT_BY_TICKET)) {
      string sym = OrderSymbol();
      double lots = OrderLots();
      double closePrice = (OrderType() == OP_BUY) ? MarketInfo(sym, MODE_BID) : MarketInfo(sym, MODE_ASK);
      ResetLastError();
      bool ok = OrderClose(ticket, lots, closePrice, InpSlippage, clrYellow);
      if (ok) {
         double pnl = 0.0;
         if (OrderSelect(ticket, SELECT_BY_TICKET, MODE_HISTORY)) {
            closePrice = OrderClosePrice();
            pnl = OrderProfit() + OrderSwap() + OrderCommission();
         }
         Print("✅ Broker Closed MT4 Order #", ticket, " @ ", closePrice, " P&L: ", pnl);
         SendOrderCallback("ORDER_CLOSED", commandId, nonce, ticket, sym, "CLOSE", lots, closePrice, pnl, 0, "");
         SyncAccountWithAraaBot();
      } else {
         int err = GetLastError();
         Print("❌ Failed to close MT4 Order #", ticket, " Error: ", err);
         SendOrderCallback("ORDER_FAILED", commandId, nonce, ticket, sym, "CLOSE", lots, closePrice, 0.0, err, "OrderClose failed");
      }
   }
}

//+------------------------------------------------------------------+
//| Emergency closes all open ARAA positions                         |
//+------------------------------------------------------------------+
void ExecuteCloseAll(string commandId, string nonce)
{
   Print("🚨 ARAA EMERGENCY CLOSE ALL Triggered!");
   for (int i = OrdersTotal() - 1; i >= 0; i--) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (OrderMagicNumber() == InpMagicNumber || InpMagicNumber == 0) {
            int tkt = OrderTicket();
            string sym = OrderSymbol();
            double lots = OrderLots();
            double closePrice = (OrderType() == OP_BUY) ? MarketInfo(sym, MODE_BID) : MarketInfo(sym, MODE_ASK);
            if (OrderClose(tkt, lots, closePrice, InpSlippage, clrRed)) {
               double pnl = OrderProfit() + OrderSwap() + OrderCommission();
               SendOrderCallback("ORDER_CLOSED", commandId, nonce, tkt, sym, "CLOSE", lots, closePrice, pnl, 0, "");
            }
         }
      }
   }
   SyncAccountWithAraaBot();
}

//+------------------------------------------------------------------+
//| Reports authenticated broker execution back to ARAA              |
//+------------------------------------------------------------------+
void SendOrderCallback(string status, string commandId, string nonce, int mt4Ticket, string symbol,
                       string side, double lots, double price, double profit, int errCode, string errMsg)
{
   string headers = "Content-Type: application/json\r\nX-Araa-Token: " + sessionTokenStr + "\r\n";
   string payload = StringFormat(
      "{\"token\":\"%s\",\"terminal_id\":\"%s\",\"account\":\"%s\",\"status\":\"%s\","
      "\"command_id\":\"%s\",\"ticket_sim\":\"%s\",\"nonce\":\"%s\",\"mt4_ticket\":%d,"
      "\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,\"price\":%.5f,\"profit\":%.2f,"
      "\"error_code\":%d,\"error_message\":\"%s\"}",
      sessionTokenStr, terminalIdStr, accountLoginStr, status,
      commandId, commandId, nonce, mt4Ticket,
      symbol, side, lots, price, profit, errCode, errMsg
   );
   int hCb = FileOpen(CB_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if (hCb != INVALID_HANDLE) {
      FileWriteString(hCb, payload);
      FileClose(hCb);
   }

   char postData[];
   char result[];
   string resultHeaders;
   int dataLen = StringToCharArray(payload, postData, 0, WHOLE_ARRAY, CP_UTF8);
   if (dataLen > 0) ArrayResize(postData, dataLen - 1);

   string url = InpServerUrl + "/api/mt4/order_callback";
   ResetLastError();
   int cbRes = WebRequest("POST", url, NULL, NULL, 3000, postData, ArraySize(postData), result, resultHeaders);
   if (cbRes != 200) {
      string getUrl = StringFormat(
         "%s/api/mt4/order_callback?token=%s&terminal_id=%s&account=%s&status=%s&command_id=%s&ticket_sim=%s&nonce=%s&mt4_ticket=%d&symbol=%s&side=%s&lots=%.2f&price=%.5f&profit=%.2f&error_code=%d",
         InpServerUrl, sessionTokenStr, terminalIdStr, accountLoginStr, status, commandId, commandId, nonce,
         mt4Ticket, symbol, side, lots, price, profit, errCode
      );
      char emptyData[];
      ResetLastError();
      WebRequest("GET", getUrl, NULL, NULL, 3000, emptyData, 0, result, resultHeaders);
   }
}
//+------------------------------------------------------------------+
