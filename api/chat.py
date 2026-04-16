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
Tu analyses les données de flotte et aides à la prise de décision opérationnelle et stratégique.

═══════════════════════════════════════════════
BASE DE DONNÉES MySQL
═══════════════════════════════════════════════
TABLE vehicules   : id, immatriculation, type (bus/minibus/taxi), capacite, statut (actif/maintenance/hors_service), kilometrage, date_acquisition
TABLE chauffeurs  : id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite (TRUE/FALSE), vehicule_id, date_embauche
TABLE lignes      : id, code, nom, origine, destination, distance_km, duree_minutes
TABLE tarifs      : id, ligne_id, type_client (normal/etudiant/senior), prix
TABLE trajets     : id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut (planifie/en_cours/termine/annule), nb_passagers, recette
TABLE incidents   : id, trajet_id, type (panne/accident/retard/autre), description, gravite (faible/moyen/grave), date_incident, resolu (0/1)

═══════════════════════════════════════════════
RÈGLES ABSOLUES
═══════════════════════════════════════════════
1. Génère UNIQUEMENT des SELECT. Jamais de INSERT/UPDATE/DELETE/DROP/ALTER.
2. Réponds TOUJOURS en JSON valide strict, sans markdown ni backticks :
   {"sql": "SELECT ...", "explication": "texte clair", "conseil": "recommandation ou null"}
3. LIMIT 50 maximum sauf pour les COUNT/SUM/AVG (agrégats).
4. Noms complets chauffeurs : CONCAT(ch.nom, ' ', ch.prenom) AS chauffeur
5. Alias lisibles : COUNT(*) AS total, SUM(recette) AS recette_totale, AVG(recette) AS recette_moyenne
6. Si question conversationnelle ou hors-sujet : sql = null

═══════════════════════════════════════════════
GESTION DES DATES — FORMULES EXACTES
═══════════════════════════════════════════════
- Aujourd'hui            : DATE(col) = CURDATE()
- Hier                   : DATE(col) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
- Cette semaine (7j)     : col >= DATE_SUB(NOW(), INTERVAL 7 DAY)
- Ce mois                : MONTH(col) = MONTH(CURDATE()) AND YEAR(col) = YEAR(CURDATE())
- Mois précédent         : MONTH(col) = MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) AND YEAR(col) = YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))
- Il y a N mois          : col >= DATE_SUB(CURDATE(), INTERVAL N MONTH)
- Mois nommé (ex: mars)  : MONTH(col) = 3 (adapter selon le mois mentionné : jan=1, fev=2, mar=3, avr=4, mai=5, jun=6, jul=7, aou=8, sep=9, oct=10, nov=11, dec=12)
- Cette année            : YEAR(col) = YEAR(CURDATE())
- Année précédente       : YEAR(col) = YEAR(CURDATE()) - 1

═══════════════════════════════════════════════
TYPES DE REQUÊTES AVANCÉES
═══════════════════════════════════════════════

── RAPPORT MENSUEL COMPLET ──
Si on demande un "rapport mensuel", "bilan du mois", "synthèse mensuelle" :
Génère une requête qui retourne EN UNE SEULE REQUÊTE via UNION ALL :
  - Nombre de trajets terminés
  - Recette totale
  - Nombre de passagers
  - Nombre d'incidents
  - Taux d'annulation
Exemple :
SELECT 'Trajets terminés' AS indicateur, COUNT(*) AS valeur FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
UNION ALL
SELECT 'Recette totale (FCFA)', SUM(recette) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
UNION ALL
SELECT 'Total passagers', SUM(nb_passagers) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
UNION ALL
SELECT 'Incidents ce mois', COUNT(*) FROM incidents WHERE MONTH(date_incident)=MONTH(CURDATE()) AND YEAR(date_incident)=YEAR(CURDATE())
UNION ALL
SELECT 'Trajets annulés', COUNT(*) FROM trajets WHERE statut='annule' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())

── COMPARAISONS MOIS SUR MOIS ──
Si on demande "comparaison", "évolution", "vs mois dernier", "par rapport au mois précédent" :
Utilise deux sous-requêtes ou un CASE WHEN pour comparer ce mois vs mois précédent.
Exemple :
SELECT
  SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) THEN recette ELSE 0 END) AS recette_ce_mois,
  SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) THEN recette ELSE 0 END) AS recette_mois_precedent
FROM trajets WHERE statut='termine'

── ANALYSE DE PERFORMANCE CHAUFFEUR ──
Si on demande "performance", "rendement", "classement", "meilleur" pour les chauffeurs :
SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur,
  COUNT(t.id) AS nb_trajets,
  SUM(t.recette) AS recette_totale,
  ROUND(AVG(t.recette),0) AS recette_moyenne,
  SUM(t.nb_passagers) AS total_passagers,
  ROUND(SUM(t.recette)/NULLIF(COUNT(t.id),0),0) AS recette_par_trajet
FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id=ch.id
WHERE t.statut='termine'
GROUP BY ch.id ORDER BY recette_totale DESC LIMIT 10

