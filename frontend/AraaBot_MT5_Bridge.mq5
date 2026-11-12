//+------------------------------------------------------------------+
//|                                          AraaBot_MT5_Bridge.mq5  |
//|                                   Copyright 2026, AraaBot.in AI  |
//|                                       https://www.araabot.in     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AraaBot.in AI Quantum Trading"
#property link      "https://www.araabot.in"
#property version   "3.00"
#property description "Authenticated Zero-Password Exness & Multi-Broker MT5 Bridge for AraaBot."
#property description "Supports Demo/Real detection, one-time pairing token registration,"
#property description "live margin/equity/position sync, and broker-confirmed CTrade execution."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- EA Input Parameters
input string   InpServerUrl      = "http://127.0.0.1:5050"; // AraaBot Server URL (Waitlist in Tools -> Options -> Expert Advisors)
input string   InpPairingToken   = "";                      // One-Time Pairing Token from ARAA Dashboard (e.g. ARAA-MT4-XXXX)
input string   InpBrandId        = "ARAA";                  // Brand Identifier (ARAA)
input string   InpTerminalId     = "";                      // Optional Custom Terminal ID (Auto-generated if blank)
input int      InpPollSeconds    = 1;                       // Heartbeat & Command Poll Interval (Seconds)
input int      InpSlippagePoints = 30;                      // Max Deviation / Slippage in Points
input int      InpMagicNumber    = 888801;                  // AraaBot Magic Identifier

//--- Global State
CTrade         ExtTrade;
CPositionInfo  ExtPosition;
string         accountLoginStr   = "";
string         accountServerStr  = "";
string         accountTypeStr    = "DEMO";
string         accountCurrStr    = "USD";
string         terminalIdStr     = "";
string         sessionTokenStr   = "";
bool           isRegistered      = false;
string         lastCommandId     = "";
string         BRIDGE_FILE       = "araabot_mt4_bridge.json";
string         CMD_FILE          = "araabot_mt4_cmd.json";
string         CB_FILE           = "araabot_mt4_cb.json";

//+------------------------------------------------------------------+
//| Writes telemetry to MQL5/Files/araabot_mt4_bridge.json           |
//+------------------------------------------------------------------+
void WriteBridgeFile(string jsonPayload)
{
   int h = FileOpen(BRIDGE_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileWriteString(h, jsonPayload);
      FileClose(h);
   }
}

//+------------------------------------------------------------------+
//| Writes callback to MQL5/Files/araabot_mt4_cb.json                |
//+------------------------------------------------------------------+
void WriteCallbackFile(string jsonPayload)
{
   int h = FileOpen(CB_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileWriteString(h, jsonPayload);
      FileClose(h);
   }
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   accountLoginStr  = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   accountServerStr = AccountInfoString(ACCOUNT_SERVER);
   accountCurrStr   = AccountInfoString(ACCOUNT_CURRENCY);
   if(accountCurrStr == "") accountCurrStr = "USD";

   long tradeMode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(tradeMode == ACCOUNT_TRADE_MODE_REAL)
      accountTypeStr = "REAL";
   else
      accountTypeStr = "DEMO";

   if(StringLen(InpTerminalId) > 0)
      terminalIdStr = InpTerminalId;
   else
      terminalIdStr = "TERM-" + InpBrandId + "-MT5-" + accountLoginStr;

   sessionTokenStr = InpPairingToken;

   ExtTrade.SetExpertMagicNumber(InpMagicNumber);
   ExtTrade.SetDeviationInPoints(InpSlippagePoints);
   ExtTrade.SetTypeFillingBySymbol(_Symbol);
   ExtTrade.SetAsyncMode(false);

   EventSetTimer(MathMax(1, InpPollSeconds));

   Print("⚡ AraaBot MT5 Bridge v3.0 Initialized for Account #", accountLoginStr,
         " (", accountTypeStr, ") on Server: ", accountServerStr);

   // Step 1: Register terminal if pairing token is provided
   if(StringLen(sessionTokenStr) > 0)
   {
      RegisterTerminalWithAraaBot();
   }
   // Step 2: Perform immediate telemetry sync
   SyncAccountWithAraaBot();

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

//+------------------------------------------------------------------+
//| Timer function (Every 1 second)                                  |
//+------------------------------------------------------------------+
void OnTimer()
{
   // 1. Check for queued trading commands from AraaBot
   PollAraaBotCommands();

   // 2. Push live balance, equity, margin, permissions & open positions
   SyncAccountWithAraaBot();
}

//+------------------------------------------------------------------+
//| Chart HUD Overlay                                                |
//+------------------------------------------------------------------+
void UpdateChartHUD(string statusMsg)
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double fm  = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   double ml  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   bool   tAllowed = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && (bool)MQLInfoInteger(MQL_TRADE_ALLOWED);

   string hud = StringFormat(
      "\n   ╔══════════════════════════════════════════════════════════╗\n"
      "   ║  ⚡ ARAABOT.IN AI QUANTUM COMMAND CENTER (MT5 v3.0)      ║\n"
      "   ║  Exness & Multi-Broker MT5 Authenticated Bridge          ║\n"
      "   ╠══════════════════════════════════════════════════════════╣\n"
      "   ║  Status      : %s\n"
      "   ║  Terminal ID : %s\n"
      "   ║  Account     : #%s [%s] (%s)\n"
      "   ║  Balance     : %.2f %s\n"
      "   ║  Equity      : %.2f %s\n"
      "   ║  Free Margin : %.2f %s (Level: %.1f%%)\n"
      "   ║  Open Orders : %d Active Broker Trades\n"
      "   ║  Permissions : %s\n"
      "   ╚══════════════════════════════════════════════════════════╝",
      statusMsg,
      terminalIdStr,
      accountLoginStr, accountTypeStr, accountServerStr,
      bal, accountCurrStr,
      eq, accountCurrStr,
      fm, accountCurrStr, ml,
      PositionsTotal(),
      tAllowed ? "ALLOWED (Algo Trading ON)" : "BLOCKED (Enable Algo Trading in MT5)"
   );
   Comment(hud);
}

