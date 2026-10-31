"""Best-effort public-data collector for the DeusOLD Vitoriosos roster.
Reads public ranking + guild pages only; no game login or client automation.
"""
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import json, os, re, sqlite3, time as time_module
import requests

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv("DATABASE_PATH", str(BASE / "data.sqlite3"))
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CONFIG.get("timezone", "America/Sao_Paulo"))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GuildMonitor/1.0; public-data)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def connect():
    c=sqlite3.connect(DB, timeout=30); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY,level INTEGER DEFAULT 0,daily_xp INTEGER DEFAULT 0,recent_xp INTEGER DEFAULT 0,total_xp INTEGER DEFAULT 0,rank INTEGER DEFAULT 0,updated_at TEXT,day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS deaths(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE,time TEXT,character TEXT,level INTEGER DEFAULT 0,involved TEXT,day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT,captured_at TEXT,name TEXT,level INTEGER,total_xp INTEGER)""")
    return c

def norm(s): return re.sub(r"\s+", " ", (s or "")).strip()
def number(s):
    s=norm(s).lower().replace("+","").replace("xp","").strip()
    s=re.sub(r"\\s+","",s)
    mult=1
    if s.endswith("kk") or s.endswith("m"):
        mult=1_000_000; s=s[:-2] if s.endswith("kk") else s[:-1]
    elif s.endswith("k"):
        mult=1_000; s=s[:-1]
    # Decimal suffixes (19.2kk / 3.9M) versus thousands-separated integers.
    if mult != 1:
        s=s.replace(",",".")
        try: return int(float(s)*mult)
        except: return 0
    s=s.replace(".","").replace(",","")
    try: return int(float(s))
    except: return 0

def parse_level(s):
    m=re.search(r"\d+", norm(s))
    return int(m.group()) if m else 0

def get_soup(url):
    r=SESSION.get(url, timeout=25); r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def roster_names(soup):
    names=set()
    for a in soup.select('a[href*="character"], a[href*="community/character"]'):
        name=norm(a.get_text(" ", strip=True))
        if name and len(name)<40 and not name.lower().startswith(("view","see","character")):
            names.add(name.casefold())
    # Some site versions show a table with Character as the first column.
    for tr in soup.select("table tr"):
        cells=[norm(x.get_text(" ",strip=True)) for x in tr.select("th,td")]
        if cells and cells[0] and not cells[0].lower().startswith("character"):
            if len(cells[0])<40: names.add(cells[0].casefold())
    return names

def parse_ranking(soup):
    found={}
    for tr in soup.select("tr"):
        cells=[norm(x.get_text(" ",strip=True)) for x in tr.select("th,td")]
        if len(cells)<4: continue
        # Ranking layouts vary; identify name, level and XP by table headers or common row shape.
        if any(x.lower() in ("character","personagem","rank") for x in cells): continue
        text=" ".join(cells)
        xp_candidates=[number(x) for x in cells if re.search(r"\d",x) and (re.search(r"[kKmM]",x) or len(re.sub(r"\D","",x))>=5)]
        level_candidates=[parse_level(x) for x in cells if re.fullmatch(r"\d{1,4}(?:\+\d+)?",x)]
        if not xp_candidates or not level_candidates: continue
        name=next((x for x in cells if x and not re.fullmatch(r"#?\d+",x) and not re.search(r"\d",x) and len(x)<40), "")
        if not name: continue
        rank_match=re.match(r"#?(\d+)",cells[0])
        found[name.casefold()]={"name":name,"level":level_candidates[-1],"total_xp":max(xp_candidates),"rank":int(rank_match.group(1)) if rank_match else 0}
    return found

def parse_daily(soup):
    found={}
    for tr in soup.select("tr"):
        cells=[norm(x.get_text(" ",strip=True)) for x in tr.select("th,td")]
        if len(cells)<5: continue
        if any(x.lower() in ("personagem","character","rank") for x in cells): continue
        # On the daily page, character name and final column is daily XP.
        xp=number(cells[-1])
        name=next((x for x in cells if x and not re.fullmatch(r"#?\d+",x) and not re.search(r"\d",x) and len(x)<40), "")
        if name and xp: found[name.casefold()]=xp
    return found

def server_save_start(now):
    # Daily accumulation resets at 10:00 local server time.
    ss=time(10,0)
    return datetime.combine(now.date(), ss, TZ) if now.timetz().replace(tzinfo=None)>=ss else datetime.combine(now.date()-timedelta(days=1),ss,TZ)

def collect_once():
    now=datetime.now(TZ); stamp=now.isoformat(timespec="seconds"); day=now.date().isoformat()
    guild_url=CONFIG["guild_url"]
    ranking_url=CONFIG["ranking_url"]
    daily_url=CONFIG["daily_url"]
    # Guild page is used to discover the official member list. Invited names are kept separately in config.
    guild_soup=get_soup(guild_url)
    official=roster_names(guild_soup)
    invited={x.casefold() for x in CONFIG.get("invited",[])}
    # Keep only official members + explicitly listed invited players, as requested.
    allowed=official | invited
    if not allowed:
        raise RuntimeError("Roster da guild veio vazio; coleta interrompida para não misturar personagens de outras guilds.")
    ranking=parse_ranking(get_soup(ranking_url))
    daily=parse_daily(get_soup(daily_url))
    c=connect()
    for key,row in ranking.items():
        if allowed and key not in allowed: continue
        prev=c.execute("SELECT total_xp,day FROM players WHERE name=?",(row["name"],)).fetchone()
        recent=max(0,row["total_xp"]-(prev["total_xp"] or 0)) if prev and prev["day"]==day else 0
        daily_xp=daily.get(key, 0)
        # Daily source is authoritative when it contains the character. Otherwise retain cumulative
        # XP calculated since 10:00 Server Save using stored snapshots.
        if key not in daily:
            start=server_save_start(now).isoformat(timespec="seconds")
            first=c.execute("SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id ASC LIMIT 1",(row["name"],start)).fetchone()
            base=first["total_xp"] if first else row["total_xp"]
            daily_xp=max(0,row["total_xp"]-base)
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET level=excluded.level,daily_xp=excluded.daily_xp,
        recent_xp=excluded.recent_xp,total_xp=excluded.total_xp,rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
        (row["name"],row["level"],daily_xp,recent,row["total_xp"],row["rank"],stamp,day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",(stamp,row["name"],row["level"],row["total_xp"]))
    c.commit(); c.close()
    print(f"[collector] {stamp}: {len(official)} guild members, {len(ranking)} ranking rows, {len(allowed)} allowed names")
