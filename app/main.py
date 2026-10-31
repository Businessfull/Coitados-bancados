from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import asyncio, os, sqlite3

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv("DATABASE_PATH", str(BASE / "data.sqlite3"))
INGEST_KEY = os.getenv("INGEST_KEY", "")
TZ = ZoneInfo("America/Sao_Paulo")

def now_local():
    return datetime.now(TZ)

def game_day(now=None):
    # A game day starts at 10:00 in Sao Paulo, not at midnight.
    now = now or now_local()
    return (now - timedelta(hours=10)).date().isoformat()

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY, level INTEGER DEFAULT 0, daily_xp INTEGER DEFAULT 0, recent_xp INTEGER DEFAULT 0, total_xp INTEGER DEFAULT 0, rank INTEGER DEFAULT 0, updated_at TEXT, day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS deaths(id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE, time TEXT, character TEXT, level INTEGER DEFAULT 0, involved TEXT, day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT, name TEXT, level INTEGER, total_xp INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS collector_status(id INTEGER PRIMARY KEY CHECK(id=1), last_success TEXT, last_error TEXT)""")
    c.commit()
    return c

def update_collector_status(success=False, error=None):
    c = db()
    old = c.execute("SELECT last_success FROM collector_status WHERE id=1").fetchone()
    last_success = now_local().isoformat(timespec="seconds") if success else (old["last_success"] if old else None)
    c.execute("""INSERT INTO collector_status(id,last_success,last_error) VALUES(1,?,?)
        ON CONFLICT(id) DO UPDATE SET last_success=excluded.last_success,last_error=excluded.last_error""",
        (last_success, None if success else (str(error)[:500] if error else None)))
    c.commit()
    c.close()

class Player(BaseModel):
    name: str
    level: int = 0
    daily_xp: int = 0
    recent_xp: int = 0
    total_xp: int = 0
    rank: int = 0
    updated_at: str = ""
class Death(BaseModel):
    time: str
    character: str
    level: int = 0
    involved: str = ""
class Ingest(BaseModel):
    players: list[Player] = Field(default_factory=list)
    deaths: list[Death] = Field(default_factory=list)

async def collector_loop():
    try:
        from app.collector import collect_once
    except Exception as exc:
        update_collector_status(error=f"Falha ao carregar coletor: {exc!r}")
        print("Collector import failed:", exc)
        return
    while True:
        try:
            result = await asyncio.to_thread(collect_once)
            update_collector_status(success=True)
            print("Collector finished:", result)
        except Exception as exc:
            update_collector_status(error=repr(exc))
            print("Collector error:", repr(exc))
        await asyncio.sleep(max(60, int(os.getenv("POLL_SECONDS", "300"))))

@asynccontextmanager
async def lifespan(app):
    db().close()
    task = asyncio.create_task(collector_loop()) if os.getenv("ENABLE_COLLECTOR", "1") == "1" else None
    yield
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

app = FastAPI(title="Coitados Bancados Monitor", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/")
def home():
    return FileResponse(BASE / "index.html")

@app.get("/api/health")
def health():
    c = db()
    count = c.execute("SELECT COUNT(*) n FROM players").fetchone()["n"]
    status = c.execute("SELECT last_success,last_error FROM collector_status WHERE id=1").fetchone()
    c.close()
    return {"ok": True, "collector_enabled": os.getenv("ENABLE_COLLECTOR", "1") == "1", "players": count,
            "last_collection": status["last_success"] if status else None,
            "collector_error": status["last_error"] if status else None, "timezone": "America/Sao_Paulo"}

@app.get("/api/dashboard")
def dashboard():
    today = game_day()
    c = db()
    players = [dict(x) for x in c.execute("SELECT name,level,daily_xp,recent_xp,total_xp,rank,updated_at FROM players WHERE day=? ORDER BY daily_xp DESC", (today,))]
    deaths = [dict(x) for x in c.execute("SELECT time,character,level,involved FROM deaths WHERE day=? ORDER BY id DESC LIMIT 100", (today,))]
    status = c.execute("SELECT last_success,last_error FROM collector_status WHERE id=1").fetchone()
    c.close()
    return {"summary": {"total_xp": sum(p["daily_xp"] or 0 for p in players), "recent_xp": sum(p["recent_xp"] or 0 for p in players), "player_count": len(players), "death_count": len(deaths)},
            "players": players, "deaths": deaths,
            "collector": {"last_success": status["last_success"] if status else None, "last_error": status["last_error"] if status else None}}

@app.post("/api/ingest")
def ingest(payload: Ingest, x_ingest_key: str = Header(default="")):
    if not INGEST_KEY or x_ingest_key != INGEST_KEY:
        raise HTTPException(401, "Chave de ingestão inválida")
    now = now_local()
    stamp = now.isoformat(timespec="seconds")
    day = game_day(now)
    c = db()
    for p in payload.players:
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET level=excluded.level,daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,total_xp=excluded.total_xp,rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
        (p.name,p.level,p.daily_xp,p.recent_xp,p.total_xp,p.rank,p.updated_at or stamp,day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",(stamp,p.name,p.level,p.total_xp))
    for d in payload.deaths:
        key = f"{day}|{d.time}|{d.character}|{d.level}|{d.involved}"
        c.execute("INSERT OR IGNORE INTO deaths(event_key,time,character,level,involved,day) VALUES(?,?,?,?,?,?)", (key,d.time,d.character,d.level,d.involved,day))
    c.commit()
    c.close()
    return {"ok": True, "players_received": len(payload.players), "deaths_received": len(payload.deaths), "captured_at": stamp}
