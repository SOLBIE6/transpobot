from fastapi import APIRouter
from db import execute_query

router = APIRouter()

@router.get("/chauffeurs")
def get_chauffeurs():
    return execute_query("""
        SELECT 
            c.*,
            v.immatriculation
        FROM chauffeurs c
        LEFT JOIN vehicules v ON c.vehicule_id = v.id
        ORDER BY c.nom ASC, c.prenom ASC
    """)