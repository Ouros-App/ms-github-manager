import unittest

from app.core.config import get_settings, reset_worker_settings, set_worker_settings


class Env:
    GH_TOKEN = "worker-token"
    GH_TIMEOUT_SECONDS = "5"


class WorkerSettingsTest(unittest.TestCase):
    def test_worker_settings_are_request_scoped(self):
        before = get_settings()
        token = set_worker_settings(Env())
        try:
            current = get_settings()
            self.assertEqual(current.GH_TOKEN, "worker-token")
            self.assertEqual(current.GH_TIMEOUT_SECONDS, 5)
        finally:
            reset_worker_settings(token)
        self.assertIs(get_settings(), before)
