<!-- Thanks for the PR! Fill in the blanks so it's easy to review. -->

## Summary

What does this change do and why?

## Related issue

Fixes #<issue> (or "none").

## How it was tested

Run the pytest suite plus whatever manual checks apply:

- [ ] `./venv/bin/python -m pytest -q` passes
- [ ] `./venv/bin/python bot.py`; bot started, slash commands synced
- [ ] `./venv/bin/python app.py`; dashboard pages render
- [ ] Other, e.g. `./venv/bin/python generate_graphs.py`

## Checklist

- [ ] Existing code style and conventions followed (read `AGENTS.md`)
- [ ] DB schema changes applied in **all** places that maintain the schema
      (see `AGENTS.md` "DB schema is maintained in three places")
- [ ] New `.env` variables documented in `.env.example`
- [ ] No secrets, `.env`, `database.db*`, or log files committed
- [ ] If a `prompts/<name>.txt` persona was added, it's intentional; new
      persona files are gitignored by default