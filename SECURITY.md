# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Instead report them
privately through GitHub's Security Advisories:

1. On the repo page, click **Security** → **Report a vulnerability**.
2. Describe the issue and how to reproduce it. Include the commit/version you
   tested against, and any relevant logs (redact tokens and user IDs).

Reports are usually acknowledged within a few days. Stop testing once code is
fixed and a release/commit is published as announced. Public disclosure without
coordination puts users at risk, so we'd ask for a reasonable window before you
publish write-ups.

## What to include

- The vulnerability's impact (e.g. "admin session forgeable", "LLM prompt
  injection leaks prompt file").
- Steps to reproduce.
- Anything you changed to trigger it.

## Scope & notes

- **`database.db`, `.env`, `admin.log`, `command_logs.txt` are runtime data and
  must never be committed**; if one of these shows up in the repo, report it as
  an urgent secret leak.
- The **admin panel** (`/admin`) is the highest-risk surface: it's gated by
  `ADMIN_PASSWORD` plus an optional webhook 2FA code, and it can start/stop the
  bot and edit user data. If you find a bypass of the login or CSRF checks, treat
  it as critical.
- Any credential in `.env.example` values are placeholders only; a real `.env`
  is never part of the repository (it's gitignored).
- Vulns in **Ollama** are out of scope; a compromised Ollama host undermines the
  AI chat feature by design. Same for the self-hosted **Lavalink** server.