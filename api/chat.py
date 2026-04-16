from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import execute_query
import os, re, httpx, json
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# ── MODÈLE ─────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    question: str
    history: list = []


# ── PROMPT SYSTÈME (version allégée mais puissante) ─────────────
SYSTEM_PROMPT = """
Tu es TranspoBot, assistant IA expert en gestion de transport urbain au Sénégal (projet GLSi - ESP/UCAD).

BASE DE DONNÉES :
- vehicules (immatriculation, type, capacite, statut, kilometrage)
- chauffeurs (nom, prenom, telephone, numero_permis, disponibilite, vehicule_id)
- lignes (code, nom, origine, destination)
- trajets (ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut, nb_passagers, recette)
- incidents (trajet_id, type, description, gravite, date_incident, resolu)

RÈGLES ABSOLUES :
1. Génère UNIQUEMENT des requêtes SELECT. Interdit total : INSERT, UPDATE, DELETE, DROP, ALTER.
2. Réponds TOUJOURS en JSON strict : {"sql": "...", "explication": "...", "conseil": "..." ou null}
3. Utilise LIMIT 50 maximum (sauf pour COUNT/SUM/AVG).
4. Noms complets chauffeurs : CONCAT(nom, ' ', prenom) AS chauffeur
5. Si la question est conversationnelle ou hors sujet : {"sql": null, "explication": "...", "conseil": null}

GESTION DES DATES (utilise ces formules exactes) :
- Aujourd'hui : DATE(col) = CURDATE()
- Cette semaine : col >= DATE_SUB(NOW(), INTERVAL 7 DAY)
- Ce mois : MONTH(col) = MONTH(CURDATE()) AND YEAR(col) = YEAR(CURDATE())
- Mois précédent : MONTH(col) = MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) AND YEAR(col) = YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))

STYLE : Ton professionnel d'analyste métier. Réponses claires et actionnables en français.
"""

# ── FALLBACK MOTS-CLÉS (regroupés et optimisés) ────────────────
KEYWORD_QUERIES = {
    # Rapports & Recettes
    "rapport mensuel|bilan du mois|synthèse mensuelle": """
        SELECT 'Trajets terminés' AS indicateur, COUNT(*) AS valeur FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
        UNION ALL SELECT 'Recette totale', COALESCE(SUM(recette),0) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
        UNION ALL SELECT 'Total passagers', COALESCE(SUM(nb_passagers),0) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
        UNION ALL SELECT 'Incidents', COUNT(*) FROM incidents WHERE MONTH(date_incident)=MONTH(CURDATE()) AND YEAR(date_incident)=YEAR(CURDATE())
    """,
    "mois précédent|mois dernier": """
        SELECT 'Trajets terminés' AS indicateur, COUNT(*) AS valeur FROM trajets WHERE statut='termine' 
        AND MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) 
        AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))
        UNION ALL SELECT 'Recette totale', COALESCE(SUM(recette),0) FROM trajets WHERE statut='termine' 
        AND MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) 
        AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))
    """,
    "comparaison|vs mois|évolution": """
        SELECT 
          COALESCE(SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(CURDATE()) THEN recette ELSE 0 END),0) AS ce_mois,
          COALESCE(SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) THEN recette ELSE 0 END),0) AS mois_precedent
        FROM trajets WHERE statut='termine'
    """,
    # Performance
    "meilleur chauffeur|performance chauffeur|top chauffeur": """
        SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur, COUNT(t.id) AS nb_trajets, 
               SUM(t.recette) AS recette_totale, ROUND(AVG(t.recette),0) AS recette_moyenne
        FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        WHERE t.statut='termine' GROUP BY ch.id ORDER BY recette_totale DESC LIMIT 10
    """,
    "rentabilité|véhicule rentable": """
        SELECT v.immatriculation, v.type, COUNT(t.id) AS nb_trajets, SUM(t.recette) AS recette_totale,
               ROUND(SUM(t.recette)/NULLIF(v.kilometrage,0),2) AS fcfa_par_km
        FROM trajets t JOIN vehicules v ON t.vehicule_id = v.id
        WHERE t.statut='termine' GROUP BY v.id ORDER BY recette_totale DESC LIMIT 10
    """,
    # Incidents & Flotte
    "incident grave|incidents graves": "SELECT * FROM incidents WHERE gravite='grave' AND resolu=FALSE ORDER BY date_incident DESC LIMIT 20",
    "maintenance": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut='maintenance'",
    "en cours": """
        SELECT l.nom AS ligne, CONCAT(ch.nom,' ',ch.prenom) AS chauffeur, v.immatriculation 
        FROM trajets t 
        JOIN lignes l ON t.ligne_id=l.id 
        JOIN chauffeurs ch ON t.chauffeur_id=ch.id 
        JOIN vehicules v ON t.vehicule_id=v.id 
        WHERE t.statut='en_cours'
    """
}

