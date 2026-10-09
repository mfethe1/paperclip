import unittest
import uuid

import runtime


class ClosedRuntimeTests(unittest.TestCase):
    def test_transport_closed(self):
        self.assertEqual(runtime.MACHINE, "paperclip-executor-184991")
        self.assertFalse(runtime.DEDICATED_RUNTIME_QUALIFIED)
        with self.assertRaisesRegex(RuntimeError, "DEDICATED_RUNTIME_UNPROVISIONED"):
            runtime.transport("true")

    def test_command_closed(self):
        with self.assertRaisesRegex(RuntimeError, "DEDICATED_RUNTIME_UNPROVISIONED"):
            runtime.run_command("print(1)", timeout=1)

    def test_model_closed(self):
        with self.assertRaisesRegex(RuntimeError, "OAUTH_BROKER_UNQUALIFIED"):
            runtime.run_model_task(model="gpt-6.1-sol", provider="openai-codex")

    def test_input_bounds(self):
        for timeout in (True, 0, 11):
            with self.assertRaises(ValueError):
                runtime.run_command("print(1)", timeout=timeout)
        with self.assertRaises(ValueError):
            runtime.run_command("x" * 65537)
        with self.assertRaises(ValueError):
            runtime.run_command("print(1)", token="not-a-uuid")
        with self.assertRaisesRegex(RuntimeError, "DEDICATED_RUNTIME_UNPROVISIONED"):
            runtime.cancel(str(uuid.uuid4()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
