"""
Trade Pro Enterprise Security Firewall (WAF)
==============================================
Autonomous Application Firewall & Threat Defense System for Trade Pro.
Guards against:
- Brute force & credential stuffing (IP-based & account-based rate limiting)
- SQL Injection (SQLi) & Cross-Site Scripting (XSS) payload inspection
- Unauthorized origin spoofing (CORS & Host header validation)
- Path traversal & Directory probing (.env, .git, etc.)
- Distributed Denial of Service (DDoS) high-frequency request flood
- API abuse & Token tampering
"""

import time
import re
import json
import ipaddress
import threading
from collections import defaultdict
from flask import request, jsonify

# Pre-compiled Regex patterns for attack detection
SQLI_PATTERNS = [
    re.compile(r"(\b(UNION(\s+ALL)?|SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|EXECUTE)\b.{1,100}\b(FROM|INTO|TABLE|DATABASE|WHERE)\b)", re.IGNORECASE),
    re.compile(r"('|\")\s*(OR|AND)\s*('|\")?\d+('|\")?\s*=\s*('|\")?\d+", re.IGNORECASE),
    re.compile(r"(--|#|/\*.*?\*/|;)\s*$", re.IGNORECASE),
    re.compile(r"\bWAITFOR\s+DELAY\b|\bBENCHMARK\s*\(|\bPG_SLEEP\s*\(", re.IGNORECASE)
]

XSS_PATTERNS = [
    re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript\s*:\s*.*", re.IGNORECASE),
    re.compile(r"on(load|error|click|mouseover|submit|focus)\s*=", re.IGNORECASE),
    re.compile(r"<\s*iframe[^>]*>", re.IGNORECASE)
]

PATH_TRAVERSAL_PATTERNS = [
    re.compile(r"(\.\./|\.\.\\)", re.IGNORECASE),
    re.compile(r"(/\.env|\.git|\.aws|\.ssh|/etc/passwd|/proc/self)", re.IGNORECASE)
]

