import os
import json
import uuid
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, Text,
    ForeignKey, select, func, and_, or_, text as sql_text, UniqueConstraint
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from sqlalchemy.dialects.postgresql import JSONB

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inhouse.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "924sdb")
CORS_ALLOW_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
] if os.getenv("CORS_ALLOW_ORIGINS") else ["*"]

IS_POSTGRES = DATABASE_URL.lower().startswith("postgres")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

UTC = timezone.utc

# Helpers para JSON dependendo do dialeto
def JSONCol(nullable=True):
    return Column(JSONB if IS_POSTGRES else Text, nullable=nullable)

def jloads(v):
    if v is None:
        return None
    if IS_POSTGRES:
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return v

def jdumps(v):
    if v is None:
        return None
    if IS_POSTGRES:
        return v
    return json.dumps(v, ensure_ascii=False)

# -------------------------------------------------------------------
# Modelos
# -------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)  # uuid
    name = Column(String, unique=True, index=True)
    score = Column(Float, default=0.0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    played = Column(Integer, default=0)
    current_streak = Column(Integer, default=0)
    max_streak = Column(Integer, default=0)
    streaks_broken = Column(Integer, default=0)
    correct_bets = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(tz=UTC))

class QueueEntry(Base):
    __tablename__ = "queue"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    joined_at = Column(DateTime, default=lambda: datetime.now(tz=UTC))
    user = relationship("User")

class Match(Base):
    __tablename__ = "matches"
    id = Column(String, primary_key=True)  # uuid interno
    display_id = Column(Text, nullable=True)  # "YYYY-MM-DD HH:MM:SS + N"
    map = Column(String, nullable=False)
    status = Column(String, index=True)  # draft, in_progress, finished, canceled
    started_at = Column(DateTime, nullable=True)
    bet_deadline = Column(DateTime, nullable=True)
    draft_round = Column(Integer, default=0)  # 0..2
    finished_at = Column(DateTime, nullable=True)

    team1 = JSONCol()
    team2 = JSONCol()
    picks = JSONCol()  # { user_id: champion }
    winner_team = Column(Integer, nullable=True)

    # streakados na criação (para histórico)
    streaked_player_ids = JSONCol()

    # reporte de resultado (um de cada time)
    t1_report = Column(Integer, nullable=True)       # 1 ou 2
    t2_report = Column(Integer, nullable=True)       # 1 ou 2
    t1_reporter = Column(String, nullable=True)      # user_id
    t2_reporter = Column(String, nullable=True)      # user_id

    # snapshot de deltas aplicados na finalização (para reverter/cancelar/override)
    result_deltas = JSONCol()

class Bet(Base):
    __tablename__ = "bets"
    id = Column(String, primary_key=True)  # uuid
    match_id = Column(String, ForeignKey("matches.id"), index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    team = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(tz=UTC))
    __table_args__ = (UniqueConstraint('match_id', 'user_id', name='uq_bet_match_user'),)

class AdminConfig(Base):
    __tablename__ = "admin_config"
    id = Column(Integer, primary_key=True)
    points_win = Column(Float, default=1.0)
    points_loss = Column(Float, default=0.0)
    streak_bonus = JSONCol()       # {"3":0.25,"6":0.5,"9":1}
    active_maps = JSONCol()
    active_champions = JSONCol()

class DayCounter(Base):
    __tablename__ = "day_counters"
    day = Column(String, primary_key=True)  # YYYY-MM-DD
    counter = Column(Integer, default=0)

class ChampionStat(Base):
    __tablename__ = "champion_stats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    champion = Column(String, index=True)
    played = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    streaks_broken = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint('user_id', 'champion', name='uq_user_champion'),)

Base.metadata.create_all(engine)

# migração leve: garante novas colunas
with engine.begin() as conn:
    for col, ddl in [
        ("t1_report", "integer"),
        ("t2_report", "integer"),
        ("t1_reporter", "text"),
        ("t2_reporter", "text"),
        ("finished_at", "timestamp"),
        ("result_deltas", "jsonb" if IS_POSTGRES else "text"),
    ]:
        try:
            conn.execute(sql_text(f"ALTER TABLE matches ADD COLUMN IF NOT EXISTS {col} {ddl}"))
        except Exception:
            pass