def keyword_fallback(question: str):
    q = question.lower()
    for keywords, sql in KEYWORD_QUERIES.items():
        if any(k in q for k in keywords.split("|")):
            return {"sql": sql.strip(), "explication": "Réponse via fallback rapide"}
    return None


# ── SMALL TALK (version simplifiée) ────────────────────────────
SMALL_TALK = {
    "bonjour|salut|hello|hi": "Bonjour ! 👋 Je suis TranspoBot. Comment puis-je vous aider aujourd'hui ?",
    "qui es-tu|qui es tu": "Je suis TranspoBot 🤖, votre assistant IA spécialisé en gestion de flotte de transport urbain.",
    "merci": "Avec plaisir ! 😊 N'hésitez pas si vous avez d'autres questions.",
}


def detect_small_talk(question: str) -> str | None:
    q = question.lower().strip()
    for keys, response in SMALL_TALK.items():
        if any(k in q for k in keys.split("|")):
            return response
    return None


# ── APPEL À L'API LLM ──────────────────────────────────────────
async def ask_openai(question: str, history: list = []):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or len(api_key) < 20:
        return None, "Clé API manquante"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-8:])  # Réduction de l'historique
    messages.append({"role": "user", "content": question})

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(
                f"{os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"), "messages": messages, "temperature": 0.1}
            )

            if r.status_code != 200:
                return None, f"Erreur API : {r.status_code}"

            content = r.json()["choices"][0]["message"]["content"]
            content = re.sub(r'```json\s*|\s*```', '', content)

            match = re.search(r'\{.*\}', content, re.DOTALL)
            return json.loads(match.group()) if match else None, None

    except Exception as e:
        return None, str(e)


# ── ROUTE PRINCIPALE ───────────────────────────────────────────
@router.post("/chat")
async def chat(msg: ChatMessage):
    try:
        q = msg.question.strip()

        # 1. Small talk rapide
        if small := detect_small_talk(q):
            return {"answer": small, "data": [], "sql": None, "conseil": None}

        # 2. Appel LLM
        llm_result, error = await ask_openai(q, msg.history)

        if llm_result:
            sql = llm_result.get("sql")
            if not sql or str(sql).strip().lower() in ("null", "none", ""):
                return {"answer": llm_result.get("explication", "Je n'ai pas compris la question."), "data": [], "sql": None}

            data = execute_query(sql)
            return {
                "answer": llm_result.get("explication", "Voici les résultats :"),
                "data": data,
                "sql": sql,
                "count": len(data),
                "conseil": llm_result.get("conseil")
            }

        # 3. Fallback mots-clés
        if fallback := keyword_fallback(q):
            data = execute_query(fallback["sql"])
            return {"answer": fallback["explication"], "data": data, "sql": fallback["sql"], "count": len(data)}

        return {"answer": "Je n'ai pas pu traiter votre demande. Essayez une question plus précise.", "data": [], "sql": None}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur interne : {str(e)}")