"""Coletor de highscores e XP diário do Tibia Watch para DeusOLD.

Fontes públicas:
- /deusold/highscores: level e XP total mais recente.
- /deusold/exp-de-hoje: XP diário publicado pelo Tibia Watch.

Não consulta páginas bloqueadas do DeusOLD nem tenta contornar proteções.
"""
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json, os, re, sqlite3, unicodedata, requests

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv("DATABASE_PATH", str(BASE / "data.sqlite3"))
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CONFIG.get("timezone", "America/Sao_Paulo"))
RANKING_URL = "https://tibiawatch.com/deusold/highscores"
DAILY_URL = "https://tibiawatch.com/deusold/exp-de-hoje"

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; CoitadosBancados/1.1; public highscores monitor)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
})
retry = Retry(total=2, connect=2, read=1, backoff_factor=1,
              status_forcelist=(429, 500, 502, 503, 504),
              allowed_methods=frozenset(["GET"]))
S.mount("https://", HTTPAdapter(max_retries=retry))

def norm(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def name_key(v):
    s = unicodedata.normalize("NFKD", norm(v).casefold())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()

def number(v):
    s = norm(v).lower().replace("xp", "").replace("+", "").replace(" ", "")
    s = s.replace(",", ".")
    mult = 1
    if s.endswith(("kk", "m")):
        mult = 1_000_000
        s = s[:-2] if s.endswith("kk") else s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    try:
        if mult != 1:
            return int(float(s) * mult)
    except ValueError:
        return 0
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else 0

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS players(
      name TEXT PRIMARY KEY, level INTEGER DEFAULT 0, daily_xp INTEGER DEFAULT 0,
      recent_xp INTEGER DEFAULT 0, total_xp INTEGER DEFAULT 0, rank INTEGER DEFAULT 0,
      updated_at TEXT, day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(
      id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT, name TEXT,
      level INTEGER, total_xp INTEGER)""")
    c.commit()
    return c

def roster():
    names = []
    try:
        data = json.loads((BASE / "seed_vitoriosos.json").read_text(encoding="utf-8"))
        names.extend(norm(row[0]) for row in data.get("players", []) if row and row[0])
    except (OSError, ValueError, TypeError, IndexError):
        pass
    names.extend(norm(x) for x in CONFIG.get("invited", []) if norm(x))
    return {name_key(n): n for n in names if n}

def fetch_html(url):
    try:
        response = S.get(url, timeout=(10, 35))
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de conexão com {url}: {exc}") from exc
    if response.status_code == 403:
        raise RuntimeError(f"Fonte pública recusou a coleta automatizada (HTTP 403): {url}")
    if response.status_code == 429:
        raise RuntimeError(f"Fonte pública limitou as requisições (HTTP 429): {url}")
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")

def row_name(tr, cells):
    # Em ambas as tabelas o nome do personagem é um link.
    for a in tr.select("a"):
        text = norm(a.get_text(" ", strip=True))
        if text and not re.fullmatch(r"#?\d+", text):
            return text
    return cells[1] if len(cells) > 1 else ""

def fetch_highscores():
    soup = fetch_html(RANKING_URL)
    found = {}
    for tr in soup.select("tr"):
        cells = [norm(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        if len(cells) < 6 or "Memorium" not in cells:
            continue
        name = row_name(tr, cells)
        # A linha tem rank, personagem, guild, mundo, level, total XP e variação.
        world_index = cells.index("Memorium")
        level = 0
        for cell in cells[world_index + 1:]:
            m = re.match(r"^(\d{1,3})", cell)
            if m:
                level = int(m.group(1))
                break
        xp_values = [number(cell) for cell in cells if re.search(r"(?i)(kk|\bM\b|\bk\b)", cell)]
        if name and level and xp_values:
            rank_match = re.match(r"#?(\d+)", cells[0])
            found[name_key(name)] = {
                "name": name, "level": level, "total_xp": max(xp_values),
                "rank": int(rank_match.group(1)) if rank_match else 0
            }
    if not found:
        raise RuntimeError("Highscores respondeu, mas nenhuma linha válida de Memorium foi identificada.")
    return found

def fetch_daily_xp():
    soup = fetch_html(DAILY_URL)
    found = {}
    for tr in soup.select("tr"):
        cells = [norm(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        if len(cells) < 6 or "Memorium" not in cells:
            continue
        name = row_name(tr, cells)
        if not name:
            continue
        # Formato publicado: rank, personagem, mundo, vocação, level, XP no dia.
        xp = number(cells[-1])
        level_match = re.match(r"^(\d{1,3})", cells[-2]) if len(cells) >= 2 else None
        level = int(level_match.group(1)) if level_match else 0
        if xp >= 0:
            found[name_key(name)] = {"daily_xp": xp, "level": level}
    if not found:
        raise RuntimeError("A página Exp do Dia respondeu, mas nenhuma linha de Memorium foi identificada.")
    return found

def collect_once():
    allow = roster()
    if not allow:
        raise RuntimeError("Lista local vazia: seed_vitoriosos.json não foi carregado.")

    # Use the publisher's daily table when reachable; otherwise calculate from
    # total-XP snapshots collected since the 10:00 server save.
    try:
        daily = fetch_daily_xp()
        daily_error = None
    except Exception as exc:
        daily = {}
        daily_error = str(exc)
    try:
        ranking = fetch_highscores()
        ranking_error = None
    except Exception as exc:
        ranking = {}
        ranking_error = str(exc)
    if not daily and not ranking:
        raise RuntimeError(f"Falha nas duas fontes públicas. Exp do Dia: {daily_error}; Highscores: {ranking_error}")

    now = datetime.now(TZ)
    stamp = now.isoformat(timespec="seconds")
    game_date = now.date() if now.hour >= 10 else now.date() - timedelta(days=1)
    game_day = game_date.isoformat()
    start = datetime.combine(game_date, time(10, 0), TZ).isoformat(timespec="seconds")
    c = db()
    updated = 0
    for key, canonical in allow.items():
        d = daily.get(key, {})
        r = ranking.get(key, {})
        old = c.execute("SELECT total_xp,level FROM players WHERE name=?", (canonical,)).fetchone()
        total_xp = r.get("total_xp", old["total_xp"] if old else 0)
        level = r.get("level", d.get("level", old["level"] if old else 0))
        previous = c.execute(
            "SELECT total_xp FROM snapshots WHERE name=? ORDER BY id DESC LIMIT 1", (canonical,)
        ).fetchone()
        first_today = c.execute(
            "SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id ASC LIMIT 1",
            (canonical, start)
        ).fetchone()
        recent = max(0, total_xp - previous["total_xp"]) if previous and total_xp else 0
        # Prefer Tibia Watch's published daily value. If a character is not in
        # that top list, fall back to the service's own post-SS snapshots.
        if key in daily:
            daily_value = d["daily_xp"]
        elif total_xp and first_today:
            daily_value = max(0, total_xp - first_today["total_xp"])
        else:
            daily_value = 0
        rank = r.get("rank", 0)
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
          level=CASE WHEN excluded.level>0 THEN excluded.level ELSE players.level END,
          daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,
          total_xp=CASE WHEN excluded.total_xp>0 THEN excluded.total_xp ELSE players.total_xp END,
          rank=CASE WHEN excluded.rank>0 THEN excluded.rank ELSE players.rank END,
          updated_at=excluded.updated_at,day=excluded.day""",
          (canonical, level, daily_value, recent, total_xp, rank, stamp, game_day))
        if total_xp:
            c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",
                      (stamp, canonical, level, total_xp))
        updated += 1
    c.commit()
    c.close()
    result = {
        "ok": True, "source": "tibiawatch_public_highscores_and_daily_xp",
        "ranking_url": RANKING_URL, "daily_url": DAILY_URL,
        "daily_rows": len(daily), "ranking_rows": len(ranking),
        "roster_names": len(allow), "players_updated": updated,
        "captured_at": stamp, "server_save": "10:00 America/Sao_Paulo",
        "daily_xp_method": "Tibia Watch Exp do Dia published measurement",
        "ranking_warning": ranking_error,\n        "warnings": [ranking_error] if ranking_error else [],
        "note": "A fonte Exp do Dia publica a variação entre leituras diárias do Tibia Watch; não é um histórico minuto a minuto nem garante leitura exatamente às 10h."
    }
    print("[collector]", result)
    return result
