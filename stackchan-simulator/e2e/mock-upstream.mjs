import { createServer } from "node:http";

const openapi = {
  openapi: "3.1.0",
  info: { title: "simulator mock", version: "1" },
  paths: {
    "/health": { get: { summary: "Mock liveness", responses: { 200: { description: "ok" } } } },
  },
};

createServer((request, response) => {
  response.setHeader("content-type", "application/json");
  if (request.url === "/openapi.json") response.end(JSON.stringify(openapi));
  else if (request.url === "/health") response.end(JSON.stringify({ ok: true, service: "mock" }));
  else if (request.url === "/xiaozhi/admin/devices") response.end(JSON.stringify({ devices: ["stackchan-sim-001"] }));
  else { response.statusCode = 404; response.end(JSON.stringify({ error: "mock not found" })); }
}).listen(19090, "127.0.0.1");