── ANALYSE DE RENTABILITÉ VÉHICULE ──
Si on demande "rentabilité", "véhicule le plus rentable" :
SELECT v.immatriculation, v.type,
  COUNT(t.id) AS nb_trajets,
  SUM(t.recette) AS recette_totale,
  v.kilometrage,
  ROUND(SUM(t.recette)/NULLIF(v.kilometrage,0),2) AS fcfa_par_km
FROM trajets t JOIN vehicules v ON t.vehicule_id=v.id
WHERE t.statut='termine'
GROUP BY v.id ORDER BY recette_totale DESC LIMIT 10

── ÉVOLUTION MENSUELLE (tendance sur N mois) ──
Si on demande "évolution sur X mois", "tendance", "historique mensuel" :
SELECT DATE_FORMAT(date_heure_depart,'%Y-%m') AS mois,
  COUNT(*) AS nb_trajets,
  SUM(recette) AS recette_totale,
  SUM(nb_passagers) AS total_passagers
FROM trajets WHERE statut='termine' AND date_heure_depart >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
GROUP BY mois ORDER BY mois ASC

── TAUX D'INCIDENTS PAR CHAUFFEUR ──
Si on demande "chauffeur avec le plus d'incidents", "incidents par chauffeur" :
SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur,
  COUNT(i.id) AS nb_incidents,
  SUM(CASE WHEN i.gravite='grave' THEN 1 ELSE 0 END) AS incidents_graves,
  SUM(CASE WHEN i.resolu=FALSE THEN 1 ELSE 0 END) AS non_resolus
FROM incidents i
JOIN trajets t ON i.trajet_id=t.id
JOIN chauffeurs ch ON t.chauffeur_id=ch.id
GROUP BY ch.id ORDER BY nb_incidents DESC LIMIT 10

── LIGNE LA PLUS RENTABLE ──
SELECT l.nom AS ligne, l.origine, l.destination,
  COUNT(t.id) AS nb_trajets,
  SUM(t.recette) AS recette_totale,
  ROUND(AVG(t.recette),0) AS recette_moyenne,
  SUM(t.nb_passagers) AS total_passagers
FROM trajets t JOIN lignes l ON t.ligne_id=l.id
WHERE t.statut='termine'
GROUP BY l.id ORDER BY recette_totale DESC

═══════════════════════════════════════════════
JOINTURES DE RÉFÉRENCE
═══════════════════════════════════════════════
- trajets t JOIN lignes l ON t.ligne_id = l.id
- trajets t JOIN chauffeurs ch ON t.chauffeur_id = ch.id
- trajets t JOIN vehicules v ON t.vehicule_id = v.id
- incidents i JOIN trajets t ON i.trajet_id = t.id

═══════════════════════════════════════════════
STYLE DE RÉPONSE
═══════════════════════════════════════════════
- Adopte le ton d'un analyste métier : chiffres précis, lecture utile.
- Dans "explication" : donne le résumé de ce que la requête fait + comment lire le résultat.
- Dans "conseil" : donne une recommandation actionnable si pertinent (ex: "Ce véhicule dépasse 100 000 km, une révision est recommandée"), sinon null.
- Langue : français prioritaire, anglais si la question est posée en anglais.
- Mois nommés en français → convertis en numéro : janvier=1, février=2, mars=3, avril=4, mai=5, juin=6, juillet=7, août=8, septembre=9, octobre=10, novembre=11, décembre=12.

═══════════════════════════════════════════════
EXEMPLES
═══════════════════════════════════════════════
Q: Donne-moi le rapport du mois
R: {"sql":"SELECT 'Trajets terminés' AS indicateur, CAST(COUNT(*) AS CHAR) AS valeur FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) UNION ALL SELECT 'Recette totale (FCFA)', CAST(SUM(recette) AS CHAR) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) UNION ALL SELECT 'Total passagers', CAST(SUM(nb_passagers) AS CHAR) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) UNION ALL SELECT 'Incidents ce mois', CAST(COUNT(*) AS CHAR) FROM incidents WHERE MONTH(date_incident)=MONTH(CURDATE()) AND YEAR(date_incident)=YEAR(CURDATE()) UNION ALL SELECT 'Trajets annulés', CAST(COUNT(*) AS CHAR) FROM trajets WHERE statut='annule' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())","explication":"Voici le bilan complet du mois en cours : activité, recettes, passagers et incidents.","conseil":"Comparez avec le mois précédent pour évaluer la progression de la flotte."}

Q: Recette du mois précédent ?
R: {"sql":"SELECT SUM(recette) AS recette_mois_precedent, COUNT(*) AS nb_trajets, SUM(nb_passagers) AS total_passagers FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH))","explication":"Recette totale, nombre de trajets et passagers du mois précédent.","conseil":null}

