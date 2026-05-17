// FTS5 client for Dotty's `brain.db`. Mirrors the contract of
// bridge.py:_voice_memory_search_blocking — read-only access, phrase
// match wrapping, top-N by rank.
//
// brain.db schema (frozen — managed by ZeroClaw, do NOT mutate from here):
//   memories(id, key, content, category, embedding, created_at,
//            updated_at, session_id, namespace, importance, superseded_by)
//   memories_fts(key, content)  -- virtual FTS5, content=memories
//
// The bind-mount inside the dotty-pi container puts brain.db at
//   /root/.pi/memory/brain.db
// (env-overridable via DOTTY_BRAIN_DB).

import Database from "better-sqlite3";

export interface MemoryRow {
  key: string;
  content: string;
  category: string;
  namespace: string;
  created_at: string;
}

const DEFAULT_PATH = process.env.DOTTY_BRAIN_DB ?? "/root/.pi/memory/brain.db";

let cachedDb: Database.Database | null = null;
let cachedPath: string | null = null;

function openReadOnly(path: string): Database.Database {
  // Reuse the handle across calls — SQLite read-only opens are cheap but
  // not free, and the dotty-pi process is long-lived per #36 Step-5.
  if (cachedDb && cachedPath === path) return cachedDb;
  if (cachedDb) cachedDb.close();
  cachedDb = new Database(path, { readonly: true, fileMustExist: true });
  cachedPath = path;
  return cachedDb;
}

export interface SearchOptions {
  /** Override brain.db path (defaults to DOTTY_BRAIN_DB env / canonical). */
  dbPath?: string;
  /** Cap rows returned by the FTS query (formatter trims further). */
  limit?: number;
}

/**
 * FTS5 phrase search. Returns empty array on missing db, empty query,
 * or any SQLite error (logged to stderr). Never throws into the caller —
 * the voice path must degrade gracefully.
 */
export function searchMemories(
  query: string,
  opts: SearchOptions = {},
): MemoryRow[] {
  const limit = opts.limit ?? 5;
  const path = opts.dbPath ?? DEFAULT_PATH;
  const safe = (query ?? "").replace(/"/g, '""').trim();
  if (!safe) return [];
  // Wrap in double quotes for FTS5 phrase match — same as bridge.py.
  // Plain MATCH on multi-word queries would treat tokens as AND;
  // phrase-quoting keeps the user's word order, matching the existing
  // tool's behaviour the LLM was tuned against.
  const fts = `"${safe}"`;

  try {
    const db = openReadOnly(path);
    const stmt = db.prepare(`
      SELECT m.key, m.content, m.category, m.namespace, m.created_at
      FROM memories_fts
      JOIN memories m ON m.rowid = memories_fts.rowid
      WHERE memories_fts MATCH ?
      ORDER BY rank
      LIMIT ?
    `);
    return stmt.all(fts, limit) as MemoryRow[];
  } catch (err) {
    process.stderr.write(
      `[brain_db] search failed for query=${JSON.stringify(safe.slice(0, 60))}: ${err}\n`,
    );
    return [];
  }
}

/** Test-only helper: close the cached handle. */
export function _resetForTests(): void {
  if (cachedDb) cachedDb.close();
  cachedDb = null;
  cachedPath = null;
}
