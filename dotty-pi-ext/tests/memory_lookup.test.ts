// Equivalence test: run a handful of queries through the TS port and
// assert the output is byte-identical to bridge.py's behaviour against
// the same brain.db snapshot.
//
// Usage:
//   DOTTY_BRAIN_DB_SNAPSHOT=/path/to/brain.db \
//   node --experimental-strip-types tests/memory_lookup.test.ts
//
// The oracle (tests/oracle.py) is the spec. If this test fails, fix the
// TS code — don't fix the test by mutating oracle.py, since that's
// literally copy-pasted bridge.py.

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { runMemoryLookup } from "../src/tools/memory_lookup.ts";
import { _resetForTests } from "../src/lib/brain_db.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ORACLE = join(__dirname, "oracle.py");

const QUERIES_EXPECTING_HITS = [
  "Dotty",
  "Taiwan",
  "name",
];

const QUERIES_EXPECTING_NO_HITS = [
  "nonexistent_zzz_token_qqq",
];

const EDGE_CASES: Array<{ query: string; expected: string }> = [
  { query: "", expected: "(empty query)" },
  { query: "   ", expected: "(empty query)" },
];

interface OracleLine {
  query: string;
  expected: string;
}

function callOracle(db: string, queries: string[]): OracleLine[] {
  const out = execFileSync("python3", [ORACLE, db, ...queries], {
    encoding: "utf8",
  });
  return out
    .trim()
    .split("\n")
    .filter((l) => l.length > 0)
    .map((l) => JSON.parse(l) as OracleLine);
}

function assertEq(label: string, actual: string, expected: string): void {
  if (actual === expected) {
    process.stdout.write(`  PASS  ${label}\n`);
    return;
  }
  process.stderr.write(
    `  FAIL  ${label}\n        expected: ${JSON.stringify(expected.slice(0, 200))}\n        actual:   ${JSON.stringify(actual.slice(0, 200))}\n`,
  );
  failures++;
}

let failures = 0;

function main(): void {
  const snapshot = process.env.DOTTY_BRAIN_DB_SNAPSHOT;
  if (!snapshot || !existsSync(snapshot)) {
    process.stderr.write(
      `SKIP: set DOTTY_BRAIN_DB_SNAPSHOT to a readable brain.db copy.\n` +
        `      (default location for dev: ~/Repos/dotty-private/probes/runs/brain.db.snapshot-*)\n`,
    );
    process.exit(0);
  }
  process.env.DOTTY_BRAIN_DB = snapshot;
  _resetForTests();

  process.stdout.write(`Snapshot: ${snapshot}\n\n`);

  process.stdout.write("Edge cases (no oracle needed):\n");
  for (const { query, expected } of EDGE_CASES) {
    const actual = runMemoryLookup(query);
    assertEq(`query=${JSON.stringify(query)}`, actual, expected);
  }

  process.stdout.write("\nQueries expecting hits (vs oracle):\n");
  const hitOracles = callOracle(snapshot, QUERIES_EXPECTING_HITS);
  for (const { query, expected } of hitOracles) {
    const actual = runMemoryLookup(query, snapshot);
    assertEq(`query=${JSON.stringify(query)}`, actual, expected);
  }

  process.stdout.write("\nQueries expecting no hits (vs oracle):\n");
  const missOracles = callOracle(snapshot, QUERIES_EXPECTING_NO_HITS);
  for (const { query, expected } of missOracles) {
    const actual = runMemoryLookup(query, snapshot);
    assertEq(`query=${JSON.stringify(query)}`, actual, expected);
  }

  process.stdout.write(`\n${failures === 0 ? "OK" : "FAIL"} — ${failures} failure(s)\n`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
