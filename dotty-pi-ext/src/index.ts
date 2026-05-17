// dotty-pi-ext — pi extension that exposes Dotty's voice tools.
// Loaded by the dotty-pi container's pi runtime via the extensions/
// bind-mount (see ../dotty-pi/README.md).
//
// This entry point is intentionally thin: it just registers tools. All
// behaviour lives in tools/* (testable in isolation) and lib/* (the
// underlying clients — sqlite for brain.db, fetch for xiaozhi admin,
// etc).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { memoryLookupTool } from "./tools/memory_lookup.ts";

export default function (pi: ExtensionAPI) {
  pi.registerTool(memoryLookupTool);
  // think_hard, take_photo, play_song, set_led land in subsequent slices.
}
