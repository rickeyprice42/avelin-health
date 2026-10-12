import io
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import chat_history
import local_server


class ChatHistoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "data" / "health.db"

    def test_history_survives_reopening_and_keeps_metadata(self):
        message_id = chat_history.start_turn(self.db, "Привет")
        chat_history.finish_turn(self.db, message_id, "Ответ **текст**", "ollama", "test")
        rows = chat_history.history(self.db)
        self.assertEqual([row["content"] for row in rows], ["Привет", "Ответ **текст**"])
        self.assertEqual(rows[-1]["model"], "test")
        self.assertTrue(rows[-1]["complete"])

    def test_interrupted_and_failed_answers_are_visible_but_not_context(self):
        chat_history.start_turn(self.db, "Первый вопрос")
        message_id = chat_history.start_turn(self.db, "Второй вопрос")
        chat_history.finish_turn(self.db, message_id, "Часть ответа", error="Ошибка")
        rows = chat_history.history(self.db)
        self.assertTrue(rows[1]["error"])
        self.assertEqual(rows[-1]["content"], "Часть ответа")
        self.assertEqual([row["role"] for row in chat_history.context(self.db)], ["user", "user"])

    def test_http_stream_restores_history_after_server_restart(self):
        def request(server, path, data=None):
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}",
                data=json.dumps(data).encode() if data else None,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as response:
                return response.read().decode()

        def start():
            server = ThreadingHTTPServer(("127.0.0.1", 0), local_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, thread

        def stop(server, thread):
            server.shutdown()
            server.server_close()
            thread.join()

        with patch.object(local_server, "DB", self.db), patch.object(local_server, "settings", return_value={"provider":"local"}), patch.object(local_server, "chat", return_value={"text":"Ответ", "mode":"local"}) as answer:
            server, thread = start()
            try:
                events = request(server, "/api/chat", {"messages":[{"role":"user", "content":"Вопрос"}], "stream":True})
                self.assertEqual(json.loads(events.splitlines()[-1])["type"], "done")
            finally:
                stop(server, thread)
            server, thread = start()
            try:
                rows = json.loads(request(server, "/api/chat/history"))["messages"]
                self.assertEqual([row["content"] for row in rows], ["Вопрос", "Ответ"])
                request(server, "/api/chat", {"messages":[{"role":"user", "content":"Продолжим"}]})
                self.assertEqual([row["content"] for row in answer.call_args.args[0]], ["Вопрос", "Ответ", "Продолжим"])
            finally:
                stop(server, thread)

    def test_partial_stream_is_saved_on_provider_error(self):
        message_id = chat_history.start_turn(self.db, "Вопрос")
        handler = object.__new__(local_server.Handler)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None

        def events(messages):
            yield {"type":"status", "mode":"ollama", "model":"test"}
            yield {"type":"delta", "text":"Часть ответа"}
            raise RuntimeError("Ошибка модели")

        with patch.object(local_server, "DB", self.db), patch.object(local_server, "settings", return_value={"provider":"ollama"}), patch.object(local_server, "ollama_events", side_effect=events):
            handler.chat_stream(chat_history.context(self.db), message_id)
        answer = chat_history.history(self.db)[-1]
        self.assertEqual(answer["content"], "Часть ответа")
        self.assertEqual(answer["error"], "Ошибка модели")
        self.assertFalse(answer["complete"])
        self.assertEqual(answer["model"], "test")


if __name__ == "__main__":
    unittest.main()
