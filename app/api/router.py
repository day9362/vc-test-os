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
from app.api.overview.rc_bias import router as rc_bias_router
from app.api.overview.pipeline import router as pipeline_router
from app.api.overview.alarms import router as alarms_router
from app.api.overview.ack_alarm import router as ack_alarm_router
from app.api.overview.unack_alarm import router as unack_router
from app.api.overview.ack_all import router as ack_all_router
from app.api.overview.attribution import router as attribution_router
from app.api.overview.attribution_rerun import router as attribution_rerun_router
from app.api.overview.ws import router as ws_router
from app.api.settings.get import router as settings_get_router
from app.api.settings.test_connection import router as settings_test_router
from app.api.settings.jobs_status import router as settings_jobs_router
from app.api.settings.sim_catalog import router as settings_sim_catalog_router
from app.api.settings.sim_actions import router as settings_sim_actions_router

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
api_router.include_router(rc_bias_router)
api_router.include_router(pipeline_router)
api_router.include_router(alarms_router)
api_router.include_router(ack_alarm_router)
api_router.include_router(unack_router)
api_router.include_router(ack_all_router)
api_router.include_router(attribution_router)
api_router.include_router(attribution_rerun_router)
api_router.include_router(ws_router)
api_router.include_router(settings_get_router)
api_router.include_router(settings_test_router)
api_router.include_router(settings_jobs_router)
api_router.include_router(settings_sim_catalog_router)
api_router.include_router(settings_sim_actions_router)
