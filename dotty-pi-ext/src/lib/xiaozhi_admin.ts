// xiaozhi-server admin client. Lives alongside brain_db.ts and
// llama_swap.ts as the third "infrastructure dep" the extension talks
// to from inside the dotty-pi container. Both xiaozhi-server and pi
// run on the same Compose network, so the default URL is the xiaozhi
// service DNS name. Env vars override for dev / tests.
//
// Admin auth: when DOTTY_ADMIN_TOKEN is set we attach an X-Admin-Token header
// on every admin request, matching the xiaozhi-server /xiaozhi/admin/*
// middleware. Unset = no header, so this is a no-op until the same token is
// provisioned across all callers + the server. See architecture.md threat model.

const DEFAULT_TIMEOUT_MS = Number(
  process.env.XIAOZHI_ADMIN_TIMEOUT_MS ?? "3000",
);
const ADMIN_TOKEN = process.env.DOTTY_ADMIN_TOKEN ?? "";

export interface AdminOptions {
  host?: string;
  port?: number;
  timeoutMs?: number;
}

function buildUrl(path: string, opts: AdminOptions = {}): string {
  const suffix = path.startsWith("/") ? path : "/" + path;
  if (opts.host) {
    const port = opts.port ?? 8003;
    return `http://${opts.host}:${port}${suffix}`;
  }
  const baseUrl = (
    process.env.XIAOZHI_ADMIN_BASE_URL ?? "http://xiaozhi-esp32-server:8003"
  ).replace(/\/+$/, "");
  return `${baseUrl}${suffix}`;
}

async function adminFetch(
  path: string,
  init: RequestInit,
  opts: AdminOptions,
): Promise<Response> {
  const url = buildUrl(path, opts);
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  // Merge the admin token into any caller-supplied headers (e.g. content-type)
  // when DOTTY_ADMIN_TOKEN is set; otherwise leave headers untouched.
  const headers = new Headers(init.headers);
  if (ADMIN_TOKEN) headers.set("X-Admin-Token", ADMIN_TOKEN);
  try {
    return await fetch(url, { ...init, headers, signal: ac.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * GET /xiaozhi/admin/songs — returns the song basenames mounted in
 * xiaozhi-server's assets dir. Empty list on any failure (matches
 * bridge.py:_voice_tool_play_song_catalog).
 */
export async function fetchSongCatalog(
  opts: AdminOptions = {},
): Promise<string[]> {
  try {
    const resp = await adminFetch("/xiaozhi/admin/songs", { method: "GET" }, opts);
    if (!resp.ok) return [];
    const data = (await resp.json()) as { files?: unknown };
    const files = data.files;
    if (!Array.isArray(files)) return [];
    return files.filter((f): f is string => typeof f === "string");
  } catch {
    return [];
  }
}

/**
 * POST /xiaozhi/admin/play-asset {asset: <abs_path>}. Returns
 * {ok: true} on 2xx, otherwise {ok: false, error: <short>}.
 */
export interface PlayAssetResult {
  ok: boolean;
  error?: string;
}

export async function playAsset(
  assetPath: string,
  opts: AdminOptions = {},
): Promise<PlayAssetResult> {
  try {
    const resp = await adminFetch(
      "/xiaozhi/admin/play-asset",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ asset: assetPath }),
      },
      opts,
    );
    if (resp.status === 200) return { ok: true };
    const body = await resp.text().catch(() => "");
    return { ok: false, error: `HTTP ${resp.status}: ${body.slice(0, 120)}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}
