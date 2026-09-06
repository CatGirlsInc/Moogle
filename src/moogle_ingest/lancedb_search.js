// Direct LanceDB read helper, executed inside the AnythingLLM container via
// `docker exec` so it reuses the exact @lancedb/lancedb client (and on-disk
// index) AnythingLLM itself uses. Input/output is JSON to keep the contract
// small and easy to reason about from the Python side.
//
// Input (env var LANCEDB_SEARCH_REQUEST, JSON):
//   {
//     "storageDir": "/app/server/storage/lancedb",
//     "namespace": "bg-wiki",
//     "similarityThreshold": 0.25,
//     "queries": [{"query": "...", "vector": [..1024 floats..], "topN": 4}, ...]
//   }
//
// Output (stdout, JSON):
//   [{"query": "...", "sources": [{"id":.., "title":.., "text":.., "score":..}]}, ...]

const lancedb = require("/app/server/node_modules/@lancedb/lancedb");

function distanceToSimilarity(distance) {
  if (distance === null || typeof distance !== "number") return 0.0;
  if (distance >= 1.0) return 1;
  if (distance < 0) return 1 - Math.abs(distance);
  return 1 - distance;
}

async function main() {
  const request = JSON.parse(process.env.LANCEDB_SEARCH_REQUEST);
  const { storageDir, namespace, similarityThreshold = 0.25, queries } = request;

  const client = await lancedb.connect(storageDir);
  const table = await client.openTable(namespace);

  const results = await Promise.all(
    queries.map(async ({ query, vector, topN = 4 }) => {
      const rows = await table
        .vectorSearch(vector)
        .distanceType("cosine")
        .limit(topN)
        .toArray();

      const sources = rows
        .map((row) => {
          const { vector: _vector, ...rest } = row;
          return { ...rest, score: distanceToSimilarity(row._distance) };
        })
        .filter((source) => source.score >= similarityThreshold);

      return { query, sources };
    })
  );

  process.stdout.write(JSON.stringify(results));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
