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
}

REQUIRED_USERS_COLUMNS = {
    "guild_id", "user_id", "display_name", "username", "level",
    "progress", "out_of", "last_message", "total_messages",
    "total_messages_xp", "total_xp", "vc_minutes", "vc_xp_minutes",
    "avatar_hash",
}

USER_FIELDS = {
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
}

GUILD_SETTING_FIELDS = {
    "level_channel_id": "int",
    "level_channel_enabled": "bool",
    "qotd_enabled": "bool",
    "qotd_channel": "int",
    "qotd_role_id": "int",
    "delete_old_qotd": "bool",
}

LEVEL_ROLE_FIELDS = {
    "level": "int",
    "role_id": "int",
}
