"""Coletor do ranking público do DeusOLD via página de highscores do Tibia Watch.

Não consulta páginas bloqueadas do DeusOLD, não usa login e não tenta
contornar Cloudflare. XP diário é calculado pela diferença entre snapshots
do ranking observados pelo próprio serviço desde o server save das 10h.
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
S = requests.Session()
S.headers.update({
    "User-Agent": "CoitadosBancados/1.0 (public highscores monitor)",
    "Accept": "text/html,application/xhtml+xml",
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
    mult = 1
    if s.endswith("kk") or s.endswith("m"):
        mult, s = 1_000_000, s[:-2] if s.endswith("kk") else s[:-1]
    elif s.endswith("k"):
        mult, s = 1_000, s[:-1]
    if mult != 1:
        try: return int(float(s.replace(",", ".")) * mult)
        except ValueError: return 0
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
    path = BASE / "seed_vitoriosos.json"
    names = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names.extend(norm(row[0]) for row in data.get("players", []) if row and row[0])
    except (OSError, ValueError, TypeError, IndexError):
        pass
    names.extend(norm(x) for x in CONFIG.get("invited", []) if norm(x))
    return {name_key(n): n for n in names if n}

def server_save_start(now):
    ss = time(10, 0)
    d = now.date() if now.timetz().replace(tzinfo=None) >= ss else now.date() - timedelta(days=1)
    return datetime.combine(d, ss, TZ)

def fetch_ranking():
    try:
        response = S.get(RANKING_URL, timeout=(10, 35))
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de conexão com o ranking público Tibia Watch: {exc}") from exc
    if response.status_code == 403:
        raise RuntimeError(
            f"Tibia Watch recusou o acesso automatizado ao ranking (HTTP 403) em {RANKING_URL}. "
            "O Render não recebeu permissão da origem; não será tentado nenhum bypass."
        )
    if response.status_code == 429:
        raise RuntimeError("Tibia Watch limitou as requisições (HTTP 429); aguardar e tentar novamente.")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found = {}
    for tr in soup.select("tr"):
        cells = [norm(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        if len(cells) < 5 or "Memorium" not in cells:
            continue
        anchors = [norm(a.get_text(" ", strip=True)) for a in tr.select("a")]
        name = next((a for a in anchors if a and not re.fullmatch(r"#?\d+", a)), "")
        if not name:
            # Character name is normally the second table cell.
            name = cells[1] if len(cells) > 1 else ""
        if not name or name.lower() in ("character", "personagem"):
            continue
        level = 0
        for cell in cells:
            if re.fullmatch(r"\d{1,4}", cell):
                n = int(cell)
                if 1 <= n <= 300:
                    level = n
        xp_values = [number(cell) for cell in cells
                     if re.search(r"(?i)(kk|\bk\b|\bm\b)", cell)]
        if not xp_values:
            xp_values = [number(cell) for cell in cells
                         if len(re.sub(r"\D", "", cell)) >= 6]
        xp = max(xp_values, default=0)
        rank_match = re.match(r"#?(\d+)", cells[0])
        rank = int(rank_match.group(1)) if rank_match else 0
        if level and xp:
            found[name_key(name)] = {
                "name": name, "level": level, "total_xp": xp, "rank": rank
            }
    if not found:
        raise RuntimeError(
            "A página de highscores respondeu, mas o coletor não encontrou linhas válidas "
            "do mundo Memorium. O HTML pode ter mudado."
        )
    return found

def collect_once():
    allow = roster()
    if not allow:
        raise RuntimeError("A lista local de personagens está vazia: seed_vitoriosos.json não foi carregado.")
    ranking = fetch_ranking()
    selected = []
    for key, row in ranking.items():
        canonical = allow.get(key)
        if canonical:
            row["name"] = canonical
            selected.append(row)
    if not selected:
        sample = ", ".join(x["name"] for x in list(ranking.values())[:5])
        raise RuntimeError(
            f"Ranking acessível ({len(ranking)} personagens), mas nenhum cruzou com a lista "
            f"local de {len(allow)} nomes. Exemplos no ranking: {sample}"
        )

    now = datetime.now(TZ)
    stamp = now.isoformat(timespec="seconds")
    start = server_save_start(now).isoformat(timespec="seconds")
    game_day = start[:10]
    c = db()
    for row in selected:
        previous = c.execute(
            "SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id DESC LIMIT 1",
            (row["name"], start)
        ).fetchone()
        first = c.execute(
            "SELECT total_xp FROM snapshots WHERE name=? AND captured_at>=? ORDER BY id ASC LIMIT 1",
            (row["name"], start)
        ).fetchone()
        recent = max(0, row["total_xp"] - previous["total_xp"]) if previous else 0
        daily = max(0, row["total_xp"] - first["total_xp"]) if first else 0
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
          level=excluded.level,daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,
          total_xp=excluded.total_xp,rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
          (row["name"], row["level"], daily, recent, row["total_xp"], row["rank"], stamp, game_day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",
                  (stamp, row["name"], row["level"], row["total_xp"]))
    c.commit()
    c.close()
    result = {
        "ok": True, "source": "tibiawatch_public_highscores",
        "source_url": RANKING_URL, "ranking_rows": len(ranking),
        "roster_names": len(allow), "players_updated": len(selected),
        "captured_at": stamp, "server_save": "10:00 America/Sao_Paulo",
        "daily_xp_method": "difference_between_first_and_latest_highscore_snapshot_after_server_save",
        "note": "XP diário começa na primeira leitura bem-sucedida após o server save; não recupera XP anterior à primeira leitura."
    }
    print("[collector]", result)
    return result
