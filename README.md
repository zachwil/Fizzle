# Fizzle Campaign Archive

A private campaign organizer with separate Dungeon Master and player views. It can run locally or as a hosted Render service.

## Run it

```bash
python3 app.py
```

The dashboard opens at <http://127.0.0.1:8765>. Press `Ctrl+C` in the terminal to stop it.

## Included

- Characters, NPCs, locations, factions, quests, notes, resources, and maps
- Player dossiers for character details, relationships, secrets, goals, and notes
- Full-text campaign search
- A d100 roller containing the printed-page-19 rumour table
- Favorites, statuses, and tags
- Direct access to sourcebook PDFs in `resources/`
- SQLite storage with no dependencies or account required

Back up `campaign.db` to preserve your campaign records.

## Deploy on Render

The included `render.yaml` creates a Starter web service and a 1 GB persistent disk. In Render:

1. Create a new Blueprint from this repository.
2. Set `DM_PASSWORD` to a strong, unique password.
3. Set `PUBLIC_URL` to the service URL Render assigns, without a trailing slash.
4. Open `/dm` for the authenticated DM dashboard or `/portal` for player login.

The hosted database is stored at `/var/data/campaign.db`. It is separate from the local `campaign.db`, which is intentionally excluded from Git. Sourcebook files under `resources/` are also excluded.

## Publish the local app with Tailscale Funnel

To keep `campaign.db` on this computer while allowing browser access over the internet, put the following in the ignored `.env` file:

```bash
PUBLIC_URL=https://your-device.your-tailnet.ts.net
DM_USERNAME=dm
DM_PASSWORD=choose-a-strong-password
```

The desktop launcher reads this file automatically. Start the app, then publish its local port with `tailscale funnel --bg 8765`. The computer and app must remain running while the portal is in use.
