import logging

LOG_FORMAT = '%(levelname)-10s %(name)s  %(message)s'

_CUSTOM_LEVELS = [
    ("COMMAND", 21),
    ("MESSAGE", 22),
    ("GUILD", 23),
    ("BLOCKED", 24),
    ("WEBHOOK", 25),
]

for _name, _level in _CUSTOM_LEVELS:
    logging.addLevelName(_level, _name)


def setup_logging():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)


class Logger(logging.Logger):
    def command(self, msg, *args, **kwargs):
        self.log(21, msg, *args, **kwargs)

    def message(self, msg, *args, **kwargs):
        self.log(22, msg, *args, **kwargs)

    def guild(self, msg, *args, **kwargs):
        self.log(23, msg, *args, **kwargs)

    def blocked(self, msg, *args, **kwargs):
        self.log(24, msg, *args, **kwargs)

    def webhook(self, msg, *args, **kwargs):
        self.log(25, msg, *args, **kwargs)


logging.setLoggerClass(Logger)
