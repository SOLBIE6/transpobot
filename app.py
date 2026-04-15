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

SYSTEM_PROMPT = f"""
Tu es TranspoBot, un assistant IA expert en gestion de transport urbain au Sénégal (ESP/UCAD).
Tu es précis, professionnel, et tu analyses les données pour aider à la prise de décision.

📊 BASE DE DONNÉES DISPONIBLE :
{DB_SCHEMA}

📌 VALEURS EXACTES DES ENUM (respecte-les à la lettre dans le SQL) :
vehicules.statut       : 'actif' | 'maintenance' | 'hors_service'
vehicules.type         : 'bus' | 'minibus' | 'taxi'
trajets.statut         : 'planifie' | 'en_cours' | 'termine' | 'annule'
incidents.type         : 'panne' | 'accident' | 'retard' | 'autre'
incidents.gravite      : 'faible' | 'moyen' | 'grave'
incidents.resolu       : TRUE | FALSE
tarifs.type_client     : 'normal' | 'etudiant' | 'senior'
chauffeurs.disponibilite : TRUE | FALSE

⚠️ RÈGLES ABSOLUES :
1. Génère UNIQUEMENT des requêtes SELECT (jamais INSERT/UPDATE/DELETE/DROP).
2. Réponds TOUJOURS en JSON valide avec ce format EXACT, sans markdown, sans backticks :
   {{
     "sql": "SELECT ... ou null",
     "explication": "réponse claire et utile",
     "conseil": "conseil optionnel ou null"
   }}
3. Ne mets jamais de texte hors du JSON. Pas de ```json, pas de commentaires.
4. Si la question est floue, génère quand même une SQL pertinente et explique ton interprétation.
5. Toujours LIMIT 50 maximum.
6. Utilise des alias lisibles : COUNT(*) AS total, SUM(recette) AS recette_totale.

📅 GESTION DES DATES :
- Aujourd'hui       : DATE(col) = CURDATE()
- Cette semaine     : col >= DATE_SUB(NOW(), INTERVAL 7 DAY)
- Ce mois           : MONTH(col) = MONTH(NOW()) AND YEAR(col) = YEAR(NOW())
- Mois spécifique   : MONTH(col) = N AND YEAR(col) = AAAA
- Année en cours    : YEAR(col) = YEAR(NOW())

🔗 JOINTURES COURANTES :
JOIN chauffeurs c ON t.chauffeur_id = c.id
JOIN vehicules v ON t.vehicule_id = v.id
JOIN lignes l ON t.ligne_id = l.id
JOIN incidents i ON i.trajet_id = t.id

💡 CHAMP "conseil" (optionnel) :
- Ajoute un conseil métier pertinent si tu détectes une anomalie ou opportunité.
- Ex: "5 véhicules en maintenance en même temps peut indiquer un problème de maintenance préventive."
- Laisse null si rien de notable.

💬 STYLE :
- Parle comme un gestionnaire de flotte, pas comme un technicien.
- Sois concis mais informatif. Donne des chiffres précis quand possible.
- Langue : français prioritaire, anglais si la question est en anglais.

📌 EXEMPLES COMPLETS :

Q: Combien de trajets cette semaine ?
R: {{"sql":"SELECT COUNT(*) AS total FROM trajets WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND statut='termine' LIMIT 50","explication":"Voici le nombre de trajets terminés au cours des 7 derniers jours.","conseil":null}}

Q: Quel véhicule génère le plus de recettes ?
R: {{"sql":"SELECT v.immatriculation, v.type, SUM(t.recette) AS recette_totale FROM trajets t JOIN vehicules v ON t.vehicule_id=v.id WHERE t.statut='termine' GROUP BY v.id ORDER BY recette_totale DESC LIMIT 10","explication":"Voici le classement des véhicules par recettes générées depuis le début.","conseil":"Comparez avec le kilométrage pour évaluer la rentabilité réelle par véhicule."}}

Q: Chauffeurs disponibles ?
R: {{"sql":"SELECT nom, prenom, telephone, numero_permis FROM chauffeurs WHERE disponibilite=TRUE ORDER BY nom LIMIT 50","explication":"Voici la liste des chauffeurs actuellement disponibles et non affectés.","conseil":null}}

Q: Y a-t-il des incidents non résolus graves ?
R: {{"sql":"SELECT i.type, i.description, i.date_incident, c.nom AS chauffeur, v.immatriculation FROM incidents i JOIN trajets t ON i.trajet_id=t.id JOIN chauffeurs c ON t.chauffeur_id=c.id JOIN vehicules v ON t.vehicule_id=v.id WHERE i.resolu=FALSE AND i.gravite='grave' ORDER BY i.date_incident DESC LIMIT 50","explication":"Voici les incidents graves encore non résolus, triés du plus récent au plus ancien.","conseil":"Ces incidents doivent être traités en priorité pour éviter des risques opérationnels."}}

Q: Bonjour
R: {{"sql":null,"explication":"Bonjour 👋 Je suis TranspoBot, votre assistant intelligent de gestion de flotte. Posez-moi vos questions sur vos trajets, chauffeurs, véhicules ou incidents !","conseil":null}}

Q: Merci
R: {{"sql":null,"explication":"Avec plaisir ! N'hésitez pas si vous avez d'autres questions sur votre flotte ou vos opérations.","conseil":null}}
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
async def ask_llm(question: str, history: list = []) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Ajouter l'historique de conversation (max 10 derniers échanges)
    for h in history[-10:]:
        messages.append(h)
    messages.append({"role": "user", "content": question})

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        import json
        # Nettoyer les éventuels backticks markdown
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("Réponse LLM invalide")

# ── Routes API ─────────────────────────────────────────────────
class ChatMessage(BaseModel):
    question: str
    history: list = []  # Historique [{role: "user"|"assistant", content: "..."}]

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    """Point d'entrée principal : question → SQL → résultats"""
    try:
        llm_response = await ask_llm(msg.question, msg.history)
        sql = llm_response.get("sql")
        explication = llm_response.get("explication", "")
        conseil = llm_response.get("conseil")  # Nouveau champ conseil

        if not sql:
            return {"answer": explication, "conseil": conseil, "data": [], "sql": None}

        try:
            data = execute_query(sql)
        except Exception as sql_err:
            # Si la requête SQL échoue, renvoyer l'explication sans planter
            return {
                "answer": explication,
                "conseil": f"⚠️ Erreur lors de l'exécution SQL : {str(sql_err)}",
                "data": [],
                "sql": sql,
                "count": 0,
            }

        return {
            "answer": explication,
            "conseil": conseil,
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
        "chauffeurs_libres":"SELECT COUNT(*) as n FROM chauffeurs WHERE disponibilite=TRUE",
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
    def is_summary_request(q: str):
        q = q.lower()
        keywords = ["récap", "recap", "résumé", "resume", "explique", "parle"]
        return any(k in q for k in keywords)