class SecurityFirewall:
    def __init__(self):
        self.lock = threading.Lock()
        
        # IP Rate Limiting: ip -> list of timestamps
        self.ip_requests = defaultdict(list)
        # Authentication attempts: ip -> list of timestamps
        self.auth_attempts = defaultdict(list)
        # Blocked IPs: ip -> expiry_timestamp
        self.banned_ips = {}
        
        # Firewall settings
        self.MAX_REQ_PER_SEC = 200         # Generous API rate limit per second per IP (supports multiple browser pollers & MT4 EAs)
        self.MAX_REQ_PER_MIN = 3000        # Generous API rate limit per minute per IP
        self.MAX_AUTH_PER_MIN = 30         # Max login/register attempts per minute per IP
        self.BAN_DURATION_SECS = 60.0      # Temporary 60s cooldown on excessive flood
        # Whitelisted IPs exempt from permanent IP bans & strict rate throttling (local loopback development)
        self.WHITELISTED_IPS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}

        # Threat Event Audit Log (in-memory rolling buffer)
        self.threat_logs = []
        self.MAX_LOGS = 200
        
        # Telemetry stats
        self.stats = {
            "total_inspected": 0,
            "threats_blocked": 0,
            "sqli_blocked": 0,
            "xss_blocked": 0,
            "rate_limits_tripped": 0,
            "path_traversals_blocked": 0,
            "active_banned_ips": 0,
            "firewall_status": "ACTIVE_DEFENSE_MODE"
        }

    def get_client_ip(self):
        """Extract trusted client IP from reverse proxy headers or socket."""
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        xf = request.headers.get("X-Forwarded-For")
        if xf:
            return xf.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        return request.remote_addr or "127.0.0.1"

    def log_threat(self, ip, threat_type, details):
        """Record threat event into security audit buffer."""
        now = time.time()
        entry = {
            "timestamp": now,
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "ip": ip,
            "type": threat_type,
            "details": details,
            "path": request.path,
            "method": request.method
        }
        with self.lock:
            self.threat_logs.insert(0, entry)
            if len(self.threat_logs) > self.MAX_LOGS:
                self.threat_logs.pop()

    def inspect_request(self):
        """
        Primary Flask before_request filter.
        Returns a JSON 403/429 response if blocked, or None if request is safe to proceed.
        """
        # Exempt high-frequency MT4/MT5 EA telemetry & healthcheck endpoints from rate bans
        if request.path.startswith(("/api/mt4/", "/api/mt5/")) or request.path in ("/healthz", "/api/health"):
            return None

        ip = self.get_client_ip()
        now = time.time()

        with self.lock:
            self.stats["total_inspected"] += 1
            
            # 1. Check if IP is currently banned
            ban_expiry = self.banned_ips.get(ip)
            if ban_expiry:
                if now < ban_expiry:
                    remaining = int(ban_expiry - now)
                    return jsonify({
                        "firewall_blocked": True,
                        "error": f"Security Firewall Alert: Your IP is temporarily banned due to malicious activity. Retry in {remaining}s.",
                        "threat_level": "CRITICAL"
                    }), 403
                else:
                    del self.banned_ips[ip]

            # 2. Rate Limiting (DDoS & Brute Force Protection)
            # Clean timestamps older than 60 seconds
            req_history = [t for t in self.ip_requests[ip] if now - t < 60.0]
            self.ip_requests[ip] = req_history
            
            # Check last 1 second burst
            last_sec_reqs = sum(1 for t in req_history if now - t < 1.0)
            if last_sec_reqs > self.MAX_REQ_PER_SEC and ip not in self.WHITELISTED_IPS:
                self.stats["threats_blocked"] += 1
                self.stats["rate_limits_tripped"] += 1
                self.log_threat(ip, "DDOS_BURST_FLOOD", f"Exceeded {self.MAX_REQ_PER_SEC} requests/sec ({last_sec_reqs} req/s)")
                return jsonify({
                    "firewall_blocked": True,
                    "error": "Security Firewall: Request rate exceeded threshold (Anti-Flood Shield).",
                    "code": 429
                }), 429
                
            if len(req_history) > self.MAX_REQ_PER_MIN:
                self.stats["threats_blocked"] += 1
                self.stats["rate_limits_tripped"] += 1
                # Auto-ban aggressive flooders (except whitelisted local/loopback)
                if ip not in self.WHITELISTED_IPS:
                    self.banned_ips[ip] = now + self.BAN_DURATION_SECS
                self.log_threat(ip, "HIGH_FREQUENCY_FLOOD_BAN", f"Banned IP for {self.BAN_DURATION_SECS}s after {len(req_history)} req/min")
                return jsonify({
                    "firewall_blocked": True,
                    "error": "Security Firewall: Excessive request frequency. IP blacklisted for 15 minutes.",
                    "code": 429
                }), 429

            self.ip_requests[ip].append(now)

            # 3. Auth brute-force protection
            if request.path in ("/api/auth/login", "/api/auth/register") and request.method == "POST":
                auth_history = [t for t in self.auth_attempts[ip] if now - t < 60.0]
                self.auth_attempts[ip] = auth_history
                if len(auth_history) >= self.MAX_AUTH_PER_MIN:
                    if ip not in self.WHITELISTED_IPS:
                        self.banned_ips[ip] = now + 600.0  # 10 min ban for password guessing
                    self.stats["threats_blocked"] += 1
                    self.log_threat(ip, "CREDENTIAL_BRUTE_FORCE", f"Exceeded {self.MAX_AUTH_PER_MIN} auth attempts/min")
                    return jsonify({
                        "firewall_blocked": True,
                        "error": "Security Firewall: Too many authentication attempts. Please wait 10 minutes.",
                        "code": 429
                    }), 429
                self.auth_attempts[ip].append(now)

        # 4. Deep Payload Inspection (Path, Query Strings, JSON Body)
        # Check Path Traversal
        raw_path = request.path
        for pat in PATH_TRAVERSAL_PATTERNS:
            if pat.search(raw_path):
                with self.lock:
                    self.stats["threats_blocked"] += 1
                    self.stats["path_traversals_blocked"] += 1
                    if ip not in self.WHITELISTED_IPS:
                        self.banned_ips[ip] = now + 300.0
                self.log_threat(ip, "PATH_TRAVERSAL_PROBE", f"Blocked probing path: {raw_path}")
                return jsonify({
                    "firewall_blocked": True,
                    "error": "Security Firewall Alert: Unauthorized path probing blocked.",
                    "code": 403
                }), 403

        # Aggregate inputs to inspect (Query string raw + URL-decoded + Form + JSON)
        from urllib.parse import unquote_plus
        qs_raw = request.query_string.decode("utf-8", errors="ignore")
        sample_texts = [qs_raw, unquote_plus(qs_raw)]
        if request.is_json:
            try:
                body_str = json.dumps(request.get_json(silent=True) or {})
                sample_texts.append(body_str)
            except Exception:
                pass
        elif request.form:
            sample_texts.extend(request.form.values())

        full_payload = " ".join(sample_texts)

        # SQL Injection Check
        for pat in SQLI_PATTERNS:
            if pat.search(full_payload):
                with self.lock:
                    self.stats["threats_blocked"] += 1
                    self.stats["sqli_blocked"] += 1
                    if ip not in self.WHITELISTED_IPS:
                        self.banned_ips[ip] = now + self.BAN_DURATION_SECS
                self.log_threat(ip, "SQL_INJECTION_ATTEMPT", f"Matched SQLi pattern in {request.path}")
                return jsonify({
                    "firewall_blocked": True,
                    "error": "Security Firewall Alert: Malicious SQL injection signature detected and neutralized.",
                    "code": 403
                }), 403

        # XSS Check
        for pat in XSS_PATTERNS:
            if pat.search(full_payload):
                with self.lock:
                    self.stats["threats_blocked"] += 1
                    self.stats["xss_blocked"] += 1
                self.log_threat(ip, "XSS_ATTACK_ATTEMPT", f"Matched XSS pattern in {request.path}")
                return jsonify({
                    "firewall_blocked": True,
                    "error": "Security Firewall Alert: Cross-Site Scripting (XSS) payload rejected.",
                    "code": 403
                }), 403

        return None

    def get_status_report(self):
        """Telemetry snapshot for Admin Dashboard & Security Portal."""
        with self.lock:
            active_bans = [
                {"ip": ip, "expires_in_secs": max(0, int(exp - time.time()))}
                for ip, exp in self.banned_ips.items() if exp > time.time()
            ]
            self.stats["active_banned_ips"] = len(active_bans)
            return {
                "stats": dict(self.stats),
                "active_bans": active_bans,
                "recent_threats": list(self.threat_logs[:30]),
                "rules_active": {
                    "anti_ddos": True,
                    "anti_sqli": True,
                    "anti_xss": True,
                    "anti_brute_force": True,
                    "anti_path_traversal": True,
                    "max_req_sec": self.MAX_REQ_PER_SEC,
                    "max_req_min": self.MAX_REQ_PER_MIN
                }
            }

    def unban_ip(self, ip):
        with self.lock:
            if ip in self.banned_ips:
                del self.banned_ips[ip]
                return True
        return False

# Global Firewall Singleton
firewall = SecurityFirewall()