//+------------------------------------------------------------------+
//| Step 13-15: Register MT5 Terminal with One-Time Pairing Token    |
//+------------------------------------------------------------------+
void RegisterTerminalWithAraaBot()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double fm  = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   double mr  = AccountInfoDouble(ACCOUNT_MARGIN);
   double ml  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   long   lev = AccountInfoInteger(ACCOUNT_LEVERAGE);
   int    tAllow = (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED)) ? 1 : 0;
   int    eAllow = MQLInfoInteger(MQL_TRADE_ALLOWED) ? 1 : 0;

   string payload = StringFormat(
      "{\"pairing_token\":\"%s\",\"brand_id\":\"%s\",\"terminal_id\":\"%s\",\"platform\":\"MT5\",\"account\":\"%s\",\"server\":\"%s\","
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
   string headers = "Content-Type: application/json\r\nX-Araa-Token: " + sessionTokenStr + "\r\n";
   int dataLen = StringToCharArray(payload, postData, 0, WHOLE_ARRAY, CP_UTF8);
   if(dataLen > 0) ArrayResize(postData, dataLen - 1);

   string url = InpServerUrl + "/api/mt5/register";
   ResetLastError();
   int res = WebRequest("POST", url, headers, 3000, postData, result, resultHeaders);
   if(res != 200)
   {
      string getUrl = StringFormat(
         "%s/api/mt5/register?pairing_token=%s&brand_id=%s&terminal_id=%s&platform=MT5&account=%s&server=%s&account_type=%s&currency=%s&balance=%.2f&equity=%.2f&free_margin=%.2f&margin=%.2f&margin_level=%.2f&leverage=%d&trading_allowed=%d&expert_enabled=%d",
         InpServerUrl, sessionTokenStr, InpBrandId, terminalIdStr, accountLoginStr, accountServerStr,
         accountTypeStr, accountCurrStr, bal, eq, fm, mr, ml, lev, tAllow, eAllow
      );
      char emptyData[];
      ResetLastError();
      res = WebRequest("GET", getUrl, headers, 3000, emptyData, result, resultHeaders);
   }

   if(res == 200)
   {
      string resp = CharArrayToString(result);
      string assignedTermId = JsonGetString(resp, "terminal_id");
      string assignedToken  = JsonGetString(resp, "session_token");
      if(StringLen(assignedTermId) > 0) terminalIdStr = assignedTermId;
      if(StringLen(assignedToken) > 0)  sessionTokenStr = assignedToken;
   }
   isRegistered = true;
   UpdateChartHUD("CONNECTED & AUTHENTICATED (" + accountTypeStr + ")");
   Print("✅ MT5 Terminal Registered with ARAA: ", terminalIdStr);
}

