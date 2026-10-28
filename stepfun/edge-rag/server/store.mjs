import path from "node:path";
import { SeekdbAdminClient, SeekdbClient, Schema, FulltextIndexConfig, VectorIndexConfig } from "seekdb";

export const DIMENSION = 384;
const dbPath = path.resolve(process.env.SEEKDB_PATH || ".seekdb/edge-rag");
const database = process.env.SEEKDB_DATABASE || "edge_rag";
const serverHost = process.env.SEEKDB_HOST;
let client;
if (serverHost) {
  client = new SeekdbClient({
    host: serverHost,
    port: Number(process.env.SEEKDB_PORT || 2881),
    user: process.env.SEEKDB_USER || "root",
    password: process.env.SEEKDB_PASSWORD || "",
    database,
  });
} else {
  const admin = new SeekdbAdminClient({ path: dbPath });
  const existingDatabases = await admin.listDatabases();
  if (!existingDatabases.some((item) => (typeof item === "string" ? item : item.name) === database)) {
    await admin.createDatabase(database);
  }
  await admin.close();
  client = new SeekdbClient({ path: dbPath, database });
}
const collections = new Map();

function safeCollectionName(kbId) {
  const safe = String(kbId || "default").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 32);
  return `kb_${safe || "default"}`;
}

function assertVector(vector) {
  if (!Array.isArray(vector) || vector.length !== DIMENSION || vector.some((value) => !Number.isFinite(value))) {
    throw new Error(`embedding 必须是 ${DIMENSION} 维有限数值数组`);
  }
}

async function getCollection(kbId) {
  const name = safeCollectionName(kbId);
  if (!collections.has(name)) {
    const schema = new Schema()
      .createIndex(new FulltextIndexConfig())
      .createIndex(new VectorIndexConfig({ hnsw: { dimension: DIMENSION, distance: "cosine" }, embeddingFunction: null }));
    collections.set(name, await client.getOrCreateCollection({ name, schema }));
  }
  return collections.get(name);
}

export async function upsertItems(kbId, items) {
  if (!Array.isArray(items) || !items.length) throw new Error("items 不能为空");
  if (items.length > 256) throw new Error("单批最多写入 256 个文本块");
  items.forEach((item) => assertVector(item.embedding));
  const collection = await getCollection(kbId);
  const ids = items.map((item) => String(item.id));
  await collection.upsert({
    ids,
    documents: items.map((item) => String(item.content)),
    embeddings: items.map((item) => item.embedding),
    metadatas: items.map((item) => ({ ...item.metadata, kbId: String(kbId) })),
  });
  const persisted = await collection.get({ ids, include: ["documents", "metadatas"] });
  const all = await collection.get({ limit: 10000, include: ["metadatas"] });
  return { written: persisted.ids?.length ?? ids.length, total: all.ids?.length ?? ids.length };
}

function firstRow(value) {
  return Array.isArray(value?.[0]) ? value[0] : (value || []);
}

export async function hybridSearch(kbId, query, embedding, limit = 6) {
  assertVector(embedding);
  const collection = await getCollection(kbId);
  const nResults = Math.max(1, Math.min(20, Number(limit) || 6));
  const started = performance.now();
  const result = await collection.hybridSearch({
    query: { whereDocument: { $contains: String(query) }, nResults: Math.max(10, nResults * 2) },
    knn: { queryEmbeddings: [embedding], nResults: Math.max(10, nResults * 2) },
    rank: { rrf: {} },
    nResults,
    include: ["documents", "metadatas", "distances"],
  });
  const ids = firstRow(result.ids);
  const documents = firstRow(result.documents);
  const metadatas = firstRow(result.metadatas);
  const distances = firstRow(result.distances);
  return {
    searchMs: performance.now() - started,
    results: ids.map((id, index) => ({ id, document: documents[index], metadata: metadatas[index], distance: distances[index] })),
  };
}

export async function closeStore() {
  await client.close();
}

export const storeInfo = {
  engine: serverHost ? "seekdb-js server" : "seekdb-js embedded",
  location: serverHost ? `${serverHost}:${process.env.SEEKDB_PORT || 2881}` : dbPath,
  database,
  dimension: DIMENSION,
};
