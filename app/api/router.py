from fastapi import APIRouter

from app.api.auth.login import router as login_router
from app.api.auth.logout import router as logout_router
from app.api.auth.me import router as me_router

api_router = APIRouter()
api_router.include_router(login_router)
api_router.include_router(logout_router)
api_router.include_router(me_router)
