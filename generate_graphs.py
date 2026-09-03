import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
from datetime import datetime
import numpy as np
import json
import os
import logging

logger = logging.getLogger("generate_graphs")

DATA_FILE = "stats_history.json"
OUTPUT_DIR = "Graphs"

BG_COLOR = "#1a1d23"
PLOT_COLOR = "#23272e"
GRID_COLOR = "#2e3239"
TEXT_COLOR = "#dcddde"
SUBTEXT_COLOR = "#8e9297"

GRAPHS = [
    ("total_guilds", "Total Servers", "Servers", "#5865F2"),
    ("total_members", "Total Members", "Members", "#57F287"),
    ("total_users", "Tracked Users", "Users", "#FEE75C"),
    ("total_xp", "Total XP Earned", "XP", "#EB459E"),
    ("total_messages", "Total Messages", "Messages", "#ED4245"),
    ("total_vc_minutes", "Total Voice Hours", "Hours", "#5865F2"),
    ("avg_level", "Average Level", "Level", "#EB459E"),
]

DERIVED_GRAPHS = [
    ("xp_per_user", "XP per User", "XP / User", "#EB459E"),
    ("messages_per_user", "Messages per User", "Msgs / User", "#ED4245"),
    ("vc_hours_per_user", "Voice Hours per User", "Hrs / User", "#5865F2"),
    ("msg_xp_ratio", "Message XP Ratio", "% Messages with XP", "#57F287"),
    ("vc_xp_ratio", "Voice XP Ratio", "% VC Minutes with XP", "#FEE75C"),
]

MAX_SCATTER_DOTS = 30

COMBINED_GRAPHS = [
    ("total_guilds", "Servers", "#5865F2", 1),
    ("total_members", "Members", "#57F287", 1),
    ("total_users", "Tracked Users", "#FEE75C", 1),
    ("total_xp", "Total XP", "#EB459E", 2),
    ("total_messages", "Total Messages", "#ED4245", 2),
    ("total_vc_minutes", "Voice Hours", "#5865F2", 2),
]


def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def parse_timestamps(data):
    return [datetime.fromisoformat(snap["timestamp"]) for snap in data]


def apply_xaxis(ax, timestamps):
    max_ticks = 14
    if len(timestamps) < 2:
        return
    span = (timestamps[-1] - timestamps[0]).total_seconds()

    if span < 3600:
        interval = max(1, int(span / max_ticks / 60))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=interval))
    elif span < 86400 * 3:
        interval = max(1, int(span / max_ticks / 3600))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=interval))
    elif span < 86400 * 30:
        interval = max(1, int(span / max_ticks / 86400))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=interval))
    elif span < 86400 * 365:
        interval = max(1, int(span / max_ticks / 86400 / 7))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=interval))
    else:
        interval = max(1, int(span / max_ticks / 86400 / 365))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_major_locator(mdates.YearLocator(interval=interval))


def get_tick_positions(ax, timestamps):
    loc = ax.xaxis.get_major_locator()
    ticks = loc.tick_values(timestamps[0], timestamps[-1])
    return [mdates.num2date(t) for t in ticks]


def make_graph(data, key, title, ylabel, color, filename, value_fn=None):
    timestamps = parse_timestamps(data)
    values = []

    for snap in data:
        if value_fn:
            values.append(value_fn(snap))
        else:
            val = snap[key]
            if key == "total_vc_minutes":
                val = val / 60
            values.append(val)

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(PLOT_COLOR)

    ax.plot(timestamps, values, color=color, linewidth=2.5, zorder=3)
    ax.fill_between(timestamps, values, alpha=0.12, color=color, zorder=2)

    ax.set_title(title, fontsize=18, fontweight="bold", color=TEXT_COLOR, pad=16)
    ax.set_ylabel(ylabel, fontsize=12, color=SUBTEXT_COLOR, labelpad=10)

    ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7, linestyle="--")
    ax.tick_params(axis="both", colors=SUBTEXT_COLOR, labelsize=10)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x == int(x) else f"{x:,.1f}"))

    if values:
        y_max = max(values)
        y_min = min(values)
        if y_max == y_min:
            padding = max(abs(y_max) * 0.2, 1)
        else:
            padding = (y_max - y_min) * 0.3
        ax.set_ylim(bottom=y_min - padding, top=y_max + padding)

    for spine in ax.spines.values():
        spine.set_visible(False)

    apply_xaxis(ax, timestamps)
    fig.autofmt_xdate(rotation=40, ha="right")
    plt.setp(ax.get_xticklabels(), color=SUBTEXT_COLOR)

    plt.tight_layout(pad=2)
    fig.canvas.draw()

    tick_times = get_tick_positions(ax, timestamps)
    ts_arr = np.array([t.timestamp() for t in timestamps])
    plot_idx = []
    for tick_t in tick_times:
        tick_ts = tick_t.timestamp()
        nearest = int(np.argmin(np.abs(ts_arr - tick_ts)))
        if nearest not in plot_idx:
            plot_idx.append(nearest)
    plot_idx.sort()

    ax.scatter([timestamps[i] for i in plot_idx], [values[i] for i in plot_idx],
               color=color, s=16, zorder=6)
    last_label_x = None
    min_pixel_gap = 40
    for i in plot_idx:
        ts, val = timestamps[i], values[i]
        label = f"{val:,.0f}" if val == int(val) else f"{val:,.1f}"
        disp = ax.transData.transform((mdates.date2num(ts), val))
        if last_label_x is not None and abs(disp[0] - last_label_x) < min_pixel_gap:
            continue
        last_label_x = disp[0]
        ax.annotate(label, (ts, val), textcoords="offset points", xytext=(0, 14),
                    ha="center", va="bottom", fontsize=7, color=SUBTEXT_COLOR, zorder=5)
    path = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", path)


