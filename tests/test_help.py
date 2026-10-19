from cogs.general import DOCUMENTED_ALIASES, DOCUMENTED_COMMANDS, LABELS, GeneralCog, _resolve_topic


def _cog():
    return GeneralCog.__new__(GeneralCog)


def test_help_embeds_fit_discord_limits():
    cog = _cog()
    for cat in LABELS:
        embed = cog._help_embed(cat)
        assert len(embed.title or "") <= 256, cat
        assert len(embed.description or "") <= 4096, cat
        for field in embed.fields:
            assert len(field.value) <= 1024, f"{cat} / {field.name}"


def test_resolve_topic_categories():
    for cat, label in LABELS.items():
        assert _resolve_topic(cat) == cat
        assert _resolve_topic(label) == cat


def test_resolve_topic_aliases():
    for alias, cat in DOCUMENTED_ALIASES.items():
        assert _resolve_topic(alias) == cat


def test_resolve_topic_commands():
    for cat, cmds in DOCUMENTED_COMMANDS.items():
        for cmd in cmds:
            assert _resolve_topic(cmd) == cat, cmd
            assert _resolve_topic(f"/{cmd}") == cat, cmd


def test_resolve_topic_unknown():
    assert _resolve_topic("faltu server hat") is None
    assert _resolve_topic("not-a-topic") is None
    assert _resolve_topic("") is None
    assert _resolve_topic("   ") is None
