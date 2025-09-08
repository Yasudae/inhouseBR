# backend/app.py
import os
import json
import uuid
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, Text, Boolean,
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
    status = Column(String, index=True)  # draft, in_progress, finished
    started_at = Column(DateTime, nullable=True)
    bet_deadline = Column(DateTime, nullable=True)
    draft_round = Column(Integer, default=0)  # 0..2
    team1 = JSONCol()
    team2 = JSONCol()
    picks = JSONCol()  # { user_id: champion }
    winner_team = Column(Integer, nullable=True)
    streaked_player_ids = JSONCol()  # lista de ids "streakados" no momento do jogo
    # --- novos campos para reporte de resultado ---
    t1_report = Column(Integer, nullable=True)       # 1 ou 2 (time vencedor reportado por um jogador de T1)
    t2_report = Column(Integer, nullable=True)       # 1 ou 2 (… reportado por alguém de T2)
    t1_reporter = Column(String, nullable=True)      # user_id do repórter de T1
    t2_reporter = Column(String, nullable=True)      # user_id do repórter de T2

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
    # streak bonus thresholds -> value (ex.: {"3":0.25,"6":0.5,"9":1})
    streak_bonus = JSONCol()
    # ativos
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
# migração leve: cria colunas de reporte se não existirem
with engine.begin() as conn:
    try:
        conn.execute(sql_text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS t1_report integer"))
    except Exception: pass
    try:
        conn.execute(sql_text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS t2_report integer"))
    except Exception: pass
    try:
        conn.execute(sql_text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS t1_reporter text"))
    except Exception: pass
    try:
        conn.execute(sql_text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS t2_reporter text"))
    except Exception: pass

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
                "Ashka","Bakko","Blossom","Croak","Destiny","Ezmo","Freya","Iva","Jade","Jamila",
                "Jumong","Lucie","Oldur","Pestilus","Poloma","Raigon","Rook","Ruh Kaan","Shifu","Sirius",
                "Taya","Thorn","Ulric","Varesh","Zander","Alysia","Shen Rao"
            ])
        )
        db.add(cfg)
        db.commit()
    else:
        # garante inclusão de Alysia/Shen Rao em instalações já existentes; remove Pearl se existir
        champs = set(jloads(cfg.active_champions) or [])
        changed = False
        for extra in ["Alysia","Shen Rao"]:
            if extra not in champs:
                champs.add(extra); changed = True
        if "Pearl" in champs:
            champs.remove("Pearl"); changed = True
        if changed:
            cfg.active_champions = jdumps(sorted(champs))
            db.commit()
    return cfg

# -------------------------------------------------------------------
# FastAPI / CORS
# -------------------------------------------------------------------
app = FastAPI(title="Inhouse BR API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    # Itera em Python por causa das diferenças JSON (SQLite/Postgres)
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
    if not maps:
        maps = ["Mount Araz Day"]
    return random.choice(maps)

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

class MatchFinalizeIn(BaseModel):
    match_id: str
    winner_team: int

# -------------------------------------------------------------------
# SSE (simples heartbeat)
# -------------------------------------------------------------------
async def sse_event_gen():
    while True:
        # Simples heartbeat para o frontend fazer refresh
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
        # pega os 6 primeiros
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
    # valida ninguém em outra partida
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
        team1=jdumps(t1),
        team2=jdumps(t2),
        picks=jdumps({}),
        streaked_player_ids=jdumps([]),
    )

    # marca quem estava streakado no momento da criação (para histórico)
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
            "bet_deadline": m.bet_deadline,
            "draft_round": m.draft_round,
            "team1": jloads(m.team1) or [],
            "team2": jloads(m.team2) or [],
            "picks": jloads(m.picks) or {},
            "winner_team": m.winner_team,
            "streaked_player_ids": jloads(m.streaked_player_ids) or [],
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
        "bet_deadline": m.bet_deadline,
        "draft_round": m.draft_round,
        "team1": jloads(m.team1) or [],
        "team2": jloads(m.team2) or [],
        "picks": jloads(m.picks) or {},
        "winner_team": m.winner_team,
        "streaked_player_ids": jloads(m.streaked_player_ids) or [],
    }

