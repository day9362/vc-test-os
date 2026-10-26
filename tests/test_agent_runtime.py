import unittest

from app.core.errors import AppError
from app.service.agent.sessions import AgentStore


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_module(self) -> None:
        with self.assertRaises(AppError) as caught:
            AgentStore().create("u1", "agent.other")
        self.assertEqual(caught.exception.status, 422)

    async def test_hides_another_users_session(self) -> None:
        store = AgentStore()
        session = store.create("u1", "agent.ops")
        with self.assertRaises(AppError) as caught:
            store.get("u2", session.session_id)
        self.assertEqual(caught.exception.status, 404)
