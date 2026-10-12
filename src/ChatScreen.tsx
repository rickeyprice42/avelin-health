import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, LoaderCircle, Send, Sparkles } from "lucide-react";
import { markdownForDisplay, readChatEvents } from "./chatStream";
import { ChatRecipe, recipeParts } from "./Recipes";

type Message = { role: "user" | "assistant"; content: string; mode?: string; model?: string; error?: string; complete: boolean };

export function ChatScreen({ onRecipes }: { onRecipes: (id: string) => void }) {
  const [messages, setMessages] = useState<Message[]>([{ role: "assistant", content: "Привет! Я Avelin. Помогу разобраться в твоих данных и подобрать питание. Что хочешь узнать?", complete: true }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [status, setStatus] = useState("Готовлю ответ…");
  const viewport = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const active = useRef(false);
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef("");
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; controller.current?.abort(); if (timer.current) clearTimeout(timer.current); };
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/chat/history", { signal: abort.signal });
        if (!response.ok) throw new Error("Не удалось загрузить историю. Обнови страницу, чтобы повторить.");
        const result = await response.json();
        if (!Array.isArray(result.messages)) throw new Error("Не удалось загрузить историю. Обнови страницу, чтобы повторить.");
        if (!abort.signal.aborted && result.messages.length) setMessages(result.messages);
      } catch (error) {
        if (!abort.signal.aborted) setHistoryError(error instanceof Error ? error.message : "Не удалось загрузить историю.");
      } finally { if (!abort.signal.aborted) setLoading(false); }
    }
    load();
    return () => abort.abort();
  }, []);
  useEffect(() => {
    if (follow.current && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [messages, busy, status]);

  async function send(value = input) {
    const text = value.trim();
    if (!text || active.current || loading || historyError) return;
    active.current = true;
    follow.current = true;
    pending.current = "";
    const history: Message[] = [...messages, { role: "user", content: text, complete: true }];
    const index = history.length;
    setMessages([...history, { role: "assistant", content: "", complete: false }]);
    setInput(""); setBusy(true); setStatus("Готовлю ответ…");
    const abort = new AbortController();
    controller.current = abort;
    const update = (change: Partial<Message>) => {
      if (mounted.current) setMessages(previous => previous.map((message, i) => i === index ? { ...message, ...change } : message));
    };
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const paint = () => {
      if (!mounted.current || abort.signal.aborted) { timer.current = null; return; }
      const characters = Array.from(pending.current);
      const part = characters.slice(0, reduced ? characters.length : Math.min(20, Math.max(1, Math.ceil(characters.length / 25)))).join("");
      pending.current = pending.current.slice(part.length);
      if (part) setMessages(previous => previous.map((message, i) => i === index ? { ...message, content: message.content + part } : message));
      timer.current = pending.current ? setTimeout(paint, 25) : null;
    };
    const enqueue = (chunk: string) => { pending.current += chunk; if (timer.current === null) paint(); };
    const drain = async () => { while (pending.current && mounted.current && !abort.signal.aborted) await new Promise(resolve => setTimeout(resolve, 25)); };
    try {
      const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: [{ role: "user", content: text }], stream: true }), signal: abort.signal });
      if (!response.ok) { const result = await response.json(); throw new Error(result.error || "Не удалось получить ответ."); }
      if (!response.headers.get("content-type")?.includes("application/x-ndjson")) {
        const result = await response.json();
        enqueue(result.text || result.content || result.reply || "");
        await drain();
        update({ mode: result.mode, model: result.model, complete: true });
      } else {
        if (!response.body) throw new Error("Браузер не поддерживает потоковый ответ.");
        let completed = false;
        for await (const event of readChatEvents(response.body)) {
          if (event.type === "delta") enqueue(event.text || "");
          if (event.type === "status") {
            if (mounted.current) setStatus(event.text || "Готовлю ответ…");
            if (event.mode) update({ mode: event.mode, model: event.model });
          }
          if (event.type === "error") throw new Error(event.text || "Не удалось получить ответ.");
          if (event.type === "done") { completed = true; update({ mode: event.mode, model: event.model }); }
        }
        await drain();
        if (!completed) throw new Error("Соединение прервалось. Попробуй отправить сообщение ещё раз.");
        update({ complete: true });
      }
    } catch (error) {
      if (!abort.signal.aborted) { await drain(); update({ error: error instanceof Error ? error.message : "Не удалось получить ответ." }); }
    } finally { active.current = false; if (mounted.current) setBusy(false); }
  }

  return <div className="chat-page"><header><div><p className="eyebrow">ПЕРСОНАЛЬНЫЙ ПОМОЩНИК</p><h1>Агент Avelin</h1><p className="subtitle">Ответы на основе твоих данных</p></div></header><section className="chat-panel panel">
    <div className="chat-header"><div className="chat-avatar"><Sparkles size={20}/></div><div><h3>Агент Avelin</h3><p>Твой помощник по здоровью и питанию</p></div></div>
    <div className="messages" ref={viewport} onScroll={() => { const element = viewport.current; if (element) follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; }}>
      {loading && <p role="status">Загружаю историю…</p>}
      {historyError && <p className="chat-error" role="alert">{historyError}</p>}
      {messages.map((message, index) => <article key={index} className={`message ${message.role}`}>
        {message.role === "assistant" && <div className="avatar"><Bot size={18}/></div>}
        <div className="message-body">
          {message.role === "assistant" ? <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={{
            a: props => <a href={props.href} target="_blank" rel="noopener noreferrer">{props.children}</a>,
            table: props => <div className="markdown-table"><table>{props.children}</table></div>,
            img: props => <span>{props.alt || "Изображение"}</span>,
          }}>{markdownForDisplay(recipeParts(message.content).text, busy && index === messages.length - 1)}</Markdown>{message.complete && !message.error && recipeParts(message.content).cards.map((data, i) => <ChatRecipe key={i} data={data} onOpen={onRecipes}/>)}</div> : <p>{message.content}</p>}
          {busy && index === messages.length - 1 && <div className="typing-status" role="status">{message.content ? <><span className="typing-caret"/>Печатает…</> : <><LoaderCircle size={14} className="spin"/>{status}</>}</div>}
          {message.error && <p className="chat-error" role="alert">{message.error}</p>}
          {message.mode && <small className="message-mode">{message.mode === "ollama" ? `Ollama · ${message.model || "Gemma"}` : message.mode === "local" ? "Локальный помощник" : "Avelin"}</small>}
        </div>
      </article>)}
    </div>
    <div className="suggestions">{["Что можно съесть на ужин?", "Как выглядела моя активность за неделю?", "Каких данных мне не хватает?"].map(text => <button key={text} disabled={busy || loading || !!historyError} onClick={() => send(text)}>{text}</button>)}</div>
    <form className="composer" onSubmit={event => { event.preventDefault(); send(); }}>
      <input aria-label="Сообщение агенту" value={input} onChange={event => setInput(event.target.value)} placeholder="Спроси Avelin…" />
      <button type="submit" disabled={busy || loading || !!historyError || !input.trim()} aria-label="Отправить сообщение">{busy ? <LoaderCircle size={18} className="spin"/> : <Send size={18}/>}</button>
    </form>
  </section></div>;
}
