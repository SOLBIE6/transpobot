from fastapi import APIRouter
from db import execute_query
 
router = APIRouter()
 
@router.get("/incidents")
def get_incidents():
    return execute_query("""
        SELECT i.*,
               CONCAT(ch.nom, ' ', ch.prenom) as chauffeur_nom,
               l.nom as ligne
        FROM incidents i
        LEFT JOIN trajets t   ON i.trajet_id   = t.id
        LEFT JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        LEFT JOIN lignes l    ON t.ligne_id    = l.id
        ORDER BY i.date_incident DESC
    """)
 
# 🔥 BONUS (optionnel)
@router.get("/incidents/graves")
def get_incidents_graves():
    return execute_query("""
        SELECT *
        FROM incidents
        WHERE gravite = 'grave'
        ORDER BY date_incident DESC
    """)