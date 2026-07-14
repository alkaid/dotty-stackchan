// Thin OpenAI-compatible chat-completions client used by voice tools.
// Lives next to brain_db.ts because the thinker endpoint is the other
// infrastructure dependency the extension talks to from inside dotty-pi.
//
// We don't generalise — voice tools touch a tiny slice of the OpenAI
// API and bridge.py never grew an abstraction either. Each consuming
// tool builds its own request body via a pure helper so the test rig
// can diff against bridge.py's exact shape.

const DEFAULT_TIMEOUT_SEC = Number(process.env.VOICE_THINKER_TIMEOUT ?? "30");

function defaultUrl(): string {
  const explicit = process.env.VOICE_THINKER_URL?.trim();
  if (explicit) return explicit;
  const base = (
    process.env.DOTTY_PI_BASE_URL ??
    "https://DOTTY_PI_BASE_URL_PLACEHOLDER/v1"
  ).replace(/\/+$/, "");
  return `${base}/chat/completions`;
}

function defaultApiKey(): string | undefined {
  return process.env.VOICE_THINKER_API_KEY || process.env.DOTTY_PI_API_KEY;
}

export interface ChatCompletionRequest {
  model: string;
  messages: Array<{ role: "system" | "user" | "assistant"; content: string }>;
  max_tokens: number;
  temperature: number;
  stream: boolean;
  chat_template_kwargs?: Record<string, unknown>;
  reasoning_effort?: string;
}

export class TimeoutError extends Error {
  readonly isTimeout = true as const;
}

export interface PostOptions {
  url?: string;
  timeoutSec?: number;
  apiKey?: string;
}

/**
 * POST a chat-completion request and return the assistant content. The
 * caller is responsible for shaping {@link ChatCompletionRequest} —
 * keeping the body construction in each tool's pure helper means the
 * oracle tests can diff request bodies without going through this fn.
 *
 * Throws {@link TimeoutError} on AbortSignal timeout; throws Error
 * subclasses on non-2xx / parse failures / network errors.
 */
export async function postChatCompletion(
  body: ChatCompletionRequest,
  opts: PostOptions = {},
): Promise<string> {
  const url = opts.url ?? defaultUrl();
  const timeoutMs = (opts.timeoutSec ?? DEFAULT_TIMEOUT_SEC) * 1000;
  const apiKey = opts.apiKey || defaultApiKey();
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(apiKey
          ? { authorization: `Bearer ${apiKey}` }
          : {}),
      },
      body: JSON.stringify(body),
      signal: ac.signal,
    });
    if (!resp.ok) {
      throw new Error(`thinker endpoint HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    return data.choices?.[0]?.message?.content ?? "";
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new TimeoutError(`thinker endpoint timeout after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
