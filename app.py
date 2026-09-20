#!/usr/bin/env python3
"""Drakkenheim campaign dashboard: zero-dependency local web app."""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import json
import hashlib
import hmac
import mimetypes
import os
import secrets
import socket
import sqlite3
import threading
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "campaign.db"
STATIC = ROOT / "static"
KINDS = {"player", "npc", "location", "faction", "quest", "note", "todo", "session", "rumor", "resource", "map", "message"}
SESSIONS = {}
DM_SESSIONS = set()
PORT = int(os.environ.get("PORT", "8765"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
DM_USERNAME = os.environ.get("DM_USERNAME", "dm").lower()
DM_PASSWORD = os.environ.get("DM_PASSWORD", "")


def local_network_ip():
    """Return the host's preferred LAN address without sending network data."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
        summary TEXT DEFAULT '', body TEXT DEFAULT '', tags TEXT DEFAULT '',
        status TEXT DEFAULT '', favorite INTEGER DEFAULT 0,
        extra TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS player_accounts (
        player_id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, salt TEXT NOT NULL,
        must_change INTEGER DEFAULT 1,
        FOREIGN KEY(player_id) REFERENCES entries(id) ON DELETE CASCADE)""")
    return conn


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240_000).hex()


def set_password(conn, player_id, username, password, must_change=0):
    salt = secrets.token_hex(16)
    digest = password_hash(password, salt)
    conn.execute("""INSERT INTO player_accounts(player_id,username,password_hash,salt,must_change)
        VALUES(?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET
        username=excluded.username,password_hash=excluded.password_hash,
        salt=excluded.salt,must_change=excluded.must_change""",
        (player_id, username.strip().lower(), digest, salt, must_change))


def row_dict(row):
    item = dict(row)
    try: item["extra"] = json.loads(item["extra"] or "{}")
    except json.JSONDecodeError: item["extra"] = {}
    item["favorite"] = bool(item["favorite"])
    return item


def seed_players():
    """Create the initial Session 0 roster once, without touching later edits."""
    names = ("Derrek", "Kylan", "Charles", "Gaelen", "Wilgy", "Victor", "Loyd", "Seth")
    with db() as conn:
        if conn.execute("SELECT count(*) FROM entries WHERE kind='player'").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO entries(kind,name,status,extra) VALUES('player',?,'Session 0',?)",
                ((name, json.dumps({"character_name":"", "pronouns":"", "class_name":"", "ancestry":"", "background":"", "relationships":"", "secrets":"", "goals":""})) for name in names),
            )


def seed_player_accounts():
    """Give each rostered player a LAN-only account with a temporary password."""
    with db() as conn:
        for player in conn.execute("SELECT id,name FROM entries WHERE kind='player'"):
            exists = conn.execute("SELECT 1 FROM player_accounts WHERE player_id=?", (player["id"],)).fetchone()
            if not exists:
                username = "".join(c.lower() for c in player["name"] if c.isalnum())
                set_password(conn, player["id"], username, "drakkenheim", 1)


