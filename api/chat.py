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
    history: list = []  # Historique [{role: "user"|"assistant", content: "..."}]

# ── PROMPT SYSTÈME ─────────────────────────────────────────────
SYSTEM_PROMPT = """
Tu es TranspoBot, assistant IA expert en gestion de transport urbain au Sénégal (projet GLSi - ESP/UCAD).
Tu analyses les données de la flotte et tu aides à la prise de décision opérationnelle.

BASE DE DONNÉES MySQL disponible :

TABLE vehicules   : id, immatriculation, type (bus/minibus/taxi), capacite, statut (actif/maintenance/hors_service), kilometrage, date_acquisition
TABLE chauffeurs  : id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite (TRUE/FALSE), vehicule_id, date_embauche
TABLE lignes      : id, code, nom, origine, destination, distance_km, duree_minutes
TABLE tarifs      : id, ligne_id, type_client (normal/etudiant/senior), prix
TABLE trajets     : id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut (planifie/en_cours/termine/annule), nb_passagers, recette
TABLE incidents   : id, trajet_id, type (panne/accident/retard/autre), description, gravite (faible/moyen/grave), date_incident, resolu (0/1)

RÈGLES ABSOLUES :
1. Génère UNIQUEMENT des SELECT. Jamais de INSERT/UPDATE/DELETE/DROP.
2. Réponds TOUJOURS en JSON valide, sans markdown, sans backticks, sans texte hors du JSON :
   {"sql": "SELECT ...", "explication": "réponse claire", "conseil": null}
3. Le champ "conseil" est optionnel : ajoute une recommandation métier si pertinent, sinon null.
4. Toujours LIMIT 50 maximum.
5. Pour les noms complets : CONCAT(ch.nom, ' ', ch.prenom) AS chauffeur.
6. Utilise des alias lisibles : COUNT(*) AS total, SUM(recette) AS recette_totale.

GESTION DES DATES :
- Aujourd'hui      : DATE(col) = CURDATE()
- Cette semaine    : col >= DATE_SUB(NOW(), INTERVAL 7 DAY)
- Ce mois          : MONTH(col) = MONTH(CURDATE()) AND YEAR(col) = YEAR(CURDATE())
- Mois specifique  : MONTH(col) = N AND YEAR(col) = AAAA

JOINTURES COURANTES :
- JOIN lignes l ON t.ligne_id = l.id
- JOIN chauffeurs ch ON t.chauffeur_id = ch.id
- JOIN vehicules v ON t.vehicule_id = v.id
- JOIN incidents i ON i.trajet_id = t.id

STYLE DE RÉPONSE :
- Parle comme un gestionnaire de flotte, pas comme un technicien.
- Sois concis, précis, et utile pour la prise de décision.
- Si la question est conversationnelle (bonjour, merci), sql = null.
- Langue : français prioritaire, anglais si la question est en anglais.

EXEMPLES :
Q: Combien de trajets cette semaine ?
R: {"sql":"SELECT COUNT(*) AS total FROM trajets WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND statut='termine' LIMIT 50","explication":"Voici le nombre de trajets terminés sur les 7 derniers jours.","conseil":null}

Q: Quel vehicule rapporte le plus ?
R: {"sql":"SELECT v.immatriculation, v.type, SUM(t.recette) AS recette_totale FROM trajets t JOIN vehicules v ON t.vehicule_id=v.id WHERE t.statut='termine' GROUP BY v.id ORDER BY recette_totale DESC LIMIT 10","explication":"Classement des vehicules par recettes generees.","conseil":"Comparez avec le kilometrage pour evaluer la rentabilite reelle."}

Q: Bonjour
R: {"sql":null,"explication":"Bonjour ! Je suis TranspoBot, votre assistant de gestion de flotte. Posez-moi vos questions sur vos trajets, chauffeurs, vehicules ou incidents.","conseil":null}
"""