def make_combined_graph(data):
    timestamps = parse_timestamps(data)

    fig, axes = plt.subplots(3, 2, figsize=(18, 16))
    fig.patch.set_facecolor(BG_COLOR)
    fig.suptitle("All Bot Stats", fontsize=22, fontweight="bold", color=TEXT_COLOR, y=0.98)

    for idx, (key, label, color, _) in enumerate(COMBINED_GRAPHS):
        row = idx // 2
        col = idx % 2
        ax = axes[row][col]
        ax.set_facecolor(PLOT_COLOR)

        values = []
        for snap in data:
            val = snap[key]
            if key == "total_vc_minutes":
                val = val / 60
            values.append(val)

        ax.plot(timestamps, values, color=color, linewidth=2, zorder=3)
        ax.fill_between(timestamps, values, alpha=0.12, color=color, zorder=2)

        ax.set_title(label, fontsize=14, fontweight="bold", color=TEXT_COLOR, pad=10)
        ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7, linestyle="--")
        ax.tick_params(axis="both", colors=SUBTEXT_COLOR, labelsize=9)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x == int(x) else f"{x:,.1f}"))

        for spine in ax.spines.values():
            spine.set_visible(False)

        if values:
            y_max = max(values)
            y_min = min(values)
            if y_max == y_min:
                padding = max(abs(y_max) * 0.2, 1)
            else:
                padding = (y_max - y_min) * 0.3
                ax.set_ylim(bottom=y_min - padding, top=y_max + padding)

        for spine in ax.spines.values():
            spine.set_visible(False)

        apply_xaxis(ax, timestamps)
        fig.autofmt_xdate(rotation=40, ha="right")
        plt.setp(ax.get_xticklabels(), color=SUBTEXT_COLOR)

    plt.tight_layout(pad=3, rect=[0, 0, 1, 0.96])
    path = os.path.join(OUTPUT_DIR, "13_all_stats.png")
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", path)


def make_ratio_graph(data):
    timestamps = parse_timestamps(data)

    ratio_fns = {
        "xp_per_user": ("XP per User", "#EB459E", lambda s: s["total_xp"] / s["total_users"] if s["total_users"] else 0),
        "messages_per_user": ("Messages per User", "#ED4245", lambda s: s["total_messages"] / s["total_users"] if s["total_users"] else 0),
        "vc_hours_per_user": ("Voice Hours per User", "#5865F2", lambda s: s["total_vc_minutes"] / s["total_users"] / 60 if s["total_users"] else 0),
        "msg_xp_ratio": ("Message XP Ratio", "#57F287", lambda s: s["total_messages_xp"] / s["total_messages"] * 100 if s["total_messages"] else 0),
        "vc_xp_ratio": ("Voice XP Ratio", "#FEE75C", lambda s: s["total_vc_xp_minutes"] / s["total_vc_minutes"] * 100 if s["total_vc_minutes"] else 0),
    }

    fig, axes = plt.subplots(3, 2, figsize=(18, 16))
    fig.patch.set_facecolor(BG_COLOR)
    fig.suptitle("Ratios & Per-User Stats", fontsize=22, fontweight="bold", color=TEXT_COLOR, y=0.98)

    items = list(ratio_fns.items())
    for idx in range(6):
        row = idx // 2
        col = idx % 2
        ax = axes[row][col]
        ax.set_facecolor(PLOT_COLOR)

        if idx < len(items):
            key, (label, color, fn) = items[idx]
            values = [fn(snap) for snap in data]

            ax.plot(timestamps, values, color=color, linewidth=2, zorder=3)
            ax.fill_between(timestamps, values, alpha=0.12, color=color, zorder=2)

            ax.set_title(label, fontsize=14, fontweight="bold", color=TEXT_COLOR, pad=10)
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x == int(x) else f"{x:,.1f}"))

            if values:
                y_max = max(values)
                y_min = min(values)
                if y_max == y_min:
                    padding = max(abs(y_max) * 0.2, 1)
                else:
                    padding = (y_max - y_min) * 0.3
                ax.set_ylim(bottom=y_min - padding, top=y_max + padding)
        else:
            ax.set_visible(False)

        ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7, linestyle="--")
        ax.tick_params(axis="both", colors=SUBTEXT_COLOR, labelsize=9)

        for spine in ax.spines.values():
            spine.set_visible(False)

        apply_xaxis(ax, timestamps)
        fig.autofmt_xdate(rotation=40, ha="right")
        plt.setp(ax.get_xticklabels(), color=SUBTEXT_COLOR)

    plt.tight_layout(pad=3, rect=[0, 0, 1, 0.96])
    path = os.path.join(OUTPUT_DIR, "14_ratios_overview.png")
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", path)


