import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if self.headers.get("X-API-KEY") != "stubkey123":
            self._respond(401, {"message": "Unauthorized"})
        elif self.path.startswith("/api/system/status"):
            self._respond(200, {"data": {"bazarr_version": "1.5.1"}})
        elif self.path.startswith("/api/system/health"):
            self._respond(200, {"data": []})
        elif self.path.startswith("/api/movies"):
            self._respond(200, {"data": [], "total": 0})
        elif self.path.startswith("/api/series"):
            self._respond(200, {"data": [], "total": 0})
        elif self.path.startswith("/api/episodes"):
            self._respond(200, {"data": [], "total": 0})
        else:
            self._respond(200, {})

    def do_PATCH(self):
        if self.headers.get("X-API-KEY") != "stubkey123":
            self._respond(401, {"message": "Unauthorized"})
        else:
            self._respond(204, "")

    def do_POST(self):
        if self.headers.get("X-API-KEY") != "stubkey123":
            self._respond(401, {"message": "Unauthorized"})
        else:
            self._respond(204, "")

    def log_message(self, *a):
        pass

HTTPServer(("0.0.0.0", 6767), Handler).serve_forever()
