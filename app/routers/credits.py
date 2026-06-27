from fastapi import APIRouter

from app.suno_client import SunoAPIClient


router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.get("")
async def get_remaining_credits():
    return await SunoAPIClient().get_remaining_credits()
