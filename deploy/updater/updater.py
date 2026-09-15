"""Tiny sidecar: on POST /update, pull the latest API image and recreate the api service.
Only reachable on the compose network (the API calls it when the admin presses "Actualizar")."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

COMPOSE = ["docker", "compose", "-f", os.environ.get("COMPOSE_FILE", "/stack/docker-compose.prod.yml")]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/update":
            self.send_response(404)
            self.end_headers()
            return
        # answer first: the api container is about to be replaced
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "updating"}).encode())
        subprocess.Popen(COMPOSE + ["pull", "api"]).wait()
        subprocess.Popen(COMPOSE + ["up", "-d", "--no-deps", "api"])

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)


HTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
