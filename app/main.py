from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import asyncio, json, os, sqlite3

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv("DATABASE_PATH", str(BASE / "data.sqlite3"))
INGEST_KEY = os.getenv("INGEST_KEY", "")
CONFIG_PATH = BASE / "config.json"

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS players(
        name TEXT PRIMARY KEY, level INTEGER DEFAULT 0, daily_xp INTEGER DEFAULT 0,
        recent_xp INTEGER DEFAULT 0, total_xp INTEGER DEFAULT 0,
        rank INTEGER DEFAULT 0, updated_at TEXT, day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS deaths(
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE,
        time TEXT, character TEXT, level INTEGER DEFAULT 0, involved TEXT, day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(
        id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT, name TEXT,
        level INTEGER, total_xp INTEGER)""")
    c.commit()
    return c

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
        print("Collector import failed:", exc)
        return
    while True:
        try:
            await asyncio.to_thread(collect_once)
        except Exception as exc:
            print("Collector error:", repr(exc))
        await asyncio.sleep(int(os.getenv("POLL_SECONDS", "300")))

@asynccontextmanager
async def lifespan(app):
    db().close()
    task = asyncio.create_task(collector_loop()) if os.getenv("ENABLE_COLLECTOR", "1") == "1" else None
    yield
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

app = FastAPI(title="Coitados Bancados Monitor", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/")
def home():
    return FileResponse(BASE / "index.html")

@app.get("/api/health")
def health():
    c = db()
    count = c.execute("SELECT COUNT(*) n FROM players").fetchone()["n"]
    c.close()
    return {"ok": True, "collector_enabled": os.getenv("ENABLE_COLLECTOR", "1") == "1", "players": count}

@app.get("/api/dashboard")
def dashboard():
    today = datetime.now().astimezone().date().isoformat()
    c = db()
    players = [dict(x) for x in c.execute("SELECT name,level,daily_xp,recent_xp,total_xp,rank,updated_at FROM players WHERE day=? ORDER BY daily_xp DESC", (today,))]
    deaths = [dict(x) for x in c.execute("SELECT time,character,level,involved FROM deaths WHERE day=? ORDER BY id DESC LIMIT 100", (today,))]
    c.close()
    return {"summary": {"total_xp": sum(p["daily_xp"] or 0 for p in players),
        "recent_xp": sum(p["recent_xp"] or 0 for p in players),
        "player_count": len(players), "death_count": len(deaths)},
        "players": players, "deaths": deaths}

@app.post("/api/ingest")
def ingest(payload: Ingest, x_ingest_key: str = Header(default="")):
    if not INGEST_KEY or x_ingest_key != INGEST_KEY:
        raise HTTPException(401, "Chave de ingestão inválida")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    day = datetime.now().astimezone().date().isoformat()
    c = db()
    for p in payload.players:
        c.execute("""INSERT INTO players(name,level,daily_xp,recent_xp,total_xp,rank,updated_at,day)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET level=excluded.level,
        daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,total_xp=excluded.total_xp,
        rank=excluded.rank,updated_at=excluded.updated_at,day=excluded.day""",
        (p.name,p.level,p.daily_xp,p.recent_xp,p.total_xp,p.rank,p.updated_at or now,day))
        c.execute("INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)",(now,p.name,p.level,p.total_xp))
    for d in payload.deaths:
        key = f"{day}|{d.time}|{d.character}|{d.level}|{d.involved}"
        c.execute("INSERT OR IGNORE INTO deaths(event_key,time,character,level,involved,day) VALUES(?,?,?,?,?,?)",
                  (key,d.time,d.character,d.level,d.involved,day))
    c.commit(); c.close()
    return {"ok": True, "players_received": len(payload.players), "deaths_received": len(payload.deaths), "captured_at": now}