# Corrige / inicializa config padrão
def ensure_admin_config(db: Session) -> AdminConfig:
    cfg = db.execute(select(AdminConfig).where(AdminConfig.id == 1)).scalar_one_or_none()
    if not cfg:
        cfg = AdminConfig(
            id=1,
            points_win=1.0,
            points_loss=0.0,
            streak_bonus=jdumps({"3":0.25,"6":0.5,"9":1.0}),
            active_maps=jdumps([
                "Mount Araz Day","Mount Araz Night","Orman Night",
                "Blackstone Day","Blackstone Night",
                "Dragon Garden Day","Dragon Garden Night","Meriko Night"
            ]),
            active_champions=jdumps([
                "Alysia","Ashka","Bakko","Blossom","Croak","Destiny","Ezmo","Freya","Iva","Jade","Jamila",
                "Jumong","Lucie","Oldur","Pearl","Pestilus","Poloma","Raigon","Rook","Ruh Kaan","Shen Rao","Shifu","Sirius",
                "Taya","Thorn","Ulric","Varesh","Zander"
            ])
        )
        db.add(cfg)
        db.commit()
    return cfg

# -------------------------------------------------------------------
# FastAPI / CORS
# -------------------------------------------------------------------
app = FastAPI(title="Inhouse BR API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# (Alguns proxies fazem preflight agressivo)
@app.options("/{rest_of_path:path}")
def options_passthrough(rest_of_path: str):
    return PlainTextResponse("ok")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------
def now():
    return datetime.now(tz=UTC)

def is_user_in_active_match(db: Session, user_id: str) -> bool:
    for m in db.execute(select(Match)).scalars():
        if m.status in ("draft","in_progress"):
            t1 = jloads(m.team1) or []
            t2 = jloads(m.team2) or []
            if user_id in t1 or user_id in t2:
                return True
    return False

def next_display_id(db: Session) -> str:
    d = now().strftime("%Y-%m-%d")
    rec = db.execute(select(DayCounter).where(DayCounter.day == d)).scalar_one_or_none()
    if not rec:
        rec = DayCounter(day=d, counter=0)
        db.add(rec)
        db.commit()
        db.refresh(rec)
    rec.counter += 1
    db.commit()
    return f"{now().strftime('%Y-%m-%d %H:%M:%S')} + {rec.counter}"

def pick_random_map(db: Session) -> str:
    cfg = ensure_admin_config(db)
    maps = jloads(cfg.active_maps) or []
    return random.choice(maps or ["Mount Araz Day"])

def champ_is_allowed(db: Session, name: str) -> bool:
    cfg = ensure_admin_config(db)
    allowed = jloads(cfg.active_champions) or []
    return name in allowed

def get_or_create_champ_stat(db: Session, user_id: str, champion: str) -> ChampionStat:
    cs = db.execute(
        select(ChampionStat).where(ChampionStat.user_id==user_id, ChampionStat.champion==champion)
    ).scalar_one_or_none()
    if not cs:
        cs = ChampionStat(user_id=user_id, champion=champion, played=0, wins=0, streaks_broken=0)
        db.add(cs)
        db.commit()
        db.refresh(cs)
    return cs

# -------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------
class UpsertUserIn(BaseModel):
    name: str

class QueueEnterIn(BaseModel):
    user_id: str

class MatchCreateIn(BaseModel):
    user_ids: List[str]

class DraftPickIn(BaseModel):
    match_id: str
    user_id: str
    champion_id: str

class BetPlaceIn(BaseModel):
    match_id: str
    user_id: str
    team: int

class MatchReportIn(BaseModel):
    match_id: str
    user_id: str
    winner_team: int  # 1 ou 2

class MatchFinalizeIn(BaseModel):
    match_id: str
    winner_team: int

class AdminCancelIn(BaseModel):
    match_key: str  # aceita id (uuid) ou display_id

class AdminOverrideIn(BaseModel):
    match_key: str
    winner_team: int

# -------------------------------------------------------------------
# SSE (simples heartbeat)
# -------------------------------------------------------------------
async def sse_event_gen():
    while True:
        payload = json.dumps({"t": datetime.utcnow().isoformat()})
        yield f"data: {payload}\n\n"
        await asyncio.sleep(5)

@app.get("/events")
async def events():
    return StreamingResponse(sse_event_gen(), media_type="text/event-stream")

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

# -------------------------------------------------------------------
# Users
# -------------------------------------------------------------------
@app.post("/users/upsert")
def users_upsert(body: UpsertUserIn, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "invalid_name")
    u = db.execute(select(User).where(User.name == name)).scalar_one_or_none()
    if not u:
        u = User(id=str(uuid.uuid4()), name=name)
        db.add(u)
        db.commit()
        db.refresh(u)
    return {"id": u.id, "name": u.name}

@app.get("/users")
def users_list(db: Session = Depends(get_db)):
    rows = db.execute(select(User)).scalars().all()
    return [{"id": r.id, "name": r.name} for r in rows]

@app.get("/users/{user_id}/profile")
def user_profile(user_id: str, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "user_not_found")
    champs = db.execute(select(ChampionStat).where(ChampionStat.user_id==user_id)).scalars().all()
    return {
        "user": {"id": u.id, "name": u.name},
        "stats": {
            "played": u.played,
            "wins": u.wins,
            "losses": u.losses,
            "current_streak": u.current_streak,
            "max_streak": u.max_streak,
            "streaks_broken": u.streaks_broken,
            "correct_bets": u.correct_bets,
            "score": u.score
        },
        "champions": [
            {"champion": c.champion, "played": c.played, "wins": c.wins, "streaks_broken": c.streaks_broken}
            for c in champs
        ]
    }

# -------------------------------------------------------------------
# Queue
# -------------------------------------------------------------------
@app.get("/queue")
def queue_status(user_id: Optional[str] = None, db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(QueueEntry)).scalar_one()
    queued = False
    if user_id:
        queued = db.execute(select(QueueEntry).where(QueueEntry.user_id==user_id)).scalar_one_or_none() is not None
    return {"count": count, "queued": queued}

@app.get("/queue/members")
def queue_members(db: Session = Depends(get_db)):
    rows = db.execute(select(QueueEntry).order_by(QueueEntry.joined_at)).scalars().all()
    out = []
    for r in rows:
        u = db.execute(select(User).where(User.id == r.user_id)).scalar_one_or_none()
        if u:
            out.append({"user_id": u.id, "name": u.name, "joined_at": r.joined_at})
    return out

def validate_not_in_match_or_queue(db: Session, user_id: str):
    if db.execute(select(QueueEntry).where(QueueEntry.user_id==user_id)).scalar_one_or_none():
        raise HTTPException(400, "already_in_queue")
    if is_user_in_active_match(db, user_id):
        raise HTTPException(400, "already_in_match")

@app.post("/queue/enter")
def queue_enter(body: QueueEnterIn, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.id==body.user_id)).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "user_not_found")
    validate_not_in_match_or_queue(db, body.user_id)
    db.add(QueueEntry(user_id=body.user_id))
    db.commit()

    # checa se temos 6
    rows = db.execute(select(QueueEntry).order_by(QueueEntry.joined_at)).scalars().all()
    if len(rows) >= 6:
        six = rows[:6]
        ids = [r.user_id for r in six]
        for r in six:
            db.delete(r)
        db.commit()
        match = create_match_internal(db, ids)
        return {"ok": True, "match_id": match.id}
    return {"ok": True}

