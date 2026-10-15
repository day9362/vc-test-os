from fastapi import APIRouter

from app.api.auth.login import router as login_router
from app.api.auth.logout import router as logout_router
from app.api.auth.me import router as me_router
from app.api.overview.machines import router as machines_router
from app.api.overview.machine_detail import router as machine_detail_router
from app.api.overview.slot_curve import router as curve_router
from app.api.overview.kpi import router as kpi_router
from app.api.overview.agg5m import router as agg5m_router
from app.api.overview.anomaly_trend import router as anomaly_router

api_router = APIRouter()
api_router.include_router(login_router)
api_router.include_router(logout_router)
api_router.include_router(me_router)
api_router.include_router(machines_router)
api_router.include_router(machine_detail_router)
api_router.include_router(curve_router)
api_router.include_router(kpi_router)
api_router.include_router(agg5m_router)
api_router.include_router(anomaly_router)
