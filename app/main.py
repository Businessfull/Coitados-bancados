from datetime import datetime
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import os, sqlite3

BASE = Path(__file__).resolve().parent.parent
DB = os.getenv('DATABASE_PATH', str(BASE / 'data.sqlite3'))
INGEST_KEY = os.getenv('INGEST_KEY', '')
app = FastAPI(title='Vitoriosos Guild Monitor', version='0.1.0')
app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY, level INTEGER, daily_xp INTEGER, recent_xp INTEGER, updated_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS deaths(id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, character TEXT, level INTEGER, involved TEXT, day TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT, name TEXT, level INTEGER, total_xp INTEGER)')
    return c

class Player(BaseModel):
    name: str
    level: int = 0
    daily_xp: int = 0
    recent_xp: int = 0
    updated_at: str = ''
class Death(BaseModel):
    time: str
    character: str
    level: int = 0
    involved: str = ''
class Ingest(BaseModel):
    players: list[Player] = Field(default_factory=list)
    deaths: list[Death] = Field(default_factory=list)

@app.get('/')
def home(): return FileResponse(BASE / 'index.html')
@app.get('/api/health')
def health(): return {'ok': True, 'service': 'vitoriosos-monitor'}
@app.get('/api/dashboard')
def dashboard():
    c=db(); today=datetime.now().astimezone().date().isoformat()
    players=[dict(x) for x in c.execute('SELECT * FROM players ORDER BY daily_xp DESC')]
    deaths=[dict(x) for x in c.execute('SELECT time,character,level,involved FROM deaths WHERE day=? ORDER BY id DESC LIMIT 100',(today,))]
    c.close()
    return {'summary':{'total_xp':sum(p['daily_xp'] or 0 for p in players),'recent_xp':sum(p['recent_xp'] or 0 for p in players),'player_count':len(players),'death_count':len(deaths)},'players':players,'deaths':deaths}
@app.post('/api/ingest')
def ingest(payload: Ingest, x_ingest_key: str = Header(default='')):
    if not INGEST_KEY or x_ingest_key != INGEST_KEY: raise HTTPException(401,'Chave de ingestão inválida')
    now=datetime.now().astimezone().isoformat(timespec='seconds'); day=datetime.now().astimezone().date().isoformat(); c=db()
    for p in payload.players:
        c.execute('INSERT INTO players(name,level,daily_xp,recent_xp,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET level=excluded.level,daily_xp=excluded.daily_xp,recent_xp=excluded.recent_xp,updated_at=excluded.updated_at',(p.name,p.level,p.daily_xp,p.recent_xp,p.updated_at or now))
        c.execute('INSERT INTO snapshots(captured_at,name,level,total_xp) VALUES(?,?,?,?)',(now,p.name,p.level,p.daily_xp))
    for d in payload.deaths:
        c.execute('INSERT INTO deaths(time,character,level,involved,day) VALUES(?,?,?,?,?)',(d.time,d.character,d.level,d.involved,day))
    c.commit(); c.close()
    return {'ok':True,'players_received':len(payload.players),'deaths_received':len(payload.deaths),'captured_at':now}