# ── FALLBACK MOTS-CLÉS (secours si API indisponible) ───────────
KEYWORD_QUERIES = [
    {
        "keys": ["meilleur chauffeur", "plus de trajet", "classement chauffeur", "top chauffeur"],
        "sql": """SELECT CONCAT(ch.nom, ' ', ch.prenom) AS chauffeur,
                   COUNT(*) AS nb_trajets, SUM(t.recette) AS recette_totale
            FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id = ch.id
            WHERE t.statut = 'termine'
            GROUP BY ch.id, ch.nom, ch.prenom ORDER BY nb_trajets DESC LIMIT 5""",
        "exp": "Classement des chauffeurs par nombre de trajets :"
    },
    {
        "keys": ["recette moyenne", "moyenne recette"],
        "sql": "SELECT ROUND(AVG(recette), 0) AS recette_moyenne FROM trajets WHERE statut = 'termine' AND recette > 0",
        "exp": "Recette moyenne par trajet termine :"
    },
    {
        "keys": ["recette total", "recette mois", "recette du mois", "chiffre affaires"],
        "sql": """SELECT SUM(recette) AS recette_totale FROM trajets
            WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE())
            AND YEAR(date_heure_depart)=YEAR(CURDATE())""",
        "exp": "Recette totale ce mois :"
    },
    {
        "keys": ["non resolu", "non résolu", "incident ouvert", "incidents ouverts"],
        "sql": """SELECT i.type, i.description, i.gravite, i.date_incident,
                   CONCAT(ch.nom, ' ', ch.prenom) AS chauffeur
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id = t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id = ch.id
            WHERE i.resolu = FALSE ORDER BY i.date_incident DESC LIMIT 50""",
        "exp": "Incidents non resolus :"
    },
    {
        "keys": ["incident grave", "gravite grave"],
        "sql": """SELECT i.type, i.description, i.date_incident,
                   CONCAT(ch.nom, ' ', ch.prenom) AS chauffeur, v.immatriculation
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id = t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id = ch.id
            LEFT JOIN vehicules v ON t.vehicule_id = v.id
            WHERE i.gravite = 'grave' AND i.resolu = FALSE
            ORDER BY i.date_incident DESC LIMIT 50""",
        "exp": "Incidents graves non resolus :"
    },
    {
        "keys": ["incident", "panne", "accident"],
        "sql": """SELECT i.type, i.description, i.gravite, i.date_incident, i.resolu,
                   CONCAT(ch.nom, ' ', ch.prenom) AS chauffeur
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id = t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id = ch.id
            ORDER BY i.date_incident DESC LIMIT 50""",
        "exp": "Liste des incidents :"
    },
    {
        "keys": ["chauffeur disponible", "disponible"],
        "sql": """SELECT CONCAT(nom, ' ', prenom) AS chauffeur, telephone, categorie_permis
            FROM chauffeurs WHERE disponibilite = TRUE ORDER BY nom""",
        "exp": "Chauffeurs actuellement disponibles :"
    },
    {
        "keys": ["hors service"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut = 'hors_service'",
        "exp": "Vehicules hors service :"
    },
    {
        "keys": ["maintenance"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut = 'maintenance'",
        "exp": "Vehicules en maintenance :"
    },
    {
        "keys": ["plus de km", "kilometrage", "kilométrage", "plus kilometr"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules ORDER BY kilometrage DESC LIMIT 5",
        "exp": "Vehicules avec le plus de kilometrage :"
    },
    {
        "keys": ["aujourd'hui", "aujourd hui", "ce jour"],
        "sql": "SELECT COUNT(*) AS total FROM trajets WHERE DATE(date_heure_depart) = CURDATE()",
        "exp": "Nombre de trajets aujourd'hui :"
    },
    {
        "keys": ["cette semaine", "cette sem", "semaine"],
        "sql": """SELECT COUNT(*) AS total FROM trajets
            WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            AND statut = 'termine'""",
        "exp": "Nombre de trajets termines cette semaine :"
    },
    {
        "keys": ["ce mois", "du mois", "mois en cours"],
        "sql": """SELECT COUNT(*) AS total FROM trajets
            WHERE MONTH(date_heure_depart)=MONTH(CURDATE())
            AND YEAR(date_heure_depart)=YEAR(CURDATE())""",
        "exp": "Nombre de trajets ce mois :"
    },
    {
        "keys": ["vehicule", "véhicule", "flotte"],
        "sql": """SELECT immatriculation, type, capacite, statut, kilometrage
            FROM vehicules ORDER BY statut, immatriculation""",
        "exp": "Etat de la flotte :"
    },
    {
        "keys": ["chauffeur", "conducteur"],
        "sql": """SELECT CONCAT(nom, ' ', prenom) AS chauffeur, telephone,
                   categorie_permis, date_embauche
            FROM chauffeurs ORDER BY nom""",
        "exp": "Liste des chauffeurs :"
    },
    {
        "keys": ["trajet", "ligne"],
        "sql": """SELECT l.nom AS ligne, COUNT(*) AS nb_trajets, SUM(t.recette) AS recette
            FROM trajets t JOIN lignes l ON t.ligne_id = l.id
            WHERE t.statut = 'termine'
            GROUP BY l.id, l.nom ORDER BY nb_trajets DESC""",
        "exp": "Trajets par ligne :"
    },
]

def keyword_fallback(question: str):
    q = question.lower()
    for entry in KEYWORD_QUERIES:
        if any(k in q for k in entry["keys"]):
            return {"sql": entry["sql"].strip(), "explication": entry["exp"]}
    return None


# ── APPEL API OPENAI ───────────────────────────────────────────
async def ask_openai(question: str, history: list = []) -> tuple:
    api_key   = os.getenv("OPENAI_API_KEY", "")
    model     = os.getenv("LLM_MODEL", "gpt-4o-mini")
    base_url  = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

    if not api_key or len(api_key) < 20:
        return None, "Clé OpenAI manquante dans le fichier .env (variable OPENAI_API_KEY)"

    # Construire les messages : system + historique (max 10) + question
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": 1024,
                },
            )

            print(f"[OpenAI] status={r.status_code}")

            if r.status_code == 401:
                return None, "Clé OpenAI invalide — vérifie OPENAI_API_KEY dans .env"
            if r.status_code == 429:
                return None, "Quota OpenAI dépassé — réessaie dans quelques instants"
            if r.status_code != 200:
                print("[OpenAI] erreur:", r.text[:300])
                return None, f"Erreur API OpenAI HTTP {r.status_code}"

            data    = r.json()
            content = data["choices"][0]["message"]["content"]
            print(f"[OpenAI] réponse OK: {content[:120]}")

            # Nettoyer les éventuels backticks markdown
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*', '', content)

            match = re.search(r'\{.*\}', content, re.DOTALL)
            if not match:
                return None, "Réponse OpenAI non parseable"

            return json.loads(match.group()), None

    except httpx.TimeoutException:
        return None, "Timeout — OpenAI ne répond pas (>30s)"
    except json.JSONDecodeError as e:
        print("[OpenAI] JSON invalide:", str(e))
        return None, "Réponse JSON invalide"
    except Exception as e:
        print("[OpenAI] exception:", str(e))
        return None, f"Erreur réseau : {str(e)}"


# ── ROUTE CHAT ─────────────────────────────────────────────────
@router.post("/chat")
async def chat(msg: ChatMessage):
    try:
        q       = msg.question.strip()
        q_lower = q.lower()

        # Small talk direct (pas besoin d'IA)
        if any(k in q_lower for k in ["bonjour", "salut", "hello", "hey", "bonsoir", "merci", "au revoir"]):
            responses = {
                "merci":     "Avec plaisir ! N'hésitez pas si vous avez d'autres questions.",
                "au revoir": "À bientôt ! Bonne gestion de votre flotte.",
            }
            for key, rep in responses.items():
                if key in q_lower:
                    return {"answer": rep, "data": [], "sql": None, "conseil": None}
            return {
                "answer": "Bonjour ! Je suis TranspoBot, votre assistant de gestion de flotte. "
                          "Posez-moi vos questions sur les trajets, véhicules, chauffeurs ou incidents.",
                "data": [], "sql": None, "conseil": None
            }

        # 1. Appel OpenAI (IA principale)
        llm_result, llm_error = await ask_openai(q, msg.history)

        if llm_result:
            sql    = llm_result.get("sql")
            exp    = llm_result.get("explication") or "Voici le résultat :"
            conseil = llm_result.get("conseil")

            if not sql or str(sql).strip().lower() in ("null", "none", ""):
                return {"answer": exp, "data": [], "sql": None, "conseil": conseil}

            try:
                data = execute_query(sql)
                return {
                    "answer":  exp,
                    "data":    data,
                    "sql":     sql,
                    "count":   len(data),
                    "conseil": conseil,
                }
            except Exception as e:
                print(f"[SQL Error] {str(e)}")
                return {
                    "answer": f"Requête générée mais erreur d'exécution : {str(e)}",
                    "data": [], "sql": sql, "conseil": None
                }

        # 2. Fallback mots-clés (si OpenAI indisponible)
        print(f"[Fallback] OpenAI KO : {llm_error}")
        fallback = keyword_fallback(q)

        if fallback:
            try:
                data = execute_query(fallback["sql"])
                return {
                    "answer":  fallback["explication"],
                    "data":    data,
                    "sql":     fallback["sql"],
                    "count":   len(data),
                    "conseil": None,
                    "mode":    "hors-ligne",
                }
            except Exception as e:
                return {
                    "answer": f"Erreur SQL : {str(e)}",
                    "data": [], "sql": fallback["sql"], "conseil": None
                }

        # 3. Rien trouvé
        return {
            "answer": f"Service temporairement indisponible ({llm_error}). "
                      "Essayez : trajets, véhicules, chauffeurs, incidents, recette, maintenance.",
            "data": [], "sql": None, "conseil": None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
