import argparse
import asyncio
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent import create_session


BASE_DIR = Path(__file__).resolve().parent
WEB_UI_DIR = BASE_DIR / "webui"


class PlantChatServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]):
        super().__init__(server_address, handler_class)
        self.session = create_session()
        self.session_lock = threading.Lock()


class PlantChatRequestHandler(BaseHTTPRequestHandler):
    server: PlantChatServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._serve_file(WEB_UI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self._serve_file(WEB_UI_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file(WEB_UI_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/state":
            self._send_json(HTTPStatus.OK, self.server.session.snapshot())
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/message":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid content length"})
            return

        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body must be valid JSON"})
            return

        message = str(payload.get("message", "")).strip()
        if not message:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Message is required"})
            return

        try:
            with self.server.session_lock:
                result = asyncio.run(self.server.session.handle_message(message))
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"Request failed: {exc}"},
            )
            return

        self._send_json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args) -> None:
        return

    def _serve_file(self, filepath: Path, content_type: str) -> None:
        if not filepath.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content = filepath.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status_code: HTTPStatus, payload: dict) -> None:
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Plant Simulation chat UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to.")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve the UI on.")
    args = parser.parse_args()

    server = PlantChatServer((args.host, args.port), PlantChatRequestHandler)
    print(f"Plant chat UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
