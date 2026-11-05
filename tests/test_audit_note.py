import unittest

from app.service.audit_note import audit_note


class AuditNoteTest(unittest.TestCase):
    def test_clock_names_the_user_and_speed(self) -> None:
        self.assertEqual(audit_note("admin", "sim.clock", "", {"speed": 10}, {}), "admin 把仿真倍率改为 ×10")

    def test_fault_includes_the_machine(self) -> None:
        text = audit_note("limingyuan", "sim.fault", "M01", {"kind": "VACUUM_LEAK", "slot_index": 7}, {})
        self.assertEqual(text, "limingyuan 给 M01 的 7 号槽注入了故障 VACUUM_LEAK")

    def test_unknown_action_still_names_the_user(self) -> None:
        self.assertEqual(audit_note("admin", "custom.op", "", {}, {}), "admin 执行了 custom.op")


if __name__ == "__main__":
    unittest.main()
