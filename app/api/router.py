from fastapi import APIRouter

from app.api.auth.login import router as login_router
from app.api.auth.logout import router as logout_router
from app.api.auth.me import router as me_router
from app.api.auth.tenants import router as tenants_router
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
from app.api.realtime.ws import router as ws_router
from app.api.machines.power_on import router as power_on_router
from app.api.machines.power_off import router as power_off_router
from app.api.machines.maintenance import router as maintenance_router
from app.api.machines.reset import router as reset_router
from app.api.machines.plan_history import router as plan_history_router
from app.api.test_plan.list_plans import router as list_plans_router
from app.api.test_plan.validate_plan import router as validate_plan_router
from app.api.test_plan.publish_plan import router as publish_plan_router
from app.api.test_plan.create_draft import router as create_draft_router
from app.api.test_plan.draft_from_text import router as draft_from_text_router
from app.api.test_plan.update_draft import router as update_draft_router
from app.api.test_plan.delete_draft import router as delete_draft_router
from app.api.test_plan.plan_detail import router as plan_detail_router
from app.api.runs.list import router as runs_list_router
from app.api.runs.detail import router as runs_detail_router
from app.api.runs.samples import router as runs_samples_router
from app.api.runs.ground_truth import router as runs_ground_truth_router
from app.api.runs.export import router as runs_export_router
from app.api.reports.data import router as reports_data_router
from app.api.reports.export import router as reports_export_router
from app.api.compensation.channel_bias import router as channel_bias_router
from app.api.compensation.suggestion import router as suggestion_router
from app.api.compensation.history import router as compensation_history_router
from app.api.compensation.compensation import router as compensation_router
from app.api.compensation.drifts import router as drifts_router
from app.api.settings.get import router as settings_get_router
from app.api.settings.test_connection import router as settings_test_router
from app.api.settings.jobs_status import router as settings_jobs_router
from app.api.settings.sim_catalog import router as settings_sim_catalog_router
from app.api.settings.sim_actions import router as settings_sim_actions_router
from app.api.search.get import router as search_router
from app.api.audit.list import router as audit_router
from app.api.production.models import router as models_router
from app.api.production.batches import router as batches_router
from app.api.production.batch_stats import router as batch_stats_router
from app.api.production.batch_stat import router as batch_stat_router
from app.api.production.get import router as production_router
from app.api.production.precheck import router as precheck_router
from app.api.production.start import router as production_start_router
from app.api.production.stop import router as production_stop_router
from app.api.agent.create_session import router as agent_create_router
from app.api.agent.get_session import router as agent_get_router
from app.api.agent.send_message import router as agent_send_router

api_router = APIRouter()
api_router.include_router(login_router)
api_router.include_router(logout_router)
api_router.include_router(me_router)
api_router.include_router(tenants_router)
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
api_router.include_router(power_on_router)
api_router.include_router(power_off_router)
api_router.include_router(maintenance_router)
api_router.include_router(reset_router)
api_router.include_router(plan_history_router)
api_router.include_router(list_plans_router)
api_router.include_router(validate_plan_router)
api_router.include_router(publish_plan_router)
api_router.include_router(draft_from_text_router)
api_router.include_router(create_draft_router)
api_router.include_router(update_draft_router)
api_router.include_router(delete_draft_router)
api_router.include_router(plan_detail_router)
api_router.include_router(runs_list_router)
api_router.include_router(runs_samples_router)
api_router.include_router(runs_ground_truth_router)
api_router.include_router(runs_detail_router)
api_router.include_router(runs_export_router)
api_router.include_router(reports_data_router)
api_router.include_router(reports_export_router)
api_router.include_router(channel_bias_router)
api_router.include_router(suggestion_router)
api_router.include_router(compensation_history_router)
api_router.include_router(compensation_router)
api_router.include_router(drifts_router)
api_router.include_router(settings_get_router)
api_router.include_router(settings_test_router)
api_router.include_router(settings_jobs_router)
api_router.include_router(settings_sim_catalog_router)
api_router.include_router(settings_sim_actions_router)
api_router.include_router(search_router)
api_router.include_router(audit_router)
api_router.include_router(models_router)
api_router.include_router(batches_router)
api_router.include_router(batch_stats_router)
api_router.include_router(batch_stat_router)
api_router.include_router(production_router)
api_router.include_router(precheck_router)
api_router.include_router(production_start_router)
api_router.include_router(production_stop_router)
api_router.include_router(agent_create_router)
api_router.include_router(agent_get_router)
api_router.include_router(agent_send_router)
