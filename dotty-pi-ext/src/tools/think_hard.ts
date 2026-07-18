// think_hard voice tool — pi-extension port of
// bridge.py:_voice_tool_think_hard (lines ~3998-4038).
//
// Bypasses the agent loop entirely: a direct POST to the configured
// OpenAI-compatible thinker endpoint. This keeps the normal voice route
// and the deeper think_hard route switchable independently.
//
// Contract (must match Python so the LLM's tuned-for prompt behaviour
// holds):
//   - Empty / whitespace question → "(empty question)"
//   - Timeout                     → "(I'm slow today, try again in a moment)"
//   - Other error                 → "(thinking failed)"
//   - Success                     → trimmed content, truncated to 500 chars

import { Type } from "typebox";
import {
  configuredOpenAIApi,
  type OpenAIApi,
  type OpenAIRequest,
  postOpenAIRequest,
  TimeoutError,
  type ChatCompletionRequest,
  type ResponsesRequest,
  WEB_SEARCH_TOOL,
} from "../lib/llama_swap.ts";

const DEFAULT_MODEL = process.env.VOICE_THINKER_MODEL ?? "dotty-think";
const SYSTEM_PROMPT =
  "Answer the user's question concisely in 1-2 sentences. Be precise.";
const MAX_OUTPUT_CHARS = 500;
const MAX_SEARCH_INPUT_CHARS = 2000;
const SEARCH_TOOL_BLOCK_REASON =
  "Local tools are disabled after web search for this session.";

export function createSearchIsolationGate(
  searchEnabled: () => boolean = () =>
    configuredOpenAIApi() === "openai-responses",
) {
  let currentUserPrompt = "";
  let searchStarted = false;
  return {
    startSession(): void {
      currentUserPrompt = "";
      searchStarted = false;
    },
    setUserPrompt(prompt: string): void {
      currentUserPrompt = Array.from((prompt ?? "").trim())
        .slice(0, MAX_SEARCH_INPUT_CHARS)
        .join("");
    },
    getUserPrompt(): string {
      return currentUserPrompt;
    },
    beforeToolCall(toolName: string): { block: true; reason: string } | undefined {
      if (searchStarted) {
        return { block: true, reason: SEARCH_TOOL_BLOCK_REASON };
      }
      if (toolName === "think_hard" && searchEnabled()) searchStarted = true;
      return undefined;
    },
  };
}

/**
 * Pure request-body builder. Separated so the oracle can diff our body
 * shape against bridge.py's without hitting the thinker endpoint.
 */
export function buildThinkRequest(
  question: string,
  model: string = DEFAULT_MODEL,
  api: OpenAIApi = configuredOpenAIApi(),
): OpenAIRequest {
  const maxTokens = Number.parseInt(
    process.env.DOTTY_PI_THINK_MAX_TOKENS ?? "4096",
    10,
  );
  const reasoning = ["1", "true", "yes", "on"].includes(
    (process.env.DOTTY_PI_THINK_REASONING ?? "true").toLowerCase(),
  );
  const reasoningEffort = (
    process.env.DOTTY_PI_THINK_REASONING_EFFORT ?? "high"
  ).trim();
  if (api === "openai-responses") {
    return {
      model,
      instructions: SYSTEM_PROMPT,
      input: question,
      max_output_tokens:
        Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : 4096,
      stream: false,
      store: false,
      tools: [WEB_SEARCH_TOOL],
      ...(reasoning && reasoningEffort
        ? { reasoning: { effort: reasoningEffort } }
        : {}),
    } satisfies ResponsesRequest;
  }
  return {
    model,
    messages: [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user", content: question },
    ],
    max_tokens: Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : 4096,
    temperature: 0.3,
    stream: false,
    chat_template_kwargs: { enable_thinking: reasoning },
    ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
  } satisfies ChatCompletionRequest;
}

export interface ThinkHardOptions {
  url?: string;
  timeoutSec?: number;
  model?: string;
  apiKey?: string;
  api?: OpenAIApi;
}

/**
 * Top-level dispatch. Mirrors the Python wrapper's error handling.
 */
export async function runThinkHard(
  question: string,
  opts: ThinkHardOptions = {},
): Promise<string> {
  const q = (question ?? "").trim();
  if (!q) return "(empty question)";
  const api = opts.api ?? configuredOpenAIApi();
  const body = buildThinkRequest(q, opts.model, api);
  try {
    const content = await postOpenAIRequest(body, {
      url: opts.url,
      timeoutSec: opts.timeoutSec,
      apiKey: opts.apiKey,
      api,
    });
    // Python: (content or "").strip()[:500]
    // JS .slice is OK here — the 500-char cap is generous and the
    // codepoint/code-unit drift is at most ~10 chars on emoji-dense
    // replies; the LLM is told to answer in 1-2 sentences, so we'll
    // virtually never hit the cap anyway. Matching Python literally:
    return content.trim().slice(0, MAX_OUTPUT_CHARS);
  } catch (err) {
    if (err instanceof TimeoutError) {
      return "(I'm slow today, try again in a moment)";
    }
    process.stderr.write(`[think_hard] failed: ${err}\n`);
    return "(thinking failed)";
  }
}

export function createThinkHardTool(currentUserPrompt: () => string) {
  return {
    name: "think_hard",
    label: "Think Hard",
    description:
      "Send the current user's question to an isolated reasoning model with " +
      "web search for a precise 1-2 sentence answer. Use when the quick chat " +
      "path needs current facts, math, lookups, or technical specifics.",
    promptSnippet:
      "Escalate the current user question to the configured think_hard model.",
    promptGuidelines: [
      "Use think_hard when the current user asks a factual or technical " +
        "question that needs precise reasoning or current web information.",
    ],
    parameters: Type.Object({}),
    executionMode: "sequential" as const,
    async execute(
      _toolCallId: string,
      _params: Record<string, never>,
      _signal: AbortSignal | undefined,
      _onUpdate: unknown,
      _ctx: unknown,
    ): Promise<{ content: Array<{ type: "text"; text: string }> }> {
      const text = await runThinkHard(currentUserPrompt());
      return { content: [{ type: "text", text }] };
    },
  };
}
