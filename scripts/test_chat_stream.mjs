import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { readChatEvents, markdownForDisplay } from "../src/chatStream.ts";

test("NDJSON survives every UTF-8 byte boundary and final line without newline", async () => {
  const events = [{type:"delta",text:"Привет 🥗"}, {type:"done",mode:"ollama"}];
  const bytes = new TextEncoder().encode(events.map(JSON.stringify).join("\n"));
  const body = new ReadableStream({start(controller){for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close();}});
  const received = [];
  for await (const event of readChatEvents(body)) received.push(event);
  assert.deepEqual(received, events);
});
test("Markdown renders headings, emphasis, lists and separators safely", () => {
  const content = markdownForDisplay("### Завтрак\n\n**Белок**\n\n* Яйца\n* Творог\n\n1. Приготовь\n2. Съешь\n\n--\n\n<script>alert(1)</script>\n\n[опасная ссылка](javascript:alert)", false);
  const html = renderToStaticMarkup(React.createElement(Markdown, {remarkPlugins:[remarkGfm],skipHtml:true}, content));
  for (const tag of ["<h3>","<strong>","<ul>","<ol>","<hr"]) assert.ok(html.includes(tag), tag);
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes('href="javascript:'));
});
test("unfinished streamed formatting hides pending markers", () => {
  assert.equal(markdownForDisplay("**Белок",true), "**Белок**");
  assert.equal(markdownForDisplay("Текст\n###",true), "Текст");
  assert.equal(markdownForDisplay("**Белок",false), "**Белок");
});