def make_readme_banner(data):
    latest = data[-1]

    stats = [
        ("SERVERS", latest["total_guilds"], "#5865F2", [s["total_guilds"] for s in data]),
        ("MEMBERS", latest["total_members"], "#57F287", [s["total_members"] for s in data]),
        ("XP EARNED", latest["total_xp"], "#EB459E", [s["total_xp"] for s in data]),
        ("MESSAGES", latest["total_messages"], "#ED4245", [s["total_messages"] for s in data]),
        ("VOICE HOURS", round(latest["total_vc_minutes"] / 60, 1), "#5865F2", [s["total_vc_minutes"] / 60 for s in data]),
    ]

    fig = plt.figure(figsize=(18, 4.5))
    fig.patch.set_facecolor("#111318")

    gs = fig.add_gridspec(2, 5, hspace=0.15, wspace=0.25,
                          left=0.03, right=0.97, top=0.85, bottom=0.01)

    fig.text(0.5, 0.95, "Real-time stats, updated every hour", fontsize=18,
             color="#8e9297", ha="center", va="center", fontfamily="sans-serif", fontweight="bold")

    for i, (label, value, color, values) in enumerate(stats):
        ax_num = fig.add_subplot(gs[0, i])
        ax_num.set_facecolor("#111318")
        ax_num.set_xlim(0, 1)
        ax_num.set_ylim(0, 1)
        ax_num.axis("off")

        for spine in ax_num.spines.values():
            spine.set_visible(False)

        formatted = f"{value:,.0f}" if isinstance(value, int) or value == int(value) else f"{value:,.1f}"
        ax_num.text(0.5, 0.3, formatted, fontsize=30, fontweight="bold",
                    color="white", ha="center", va="center", fontfamily="sans-serif")
        ax_num.text(0.5, -0.1, label, fontsize=10, color=color,
                    ha="center", va="center", fontfamily="sans-serif",
                    fontweight="bold")

        ax_spark = fig.add_subplot(gs[1, i])
        ax_spark.set_facecolor("#111318")

        spark_vals = np.array(values, dtype=float)
        spark_x = np.linspace(0, 1, len(spark_vals))

        if spark_vals.max() != spark_vals.min():
            spark_norm = (spark_vals - spark_vals.min()) / (spark_vals.max() - spark_vals.min())
        else:
            spark_norm = np.ones_like(spark_vals) * 0.5

        ax_spark.fill_between(spark_x, spark_norm, alpha=0.15, color=color)
        ax_spark.plot(spark_x, spark_norm, color=color, linewidth=2)
        ax_spark.set_xlim(0, 1)
        ax_spark.set_ylim(0, 1.2)
        ax_spark.axis("off")

        for spine in ax_spark.spines.values():
            spine.set_visible(False)

    path = os.path.join("static", "images", "stats.png")
    fig.savefig(path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    logger.info("Saved %s", path)


def main():
    if not os.path.exists(DATA_FILE):
        logger.error("%s not found. Run the bot first to collect data.", DATA_FILE)
        return

    data = load_data()
    if not data:
        logger.error("No data in stats history file.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logger.info("Generating graphs from %s snapshots...", len(data))

    for idx, (key, title, ylabel, color) in enumerate(GRAPHS, start=1):
        make_graph(data, key, title, ylabel, color, filename=f"{idx:02d}_{key}.png")

    derived_fns = {
        "xp_per_user": lambda s: s["total_xp"] / s["total_users"] if s["total_users"] else 0,
        "messages_per_user": lambda s: s["total_messages"] / s["total_users"] if s["total_users"] else 0,
        "vc_hours_per_user": lambda s: s["total_vc_minutes"] / s["total_users"] / 60 if s["total_users"] else 0,
        "msg_xp_ratio": lambda s: s["total_messages_xp"] / s["total_messages"] * 100 if s["total_messages"] else 0,
        "vc_xp_ratio": lambda s: s["total_vc_xp_minutes"] / s["total_vc_minutes"] * 100 if s["total_vc_minutes"] else 0,
    }

    offset = len(GRAPHS) + 1
    for idx, (key, title, ylabel, color) in enumerate(DERIVED_GRAPHS, start=offset):
        make_graph(data, key, title, ylabel, color, filename=f"{idx:02d}_{key}.png", value_fn=derived_fns[key])

    make_combined_graph(data)
    make_ratio_graph(data)
    make_readme_banner(data)

    logger.info("Done! Graphs saved to %s/", OUTPUT_DIR)


if __name__ == "__main__":
    main()
