"""Coletor exclusivo do Highscore oficial do DeusOLD.

Percorre as páginas públicas de /ranking, cruza os nomes com
seed_vitoriosos.json e mede XP por snapshots a cada cinco minutos.
Não usa Tibia Watch nem páginas de guild bloqueadas.
"""
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json, os, re, sqlite3, unicodedata

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv("DATABASE_PATH", str(BASE / "data.sqlite3"))
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CONFIG.get("timezone", "America/Sao_Paulo"))
RANKING_URL = CONFIG.get("ranking_url", "https://www.deusold.com/ranking")
MAX_PAGES = int(os.getenv("MAX_RANKING_PAGES", str(CONFIG.get("max_pages", 30))))

def norm(v):
    s = unicodedata.normalize("NFKD", str(v or "").strip().casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s)

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
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_name_time ON snapshots(name,captured_at)")
    c.commit()
    return c

def roster():
    path = BASE / "seed_vitoriosos.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = [str(row[0]).strip() for row in data.get("players", []) if row and row[0]]
    except (OSError, ValueError, TypeError, IndexError) as exc:
        raise RuntimeError(f"Não foi possível carregar seed_vitoriosos.json: {exc}") from exc
    names.extend(str(x).strip() for x in CONFIG.get("invited", []) if str(x).strip())
    return {norm(n): n for n in names if n}

def fetch_page(page):
    url = RANKING_URL + "?" + urlencode({"page": page})
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
    })
    try:
        with urlopen(req, timeout=25) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == 403:
            raise RuntimeError(f"Highscore oficial recusou acesso automatizado (HTTP 403) na página {page}.") from exc
        if code == 429:
            raise RuntimeError(f"Highscore oficial limitou as consultas (HTTP 429) na página {page}.") from exc
        raise RuntimeError(f"Página {page}: falha ao consultar o Highscore oficial: {exc}") from exc

def parse_page(html, page, targets):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for tr in soup.select("tr"):
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()
                 for td in tr.select("td,th")]
        if len(cells) < 5:
            continue
        # Formato original do ranking: rank, nome, vocação, mundo, level, experiência.
        name = cells[1]
        key = norm(name)
        if key not in targets:
            continue
        level = None
        xp = None
        for value in cells[2:]:
            numeric = value.replace(",", "").replace(".", "")
            if re.fullmatch(r"\\d+", numeric):
                n = int(numeric)
                if level is None and 1 <= n <= 300:
                    level = n
                elif n > 1000:
                    xp = n
        if level is not None:
            rank_match = re.match(r"#?(\d+)", cells[0])
            found.append({
                "name": targets[key], "level": level, "total_xp": xp,
                "rank": int(rank_match.group(1)) if rank_match else 0, "page": page
            })
    return found

def fetch_highscores():
    targets = roster()
    all_rows, errors = [], []
    for page in range(1, MAX_PAGES + 1):
        try:
            rows = parse_page(fetch_page(page), page, targets)
            if rows:
                all_rows.extend(rows)
        except Exception as exc:
            errors.append(str(exc))
            # A 403/429 na primeira página não será repetido em dezenas de páginas.
            if "HTTP 403" in str(exc) or "HTTP 429" in str(exc):
                break
    if not all_rows:
        detail = " | ".join(errors[:3]) if errors else "nenhum personagem da lista foi encontrado nas páginas consultadas"
        raise RuntimeError(f"Não foi possível coletar membros no Highscore oficial: {detail}")
    # Keep the most recent occurrence of each monitored character.
    unique = {}
    for row in all_rows:
        unique[norm(row["name"])] = row
    return list(unique.values()), errors

def collect_once():
    allow = roster()
    if not allow:
        raise RuntimeError("A lista local de personagens está vazia.")
    rows, errors = fetch_highscores()
    now = datetime.now(TZ)
    stamp = now.isoformat(timespec="seconds")
    game_date = now.date() if now.hour >= int(CONFIG.get("server_save_hour", 10)) else now.date() - timedelta(days=1)
    game_day = game_date.isoformat()
    start = datetime.combine(game_date, time(int(CONFIG.get("server_save_hour", 10)), 0), TZ).isoformat(timespec="seconds")

    c = db()
    updated = 0
    for row in rows:
        name = row["name"]
        previous = c.execute(
            "SELECT total_xp FROM snapshots WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        first_today = c.execute(
            "SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id ASC LIMIT 1",
            (name, start)
        ).fetchone()
        recent = max(0, row["total_xp"] - previous["total_xp"]) if previous and row["total_xp"] is not None else 0
        daily = max(0, row["total_xp"] - first_today["total_xp"]) if first_today and row["total_xp"] is not None else 0
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
          level=excluded.level,daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,
          total_xp=COALESCE(excluded.total_xp,players.total_xp),
          rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
          (name, row["level"], daily, recent, row["total_xp"], row["rank"], stamp, game_day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",
                  (stamp, name, row["level"], row["total_xp"]))
        updated += 1
    c.commit()
    c.close()
    result = {
        "ok": True, "source": "official_deusold_highscores",
        "source_url": RANKING_URL, "pages_checked": MAX_PAGES,
        "roster_names": len(allow), "players_updated": updated,
        "captured_at": stamp, "server_save": f'{CONFIG.get("server_save_hour", 10):02d}:00 America/Sao_Paulo',
        "daily_xp_method": "difference_between_first_and_latest_official_highscore_snapshot_after_server_save",
        "warnings": errors,
        "note": "XP diário começa na primeira leitura bem-sucedida após o server save; a primeira leitura serve como linha de base."
    }
    print("[collector]", result)
    return result
