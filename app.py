#!/usr/bin/env python3
"""Drakkenheim campaign dashboard: zero-dependency local web app."""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote
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
KINDS = {"player", "npc", "mission", "location", "faction", "quest", "note", "todo", "session", "rumor", "resource", "map", "message", "name"}
SESSIONS = {}
DM_SESSIONS = set()
DISPLAY_SESSIONS = set()
PORT = int(os.environ.get("PORT", "8765"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
DM_USERNAME = os.environ.get("DM_USERNAME", "dm").lower()
DM_PASSWORD = os.environ.get("DM_PASSWORD", "")
DISPLAY_USERNAME = os.environ.get("DISPLAY_USERNAME", "dashboard").lower()
DISPLAY_PASSWORD = os.environ.get("DISPLAY_PASSWORD", DM_PASSWORD)


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
    conn.execute("""CREATE TABLE IF NOT EXISTS display_state (
        id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("INSERT OR IGNORE INTO display_state(id,payload) VALUES(1,'{}')")
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


FACTION_CONTACTS = (
        ("River", "Faction contact — The Amethyst Academy", """ROLE
Lieutenant and field representative for the Amethyst Academy in Drakkenheim. She works alongside Archwizard Eldrick Runeweaver and frequently hires capable adventurers for Academy business.

APPEARANCE
A short tiefling woman in her late twenties with spotted brown skin, sharp features, flowing blue hair, and two dark horns swept backward. She wears a practical purple high-collared jacket, five rings, and several belted pouches.

PERSONALITY
Precise, pragmatic, and professional, with a wry sardonic humour reserved for people she considers competent. She values results and has little patience for excuses or foolishness.

RELATIONSHIPS & RESOURCES
Eldrick Runeweaver is her mentor and close friend. River is usually accompanied by an imp familiar and shield guardian, and maintains ready access to sending magic, teleportation, scrolls, and potions.

SOURCE
Dungeons of Drakkenheim, Chapter 3: Factions.""", "Amethyst Academy, contact, lieutenant, tiefling, mage", "The Amethyst Academy"),
        ("Nathaniel Flint", "Faction contact — Followers of the Falling Fire", """ROLE
Principal lieutenant and enthusiastic missionary for the Followers of the Falling Fire. He guides pilgrims and introduces outsiders to Lucretia Mathias’s teachings.

APPEARANCE
An animated human man in his early thirties with curly brown hair, mutton chops, a bushy moustache, and a flushed face. He wears pilgrim robes and a Falling Fire tabard; a scarfed hood conceals the delerium shard in his chest.

PERSONALITY
Jovial, eager, and utterly convinced of Lucretia’s prophecies. He sees even terrible events as part of a divine plan.

DM POSSIBILITY
At the DM’s option, Nathaniel may be Leonard von Kessel without any memory of his former identity, or have another hidden connection to the royal family.

SOURCE
Dungeons of Drakkenheim, Chapter 3: Factions.""", "Falling Fire, contact, lieutenant, chaplain, pilgrim", "Followers of the Falling Fire"),
        ("Captain Ansom Lang", "Faction contact — Hooded Lanterns", """ROLE
Captain of the Hooded Lanterns’ Vanguard Company and one of Lord Commander Elias Drexel’s principal field officers.

APPEARANCE
An athletic young human man with long black hair, a neat short beard, angular jaw, and rugged features. His green cloak and light chain armour display a captain’s insignia.

PERSONALITY
Determined, suspicious, and slow to trust adventurers. He hopes hard work can restore Drakkenheim, but habitually doubts outsiders.

RELATIONSHIPS
Petra Lang is his adopted sister and closest bond. The two were raised by Elias Drexel and have protected one another since childhood.

SOURCE
Dungeons of Drakkenheim, Chapter 3: Factions.""", "Hooded Lanterns, contact, captain, ranger, vanguard", "Hooded Lanterns"),
        ("Lieutenant Petra Lang", "Faction contact — Hooded Lanterns", """ROLE
Hooded Lanterns lieutenant, urban ranger, and trusted field officer under Lord Commander Elias Drexel.

APPEARANCE
A fit and nimble young human woman with long black hair, a narrow pointed chin, and bold features. She wears the Lanterns’ green cloak and light chain armour with a lieutenant’s insignia.

PERSONALITY
Hopeful, perceptive, and willing to trust people who risk themselves for the city. Her faith in apparent allies can leave her exposed.

RELATIONSHIPS
Ansom Lang is her adopted brother. Elias Drexel raised and trained them both, and Petra is determined to prove worthy of his trust.

SOURCE
Dungeons of Drakkenheim, Chapter 3: Factions.""", "Hooded Lanterns, contact, lieutenant, ranger, scout", "Hooded Lanterns"),
        ("High Flamekeeper Ophelia Reed", "Faction contact — Knights of the Silver Order", """ROLE
High Flamekeeper, chaplain, and closest counsellor to Knight-Captain Theodore Marshal in the Silver Order’s Drakkenheim expedition.

APPEARANCE
A stout Black human woman in her late forties with a warm smile, rounded features, and braided hair. She wears yellow-and-white robes and carries a silvered staff and ever-burning censer.

PERSONALITY
Patient, attentive, and kind. She seeks the proper remedy for every problem, but believes some corruption can be answered only by death.

RELATIONSHIPS & RESOURCES
She has taken a vow of poverty and devoted her life to the Sacred Flame. She offers healing, counsel, historical knowledge, and restorative magic to proven allies.

SOURCE
Dungeons of Drakkenheim, Chapter 3: Factions.""", "Silver Order, contact, high flamekeeper, chaplain, sacred flame", "Knights of the Silver Order"),
        ("Blackjack Mel", "Faction contact — The Queen’s Men", """ROLE
Faction lieutenant, fixer, and public intermediary for the Queen of Thieves. He is usually found at the Skull & Sword Taphouse.

APPEARANCE
A short, scrawny human man in his late thirties with a clean-shaven face and greasy slicked-back hair. His black jacket and buckled slacks look distinguished from afar but are shabby up close.

PERSONALITY
Sleazy, persistent, and always hunting for the angle that closes a deal. He believes everyone acts for themselves and treats favours as currency.

RELATIONSHIPS
Mel can arrange contact with the Queen of Thieves. He is also a compulsive liar who sometimes loses track of his own inventions.

SOURCE
Dungeons of Drakkenheim, Chapter 3: Factions.""", "Queen's Men, contact, lieutenant, fixer, scoundrel", "The Queen’s Men"),
)


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
        for name, summary, body, tags, faction in FACTION_CONTACTS:
            exists = conn.execute("SELECT 1 FROM entries WHERE kind='npc' AND lower(name)=lower(?)", (name,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO entries(kind,name,summary,body,tags,status,extra) VALUES('npc',?,?,?,?,'Active',?)",
                    (name, summary, body, tags, json.dumps({"contact":True, "faction":faction})),
                )
        contact_factions = {
            "Archwizard Eldrick Runeweaver":"The Amethyst Academy", "Lucretia Mathias":"Followers of the Falling Fire",
            "Lord Commander Elias Drexel":"Hooded Lanterns", "Knight-Captain Theodore Marshal":"Knights of the Silver Order",
            "Queen of Thieves":"The Queen’s Men", **{row[0]:row[4] for row in FACTION_CONTACTS},
        }
        for name, faction in contact_factions.items():
            row = conn.execute("SELECT id,extra FROM entries WHERE kind='npc' AND lower(name)=lower(?)", (name,)).fetchone()
            if not row: continue
            try: extra = json.loads(row["extra"] or "{}")
            except json.JSONDecodeError: extra = {}
            extra.update({"contact":True, "faction":faction})
            conn.execute("UPDATE entries SET extra=? WHERE id=?", (json.dumps(extra), row["id"]))


def seed_first_session():
    """Add the campaign's first scheduled date once."""
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM entries WHERE kind='session' AND json_extract(extra, '$.date')=?", ("2026-09-23",)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO entries(kind,name,summary,status,extra) VALUES('session',?,?,?,?)",
                ("Session 0", "Character creation and campaign setup", "Scheduled", json.dumps({"date":"2026-09-23", "start_time":"", "location":"", "agenda":"Complete characters and establish party connections."})),
            )


def seed_sample_missions():
    """Add original ready-to-run faction missions without overwriting edits."""
    missions = (
        {
            "name":"Resonance Beneath the Glassworks", "faction":"The Amethyst Academy", "level":"Levels 3–4",
            "summary":"Recover an experimental resonance lens before its signal draws something worse into the ruined glassworks.",
            "tags":"Amethyst Academy, arcane, delerium, investigation",
            "body":"""MISSION HOOK
River offers controlled access to Academy supplies if the party retrieves a brass-and-crystal resonance lens lost beneath an abandoned glassworks. The device has begun broadcasting a magical pulse through the Haze.

PRIMARY OBJECTIVES
• Reach the glassworks before a rival scavenger crew.
• Shut down or safely recover the resonance lens.
• Determine what has been answering its signal.

SCENE BEATS
1. Shattered Workshop — Unstable glass sheets turn movement into a noisy hazard while rival scavengers search the floor.
2. Harmonic Vault — Three tuning pillars must be aligned; a failed attempt causes an arcane backlash and advances the threat.
3. The Answering Shape — A haze-warped predator arrives through a fractured mirror as the lens reaches full resonance.

COMPLICATION
The lens contains a recorded voice claiming the Academy knew the test could attract extraplanar creatures. Returning it intact earns River’s trust; revealing the recording creates leverage but damages the relationship.

OUTCOMES
Success earns Academy spellcasting assistance and the lens as a future research lead. Destroying the device prevents further incursions but disappoints the Academy. A rival escapee may sell news of the discovery.""",
            "npcs":[
                {"name":"Academy Field Arcanist","type":"Medium humanoid, neutral","ac":"13 (16 with arcane ward)","hp":"27 (5d8 + 5)","speed":"30 ft.","abilities":"STR 9 · DEX 14 · CON 12 · INT 17 · WIS 12 · CHA 11","saves":"Int +5, Wis +3","skills":"Arcana +5, Investigation +5","senses":"passive Perception 11","languages":"Common plus two others","cr":"CR 2 (450 XP)","traits":["Arcane Ward (1/Day). When hit, the arcanist gains +3 AC against that attack, potentially causing it to miss."],"actions":["Arcane Bolt. Ranged Spell Attack: +5 to hit, range 120 ft., one target. Hit: 10 (2d6 + 3) force damage.","Resonant Pulse (Recharge 5–6). Creatures in a 15-foot cone make a DC 13 Con save, taking 14 (4d6) thunder damage on a failure, or half on a success."]},
                {"name":"Mirror-Haze Stalker","type":"Large aberration, unaligned","ac":"14","hp":"68 (8d10 + 24)","speed":"40 ft., climb 30 ft.","abilities":"STR 18 · DEX 15 · CON 16 · INT 5 · WIS 14 · CHA 7","saves":"Dex +4, Wis +4","skills":"Perception +4, Stealth +4","senses":"darkvision 60 ft., passive Perception 14","languages":"—","cr":"CR 4 (1,100 XP)","traits":["Reflected Step. As a bonus action near glass or a mirror, the stalker teleports up to 20 feet to another reflective surface it can see."],"actions":["Multiattack. The stalker makes two Claw attacks.","Claw. Melee Weapon Attack: +6 to hit, reach 5 ft. Hit: 11 (2d6 + 4) slashing damage.","Splintering Gaze (Recharge 6). One creature within 60 feet makes a DC 13 Wis save or takes 18 (4d8) psychic damage and is frightened until the end of its next turn."]}
            ]
        },
        {
            "name":"Lanterns on the Pilgrim Road", "faction":"Followers of the Falling Fire", "level":"Levels 3–4",
            "summary":"Escort a divided band of pilgrims through the Outer City while deciding whose visions can be trusted.",
            "tags":"Falling Fire, escort, pilgrims, Haze",
            "body":"""MISSION HOOK
Nathaniel Flint asks the party to escort twelve pilgrims to a roadside shrine inside the Haze. One pilgrim has recurring visions of a safer path, while another insists the visions are a temptation.

PRIMARY OBJECTIVES
• Keep at least eight pilgrims together and alive.
• Reach the shrine before nightfall.
• Decide whether to follow the mapped route or the visionary’s detour.

SCENE BEATS
1. The Broken Procession — A collapsed street forces the group through unstable row houses or an exposed square.
2. The Divided Faithful — Fear splits the pilgrims. Calm leadership, proof, or compassion prevents desertion.
3. Shrine of Embers — Haze-fed hunters surround the shrine while the pilgrims complete a ten-minute rite.

COMPLICATION
The visionary’s route is genuinely safer, but leads past a delerium growth that induces a shared revelation. Characters who approach it glimpse a possible future at a personal cost chosen by the DM.

OUTCOMES
Saving the procession earns the Followers’ hospitality and Nathaniel’s confidence. Forcing the pilgrims onward without regard for casualties completes the route but creates a resentful survivor.""",
            "npcs":[
                {"name":"Falling Fire Guide","type":"Medium humanoid, lawful neutral","ac":"14","hp":"32 (5d8 + 10)","speed":"30 ft.","abilities":"STR 12 · DEX 12 · CON 14 · INT 10 · WIS 16 · CHA 14","saves":"Wis +5, Cha +4","skills":"Insight +5, Medicine +5, Religion +3","senses":"passive Perception 13","languages":"Common","cr":"CR 2 (450 XP)","traits":["Steadfast Faith. The guide and allies within 10 feet have advantage on saves against being frightened."],"actions":["Quarterstaff. Melee Weapon Attack: +3 to hit. Hit: 5 (1d8 + 1) bludgeoning damage.","Guiding Ember (3/Day). Ranged Spell Attack: +5 to hit, range 60 ft. Hit: 10 (3d6) radiant damage; the next attack against the target has advantage."]},
                {"name":"Haze Prowler","type":"Medium monstrosity, unaligned","ac":"14","hp":"45 (6d8 + 18)","speed":"40 ft.","abilities":"STR 16 · DEX 16 · CON 16 · INT 4 · WIS 13 · CHA 6","saves":"Dex +5","skills":"Perception +3, Stealth +7","senses":"darkvision 60 ft., passive Perception 13","languages":"—","cr":"CR 3 (700 XP)","traits":["Haze Camouflage. The prowler can Hide while lightly obscured by mist, smoke, or the Haze."],"actions":["Multiattack. The prowler makes two Talon attacks.","Talon. Melee Weapon Attack: +5 to hit. Hit: 8 (1d10 + 3) slashing damage.","Dragging Leap. The prowler leaps up to 20 feet and makes a Talon attack. On a hit, the target must succeed on a DC 13 Str save or fall prone."]}
            ]
        },
        {
            "name":"The Silent Watchtower", "faction":"Hooded Lanterns", "level":"Levels 4–5",
            "summary":"Restore a vital signal tower whose garrison vanished after reporting lights beneath the street.",
            "tags":"Hooded Lanterns, military, rescue, watchtower",
            "body":"""MISSION HOOK
Elias Drexel has lost contact with a watchtower guarding a supply route. The final signal reported green lights moving beneath the cobbles. The party must restore the beacon and account for the garrison.

PRIMARY OBJECTIVES
• Secure the watchtower and relight its signal brazier.
• Find the six missing Lanterns.
• Keep the underground threat away from the supply route.

SCENE BEATS
1. Empty Barricades — The defences face inward, and drag marks lead to the cellar.
2. Buried Service Tunnel — The missing soldiers are cocooned along a delerium-veined tunnel; freeing them risks alerting the brood.
3. Hold the Tower — Lighting the beacon draws the brood brute and smaller creatures into a three-round defence.

COMPLICATION
The Lantern sergeant concealed early signs of contamination in two soldiers to avoid abandoning the post. The party must decide how to report and treat them.

OUTCOMES
Restoring the tower opens a safe route and a Lantern supply cache. Honest reporting earns Drexel’s respect but may condemn contaminated survivors; concealment preserves lives while creating future risk.""",
            "npcs":[
                {"name":"Hooded Lantern Sergeant","type":"Medium humanoid, lawful neutral","ac":"17 (chain shirt, shield)","hp":"44 (8d8 + 8)","speed":"30 ft.","abilities":"STR 15 · DEX 14 · CON 13 · INT 11 · WIS 14 · CHA 13","saves":"Str +4, Wis +4","skills":"Athletics +4, Perception +4, Survival +4","senses":"passive Perception 14","languages":"Common","cr":"CR 3 (700 XP)","traits":["Hold the Line. Allies within 10 feet gain +1 AC while the sergeant is conscious."],"actions":["Multiattack. The sergeant makes two Longsword attacks.","Longsword. Melee Weapon Attack: +4 to hit. Hit: 6 (1d8 + 2) slashing damage.","Rally (Recharge 5–6). Up to three allies within 30 feet gain 7 temporary hit points and may move 10 feet without provoking opportunity attacks."]},
                {"name":"Delerium Brood Brute","type":"Large monstrosity, unaligned","ac":"15","hp":"85 (10d10 + 30)","speed":"30 ft., burrow 15 ft.","abilities":"STR 19 · DEX 10 · CON 17 · INT 3 · WIS 12 · CHA 5","saves":"Con +6","skills":"Perception +4","senses":"tremorsense 30 ft., darkvision 60 ft., passive Perception 14","languages":"—","cr":"CR 5 (1,800 XP)","traits":["Crystal Carapace. The first time each round the brute takes spell damage, reduce that damage by 5."],"actions":["Multiattack. The brute makes two Crush attacks.","Crush. Melee Weapon Attack: +7 to hit, reach 10 ft. Hit: 13 (2d8 + 4) bludgeoning damage.","Shard Eruption (Recharge 5–6). Creatures within 15 feet make a DC 14 Dex save, taking 21 (6d6) piercing damage on a failure, or half on a success."]}
            ]
        },
        {
            "name":"The Cinders of Saint Brenna", "faction":"Knights of the Silver Order", "level":"Levels 5–6",
            "summary":"Recover a sacred ember from a ruined chapel before a corrupted guardian snuffs it out forever.",
            "tags":"Silver Order, sacred flame, undead, relic",
            "body":"""MISSION HOOK
Ophelia Reed believes an ember from Saint Brenna’s sanctuary still burns beneath a ruined chapel. The Silver Order needs it to consecrate a field hospital, but the dead around the chapel have begun walking.

PRIMARY OBJECTIVES
• Enter the sealed undercroft without extinguishing its warding flames.
• Recover the saint’s ember in a consecrated vessel.
• Lay the corrupted guardian to rest or redeem it.

SCENE BEATS
1. Ashen Nave — Braziers must be lit in the correct order while ash-wights close in.
2. Confession Door — The undercroft opens only after a character truthfully admits a failure or sacrifice.
3. The Last Keeper — A former Flamekeeper guards the ember, convinced all living visitors are contaminated.

COMPLICATION
The guardian can be redeemed by presenting evidence that the Sacred Flame still serves the people, turning the climax into a tense social encounter under attack by lesser undead.

OUTCOMES
Returning the ember unlocks Silver Order healing services. Redeeming the keeper impresses Ophelia; simply destroying it satisfies Theodore Marshal but leaves unanswered questions in the chapel archive.""",
            "npcs":[
                {"name":"Silver Order Flamekeeper","type":"Medium humanoid, lawful good","ac":"16 (scale mail, shield)","hp":"38 (7d8 + 7)","speed":"30 ft.","abilities":"STR 13 · DEX 10 · CON 12 · INT 12 · WIS 17 · CHA 15","saves":"Wis +6, Cha +5","skills":"Medicine +6, Religion +4","senses":"passive Perception 13","languages":"Common, Celestial","cr":"CR 3 (700 XP)","traits":["Sacred Shelter. Allies within 10 feet have advantage on death saving throws."],"actions":["Mace. Melee Weapon Attack: +3 to hit. Hit: 4 (1d6 + 1) bludgeoning plus 4 (1d8) radiant damage.","Flame of Rebuke (Recharge 5–6). One creature within 60 feet makes a DC 14 Dex save, taking 18 (4d8) radiant damage on a failure, or half on a success.","Healing Prayer (2/Day). A creature within 30 feet regains 12 (2d8 + 3) hit points."]},
                {"name":"Cinderbound Keeper","type":"Medium undead, lawful neutral","ac":"17","hp":"90 (12d8 + 36)","speed":"30 ft.","abilities":"STR 16 · DEX 12 · CON 16 · INT 11 · WIS 15 · CHA 14","saves":"Con +6, Wis +5","skills":"Insight +5, Religion +3","senses":"darkvision 60 ft., passive Perception 12","languages":"Common, Celestial","cr":"CR 5 (1,800 XP)","traits":["Undying Vigil. If reduced to 0 hit points while the sacred ember burns, the keeper drops to 1 hit point instead; this works once.","Turn Resistance. The keeper has advantage on saves against effects that turn undead."],"actions":["Multiattack. The keeper makes two Ashen Blade attacks.","Ashen Blade. Melee Weapon Attack: +6 to hit. Hit: 8 (1d10 + 3) slashing plus 4 (1d8) fire damage.","Cinder Wave (Recharge 5–6). Creatures in a 20-foot cone make a DC 14 Con save, taking 18 (4d8) fire damage and becoming blinded until their next turn on a failure; half damage without blindness on a success."]}
            ]
        },
        {
            "name":"The Ledger at Buckledown Row", "faction":"The Queen’s Men", "level":"Levels 4–5",
            "summary":"Steal a smuggler’s ledger during a gang auction without revealing who hired the party—or what else the book contains.",
            "tags":"Queen's Men, heist, gangs, intrigue",
            "body":"""MISSION HOOK
Blackjack Mel offers the party a simple theft: acquire a coded ledger being auctioned in Buckledown Row. He insists the book belongs to the Queen, but several buyers claim it proves who has been selling contaminated supplies.

PRIMARY OBJECTIVES
• Enter the auction by invitation, disguise, or infiltration.
• Obtain the ledger without uniting the gangs against the party.
• Decide whether to deliver, copy, expose, or destroy its contents.

SCENE BEATS
1. Price of Admission — The doorkeeper demands a secret, valuable collateral, or victory in a nonlethal bout.
2. Crooked Auction — Bids include coin, favours, blackmail, and future crimes. Characters can manipulate rival bidders.
3. Knives in the Dark — When the ledger changes hands, a masked thief cuts the lights and every faction moves at once.

COMPLICATION
The ledger implicates one of Mel’s own allies and contains payments connected to a respectable Emberwood merchant. The masked thief is trying to expose the scheme, not profit from it.

OUTCOMES
Giving Mel the only copy earns access to Queen’s Men information. Keeping a copy creates leverage. Public exposure disrupts contaminated supplies but makes the party enemies among several gangs.""",
            "npcs":[
                {"name":"Queen’s Men Fixer","type":"Medium humanoid, chaotic neutral","ac":"15 (studded leather)","hp":"39 (6d8 + 12)","speed":"30 ft.","abilities":"STR 10 · DEX 17 · CON 14 · INT 14 · WIS 12 · CHA 16","saves":"Dex +5, Cha +5","skills":"Deception +7, Insight +3, Sleight of Hand +5, Stealth +5","senses":"passive Perception 11","languages":"Common, thieves’ cant","cr":"CR 3 (700 XP)","traits":["Cunning Action. The fixer can Dash, Disengage, or Hide as a bonus action.","Underhanded Strike (1/Turn). The fixer deals an extra 7 (2d6) damage when attacking with advantage or while an ally is adjacent to the target."],"actions":["Multiattack. The fixer makes two attacks with Rapier or Hand Crossbow.","Rapier. Melee Weapon Attack: +5 to hit. Hit: 7 (1d8 + 3) piercing damage.","Hand Crossbow. Ranged Weapon Attack: +5 to hit, range 30/120 ft. Hit: 6 (1d6 + 3) piercing damage."]},
                {"name":"Buckledown Gang Enforcer","type":"Medium humanoid, any non-good alignment","ac":"16 (breastplate)","hp":"65 (10d8 + 20)","speed":"30 ft.","abilities":"STR 17 · DEX 13 · CON 15 · INT 9 · WIS 11 · CHA 12","saves":"Str +6, Con +5","skills":"Athletics +6, Intimidation +4","senses":"passive Perception 10","languages":"Common","cr":"CR 4 (1,100 XP)","traits":["Crowd Fighter. The enforcer gains +2 damage for each conscious ally adjacent to its target, to a maximum of +6."],"actions":["Multiattack. The enforcer makes two Heavy Club attacks.","Heavy Club. Melee Weapon Attack: +6 to hit. Hit: 10 (2d6 + 3) bludgeoning damage.","Make an Example (Recharge 5–6). After hitting a creature, each enemy within 15 feet must succeed on a DC 13 Wis save or become frightened of the enforcer until the end of its next turn."]}
            ]
        },
        {
            "name":"The Violet Lantern", "faction":"Amethyst Academy", "level":"Level 2",
            "summary":"Recover a fallen survey lantern from the edge of the ruins before its unstable crystal attracts something worse.",
            "tags":"Amethyst Academy, level 2, recovery, delerium",
            "body":"""MISSION HOOK
River asks the party to retrieve a violet survey lantern lost during a hasty retreat. Its crystal is pulsing beneath a shattered glassworks and drawing scavengers from the surrounding streets.

PRIMARY OBJECTIVES
• Find the lantern before its crystal overloads.
• Record the strange markings discovered around it.
• Return it without exposing anyone to its cracked casing.

SCENE BEATS
1. Broken Trail — Arcane scorch marks and abandoned equipment reveal where the survey team fled.
2. Glasswork Nest — Crystal-backed vermin circle the lantern among dangerously unstable panes.
3. The Final Pulse — The party has three rounds to shut down, shield, or safely remove the crystal.

COMPLICATION
An Academy apprentice who stayed behind insists the markings prove the lantern found a hidden chamber and wants the party to delay their retreat.

OUTCOMES
Returning the lantern earns Academy supplies and River’s trust. Recovering the survey notes reveals a useful route into the ruins; breaking the crystal makes the area safer but disappoints the Academy.""",
            "npcs":[
                {"name":"Academy Apprentice","type":"Medium humanoid, any alignment","ac":"12 (15 with arcane ward)","hp":"16 (3d8 + 3)","speed":"30 ft.","abilities":"STR 9 · DEX 14 · CON 12 · INT 15 · WIS 11 · CHA 10","saves":"Int +4","skills":"Arcana +4, Investigation +4","senses":"passive Perception 10","languages":"Common, Draconic","cr":"CR 1/2 (100 XP)","traits":["Arcane Ward (1/Day). As a reaction when hit, the apprentice gains +3 AC against that attack."],"actions":["Arcane Bolt. Ranged Spell Attack: +4 to hit, range 60 ft. Hit: 7 (2d6) force damage.","Static Snare (Recharge 6). One creature within 30 feet must succeed on a DC 12 Str save or have speed 0 until the end of its next turn."]},
                {"name":"Crystal-Backed Vermin","type":"Small monstrosity, unaligned","ac":"13","hp":"22 (4d6 + 8)","speed":"30 ft., climb 20 ft.","abilities":"STR 12 · DEX 14 · CON 14 · INT 3 · WIS 12 · CHA 5","saves":"—","skills":"Perception +3, Stealth +4","senses":"darkvision 30 ft., passive Perception 13","languages":"—","cr":"CR 1 (200 XP)","traits":["Fractured Carapace. When first reduced below 11 hit points, creatures within 5 feet must make a DC 11 Dex save or take 3 (1d6) piercing damage."],"actions":["Bite. Melee Weapon Attack: +4 to hit. Hit: 7 (1d10 + 2) piercing damage."]}
            ]
        },
        {
            "name":"Embers for the Road", "faction":"The Followers of the Falling Fire", "level":"Level 2",
            "summary":"Recover a pilgrim caravan’s stolen provisions before nightfall leaves the faithful exposed to the Haze.",
            "tags":"Falling Fire, level 2, escort, negotiation",
            "body":"""MISSION HOOK
Lucretia Mathias asks the party to find medicine and lamp oil stolen from a pilgrim camp. Tracks lead toward an abandoned tollhouse just beyond Emberwood Village.

PRIMARY OBJECTIVES
• Recover the medicine and lamp oil.
• Keep the novice guide alive.
• Resolve the theft before the pilgrims must travel after dark.

SCENE BEATS
1. Divided Camp — Frightened witnesses disagree about the number and nature of the thieves.
2. Tollhouse Parley — Hungry refugees took the supplies and barricaded themselves against prowling beasts.
3. Last Light — Haze-starved jackals attack while the party chooses how to divide the provisions.

COMPLICATION
The refugees include a sick child who needs the same medicine as an elderly pilgrim. Neither group has enough without the party finding an alternative.

OUTCOMES
A peaceful solution builds goodwill with the Falling Fire and the refugees. Recovering every crate completes the task, while finding the hidden herbal cache saves both patients and earns a future guide.""",
            "npcs":[
                {"name":"Pilgrim Warden","type":"Medium humanoid, lawful neutral","ac":"14 (leather, shield)","hp":"18 (4d8)","speed":"30 ft.","abilities":"STR 12 · DEX 12 · CON 11 · INT 10 · WIS 15 · CHA 13","saves":"Wis +4","skills":"Medicine +4, Survival +4","senses":"passive Perception 12","languages":"Common","cr":"CR 1/2 (100 XP)","traits":["Guiding Word (2/Day). A creature within 30 feet adds 1d4 to one saving throw it just made."],"actions":["Spear. Melee or Ranged Weapon Attack: +3 to hit, reach 5 ft. or range 20/60 ft. Hit: 4 (1d6 + 1) piercing damage."]},
                {"name":"Haze-Starved Jackal","type":"Medium monstrosity, unaligned","ac":"13","hp":"26 (4d8 + 8)","speed":"40 ft.","abilities":"STR 14 · DEX 15 · CON 14 · INT 3 · WIS 13 · CHA 6","saves":"—","skills":"Perception +3, Stealth +4","senses":"darkvision 60 ft., passive Perception 13","languages":"—","cr":"CR 1 (200 XP)","traits":["Pack Tactics. The jackal has advantage on an attack roll if an ally is within 5 feet of the target."],"actions":["Bite. Melee Weapon Attack: +4 to hit. Hit: 7 (1d10 + 2) piercing damage; the target must succeed on a DC 11 Str save or fall prone."]}
            ]
        },
        {
            "name":"The Missing Greencloak", "faction":"The Hooded Lanterns", "level":"Level 2",
            "summary":"Find a missing Lantern scout whose last signal came from a collapsed tenement near the city wall.",
            "tags":"Hooded Lanterns, level 2, rescue, ruins",
            "body":"""MISSION HOOK
Ansom Lang sends the party after a young scout who missed two check-ins. Her green signal ribbon hangs from a tenement window, but looters are already searching the building.

PRIMARY OBJECTIVES
• Locate and stabilize the missing scout.
• Recover her map of nearby contamination pockets.
• Leave before the damaged building collapses.

SCENE BEATS
1. False Signal — A tripwire at the entrance warns the looters upstairs.
2. Tilting Floors — Crossing the tenement requires careful movement or shoring up its broken supports.
3. Shared Escape — The scout is pinned near a delerium seep while the looters’ retreat destabilizes the structure.

COMPLICATION
The scout learned the looters are displaced residents searching for a family strongbox, not hardened criminals.

OUTCOMES
Saving the scout earns a reliable map and Lantern favour. Helping recover the strongbox creates local allies; arresting the looters pleases stricter officers but breeds resentment.""",
            "npcs":[
                {"name":"Lantern Scout","type":"Medium humanoid, lawful neutral","ac":"14 (studded leather)","hp":"18 (4d8)","speed":"30 ft.","abilities":"STR 11 · DEX 15 · CON 11 · INT 12 · WIS 14 · CHA 10","saves":"Dex +4","skills":"Perception +4, Stealth +4, Survival +4","senses":"passive Perception 14","languages":"Common","cr":"CR 1/2 (100 XP)","traits":["Ruin Runner. Difficult terrain caused by rubble does not cost the scout extra movement."],"actions":["Shortsword. Melee Weapon Attack: +4 to hit. Hit: 5 (1d6 + 2) piercing damage.","Shortbow. Ranged Weapon Attack: +4 to hit, range 80/320 ft. Hit: 5 (1d6 + 2) piercing damage."]},
                {"name":"Ruin Looter Captain","type":"Medium humanoid, any alignment","ac":"14 (leather)","hp":"27 (5d8 + 5)","speed":"30 ft.","abilities":"STR 13 · DEX 15 · CON 12 · INT 11 · WIS 12 · CHA 13","saves":"—","skills":"Athletics +3, Deception +3, Perception +3","senses":"passive Perception 13","languages":"Common","cr":"CR 1 (200 XP)","traits":["Scramble Away. The captain can Disengage as a bonus action while within 5 feet of rubble or cover."],"actions":["Multiattack. The captain makes two Knife attacks.","Knife. Melee or Ranged Weapon Attack: +4 to hit, reach 5 ft. or range 20/60 ft. Hit: 4 (1d4 + 2) piercing damage."]}
            ]
        },
        {
            "name":"The Bell of Ash and Rain", "faction":"Knights of the Silver Order", "level":"Level 2",
            "summary":"Cleanse a roadside shrine and recover its silver bell before restless dead overrun a nearby refugee camp.",
            "tags":"Silver Order, level 2, undead, shrine",
            "body":"""MISSION HOOK
Ophelia Reed needs the bell from a desecrated roadside shrine to ward a refugee camp. Each sunset, the bell rings by itself and another ash-covered corpse rises nearby.

PRIMARY OBJECTIVES
• Reach the shrine before sunset.
• Discover what binds the dead to its bell.
• Return the bell after cleansing or reconsecrating it.

SCENE BEATS
1. Roadside Graves — Disturbed markers reveal that one burial was deliberately omitted.
2. The Locked Belfry — A simple hymn, force, or climbing route opens the bell tower.
3. Ash at Sunset — Restless penitents emerge while a trapped spirit begs the party not to take the bell.

COMPLICATION
The spirit is the shrine’s former keeper, falsely condemned and denied a marked grave. Laying the keeper to rest weakens the undead without a fight.

OUTCOMES
The cleansed bell protects the camp and earns Silver Order aid. Returning it without resolving the haunting works briefly, but the spirit follows it back.""",
            "npcs":[
                {"name":"Silver Order Acolyte","type":"Medium humanoid, lawful good","ac":"15 (chain shirt, shield)","hp":"19 (3d8 + 6)","speed":"30 ft.","abilities":"STR 13 · DEX 10 · CON 14 · INT 10 · WIS 15 · CHA 12","saves":"Wis +4","skills":"Medicine +4, Religion +2","senses":"passive Perception 12","languages":"Common, Celestial","cr":"CR 1/2 (100 XP)","traits":["Steady Flame (1/Day). An ally within 30 feet may reroll a failed save against being frightened."],"actions":["Mace. Melee Weapon Attack: +3 to hit. Hit: 4 (1d6 + 1) bludgeoning damage.","Sacred Spark. Ranged Spell Attack: +4 to hit, range 60 ft. Hit: 5 (1d8 + 1) radiant damage."]},
                {"name":"Ashen Penitent","type":"Medium undead, neutral","ac":"12","hp":"30 (4d8 + 12)","speed":"25 ft.","abilities":"STR 14 · DEX 10 · CON 16 · INT 6 · WIS 12 · CHA 7","saves":"Con +5","skills":"—","senses":"darkvision 60 ft., passive Perception 11","languages":"understands Common but cannot speak","cr":"CR 1 (200 XP)","traits":["Ashen Body. The penitent is immune to disease and does not need to breathe."],"actions":["Cinder Grasp. Melee Weapon Attack: +4 to hit. Hit: 6 (1d8 + 2) bludgeoning plus 2 (1d4) fire damage.","Choking Ash (Recharge 6). Creatures within 10 feet make a DC 11 Con save or become blinded until the start of the penitent’s next turn."]}
            ]
        },
        {
            "name":"Three Cards Short", "faction":"The Queen’s Men", "level":"Level 2",
            "summary":"Retrieve a marked card deck containing a coded message before a rival gang plays the winning hand.",
            "tags":"Queen's Men, level 2, intrigue, chase",
            "body":"""MISSION HOOK
Blackjack Mel claims a sentimental deck was lifted from one of his couriers. In truth, three missing cards encode the place and time of a Queen’s Men exchange.

PRIMARY OBJECTIVES
• Identify the pickpocket who took the deck.
• Recover all three missing cards.
• Keep the exchange location secret.

SCENE BEATS
1. Market Tell — Questioning gamblers reveals that the deck was split among three young thieves.
2. Rooftop Cut — One thief runs, one bargains, and one unknowingly sold a card to a dangerous buyer.
3. Final Hand — The buyer challenges the party to a crooked game while allies close off the exits.

COMPLICATION
The thieves stole the deck to buy safe passage for their families. Mel cares about the message, not what happens to them.

OUTCOMES
Returning the cards earns coin and a Queen’s Men contact. Protecting the thieves costs part of the reward but creates a street-level information network.""",
            "npcs":[
                {"name":"Street Fixer","type":"Medium humanoid, chaotic neutral","ac":"13 (leather)","hp":"17 (3d8 + 3)","speed":"30 ft.","abilities":"STR 9 · DEX 15 · CON 12 · INT 13 · WIS 12 · CHA 15","saves":"—","skills":"Deception +4, Insight +3, Sleight of Hand +4","senses":"passive Perception 11","languages":"Common, thieves’ cant","cr":"CR 1/2 (100 XP)","traits":["Quick Deal. The fixer can take the Help action as a bonus action when aiding a Deception or Sleight of Hand check."],"actions":["Dagger. Melee or Ranged Weapon Attack: +4 to hit, reach 5 ft. or range 20/60 ft. Hit: 4 (1d4 + 2) piercing damage."]},
                {"name":"Alley Knife","type":"Medium humanoid, any non-lawful alignment","ac":"14 (studded leather)","hp":"24 (4d8 + 4)","speed":"30 ft.","abilities":"STR 11 · DEX 16 · CON 12 · INT 10 · WIS 11 · CHA 12","saves":"Dex +5","skills":"Acrobatics +5, Stealth +5","senses":"passive Perception 10","languages":"Common","cr":"CR 1 (200 XP)","traits":["Sneak Attack (1/Turn). The knife deals an extra 3 (1d6) damage when attacking with advantage or while an ally is adjacent to the target."],"actions":["Multiattack. The knife makes two Dagger attacks.","Dagger. Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or range 20/60 ft. Hit: 5 (1d4 + 3) piercing damage."]}
            ]
        },
    )
    with db() as conn:
        for mission in missions:
            exists = conn.execute("SELECT 1 FROM entries WHERE kind='mission' AND lower(name)=lower(?)", (mission["name"],)).fetchone()
            if exists: continue
            extra = {"faction":mission["faction"], "level":mission["level"], "npcs":mission["npcs"], "sample":True}
            conn.execute("""INSERT INTO entries(kind,name,summary,body,tags,status,extra)
                VALUES('mission',?,?,?,?,'Ready',?)""",
                (mission["name"], mission["summary"], mission["body"], mission["tags"], json.dumps(extra)))


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

    def display_session(self):
        cookies = self.headers.get("Cookie", "")
        token = next((x.split("=", 1)[1] for x in cookies.split("; ") if x.startswith("fizzle_display=")), "")
        return token if token in DISPLAY_SESSIONS else None

    def get_display_state(self):
        with db() as conn: row = conn.execute("SELECT payload FROM display_state WHERE id=1").fetchone()
        try: state = json.loads(row["payload"] or "{}")
        except (json.JSONDecodeError, TypeError): state = {}
        return {"initiative":state.get("initiative", {"combatants":[],"round":1,"currentId":None}),
                "message":str(state.get("message", "")), "image":str(state.get("image", "")),
                "focus":state.get("focus", "standard") if state.get("focus") in ("standard", "message", "image") else "standard",
                "theme":state.get("theme", "eldritch") if state.get("theme") in ("eldritch", "royal", "dragonfire", "frost", "wilds") else "eldritch"}

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
                WHERE kind='message' AND CAST(json_extract(extra,'$.player_id') AS INTEGER)=?
                ORDER BY created_at DESC""", (player_id,))]
            contacts = [row_dict(x) for x in conn.execute("""SELECT * FROM entries WHERE kind='npc'
                AND CAST(json_extract(extra,'$.contact') AS INTEGER)=1 ORDER BY name""")]
        if not row: return None
        player = row_dict(row); extra = player.get("extra", {})
        if extra.get("archived"): return None
        allowed = ("character_name", "pronouns", "class_name", "ancestry", "level", "armor_class", "max_hp",
                   "passive_perception", "speed", "initiative", "spell_save_dc", "background", "relationships", "goals")
        player["extra"] = {key: extra.get(key, "") for key in allowed}
        player.pop("body", None); player.pop("tags", None)
        safe_letters = [{"id":x["id"], "name":"An Anonymous Whisper" if x.get("extra", {}).get("message_type") == "rumor" else x["name"], "body":x["body"], "created_at":x["created_at"],
                         "message_type":x.get("extra", {}).get("message_type", "letter"),
                         "direction":x.get("extra", {}).get("direction", "dm_to_player"),
                         "contact_id":x.get("extra", {}).get("contact_id"),
                         "contact_name":x.get("extra", {}).get("contact_name", ""),
                         "contact_faction":x.get("extra", {}).get("contact_faction", "")} for x in letters]
        safe_contacts = [{"id":x["id"], "name":x["name"], "faction":x.get("extra", {}).get("faction", "")}
                         for x in contacts]
        return {"player":player, "sessions":sessions, "letters":safe_letters, "contacts":safe_contacts,
                "username":account["username"], "must_change":bool(account["must_change"]), "theme":self.get_display_state()["theme"]}

    def do_GET(self):
        parsed = urlparse(self.path)
        host = self.headers.get("Host", "").lower()
        direct_local_host = host == "localhost" or host.startswith("localhost:") or host == "127.0.0.1" or host.startswith("127.0.0.1:")
        if PUBLIC_URL and direct_local_host and parsed.path in ("/dm", "/dm/", "/dashboard", "/dashboard/", "/display", "/display/"):
            destination = "/dm" if parsed.path.startswith("/dm") else "/display" if parsed.path.startswith("/display") else "/dashboard"
            self.send_response(302)
            self.send_header("Location", f"{PUBLIC_URL}{destination}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); return
        if parsed.path == "/api/dm/me":
            if (not PUBLIC_URL and self.is_local()) or self.dm_session(): self.json({"authenticated":True}); return
            self.json({"authenticated":False}, 401); return
        if parsed.path == "/api/theme":
            self.json({"theme":self.get_display_state()["theme"]}); return
        if parsed.path == "/api/display/me":
            if self.display_session(): self.json({"authenticated":True}); return
            self.json({"authenticated":False}, 401); return
        if parsed.path == "/api/display/state":
            if not self.display_session(): self.json({"error":"Display login required"}, 401); return
            self.json(self.get_display_state()); return
        if parsed.path == "/api/display/control":
            if not self.require_local(): return
            self.json(self.get_display_state()); return
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
        if parsed.path == "/api/library":
            if not self.require_local(): return
            library = ROOT / "resources"; files = []
            if library.is_dir():
                for path in sorted(library.rglob("*"), key=lambda item: str(item).lower()):
                    if not path.is_file() or path.is_symlink() or any(part.startswith(".") for part in path.relative_to(library).parts): continue
                    relative = path.relative_to(library)
                    files.append({"name":path.stem, "filename":path.name, "folder":str(relative.parent) if relative.parent != Path(".") else "",
                                  "extension":path.suffix.lower().lstrip("."), "size":path.stat().st_size,
                                  "url":"/resources/" + quote(str(relative), safe="/")})
            self.json(files); return
        if parsed.path.startswith("/resources/"):
            if not self.require_local(): return
            target = (ROOT / unquote(parsed.path.lstrip("/"))).resolve()
            if ROOT / "resources" not in target.parents or not target.is_file(): self.send_error(404); return
            raw = target.read_bytes(); self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(target.name)}")
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw); return
        if parsed.path in ("/portal", "/portal/"): parsed = parsed._replace(path="/portal.html")
        if parsed.path in ("/demo", "/demo/"): parsed = parsed._replace(path="/demo.html")
        if parsed.path in ("/oracle", "/oracle/"): parsed = parsed._replace(path="/oracle.html")
        if parsed.path in ("/dashboard", "/dashboard/"): parsed = parsed._replace(path="/index.html")
        if parsed.path in ("/dm", "/dm/"): parsed = parsed._replace(path="/dm-login.html")
        if parsed.path in ("/display", "/display/"): parsed = parsed._replace(path="/display.html")
        if parsed.path == "/" and (PUBLIC_URL or not self.is_local()): parsed = parsed._replace(path="/portal.html")
        target = STATIC / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        if not target.is_file(): self.send_error(404); return
        raw = target.read_bytes(); self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        if self.path == "/api/theme":
            if not self.require_local(): return
            theme = str(self.body().get("theme", ""))
            if theme not in ("eldritch", "royal", "dragonfire", "frost", "wilds"):
                self.json({"error":"Unknown theme"}, 400); return
            state = self.get_display_state(); state["theme"] = theme
            with db() as conn: conn.execute("UPDATE display_state SET payload=?,updated_at=CURRENT_TIMESTAMP WHERE id=1", (json.dumps(state),))
            self.json({"ok":True, "theme":theme}); return
        if self.path == "/api/display/login":
            d = self.body(); username = str(d.get("username", "")).strip().lower(); password = str(d.get("password", ""))
            if not DISPLAY_PASSWORD: self.json({"error":"Display password is not configured"}, 503); return
            if not hmac.compare_digest(username, DISPLAY_USERNAME) or not hmac.compare_digest(password, DISPLAY_PASSWORD):
                self.json({"error":"Incorrect display username or password"}, 401); return
            token = secrets.token_urlsafe(32); DISPLAY_SESSIONS.add(token); raw = json.dumps({"ok":True}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            secure = "; Secure" if PUBLIC_URL else ""
            self.send_header("Set-Cookie", f"fizzle_display={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800{secure}")
            self.send_header("Content-Length", len(raw)); self.end_headers(); self.wfile.write(raw); return
        if self.path == "/api/display/logout":
            token = self.display_session()
            if token: DISPLAY_SESSIONS.discard(token)
            self.send_response(204); self.send_header("Set-Cookie", "fizzle_display=; Path=/; Max-Age=0"); self.end_headers(); return
        if self.path == "/api/display/control":
            if not self.require_local(): return
            d = self.body(); state = self.get_display_state()
            if "initiative" in d and isinstance(d["initiative"], dict): state["initiative"] = d["initiative"]
            if "message" in d: state["message"] = str(d["message"])[:2000]
            if "focus" in d and d["focus"] in ("standard", "message", "image"): state["focus"] = d["focus"]
            if "image" in d:
                image = str(d["image"])
                if image and (not image.startswith("data:image/") or len(image) > 8_000_000):
                    self.json({"error":"Use an image smaller than 6 MB"}, 413); return
                state["image"] = image
            if "message" in d and not state["message"] and state.get("focus") == "message": state["focus"] = "standard"
            if "image" in d and not state["image"] and state.get("focus") == "image": state["focus"] = "standard"
            with db() as conn: conn.execute("UPDATE display_state SET payload=?,updated_at=CURRENT_TIMESTAMP WHERE id=1", (json.dumps(state),))
            self.json({"ok":True}); return
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
            try: contact_id = int(d.get("contact_id") or 0)
            except (TypeError, ValueError): contact_id = 0
            if message_type not in ("quest", "letter"):
                self.json({"error":"Choose a personal quest update or a letter"}, 400); return
            if not message:
                self.json({"error":"Write a message before sending"}, 400); return
            if len(subject) > 120 or len(message) > 5000:
                self.json({"error":"Subject or message is too long"}, 400); return
            with db() as conn:
                player = conn.execute("SELECT name FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
                if not player: self.json({"error":"Player not found"}, 404); return
                contact = None
                if message_type == "letter" and contact_id:
                    contact = conn.execute("""SELECT name,json_extract(extra,'$.faction') faction FROM entries WHERE id=? AND kind='npc'
                        AND CAST(json_extract(extra,'$.contact') AS INTEGER)=1""", (contact_id,)).fetchone()
                    if not contact: self.json({"error":"Choose an available contact"}, 400); return
                label = "Personal Quest Update" if message_type == "quest" else "Letter"
                title = subject or label
                recipient = contact["name"] if contact else "Dungeon Master"
                contact_id = contact_id if contact else 0
                extra = json.dumps({"player_id":player_id, "player_name":player["name"], "message_type":message_type,
                                    "direction":"player_to_dm", "contact_id":contact_id or None,
                                    "contact_name":contact["name"] if contact else "",
                                    "contact_faction":contact["faction"] if contact else ""})
                cur = conn.execute("""INSERT INTO entries(kind,name,summary,body,tags,status,extra)
                    VALUES('message',?,?,?,?,?,?)""",
                    (f"{label} — {player['name']} to {recipient}: {title}", f"Private dispatch from {player['name']} to {recipient}", message,
                     "private, player dispatch", "Unread", extra))
            self.json({"ok":True,"id":cur.lastrowid}, 201); return
        if self.path.startswith("/api/player-letter/"):
            if not self.require_local(): return
            try: player_id = int(self.path.rsplit("/", 1)[1])
            except ValueError: self.send_error(404); return
            d = self.body(); subject = str(d.get("subject", "")).strip(); message = str(d.get("message", "")).strip()
            try: contact_id = int(d.get("contact_id") or 0)
            except (TypeError, ValueError): contact_id = 0
            if not message: self.json({"error":"Write a letter before sending"}, 400); return
            if len(subject) > 120 or len(message) > 5000:
                self.json({"error":"Subject or letter is too long"}, 400); return
            with db() as conn:
                player = conn.execute("SELECT name,extra FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
                if not player: self.json({"error":"Player not found"}, 404); return
                try: player_extra = json.loads(player["extra"] or "{}")
                except json.JSONDecodeError: player_extra = {}
                if player_extra.get("archived"): self.json({"error":"Archived players cannot receive letters"}, 409); return
                contact = None
                if contact_id:
                    contact = conn.execute("""SELECT name,json_extract(extra,'$.faction') faction FROM entries WHERE id=? AND kind='npc'
                        AND CAST(json_extract(extra,'$.contact') AS INTEGER)=1""", (contact_id,)).fetchone()
                    if not contact: self.json({"error":"Choose an available contact"}, 400); return
                sender = contact["name"] if contact else "Dungeon Master"
                title = subject or f"A Letter from {sender}"
                extra = json.dumps({"player_id":player_id, "player_name":player["name"], "message_type":"letter",
                                    "direction":"dm_to_player", "contact_id":contact_id or None,
                                    "contact_name":contact["name"] if contact else "",
                                    "contact_faction":contact["faction"] if contact else ""})
                cur = conn.execute("""INSERT INTO entries(kind,name,summary,body,tags,status,extra)
                    VALUES('message',?,?,?,?,?,?)""",
                    (f"Letter from {sender} to {player['name']}: {title}", f"Private letter from {sender} to {player['name']}", message,
                     "private, contact letter" if contact else "private, DM letter", "Sent", extra))
            self.json({"ok":True,"id":cur.lastrowid}, 201); return
        if self.path.startswith("/api/player-rumor/"):
            if not self.require_local(): return
            try: player_id = int(self.path.rsplit("/", 1)[1])
            except ValueError: self.send_error(404); return
            d = self.body(); rumor = str(d.get("rumor", "")).strip(); roll = str(d.get("roll", "")).strip()
            if not rumor: self.json({"error":"Roll a rumor before sending"}, 400); return
            if len(rumor) > 2000 or len(roll) > 20: self.json({"error":"Rumor is too long"}, 400); return
            with db() as conn:
                player = conn.execute("SELECT name,extra FROM entries WHERE id=? AND kind='player'", (player_id,)).fetchone()
                if not player: self.json({"error":"Player not found"}, 404); return
                try: player_extra = json.loads(player["extra"] or "{}")
                except json.JSONDecodeError: player_extra = {}
                if player_extra.get("archived"): self.json({"error":"Archived players cannot receive rumors"}, 409); return
                extra = json.dumps({"player_id":player_id, "player_name":player["name"], "message_type":"rumor",
                                    "direction":"dm_to_player", "roll":roll})
                cur = conn.execute("""INSERT INTO entries(kind,name,summary,body,tags,status,extra)
                    VALUES('message',?,?,?,?,?,?)""",
                    (f"Rumor to {player['name']}: d100 result {roll or '—'}", f"Rumor shared with {player['name']}", rumor,
                     "private, rumor", "Sent", extra))
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
            d = self.body(); allowed = ("character_name", "pronouns", "class_name", "ancestry", "level", "armor_class",
                                        "max_hp", "passive_perception", "speed", "initiative", "spell_save_dc",
                                        "background", "relationships", "goals")
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
    seed_sample_missions()
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
