import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import llm_provider as llm
import local_server


CONFIG = {"provider":"ollama","key":"test-key","model":"test-model","baseUrl":"https://ollama.com"}


class OllamaAdapterTest(unittest.TestCase):
    def test_tool_call_roundtrip_preserves_system_message_and_result(self):
        replies = [
            {"message":{"role":"assistant","content":"","tool_calls":[
                {"function":{"name":"get_daily_summary","arguments":{"date":"2000-01-01"}}}]}},
            {"message":{"role":"assistant","content":"1234 steps"}},
        ]
        with patch.object(llm, "request_chat", side_effect=replies) as request, \
             patch.dict(llm.TOOLS, {"get_daily_summary":{"call":lambda date: {"steps":1234}}}):
            result = llm.ollama_chat([{"role":"user","content":"test"}], CONFIG)
        self.assertEqual(result["mode"], "ollama")
        self.assertEqual(result["usedTools"], ["get_daily_summary"])
        payload = request.call_args.args[0]
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][-1]["role"], "tool")
        self.assertEqual(json.loads(payload["messages"][-1]["content"]), {"steps":1234})
        self.assertEqual(len(payload["tools"]), 7)

    def test_unknown_tool_is_not_executed(self):
        replies = [{"message":{"tool_calls":[{"function":{"name":"delete_all_data","arguments":{}}}]}},
                   {"message":{"content":"Unavailable"}}]
        with patch.object(llm,"request_chat",side_effect=replies) as request:
            llm.ollama_chat([{"role":"user","content":"test"}],CONFIG)
        result = json.loads(request.call_args.args[0]["messages"][-1]["content"])
        self.assertEqual(result["error"],"unknown_tool")

    def test_loop_limit_stops_repeated_calls(self):
        reply = {"message":{"tool_calls":[{"function":{"name":"unknown","arguments":{}}}]}}
        with patch.object(llm,"request_chat",return_value=reply) as request:
            with self.assertRaisesRegex(RuntimeError,"лимит"):
                llm.ollama_chat([{"role":"user","content":"test"}],CONFIG)
        self.assertEqual(request.call_count,12)

    def test_provider_error_never_falls_back_to_openai(self):
        with patch.object(local_server,"settings",return_value=CONFIG), \
             patch.object(local_server,"ollama_chat",side_effect=RuntimeError("Ollama failed")), \
             patch.object(local_server,"openai_chat") as openai:
            with self.assertRaisesRegex(RuntimeError,"Ollama failed"):
                local_server.chat([{"role":"user","content":"test"}])
        openai.assert_not_called()

    def test_http_error_does_not_expose_provider_body(self):
        import io
        error = HTTPError("https://ollama.com/api/chat",401,"test",{},io.BytesIO(b"private-input secret-key"))
        with patch.object(llm.urllib.request,"urlopen",side_effect=error):
            with self.assertRaisesRegex(RuntimeError,"HTTP 401") as caught:
                llm.request_chat({},CONFIG)
        self.assertNotIn("secret-key",str(caught.exception))
        self.assertNotIn("private-input",str(caught.exception))

    def test_status_never_contains_key(self):
        with patch.object(llm,"settings",return_value=CONFIG):
            status = llm.public_status()
        self.assertTrue(status["llmConfigured"])
        self.assertEqual(status["llmProvider"],"ollama")
        self.assertNotIn("test-key",json.dumps(status))

    def test_explicit_local_mode_overrides_environment_keys(self):
        with patch.object(llm,"CONFIG",Path("missing-config")), \
             patch.dict(llm.os.environ,{"AVELIN_LLM_PROVIDER":"local","OLLAMA_API_KEY":"test-key"},clear=True):
            self.assertEqual(llm.settings()["provider"],"local")

    def test_cloud_without_key_fails_before_network(self):
        with patch.object(llm,"request_chat") as request:
            with self.assertRaisesRegex(RuntimeError,"API_KEY"):
                llm.ollama_chat([], {**CONFIG,"key":""})
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
