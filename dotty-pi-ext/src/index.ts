// dotty-pi-ext — pi extension that exposes Dotty's voice tools.
// Baked into the dotty-pi image and loaded through its extensions symlink.
//
// This entry point is intentionally thin: it just registers tools. All
// behaviour lives in tools/* (testable in isolation) and lib/* (the
// underlying clients — sqlite for brain.db, fetch for xiaozhi admin,
// etc).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { logTurnEnd } from "./lib/turn_logger.ts";
import { memoryLookupTool } from "./tools/memory_lookup.ts";
import { playSongTool } from "./tools/play_song.ts";
import { recallPersonTool } from "./tools/recall_person.ts";
import { rememberTool } from "./tools/remember.ts";
import { rememberPersonTool } from "./tools/remember_person.ts";
import { takePhotoTool } from "./tools/take_photo.ts";
import {
  createSearchIsolationGate,
  createThinkHardTool,
} from "./tools/think_hard.ts";

export default function (pi: ExtensionAPI) {
  const searchGate = createSearchIsolationGate();
  pi.on("session_start", () => searchGate.startSession());
  pi.on("before_agent_start", (event) => {
    searchGate.setUserPrompt(event.prompt);
  });
  pi.on("tool_call", (event) => searchGate.beforeToolCall(event.toolName));

  pi.registerTool(memoryLookupTool);
  pi.registerTool(recallPersonTool);
  pi.registerTool(rememberTool);
  pi.registerTool(rememberPersonTool);
  pi.registerTool(createThinkHardTool(() => searchGate.getUserPrompt()));
  pi.registerTool(playSongTool);
  pi.registerTool(takePhotoTool);
  // Per-turn conversation auto-log. This is the live write path on the
  // PiVoiceLLM voice path (the old bridge.py /api/voice/memory_log endpoint
  // was retired with the #36 cutover).
  pi.on("agent_end", logTurnEnd);
  // set_led is intentionally absent: the LED ring is reserved for
  // mode/state indication, not voice-driven; see README.md "Not a tool".
}
