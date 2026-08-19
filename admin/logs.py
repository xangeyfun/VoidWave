from flask import render_template, request

from . import admin_bp
from .helpers import _read_log_lines


@admin_bp.route("/logs")
def logs():
    q = (request.args.get("q") or "").strip().lower()
    page = max(1, request.args.get("page", 1, type=int))
    per = 100

    lines = _read_log_lines()[::-1]
    if q:
        lines = [ln for ln in lines if q in ln.lower()]

    total = len(lines)
    total_pages = max(1, (total + per - 1) // per)
    chunk = lines[(page - 1) * per: page * per]

    return render_template(
        "admin_logs.html",
        lines=chunk,
        total=total,
        q=q,
        page=page,
        total_pages=total_pages,
    )
