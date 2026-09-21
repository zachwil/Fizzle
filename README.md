# Fizzle Campaign Archive

Fizzle is a private, zero-dependency campaign manager with separate Dungeon Master, player, and table-display experiences. It runs on Python and SQLite and can stay on the DM's computer while being shared securely with players through Tailscale Funnel.

## Features

### Dungeon Master dashboard

- Campaign overview with full-text search across the archive
- Combined player and character dossiers with read-only profiles and explicit edit mode
- Player quick-reference cards for level, armor class, maximum HP, passive Perception, speed, initiative, and spell save DC
- Read-only profile views for NPCs, locations, factions, quests, notes, tasks, sessions, rumours, resources, and maps
- Player account creation, archiving, custom passwords, and temporary-password resets
- Private two-way correspondence with unread-message notifications and a per-player letter history
- Session calendar and session-preparation task list
- Favorites, statuses, tags, and structured campaign notes
- d100 Drakkenheim rumour roller
- Fantasy Name Forge with gender and ancestry options plus a persistent saved-name bank
- Persistent initiative tracker with active-player selection, saved or custom NPCs, automatic NPC initiative rolls from modifiers, manual sorting, turn highlighting, and round tracking
- Unified Source Library on the Overview and Resources pages
- Automatic discovery and linking of files and subfolders placed in `resources/`

### Player portal

- Individual password-protected player accounts
- Read-only character dossier with a deliberate Edit Dossier mode
- Character identity, personal quest, relationships, goals, and DM quick-reference fields
- Private letters from the DM
- Secret personal-quest updates and letters sent to the DM
- Upcoming session schedule and quick links
- Players can see only their own dossier and correspondence

### Live table display

- Separate presentation-only login suitable for an iPad or shared screen
- Live initiative order, round number, and highlighted current turn
- DM-controlled message broadcasts
- DM-controlled image uploads up to 6 MB
- Standard, full-screen message, and full-screen image layouts
- Individual Clear Message and Clear Image controls
- Automatic updates without refreshing the iPad
- No access to private campaign records or DM tools

## Requirements

- Python 3
- A modern web browser
- No third-party Python packages

## Run locally

```bash
python3 app.py
```

The local DM dashboard opens at <http://127.0.0.1:8765>. Press `Ctrl+C` to stop the server.

The main routes are:

| View | URL |
| --- | --- |
| DM login | `/dm` |
| DM dashboard | `/dashboard` |
| Player portal | `/portal` |
| iPad/table display | `/display` |

## Configuration

Create an ignored `.env` file in the project directory when using the included desktop launcher or systemd service:

```bash
PUBLIC_URL=https://your-device.your-tailnet.ts.net
DM_USERNAME=dm
DM_PASSWORD=choose-a-strong-password
DISPLAY_USERNAME=dashboard
DISPLAY_PASSWORD=choose-a-display-password
```

`DISPLAY_USERNAME` defaults to `dashboard`. If `DISPLAY_PASSWORD` is omitted, the table display uses `DM_PASSWORD`. The display account is presentation-only and cannot open the DM archive.

When running `python3 app.py` directly, export these variables into the process environment first. The included launcher reads `.env` automatically.

## Player accounts

Create or edit a player from **Players & Characters** in the DM dashboard. New players receive a portal account and can be assigned a custom password. Password resets use the temporary password:

```text
drakkenheim
```

The player must choose a new password after logging in with a reset temporary password.

## Initiative and table display

1. Open **Initiative Tracker** in the DM sidebar.
2. Add active player characters and any number of saved or custom NPCs. NPCs roll automatically using the supplied initiative modifier.
3. Enter player initiative values, then select **Sort** or **Start**.
4. Use **Next Turn** to advance the highlighted combatant and round.
5. Open **Table Display** in the DM sidebar to send a message, upload an image, or select a presentation focus mode.
6. On the iPad, open `/display` and log in with the display account.

The initiative encounter and display broadcasts are stored locally and survive service restarts. The iPad polls for updates approximately every 1.5 seconds.

## Publish with Tailscale Funnel

Tailscale Funnel keeps `campaign.db` on the DM computer while making the portal available over public HTTPS.

1. Install and connect Tailscale.
2. Put the assigned `https://...ts.net` address in `PUBLIC_URL` inside `.env`.
3. Start Fizzle.
4. Publish the local service:

```bash
tailscale funnel --bg 8765
```

Share these addresses as needed:

```text
https://your-device.your-tailnet.ts.net/portal
https://your-device.your-tailnet.ts.net/display
```

The computer, Fizzle service, and Tailscale must remain running while remote users are connected. Funnel itself supports only the Tailscale `*.ts.net` hostname; a purchased domain can redirect to it, or a separate reverse proxy can preserve a custom domain in the address bar.

## Desktop launcher and service

The repository includes:

- `Drakkenheim Campaign.desktop` — desktop shortcut
- `launch-drakkenheim.sh` — starts the service, restores Funnel, and opens the DM login
- `drakkenheim-campaign.service` — user-level systemd service

The legacy filenames do not affect the Fizzle branding or application behavior.

## Data and backups

All campaign content is stored in `campaign.db` by default. Back up this file to preserve:

- Campaign records and player dossiers
- Player account credentials
- Private correspondence
- Saved generated names
- Initiative and table-display state
- Currently broadcast images and messages

Uploaded table-display images are stored inside the SQLite database as data, so large images increase the database size. The upload limit is 6 MB per image.

The local database, `.env`, logs, and sourcebook files are intentionally excluded from Git.

### Adding library files

Copy PDFs, images, documents, or other reference files into the `resources/` directory. Fizzle scans the directory whenever the Overview or Resources page loads, so new files appear automatically without restarting the service. Subfolders are supported and shown on each file card. Hidden files and symbolic links are ignored.

## Render deployment

The included `render.yaml` defines a Starter web service with a 1 GB persistent disk. To deploy it:

1. Connect the Fizzle repository to Render.
2. Create the service from `render.yaml` or configure an equivalent web service.
3. Set `DM_PASSWORD` to a strong password.
4. Set `PUBLIC_URL` to the Render service URL without a trailing slash.
5. Optionally set `DISPLAY_USERNAME` and `DISPLAY_PASSWORD`.

The hosted database is stored at `/var/data/campaign.db`. A persistent disk is required if campaign changes must survive redeployments or restarts. The hosted database is separate from the local database unless it is copied manually.

## Security notes

- Keep `.env` and `campaign.db` private.
- Use strong, unique DM and display passwords when exposing Fizzle publicly.
- The DM dashboard requires authentication whenever `PUBLIC_URL` is configured.
- Player sessions, DM sessions, and display sessions use separate cookies and permissions.
- The player portal never returns DM-only player secrets.
