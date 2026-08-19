from flask import Blueprint, render_template, redirect, url_for, session, request
from datetime import datetime, timezone

from .helpers import (
    _db, _ensure_admin_tables, _admin_password, _client_ip,
    _csrf_token, _csrf_ok, _log,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
def _guard():
    _ensure_admin_tables()

    if not _admin_password():
        return render_template(
            "admin_login.html", config_error="ADMIN_PASSWORD is not set in .env", password_only=True
        ), 503

    if request.method == "POST" and not _csrf_ok():
        from flask import abort
        abort(400)

    endpoint = request.endpoint or ""
    open_routes = {"admin.login", "admin.verify_2fa"}

    if endpoint in open_routes:
        if endpoint == "admin.login" and session.get("admin"):
            return redirect(url_for("admin.dashboard"))
        return None

    if not session.get("admin"):
        return redirect(url_for("admin.login"))
    return None


@admin_bp.context_processor
def _inject():
    return {
        "csrf_token": _csrf_token,
        "client_ip": _client_ip,
        "now": datetime.now(),
    }


from . import auth  # noqa: E402, F401
from . import health  # noqa: E402, F401
from . import dashboard  # noqa: E402, F401
from . import users  # noqa: E402, F401
from . import forget  # noqa: E402, F401
from . import bot  # noqa: E402, F401
from . import backups  # noqa: E402, F401
from . import stats  # noqa: E402, F401
from . import guilds  # noqa: E402, F401
from . import logs  # noqa: E402, F401
from . import api  # noqa: E402, F401
