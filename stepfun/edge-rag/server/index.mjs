import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { closeStore, hybridSearch, storeInfo, upsertItems } from "./store.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const port = Number(process.env.PORT || 8787);

function send(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "http://127.0.0.1:5173" });
  response.end(JSON.stringify(payload));
}

async function body(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 12 * 1024 * 1024) throw new Error("请求体超过 12 MB");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === "OPTIONS") {
      response.writeHead(204, { "access-control-allow-origin": "http://127.0.0.1:5173", "access-control-allow-methods": "GET,POST,OPTIONS", "access-control-allow-headers": "content-type" });
      return response.end();
    }
    if (request.url === "/api/status" && request.method === "GET") return send(response, 200, storeInfo);
    if (request.url === "/api/upsert" && request.method === "POST") {
      const payload = await body(request);
      return send(response, 200, await upsertItems(payload.kbId, payload.items));
    }
    if (request.url === "/api/search" && request.method === "POST") {
      const payload = await body(request);
      return send(response, 200, await hybridSearch(payload.kbId, payload.query, payload.embedding, payload.limit));
    }
    if (!fs.existsSync(dist)) return send(response, 404, { error: "尚未构建前端；开发模式请访问 http://127.0.0.1:5173" });
    const requested = request.url === "/" ? "index.html" : request.url.split("?")[0].replace(/^\//, "");
    const file = path.resolve(dist, requested);
    if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return send(response, 404, { error: "Not found" });
    const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
    response.writeHead(200, { "content-type": `${types[path.extname(file)] || "application/octet-stream"}; charset=utf-8` });
    fs.createReadStream(file).pipe(response);
  } catch (error) { send(response, 400, { error: error.message }); }
});

server.listen(port, "127.0.0.1", () => console.log(`EdgeSeek API: http://127.0.0.1:${port}`));
async function shutdown() { server.close(); await closeStore(); }
process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