def seed_faction_profiles():
    """Seed the five major factions and their leaders without overwriting edits."""
    factions = (
        ("The Amethyst Academy", "Arcane research institute and mage guild led in Drakkenheim by Eldrick Runeweaver.", """LEADER\nArchwizard Eldrick Runeweaver\n\nIDENTITY\nA wealthy, secretive magical institution studying delerium and safeguarding arcane knowledge. Its agents are few but exceptionally capable. Colours: purple and gold. Symbol: a lidless arcane eye within an octagram.\n\nPRIMARY OBJECTIVES\n• Collect and study delerium while controlling access to it.\n• Reclaim the Inscrutable Tower.\n• Recover the Inscrutable Staff and determine Archmage Adriana Modiera’s fate.\n• Prevent any new ruler from destroying or tightly restricting delerium.\n\nCAMPAIGN POSITION\nThe Academy considers rebuilding Drakkenheim impractical. It ultimately wants the ruins preserved as an exclusive source of research material. Professional and pragmatic, it hires adventurers for dangerous fieldwork while keeping its own members out of unnecessary danger.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3: Factions.""", "arcane, delerium, eldritch, purple and gold"),
        ("Followers of the Falling Fire", "Apocalyptic pilgrims led by Lucretia Mathias who regard Drakkenheim as a sacred site.", """LEADER\nLucretia Mathias\n\nIDENTITY\nA rapidly growing religious movement excommunicated by the established clergy of the Sacred Flame. Its pilgrims believe the meteor and delerium are part of a divine prophecy.\n\nPRIMARY OBJECTIVES\n• Transform Drakkenheim into a holy pilgrimage site.\n• Preserve delerium for the Sacrament of the Falling Fire.\n• Spread and defend their faith despite opposition from the Silver Order.\n• Recover Saint Vitruvio’s relics and reconsecrate the cathedral.\n\nCAMPAIGN POSITION\nPilgrims undertake a dangerous journey to the crater and embed delerium in their hearts during a transformative sacrament. The faithful see sacrifice as the path to salvation from a coming cosmic doom. Their conviction is sincere, but their rites and prophecies alarm nearly every rival faction.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3: Factions.""", "religion, prophecy, pilgrims, falling fire"),
        ("Hooded Lanterns", "Drakkenheim’s surviving military force, commanded by Lord Commander Elias Drexel.", """LEADER\nLord Commander Elias Drexel\n\nIDENTITY\nA disciplined regiment of soldiers, scouts, and veterans devoted to restoring their ruined homeland. Colours: dark green and iron.\n\nPRIMARY OBJECTIVES\n• Reclaim and rebuild Drakkenheim street by street.\n• Establish defensible strongholds throughout the city.\n• Recover the six Seals of Drakkenheim.\n• Find or establish a legitimate heir to the throne of Westemär.\n\nCAMPAIGN POSITION\nThe Lanterns know the city better than any other organized force and wage a sustained guerrilla campaign against monsters and outlaws. Their patriotism and practical experience make them natural allies, but their strict military priorities, suspicion of scavengers, and royalist ambitions create friction.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3: Factions.""", "military, royalists, city watch, greencloaks"),
        ("Knights of the Silver Order", "A crusading order of the Sacred Flame led locally by Knight-Captain Theodore Marshal.", """LEADER\nKnight-Captain Theodore Marshal\n\nIDENTITY\nA militant holy order sent from Elyria by the Faith of the Sacred Flame. Its knights, paladins, clerics, and retainers have come to confront the corruption in Drakkenheim. Colours: silver and gold. Symbol: a burning chalice upon a shield.\n\nPRIMARY OBJECTIVES\n• Destroy all delerium and prevent its spread.\n• Purge monsters, contamination, and dangerous magic from the ruins.\n• Reclaim Saint Vitruvio’s relics and reconsecrate the cathedral.\n• Oppose the heretical Followers of the Falling Fire.\n\nCAMPAIGN POSITION\nThe Order views delerium as an existential evil that cannot be safely controlled. Its members are courageous and capable allies against monsters, but their uncompromising mission brings them into direct conflict with factions wishing to exploit or preserve the crystals.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3: Factions.""", "sacred flame, paladins, crusaders, silver and gold"),
        ("The Queen’s Men", "A criminal confederation controlled by the enigmatic Queen of Thieves.", """LEADER\nThe Queen of Thieves\n\nIDENTITY\nA loose alliance of roughly one hundred gangs, brigands, smugglers, spies, and outlaws unified through fear, profit, and the Queen’s web of secrets.\n\nPRIMARY OBJECTIVES\n• Dominate Drakkenheim’s underworld and criminal economy.\n• Profit from treasure, smuggling, extortion, and the delerium trade.\n• Sabotage rivals without destroying the unstable balance that enriches the gangs.\n• Secretly obtain the Crown of Westemär and all six Seals needed to wield it.\n\nCAMPAIGN POSITION\nThe Queen’s Men thrive while the ruins remain lawless. They can provide intelligence, illicit goods, secret routes, and deniable assistance, but every bargain creates leverage for their ruler. Loyalty lasts only as long as it remains useful.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3: Factions.""", "criminals, spies, smugglers, outlaws"),
    )
    leaders = (
        ("Archwizard Eldrick Runeweaver", "Faction leader — The Amethyst Academy", """ROLE\nActing Archmage of Drakkenheim and director of Academy operations in the city. River serves as his lieutenant.\n\nAPPEARANCE\nA towering, broad-shouldered human man in his mid-sixties with softly glowing amber eyes, circular glasses, and a square-cut greying black beard. He wears purple and gold, nine Academy rings, and carries an obsidian staff tipped with delerium.\n\nPERSONALITY\nCalculating, economical with words, and inclined to teach through pointed questions. He values facts, restraint, competence, and careful preparation. His concern for former students can blind him to their mistakes.\n\nOBJECTIVES\nRetake the Inscrutable Tower, secure the Inscrutable Staff, expand controlled delerium research, and earn permanent appointment to the Academy Directorate.\n\nRELATIONSHIP NOTES\nTreats capable adventurers as valuable—but expendable—field agents. Reveals the full truth of his provisional position only to trusted collaborators. Often communicates magically or through a simulacrum.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3, pp. 24–29.""", "Amethyst Academy, leader, archwizard, abjuration"),
        ("Lucretia Mathias", "Faction leader — Followers of the Falling Fire", """ROLE\nProphet and spiritual leader of the Followers of the Falling Fire. Nathaniel Flint serves as her principal lieutenant.\n\nAPPEARANCE\nA willowy, wizened human woman in her early nineties with piercing eyes, pursed lips, and greying black hair coiled beneath a linen shawl. She wears simple grey robes, carries a heavy scripture, and conceals a delerium shard embedded in her heart.\n\nPERSONALITY\nSpeaks through proverbs, scripture, and cryptic guidance. Compassionate toward potential converts and certain that sacrifice can redeem the world. She withholds her most consequential visions until she believes others can understand them correctly.\n\nOBJECTIVES\nComplete the prophesied pilgrimage, preserve Drakkenheim as a holy site, spread the new faith, and recover the relics of Saint Vitruvio.\n\nRELATIONSHIP NOTES\nOffers hope and purpose rather than conventional payment. Her serene certainty can be reassuring or deeply unsettling. She believes even bitter enemies may be redeemed.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3, pp. 30–35.""", "Falling Fire, leader, prophet, sacred flame"),
        ("Lord Commander Elias Drexel", "Faction leader — Hooded Lanterns", """ROLE\nCommander of the Hooded Lanterns’ Expeditionary Force. Captain Ansom Lang and Lieutenant Petra Lang alternate as his faction lieutenants.\n\nAPPEARANCE\nA stocky, imposing human man in his early fifties with a furrowed brow, grim angular face, thick moustache, sideburns, and long braided brown hair. He wears chainmail beneath a dark green fur-lined cloak and bears the Lord Commander’s Badge.\n\nPERSONALITY\nBlunt, humourless, direct, and demanding. He prizes loyalty and trust above all else and reacts harshly to failure or betrayal.\n\nOBJECTIVES\nRestore Drakkenheim, secure strategic strongholds and the Seals, and place a legitimate sovereign on the throne.\n\nSECRETS & PRESSURES\nDuring the civil war he joined the conspiracy against Mannfred von Kessel. Guilt over his part in breaking the royal line drives his campaign as an act of penance.\n\nRELATIONSHIP NOTES\nRespects discipline, results, patriotism, and proven loyalty. He is slow to trust but staunch once convinced.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3, pp. 36–41.""", "Hooded Lanterns, leader, commander, military"),
        ("Knight-Captain Theodore Marshal", "Faction leader — Knights of the Silver Order", """ROLE\nCommander of the Silver Order’s Drakkenheim crusade. High Flamekeeper Ophelia Reed is his closest counsellor and faction lieutenant.\n\nAPPEARANCE\nA tall, athletic human man in his prime with bronzed skin, sandy-brown hair, a scarred face, stubbled beard, and a leather patch over his right eye. He wears silver plate with golden trim and carries a holy sword and broad shield marked with the Sacred Flame.\n\nPERSONALITY\nA decisive and charismatic warrior-priest shaped by battle. He approaches corruption as a threat that must be confronted directly, while carrying the authority and moral certainty expected of a celebrated paladin.\n\nOBJECTIVES\nDestroy delerium, purge contamination and monsters, reclaim Saint Vitruvio’s holy relics, and prevent the Falling Fire from establishing its heresy.\n\nRELATIONSHIP NOTES\nHonours courage and direct action. Cooperation is possible when others accept the danger of delerium, but compromise becomes difficult when sacred duty is at stake.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3, pp. 42–46.""", "Silver Order, leader, paladin, sacred flame"),
        ("Queen of Thieves", "Faction leader — The Queen’s Men", """ROLE\nHidden ruler of Drakkenheim’s criminal underworld. Blackjack Mel serves as her faction lieutenant and intermediary.\n\nAPPEARANCE\nNo single appearance is reliable. Her signature persona is a lithe masked swashbuckler with a broad hat and jewelled rapier, but she changes face, body, age, and gender through disguise and magic. She proves her identity by revealing secrets only the Queen should know.\n\nPERSONALITY\nRakishly confident, relentlessly prepared, and fond of exposing what she knows. She prefers manipulation, blackmail, and profitable bargains to wasteful bloodshed. She trusts no one, expects betrayal, and prepares countermeasures in advance.\n\nOBJECTIVES\nControl the ruins through information and crime, undermine rival factions, collect the Seals, and steal the Crown of Westemär.\n\nDM SECRET\nThe book suggests Katarina von Kessel as her original-campaign identity, but explicitly invites the GM to choose a different answer. Preserve the uncertainty until a reveal suits this campaign.\n\nRELATIONSHIP NOTES\nEvery favour is leverage. She may become patron, rival, informant, or enemy—often several at once.\n\nSOURCE\nDungeons of Drakkenheim, Chapter 3, pp. 47–53.""", "Queen's Men, leader, criminal, secret identity"),
    )
    with db() as conn:
        for kind, rows in (("faction", factions), ("npc", leaders)):
            for name, summary, body, tags in rows:
                exists = conn.execute("SELECT 1 FROM entries WHERE kind=? AND lower(name)=lower(?)", (kind, name)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO entries(kind,name,summary,body,tags,status,extra) VALUES(?,?,?,?,?,'Active','{}')",
                        (kind, name, summary, body, tags),
                    )


