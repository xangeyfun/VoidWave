from pathlib import Path

BACKUP_DIR = Path.home() / "Backups" / "VoidWave"
ADMIN_LOG_FILE = "admin.log"
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 900
TWOFA_TTL = 120
KEEP_BACKUPS = 48
BOT_SERVICE = "voidwave.service"

TABLES = {
    "users", "bot_stats", "guild_settings", "level_roles", "vote_boosts",
    "user_ratings", "playlists", "playlist_tracks",
}

BLOCK_FEATURES = {
    "ai": ("AI features", "/ai command, @mention replies, and DM replies"),
    "feedback": ("/feedback", "The /feedback command"),
    "leveling": ("Leveling", "Earning XP from messages and voice channels"),
    "music": ("Music", "/music commands and playback in voice channels"),
    "commands": ("All commands", "Every slash command (nuclear option)"),
}

BLOCK_DURATIONS = [
    ("", "Keep current"),
    ("perm", "Permanent"),
    ("3600", "1 hour"),
    ("21600", "6 hours"),
    ("43200", "12 hours"),
    ("86400", "1 day"),
    ("259200", "3 days"),
    ("604800", "1 week"),
    ("2592000", "30 days"),
]

VALID_BLOCK_DURATIONS = {int(seconds) for seconds, _ in BLOCK_DURATIONS if seconds.isdigit()}

REQUIRED_USERS_COLUMNS = {
    "guild_id", "user_id", "display_name", "username", "level",
    "progress", "out_of", "last_message", "total_messages",
    "total_messages_xp", "total_xp", "vc_minutes", "vc_xp_minutes",
    "avatar_hash", "command_uses", "rated", "prompt_sent",
}

REQUIRED_GUILD_COLUMNS = {
    "guild_id", "level_channel_id", "level_channel_enabled",
    "vote_announce_enabled", "ai_enabled",
    "qotd_enabled", "qotd_channel", "qotd_role_id",
    "last_qotd_id", "last_qotd_thread_id", "qotd_queue",
    "delete_old_qotd", "qotd_time", "qotd_tz", "last_qotd_date",
}

REQUIRED_VOTE_BOOST_COLUMNS = {"user_id", "multiplier", "expires_at", "last_vote_at"}

USER_FIELDS = {
    "guild_id": "pk",
    "user_id": "pk",
    "display_name": "text",
    "username": "text",
    "avatar_hash": "text",
    "level": "int",
    "progress": "int",
    "out_of": "int",
    "total_xp": "int",
    "total_messages": "int",
    "total_messages_xp": "int",
    "vc_minutes": "int",
    "vc_xp_minutes": "int",
    "last_message": "text",
    "command_uses": "int",
    "rated": "int",
    "prompt_sent": "int",
}

USER_PK_FIELDS = ("guild_id", "user_id")

RELATED_USER_TABLES = (
    "vote_boosts",
    "user_blocks",
    "user_prefs",
    "vote_reminders",
    "user_ratings",
    "playlists",
)

GUILD_SETTING_FIELDS = {
    "level_channel_id": "int",
    "level_channel_enabled": "bool",
    "vote_announce_enabled": "bool",
    "ai_enabled": "bool",
    "qotd_enabled": "bool",
    "qotd_channel": "int",
    "qotd_role_id": "int",
    "delete_old_qotd": "bool",
    "last_qotd_id": "int",
    "last_qotd_thread_id": "int",
    "last_qotd_date": "text",
}

LEVEL_ROLE_FIELDS = {
    "level": "int",
    "role_id": "int",
}
