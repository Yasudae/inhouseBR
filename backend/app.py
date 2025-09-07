from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
# (restante do código completo da versão final com fila, draft, apostas, leaderboard, perfil, SSE, admin)

# adicione este modelo perto dos outros Schemas
class UpsertUserIn(BaseModel):
    name: str

# SUBSTITUA o endpoint atual por este
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
