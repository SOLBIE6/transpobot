from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import execute_query
import os, re, httpx, json
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Modèle de requête
class ChatMessage(BaseModel):
    question: str
    history: list = []


# Prompt système optimisé pour GPT-4o-mini
SYSTEM_PROMPT = """
Tu es TranspoBot, un assistant IA spécialisé dans la gestion de flotte de transport urbain au Sénégal.

Tu as accès à cette base de données MySQL :
- vehicules (immatriculation, type: bus/minibus/taxi, capacite, statut: actif/maintenance/hors_service, kilometrage)
- chauffeurs (nom, prenom, telephone, disponibilite)
- trajets (date_heure_depart, statut: termine/en_cours, recette, nb_passagers, ligne_id, chauffeur_id, vehicule_id)
- incidents (type, description, gravite, date_incident, resolu)

RÈGLES STRICTES :
- Tu dois répondre UNIQUEMENT avec un JSON valide : 
  {"sql": "SELECT ...", "explication": "texte clair en français", "conseil": null ou texte court}
- Tu ne génères JAMAIS d'autres types de requêtes que SELECT.
- Si tu ne peux pas répondre avec une requête SQL, mets "sql": null et donne une explication utile.
- Utilise toujours le français dans "explication".
- Sois précis et professionnel.
"""

# Fallbacks mots-clés (très important pour la fiabilité)
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


# Route principale
@router.post("/chat")
async def chat(msg: ChatMessage):
    q = msg.question.strip()
    print(f"[CHAT] Question reçue → {q}")

    # 1. Small talk simple
    if any(greeting in q.lower() for greeting in ["bonjour", "salut", "hello", "hi", "coucou"]):
        return {
            "answer": "Bonjour ! 👋 Je suis TranspoBot. Comment puis-je vous aider aujourd'hui ?",
            "data": [], 
            "sql": None
        }

    # 2. Essayer le fallback mots-clés (rapide et fiable)
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

    # 3. Appel à GPT-4o-mini
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {"answer": "Clé OpenAI manquante dans le fichier .env", "data": [], "sql": None}

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question : {q}"}
        ]

        async with httpx.AsyncClient(timeout=25.0) as client:
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
                    "max_tokens": 700
                }
            )

            if response.status_code != 200:
                print(f"[OpenAI] Erreur {response.status_code}: {response.text[:200]}")
                return {"answer": "Erreur de connexion à OpenAI. Veuillez réessayer.", "data": [], "sql": None}

            content = response.json()["choices"][0]["message"]["content"]
            print(f"[OpenAI] Réponse brute : {content[:200]}...")

            # Extraction du JSON
            match = re.search(r'\{.*\}', content, re.DOTALL | re.IGNORECASE)
            if match:
                result = json.loads(match.group())
                sql = result.get("sql")

                if sql and str(sql).strip().lower() not in ("null", "none", ""):
                    data = execute_query(sql)
                    return {
                        "answer": result.get("explication", "Voici les résultats :"),
                        "data": data,
                        "sql": sql,
                        "count": len(data),
                        "conseil": result.get("conseil")
                    }
                else:
                    return {
                        "answer": result.get("explication", "Je n'ai pas les informations nécessaires pour répondre à cette question."),
                        "data": [], 
                        "sql": None
                    }

    except Exception as e:
        print(f"[OpenAI ERROR] {str(e)}")

    # Réponse par défaut
    return {
        "answer": "Désolé, je n'ai pas pu traiter votre demande. Essayez des questions comme :\n• Recette du mois\n• Chauffeurs disponibles\n• Véhicules en maintenance\n• Incidents graves",
        "data": [], 
        "sql": None
    }