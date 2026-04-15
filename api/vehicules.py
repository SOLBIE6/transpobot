from fastapi import APIRouter
from db import execute_query

router = APIRouter()

@router.get("/vehicules")
def vehicules():
    return execute_query("SELECT * FROM vehicules ORDER BY immatriculation")