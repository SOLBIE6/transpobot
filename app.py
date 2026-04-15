from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 🔥 IMPORTS ROUTES
from api.chat import router as chat_router
from api.vehicules import router as vehicules_router
from api.chauffeurs import router as chauffeurs_router
from api.trajets import router as trajets_router
from api.stats import router as stats_router
from api.incidents import router as incidents_router  # 👈 AJOUT

app = FastAPI(title="TranspoBot API", version="1.0.0")

app.mount("/static", StaticFiles(directory="."), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 ROUTES API
app.include_router(chat_router, prefix="/api")
app.include_router(vehicules_router, prefix="/api")
app.include_router(chauffeurs_router, prefix="/api")
app.include_router(trajets_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(incidents_router, prefix="/api")  # 👈 AJOUT

@app.get("/health")
def health():
    return {"status": "ok"}