//+------------------------------------------------------------------+
//| Build JSON array of all currently open MT5 broker positions      |
//+------------------------------------------------------------------+
string BuildOpenPositionsJson()
{
   string json = "[";
   bool first = true;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      long posType = PositionGetInteger(POSITION_TYPE);
      if(posType != POSITION_TYPE_BUY && posType != POSITION_TYPE_SELL) continue;

      string sym     = PositionGetString(POSITION_SYMBOL);
      string sideStr = (posType == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      double lots    = PositionGetDouble(POSITION_VOLUME);
      double openP   = PositionGetDouble(POSITION_PRICE_OPEN);
      double curP    = PositionGetDouble(POSITION_PRICE_CURRENT);
      double slP     = PositionGetDouble(POSITION_SL);
      double tpP     = PositionGetDouble(POSITION_TP);
      double profit  = PositionGetDouble(POSITION_PROFIT);
      double swap    = PositionGetDouble(POSITION_SWAP);
      long   openTm  = PositionGetInteger(POSITION_TIME);

      if(!first) json += ",";
      first = false;

      json += StringFormat(
         "{\"ticket\":%I64u,\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,"
         "\"open_price\":%.5f,\"current_price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,"
         "\"profit\":%.2f,\"swap\":%.2f,\"commission\":0.00,\"open_time\":%I64d}",
         ticket, sym, sideStr, lots, openP, curP, slP, tpP, profit, swap, openTm
      );
   }
   json += "]";
   return json;
}

//+------------------------------------------------------------------+
//| Synchronizes MT5 account, permissions, and positions with ARAA   |
//+------------------------------------------------------------------+
void SyncAccountWithAraaBot()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double fm  = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   double mr  = AccountInfoDouble(ACCOUNT_MARGIN);
   double ml  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   long   lev = AccountInfoInteger(ACCOUNT_LEVERAGE);
   int    tAllow = (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED)) ? 1 : 0;
   int    eAllow = MQLInfoInteger(MQL_TRADE_ALLOWED) ? 1 : 0;
   string openPosJson = BuildOpenPositionsJson();

   string headers = "Content-Type: application/json\r\nX-Araa-Token: " + sessionTokenStr + "\r\n";
   string payload = StringFormat(
      "{\"token\":\"%s\",\"terminal_id\":\"%s\",\"platform\":\"MT5\",\"account\":\"%s\",\"server\":\"%s\","
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
   if(dataLen > 0) ArrayResize(postData, dataLen - 1);

   string url = InpServerUrl + "/api/mt5/sync";
   ResetLastError();
   int res = WebRequest("POST", url, headers, 3000, postData, result, resultHeaders);
   if(res != 200)
   {
      string getUrl = StringFormat(
         "%s/api/mt5/sync?token=%s&terminal_id=%s&platform=MT5&account=%s&server=%s&account_type=%s&currency=%s&balance=%.2f&equity=%.2f&free_margin=%.2f&margin=%.2f&margin_level=%.2f&leverage=%d&trading_allowed=%d&expert_enabled=%d",
         InpServerUrl, sessionTokenStr, terminalIdStr, accountLoginStr, accountServerStr,
         accountTypeStr, accountCurrStr, bal, eq, fm, mr, ml, lev, tAllow, eAllow
      );
      char emptyData[];
      ResetLastError();
      res = WebRequest("GET", getUrl, headers, 3000, emptyData, result, resultHeaders);
   }

   isRegistered = true;
   UpdateChartHUD("READY · HEARTBEAT ACTIVE");
}

//+------------------------------------------------------------------+
//| Resolve Exness broker symbol (handles 'm' suffix automatically)  |
//+------------------------------------------------------------------+
string ResolveBrokerSymbol(string rawSym)
{
   if(rawSym == "") return _Symbol;
   if(SymbolInfoDouble(rawSym, SYMBOL_BID) > 0)
   {
      SymbolSelect(rawSym, true);
      return rawSym;
   }
   string withM = rawSym + "m";
   if(SymbolInfoDouble(withM, SYMBOL_BID) > 0)
   {
      SymbolSelect(withM, true);
      return withM;
   }
   int len = StringLen(rawSym);
   if(len > 1 && StringSubstr(rawSym, len - 1, 1) == "m")
   {
      string baseSym = StringSubstr(rawSym, 0, len - 1);
      if(SymbolInfoDouble(baseSym, SYMBOL_BID) > 0)
      {
         SymbolSelect(baseSym, true);
         return baseSym;
      }
   }
   SymbolSelect(rawSym, true);
   return rawSym;
}

