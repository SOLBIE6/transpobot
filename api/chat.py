from fastapi import APIRouter
from pydantic import BaseModel
from db import execute_query
import os, re, httpx, json
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()


class ChatMessage(BaseModel):
    question: str
    history: list = []


SYSTEM_PROMPT = """
Tu es TranspoBot, un assistant IA spécialisé dans la gestion de flotte de transport urbain au Sénégal.

Tu as accès à cette base de données MySQL :
- vehicules (immatriculation, type: bus/minibus/taxi, capacite, statut: actif/maintenance/hors_service, kilometrage)
- chauffeurs (nom, prenom, telephone, disponibilite)
- trajets (date_heure_depart, statut: termine/en_cours, recette, nb_passagers, ligne_id, chauffeur_id, vehicule_id)
- incidents (type, description, gravite, date_incident, resolu, trajet_id)

RÈGLES STRICTES :
- Tu dois répondre UNIQUEMENT avec un JSON valide sur une seule ligne :
  {"sql": "SELECT ...", "explication": "texte clair en français", "conseil": null}
- Tu ne génères JAMAIS d'autres types de requêtes que SELECT.
- Si la question ne nécessite pas de SQL, mets "sql": null et donne une explication utile.
- Utilise toujours le français dans "explication" et "conseil".
- Sois précis et professionnel.
- Ne mets JAMAIS de texte avant ou après le JSON.
"""

# Fallback mots-clés — utilisé seulement si OpenAI échoue
KEYWORD_QUERIES = {
    "trajets aujourd'hui|combien de trajets aujourd'hui":
        "SELECT COUNT(*) AS total_trajets FROM trajets WHERE DATE(date_heure_depart) = CURDATE()",
    "trajets cette semaine":
        "SELECT COUNT(*) AS total FROM trajets WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND statut='termine'",
    "véhicule|plus de km|kilométrage maximum":
        "SELECT immatriculation, type, kilometrage FROM vehicules ORDER BY kilometrage DESC LIMIT 5",
    "chauffeurs disponibles|disponible":
        "SELECT CONCAT(nom, ' ', prenom) AS chauffeur, telephone FROM chauffeurs WHERE disponibilite = TRUE ORDER BY nom",
    "recette moyenne|recette moyenne par trajet":
        "SELECT ROUND(AVG(recette), 0) AS recette_moyenne FROM trajets WHERE statut = 'termine' AND recette > 0",
    "maintenance|véhicules en maintenance":
        "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut = 'maintenance'",
    "incidents graves":
        "SELECT type, description, date_incident FROM incidents WHERE gravite = 'grave' AND resolu = FALSE ORDER BY date_incident DESC LIMIT 10",
    "recette du mois|recette ce mois":
        "SELECT SUM(recette) AS recette_totale, COUNT(*) AS nb_trajets FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())",
    "incidents non résolus":
        "SELECT i.type, i.description, CONCAT(ch.nom,' ',ch.prenom) AS chauffeur FROM incidents i LEFT JOIN trajets t ON i.trajet_id = t.id LEFT JOIN chauffeurs ch ON t.chauffeur_id = ch.id WHERE i.resolu = FALSE ORDER BY i.date_incident DESC LIMIT 15"
}


def keyword_fallback(question: str):
    q = question.lower()
    for keywords, sql in KEYWORD_QUERIES.items():
        if any(k in q for k in keywords.split("|")):
            return {"sql": sql.strip(), "explication": "Voici les informations demandées :"}
    return None


def is_safe_sql(sql: str) -> bool:
    """Vérifie que la requête est bien un SELECT (sécurité basique)."""
    cleaned = sql.strip().lstrip("(").upper()
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC"]
    if not cleaned.startswith("SELECT"):
        return False
    return not any(kw in cleaned for kw in forbidden)


