# Inhouse BR v2 - FastAPI backend (FINAL)
# Run local: uvicorn app:app --host 0.0.0.0 --port 8330
# ENV:
#   DATABASE_URL=postgresql://user:pass@host:5432/dbname  (pode usar sqlite:///inhouse.db)
#   CORS_ALLOW_ORIGINS=https://inhouse-br.vercel.app
#   ADMIN_TOKEN=seu_token_admin_opcional

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Literal
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, UniqueConstraint, Float, text
from sqlalchemy.orm import declarative_base, Session, sessionmaker
from starlette.responses import StreamingResponse
import os, uuid, random, json as _json, asyncio
import logging

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///inhouse.db")
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

# ---------- Models ----------
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Match(Base):
    __tablename__ = "matches"
    id = Column(String, primary_key=True)
    map = Column(String)
    status = Column(String, index=True)  # draft, in_progress, finished
    started_at = Column(DateTime, nullable=True)
    bet_deadline = Column(DateTime, nullable=True)
    draft_round = Column(Integer, default=0)  # 0..2

class DraftOrder(Base):
    __tablename__ = "draft_order"
    id = Column(String, primary_key=True)
    match_id = Column(String, ForeignKey("matches.id"), index=True)
    round = Column(Integer)  # 0,1,2
    t1_user_id = Column(String, ForeignKey("users.id"))
    t2_user_id = Column(String, ForeignKey("users.id"))
    UniqueConstraint("match_id","round")

class MatchPlayer(Base):
    __tablename__ = "match_players"
    id = Column(String, primary_key=True)
    match_id = Column(String, ForeignKey("matches.id"), index=True)
    user_id = Column(String, ForeignKey("users.id"))
    team = Column(Integer)  # 1 ou 2
    champion_id = Column(String, nullable=True)  # champion "name"
    UniqueConstraint("match_id","user_id")

class Bet(Base):
    __tablename__ = "bets"
    id = Column(String, primary_key=True)
    match_id = Column(String, ForeignKey("matches.id"), index=True)
    user_id = Column(String, ForeignKey("users.id"))
    team = Column(Integer)
    placed_at = Column(DateTime, default=datetime.utcnow)
    UniqueConstraint("match_id","user_id")

class PlayerStats(Base):
    __tablename__ = "player_stats"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), unique=True)
    played = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    current_streak = Column(Integer, default=0)
    max_streak = Column(Integer, default=0)
    streaks_broken = Column(Integer, default=0)
    correct_bets = Column(Integer, default=0)
    score = Column(Float, default=0.0)   # <-- era Integer

class PlayerChampStats(Base):
    __tablename__ = "player_champ_stats"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    champion = Column(String)
    played = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    streaks_broken = Column(Integer, default=0)
    UniqueConstraint("user_id","champion")

class QueueEntry(Base):
    __tablename__ = "queue"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)  # "config"
    value = Column(String)  # JSON string

Base.metadata.create_all(engine)

