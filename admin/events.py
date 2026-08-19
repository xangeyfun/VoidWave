import time
import json

from flask import Response, render_template, stream_with_context

from . import admin_bp
from .helpers import _recent_events


@admin_bp.route("/events")
def events_page():
    return render_template("admin_events.html")


@admin_bp.route("/api/events/stream")
def events_stream():
    def generate():
        last_id = 0
        events = _recent_events(limit=20, since_id=0)
        if events:
            last_id = events[0]["id"]
            yield f"data: {json.dumps({'type': 'init', 'events': events})}\n\n"

        while True:
            time.sleep(2)
            new_events = _recent_events(limit=20, since_id=last_id)
            if new_events:
                last_id = new_events[0]["id"]
                yield f"data: {json.dumps({'type': 'update', 'events': new_events})}\n\n"
            else:
                yield f": keepalive {int(time.time())}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@admin_bp.route("/api/events")
def events_api():
    from flask import request
    since_id = int(request.args.get("since", 0))
    events = _recent_events(limit=100, since_id=since_id)
    return {"events": events}
