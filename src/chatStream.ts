export type ChatEvent = { type: "delta" | "status" | "done" | "error"; text?: string; mode?: string; model?: string };

export async function* readChatEvents(body: ReadableStream<Uint8Array>) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline).trim();
        pending = pending.slice(newline + 1);
        if (line) yield JSON.parse(line) as ChatEvent;
      }
      if (done) break;
    }
    if (pending.trim()) yield JSON.parse(pending) as ChatEvent;
  } finally { reader.releaseLock(); }
}

export function markdownForDisplay(text: string, streaming: boolean) {
  let result = text.replace(/^[ \t]*--[ \t]*$/gm, "---");
  if (!streaming) return result;
  result = result.replace(/(^|\n)#{1,6}[ \t]*$/, "").replace(/(^|\n)[*-][ \t]*$/, "");
  if ((result.match(/\*\*/g)?.length ?? 0) % 2) result += "**";
  const fence = String.fromCharCode(96).repeat(3);
  if (result.split("\n").filter(line => line.startsWith(fence)).length % 2) result += "\n" + fence;
  return result;
}