@app.post("/queue/leave")
def queue_leave(body: QueueEnterIn, db: Session = Depends(get_db)):
    row = db.execute(select(QueueEntry).where(QueueEntry.user_id==body.user_id)).scalar_one_or_none()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}

# -------------------------------------------------------------------
# Matches
# -------------------------------------------------------------------
def create_match_internal(db: Session, user_ids: List[str]) -> Match:
    if len(user_ids) != 6:
        raise HTTPException(400, "need_6_players")
    for uid in user_ids:
        if is_user_in_active_match(db, uid):
            raise HTTPException(400, f"user_in_other_match:{uid}")

    random.shuffle(user_ids)
    t1 = user_ids[:3]
    t2 = user_ids[3:]

    m = Match(
        id=str(uuid.uuid4()),
        display_id=next_display_id(db),
        map=pick_random_map(db),
        status="draft",
        started_at=None,
        bet_deadline=None,
        draft_round=0,
        finished_at=None,
        team1=jdumps(t1),
        team2=jdumps(t2),
        picks=jdumps({}),
        streaked_player_ids=jdumps([]),
        result_deltas=jdumps({}),
    )

    # marca quem estava streakado na criação (para histórico simples)
    streaked = []
    for uid in user_ids:
        u = db.execute(select(User).where(User.id==uid)).scalar_one_or_none()
        if u and u.current_streak >= 3:
            streaked.append(uid)
    m.streaked_player_ids = jdumps(streaked)

    db.add(m)
    db.commit()
    db.refresh(m)
    return m

