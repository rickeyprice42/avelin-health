import io
import json
import unittest
from unittest.mock import patch
import llm_provider as llm

CONFIG = {"provider":"ollama","key":"test","model":"test","baseUrl":"https://ollama.com"}

class StreamingTest(unittest.TestCase):
    def test_content_arrives_before_done(self):
        with patch.object(llm, "request_chat_stream", return_value=iter([
            {"message":{"content":"Hello","thinking":"private"}},
            {"message":{"content":" world"},"done":True}])):
            events = llm.ollama_events([{"role":"user","content":"test"}], CONFIG)
            self.assertEqual(next(events)["type"], "status")
            self.assertEqual(next(events), {"type":"delta","text":"Hello"})
            self.assertEqual(next(events), {"type":"delta","text":" world"})
            self.assertEqual(next(events)["type"], "done")

    def test_stream_tools_keep_thinking_private_and_return_results(self):
        rounds = [
            iter([{"message":{"thinking":"private","tool_calls":[{"function":{"index":0,"name":"get_daily_summary","arguments":{"date":"2000-01-01"}}}]},"done":True}]),
            iter([{"message":{"content":"1234 steps"},"done":True}]),
        ]
        with patch.object(llm,"request_chat_stream",side_effect=rounds) as request, patch.dict(llm.TOOLS,{"get_daily_summary":{"call":lambda date: {"steps":1234}}}):
            events = list(llm.ollama_events([{"role":"user","content":"test"}],CONFIG))
        self.assertEqual(events[-1]["usedTools"], ["get_daily_summary"])
        self.assertNotIn("private", json.dumps(events))
        history = request.call_args.args[0]["messages"]
        self.assertEqual(history[-2]["thinking"], "private")
        self.assertEqual(json.loads(history[-1]["content"]), {"steps":1234})

    def test_incomplete_provider_stream_raises(self):
        response = io.BytesIO(b'{"message":{"content":"partial"}}\n')
        with patch.object(llm.urllib.request,"urlopen",return_value=response):
            with self.assertRaises(RuntimeError):
                list(llm.request_chat_stream({}, CONFIG))

    def test_provider_error_body_is_not_exposed(self):
        response = io.BytesIO(b'{"error":"secret-key"}\n')
        with patch.object(llm.urllib.request,"urlopen",return_value=response):
            with self.assertRaises(RuntimeError) as caught:
                list(llm.request_chat_stream({},CONFIG))
        self.assertNotIn("secret-key",str(caught.exception))

if __name__ == "__main__":
    unittest.main()