# --- Migração: garantir player_stats.score em FLOAT (Postgres) ---
try:
    url = DATABASE_URL.lower()
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        with engine.begin() as conn:
            # verifica o tipo atual
            cur = conn.execute(text("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name='player_stats' AND column_name='score'
            """))
            row = cur.fetchone()
            if row and row[0] not in ('double precision', 'real', 'numeric'):
                # faz cast seguro para double precision
                conn.execute(text("""
                    ALTER TABLE player_stats
                    ALTER COLUMN score TYPE double precision
                    USING score::double precision
                """))
except Exception:
    # se já está no tipo correto, ou em SQLite, ou qualquer falha inofensiva: seguir
    pass
    
CHAMPIONS = [
  "Ashka","Bakko","Blossom","Croak","Destiny","Ezmo","Freya","Iva","Jade","Jamila",
  "Jumong","Lucie","Oldur","Pestilus","Poloma","Raigon","Rook","Ruh Kaan","Shifu","Sirius",
  "Taya","Thorn","Ulric","Varesh","Zander"
]
MAPS = [
  "Mount Araz Day","Mount Araz Night","Orman Night",
  "Blackstone Day","Blackstone Night","Dragon Garden Day","Dragon Garden Night","Meriko Night"
]
STREAK_BONUS = {3: 0.25, 6: 0.5, 9: 1.0}

DEFAULT_CONFIG = {
    "points": {"win": 1, "loss": 0},
    "streak_bonus": {"3": 0.25, "6": 0.5, "9": 1.0},
    "maps": MAPS,
    "active_maps": MAPS,
    "champions": CHAMPIONS,
    "active_champions": CHAMPIONS
}

app = FastAPI(title="Inhouse BR v2 API")
# CORS
origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in origins_env.split(",")] if origins_env else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
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

# ---------- Schemas ----------
class UserOut(BaseModel):
    id: str; name: str
    class Config: orm_mode = True

class UpsertUserIn(BaseModel):
    name: str

class SeedBotsOut(BaseModel):
    created: int; total: int

class CreateMatchIn(BaseModel):
    user_ids: List[str]

class PickIn(BaseModel):
    match_id: str; user_id: str; champion_id: str

class FinalizeIn(BaseModel):
    match_id: str; winner_team: Literal[1,2]

class BetIn(BaseModel):
    match_id: str; team: Literal[1,2]; user_id: str

class MatchOut(BaseModel):
    id: str; map: str; status: str
    started_at: Optional[datetime]; bet_deadline: Optional[datetime]
    draft_round: int
    team1: List[str]; team2: List[str]
    picks: Dict[str, Optional[str]]
    class Config: orm_mode = True

# ---------- SSE Broadcaster ----------
SUBSCRIBERS: set[asyncio.Queue] = set()

async def broadcast(evt: dict):
    dead = []
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(evt)
        except Exception:
            dead.append(q)
    for q in dead:
        try: SUBSCRIBERS.remove(q)
        except KeyError: pass

@app.get("/events")
async def events():
    q: asyncio.Queue = asyncio.Queue()
    SUBSCRIBERS.add(q)
    async def gen():
        try:
            while True:
                data = await q.get()
                yield f"data: {_json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try: SUBSCRIBERS.remove(q)
            except KeyError: pass
    return StreamingResponse(gen(), media_type="text/event-stream")

# ---------- Helpers ----------
BOT_NAMES = ["BOT1","BOT2","BOT3","BOT4","BOT5"]
def ensure_stats(db: Session, user_id: str):
    st = db.query(PlayerStats).filter_by(user_id=user_id).first()
    if not st:
        db.add(PlayerStats(id=str(uuid.uuid4()), user_id=user_id))

def _match_out(db: Session, match_id: str) -> MatchOut:
    m = db.query(Match).get(match_id)
    if not m: raise HTTPException(404, "match_not_found")
    players = db.query(MatchPlayer).filter_by(match_id=m.id).all()
    team1 = [p.user_id for p in players if p.team==1]
    team2 = [p.user_id for p in players if p.team==2]
    picks = {p.user_id: p.champion_id for p in players}
    return MatchOut(id=m.id, map=m.map, status=m.status, started_at=m.started_at,
                    bet_deadline=m.bet_deadline, draft_round=m.draft_round,
                    team1=team1, team2=team2, picks=picks)

def _load_config(db: Session):
    row = db.query(Setting).get("config")
    if not row:
        row = Setting(key="config", value=_json.dumps(DEFAULT_CONFIG))
        db.add(row); db.commit(); db.refresh(row)
    try:
        return _json.loads(row.value or "{}")
    except Exception:
        return DEFAULT_CONFIG

def _save_config(db: Session, cfg: dict):
    row = db.query(Setting).get("config")
    if not row:
        row = Setting(key="config", value=_json.dumps(cfg))
        db.add(row)
    else:
        row.value = _json.dumps(cfg)
    db.commit(); db.refresh(row)
    return cfg

def _require_admin_token():
    return os.getenv("ADMIN_TOKEN", "")

# ---------- Health ----------
@app.get("/health")
def health():
    return {"ok": True}

# ---------- Users ----------
@app.get("/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.asc()).all()

@app.post("/users/upsert", response_model=UserOut)
def upsert_user(data: UpsertUserIn, db: Session = Depends(get_db)):
    name = data.name.strip()
    if not (2 <= len(name) <= 32):
        raise HTTPException(400, "invalid_name")
    u = db.query(User).filter_by(name=name).first()
    if not u:
        u = User(id=str(uuid.uuid4()), name=name)
        db.add(u)
        ensure_stats(db, u.id)
        db.commit()
    db.refresh(u)
    return u

# ---------- Seed bots ----------
@app.post("/seed/test-bots", response_model=SeedBotsOut)
def seed_bots(db: Session = Depends(get_db)):
    created = 0
    for name in BOT_NAMES:
        u = db.query(User).filter_by(name=name).first()
        if not u:
            u = User(id=str(uuid.uuid4()), name=name)
            db.add(u)
            created += 1
            ensure_stats(db, u.id)
    db.commit()
    total = db.query(User).count()
    return SeedBotsOut(created=created, total=total)

# ---------- Matches ----------
class CreateMatchOut(MatchOut): pass

@app.post("/match/create", response_model=CreateMatchOut)
def match_create(data: CreateMatchIn, db: Session = Depends(get_db)):
    cfg = _load_config(db)
    active_maps = cfg.get("active_maps") or MAPS
    if len(data.user_ids) != 6:
        raise HTTPException(400, "need_6_players")
    users = db.query(User).filter(User.id.in_(data.user_ids)).all()
    if len(users) != 6:
        raise HTTPException(404, "some_users_not_found")
    # impedir usuário em match ativo (draft/in_progress)
    conflicts = (
        db.query(MatchPlayer, Match)
        .join(Match, MatchPlayer.match_id == Match.id)
        .filter(MatchPlayer.user_id.in_(data.user_ids), Match.status.in_(["draft","in_progress"]))
        .all()
    )
    if conflicts:
        user_ids_conflict = {mp.user_id for (mp, m) in conflicts}
        names = [u.name for u in users if u.id in user_ids_conflict]
        raise HTTPException(400, f"user_already_in_active_match: {', '.join(names)}")

    shuffled = data.user_ids[:]
    random.shuffle(shuffled)
    team1 = shuffled[:3]
    team2 = shuffled[3:6]

    m = Match(id=str(uuid.uuid4()), map=random.choice(active_maps), status="draft", draft_round=0)
    db.add(m); db.flush()

    for uid in team1:
        db.add(MatchPlayer(id=str(uuid.uuid4()), match_id=m.id, user_id=uid, team=1))
        ensure_stats(db, uid)
    for uid in team2:
        db.add(MatchPlayer(id=str(uuid.uuid4()), match_id=m.id, user_id=uid, team=2))
        ensure_stats(db, uid)

    for i in range(3):
        db.add(DraftOrder(id=str(uuid.uuid4()), match_id=m.id, round=i, t1_user_id=team1[i], t2_user_id=team2[i]))

    db.commit(); db.refresh(m)
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'match_created','match_id': m.id}))
    except Exception:
        pass
    return _match_out(db, m.id)

@app.get("/matches", response_model=List[MatchOut])
def list_matches(status: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Match)
    if status:
        q = q.filter_by(status=status)
    matches = q.order_by(Match.started_at.desc().nulls_last()).all()
    return [_match_out(db, m.id) for m in matches]

@app.get("/match/{match_id}", response_model=MatchOut)
def get_match(match_id: str, db: Session = Depends(get_db)):
    return _match_out(db, match_id)

# ---------- Draft ----------
@app.post("/draft/pick")
def draft_pick(data: PickIn, db: Session = Depends(get_db)):
    m = db.query(Match).get(data.match_id)
    if not m: raise HTTPException(404, "match_not_found")
    if m.status != "draft": raise HTTPException(400, "not_in_draft")

    mp = db.query(MatchPlayer).filter_by(match_id=m.id, user_id=data.user_id).first()
    if not mp: raise HTTPException(404, "user_not_in_match")

    order = db.query(DraftOrder).filter_by(match_id=m.id, round=m.draft_round).first()
    if not order: raise HTTPException(400, "invalid_round")
    if data.user_id not in (order.t1_user_id, order.t2_user_id):
        raise HTTPException(400, "not_your_turn")

    cfg = _load_config(db)
    active_champions = cfg.get("active_champions") or CHAMPIONS
    if data.champion_id not in active_champions:
        raise HTTPException(400, "invalid_champion")
    repeated = db.query(MatchPlayer).filter_by(match_id=m.id, team=mp.team, champion_id=data.champion_id).first()
    if repeated: raise HTTPException(400, "champion_already_used_in_team")

    mp.champion_id = data.champion_id
    db.add(mp); db.flush()

    other_uid = order.t1_user_id if data.user_id == order.t2_user_id else order.t2_user_id
    other_mp = db.query(MatchPlayer).filter_by(match_id=m.id, user_id=other_uid).first()
    if other_mp and other_mp.champion_id:
        m.draft_round += 1
        if m.draft_round >= 3:
            m.status = "in_progress"
            m.started_at = datetime.utcnow()
            m.bet_deadline = m.started_at + timedelta(minutes=10)
    db.add(m); db.commit(); db.refresh(m)
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'draft_update','match_id': m.id}))
    except Exception:
        pass
    return _match_out(db, m.id)

@app.post("/draft/auto_current", response_model=MatchOut)
def draft_auto_current(match_id: str, db: Session = Depends(get_db)):
    m = db.query(Match).get(match_id)
    if not m: raise HTTPException(404, "match_not_found")
    if m.status != "draft": raise HTTPException(400, "not_in_draft")
    order = db.query(DraftOrder).filter_by(match_id=m.id, round=m.draft_round).first()
    if not order: raise HTTPException(400, "invalid_round")

    cfg = _load_config(db)
    active_champions = set(cfg.get("active_champions") or CHAMPIONS)

    def available_for(team: int):
        used = {p.champion_id for p in db.query(MatchPlayer).filter_by(match_id=m.id, team=team) if p.champion_id}
        choices = [c for c in active_champions if c not in used]
        random.shuffle(choices)
        return choices

    for uid, team in [(order.t1_user_id, 1), (order.t2_user_id, 2)]:
        mp = db.query(MatchPlayer).filter_by(match_id=m.id, user_id=uid).first()
        if mp and not mp.champion_id:
            opts = available_for(team)
            mp.champion_id = opts[0] if opts else None
            db.add(mp)

    t1 = db.query(MatchPlayer).filter_by(match_id=m.id, user_id=order.t1_user_id).first()
    t2 = db.query(MatchPlayer).filter_by(match_id=m.id, user_id=order.t2_user_id).first()
    if t1 and t1.champion_id and t2 and t2.champion_id:
        m.draft_round += 1
        if m.draft_round >= 3:
            m.status = "in_progress"
            m.started_at = datetime.utcnow()
            m.bet_deadline = m.started_at + timedelta(minutes=10)
    db.add(m); db.commit(); db.refresh(m)
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'draft_update','match_id': m.id}))
    except Exception:
        pass
    return _match_out(db, m.id)

# ---------- Bets ----------
@app.post("/bets/place")
def bets_place(data: BetIn, db: Session = Depends(get_db)):
    m = db.query(Match).get(data.match_id)
    if not m: raise HTTPException(404, "match_not_found")
    if m.status != "in_progress": raise HTTPException(400, "match_not_in_progress")
    if not m.bet_deadline or datetime.utcnow() > m.bet_deadline:
        raise HTTPException(400, "bet_window_closed")
    exists = db.query(Bet).filter_by(match_id=m.id, user_id=data.user_id).first()
    if exists: raise HTTPException(400, "bet_already_placed")
    if data.team not in (1,2): raise HTTPException(400, "invalid_team")
    u = db.query(User).get(data.user_id)
    if not u: raise HTTPException(404, "user_not_found")
    db.add(Bet(id=str(uuid.uuid4()), match_id=m.id, user_id=u.id, team=data.team))
    db.commit()
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'bets_update','match_id': m.id}))
    except Exception:
        pass
    return {"ok": True}

class BetsCountOut(BaseModel):
    team1: int; team2: int

@app.get("/bets/count", response_model=BetsCountOut)
def bets_count(match_id: str = Query(...), db: Session = Depends(get_db)):
    m = db.query(Match).get(match_id)
    if not m: raise HTTPException(404, "match_not_found")
    t1 = db.query(Bet).filter_by(match_id=match_id, team=1).count()
    t2 = db.query(Bet).filter_by(match_id=match_id, team=2).count()
    return BetsCountOut(team1=t1, team2=t2)

# ---------- Finalize ----------
logger = logging.getLogger("inhouse")

@app.post("/match/finalize", response_model=MatchOut)
def match_finalize(data: FinalizeIn, db: Session = Depends(get_db)):
    try:
        m = db.query(Match).get(data.match_id)
        if not m:
            raise HTTPException(404, "match_not_found")
        if m.status == "finished":
            return _match_out(db, m.id)
        if data.winner_team not in (1, 2):
            raise HTTPException(400, "invalid_winner_team")

        winners = db.query(MatchPlayer).filter_by(match_id=m.id, team=data.winner_team).all()
        losers  = db.query(MatchPlayer).filter_by(match_id=m.id, team=(1 if data.winner_team==2 else 2)).all()

        # streaks de perdedores (para bônus / streaks_broken)
        loser_streaks = []
        for p in losers:
            st = db.query(PlayerStats).filter_by(user_id=p.user_id).first()
            loser_streaks.append((st.current_streak if st else 0))

        # bônus por maior streak >=3 entre os perdedores
        STREAK_BONUS_LOCAL = {3: 0.25, 6: 0.5, 9: 1.0}
        keys = [k for k in STREAK_BONUS_LOCAL.keys() if any(s >= k for s in loser_streaks)]
        bonus_key = max(keys) if keys else 0
        bonus = float(STREAK_BONUS_LOCAL.get(bonus_key, 0.0))
        opponents_meeting = sum(1 for s in loser_streaks if s >= 3)

        # aplica nos vencedores
        for mp in winners:
            ensure_stats(db, mp.user_id)
            st = db.query(PlayerStats).filter_by(user_id=mp.user_id).first()
            if not st:
                st = PlayerStats(id=str(uuid.uuid4()), user_id=mp.user_id, score=0.0)
                db.add(st)
            st.played = (st.played or 0) + 1
            st.wins = (st.wins or 0) + 1
            st.current_streak = (st.current_streak or 0) + 1
            st.max_streak = max(st.max_streak or 0, st.current_streak)
            st.score = float(st.score or 0.0) + 1.0 + bonus
            st.streaks_broken = (st.streaks_broken or 0) + opponents_meeting
            db.add(st)

            if mp.champion_id:
                pcs = db.query(PlayerChampStats).filter_by(user_id=mp.user_id, champion=mp.champion_id).first()
                if not pcs:
                    pcs = PlayerChampStats(id=str(uuid.uuid4()), user_id=mp.user_id, champion=mp.champion_id,
                                           played=0, wins=0, streaks_broken=0)
                pcs.played = (pcs.played or 0) + 1
                pcs.wins = (pcs.wins or 0) + 1
                pcs.streaks_broken = (pcs.streaks_broken or 0) + opponents_meeting
                db.add(pcs)

        # aplica nos perdedores
        for mp in losers:
            ensure_stats(db, mp.user_id)
            st = db.query(PlayerStats).filter_by(user_id=mp.user_id).first()
            if not st:
                st = PlayerStats(id=str(uuid.uuid4()), user_id=mp.user_id, score=0.0)
                db.add(st)
            st.played = (st.played or 0) + 1
            st.losses = (st.losses or 0) + 1
            st.current_streak = 0
            db.add(st)

            if mp.champion_id:
                pcs = db.query(PlayerChampStats).filter_by(user_id=mp.user_id, champion=mp.champion_id).first()
                if not pcs:
                    pcs = PlayerChampStats(id=str(uuid.uuid4()), user_id=mp.user_id, champion=mp.champion_id,
                                           played=0, wins=0, streaks_broken=0)
                pcs.played = (pcs.played or 0) + 1
                db.add(pcs)

        # apostas corretas (só contam se dentro da janela)
        bets = db.query(Bet).filter_by(match_id=m.id).all()
        for b in bets:
            if (not m.bet_deadline) or (b.placed_at is None):
                continue
            if b.placed_at <= m.bet_deadline and b.team == data.winner_team:
                ensure_stats(db, b.user_id)
                st = db.query(PlayerStats).filter_by(user_id=b.user_id).first()
                if not st:
                    st = PlayerStats(id=str(uuid.uuid4()), user_id=b.user_id, score=0.0)
                st.correct_bets = (st.correct_bets or 0) + 1
                db.add(st)

        m.status = "finished"
        db.add(m)
        db.commit()
        db.refresh(m)

        # Notificação (não interfere no sucesso)
        try:
            import anyio
            anyio.from_thread.run(asyncio.create_task, broadcast({'type':'match_finalized','match_id': m.id}))
        except Exception:
            pass

        return _match_out(db, m.id)

    except HTTPException:
        raise
    except Exception as e:
        # Log detalhado no Render (Settings > Logs)
        logger.exception("match_finalize failed: %s", e)
        db.rollback()
        raise HTTPException(500, "finalize_failed")

# ---------- Leaderboard & Profile ----------
class LeaderRow(BaseModel):
    user_id: str; name: str; score: float; wins: int; losses: int; played: int

@app.get("/leaderboard", response_model=List[LeaderRow])
def leaderboard(db: Session = Depends(get_db)):
    rows = (
        db.query(User, PlayerStats)
        .join(PlayerStats, PlayerStats.user_id==User.id)
        .order_by(PlayerStats.score.desc(), PlayerStats.wins.desc())
        .all()
    )
    return [
        LeaderRow(user_id=u.id, name=u.name, score=float(s.score), wins=s.wins, losses=s.losses, played=s.played)
        for (u,s) in rows
    ]

class ProfileOut(BaseModel):
    user_id: str; name: str; stats: Dict; champions: List[Dict]

@app.get("/users/{user_id}/profile", response_model=ProfileOut)
def user_profile(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).get(user_id)
    if not u: raise HTTPException(404, "user_not_found")
    s = db.query(PlayerStats).filter_by(user_id=user_id).first()
    champs = db.query(PlayerChampStats).filter_by(user_id=user_id).order_by(PlayerChampStats.played.desc()).all()
    return ProfileOut(
        user_id=u.id,
        name=u.name,
        stats={
            "played": s.played if s else 0,
            "wins": s.wins if s else 0,
            "losses": s.losses if s else 0,
            "current_streak": s.current_streak if s else 0,
            "max_streak": s.max_streak if s else 0,
            "streaks_broken": s.streaks_broken if s else 0,
            "correct_bets": s.correct_bets if s else 0,
            "score": float(s.score) if s else 0.0,
        },
        champions=[{"champion": c.champion, "played": c.played, "wins": c.wins, "streaks_broken": c.streaks_broken} for c in champs]
    )

# ---------- Admin config ----------
class ConfigOut(BaseModel):
    points: dict
    streak_bonus: dict
    maps: List[str]
    active_maps: List[str]
    champions: List[str]
    active_champions: List[str]

@app.get("/admin/config", response_model=ConfigOut)
def get_config(db: Session = Depends(get_db), token: Optional[str] = Query(None)):
    admin_token = _require_admin_token()
    if admin_token and token != admin_token:
        raise HTTPException(403, "forbidden")
    cfg = _load_config(db)
    return cfg

class ConfigIn(BaseModel):
    points: dict
    streak_bonus: dict
    active_maps: List[str]
    active_champions: List[str]

@app.post("/admin/config", response_model=ConfigOut)
def set_config(data: ConfigIn, db: Session = Depends(get_db), token: Optional[str] = Query(None)):
    admin_token = _require_admin_token()
    if admin_token and token != admin_token:
        raise HTTPException(403, "forbidden")
    cfg = _load_config(db)
    cfg["points"] = data.points
    cfg["streak_bonus"] = data.streak_bonus
    cfg["active_maps"] = data.active_maps
    cfg["active_champions"] = data.active_champions
    _save_config(db, cfg)
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'config_update'}))
    except Exception:
        pass
    return cfg

# ---------- Queue ----------
class QueueStatusOut(BaseModel):
    count: int
    queued: bool
    match_id: Optional[str] = None

@app.get("/queue", response_model=QueueStatusOut)
def queue_status(user_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    qcount = db.query(QueueEntry).count()
    queued = False
    if user_id:
        queued = db.query(QueueEntry).filter_by(user_id=user_id).first() is not None
    return QueueStatusOut(count=qcount, queued=queued, match_id=None)

class QueueEnterIn(BaseModel):
    user_id: str

@app.post("/queue/enter", response_model=QueueStatusOut)
def queue_enter(data: QueueEnterIn, db: Session = Depends(get_db)):
    u = db.query(User).get(data.user_id)
    if not u: raise HTTPException(404, "user_not_found")
    # impedir dupla-entrada: se já estiver em draft/partida
    active = db.query(MatchPlayer).join(Match, MatchPlayer.match_id==Match.id).filter(
        MatchPlayer.user_id==u.id, Match.status.in_(["draft","in_progress"])
    ).first()
    if active: raise HTTPException(400, "already_in_active_match_or_draft")
    # impedir duplicado na fila
    exists = db.query(QueueEntry).filter_by(user_id=u.id).first()
    if exists: raise HTTPException(400, "already_in_queue")

    db.add(QueueEntry(id=str(uuid.uuid4()), user_id=u.id)); db.commit()

    # criar partida se houver 6
    entries = db.query(QueueEntry).order_by(QueueEntry.created_at.asc()).all()
    match_id = None
    if len(entries) >= 6:
        picked = entries[:6]
        user_ids = [e.user_id for e in picked]
        for e in picked: db.delete(e)
        db.commit()
        m = match_create(CreateMatchIn(user_ids=user_ids), db=db)
        match_id = m.id

    qcount = db.query(QueueEntry).count()
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'queue_update'}))
    except Exception:
        pass
    return QueueStatusOut(count=qcount, queued=True, match_id=match_id)

class QueueLeaveIn(BaseModel):
    user_id: str

@app.post("/queue/leave", response_model=QueueStatusOut)
def queue_leave(data: QueueLeaveIn, db: Session = Depends(get_db)):
    e = db.query(QueueEntry).filter_by(user_id=data.user_id).first()
    if not e: raise HTTPException(400, "not_in_queue")
    db.delete(e); db.commit()
    qcount = db.query(QueueEntry).count()
    try:
        import anyio
        anyio.from_thread.run(asyncio.create_task, broadcast({'type':'queue_update'}))
    except Exception:
        pass
    return QueueStatusOut(count=qcount, queued=False, match_id=None)

@app.post("/admin/fix_open_matches")
def admin_fix_open(db: Session = Depends(get_db), token: Optional[str] = Query(None)):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if admin_token and token != admin_token:
        raise HTTPException(403, "forbidden")

    fixed = []
    matches = db.query(Match).filter(Match.status.in_(["draft", "in_progress"])).all()
    for m in matches:
        try:
            # completa o draft se ainda estava em draft
            if m.status == "draft":
                for _ in range(max(0, 3 - (m.draft_round or 0))):
                    draft_auto_current(m.id, db)  # usa o endpoint interno
            # finaliza T1
            match_finalize(FinalizeIn(match_id=m.id, winner_team=1), db)
            fixed.append(m.id)
        except Exception:
            db.rollback()
            continue
    return {"fixed": fixed}

 # validação temporária do finalizar partida
@app.post("/__debug/finalize_verbose")
def debug_finalize_verbose(data: FinalizeIn, db: Session = Depends(get_db)):
    try:
        # Chama o finalize “de verdade” reaproveitando a função
        return match_finalize(data, db)
    except HTTPException as he:
        detail = getattr(he, "detail", str(he))
        return {"ok": False, "http": getattr(he, "status_code", 500), "detail": detail}
    except Exception as e:
        import traceback
        db.rollback()
        return {"ok": False, "http": 500, "detail": str(e), "trace": traceback.format_exc()}