@app.get("/matches")
def matches_list(db: Session = Depends(get_db)):
    rows = db.execute(select(Match).order_by(Match.started_at.desc().nullslast(), Match.id.desc())).scalars().all()
    out = []
    for m in rows:
        out.append({
            "id": m.id,
            "display_id": m.display_id,
            "map": m.map,
            "status": m.status,
            "started_at": m.started_at,
            "finished_at": m.finished_at,
            "bet_deadline": m.bet_deadline,
            "draft_round": m.draft_round,
            "team1": jloads(m.team1) or [],
            "team2": jloads(m.team2) or [],
            "picks": jloads(m.picks) or {},
            "winner_team": m.winner_team,
            "streaked_player_ids": jloads(m.streaked_player_ids) or [],
            "t1_report": m.t1_report,
            "t2_report": m.t2_report,
        })
    return out

@app.get("/match/{match_id}")
def match_get(match_id: str, db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    return {
        "id": m.id,
        "display_id": m.display_id,
        "map": m.map,
        "status": m.status,
        "started_at": m.started_at,
        "finished_at": m.finished_at,
        "bet_deadline": m.bet_deadline,
        "draft_round": m.draft_round,
        "team1": jloads(m.team1) or [],
        "team2": jloads(m.team2) or [],
        "picks": jloads(m.picks) or {},
        "winner_team": m.winner_team,
        "streaked_player_ids": jloads(m.streaked_player_ids) or [],
        "t1_report": m.t1_report,
        "t2_report": m.t2_report,
    }

@app.post("/match/create")
def match_create(body: MatchCreateIn, token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    return match_get(create_match_internal(db, body.user_ids).id, db)

# -------------------------------------------------------------------
# Finalização com consenso (2 reportes)
# -------------------------------------------------------------------
@app.post("/match/finalize")
def match_finalize(body: MatchReportIn, db: Session = Depends(get_db)):
    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    if m.status not in ("in_progress","finished"):
        raise HTTPException(400, "invalid_status")

    if body.winner_team not in (1,2):
        raise HTTPException(422, "invalid_winner_team")

    t1 = jloads(m.team1) or []
    t2 = jloads(m.team2) or []

    # precisa ser jogador da partida
    is_t1 = body.user_id in t1
    is_t2 = body.user_id in t2
    if not (is_t1 or is_t2):
        raise HTTPException(403, "not_in_match")

    # registra reporte do lado correspondente
    if is_t1:
        m.t1_report = body.winner_team
        m.t1_reporter = body.user_id
    if is_t2:
        m.t2_report = body.winner_team
        m.t2_reporter = body.user_id

    db.commit()
    db.refresh(m)

    # Se já há os dois reportes:
    if m.t1_report and m.t2_report:
        if m.t1_report == m.t2_report:
            # consenso -> finaliza de fato
            return _apply_finalize_and_snapshot(MatchFinalizeIn(match_id=m.id, winner_team=m.t1_report), db)
        else:
            # conflito -> informa e pede novo reporte
            return JSONResponse(
                status_code=409,
                content={
                    "status": "mismatch",
                    "message": "Resultados reportados não batem. Reportem novamente.",
                    "t1_report": m.t1_report,
                    "t2_report": m.t2_report,
                    "t1_reporter": m.t1_reporter,
                    "t2_reporter": m.t2_reporter
                }
            )

    # ainda falta um lado reportar
    return {
        "status": "pending",
        "waiting": "team1" if not m.t1_report else "team2",
        "t1_report": m.t1_report,
        "t2_report": m.t2_report,
        "t1_reporter": m.t1_reporter,
        "t2_reporter": m.t2_reporter
    }

# -------------------------------------------------------------------
# Regras de draft
# -------------------------------------------------------------------
def try_advance_round_or_start(m: Match):
    t1 = jloads(m.team1) or []
    t2 = jloads(m.team2) or []
    picks = jloads(m.picks) or {}
    r = m.draft_round

    # avança quando ambos do par escolherem
    if r < 3:
        u1 = t1[r] if r < len(t1) else None
        u2 = t2[r] if r < len(t2) else None
        if u1 and u2 and (picks.get(u1) and picks.get(u2)):
            m.draft_round = r + 1

    # se terminou as 3 rodadas, inicia partida e abre bets
    if m.draft_round >= 3 and m.status == "draft":
        m.status = "in_progress"
        m.started_at = now()
        m.bet_deadline = now() + timedelta(minutes=10)

@app.post("/draft/pick")
def draft_pick(body: DraftPickIn, db: Session = Depends(get_db)):
    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    if m.status != "draft":
        raise HTTPException(400, "not_in_draft")

    t1 = jloads(m.team1) or []
    t2 = jloads(m.team2) or []
    if body.user_id not in t1 and body.user_id not in t2:
        raise HTTPException(403, "not_in_match")

    # valida turno do jogador (somente sua rodada)
    r = m.draft_round
    idx = (t1.index(body.user_id) if body.user_id in t1 else t2.index(body.user_id) if body.user_id in t2 else -1)
    if idx != r:
        raise HTTPException(403, "not_your_turn")

    # valida campeão permitido
    if not champ_is_allowed(db, body.champion_id):
        raise HTTPException(422, "champ_not_allowed")

    # valida não repetir campeão dentro do mesmo time
    picks = jloads(m.picks) or {}
    team = t1 if body.user_id in t1 else t2
    already_in_team = {picks.get(uid) for uid in team if picks.get(uid)}
    if body.champion_id in already_in_team:
        raise HTTPException(422, "champ_already_picked_in_team")

    # salva pick
    picks[body.user_id] = body.champion_id
    m.picks = jdumps(picks)

    try_advance_round_or_start(m)
    db.commit()
    return {"ok": True, "draft_round": m.draft_round, "status": m.status}

@app.post("/draft/auto_current")
def draft_auto_current(match_id: str = Query(...), token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    # Apenas admin
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")

    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    if m.status != "draft":
        return {"ok": True, "status": m.status}

    allowed = jloads(ensure_admin_config(db).active_champions) or []
    t1 = jloads(m.team1) or []
    t2 = jloads(m.team2) or []
    picks = jloads(m.picks) or {}

    r = m.draft_round
    for team in (t1, t2):
        if r < len(team):
            uid = team[r]
            if not picks.get(uid):
                team_picks = {picks.get(x) for x in team if picks.get(x)}
                choices = [c for c in allowed if c not in team_picks] or allowed
                picks[uid] = random.choice(choices)

    m.picks = jdumps(picks)
    try_advance_round_or_start(m)
    db.commit()
    return {"ok": True, "draft_round": m.draft_round, "status": m.status}

# -------------------------------------------------------------------
# Apostas
# -------------------------------------------------------------------
@app.post("/bets/place")
def bets_place(body: BetPlaceIn, db: Session = Depends(get_db)):
    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    if m.status != "in_progress":
        raise HTTPException(400, "bet_not_open")
    if not m.bet_deadline or now() > m.bet_deadline:
        raise HTTPException(400, "bet_closed")
    if body.team not in (1,2):
        raise HTTPException(422, "invalid_team")

    exist = db.execute(
        select(Bet).where(Bet.match_id==m.id, Bet.user_id==body.user_id)
    ).scalar_one_or_none()
    if exist:
        raise HTTPException(400, "bet_already_placed")

    b = Bet(id=str(uuid.uuid4()), match_id=m.id, user_id=body.user_id, team=body.team)
    db.add(b)
    db.commit()
    return {"ok": True}

@app.get("/bets/count")
def bets_count(match_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(Bet).where(Bet.match_id==match_id)).scalars().all()
    team1 = sum(1 for r in rows if r.team==1)
    team2 = sum(1 for r in rows if r.team==2)
    return {"team1": team1, "team2": team2}

# -------------------------------------------------------------------
# Leaderboard
# -------------------------------------------------------------------
@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    rows = db.execute(select(User).order_by(User.score.desc(), User.wins.desc(), User.name.asc())).scalars().all()
    out = []
    for u in rows:
        out.append({
            "user_id": u.id,
            "name": u.name,
            "score": round(u.score, 4),
            "wins": u.wins,
            "losses": u.losses,
            "played": u.played
        })
    return out

@app.get("/leaderboard/champions")
def leaderboard_champions(db: Session = Depends(get_db)):
    rows = db.execute(select(ChampionStat)).scalars().all()
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        c = r.champion
        if c not in agg:
            agg[c] = {"played":0, "wins":0, "users":{}}
        agg[c]["played"] += r.played or 0
        agg[c]["wins"] += r.wins or 0
        agg[c]["users"][r.user_id] = (agg[c]["users"].get(r.user_id, 0) + (r.played or 0))
    out = []
    for champ, data in agg.items():
        users_sorted = sorted(data["users"].items(), key=lambda kv: kv[1], reverse=True)[:3]
        top3 = []
        for uid, cnt in users_sorted:
            u = db.get(User, uid)
            top3.append({"user_id": uid, "name": u.name if u else uid, "played": cnt})
        winrate = (data["wins"]/data["played"]*100) if data["played"] else 0.0
        out.append({
            "champion": champ,
            "played": data["played"],
            "wins": data["wins"],
            "winrate": round(winrate,1),
            "top_users": top3
        })
    out.sort(key=lambda x: x["played"], reverse=True)
    return out

# -------------------------------------------------------------------
# Finalização (aplica + snapshot) e Admin (cancel/override)
# -------------------------------------------------------------------
def _compute_streak_bonus_per_winner(db: Session, winners: List[str], losers: List[str]) -> float:
    """
    Nova regra: cada vencedor recebe o bônus CHEIO (não dividido).
    Se houver vários perdedores com streak, seus bônus somam e
    CADA vencedor recebe a soma.
    """
    cfg = ensure_admin_config(db)
    streak_bonus = jloads(cfg.streak_bonus) or {"3":0.25,"6":0.5,"9":1.0}
    thresholds = sorted([int(k) for k in streak_bonus.keys()])
    total = 0.0
    for uid in losers:
        u = db.get(User, uid)
        if not u:
            continue
        b = 0.0
        for th in thresholds:
            if u.current_streak >= th:
                b += float(streak_bonus[str(th)])
        total += b
    return total  # aplicado integralmente a CADA vencedor

def _apply_finalize_and_snapshot(body: MatchFinalizeIn, db: Session):
    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    if m.status == "finished":
        return {"ok": True}

    if body.winner_team not in (1,2):
        raise HTTPException(422, "invalid_winner_team")

    t1 = jloads(m.team1) or []
    t2 = jloads(m.team2) or []
    picks = jloads(m.picks) or {}

    cfg = ensure_admin_config(db)
    points_win = float(cfg.points_win)
    points_loss = float(cfg.points_loss)

    winners = t1 if body.winner_team==1 else t2
    losers  = t2 if body.winner_team==1 else t1

    # bônus (nova regra)
    bonus_for_each_winner = _compute_streak_bonus_per_winner(db, winners, losers)

    # snapshot de deltas
    deltas = {
        "users": {},               # uid -> {score_delta, wins_delta, losses_delta, played_delta, streak_old, streak_new, correct_bets_delta}
        "champions": [],           # {user_id, champion, played_delta, wins_delta, streaks_broken_delta}
        "bets": {}                 # uid -> correct_bets_delta
    }

    # streaks quebradas (contagem de adversários streakados)
    broken_count_by_winner: Dict[str,int] = {uid:0 for uid in winners}
    # Um jogador perdedor conta como "streakado" se current_streak >=3 no momento da finalização
    for uid in losers:
        u = db.get(User, uid)
        if u and u.current_streak >= 3:
            for w in winners:
                broken_count_by_winner[w] += 1

    # winners
    for uid in winners:
        u = db.get(User, uid)
        if not u: 
            continue
        before_streak = u.current_streak
        u.wins += 1
        u.played += 1
        u.current_streak += 1
        u.max_streak = max(u.max_streak, u.current_streak)
        u.score += points_win + bonus_for_each_winner

        deltas["users"][uid] = {
            "score_delta":  points_win + bonus_for_each_winner,
            "wins_delta":   1,
            "losses_delta": 0,
            "played_delta": 1,
            "streak_old":   before_streak,
            "streak_new":   u.current_streak,
            "correct_bets_delta": 0
        }

        champ = picks.get(uid)
        if champ:
            cs = get_or_create_champ_stat(db, uid, champ)
            cs.played += 1
            cs.wins += 1
            inc_broken = broken_count_by_winner.get(uid, 0)
            cs.streaks_broken += inc_broken
            deltas["champions"].append({
                "user_id": uid, "champion": champ,
                "played_delta": 1, "wins_delta": 1, "streaks_broken_delta": inc_broken
            })
        u.streaks_broken += broken_count_by_winner.get(uid, 0)

    # losers
    for uid in losers:
        u = db.get(User, uid)
        if not u:
            continue
        before_streak = u.current_streak
        u.losses += 1
        u.played += 1
        u.score += points_loss
        u.current_streak = 0

        deltas["users"][uid] = {
            "score_delta":  points_loss,
            "wins_delta":   0,
            "losses_delta": 1,
            "played_delta": 1,
            "streak_old":   before_streak,
            "streak_new":   0,
            "correct_bets_delta": 0
        }

        champ = picks.get(uid)
        if champ:
            cs = get_or_create_champ_stat(db, uid, champ)
            cs.played += 1
            deltas["champions"].append({
                "user_id": uid, "champion": champ,
                "played_delta": 1, "wins_delta": 0, "streaks_broken_delta": 0
            })

    # bets
    bets = db.execute(select(Bet).where(Bet.match_id==m.id)).scalars().all()
    for b in bets:
        if b.team == body.winner_team:
            u = db.get(User, b.user_id)
            if u:
                u.correct_bets += 1
                if b.user_id not in deltas["users"]:
                    deltas["users"][b.user_id] = {
                        "score_delta":0,"wins_delta":0,"losses_delta":0,
                        "played_delta":0,"streak_old":u.current_streak,"streak_new":u.current_streak,
                        "correct_bets_delta": 1
                    }
                else:
                    deltas["users"][b.user_id]["correct_bets_delta"] += 1

    m.status = "finished"
    m.winner_team = body.winner_team
    m.finished_at = now()
    m.result_deltas = jdumps(deltas)
    db.commit()
    return {"ok": True}

def _revert_snapshot(m: Match, db: Session):
    deltas = jloads(m.result_deltas) or {}
    users = deltas.get("users", {})
    champs = deltas.get("champions", [])
    # Reverte users
    for uid, d in users.items():
        u = db.get(User, uid)
        if not u: 
            continue
        u.score -= float(d.get("score_delta",0))
        u.wins  -= int(d.get("wins_delta",0))
        u.losses-= int(d.get("losses_delta",0))
        u.played-= int(d.get("played_delta",0))
        # restaura streak para o valor anterior
        if "streak_old" in d:
            u.current_streak = int(d["streak_old"])
        # max_streak não temos como diminuir sem histórico — manter
        # bets corretas
        cb = int(d.get("correct_bets_delta",0))
        if cb:
            u.correct_bets = max(0, u.correct_bets - cb)
    # Reverte champion stats
    for c in champs:
        cs = get_or_create_champ_stat(db, c["user_id"], c["champion"])
        cs.played = max(0, cs.played - int(c.get("played_delta",0)))
        cs.wins   = max(0, cs.wins   - int(c.get("wins_delta",0)))
        cs.streaks_broken = max(0, cs.streaks_broken - int(c.get("streaks_broken_delta",0)))

    # limpa marcações finais
    m.winner_team = None
    m.finished_at = None
    m.result_deltas = jdumps({})
    # mantém picks/teams/relatos
    db.commit()

def _find_match_by_key(db: Session, key: str) -> Match:
    # tenta por id
    m = db.get(Match, key)
    if m:
        return m
    # tenta por display_id
    m = db.execute(select(Match).where(Match.display_id==key)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "match_not_found")
    return m

# Admin: cancelar partida (reverte se estava finalizada)
@app.post("/admin/match/cancel")
def admin_match_cancel(payload: AdminCancelIn, token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    m = _find_match_by_key(db, payload.match_key)
    if m.status == "finished":
        _revert_snapshot(m, db)
    m.status = "canceled"
    db.commit()
    return {"ok": True}

# Admin: override de resultado (reverte e aplica novo)
@app.post("/admin/match/override_result")
def admin_match_override(payload: AdminOverrideIn, token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    m = _find_match_by_key(db, payload.match_key)
    if m.status == "finished":
        _revert_snapshot(m, db)
        m.status = "in_progress"  # reabre para poder aplicar novo finalize
        db.commit()
    return _apply_finalize_and_snapshot(MatchFinalizeIn(match_id=m.id, winner_team=payload.winner_team), db)

# -------------------------------------------------------------------
# Admin config e seed
# -------------------------------------------------------------------
class AdminConfigIn(BaseModel):
    points: Dict[str, float]
    streak_bonus: Dict[str, float]
    active_maps: List[str]
    active_champions: List[str]

@app.get("/admin/config")
def admin_get_config(token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    cfg = ensure_admin_config(db)
    return {
        "points": {"win": cfg.points_win, "loss": cfg.points_loss},
        "streak_bonus": jloads(cfg.streak_bonus) or {"3":0.25,"6":0.5,"9":1.0},
        "active_maps": jloads(cfg.active_maps) or [],
        "active_champions": jloads(cfg.active_champions) or []
    }

@app.post("/admin/config")
def admin_set_config(
    payload: AdminConfigIn,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    cfg = ensure_admin_config(db)
    cfg.points_win = float(payload.points.get("win", 1.0))
    cfg.points_loss = float(payload.points.get("loss", 0.0))
    cfg.streak_bonus = jdumps(payload.streak_bonus or {"3":0.25,"6":0.5,"9":1.0})
    cfg.active_maps = jdumps(payload.active_maps or [])
    cfg.active_champions = jdumps(payload.active_champions or [])
    db.commit()
    return admin_get_config(token=token, db=db)

@app.post("/seed/test-bots")
def seed_bots(token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    names = ["BOT1","BOT2","BOT3","BOT4","BOT5","SMOKE"]
    for n in names:
        u = db.execute(select(User).where(User.name==n)).scalar_one_or_none()
        if not u:
            u = User(id=str(uuid.uuid4()), name=n)
            db.add(u)
    db.commit()
    return {"ok": True, "created": names}

# -------------------------------------------------------------------
# Inicialização de config default
# -------------------------------------------------------------------
with SessionLocal() as db:
    ensure_admin_config(db)

# -------------------------------------------------------------------
# Exec local (opcional)
# -------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8330"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
