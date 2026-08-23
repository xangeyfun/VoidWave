import hmac
import hashlib
import secrets
import json
import time
import urllib.request
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, session

from . import admin_bp
from .helpers import (
    _db, _admin_password, _webhook_url, _twofa_enabled, _client_ip,
    _log, _rate_limit_attempts, _rate_limit_fail, _rate_limit_reset,
    _issue_2fa, _consume_2fa, _send_webhook, _complete_login,
)
from .constants import RATE_LIMIT_MAX


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    ip = _client_ip()

    if request.method == "POST":
        if _rate_limit_attempts(ip) >= RATE_LIMIT_MAX:
            _log("LOGIN BLOCKED", "rate limited", ip)
            return render_template(
                "admin_login.html",
                error="Too many failed attempts. Try again in 15 minutes.",
                password_only=not _twofa_enabled(),
            ), 429

        password = request.form.get("password", "")
        if not hmac.compare_digest(password, _admin_password()):
            _rate_limit_fail(ip)
            _log("LOGIN FAIL", "wrong password", ip)
            return render_template(
                "admin_login.html",
                error="Incorrect password.",
                password_only=not _twofa_enabled(),
            ), 401

        _rate_limit_reset(ip)
        _log("PASSWORD OK", "issuing 2FA code", ip)

        if _twofa_enabled():
            if not _webhook_url():
                _log("LOGIN FAIL", "2FA enabled but ADMIN_WEBHOOK_URL missing", ip)
                return render_template(
                    "admin_login.html",
                    error="2FA is enabled but ADMIN_WEBHOOK_URL is not set in .env.",
                    password_only=False,
                ), 503
            token, code = _issue_2fa(ip)
            try:
                _send_webhook({
                    "username": "VoidWave Admin",
                    "embeds": [{
                        "title": "Admin login 2FA code",
                        "description": f"Your 8-digit code is **`{code}`**",
                        "color": 0x8438fc,
                        "fields": [
                            {"name": "Expires", "value": "in 2 minutes", "inline": True},
                            {"name": "Requested from", "value": f"`{ip}`", "inline": True},
                        ],
                        "footer": {"text": "Don't share this code. It is one-time use."},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }],
                })
            except Exception as e:
                _log("2FA SEND FAIL", str(e), ip)
                return render_template(
                    "admin_login.html",
                    error="Could not deliver the 2FA code to Discord. Try again.",
                    password_only=False,
                ), 500
            session["pending_2fa"] = token
            session["pending_2fa_ip"] = ip
            return render_template("admin_login.html", twofa=True)

        _complete_login(ip)
        _log("LOGIN OK", "password-only login", ip)
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_login.html", password_only=not _twofa_enabled())


@admin_bp.route("/login/2fa", methods=["POST"])
def verify_2fa():
    ip = _client_ip()

    if _rate_limit_attempts(ip) >= RATE_LIMIT_MAX:
        _log("2FA BLOCKED", "rate limited", ip)
        return render_template(
            "admin_login.html", error="Too many failed attempts. Try again in 15 minutes.", password_only=False
        ), 429

    token = session.get("pending_2fa")
    pending_ip = session.get("pending_2fa_ip")
    code = (request.form.get("code") or "").strip()

    if not token or pending_ip != ip:
        _rate_limit_fail(ip)
        _log("2FA FAIL", "missing session or ip mismatch", ip)
        return render_template(
            "admin_login.html", twofa=True, error="Session expired. Start again from the login page.", password_only=False
        ), 401

    if not code.isdigit() or len(code) != 8:
        _rate_limit_fail(ip)
        _log("2FA FAIL", "malformed code", ip)
        return render_template(
            "admin_login.html", twofa=True, error="Invalid code.", password_only=False
        ), 401

    if not _consume_2fa(token, code):
        _rate_limit_fail(ip)
        _log("2FA FAIL", "wrong or expired code", ip)
        return render_template(
            "admin_login.html", twofa=True, error="Wrong or expired code.", password_only=False
        ), 401

    _rate_limit_reset(ip)
    _log("LOGIN OK", "authenticated with 2FA", ip)
    _complete_login(ip)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/logout")
def logout():
    _log("LOGOUT", "")
    session.clear()
    return redirect(url_for("admin.login"))
