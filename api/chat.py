from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import execute_query
import os, re, httpx, json
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# ── MODEL ─────────────────
class ChatMessage(BaseModel):
    question: str

# ── PROMPT ─────────────────
SYSTEM_PROMPT = """
Tu es TranspoBot, assistant IA de gestion de transport urbain au Sénégal.

Tu as accès à une base MySQL avec le schéma suivant :

TABLE vehicules : id, immatriculation, type (bus/minibus/taxi), capacite, statut (actif/maintenance/hors_service), kilometrage, date_acquisition
TABLE chauffeurs : id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite, vehicule_id, date_embauche
TABLE lignes : id, code, nom, origine, destination, distance_km, duree_minutes
TABLE tarifs : id, ligne_id, type_client (normal/etudiant/senior), prix
TABLE trajets : id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut (planifie/en_cours/termine/annule), nb_passagers, recette
TABLE incidents : id, trajet_id, type (panne/accident/retard/autre), description, gravite (faible/moyen/grave), date_incident, resolu (0/1)

Règles :
- Génère uniquement des SELECT (pas de INSERT/UPDATE/DELETE)
- Pour les noms complets des chauffeurs, utilise : CONCAT(ch.nom, ' ', ch.prenom)
- Pour "aujourd'hui" utilise CURDATE(), pour "ce mois" utilise MONTH(col)=MONTH(CURDATE()) AND YEAR(col)=YEAR(CURDATE())
- Joins : trajets → lignes (ligne_id), trajets → chauffeurs (chauffeur_id), trajets → vehicules (vehicule_id), incidents → trajets (trajet_id)
- Si la question ne nécessite pas de SQL, mets sql à null

Réponds TOUJOURS en JSON valide, rien d'autre :
{"sql": "SELECT ...", "explication": "réponse courte et claire en français"}
"""

# ── FALLBACK MOTS-CLÉS (fonctionne sans IA) ─────────────────
KEYWORD_QUERIES = [
    {
        "keys": ["aujourd'hui", "aujourd hui", "ce jour"],
        "sql": "SELECT COUNT(*) as nb_trajets FROM trajets WHERE DATE(date_heure_depart) = CURDATE()",
        "exp": "Voici le nombre de trajets aujourd'hui :"
    },
    {
        "keys": ["cette semaine", "cette sem"],
        "sql": "SELECT COUNT(*) as nb_trajets FROM trajets WHERE YEARWEEK(date_heure_depart, 1) = YEARWEEK(CURDATE(), 1)",
        "exp": "Nombre de trajets cette semaine :"
    },
    {
        "keys": ["ce mois", "du mois", "mois"],
        "sql": "SELECT COUNT(*) as nb_trajets FROM trajets WHERE MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())",
        "exp": "Nombre de trajets ce mois :"
    },
    {
        "keys": ["plus de km", "kilométrage", "kilometrage", "plus kilometr"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules ORDER BY kilometrage DESC LIMIT 1",
        "exp": "Le véhicule avec le plus de kilométrage :"
    },
    {
        "keys": ["maintenance"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut = 'maintenance'",
        "exp": "Véhicules actuellement en maintenance :"
    },
    {
        "keys": ["hors service"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut = 'hors_service'",
        "exp": "Véhicules hors service :"
    },
    {
        "keys": ["disponible", "chauffeur disponible"],
        "sql": "SELECT CONCAT(nom, ' ', prenom) as chauffeur, telephone, categorie_permis FROM chauffeurs WHERE disponibilite = TRUE",
        "exp": "Chauffeurs disponibles :"
    },
    {
        "keys": ["recette moyenne", "moyenne recette"],
        "sql": "SELECT ROUND(AVG(recette), 0) as recette_moyenne FROM trajets WHERE statut = 'termine' AND recette > 0",
        "exp": "Recette moyenne par trajet terminé :"
    },
    {
        "keys": ["recette total", "recette mois", "recette du mois"],
        "sql": "SELECT SUM(recette) as recette_totale FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())",
        "exp": "Recette totale ce mois :"
    },
    {
        "keys": ["incident", "non résolu", "non resolu", "ouvert"],
        "sql": """SELECT i.type, i.description, i.gravite, i.date_incident,
                   CONCAT(ch.nom, ' ', ch.prenom) as chauffeur
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id = t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id = ch.id
            WHERE i.resolu = FALSE ORDER BY i.date_incident DESC""",
        "exp": "Incidents non résolus :"
    },
    {
        "keys": ["meilleur chauffeur", "plus de trajet", "classement chauffeur"],
        "sql": """SELECT CONCAT(ch.nom, ' ', ch.prenom) as chauffeur,
                   COUNT(*) as nb_trajets, SUM(t.recette) as recette_totale
            FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id = ch.id
            WHERE t.statut = 'termine'
            GROUP BY ch.id, ch.nom, ch.prenom ORDER BY nb_trajets DESC LIMIT 5""",
        "exp": "Classement des chauffeurs par nombre de trajets :"
    },
    {
        "keys": ["vehicule", "véhicule", "flotte"],
        "sql": "SELECT immatriculation, type, capacite, statut, kilometrage FROM vehicules ORDER BY statut, immatriculation",
        "exp": "État de la flotte :"
    },
    {
        "keys": ["chauffeur", "conducteur"],
        "sql": "SELECT CONCAT(nom, ' ', prenom) as chauffeur, telephone, categorie_permis, date_embauche FROM chauffeurs ORDER BY nom",
        "exp": "Liste des chauffeurs :"
    },
    {
        "keys": ["trajet", "ligne"],
        "sql": """SELECT l.nom as ligne, COUNT(*) as nb_trajets, SUM(t.recette) as recette
            FROM trajets t JOIN lignes l ON t.ligne_id = l.id
            WHERE t.statut = 'termine' GROUP BY l.id, l.nom ORDER BY nb_trajets DESC""",
        "exp": "Trajets par ligne :"
    },
]

def keyword_fallback(question: str):
    q = question.lower()
    for entry in KEYWORD_QUERIES:
        if any(k in q for k in entry["keys"]):
            return {"sql": entry["sql"].strip(), "explication": entry["exp"]}
    return None

# ── APPEL LLM ─────────────────
async def ask_llm(question: str):
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or len(api_key) < 20:
        return None, "Clé OpenAI manquante dans le fichier .env"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": question},
                    ],
                },
            )

            print(f"[OpenAI] status={r.status_code}")

            if r.status_code == 401:
                return None, "Clé OpenAI invalide ou expirée — va sur platform.openai.com/api-keys"
            if r.status_code == 429:
                return None, "Quota OpenAI dépassé — réessaie dans quelques minutes"
            if r.status_code != 200:
                print("[OpenAI] erreur:", r.text[:300])
                return None, f"Erreur OpenAI HTTP {r.status_code}"

            content = r.json()["choices"][0]["message"]["content"]
            print(f"[OpenAI] réponse OK: {content[:120]}")

            match = re.search(r'\{.*\}', content, re.DOTALL)
            if not match:
                return None, "Réponse LLM non parseable"

            return json.loads(match.group()), None

    except httpx.TimeoutException:
        return None, "Timeout — OpenAI ne répond pas (>30s)"
    except Exception as e:
        print("[OpenAI] exception:", str(e))
        return None, f"Erreur réseau : {str(e)}"