Q: Comparaison recettes ce mois vs mois dernier
R: {"sql":"SELECT SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) THEN recette ELSE 0 END) AS recette_ce_mois, SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) THEN recette ELSE 0 END) AS recette_mois_precedent FROM trajets WHERE statut='termine'","explication":"Comparaison directe des recettes entre ce mois-ci et le mois précédent.","conseil":"Si la recette ce mois est inférieure, vérifiez le taux d'annulation et les incidents."}

Q: Évolution sur 6 mois
R: {"sql":"SELECT DATE_FORMAT(date_heure_depart,'%Y-%m') AS mois, COUNT(*) AS nb_trajets, SUM(recette) AS recette_totale, SUM(nb_passagers) AS total_passagers FROM trajets WHERE statut='termine' AND date_heure_depart >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH) GROUP BY mois ORDER BY mois ASC","explication":"Évolution mensuelle de l'activité sur les 6 derniers mois.","conseil":"Identifiez les mois creux pour planifier des actions commerciales."}

Q: Performance des chauffeurs ce mois
R: {"sql":"SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur, COUNT(t.id) AS nb_trajets, SUM(t.recette) AS recette_totale, ROUND(AVG(t.recette),0) AS recette_moyenne FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id=ch.id WHERE t.statut='termine' AND MONTH(t.date_heure_depart)=MONTH(CURDATE()) AND YEAR(t.date_heure_depart)=YEAR(CURDATE()) GROUP BY ch.id ORDER BY recette_totale DESC LIMIT 10","explication":"Classement des chauffeurs par recettes générées ce mois.","conseil":"Valorisez les meilleurs chauffeurs et analysez les facteurs de leur performance."}

Q: Quel vehicule rapporte le plus ?
R: {"sql":"SELECT v.immatriculation, v.type, COUNT(t.id) AS nb_trajets, SUM(t.recette) AS recette_totale, ROUND(SUM(t.recette)/NULLIF(v.kilometrage,0),2) AS fcfa_par_km FROM trajets t JOIN vehicules v ON t.vehicule_id=v.id WHERE t.statut='termine' GROUP BY v.id ORDER BY recette_totale DESC LIMIT 10","explication":"Classement des véhicules par recettes avec ratio FCFA/km pour la rentabilité réelle.","conseil":"Un ratio FCFA/km élevé avec kilométrage élevé indique un véhicule très rentable à maintenir en priorité."}

