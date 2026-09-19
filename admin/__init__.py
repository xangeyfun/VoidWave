from datetime import datetime

from flask import Blueprint, redirect, render_template, request, session, url_for

from .helpers import (
    _admin_password,
    _client_ip,
    _csrf_ok,
    _csrf_token,
    _ensure_admin_tables,
    _fmt_ago,
    _fmt_delta,
    _fmt_dt,
    _fmt_size,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

admin_bp.add_app_template_filter(_fmt_delta, "delta")
admin_bp.add_app_template_filter(_fmt_dt, "dt")
admin_bp.add_app_template_filter(_fmt_ago, "ago")
admin_bp.add_app_template_filter(_fmt_size, "size")


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


from . import (  # noqa: E402
    api,  # noqa: E402, F401
    auth,  # noqa: E402, F401
    backups,  # noqa: E402, F401
    blocks,  # noqa: E402, F401
    bot,  # noqa: E402, F401
    commands,  # noqa: E402, F401
    dashboard,  # noqa: E402, F401
    events,  # noqa: E402, F401
    forget,  # noqa: E402, F401
    guilds,  # noqa: E402, F401
    health,  # noqa: E402, F401
    logs,  # noqa: E402, F401
    stats,  # noqa: E402, F401
    user_profile,  # noqa: E402, F401
    users,  # noqa: E402, F401
)
