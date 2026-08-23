from flask import render_template, request

from . import admin_bp
from .helpers import _command_stats, _parse_command_logs


@admin_bp.route("/commands")
def commands_page():
    stats = _command_stats()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 30
    all_entries = _parse_command_logs()[::-1]
    total = len(all_entries)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    page_entries = all_entries[(page - 1) * per_page : page * per_page]

    return render_template(
        "admin_commands.html",
        stats=stats,
        entries=page_entries,
        page=page,
        total_pages=total_pages,
        total=total,
    )
