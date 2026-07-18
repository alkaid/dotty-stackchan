// Thin OpenAI-compatible client used by voice tools.
// Lives next to brain_db.ts because the thinker endpoint is the other
// infrastructure dependency the extension talks to from inside dotty-pi.
//
// The outer pi loop and think_hard share DOTTY_PI_PROVIDER_API so a deployment
// can move both paths to Responses without breaking local Chat Completions
// backends.

const DEFAULT_TIMEOUT_SEC = Number(process.env.VOICE_THINKER_TIMEOUT ?? "30");

export type OpenAIApi = "openai-completions" | "openai-responses";

export const WEB_SEARCH_TOOL = { type: "web_search" } as const;

export function configuredOpenAIApi(
  env: Record<string, string | undefined> = process.env,
): OpenAIApi {
  return env.DOTTY_PI_PROVIDER_API?.trim() === "openai-responses"
    ? "openai-responses"
    : "openai-completions";
}

function defaultUrl(api: OpenAIApi): string {
  const explicit = process.env.VOICE_THINKER_URL?.trim();
  if (explicit) return explicit;
  const base = (
    process.env.DOTTY_PI_BASE_URL ??
    "https://DOTTY_PI_BASE_URL_PLACEHOLDER/v1"
  ).replace(/\/+$/, "");
  return api === "openai-responses"
    ? `${base}/responses`
    : `${base}/chat/completions`;
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

export interface ResponsesRequest {
  model: string;
  instructions: string;
  input: string;
  max_output_tokens: number;
  stream: false;
  store: false;
  tools: Array<typeof WEB_SEARCH_TOOL>;
  reasoning?: { effort: string };
}

export type OpenAIRequest = ChatCompletionRequest | ResponsesRequest;

export class TimeoutError extends Error {
  readonly isTimeout = true as const;
}

export interface PostOptions {
  url?: string;
  timeoutSec?: number;
  apiKey?: string;
  api?: OpenAIApi;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function responseText(data: unknown): string {
  if (!isRecord(data)) return "";
  const output = Array.isArray(data.output) ? data.output : [];
  const text = output
    .flatMap((item) => {
      if (!isRecord(item) || item.type !== "message") return [];
      const content = Array.isArray(item.content) ? item.content : [];
      return content.flatMap((part) =>
        isRecord(part)
        && part.type === "output_text"
        && typeof part.text === "string"
          ? [part.text]
          : []
      );
    })
    .join("");
  return text || (typeof data.output_text === "string" ? data.output_text : "");
}

/** POST a Chat Completions or Responses request and return assistant text. */
export async function postOpenAIRequest(
  body: OpenAIRequest,
  opts: PostOptions = {},
): Promise<string> {
  const api = opts.api ?? configuredOpenAIApi();
  const url = opts.url ?? defaultUrl(api);
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
    const data = await resp.json() as unknown;
    if (api === "openai-responses") return responseText(data);
    if (!isRecord(data) || !Array.isArray(data.choices)) return "";
    const choice = data.choices[0];
    if (!isRecord(choice) || !isRecord(choice.message)) return "";
    return typeof choice.message.content === "string"
      ? choice.message.content
      : "";
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new TimeoutError(`thinker endpoint timeout after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
