// LanceDB compaction/vacuum, run inside a throwaway container from the SAME
// AnythingLLM image (so it reuses the exact bundled @lancedb/lancedb native
// binary/version) while the real AnythingLLM container is stopped, avoiding
// concurrent writes during maintenance. Uses LanceDB's own supported
// Table#optimize() API (compaction + old-version pruning + index optimize,
// "modeled after VACUUM in PostgreSQL") -- never touches _versions/data
// files directly.
//
// Input (env var LANCEDB_COMPACT_REQUEST, JSON):
//   {"storageDir": "/app/server/storage/lancedb", "namespace": "bg-wiki", "cleanupOlderThanDays": 0}
//
// Output (stdout, JSON):
//   {"rowCountBefore": N, "rowCountAfter": N, "versionBefore": V, "versionAfter": V,
//    "indicesBefore": [...], "indicesAfter": [...], "optimizeStats": {...}}

const lancedb = require("/app/server/node_modules/@lancedb/lancedb");

async function main() {
  const request = JSON.parse(process.env.LANCEDB_COMPACT_REQUEST);
  const { storageDir, namespace, cleanupOlderThanDays = 0 } = request;

  const client = await lancedb.connect(storageDir);
  const tables = await client.tableNames();
  if (!tables.includes(namespace)) {
    throw new Error(`table '${namespace}' not found under ${storageDir} (tables present: ${tables.join(", ")})`);
  }

  const table = await client.openTable(namespace);

  const rowCountBefore = await table.countRows();
  const versionBefore = await table.version();
  const indicesBefore = (await table.listIndices()).map((idx) => idx.name);

  const cleanupOlderThan = new Date();
  cleanupOlderThan.setDate(cleanupOlderThan.getDate() - cleanupOlderThanDays);

  const optimizeStats = await table.optimize({ cleanupOlderThan, deleteUnverified: false });

  const rowCountAfter = await table.countRows();
  const versionAfter = await table.version();
  const indicesAfter = (await table.listIndices()).map((idx) => idx.name);

  process.stdout.write(
    JSON.stringify({
      rowCountBefore,
      rowCountAfter,
      versionBefore,
      versionAfter,
      indicesBefore,
      indicesAfter,
      optimizeStats,
    }),
  );
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