def extract_json(text: str) -> dict | None:
    """Extrait le JSON de la réponse OpenAI de façon robuste."""
    # Nettoyer les blocs markdown si présents
    text = re.sub(r"```(?:json)?", "", text).strip()

    # Tentative 1 : parser directement
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Tentative 2 : trouver le premier {...} avec re.DOTALL
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def build_messages(question: str, history: list) -> list:
    """Construit le tableau de messages avec l'historique de conversation."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Injecter l'historique (max 6 derniers échanges pour ne pas dépasser le context)
    for entry in history[-6:]:
        role = entry.get("role", "user")
        content = entry.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)})

    messages.append({"role": "user", "content": f"Question : {question}"})
    return messages


async def call_openai(messages: list, api_key: str, retries: int = 2) -> dict | None:
    """Appelle OpenAI GPT-4o-mini avec retry automatique."""
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 700,
                        "response_format": {"type": "json_object"}  # Force JSON natif
                    }
                )

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                print(f"[OpenAI] Tentative {attempt + 1} → OK")
                print(f"[OpenAI] Réponse : {content[:300]}")
                return extract_json(content)

            elif response.status_code == 429:
                print(f"[OpenAI] Rate limit (tentative {attempt + 1})")
                # Pas de sleep pour ne pas bloquer FastAPI — on passe au fallback
                continue

            else:
                print(f"[OpenAI] Erreur {response.status_code}: {response.text[:200]}")
                return None

        except httpx.TimeoutException:
            print(f"[OpenAI] Timeout (tentative {attempt + 1})")
        except Exception as e:
            print(f"[OpenAI] Exception (tentative {attempt + 1}): {e}")

    return None


@router.post("/chat")
async def chat(msg: ChatMessage):
    q = msg.question.strip()
    print(f"\n[CHAT] ──────────────────────────────")
    print(f"[CHAT] Question : {q}")
    print(f"[CHAT] Historique : {len(msg.history)} messages")

    # 1. Small talk
    greetings = ["bonjour", "salut", "hello", "hi", "coucou", "bonsoir"]
    if any(g in q.lower() for g in greetings):
        return {
            "answer": "Bonjour ! 👋 Je suis TranspoBot. Posez-moi des questions sur votre flotte : recettes, chauffeurs, véhicules, incidents...",
            "data": [],
            "sql": None
        }

    api_key = os.getenv("OPENAI_API_KEY")

    # 2. Appel OpenAI en priorité (si clé disponible)
    if api_key:
        messages = build_messages(q, msg.history)
        result = await call_openai(messages, api_key)

        if result:
            sql = result.get("sql")
            explication = result.get("explication", "Voici les résultats :")
            conseil = result.get("conseil")

            if sql and str(sql).strip().lower() not in ("null", "none", ""):
                if not is_safe_sql(sql):
                    print(f"[SÉCURITÉ] Requête refusée : {sql}")
                    return {
                        "answer": "⚠️ Requête non autorisée détectée. Seules les requêtes SELECT sont permises.",
                        "data": [],
                        "sql": None
                    }
                try:
                    data = execute_query(sql)
                    print(f"[OpenAI] SQL exécuté → {len(data)} résultats")
                    return {
                        "answer": explication,
                        "data": data,
                        "sql": sql,
                        "count": len(data),
                        "conseil": conseil
                    }
                except Exception as e:
                    print(f"[DB ERROR] {e}")
                    return {
                        "answer": f"Erreur lors de l'exécution de la requête : {str(e)}",
                        "data": [],
                        "sql": sql
                    }
            else:
                # OpenAI a répondu sans SQL (question conversationnelle)
                return {
                    "answer": explication,
                    "data": [],
                    "sql": None,
                    "conseil": conseil
                }
        else:
            print("[OpenAI] Échec → passage au fallback mots-clés")
    else:
        print("[CHAT] Clé OpenAI absente → fallback mots-clés uniquement")

    # 3. Fallback mots-clés (seulement si OpenAI échoue ou clé absente)
    if fallback := keyword_fallback(q):
        try:
            data = execute_query(fallback["sql"])
            print(f"[FALLBACK] Succès → {len(data)} résultats")
            return {
                "answer": fallback["explication"],
                "data": data,
                "sql": fallback["sql"],
                "count": len(data)
            }
        except Exception as e:
            print(f"[FALLBACK ERROR] {e}")

    # 4. Réponse par défaut
    return {
        "answer": (
            "Désolé, je n'ai pas pu traiter votre demande. "
            "Essayez des questions comme :\n"
            "• Recette du mois\n"
            "• Chauffeurs disponibles\n"
            "• Véhicules en maintenance\n"
            "• Incidents graves"
        ),
        "data": [],
        "sql": None
    }