@app.post("/match/create")
def match_create(body: MatchCreateIn, token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    return match_get(create_match_internal(db, body.user_ids).id, db)

class MatchReportIn(BaseModel):
    match_id: str
    user_id: str
    winner_team: int  # 1 ou 2

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
            # consenso -> finaliza de fato (reusa lógica antiga)
            finalize_payload = MatchFinalizeIn(match_id=m.id, winner_team=m.t1_report)
            # chama a antiga rotina de fechamento "real"
            return _finalize_apply_and_close(finalize_payload, db)
        else:
            # conflito -> informa times e pede novo reporte
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

def _finalize_apply_and_close(body: MatchFinalizeIn, db: Session):
    # ---- mesma lógica do finalize antigo (atualizado) ----
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
    points_win = cfg.points_win
    points_loss = cfg.points_loss
    streak_bonus = jloads(cfg.streak_bonus) or {"3":0.25,"6":0.5,"9":1.0}

    winners = t1 if body.winner_team==1 else t2
    losers = t2 if body.winner_team==1 else t1

    thresholds = sorted([int(k) for k in streak_bonus.keys()])
    total_bonus = 0.0
    broken_count_by_winner: Dict[str, int] = {uid:0 for uid in winners}

    for uid in losers:
        u = db.get(User, uid)
        if not u: continue
        b = 0.0
        for th in thresholds:
            if u.current_streak >= th:
                b += float(streak_bonus[str(th)])
        if b > 0:
            total_bonus += b
            for w in winners:
                broken_count_by_winner[w] += 1

    bonus_per_winner = total_bonus / len(winners) if winners else 0.0

    for uid in winners:
        u = db.get(User, uid)
        if not u: continue
        u.wins += 1
        u.played += 1
        u.current_streak += 1
        u.max_streak = max(u.max_streak, u.current_streak)
        u.score += float(points_win) + bonus_per_winner
        champ = picks.get(uid)
        if champ:
            cs = get_or_create_champ_stat(db, uid, champ)
            cs.played += 1
            cs.wins += 1
            cs.streaks_broken += broken_count_by_winner.get(uid, 0)
        u.streaks_broken += broken_count_by_winner.get(uid, 0)

    for uid in losers:
        u = db.get(User, uid)
        if not u: continue
        u.losses += 1
        u.played += 1
        u.score += float(points_loss)
        u.current_streak = 0
        champ = picks.get(uid)
        if champ:
            cs = get_or_create_champ_stat(db, uid, champ)
            cs.played += 1

    bets = db.execute(select(Bet).where(Bet.match_id==m.id)).scalars().all()
    for b in bets:
        if b.team == body.winner_team:
            u = db.get(User, b.user_id)
            if u:
                u.correct_bets += 1

    m.status = "finished"
    m.winner_team = body.winner_team
    db.commit()
    return {"ok": True}

# -------------------------------------------------------------------
# Draft
# -------------------------------------------------------------------
def get_user_turn_index(team: List[str], uid: str) -> Optional[int]:
    return team.index(uid) if uid in team else None

def try_advance_round_or_start(m: Match):
    t1 = jloads(m.team1) or []
    t2 = jloads(m.team2) or []
    picks = jloads(m.picks) or {}
    r = m.draft_round

    # se ambos da rodada r escolheram, avança
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

    # valida campeão permitido
    if not champ_is_allowed(db, body.champion_id):
        raise HTTPException(422, "champ_not_allowed")

    # ===== backend reforça: só pode escolher na sua vez =====
    team = t1 if body.user_id in t1 else t2
    my_idx = team.index(body.user_id)
    if my_idx != m.draft_round:
        raise HTTPException(400, "not_your_turn")

    # valida não repetir campeão dentro do mesmo time
    picks = jloads(m.picks) or {}
    already_in_team = {picks.get(uid) for uid in team if picks.get(uid)}
    if body.champion_id in already_in_team:
        raise HTTPException(422, "champ_already_picked_in_team")

    # salva pick
    picks[body.user_id] = body.champion_id
    m.picks = jdumps(picks)

    # Regra de rounds simultâneos:
    # O frontend controla a visibilidade; aqui só avançamos quando o par da rodada está completo.
    try_advance_round_or_start(m)
    db.commit()
    return {"ok": True, "draft_round": m.draft_round, "status": m.status}

@app.post("/draft/auto_current")
def draft_auto_current(match_id: str = Query(...), token: Optional[str] = Query(None), db: Session = Depends(get_db)):
    # admin ou não: pode ser útil em testes — manter aberto
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
                # escolhe aleatório que não esteja no time
                team_picks = {picks.get(x) for x in team if picks.get(x)}
                choices = [c for c in allowed if c not in team_picks] or allowed
                picks[uid] = random.choice(choices)

    m.picks = jdumps(picks)
    try_advance_round_or_start(m)
    db.commit()
    return {"ok": True, "draft_round": m.draft_round, "status": m.status}

# -------------------------------------------------------------------
# Bets
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

    # um bet por usuário por partida
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
    # agrega ChampionStat por campeão
    rows = db.execute(select(ChampionStat)).scalars().all()
    agg: Dict[str, Dict[str, Any]] = {}
    # acumula por campeão
    for r in rows:
        c = r.champion
        if c not in agg:
            agg[c] = {"played":0, "wins":0, "users":{}}
        agg[c]["played"] += r.played or 0
        agg[c]["wins"] += r.wins or 0
        agg[c]["users"][r.user_id] = (agg[c]["users"].get(r.user_id, 0) + (r.played or 0))
    # top 3 usuários por uso
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
    # ordena por jogado desc
    out.sort(key=lambda x: x["played"], reverse=True)
    return out

# -------------------------------------------------------------------
# Admin
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

# ---------- ADMIN: override resultado, cancelar, resets ----------
class AdminOverrideIn(BaseModel):
    match_id: str
    winner_team: int  # 1 ou 2

@app.post("/admin/match/override")
def admin_override_result(
    payload: AdminOverrideIn,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    # aplica finalização direta (ignora pendência de reporte)
    return _finalize_apply_and_close(MatchFinalizeIn(match_id=payload.match_id, winner_team=payload.winner_team), db)

class AdminCancelIn(BaseModel):
    match_id: str

@app.post("/admin/match/cancel")
def admin_cancel_match(
    payload: AdminCancelIn,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    m = db.get(Match, payload.match_id)
    if not m:
        raise HTTPException(404, "match_not_found")
    # cancelar não pontua nada
    m.status = "finished"
    m.winner_team = None
    db.commit()
    return {"ok": True, "status": "canceled"}

@app.post("/admin/reset/users")
def admin_reset_users(
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    # zera scoreboard dos usuários
    db.execute(sql_text("UPDATE users SET score=0, wins=0, losses=0, played=0, current_streak=0, max_streak=0, streaks_broken=0, correct_bets=0"))
    db.commit()
    return {"ok": True}

@app.post("/admin/reset/champions")
def admin_reset_champions(
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")
    # limpa tabela de stats por campeão
    db.execute(sql_text("DELETE FROM champion_stats"))
    db.commit()
    return {"ok": True}

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
