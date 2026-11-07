import unittest

from app.service.audit_note import audit_note
from app.service.settings.changes import describe_settings_changes


class SettingsChangeTest(unittest.TestCase):
    def test_names_each_changed_setting_without_the_token(self) -> None:
        before = {
            "source": "sim",
            "cluster": {"token": "secret-old", "timeout_s": 5},
            "ai": {"model": "deepseek-flash", "monthly_budget_m": 120, "alert_pct": 80},
            "rules": {"degraded_alarm": True},
            "jobs": [{"key": "fleet", "name": "机群状态", "interval_s": 2, "enabled": True}],
        }
        after = {
            "source": "cluster",
            "cluster": {"token": "secret-new", "timeout_s": 8},
            "ai": {"model": "deepseek-v3", "monthly_budget_m": 80, "alert_pct": 80},
            "rules": {"degraded_alarm": False},
            "jobs": [{"key": "fleet", "name": "机群状态", "interval_s": 2, "enabled": False}],
        }
        changes = describe_settings_changes(before, after)
        self.assertEqual(
            changes,
            [
                "数据源改为 真实集群",
                "修改了集群令牌",
                "请求超时改为 8 秒",
                "停用机群状态",
                "共用模型改为 deepseek-v3",
                "月度预算改为 80 M tokens",
                "关闭通信降级告警",
            ],
        )
        self.assertNotIn("secret-new", " ".join(changes))

    def test_audit_note_lists_the_user_and_the_changes(self) -> None:
        text = audit_note("admin", "settings.save", "", {"changes": ["月度预算改为 80 M tokens", "预算提醒改为 70%"]}, {"count": 2})
        self.assertEqual(text, "admin 修改了系统设置：月度预算改为 80 M tokens、预算提醒改为 70%")


if __name__ == "__main__":
    unittest.main()
