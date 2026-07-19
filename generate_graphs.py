import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import json
import os

DATA_FILE = "stats_history.json"
OUTPUT_DIR = "Graphs"

GRAPHS = [
    ("total_guilds", "Total Servers", "Servers", "#5865F2"),
    ("total_members", "Total Members", "Members", "#57F287"),
    ("total_users", "Tracked Users", "Users", "#FEE75C"),
    ("total_xp", "Total XP Earned", "XP", "#EB459E"),
    ("total_messages", "Total Messages", "Messages", "#ED4245"),
    ("total_vc_minutes", "Total Voice Hours", "Hours", "#5865F2"),
    ("avg_level", "Average Level", "Level", "#EB459E"),
]


def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def make_graph(data, key, title, ylabel, color):
    timestamps = []
    values = []

    for snap in data:
        ts = snap["timestamp"]
        val = snap[key]
        if key == "total_vc_minutes":
            val = val / 60
        timestamps.append(ts)
        values.append(val)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(timestamps, values, color=color, linewidth=2, marker="o", markersize=3)
    ax.fill_between(timestamps, values, alpha=0.1, color=color)

    ax.set_title(title, fontsize=16, fontweight="bold", color="white")
    ax.set_ylabel(ylabel, fontsize=12, color="white")
    ax.set_xlabel("Time", fontsize=12, color="white")

    fig.patch.set_facecolor("#2C2F33")
    ax.set_facecolor("#2C2F33")
    ax.tick_params(colors="white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    ax.title.set_color("white")
    for spine in ax.spines.values():
        spine.set_color("#40444B")

    if len(timestamps) > 1:
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
    fig.autofmt_xdate()

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, f"{key}.png")
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Saved {path}")


def main():
    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found. Run the bot first to collect data.")
        return

    data = load_data()
    if not data:
        print("Error: No data in stats history file.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Generating graphs from {len(data)} snapshots...")

    for key, title, ylabel, color in GRAPHS:
        make_graph(data, key, title, ylabel, color)

    print(f"Done! Graphs saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