//+------------------------------------------------------------------+
//| Polls AraaBot for queued authenticated order commands            |
//+------------------------------------------------------------------+
void PollAraaBotCommands()
{
   string resp = "";
   if(FileIsExist(CMD_FILE))
   {
      int h = FileOpen(CMD_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h != INVALID_HANDLE)
      {
         while(!FileIsEnding(h))
            resp += FileReadString(h);
         FileClose(h);
         FileDelete(CMD_FILE);
      }
   }

   if(StringLen(resp) == 0)
   {
      char postData[];
      char result[];
      string resultHeaders;
      string headers = "X-Araa-Token: " + sessionTokenStr + "\r\n";
      string url = StringFormat("%s/api/mt5/poll?account=%s&terminal_id=%s&token=%s",
                                InpServerUrl, accountLoginStr, terminalIdStr, sessionTokenStr);
      ResetLastError();
      int res = WebRequest("GET", url, headers, 3000, postData, result, resultHeaders);
      if(res != 200) return;
      resp = CharArrayToString(result);
   }

   if(StringFind(resp, "\"action\":\"NONE\"") >= 0 || StringFind(resp, "\"action\": \"NONE\"") >= 0)
      return;

   string cmdId = JsonGetString(resp, "command_id");
   string nonce = JsonGetString(resp, "nonce");
   if(StringLen(cmdId) > 0 && cmdId == lastCommandId)
      return; // Replay protection

   if(StringFind(resp, "ORDER_OPEN") >= 0)
   {
      lastCommandId = cmdId;
      string rawSym = JsonGetString(resp, "symbol");
      string sym    = ResolveBrokerSymbol(rawSym);
      string side   = JsonGetString(resp, "side");
      double lots   = StringToDouble(JsonGetNumber(resp, "lots"));
      double sl     = StringToDouble(JsonGetNumber(resp, "sl"));
      double tp     = StringToDouble(JsonGetNumber(resp, "tp"));

      if(lots <= 0) lots = 0.01;
      ExtTrade.SetTypeFillingBySymbol(sym);

      bool isBuy = (side == "BUY" || side == "LONG");
      double execPrice = isBuy ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);

      ResetLastError();
      bool ok = false;
      if(isBuy)
         ok = ExtTrade.Buy(lots, sym, execPrice, sl, tp, "ARAA_MT5_" + cmdId);
      else
         ok = ExtTrade.Sell(lots, sym, execPrice, sl, tp, "ARAA_MT5_" + cmdId);

      ulong dealTicket  = ExtTrade.ResultDeal();
      ulong orderTicket = ExtTrade.ResultOrder();
      ulong finalTicket = (orderTicket > 0) ? orderTicket : dealTicket;
      double fillPrice  = ExtTrade.ResultPrice();
      if(fillPrice <= 0) fillPrice = execPrice;

      if(ok && finalTicket > 0)
      {
         Print("✅ MT5 Order Filled: Ticket #", finalTicket, " ", side, " ", lots, " ", sym, " @ ", fillPrice);
         NotifyOrderCallback(cmdId, nonce, "ORDER_FILLED", (int)finalTicket, sym, side, lots, fillPrice, 0.0, 0, "");
      }
      else
      {
         int err = (int)ExtTrade.ResultRetcode();
         string errDesc = ExtTrade.ResultRetcodeDescription();
         Print("❌ MT5 Order Failed: ", sym, " Retcode=", err, " (", errDesc, ")");
         NotifyOrderCallback(cmdId, nonce, "ORDER_FAILED", -1, sym, side, lots, execPrice, 0.0, err, errDesc);
      }
   }
   else if(StringFind(resp, "ORDER_CLOSE") >= 0)
   {
      lastCommandId = cmdId;
      ulong ticketToClose = (ulong)StringToInteger(JsonGetNumber(resp, "ticket"));
      ClosePositionByTicket(ticketToClose, cmdId, nonce);
   }
   else if(StringFind(resp, "CLOSE_ALL") >= 0)
   {
      lastCommandId = cmdId;
      CloseAllPositions(cmdId, nonce);
   }
}

