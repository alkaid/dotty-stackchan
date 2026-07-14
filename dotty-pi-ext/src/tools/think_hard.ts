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
  TimeoutError,
  postChatCompletion,
  type ChatCompletionRequest,
} from "../lib/llama_swap.ts";

const DEFAULT_MODEL = process.env.VOICE_THINKER_MODEL ?? "dotty-think";
const SYSTEM_PROMPT =
  "Answer the user's question concisely in 1-2 sentences. Be precise.";
const MAX_OUTPUT_CHARS = 500;

/**
 * Pure request-body builder. Separated so the oracle can diff our body
 * shape against bridge.py's without hitting the thinker endpoint.
 */
export function buildThinkRequest(
  question: string,
  model: string = DEFAULT_MODEL,
): ChatCompletionRequest {
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
  };
}

export interface ThinkHardOptions {
  url?: string;
  timeoutSec?: number;
  model?: string;
  apiKey?: string;
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
  const body = buildThinkRequest(q, opts.model);
  try {
    const content = await postChatCompletion(body, {
      url: opts.url,
      timeoutSec: opts.timeoutSec,
      apiKey: opts.apiKey,
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

export const thinkHardTool = {
  name: "think_hard",
  label: "Think Hard",
  description:
    "Send a single question to a larger reasoning model for a precise " +
    "1-2 sentence answer. Use only when the quick chat path can't " +
    "handle the question (math, lookups, technical specifics).",
  promptSnippet:
    "Escalate a single question to the configured think_hard model.",
  promptGuidelines: [
    "Use think_hard when the user asks a factual or technical question " +
      "that needs precise reasoning. Keep the question self-contained.",
  ],
  parameters: Type.Object({
    question: Type.String({
      description:
        "Self-contained question for the reasoning model. Include any context inline.",
    }),
  }),
  async execute(
    _toolCallId: string,
    params: { question: string },
    _signal: AbortSignal | undefined,
    _onUpdate: unknown,
    _ctx: unknown,
  ): Promise<{ content: Array<{ type: "text"; text: string }> }> {
    const text = await runThinkHard(params.question);
    return { content: [{ type: "text", text }] };
  },
};
