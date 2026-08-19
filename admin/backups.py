import hmac
import shutil
from pathlib import Path

from flask import render_template, redirect, url_for, request, abort, flash

from . import admin_bp
from .helpers import (
    _db, _log, _clear_cache, _list_backups, _backup_current, _prune_backups,
    _service_active, _service_stop, _service_start,
)


@admin_bp.route("/backups")
def backups():
    items = _list_backups()
    return render_template("admin_backups.html", backups=items)


@admin_bp.route("/backups/create", methods=["POST"])
def backup_create():
    dst, err = _backup_current()
    if err:
        abort(500, description=err)
    removed = _prune_backups()
    _log("BACKUP CREATE", dst.name)
    flash(f"Backup created: {dst.name} ({removed} pruned)", "success")
    return redirect(url_for("admin.backups"))


@admin_bp.route("/backups/<name>/restore", methods=["GET", "POST"])
def backup_restore(name):
    from .constants import BACKUP_DIR
    path = BACKUP_DIR / name
    if not path.exists() or not path.is_file():
        abort(404)

    bot_active = _service_active("voidwave.service")
    site_active = _service_active("voidwave_website.service")

    if request.method == "POST":
        confirm = (request.form.get("confirm") or "").strip()
        if not hmac.compare_digest(confirm, "RESTORE"):
            _log("RESTORE FAIL", "confirmation mismatch", name)
            flash("Confirmation must be exactly: RESTORE", "error")
            return redirect(url_for("admin.backups"))

        stop_bot = request.form.get("stop_bot") == "on"
        bot_stopped = request.form.get("bot_stopped") == "on"

        if not stop_bot and not bot_stopped:
            flash("You must either stop the bot or confirm it is already stopped.", "error")
            return redirect(url_for("admin.backup_restore", name=name))

        try:
            if stop_bot:
                ok, msg = _service_stop("voidwave.service")
                if not ok:
                    flash(msg, "error")
                    return redirect(url_for("admin.backup_restore", name=name))
        except Exception as e:
            flash(str(e), "error")
            return redirect(url_for("admin.backup_restore", name=name))

        dst, err = _backup_current(suffix="_prerestore")
        if err:
            _log("RESTORE FAIL", f"no safety backup: {err}")
            flash(err, "error")
            return redirect(url_for("admin.backup_restore", name=name))

        try:
            shutil.copy2(path, "database.db")
        except OSError as e:
            _log("RESTORE FAIL", f"copy error: {e}")
            flash(f"Copy failed: {e}", "error")
            return redirect(url_for("admin.backup_restore", name=name))

        for suffix in ("-wal", "-shm"):
            p = Path("database.db" + suffix)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

        _clear_cache()
        _log("RESTORE OK", f"from {name} (safety backup {dst.name})")

        restart_msg = None
        if stop_bot:
            ok, msg = _service_start("voidwave.service")
            restart_msg = msg if not ok else "Bot restarted."

        return render_template(
            "admin_backups.html",
            backups=_list_backups(),
            restore_done=f"Restored {name} from backup. Safety copy: {dst.name}.",
            restart_msg=restart_msg,
        )

    return render_template(
        "admin_backups.html",
        backups=_list_backups(),
        restore_target=name,
        bot_active=bot_active,
        site_active=site_active,
    )


@admin_bp.route("/backups/<name>/delete", methods=["POST"])
def backup_delete(name):
    from .constants import BACKUP_DIR
    confirm = (request.form.get("confirm") or "").strip()
    if not hmac.compare_digest(confirm, "DELETE"):
        flash("Confirmation must be exactly: DELETE", "error")
        return redirect(url_for("admin.backups"))

    path = BACKUP_DIR / name
    if path.exists() and path.is_file():
        try:
            path.unlink()
            _log("BACKUP DELETE", name)
            flash(f"Deleted backup {name}", "success")
            return redirect(url_for("admin.backups"))
        except OSError as e:
            flash(str(e), "error")
            return redirect(url_for("admin.backups"))
    flash("Backup not found", "error")
    return redirect(url_for("admin.backups"))
