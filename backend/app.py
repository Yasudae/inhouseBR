from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
# (restante do código completo da versão final com fila, draft, apostas, leaderboard, perfil, SSE, admin)
