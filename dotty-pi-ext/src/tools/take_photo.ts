// take_photo voice tool — pi-extension port of bridge.py's
// _voice_tool_take_photo. v1 reads the latest cached vision description
// from the dotty-behaviour daemon over loopback HTTP; returns either the
// description (≤30 s old, capped at 300 chars) or a "can't see" string.
//
// Both upstream code paths (the bridge function and the
// dotty-behaviour /api/voice/take_photo route) cap and fall back
// identically — this tool is a thin wrapper that hands the daemon's
// reply back to the agent verbatim.

import { Type } from "typebox";
import { fetchTakePhoto, type BehaviourOptions } from "../lib/dotty_behaviour.ts";

export interface TakePhotoOptions extends BehaviourOptions {}

export async function runTakePhoto(
  opts: TakePhotoOptions = {},
): Promise<string> {
  return await fetchTakePhoto(opts);
}

export const takePhotoTool = {
  name: "take_photo",
  label: "Take Photo",
  description:
    "Look through Dotty's camera right now and describe what you see. " +
    "Uses the most recent ambient capture (≤30 s old) — Dotty does not " +
    "actively trigger a fresh photo. Use when the user asks about the " +
    "room, what Dotty can see, or to ground the conversation in the " +
    "current physical surroundings.",
  promptSnippet:
    "Look at the latest cached camera view and describe it.",
  promptGuidelines: [
    "Use take_photo when the user asks 'what do you see', mentions " +
      "something in front of the camera, or wants Dotty to describe the " +
      "current scene. Don't guess at the room contents — call this tool first.",
    "If take_photo returns '（现在没有可用的新画面）', say " +
      "so honestly to the user rather than inventing a description.",
  ],
  parameters: Type.Object({}),
  async execute(
    _toolCallId: string,
    _params: Record<string, never>,
    _signal: AbortSignal | undefined,
    _onUpdate: unknown,
    _ctx: unknown,
  ): Promise<{ content: Array<{ type: "text"; text: string }> }> {
    const text = await runTakePhoto();
    return { content: [{ type: "text", text }] };
  },
};
