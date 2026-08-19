from flask import render_template, redirect, url_for, request, jsonify, abort

from . import admin_bp
from .helpers import _log, _service_status, _service_logs, _service_stop, _service_start
from .constants import BOT_SERVICE


@admin_bp.route("/bot")
def bot_status():
    status = _service_status(BOT_SERVICE)
    logs = _service_logs(BOT_SERVICE, 80)
    return render_template("admin_bot.html", status=status, logs=logs, service=BOT_SERVICE)


@admin_bp.route("/bot/confirm/<action>")
def bot_confirm(action):
    if action not in ("stop", "restart"):
        abort(404)
    status = _service_status(BOT_SERVICE)
    return render_template("admin_bot_confirm.html", action=action, status=status, service=BOT_SERVICE)


@admin_bp.route("/bot/action/<action>", methods=["POST"])
def bot_action(action):
    if action not in ("start", "stop", "restart"):
        abort(404)

    confirm_text = request.form.get("confirm", "").strip()
    if action == "stop" and confirm_text.upper() != "STOP":
        return redirect(url_for("admin.bot_confirm", action="stop", err="Type STOP to confirm"))
    if action == "restart" and confirm_text.upper() != "RESTART":
        return redirect(url_for("admin.bot_confirm", action="restart", err="Type RESTART to confirm"))

    if action == "stop":
        ok, msg = _service_stop(BOT_SERVICE)
    elif action == "start":
        ok, msg = _service_start(BOT_SERVICE)
    else:
        ok, msg = _service_stop(BOT_SERVICE)
        if ok:
            ok, msg = _service_start(BOT_SERVICE)
            if ok:
                msg = f"Restarted {BOT_SERVICE}"

    _log("BOT ACTION", f"{action} -> {msg}")
    if ok:
        return redirect(url_for("admin.bot_status", msg=msg))
    return redirect(url_for("admin.bot_status", err=msg))


@admin_bp.route("/bot/logs")
def bot_logs():
    lines = _service_logs(BOT_SERVICE, 300)
    return jsonify({"lines": lines})
