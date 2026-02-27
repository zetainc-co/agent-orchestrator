#!/usr/bin/env python3
"""
Dify Monitor Proxy — lee directo de la DB de Dify y expone un endpoint
para el monitor HTML.
"""
import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

DB_CONTAINER = "docker-db_postgres-1"

QUERY = """
SELECT
  m.id,
  m.conversation_id,
  m.query,
  m.answer,
  m.message_tokens,
  m.answer_tokens,
  m.total_price::float,
  m.model_id,
  m.provider_response_latency,
  m.status,
  EXTRACT(EPOCH FROM m.created_at)::bigint AS created_at,
  c.name AS conv_name,
  a.name AS app_name
FROM messages m
LEFT JOIN conversations c ON c.id = m.conversation_id
LEFT JOIN apps a ON a.id = m.app_id
ORDER BY m.created_at DESC
LIMIT 500;
"""

def query_db():
    import csv, io
    result = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "dify",
         "--csv", "-c", QUERY],
        capture_output=True, text=True, timeout=10
    )
    rows = []
    reader = csv.DictReader(io.StringIO(result.stdout))
    for r in reader:
        try:
            mt = int(r.get("message_tokens") or 0)
            at = int(r.get("answer_tokens") or 0)
            rows.append({
                "id":             r["id"],
                "conv_id":        r["conversation_id"],
                "query":          r["query"][:120],
                "answer":         r["answer"][:100],
                "message_tokens": mt,
                "answer_tokens":  at,
                "total_tokens":   mt + at,
                "total_price":    float(r.get("total_price") or 0),
                "model":          r.get("model_id", ""),
                "latency":        f"{float(r.get('provider_response_latency') or 0):.1f}s",
                "status":         r.get("status", "normal"),
                "created_at":     int(float(r.get("created_at") or 0)),
                "conv_name":      r.get("conv_name", ""),
                "app_name":       r.get("app_name", "Sin nombre"),
            })
        except Exception:
            continue
    return rows

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            try:
                data = query_db()
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # silenciar logs

print("Monitor proxy corriendo en http://localhost:8100/metrics")
HTTPServer(("0.0.0.0", 8100), Handler).serve_forever()