Q: Bonjour
R: {"sql":null,"explication":"Bonjour ! Je suis TranspoBot, votre assistant de gestion de flotte. Posez-moi vos questions : rapports mensuels, recettes, performance des chauffeurs, état de la flotte, incidents...","conseil":null}
"""

# ── FALLBACK MOTS-CLÉS (secours si API indisponible) ───────────
KEYWORD_QUERIES = [
    # ── RAPPORTS MENSUELS ──
    {
        "keys": ["rapport mensuel", "bilan du mois", "bilan mois", "synthèse mensuelle", "synthese mensuelle", "rapport du mois"],
        "sql": """
            SELECT 'Trajets terminés' AS indicateur, CAST(COUNT(*) AS CHAR) AS valeur FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
            UNION ALL SELECT 'Recette totale (FCFA)', CAST(COALESCE(SUM(recette),0) AS CHAR) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
            UNION ALL SELECT 'Total passagers', CAST(COALESCE(SUM(nb_passagers),0) AS CHAR) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
            UNION ALL SELECT 'Trajets annulés', CAST(COUNT(*) AS CHAR) FROM trajets WHERE statut='annule' AND MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())
            UNION ALL SELECT 'Incidents ce mois', CAST(COUNT(*) AS CHAR) FROM incidents WHERE MONTH(date_incident)=MONTH(CURDATE()) AND YEAR(date_incident)=YEAR(CURDATE())
            UNION ALL SELECT 'Incidents non résolus', CAST(COUNT(*) AS CHAR) FROM incidents WHERE resolu=FALSE AND MONTH(date_incident)=MONTH(CURDATE()) AND YEAR(date_incident)=YEAR(CURDATE())
        """,
        "exp": "📊 Rapport mensuel — mois en cours :"
    },
    # ── MOIS PRÉCÉDENT ──
    {
        "keys": ["mois précédent", "mois precedent", "mois dernier", "mois passé", "mois passe"],
        "sql": """
            SELECT 'Trajets terminés' AS indicateur, CAST(COUNT(*) AS CHAR) AS valeur FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH))
            UNION ALL SELECT 'Recette totale (FCFA)', CAST(COALESCE(SUM(recette),0) AS CHAR) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH))
            UNION ALL SELECT 'Total passagers', CAST(COALESCE(SUM(nb_passagers),0) AS CHAR) FROM trajets WHERE statut='termine' AND MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH))
            UNION ALL SELECT 'Incidents', CAST(COUNT(*) AS CHAR) FROM incidents WHERE MONTH(date_incident)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_incident)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH))
        """,
        "exp": "📊 Bilan du mois précédent :"
    },
    # ── COMPARAISON CE MOIS VS MOIS DERNIER ──
    {
        "keys": ["comparaison", "comparer", "vs mois", "par rapport au mois", "évolution recette", "evolution recette"],
        "sql": """
            SELECT
              COALESCE(SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) THEN recette ELSE 0 END),0) AS recette_ce_mois,
              COALESCE(SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) THEN recette ELSE 0 END),0) AS recette_mois_precedent,
              COUNT(CASE WHEN MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) THEN 1 END) AS trajets_ce_mois,
              COUNT(CASE WHEN MONTH(date_heure_depart)=MONTH(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) AND YEAR(date_heure_depart)=YEAR(DATE_SUB(CURDATE(),INTERVAL 1 MONTH)) THEN 1 END) AS trajets_mois_precedent
            FROM trajets WHERE statut='termine'
        """,
        "exp": "📈 Comparaison ce mois vs mois précédent :"
    },
    # ── ÉVOLUTION / TENDANCE ──
    {
        "keys": ["évolution", "evolution", "tendance", "historique mensuel", "sur 6 mois", "sur 3 mois"],
        "sql": """
            SELECT DATE_FORMAT(date_heure_depart,'%Y-%m') AS mois,
              COUNT(*) AS nb_trajets,
              SUM(recette) AS recette_totale,
              SUM(nb_passagers) AS total_passagers
            FROM trajets WHERE statut='termine'
              AND date_heure_depart >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY mois ORDER BY mois ASC
        """,
        "exp": "📈 Évolution mensuelle sur les 6 derniers mois :"
    },
    # ── PERFORMANCE CHAUFFEURS ──
    {
        "keys": ["performance chauffeur", "rendement chauffeur", "meilleur chauffeur", "plus de trajet", "classement chauffeur", "top chauffeur"],
        "sql": """
            SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur,
              COUNT(t.id) AS nb_trajets,
              SUM(t.recette) AS recette_totale,
              ROUND(AVG(t.recette),0) AS recette_moyenne,
              SUM(t.nb_passagers) AS total_passagers
            FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            WHERE t.statut='termine'
            GROUP BY ch.id, ch.nom, ch.prenom ORDER BY recette_totale DESC LIMIT 10
        """,
        "exp": "🏆 Performance des chauffeurs (tous temps) :"
    },
    # ── RENTABILITÉ VÉHICULES ──
    {
        "keys": ["rentabilité", "rentabilite", "vehicule le plus rentable", "vehicule rapporte"],
        "sql": """
            SELECT v.immatriculation, v.type,
              COUNT(t.id) AS nb_trajets,
              SUM(t.recette) AS recette_totale,
              v.kilometrage,
              ROUND(SUM(t.recette)/NULLIF(v.kilometrage,0),2) AS fcfa_par_km
            FROM trajets t JOIN vehicules v ON t.vehicule_id=v.id
            WHERE t.statut='termine'
            GROUP BY v.id, v.immatriculation, v.type, v.kilometrage
            ORDER BY recette_totale DESC LIMIT 10
        """,
        "exp": "💰 Rentabilité des véhicules (recette + ratio FCFA/km) :"
    },
    # ── INCIDENTS PAR CHAUFFEUR ──
    {
        "keys": ["incident par chauffeur", "chauffeur incident", "chauffeur accident", "chauffeur panne"],
        "sql": """
            SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur,
              COUNT(i.id) AS nb_incidents,
              SUM(CASE WHEN i.gravite='grave' THEN 1 ELSE 0 END) AS incidents_graves,
              SUM(CASE WHEN i.resolu=FALSE THEN 1 ELSE 0 END) AS non_resolus
            FROM incidents i
            JOIN trajets t ON i.trajet_id=t.id
            JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            GROUP BY ch.id, ch.nom, ch.prenom ORDER BY nb_incidents DESC LIMIT 10
        """,
        "exp": "⚠️ Incidents par chauffeur :"
    },
    # ── LIGNE LA PLUS RENTABLE ──
    {
        "keys": ["ligne rentable", "ligne performante", "meilleure ligne", "ligne rapporte"],
        "sql": """
            SELECT l.nom AS ligne, l.origine, l.destination,
              COUNT(t.id) AS nb_trajets,
              SUM(t.recette) AS recette_totale,
              ROUND(AVG(t.recette),0) AS recette_moyenne,
              SUM(t.nb_passagers) AS total_passagers
            FROM trajets t JOIN lignes l ON t.ligne_id=l.id
            WHERE t.statut='termine'
            GROUP BY l.id, l.nom, l.origine, l.destination ORDER BY recette_totale DESC
        """,
        "exp": "🛣️ Performance par ligne :"
    },
    # ── RECETTE MOYENNE ──
    {
        "keys": ["recette moyenne", "moyenne recette"],
        "sql": "SELECT ROUND(AVG(recette), 0) AS recette_moyenne FROM trajets WHERE statut = 'termine' AND recette > 0",
        "exp": "Recette moyenne par trajet terminé :"
    },
    # ── RECETTE CE MOIS ──
    {
        "keys": ["recette total", "recette mois", "recette du mois", "recette ce mois", "chiffre affaires"],
        "sql": """
            SELECT SUM(recette) AS recette_totale, COUNT(*) AS nb_trajets,
              ROUND(AVG(recette),0) AS recette_moyenne
            FROM trajets WHERE statut='termine'
              AND MONTH(date_heure_depart)=MONTH(CURDATE())
              AND YEAR(date_heure_depart)=YEAR(CURDATE())
        """,
        "exp": "💰 Recettes du mois en cours :"
    },
    # ── INCIDENTS ──
    {
        "keys": ["incident grave", "gravite grave"],
        "sql": """
            SELECT i.type, i.description, i.date_incident,
              CONCAT(ch.nom,' ',ch.prenom) AS chauffeur, v.immatriculation
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id=t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            LEFT JOIN vehicules v ON t.vehicule_id=v.id
            WHERE i.gravite='grave' AND i.resolu=FALSE
            ORDER BY i.date_incident DESC LIMIT 50
        """,
        "exp": "🔴 Incidents graves non résolus :"
    },
    {
        "keys": ["non resolu", "non résolu", "incident ouvert", "incidents ouverts"],
        "sql": """
            SELECT i.type, i.description, i.gravite, i.date_incident,
              CONCAT(ch.nom,' ',ch.prenom) AS chauffeur
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id=t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            WHERE i.resolu=FALSE ORDER BY i.date_incident DESC LIMIT 50
        """,
        "exp": "⚠️ Incidents non résolus :"
    },
    {
        "keys": ["incident", "panne", "accident"],
        "sql": """
            SELECT i.type, i.description, i.gravite, i.date_incident, i.resolu,
              CONCAT(ch.nom,' ',ch.prenom) AS chauffeur
            FROM incidents i
            LEFT JOIN trajets t ON i.trajet_id=t.id
            LEFT JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            ORDER BY i.date_incident DESC LIMIT 50
        """,
        "exp": "Liste des incidents :"
    },
    {
        "keys": ["chauffeur disponible", "disponible"],
        "sql": "SELECT CONCAT(nom,' ',prenom) AS chauffeur, telephone, categorie_permis FROM chauffeurs WHERE disponibilite=TRUE ORDER BY nom",
        "exp": "Chauffeurs actuellement disponibles :"
    },
    {
        "keys": ["hors service"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut='hors_service'",
        "exp": "Véhicules hors service :"
    },
    {
        "keys": ["maintenance"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules WHERE statut='maintenance'",
        "exp": "Véhicules en maintenance :"
    },
    {
        "keys": ["plus de km", "kilometrage", "kilométrage"],
        "sql": "SELECT immatriculation, type, kilometrage FROM vehicules ORDER BY kilometrage DESC LIMIT 5",
        "exp": "Véhicules avec le plus de kilométrage :"
    },
    {
        "keys": ["aujourd'hui", "aujourd hui", "ce jour"],
        "sql": "SELECT COUNT(*) AS total FROM trajets WHERE DATE(date_heure_depart)=CURDATE()",
        "exp": "Nombre de trajets aujourd'hui :"
    },
    {
        "keys": ["cette semaine", "semaine"],
        "sql": "SELECT COUNT(*) AS total FROM trajets WHERE date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND statut='termine'",
        "exp": "Nombre de trajets terminés cette semaine :"
    },
    {
        "keys": ["ce mois", "du mois", "mois en cours"],
        "sql": "SELECT COUNT(*) AS total FROM trajets WHERE MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())",
        "exp": "Nombre de trajets ce mois :"
    },
    {
        "keys": ["vehicule", "véhicule", "flotte"],
        "sql": "SELECT immatriculation, type, capacite, statut, kilometrage FROM vehicules ORDER BY statut, immatriculation",
        "exp": "État de la flotte :"
    },
    {
        "keys": ["chauffeur", "conducteur"],
        "sql": "SELECT CONCAT(nom,' ',prenom) AS chauffeur, telephone, categorie_permis, date_embauche FROM chauffeurs ORDER BY nom",
        "exp": "Liste des chauffeurs :"
    },
    {
        "keys": ["trajet", "ligne"],
        "sql": """SELECT l.nom AS ligne, COUNT(*) AS nb_trajets, SUM(t.recette) AS recette
            FROM trajets t JOIN lignes l ON t.ligne_id=l.id
            WHERE t.statut='termine' GROUP BY l.id, l.nom ORDER BY nb_trajets DESC""",
        "exp": "Trajets par ligne :"
    },
    # ── RECETTES ENRICHIES ──
    {
        "keys": ["recette aujourd", "recette du jour", "recette ce jour", "recette journée", "recette journee"],
        "sql": """SELECT SUM(recette) AS recette_aujourd_hui, COUNT(*) AS nb_trajets
            FROM trajets WHERE statut='termine' AND DATE(date_heure_depart)=CURDATE()""",
        "exp": "💰 Recette d'aujourd'hui :"
    },
    {
        "keys": ["recette hier", "recette d'hier"],
        "sql": """SELECT SUM(recette) AS recette_hier, COUNT(*) AS nb_trajets
            FROM trajets WHERE statut='termine'
            AND DATE(date_heure_depart)=DATE_SUB(CURDATE(),INTERVAL 1 DAY)""",
        "exp": "💰 Recette d'hier :"
    },
    {
        "keys": ["recette semaine", "recette cette semaine", "recette 7 jours"],
        "sql": """SELECT SUM(recette) AS recette_semaine, COUNT(*) AS nb_trajets,
              ROUND(AVG(recette),0) AS recette_moyenne
            FROM trajets WHERE statut='termine'
            AND date_heure_depart >= DATE_SUB(NOW(), INTERVAL 7 DAY)""",
        "exp": "💰 Recette de la semaine :"
    },
    {
        "keys": ["recette annee", "recette année", "recette annuelle", "recette cette annee"],
        "sql": """SELECT SUM(recette) AS recette_annuelle, COUNT(*) AS nb_trajets,
              ROUND(AVG(recette),0) AS recette_moyenne
            FROM trajets WHERE statut='termine' AND YEAR(date_heure_depart)=YEAR(CURDATE())""",
        "exp": "💰 Recette de l'année en cours :"
    },
    {
        "keys": ["recette par ligne", "recette ligne", "recette par trajet type"],
        "sql": """SELECT l.nom AS ligne, SUM(t.recette) AS recette_totale,
              COUNT(t.id) AS nb_trajets, ROUND(AVG(t.recette),0) AS recette_moyenne
            FROM trajets t JOIN lignes l ON t.ligne_id=l.id
            WHERE t.statut='termine'
            GROUP BY l.id, l.nom ORDER BY recette_totale DESC""",
        "exp": "💰 Recette par ligne :"
    },
    {
        "keys": ["recette par chauffeur", "recette chauffeur"],
        "sql": """SELECT CONCAT(ch.nom,' ',ch.prenom) AS chauffeur,
              SUM(t.recette) AS recette_totale, COUNT(t.id) AS nb_trajets,
              ROUND(AVG(t.recette),0) AS recette_moyenne
            FROM trajets t JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            WHERE t.statut='termine'
            GROUP BY ch.id, ch.nom, ch.prenom ORDER BY recette_totale DESC LIMIT 10""",
        "exp": "💰 Recette par chauffeur :"
    },
    {
        "keys": ["recette par vehicule", "recette vehicule"],
        "sql": """SELECT v.immatriculation, v.type,
              SUM(t.recette) AS recette_totale, COUNT(t.id) AS nb_trajets
            FROM trajets t JOIN vehicules v ON t.vehicule_id=v.id
            WHERE t.statut='termine'
            GROUP BY v.id, v.immatriculation, v.type ORDER BY recette_totale DESC""",
        "exp": "💰 Recette par véhicule :"
    },
    {
        "keys": ["recette janvier", "recette février", "recette fevrier", "recette mars",
                 "recette avril", "recette mai", "recette juin", "recette juillet",
                 "recette août", "recette aout", "recette septembre", "recette octobre",
                 "recette novembre", "recette décembre", "recette decembre"],
        "sql": """SELECT DATE_FORMAT(date_heure_depart,'%Y-%m') AS mois,
              SUM(recette) AS recette_totale, COUNT(*) AS nb_trajets
            FROM trajets WHERE statut='termine'
            GROUP BY mois ORDER BY mois DESC LIMIT 12""",
        "exp": "💰 Recettes par mois (12 derniers) — précisez un mois si besoin :"
    },
    {
        "keys": ["recette", "chiffre d'affaires", "chiffre affaire"],
        "sql": """SELECT
              SUM(CASE WHEN DATE(date_heure_depart)=CURDATE() THEN recette ELSE 0 END) AS recette_aujourd_hui,
              SUM(CASE WHEN MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE()) THEN recette ELSE 0 END) AS recette_ce_mois,
              SUM(CASE WHEN YEAR(date_heure_depart)=YEAR(CURDATE()) THEN recette ELSE 0 END) AS recette_annee,
              SUM(recette) AS recette_totale_all_time
            FROM trajets WHERE statut='termine'""",
        "exp": "💰 Vue d'ensemble des recettes :"
    },
    # ── PASSAGERS ──
    {
        "keys": ["passager", "nb passager", "nombre passager", "affluence"],
        "sql": """SELECT DATE_FORMAT(date_heure_depart,'%Y-%m') AS mois,
              SUM(nb_passagers) AS total_passagers, COUNT(*) AS nb_trajets,
              ROUND(AVG(nb_passagers),1) AS moy_passagers_par_trajet
            FROM trajets WHERE statut='termine'
            AND date_heure_depart >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
            GROUP BY mois ORDER BY mois DESC""",
        "exp": "👥 Affluence passagers (3 derniers mois) :"
    },
    # ── TAUX ANNULATION ──
    {
        "keys": ["annulation", "taux annulation", "trajet annulé", "trajet annule"],
        "sql": """SELECT
              COUNT(*) AS total_trajets,
              SUM(CASE WHEN statut='annule' THEN 1 ELSE 0 END) AS nb_annules,
              ROUND(100*SUM(CASE WHEN statut='annule' THEN 1 ELSE 0 END)/COUNT(*),1) AS taux_annulation_pct
            FROM trajets
            WHERE MONTH(date_heure_depart)=MONTH(CURDATE()) AND YEAR(date_heure_depart)=YEAR(CURDATE())""",
        "exp": "📉 Taux d'annulation ce mois :"
    },
    # ── EN COURS ──
    {
        "keys": ["en cours", "trajet en cours", "actif maintenant", "temps réel"],
        "sql": """SELECT l.nom AS ligne, CONCAT(ch.nom,' ',ch.prenom) AS chauffeur,
              v.immatriculation, t.date_heure_depart, t.nb_passagers
            FROM trajets t
            JOIN lignes l ON t.ligne_id=l.id
            JOIN chauffeurs ch ON t.chauffeur_id=ch.id
            JOIN vehicules v ON t.vehicule_id=v.id
            WHERE t.statut='en_cours'
            ORDER BY t.date_heure_depart DESC""",
        "exp": "🟢 Trajets en cours en ce moment :"
    },
]

def keyword_fallback(question: str):
    q = question.lower()
    for entry in KEYWORD_QUERIES:
        if any(k in q for k in entry["keys"]):
            return {"sql": entry["sql"].strip(), "explication": entry["exp"]}
    return None


# ── SMALL TALK & CONVERSATIONS ────────────────────────────────
SMALL_TALK_RESPONSES = {
    # Salutations
    "bonjour":      "Bonjour ! 👋 Je suis **TranspoBot**, votre assistant intelligent de gestion de flotte.\nJe peux vous aider sur : recettes, trajets, chauffeurs, véhicules, incidents, rapports mensuels...\nQue souhaitez-vous savoir ?",
    "bonsoir":      "Bonsoir ! 🌙 Je suis **TranspoBot**. Que puis-je faire pour vous ce soir ?\nTrajets du jour, recettes, état de la flotte — je suis disponible.",
    "salut":        "Salut ! 😊 TranspoBot à votre service. Posez-moi vos questions sur la flotte.",
    "hello":        "Hello! 👋 I'm TranspoBot, your fleet management assistant. Ask me anything about trips, drivers, vehicles or revenue!",
    "hey":          "Hey ! Je suis là. Que voulez-vous savoir sur votre flotte ?",
    "hi":           "Hi! TranspoBot here. What can I help you with today?",
    "coucou":       "Coucou ! 😄 TranspoBot est là. Une question sur la flotte ?",
    "salam":        "Wa alaykum salam ! 🤝 Je suis TranspoBot. Comment puis-je vous aider ?",
    "assalamu":     "Wa alaykum salam ! 🤝 TranspoBot à votre service.",

    # Comment ça va
    "ca va":        "Je suis un assistant IA, donc toujours au top ! 😄 Et vous ? Qu'est-ce que je peux faire pour votre flotte aujourd'hui ?",
    "ça va":        "Je suis un assistant IA, donc toujours au top ! 😄 Et vous ? Qu'est-ce que je peux faire pour votre flotte aujourd'hui ?",
    "comment allez": "Je vais très bien, merci de demander ! 😊 Prêt à analyser vos données de flotte. Que souhaitez-vous consulter ?",
    "comment vas":  "Toujours opérationnel ! 🤖 Prêt à analyser vos trajets, recettes et incidents. Que voulez-vous savoir ?",
    "tu vas bien":  "Parfaitement bien, merci ! Je suis prêt à vous aider. Posez votre question.",
    "vous allez bien": "Très bien merci ! Comment puis-je vous aider avec votre flotte ?",

    # Présentations
    "qui es-tu":    "Je suis **TranspoBot** 🤖, un assistant IA spécialisé en gestion de transport urbain au Sénégal.\n\nJe peux vous aider à :\n• 📊 Générer des rapports mensuels\n• 💰 Analyser les recettes et tendances\n• 🚌 Suivre l'état de la flotte\n• 👨‍✈️ Évaluer la performance des chauffeurs\n• ⚠️ Gérer les incidents\n\nPosez-moi une question en langage naturel !",
    "qui etes-vous":"Je suis **TranspoBot** 🤖, votre assistant IA de gestion de flotte pour le projet GLSi ESP/UCAD.\nPosez-moi vos questions sur les trajets, véhicules, chauffeurs ou recettes !",
    "qui es tu":    "Je suis **TranspoBot** 🤖, un assistant IA spécialisé en gestion de transport urbain au Sénégal.\n\nJe peux vous aider à :\n• 📊 Générer des rapports mensuels\n• 💰 Analyser les recettes et tendances\n• 🚌 Suivre l'état de la flotte\n• 👨‍✈️ Évaluer la performance des chauffeurs\n• ⚠️ Gérer les incidents\n\nPosez-moi une question en langage naturel !",
    "présente-toi": "Je suis **TranspoBot** 🤖 — assistant IA de gestion de transport urbain (GLSi L3, ESP/UCAD).\n\nExemples de ce que vous pouvez me demander :\n• *Rapport du mois*\n• *Recette du mois précédent*\n• *Quel chauffeur performe le mieux ?*\n• *Véhicules en maintenance*\n• *Incidents non résolus*",
    "presente-toi": "Je suis **TranspoBot** 🤖 — assistant IA de gestion de transport urbain (GLSi L3, ESP/UCAD).\n\nExemples de ce que vous pouvez me demander :\n• *Rapport du mois*\n• *Recette du mois précédent*\n• *Quel chauffeur performe le mieux ?*\n• *Véhicules en maintenance*\n• *Incidents non résolus*",
    "tu fais quoi": "Je suis **TranspoBot**, votre assistant de gestion de flotte ! 🚌\nJe peux analyser vos données en temps réel :\n• Recettes et tendances financières\n• Performance des chauffeurs et véhicules\n• Rapports mensuels complets\n• Suivi des incidents",
    "what can you do": "I'm TranspoBot 🤖 — I can help you with:\n• Monthly reports & revenue analysis\n• Driver & vehicle performance\n• Incident tracking\n• Fleet status\n\nJust ask in natural language!",
    "aide":         "Voici ce que je sais faire 💡 :\n\n**Recettes :** *recette du mois, recette mois précédent, comparaison, évolution*\n**Rapports :** *rapport mensuel, bilan du mois, synthèse*\n**Chauffeurs :** *meilleur chauffeur, performance, classement, disponibles*\n**Véhicules :** *flotte, maintenance, hors service, kilométrage*\n**Incidents :** *incidents graves, non résolus, par chauffeur*\n**Lignes :** *ligne rentable, trajets par ligne*",
    "help":         "Here's what I can do 💡 :\n\n**Revenue:** *monthly revenue, last month, comparison, trends*\n**Reports:** *monthly report, summary*\n**Drivers:** *best driver, performance, available*\n**Vehicles:** *fleet status, maintenance, mileage*\n**Incidents:** *open incidents, by driver, serious*",

    # Remerciements
    "merci":        "Avec plaisir ! 😊 N'hésitez pas si vous avez d'autres questions sur la flotte.",
    "merci beaucoup": "De rien ! 🙏 Je suis là pour ça. Une autre question ?",
    "thank you":    "You're welcome! 😊 Feel free to ask anything else.",
    "thanks":       "Glad to help! Ask me anything about your fleet.",
    "super":        "Ravi que ça vous aide ! 😊 Autre chose ?",
    "parfait":      "Parfait ! 🎯 Autre chose que je puisse faire pour vous ?",
    "génial":       "Merci ! 😄 N'hésitez pas pour d'autres analyses.",
    "bien":         "Tant mieux ! Une autre question sur la flotte ?",
    "nickel":       "😄 N'hésitez pas pour d'autres questions !",
    "ok merci":     "De rien ! 🙏 À bientôt.",
    "ok":           "D'accord ! Autre chose que je puisse faire pour vous ?",

    # Au revoir
    "au revoir":    "À bientôt ! 👋 Bonne gestion de votre flotte.",
    "bye":          "Bye! 👋 Come back anytime you need fleet insights.",
    "goodbye":      "Goodbye! 👋 Have a great day.",
    "bonne journée":"Bonne journée à vous aussi ! 🌞",
    "bonne soirée": "Bonne soirée ! 🌙 À bientôt.",
    "à bientôt":    "À bientôt ! 👋",
    "a bientot":    "À bientôt ! 👋",

    # Divers
    "test":         "Je fonctionne correctement ! ✅ Posez-moi une vraie question sur votre flotte.",
    "ping":         "Pong ! 🏓 TranspoBot opérationnel.",
    "es-tu là":     "Oui, je suis là ! 🤖 Prêt à vous aider. Quelle est votre question ?",
    "tu es là":     "Oui, je suis là ! 🤖 Prêt à vous aider. Quelle est votre question ?",
    "allo":         "Allô ! 📞 TranspoBot à l'écoute. Que souhaitez-vous savoir ?",
}

def detect_small_talk(q: str) -> str | None:
    """Détecte les messages conversationnels et retourne une réponse, sinon None."""
    q = q.strip().rstrip("?!.,").lower()
    # Correspondance exacte d'abord
    if q in SMALL_TALK_RESPONSES:
        return SMALL_TALK_RESPONSES[q]
    # Correspondance partielle
    for key, response in SMALL_TALK_RESPONSES.items():
        if key in q:
            return response
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

        # ── SMALL TALK & CONVERSATIONS (sans IA, réponses instantanées) ──
        small_talk = detect_small_talk(q_lower)
        if small_talk:
            return {"answer": small_talk, "data": [], "sql": None, "conseil": None}

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