//+------------------------------------------------------------------+
//| Closes a specific MT5 position by ticket and reports callback    |
//+------------------------------------------------------------------+
void ClosePositionByTicket(ulong ticket, string cmdId, string nonce)
{
   if(!PositionSelectByTicket(ticket))
   {
      NotifyOrderCallback(cmdId, nonce, "ORDER_FAILED", (int)ticket, "", "CLOSE", 0, 0, 0, 4108, "Ticket not found");
      return;
   }

   string sym    = PositionGetString(POSITION_SYMBOL);
   double lots   = PositionGetDouble(POSITION_VOLUME);
   double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   double closeP = PositionGetDouble(POSITION_PRICE_CURRENT);

   ExtTrade.SetTypeFillingBySymbol(sym);
   bool closed = ExtTrade.PositionClose(ticket, InpSlippagePoints);
   if(closed)
   {
      NotifyOrderCallback(cmdId, nonce, "ORDER_CLOSED", (int)ticket, sym, "CLOSE", lots, closeP, profit, 0, "");
   }
   else
   {
      int err = (int)ExtTrade.ResultRetcode();
      NotifyOrderCallback(cmdId, nonce, "ORDER_FAILED", (int)ticket, sym, "CLOSE", lots, closeP, profit, err, ExtTrade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Closes all active MT5 positions                                  |
//+------------------------------------------------------------------+
void CloseAllPositions(string cmdId, string nonce)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
         ClosePositionByTicket(ticket, cmdId, nonce);
   }
}

//+------------------------------------------------------------------+
//| Sends broker execution confirmation callback to AraaBot          |
//+------------------------------------------------------------------+
void NotifyOrderCallback(string cmdId, string nonce, string status, int ticket,
                         string sym, string side, double lots, double price,
                         double profit, int errCode, string errMsg)
{
   string headers = "Content-Type: application/json\r\nX-Araa-Token: " + sessionTokenStr + "\r\n";
   string payload = StringFormat(
      "{\"token\":\"%s\",\"terminal_id\":\"%s\",\"platform\":\"MT5\",\"account\":\"%s\",\"command_id\":\"%s\",\"nonce\":\"%s\","
      "\"status\":\"%s\",\"ticket\":%d,\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,"
      "\"execution_price\":%.5f,\"profit\":%.2f,\"error_code\":%d,\"error_message\":\"%s\"}",
      sessionTokenStr, terminalIdStr, accountLoginStr, cmdId, nonce,
      status, ticket, sym, side, lots, price, profit, errCode, errMsg
   );
   WriteCallbackFile(payload);

   char postData[];
   char result[];
   string resultHeaders;
   int dataLen = StringToCharArray(payload, postData, 0, WHOLE_ARRAY, CP_UTF8);
   if(dataLen > 0) ArrayResize(postData, dataLen - 1);

   string url = InpServerUrl + "/api/mt5/order_callback";
   int res = WebRequest("POST", url, headers, 3000, postData, result, resultHeaders);
   if(res != 200)
   {
      string getUrl = StringFormat(
         "%s/api/mt5/order_callback?token=%s&terminal_id=%s&platform=MT5&account=%s&command_id=%s&nonce=%s&status=%s&ticket=%d&symbol=%s&side=%s&lots=%.2f&execution_price=%.5f&profit=%.2f&error_code=%d",
         InpServerUrl, sessionTokenStr, terminalIdStr, accountLoginStr, cmdId, nonce,
         status, ticket, sym, side, lots, price, profit, errCode
      );
      char emptyData[];
      WebRequest("GET", getUrl, headers, 3000, emptyData, result, resultHeaders);
   }
}

//+------------------------------------------------------------------+
//| Lightweight JSON String Extractor                                |
//+------------------------------------------------------------------+
string JsonGetString(string json, string key)
{
   string pattern = "\"" + key + "\"";
   int pos = StringFind(json, pattern);
   if(pos < 0) return "";
   int colon = StringFind(json, ":", pos + StringLen(pattern));
   if(colon < 0) return "";
   int q1 = StringFind(json, "\"", colon + 1);
   if(q1 < 0) return "";
   int q2 = StringFind(json, "\"", q1 + 1);
   if(q2 < 0) return "";
   return StringSubstr(json, q1 + 1, q2 - q1 - 1);
}

//+------------------------------------------------------------------+
//| Lightweight JSON Number Extractor                                |
//+------------------------------------------------------------------+
string JsonGetNumber(string json, string key)
{
   string pattern = "\"" + key + "\"";
   int pos = StringFind(json, pattern);
   if(pos < 0) return "0";
   int colon = StringFind(json, ":", pos + StringLen(pattern));
   if(colon < 0) return "0";
   int start = colon + 1;
   int len = StringLen(json);
   while(start < len)
   {
      ushort ch = StringGetCharacter(json, start);
      if(ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n' && ch != '\"') break;
      start++;
   }
   int end = start;
   while(end < len)
   {
      ushort c = StringGetCharacter(json, end);
      if((c >= '0' && c <= '9') || c == '.' || c == '-') end++;
      else break;
   }
   return StringSubstr(json, start, end - start);
}
//+------------------------------------------------------------------+
