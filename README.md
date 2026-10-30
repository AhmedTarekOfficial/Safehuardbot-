# Sentinel — Discord Moderation & Protection Bot

A practical Python Discord bot built with **discord.py 2.7.1**. Management is handled with Discord slash commands and ephemeral moderation responses.

## Features

- `/kick member reason`
- `/ban member reason delete_hours` (0–168 hours of previous messages; defaults to zero)
- `/unban user_id reason` (Discord numeric user ID)
- `/timeout member minutes reason` (1–40,320 minutes / max 28 days)
- `/untimeout member reason`
- `/purge amount` (1–100 recent messages, text channels and threads)
- `/role add member role` and `/role remove member role`
- `/permissions` **interactive private dashboard**: any server role via Role Select, full enabled/disabled base permission flags with paging, list of all roles, and text search for one permission (`manage_roles`, `ban_members`, `send_messages`, etc.) to find roles granting it either explicitly or through Administrator.
- `/guard antispam enabled` — delete triggering messages and try to timeout the offender for 10 minutes. Triggers on 7+ messages/8 s, 4 identical messages/12 s, or 8+ mentioned users in one message.
- `/guard links enabled` — remove Discord invite links (only); moderators are exempt.
- `/guard raid enabled` — raise an **alert only** when 8+ joins occur within 20 s; no automatic kicks/bans.
- `/guard logs channel` and `/guard clearlogs` — configure a log channel.
- `/guard status` — view current configuration.
- `/helpbot` — command reference.

Anti-spam, invite protection, and raid alerts start **OFF** until explicitly enabled. Configuration persists in SQLite (`sentinel.sqlite3`). Anti-spam counters are in memory and reset on restart.

## Installation

1. Install **Python 3.11+**.
2. Go to <https://discord.com/developers/applications> > **New Application** > **Bot**; create/copy your bot's token. **Never share the token or commit it to GitHub.**
3. Under **Bot > Privileged Gateway Intents**, enable **Server Members Intent** and **Message Content Intent**. These are needed for join-spike and message scanning features. At larger scale, Discord may require privileged intent review.
4. In **OAuth2 > URL Generator** or **Installation**, choose the `bot` and `applications.commands` scopes, and select the bot's necessary permissions:
   - Manage Roles
   - Kick Members
   - Ban Members
   - Moderate Members
   - Manage Messages
   - Read Message History
   - View Channels
   - Send Messages
   - Embed Links
   Avoid Administrator. **Move the bot's highest role above roles/members it needs to manage** but keep it below trusted administrator roles.
5. Invite the bot to a server you own/administer.
6. Copy `.env.example` to `.env`, then set `DISCORD_TOKEN`. For instant commands while testing, set `DEV_GUILD_ID` to your server's numeric ID (enable Developer Mode in Discord, then Copy Server ID). Leave empty to sync global commands instead.
7. In a terminal from this project's directory:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

8. Open Discord and run `/helpbot` or `/permissions`.

## Suggested first-time setup

```text
/guard logs channel:#mod-logs
/guard antispam enabled:True
/guard raid enabled:True
/guard links enabled:True
/guard status
/permissions
```

Commands may show their options in an order chosen by Discord.

## Permissions dashboard behavior

- Lists **base, server-wide role permission bits**, not all effective member permissions.
- The search result includes roles with **Administrator** because Administrator implicitly bypasses normal permission checks. In role detail view, the individual raw flags remain shown accurately as enabled/disabled.
- Server `@everyone` and other assigned roles add permissions; channel-level allows/denies can alter effective permissions.
- Discord's server owner has special authority independent of roles.
- For your security, only members with Manage Server can open the panel, and only the member who opened a private panel can press its buttons.
- Panels expire after 10 minutes; reopen with `/permissions`.

## Security notes

- Every moderation command checks the acting moderator's permissions, their role hierarchy, and the bot's hierarchy. Role assignment also prevents handing out a role that grants permissions the moderator doesn't already possess (except server owner/Administrator).
- The bot will not kick/ban/timeout the server owner or its own account, and cannot timeout an Administrator.
- Spam and invite filters exempt members with Manage Messages in the relevant channel and the server owner.
- This starter does **not** implement automated audit-log rollback, anti-nuke, machine learning classification, or a web dashboard. A raid detection alert is **not** raid prevention.
- Use a private testing server before production; anti-spam thresholds might need adjustment for your community.
- Logs only go to the configured Discord channel; no full message contents are stored in SQLite. Bot logs may contain technical errors; keep server files secure.

## Testing

```bash
python -m unittest discover -s tests -v
python -m compileall -q main.py sentinel tests
```

## Hosting

Run the process on an always-on machine or VPS. Closing your terminal stops the bot. To keep it always online, use a managed process supervisor, Docker service, or hosting that supports long-running Python processes. Secure the `.env` file and back up `sentinel.sqlite3` (or `data/sentinel.sqlite3` with Docker).

### Docker Compose option

Copy `.env.example` to `.env` and fill in the token as above, then run:

```bash
docker compose up -d --build
docker compose logs -f
```

Settings are kept in `./data/sentinel.sqlite3` and survive container restarts.
