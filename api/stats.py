from fastapi import APIRouter
from db import execute_query

router = APIRouter()

@router.get("/stats")
def stats():
    return {
        "total_trajets":     int(execute_query("SELECT COUNT(*) as n FROM trajets WHERE statut='termine'")[0]["n"]),
        "trajets_en_cours":  int(execute_query("SELECT COUNT(*) as n FROM trajets WHERE statut='en_cours'")[0]["n"]),
        "vehicules_actifs":  int(execute_query("SELECT COUNT(*) as n FROM vehicules WHERE statut='actif'")[0]["n"]),
        "incidents_ouverts": int(execute_query("SELECT COUNT(*) as n FROM incidents WHERE resolu=0")[0]["n"]),
        "recette_totale":    float(execute_query("SELECT COALESCE(SUM(recette), 0) as n FROM trajets WHERE statut='termine'")[0]["n"]),
    }