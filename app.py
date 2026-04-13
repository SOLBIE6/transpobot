"""
TranspoBot — Squelette Backend FastAPI
Projet GLSi L3 — ESP/UCAD
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
import os
import re
import httpx
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="TranspoBot API", version="1.0.0")

from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="."), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ──────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "transpobot"),
}

LLM_API_KEY  = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
# ── Schéma de la base (pour le prompt système) ─────────────────
DB_SCHEMA = """
Tables MySQL disponibles :

vehicules(id, immatriculation, type[bus/minibus/taxi], capacite, statut[actif/maintenance/hors_service], kilometrage, date_acquisition)
chauffeurs(id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite, vehicule_id, date_embauche)
lignes(id, code, nom, origine, destination, distance_km, duree_minutes)
tarifs(id, ligne_id, type_client[normal/etudiant/senior], prix)
trajets(id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut[planifie/en_cours/termine/annule], nb_passagers, recette)
incidents(id, trajet_id, type[panne/accident/retard/autre], description, gravite[faible/moyen/grave], date_incident, resolu)
"""

SYSTEM_PROMPT = f"""Tu es TranspoBot, l'assistant IA d'une compagnie de transport urbain au Sénégal.
Tu réponds en français (ou en anglais si l'utilisateur écrit en anglais).

{DB_SCHEMA}

Valeurs exactes des colonnes ENUM :
  vehicules.statut      : 'actif' | 'maintenance' | 'hors_service'
  vehicules.type        : 'bus' | 'minibus' | 'taxi'
  trajets.statut        : 'planifie' | 'en_cours' | 'termine' | 'annule'
  incidents.type        : 'panne' | 'accident' | 'retard' | 'autre'
  incidents.gravite     : 'faible' | 'moyen' | 'grave'
  incidents.resolu      : TRUE | FALSE
  tarifs.type_client    : 'normal' | 'etudiant' | 'senior'
  chauffeurs.disponibilite : TRUE | FALSE

RÈGLES STRICTES :
1. Génère UNIQUEMENT des requêtes SELECT. Jamais INSERT/UPDATE/DELETE/DROP/ALTER.
2. Réponds TOUJOURS en JSON valide avec ce format exact :
   {{"sql": "SELECT ...", "explication": "Réponse en une phrase claire"}}
3. Si pas de SQL nécessaire (salutation, hors sujet) :
   {{"sql": null, "explication": "Ta réponse directe"}}
4. Utilise des alias lisibles : COUNT(*) AS total, c.nom AS chauffeur_nom
5. Toujours ajouter LIMIT 50 maximum
6. Formules de dates :
   - Cette semaine  : date_col >= DATE_SUB(NOW(), INTERVAL 7 DAY)
   - Ce mois        : MONTH(date_col)=MONTH(NOW()) AND YEAR(date_col)=YEAR(NOW())
   - Aujourd'hui    : DATE(date_col) = CURDATE()
7. Pour joindre chauffeur : JOIN chauffeurs c ON t.chauffeur_id = c.id
8. Pour joindre véhicule  : JOIN vehicules v ON t.vehicule_id = v.id

EXEMPLES :
Q: Combien de trajets cette semaine ?
R: {{"sql": "SELECT COUNT(*) AS total FROM trajets WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND statut='termine'", "explication": "Il y a X trajets terminés sur les 7 derniers jours."}}

Q: Quel chauffeur a le plus d'incidents ce mois ?
R: {{"sql": "SELECT c.nom, c.prenom, COUNT(i.id) AS nb_incidents FROM incidents i JOIN trajets t ON i.trajet_id=t.id JOIN chauffeurs c ON t.chauffeur_id=c.id WHERE MONTH(i.date_incident)=MONTH(NOW()) AND YEAR(i.date_incident)=YEAR(NOW()) GROUP BY c.id ORDER BY nb_incidents DESC LIMIT 1", "explication": "Le chauffeur avec le plus d'incidents ce mois."}}

Q: Bonjour !
R: {{"sql": null, "explication": "Bonjour ! Je suis TranspoBot. Posez-moi des questions sur vos véhicules, trajets ou chauffeurs."}}
"""

# ── Connexion MySQL ────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def execute_query(sql: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

# ── Appel LLM ─────────────────────────────────────────────────
async def ask_llm(question: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": question},
                ],
                "temperature": 0,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # Extraire le JSON de la réponse
        import json
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("Réponse LLM invalide")

# ── Routes API ─────────────────────────────────────────────────
class ChatMessage(BaseModel):
    question: str

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    """Point d'entrée principal : question → SQL → résultats"""
    try:
        llm_response = await ask_llm(msg.question)
        sql = llm_response.get("sql")
        explication = llm_response.get("explication", "")

        if not sql:
            return {"answer": explication, "data": [], "sql": None}

        data = execute_query(sql)
        return {
            "answer": explication,
            "data": data,
            "sql": sql,
            "count": len(data),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
def get_stats():
    """Tableau de bord — statistiques rapides"""
    stats = {}
    queries = {
        "total_trajets":    "SELECT COUNT(*) as n FROM trajets WHERE statut='termine'",
        "trajets_en_cours": "SELECT COUNT(*) as n FROM trajets WHERE statut='en_cours'",
        "vehicules_actifs": "SELECT COUNT(*) as n FROM vehicules WHERE statut='actif'",
        "incidents_ouverts":"SELECT COUNT(*) as n FROM incidents WHERE resolu=FALSE",
        "recette_totale":   "SELECT COALESCE(SUM(recette),0) as n FROM trajets WHERE statut='termine'",
    }
    for key, sql in queries.items():
        result = execute_query(sql)
        stats[key] = result[0]["n"] if result else 0
    return stats

@app.get("/api/vehicules")
def get_vehicules():
    return execute_query("SELECT * FROM vehicules ORDER BY immatriculation")

@app.get("/api/chauffeurs")
def get_chauffeurs():
    return execute_query("""
        SELECT c.*, v.immatriculation
        FROM chauffeurs c
        LEFT JOIN vehicules v ON c.vehicule_id = v.id
        ORDER BY c.nom
    """)

@app.get("/api/trajets/recent")
def get_trajets_recent():
    return execute_query("""
        SELECT t.*, l.nom as ligne, ch.nom as chauffeur_nom,
               v.immatriculation
        FROM trajets t
        JOIN lignes l ON t.ligne_id = l.id
        JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        JOIN vehicules v ON t.vehicule_id = v.id
        ORDER BY t.date_heure_depart DESC
        LIMIT 20
    """)

@app.get("/health")
def health():
    return {"status": "ok", "app": "TranspoBot"}

# ── Lancement ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
