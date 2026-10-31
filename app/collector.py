"""Best-effort public-data collector for the DeusOLD Vitoriosos roster.
Reads public ranking + guild pages only; no game login or client automation.
"""
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import json, os, re, unicodedata
import sqlite3
import requests

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv("DATABASE_PATH", str(BASE / "data.sqlite3"))
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CONFIG.get("timezone", "America/Sao_Paulo"))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
# Retry only transient throttling/server errors. A 403 is deliberately not
# retried or bypassed: it indicates that the remote site refused this client.
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
_retry = Retry(total=3, connect=3, read=2, backoff_factor=1.5,
               status_forcelist=(429, 500, 502, 503, 504),
               allowed_methods=frozenset(["GET"]), respect_retry_after_header=True)
SESSION.mount("https://", HTTPAdapter(max_retries=_retry))
SESSION.mount("http://", HTTPAdapter(max_retries=_retry))

def connect():
    c=sqlite3.connect(DB, timeout=30); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY,level INTEGER DEFAULT 0,daily_xp INTEGER DEFAULT 0,recent_xp INTEGER DEFAULT 0,total_xp INTEGER DEFAULT 0,rank INTEGER DEFAULT 0,updated_at TEXT,day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS deaths(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE,time TEXT,character TEXT,level INTEGER DEFAULT 0,involved TEXT,day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT,captured_at TEXT,name TEXT,level INTEGER,total_xp INTEGER)""")
    return c

def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def name_key(s):
    """Compare character names case/spacing/accent-insensitively."""
    value = unicodedata.normalize("NFKD", norm(s).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip()

def number(s):
    s=norm(s).lower().replace("+","").replace("xp","").strip()
    s=re.sub(r"\s+","",s)
    mult=1
    if s.endswith("kk") or s.endswith("m"):
        mult=1_000_000; s=s[:-2] if s.endswith("kk") else s[:-1]
    elif s.endswith("k"):
        mult=1_000; s=s[:-1]
    if mult != 1:
        s=s.replace(",",".")
        try: return int(float(s)*mult)
        except (ValueError, OverflowError): return 0
    s=s.replace(".","").replace(",","")
    try: return int(float(s))
    except (ValueError, OverflowError): return 0

def parse_level(s):
    m=re.search(r"\d+", norm(s))
    return int(m.group()) if m else 0

def get_soup(url):
    try:
        r = SESSION.get(url, timeout=(10, 30))
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de conexão ao consultar {url}: {exc}") from exc
    if r.status_code == 403:
        server = r.headers.get("server", "desconhecido")
        via = r.headers.get("via", "")
        raise RuntimeError(
            f"DeusOLD/origem recusou a coleta (HTTP 403) em {r.url}. "
            f"Servidor: {server}. Acesso precisa ser permitido pela origem; "
            "o coletor não tentará contornar essa proteção."
        )
    if r.status_code == 429:
        raise RuntimeError(f"Limite de requisições (HTTP 429) em {r.url}; aguarde antes de nova coleta.")
    try:
        r.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"Erro HTTP {r.status_code} ao consultar {r.url}: {exc}") from exc
    if not r.text.strip():
        raise RuntimeError(f"A origem retornou uma página vazia: {r.url}")
    return BeautifulSoup(r.text, "html.parser")

def roster_names(soup):
    names=set()
    for a in soup.select('a[href*="character"], a[href*="community/character"]'):
        name=norm(a.get_text(" ", strip=True))
        if name and len(name)<40 and not name.lower().startswith(("view","see","character")):
            names.add(name.casefold())
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
        if any(x.lower() in ("character","personagem","rank") for x in cells): continue
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
        xp=number(cells[-1])
        name=next((x for x in cells if x and not re.fullmatch(r"#?\d+",x) and not re.search(r"\d",x) and len(x)<40), "")
        if name and xp: found[name.casefold()]=xp
    return found

def server_save_start(now):
    ss=time(10,0)
    return datetime.combine(now.date(), ss, TZ) if now.timetz().replace(tzinfo=None)>=ss else datetime.combine(now.date()-timedelta(days=1),ss,TZ)

def collect_official_once():
    now=datetime.now(TZ); stamp=now.isoformat(timespec="seconds"); day=(now-timedelta(hours=10)).date().isoformat()
    guild_soup=get_soup(CONFIG["guild_url"])
    official=roster_names(guild_soup)
    invited={name_key(x) for x in CONFIG.get("invited",[])}
    allowed={name_key(x) for x in official} | invited
    if not allowed:
        raise RuntimeError("A página da guild não retornou membros. Verifique se o DeusOLD mudou o HTML ou bloqueou a coleta.")
    ranking=parse_ranking(get_soup(CONFIG["ranking_url"]))
    c=connect()
    accepted=0
    for key,row in ranking.items():
        if name_key(key) not in allowed: continue
        # Only a prior live snapshot can define recent XP; screenshot seed
        # totals are historical baselines, not a five-minute observation.
        start=server_save_start(now).isoformat(timespec="seconds")
        previous=c.execute("SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id DESC LIMIT 1",(row["name"],start)).fetchone()
        recent=max(0,row["total_xp"]-previous["total_xp"]) if previous else 0
        # Total earned since the 10:00 server save, using the first observed
        # ranking snapshot as the baseline. The external "exp do dia" page is
        # intentionally not used: it measures differences between crawler reads,
        # not necessarily the complete guild total since server save.
        first=c.execute("SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id ASC LIMIT 1",(row["name"],start)).fetchone()
        base=first["total_xp"] if first else row["total_xp"]
        daily_xp=max(0,row["total_xp"]-base)
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET level=excluded.level,daily_xp=excluded.daily_xp,
        recent_xp=excluded.recent_xp,total_xp=excluded.total_xp,rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
        (row["name"],row["level"],daily_xp,recent,row["total_xp"],row["rank"],stamp,day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",(stamp,row["name"],row["level"],row["total_xp"]))
        accepted+=1
    c.commit(); c.close()
    if accepted == 0:
        raise RuntimeError(f"Fontes acessíveis, mas nenhum membro da guild foi cruzado com o ranking (guild={len(official)}, ranking={len(ranking)}).")
    result={"guild_members":len(official),"ranking_rows":len(ranking),"players_updated":accepted,"daily_source_rows":0,"daily_xp_method":"ranking_since_first_snapshot_after_server_save","captured_at":stamp}
    print("[collector]",result)
    return result


def parse_tibiawatch_daily(soup, world):
    """Parse Tibia Watch's public daily XP table; never infer guild membership."""
    found = {}
    vocations = {"knight", "elite knight", "paladin", "royal paladin",
                 "sorcerer", "master sorcerer", "druid", "elder druid", "monk"}
    for tr in soup.select("tr"):
        cells = [norm(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        if len(cells) < 5:
            continue
        if world.casefold() not in [x.casefold() for x in cells]:
            continue
        xp = number(cells[-1])
        if xp <= 0:
            continue
        name = next((x for x in cells if x and not re.fullmatch(r"#?\d+", x)
                     and x.casefold() != world.casefold()
                     and x.casefold() not in vocations
                     and not re.search(r"[+]?\d", x)
                     and len(x) < 40), "")
        if not name:
            continue
        level = 0
        for cell in cells:
            if re.fullmatch(r"\d{1,4}(?:\+\d+)?", cell):
                level = parse_level(cell)
        rank_match = re.match(r"#?(\d+)", cells[0])
        found[name.casefold()] = {
            "name": name, "level": level, "daily_xp": xp,
            "rank": int(rank_match.group(1)) if rank_match else 0
        }
    return found


def collect_tibiawatch_fallback(reason):
    url = CONFIG.get("daily_url", "")
    if not url:
        raise RuntimeError(f"Fonte oficial indisponível ({reason}); daily_url não configurada.")
    soup = get_soup(url)
    rows = parse_tibiawatch_daily(soup, CONFIG.get("world", "Memorium"))
    # Use the complete roster transcribed from the guild/highscore screenshots,
    # not only the six manually invited characters in config.json.
    allowed = {name_key(x): norm(x) for x in load_seed_roster_names()}
    allowed.update({name_key(x): norm(x) for x in CONFIG.get("invited", []) if norm(x)})
    if not allowed:
        raise RuntimeError(
            f"Fonte oficial recusou acesso ({reason}); Tibia Watch retornou {len(rows)} linhas, "
            "mas não há lista de personagens autorizada/configurada para filtrar a guild."
        )
    selected = []
    for key, row in rows.items():
        canonical = allowed.get(name_key(key))
        if canonical:
            row["name"] = canonical
            selected.append(row)
    if not selected:
        raise RuntimeError(
            f"Fallback Tibia Watch acessível ({len(rows)} linhas), mas nenhum personagem "
            "da lista configurada apareceu no XP diário."
        )

    now = datetime.now(TZ)
    stamp = now.isoformat(timespec="seconds")
    day = (now - timedelta(hours=10)).date().isoformat()
    c = connect()
    for row in selected:
        prev = c.execute("SELECT daily_xp, day, total_xp FROM players WHERE name=?",
                         (row["name"],)).fetchone()
        # On the first reading of a game day there is no previous
        # observation, so do not mislabel the full daily total as 5-minute XP.
        recent = (
            max(0, row["daily_xp"] - (prev["daily_xp"] or 0))
            if prev and prev["day"] == day else 0
        )
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
        level=excluded.level,daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,
        rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
        (row["name"], row["level"], row["daily_xp"], recent,
         prev["total_xp"] if prev else 0, row["rank"], stamp, day))
    c.commit()
    c.close()
    result = {
        "source": "tibiawatch_daily_public",
        "official_source_error": str(reason)[:300],
        "daily_rows": len(rows),
        "players_updated": len(selected),
        "recent_xp_method": "difference_between_daily_source_reads",
        "captured_at": stamp
    }
    print("[collector:fallback]", result)
    return result




def load_seed_roster_names():
    """Return the full saved Vitoriosos roster with canonical display names."""
    seed_path = BASE / "seed_vitoriosos.json"
    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
        return [norm(row[0]) for row in payload.get("players", []) if row and row[0]]
    except (OSError, ValueError, TypeError, IndexError):
        return []

def load_seed_roster():
    """Compatibility helper for callers that need normalized roster keys."""
    return {name_key(name) for name in load_seed_roster_names()}


def parse_tibiawatch_world(soup, world):
    """Read the public world overview's server-rendered highscore rows."""
    found = {}
    for tr in soup.select("tr"):
        cells = [norm(x.get_text(" ", strip=True)) for x in tr.select("th,td")]
        if len(cells) < 4:
            continue
        if any(x.casefold() in ("personagem", "character", "experiência", "experience") for x in cells):
            continue
        # Overview rows contain rank, character, vocation, level and XP.
        name = next((x for x in cells if x and not re.fullmatch(r"#?\d+", x)
                     and not re.search(r"\d", x) and len(x) < 40
                     and x.casefold() not in {"elite knight", "knight", "royal paladin",
                         "paladin", "master sorcerer", "sorcerer", "elder druid", "druid"}), "")
        if not name:
            continue
        level = next((parse_level(x) for x in cells if re.fullmatch(r"\d{1,4}", x)), 0)
        xp = next((number(x) for x in reversed(cells) if re.search(r"\d", x)
                   and (re.search(r"[kKmM]", x) or len(re.sub(r"\D", "", x)) >= 5)), 0)
        if level and xp:
            rank_match = re.match(r"#?(\d+)", cells[0])
            found[name.casefold()] = {"name": name, "level": level, "total_xp": xp,
                                      "rank": int(rank_match.group(1)) if rank_match else 0}
    return found


def collect_tibiawatch_public():
    """Collect public highscores mirror; no login, game client, or access-control bypass."""
    url = "https://tibiawatch.com/deusold/memorium"
    soup = get_soup(url)
    ranking = parse_tibiawatch_world(soup, CONFIG.get("world", "Memorium"))
    if not ranking:
        raise RuntimeError("Tibia Watch respondeu, mas o HTML público não trouxe linhas de highscores legíveis.")
    allowed = {name_key(x): norm(x) for x in load_seed_roster_names()}
    allowed.update({name_key(x): norm(x) for x in CONFIG.get("invited", []) if norm(x)})
    selected = []
    for key, row in ranking.items():
        canonical = allowed.get(name_key(key))
        if canonical:
            row["name"] = canonical
            selected.append(row)
    if not selected:
        raise RuntimeError(f"Highscores públicos acessíveis ({len(ranking)} linhas), mas nenhum nome da lista Vitoriosos apareceu.")
    now = datetime.now(TZ)
    stamp = now.isoformat(timespec="seconds")
    day = (now - timedelta(hours=10)).date().isoformat()
    start = server_save_start(now).isoformat(timespec="seconds")
    c = connect()
    for row in selected:
        previous = c.execute("SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id DESC LIMIT 1",
                              (row["name"], start)).fetchone()
        recent = max(0, row["total_xp"] - previous["total_xp"]) if previous else 0
        first = c.execute("SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id ASC LIMIT 1",
                          (row["name"], start)).fetchone()
        baseline = first["total_xp"] if first else row["total_xp"]
        daily = max(0, row["total_xp"] - baseline)
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
          level=excluded.level,daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,
          total_xp=excluded.total_xp,rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
          (row["name"], row["level"], daily, recent, row["total_xp"], row["rank"], stamp, day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",
                  (stamp, row["name"], row["level"], row["total_xp"]))
    c.commit()
    c.close()
    result = {"source": "tibiawatch_public_highscores", "ranking_rows": len(ranking),
              "players_updated": len(selected), "captured_at": stamp,
              "daily_xp_method": "difference_since_first_snapshot_after_10am"}
    print("[collector:tibiawatch]", result)
    return result


def collect_once():
    """Collect live public data, preferring DeusOLD and falling back to Tibia Watch.

    Both sources are public pages. No login, private endpoint, or access-control
    bypass is attempted. The fallback is used only when the official pages fail.
    """
    official_error = None
    try:
        result = collect_official_once()
        return {
            "ok": True,
            "sources": ["deusold_official_guild", "deusold_official_ranking"],
            "warnings": [],
            "players_updated": int(result.get("players_updated", 0)),
            "guild_members": int(result.get("guild_members", 0)),
            "ranking_rows": int(result.get("ranking_rows", 0)),
            "captured_at": result.get("captured_at"),
            "source": "deusold_official",
            "daily_xp_method": result.get("daily_xp_method"),
        }
    except Exception as exc:
        official_error = str(exc)
        print("[collector] official source failed; trying public Tibia Watch fallback:", official_error)

    try:
        result = collect_tibiawatch_fallback(official_error)
        return {
            "ok": True,
            "sources": ["tibiawatch_public_daily"],
            "warnings": [f"Fonte oficial indisponível: {official_error[:250]}"],
            "players_updated": int(result.get("players_updated", 0)),
            "guild_members": 0,
            "ranking_rows": int(result.get("daily_rows", 0)),
            "captured_at": result.get("captured_at"),
            "source": result.get("source", "tibiawatch_daily_public"),
            "daily_xp_method": result.get("recent_xp_method"),
        }
    except Exception as fallback_error:
        raise RuntimeError(
            "Nenhuma fonte pública conseguiu fornecer dados. "
            f"DeusOLD: {official_error[:250]} | "
            f"Tibia Watch: {str(fallback_error)[:250]}"
        ) from fallback_error
