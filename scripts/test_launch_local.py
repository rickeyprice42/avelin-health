"""Launcher lifecycle tests: no GUI, network, personal data or real child processes."""
import unittest
from unittest.mock import Mock, patch
import launch_local as launcher


class LauncherLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.services = launcher.Services()
        self.valid = patch.object(self.services, "validate", return_value=("python", "node"))
        self.valid.start()
        self.addCleanup(self.valid.stop)

    def test_foreign_port_is_never_killed_or_reused(self):
        with patch.object(launcher, "listening", side_effect=[True, False]), \
             patch.object(self.services, "spawn") as spawn:
            with self.assertRaisesRegex(RuntimeError, "8765"):
                self.services.start()
            spawn.assert_not_called()
        self.assertFalse(self.services.reused)

    def test_existing_healthy_services_are_reused_without_spawning(self):
        with patch.object(launcher, "listening", return_value=True), \
             patch.object(launcher, "api_ready", return_value=True), \
             patch.object(launcher, "web_ready", return_value=True), \
             patch.object(self.services, "spawn") as spawn:
            self.services.start()
            self.services.stop()
            spawn.assert_not_called()
        self.assertTrue(self.services.reused)

    def test_frontend_failure_stops_backend_and_closes_logs(self):
        child = Mock()
        child.poll.return_value = None
        log = Mock()
        def spawn(name, args, env):
            if name == "backend":
                self.services.processes.append(child)
                self.services.logs.append(log)
            else:
                raise OSError("frontend failed")
        with patch.object(launcher, "listening", return_value=False), \
             patch.object(self.services, "spawn", side_effect=spawn), \
             patch.object(self.services, "wait_ready"):
            with self.assertRaisesRegex(OSError, "frontend failed"):
                self.services.start()
        child.terminate.assert_called_once()
        log.close.assert_called_once()
        self.assertEqual(self.services.processes, [])

    def test_stop_is_idempotent(self):
        child = Mock()
        child.poll.return_value = None
        self.services.processes.append(child)
        self.services.stop()
        self.services.stop()
        child.terminate.assert_called_once()

    def test_cancel_interrupts_startup(self):
        self.services.cancel.set()
        ready = Mock()
        with self.assertRaisesRegex(RuntimeError, "отмен"):
            self.services.wait_ready(ready, "Backend")
        ready.assert_not_called()


if __name__ == "__main__":
    unittest.main()