# ── ROUTE CHAT ─────────────────
@router.post("/chat")
async def chat(msg: ChatMessage):
    try:
        q = msg.question.strip()
        q_lower = q.lower()

        # Small talk
        if any(k in q_lower for k in ["bonjour", "salut", "hello", "hey", "bonsoir"]):
            return {
                "answer": "Bonjour 👋 Je suis TranspoBot. Pose-moi une question sur les trajets, véhicules ou chauffeurs.",
                "data": [], "sql": None
            }

        # 1. Essai LLM OpenAI
        llm_result, llm_error = await ask_llm(q)

        if llm_result:
            sql = llm_result.get("sql")
            exp = llm_result.get("explication") or "Voici le résultat :"

            if not sql or sql.strip().lower() in ("null", "none", ""):
                return {"answer": exp, "data": [], "sql": None}

            try:
                data = execute_query(sql)
                return {"answer": exp, "data": data, "sql": sql, "count": len(data)}
            except Exception as e:
                return {"answer": f"SQL généré mais erreur d'exécution : {str(e)}", "data": [], "sql": sql}

        # 2. Fallback mots-clés (si OpenAI KO)
        print(f"[Fallback] OpenAI KO: {llm_error}")
        fallback = keyword_fallback(q)

        if fallback:
            try:
                data = execute_query(fallback["sql"])
                note = f" <small style='opacity:0.5'>⚠️ mode hors-ligne</small>"
                return {
                    "answer": fallback["explication"] + note,
                    "data": data,
                    "sql": fallback["sql"],
                    "count": len(data)
                }
            except Exception as e:
                return {"answer": f"Erreur SQL : {str(e)}", "data": [], "sql": fallback["sql"]}

        # 3. Rien trouvé
        return {
            "answer": f"❌ {llm_error}. Essaie des mots-clés : trajets, véhicules, chauffeurs, incidents, recette, maintenance...",
            "data": [], "sql": None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))