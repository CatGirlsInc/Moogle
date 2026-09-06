// Read-only LanceDB compatibility check, executed inside the AnythingLLM
// container via `docker exec` (see direct_retrieval.py). Never mutates the
// table; only inspects table existence, field names, and vector dimension.
//
// Input (env var LANCEDB_SEARCH_REQUEST, JSON):
//   {"storageDir": "/app/server/storage/lancedb", "namespace": "bg-wiki"}
//
// Output (stdout, JSON), one of:
//   {"exists": false, "tables": ["other-table", ...]}
//   {"exists": true, "fields": ["id", "text", ...], "vectorDim": 1024, "rowCount": 196988}

const lancedb = require("/app/server/node_modules/@lancedb/lancedb");

async function main() {
  const request = JSON.parse(process.env.LANCEDB_SEARCH_REQUEST);
  const { storageDir, namespace } = request;

  const client = await lancedb.connect(storageDir);
  const tables = await client.tableNames();

  if (!tables.includes(namespace)) {
    process.stdout.write(JSON.stringify({ exists: false, tables }));
    return;
  }

  const table = await client.openTable(namespace);
  const schema = await table.schema();
  const fields = schema.fields.map((field) => field.name);

  const vectorField = schema.fields.find((field) => field.name === "vector");
  const vectorTypeStr = vectorField ? String(vectorField.type) : "";
  const dimMatch = vectorTypeStr.match(/(\d+)/);
  const vectorDim = dimMatch ? parseInt(dimMatch[1], 10) : null;

  const rowCount = await table.countRows();

  process.stdout.write(JSON.stringify({ exists: true, fields, vectorDim, rowCount }));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