def seed_first_session():
    """Add the campaign's first scheduled date once."""
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM entries WHERE kind='session' AND json_extract(extra, '$.date')=?", ("2026-09-23",)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO entries(kind,name,summary,status,extra) VALUES('session',?,?,?,?)",
                ("Session 0", "Character creation and campaign setup", "Scheduled", json.dumps({"date":"2026-09-23", "start_time":"", "location":"", "agenda":"Complete characters and establish party connections."})),
            )


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # The app normally runs unattended from a desktop launcher. Writing
        # every request to its background output can eventually fill the pipe
        # and stall otherwise healthy browser connections.
        return

    def json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(raw))
        self.end_headers(); self.wfile.write(raw)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def player_session(self):
        cookies = self.headers.get("Cookie", "")
        token = next((x.split("=", 1)[1] for x in cookies.split("; ") if x.startswith("drak_session=")), "")
        return SESSIONS.get(token)

    def dm_session(self):
        cookies = self.headers.get("Cookie", "")
        token = next((x.split("=", 1)[1] for x in cookies.split("; ") if x.startswith("drak_dm=")), "")
        return token if token in DM_SESSIONS else None

    def require_local(self):
        # Localhost is trusted only for the desktop-only deployment. A hosted
        # reverse proxy may itself connect from a local address, so hosted
        # requests must always present an authenticated DM session.
        if (not PUBLIC_URL and self.is_local()) or self.dm_session(): return True
        self.json({"error":"DM login required"}, 401)
        return False

    def portal_data(self, player_id):
        with db() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
            account = conn.execute("SELECT username,must_change FROM player_accounts WHERE player_id=?", (player_id,)).fetchone()
            sessions = [row_dict(x) for x in conn.execute("SELECT * FROM entries WHERE kind='session' ORDER BY json_extract(extra,'$.date')")]
            letters = [row_dict(x) for x in conn.execute("""SELECT * FROM entries
                WHERE kind='message' AND json_extract(extra,'$.direction')='dm_to_player'
                AND CAST(json_extract(extra,'$.player_id') AS INTEGER)=?
                ORDER BY created_at DESC""", (player_id,))]
        if not row: return None
        player = row_dict(row); extra = player.get("extra", {})
        if extra.get("archived"): return None
        allowed = ("character_name", "pronouns", "class_name", "ancestry", "background", "relationships", "goals")
        player["extra"] = {key: extra.get(key, "") for key in allowed}
        player.pop("body", None); player.pop("tags", None)
        safe_letters = [{"id":x["id"], "name":x["name"], "body":x["body"], "created_at":x["created_at"]} for x in letters]
        return {"player":player, "sessions":sessions, "letters":safe_letters, "username":account["username"], "must_change":bool(account["must_change"])}

    def do_GET(self):
        parsed = urlparse(self.path)
        host = self.headers.get("Host", "").lower()
        direct_local_host = host == "localhost" or host.startswith("localhost:") or host == "127.0.0.1" or host.startswith("127.0.0.1:")
        if PUBLIC_URL and direct_local_host and parsed.path in ("/dm", "/dm/", "/dashboard", "/dashboard/"):
            destination = "/dm" if parsed.path.startswith("/dm") else "/dashboard"
            self.send_response(302)
            self.send_header("Location", f"{PUBLIC_URL}{destination}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); return
        if parsed.path == "/api/dm/me":
            if (not PUBLIC_URL and self.is_local()) or self.dm_session(): self.json({"authenticated":True}); return
            self.json({"authenticated":False}, 401); return
        if parsed.path == "/api/auth/me":
            player_id = self.player_session()
            if not player_id: self.json({"authenticated":False}, 401); return
            data = self.portal_data(player_id)
            if not data: self.json({"authenticated":False,"error":"This player is archived"}, 403); return
            self.json({"authenticated":True, **data}); return
        if parsed.path == "/api/portal":
            player_id = self.player_session()
            if not player_id: self.json({"error":"Please log in"}, 401); return
            data = self.portal_data(player_id)
            if not data: self.json({"error":"This player is archived"}, 403); return
            self.json(data); return
        if parsed.path == "/api/entries":
            if not self.require_local(): return
            q = parse_qs(parsed.query); kind = q.get("kind", [""])[0]; term = q.get("q", [""])[0]
            sql, args = "SELECT * FROM entries WHERE 1=1", []
            if kind: sql += " AND kind=?"; args.append(kind)
            if term:
                sql += " AND (name LIKE ? OR summary LIKE ? OR body LIKE ? OR tags LIKE ?)"
                args += [f"%{term}%"] * 4
            sql += " ORDER BY favorite DESC, updated_at DESC"
            with db() as c: self.json([row_dict(x) for x in c.execute(sql, args)]); return
        if parsed.path == "/api/stats":
            if not self.require_local(): return
            with db() as c:
                counts = {x["kind"]: x["n"] for x in c.execute("SELECT kind, count(*) n FROM entries GROUP BY kind")}
                recent = [row_dict(x) for x in c.execute("SELECT * FROM entries ORDER BY updated_at DESC LIMIT 6")]
            self.json({"counts": counts, "recent": recent}); return
        if parsed.path == "/api/network":
            if not self.require_local(): return
            if PUBLIC_URL:
                self.json({"ip":"Hosted", "portal_url":f"{PUBLIC_URL}/portal"}); return
            ip = local_network_ip()
            self.json({"ip":ip, "portal_url":f"http://{ip}:8080/portal"}); return
        if parsed.path == "/api/inbox-count":
            if not self.require_local(): return
            with db() as conn:
                count = conn.execute("""SELECT count(*) FROM entries WHERE kind='message' AND status='Unread'
                    AND (json_extract(extra,'$.direction')='player_to_dm' OR json_extract(extra,'$.direction') IS NULL)""").fetchone()[0]
            self.json({"unread":count}); return
        if parsed.path.startswith("/resources/"):
            if not self.require_local(): return
            target = (ROOT / unquote(parsed.path.lstrip("/"))).resolve()
            if ROOT / "resources" not in target.parents or not target.is_file(): self.send_error(404); return
            raw = target.read_bytes(); self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw); return
        if parsed.path in ("/portal", "/portal/"): parsed = parsed._replace(path="/portal.html")
        if parsed.path in ("/dashboard", "/dashboard/"): parsed = parsed._replace(path="/index.html")
        if parsed.path in ("/dm", "/dm/"): parsed = parsed._replace(path="/dm-login.html")
        if parsed.path == "/" and (PUBLIC_URL or not self.is_local()): parsed = parsed._replace(path="/portal.html")
        target = STATIC / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        if not target.is_file(): self.send_error(404); return
        raw = target.read_bytes(); self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        if self.path == "/api/dm/login":
            d = self.body(); username = str(d.get("username", "")).strip().lower(); password = str(d.get("password", ""))
            if not DM_PASSWORD: self.json({"error":"DM_PASSWORD is not configured on the server"}, 503); return
            if not hmac.compare_digest(username, DM_USERNAME) or not hmac.compare_digest(password, DM_PASSWORD):
                self.json({"error":"Incorrect DM username or password"}, 401); return
            token = secrets.token_urlsafe(32); DM_SESSIONS.add(token)
            raw = json.dumps({"ok":True}).encode(); self.send_response(200)
            self.send_header("Content-Type", "application/json")
            secure = "; Secure" if PUBLIC_URL else ""
            self.send_header("Set-Cookie", f"drak_dm={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400{secure}")
            self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw); return
        if self.path == "/api/dm/logout":
            token = self.dm_session()
            if token: DM_SESSIONS.discard(token)
            self.send_response(204); self.send_header("Set-Cookie", "drak_dm=; Path=/; Max-Age=0"); self.end_headers(); return
        if self.path == "/api/auth/login":
            d = self.body(); username = str(d.get("username", "")).strip().lower(); password = str(d.get("password", ""))
            with db() as conn:
                account = conn.execute("SELECT * FROM player_accounts WHERE username=?", (username,)).fetchone()
            if not account or not hmac.compare_digest(account["password_hash"], password_hash(password, account["salt"])):
                self.json({"error":"Incorrect username or password"}, 401); return
            if not self.portal_data(account["player_id"]): self.json({"error":"This player account is archived"}, 403); return
            token = secrets.token_urlsafe(32); SESSIONS[token] = account["player_id"]
            raw = json.dumps({"ok":True,"must_change":bool(account["must_change"])}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            secure = "; Secure" if PUBLIC_URL else ""
            self.send_header("Set-Cookie", f"drak_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800{secure}")
            self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw); return
        if self.path == "/api/auth/logout":
            cookies = self.headers.get("Cookie", "")
            token = next((x.split("=",1)[1] for x in cookies.split("; ") if x.startswith("drak_session=")), "")
            SESSIONS.pop(token, None); self.send_response(204)
            self.send_header("Set-Cookie", "drak_session=; Path=/; Max-Age=0"); self.end_headers(); return
        if self.path == "/api/auth/password":
            player_id = self.player_session()
            if not player_id: self.json({"error":"Please log in"}, 401); return
            d = self.body(); password = str(d.get("password", ""))
            if len(password) < 8: self.json({"error":"Password must be at least 8 characters"}, 400); return
            with db() as conn:
                account = conn.execute("SELECT username FROM player_accounts WHERE player_id=?", (player_id,)).fetchone()
                set_password(conn, player_id, account["username"], password, 0)
            self.json({"ok":True}); return
        if self.path == "/api/portal/messages":
            player_id = self.player_session()
            if not player_id: self.json({"error":"Please log in"}, 401); return
            if not self.portal_data(player_id): self.json({"error":"This player is archived"}, 403); return
            d = self.body()
            message_type = str(d.get("message_type", "")).strip().lower()
            subject = str(d.get("subject", "")).strip()
            message = str(d.get("message", "")).strip()
            if message_type not in ("quest", "letter"):
                self.json({"error":"Choose a personal quest update or a letter"}, 400); return
            if not message:
                self.json({"error":"Write a message before sending"}, 400); return
            if len(subject) > 120 or len(message) > 5000:
                self.json({"error":"Subject or message is too long"}, 400); return
            with db() as conn:
                player = conn.execute("SELECT name FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
                if not player: self.json({"error":"Player not found"}, 404); return
                label = "Personal Quest Update" if message_type == "quest" else "Letter"
                title = subject or label
                extra = json.dumps({"player_id":player_id, "player_name":player["name"], "message_type":message_type, "direction":"player_to_dm"})
                cur = conn.execute("""INSERT INTO entries(kind,name,summary,body,tags,status,extra)
                    VALUES('message',?,?,?,?,?,?)""",
                    (f"{label} — {player['name']}: {title}", f"Private dispatch from {player['name']}", message,
                     "private, player dispatch", "Unread", extra))
            self.json({"ok":True,"id":cur.lastrowid}, 201); return
        if self.path.startswith("/api/player-letter/"):
            if not self.require_local(): return
            try: player_id = int(self.path.rsplit("/", 1)[1])
            except ValueError: self.send_error(404); return
            d = self.body(); subject = str(d.get("subject", "")).strip(); message = str(d.get("message", "")).strip()
            if not message: self.json({"error":"Write a letter before sending"}, 400); return
            if len(subject) > 120 or len(message) > 5000:
                self.json({"error":"Subject or letter is too long"}, 400); return
            with db() as conn:
                player = conn.execute("SELECT name,extra FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
                if not player: self.json({"error":"Player not found"}, 404); return
                try: player_extra = json.loads(player["extra"] or "{}")
                except json.JSONDecodeError: player_extra = {}
                if player_extra.get("archived"): self.json({"error":"Archived players cannot receive letters"}, 409); return
                title = subject or "A Letter from the DM"
                extra = json.dumps({"player_id":player_id, "player_name":player["name"], "message_type":"letter", "direction":"dm_to_player"})
                cur = conn.execute("""INSERT INTO entries(kind,name,summary,body,tags,status,extra)
                    VALUES('message',?,?,?,?,?,?)""",
                    (f"Letter to {player['name']}: {title}", f"Private letter sent to {player['name']}", message,
                     "private, DM letter", "Sent", extra))
            self.json({"ok":True,"id":cur.lastrowid}, 201); return
        if self.path.startswith("/api/messages/") and self.path.endswith("/read"):
            if not self.require_local(): return
            try: message_id = int(self.path.split("/")[3])
            except (ValueError, IndexError): self.send_error(404); return
            with db() as conn:
                row = conn.execute("SELECT extra FROM entries WHERE id=? AND kind='message'", (message_id,)).fetchone()
                if not row: self.json({"error":"Message not found"}, 404); return
                try: extra = json.loads(row["extra"] or "{}")
                except json.JSONDecodeError: extra = {}
                if extra.get("direction") == "dm_to_player": self.json({"error":"Outgoing letters are already sent"}, 409); return
                conn.execute("UPDATE entries SET status='Read',updated_at=CURRENT_TIMESTAMP WHERE id=?", (message_id,))
            self.json({"ok":True}); return
        if self.path.startswith("/api/player-account/"):
            if not self.require_local(): return
            try: player_id = int(self.path.rsplit("/",1)[1])
            except ValueError: self.send_error(404); return
            d = self.body(); username = str(d.get("username", "")).strip().lower(); password = str(d.get("password", ""))
            if not username or len(password) < 8: self.json({"error":"Username and an 8+ character password are required"}, 400); return
            try:
                with db() as conn: set_password(conn, player_id, username, password, 1)
            except sqlite3.IntegrityError: self.json({"error":"That username is already in use"}, 409); return
            self.json({"ok":True}); return
        if not self.require_local(): return
        if self.path != "/api/entries": self.send_error(404); return
        d = self.body()
        if d.get("kind") not in KINDS or not str(d.get("name", "")).strip(): self.json({"error":"Name and valid type required"}, 400); return
        with db() as c:
            cur = c.execute("INSERT INTO entries(kind,name,summary,body,tags,status,favorite,extra) VALUES(?,?,?,?,?,?,?,?)",
                (d["kind"], d["name"].strip(), d.get("summary",""), d.get("body",""), d.get("tags",""), d.get("status",""), int(bool(d.get("favorite"))), json.dumps(d.get("extra",{}))))
            if d["kind"] == "player":
                base = "".join(ch.lower() for ch in d["name"] if ch.isalnum()) or f"player{cur.lastrowid}"
                username, suffix = base, 2
                while c.execute("SELECT 1 FROM player_accounts WHERE username=?", (username,)).fetchone():
                    username, suffix = f"{base}{suffix}", suffix + 1
                set_password(c, cur.lastrowid, username, "drakkenheim", 1)
            row = c.execute("SELECT * FROM entries WHERE id=?", (cur.lastrowid,)).fetchone()
        self.json(row_dict(row), 201)

    def do_PUT(self):
        if self.path == "/api/portal/profile":
            player_id = self.player_session()
            if not player_id: self.json({"error":"Please log in"}, 401); return
            d = self.body(); allowed = ("character_name", "pronouns", "class_name", "ancestry", "background", "relationships", "goals")
            with db() as conn:
                row = conn.execute("SELECT extra FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
                if not row: self.json({"error":"Player not found"}, 404); return
                try: extra = json.loads(row["extra"] or "{}")
                except json.JSONDecodeError: extra = {}
                for key in allowed: extra[key] = str(d.get(key, ""))
                conn.execute("UPDATE entries SET extra=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(extra), player_id))
            self.json({"ok":True}); return
        if not self.require_local(): return
        try: eid = int(self.path.removeprefix("/api/entries/"))
        except ValueError: self.send_error(404); return
        d = self.body()
        if d.get("kind") not in KINDS or not str(d.get("name", "")).strip(): self.json({"error":"Name and valid type required"}, 400); return
        with db() as c:
            c.execute("UPDATE entries SET kind=?,name=?,summary=?,body=?,tags=?,status=?,favorite=?,extra=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (d["kind"],d["name"].strip(),d.get("summary",""),d.get("body",""),d.get("tags",""),d.get("status",""),int(bool(d.get("favorite"))),json.dumps(d.get("extra",{})),eid))
            row = c.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
        self.json(row_dict(row) if row else {"error":"Not found"}, 200 if row else 404)

    def do_DELETE(self):
        if not self.require_local(): return
        try: eid = int(self.path.removeprefix("/api/entries/"))
        except ValueError: self.send_error(404); return
        with db() as c:
            c.execute("DELETE FROM player_accounts WHERE player_id=?", (eid,))
            c.execute("DELETE FROM entries WHERE id=?", (eid,))
        self.json({"ok": True})


if __name__ == "__main__":
    db().close()
    seed_players()
    seed_player_accounts()
    seed_faction_profiles()
    seed_first_session()
    url = f"http://127.0.0.1:{PORT}"
    print(f"Drakkenheim dashboard running at {url} (Ctrl+C to stop)")
    try:
        lan_ip = local_network_ip()
        print(f"Player portal available on this network at http://{lan_ip}:8080/portal")
    except OSError: pass
    if not PUBLIC_URL:
        try: webbrowser.open(url)
        except Exception: pass
    if PORT == 8765:
        player_server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
        threading.Thread(target=player_server.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
