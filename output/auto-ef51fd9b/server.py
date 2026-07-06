#!/usr/bin/env python3
"""
Simple HTTP Server — A lightweight HTTP server supporting GET/POST methods,
static file routing, and custom 404 error pages.

Built with Python standard library only (http.server, socketserver, argparse).
"""

from __future__ import annotations

import argparse
import cgi
import email.utils
import http.server
import io
import json
import logging
import os
import posixpath
import signal
import socketserver
import sys
import time
import urllib.parse
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_POST_SIZE: int = 10 * 1024 * 1024  # 10 MB
MAX_URI_LENGTH: int = 2048
SERVER_VERSION: str = "SimpleHTTPServer/1.0"
DEFAULT_PORT: int = 8080
DEFAULT_HOST: str = "0.0.0.0"
DEFAULT_ROOT: str = "."

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logger = logging.getLogger("SimpleHTTPServer")
logger.setLevel(logging.INFO)

_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(levelname)s] %(message)s"))
logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# T001 — MIME Type Mapping
# ---------------------------------------------------------------------------

MIME_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
}


def get_mime_type(path: str) -> str:
    """Return the MIME type for a given file path based on its extension.

    Args:
        path: File path or filename.

    Returns:
        The corresponding MIME type string. Returns ``application/octet-stream``
        for unknown or missing extensions.
    """
    _, ext = os.path.splitext(path)
    return MIME_TYPES.get(ext.lower(), "application/octet-stream")


# ---------------------------------------------------------------------------
# T002 — Path Security Check
# ---------------------------------------------------------------------------


def is_safe_path(path: str) -> bool:
    """Check whether a URL path is safe (no path-traversal attempts).

    The function normalises the path with ``posixpath.normpath`` and rejects
    any path that contains ``..`` components.

    Args:
        path: The URL path to check.

    Returns:
        ``True`` if the path is safe, ``False`` if it contains ``..``.
    """
    if not path:
        return False
    # Normalise to detect any '..' traversal
    normalised = posixpath.normpath(path)
    # If the normalised path starts with '..' or contains '/../' or ends with
    # '/..', it's unsafe.  We also check the raw path for any '..' token.
    if ".." in normalised.split("/"):
        return False
    if ".." in path.split("/"):
        return False
    return True


# ---------------------------------------------------------------------------
# T003 — POST Data Parser
# ---------------------------------------------------------------------------


def parse_post_data(data: bytes, content_type: str) -> dict:
    """Parse POST request body data.

    Supports ``application/x-www-form-urlencoded`` and
    ``multipart/form-data`` content types.

    Args:
        data: Raw request body bytes.
        content_type: Value of the Content-Type header.

    Returns:
        A dictionary of parsed key-value pairs.  Values are always strings
        (for form-urlencoded the last value wins if a key appears multiple
        times).  Returns an empty dict if the content type is unsupported or
        the data is empty.
    """
    if not data:
        return {}

    content_type_lower = content_type.lower()

    if "application/x-www-form-urlencoded" in content_type_lower:
        parsed = urllib.parse.parse_qs(data.decode("utf-8", errors="replace"))
        # Flatten lists — take the last value for each key
        return {k: v[-1] if isinstance(v, list) else v for k, v in parsed.items()}

    if "multipart/form-data" in content_type_lower:
        # Use cgi.FieldStorage for multipart parsing (works in Python < 3.13)
        # For Python 3.13+, we provide a basic manual fallback.
        try:
            env = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(len(data)),
            }
            # Use io.BytesIO to simulate file-like input
            fp = io.BytesIO(data)
            fields = cgi.FieldStorage(fp=fp, environ=env, keep_blank_values=True)
            result: dict = {}
            for key in fields:
                field = fields[key]
                if isinstance(field, list):
                    result[key] = [f.value for f in field]
                else:
                    result[key] = field.value
            return result
        except Exception:
            # Fallback: try simple parsing
            return _parse_multipart_simple(data, content_type)

    return {}


def _parse_multipart_simple(data: bytes, content_type: str) -> dict:
    """Basic multipart/form-data parser fallback.

    Args:
        data: Raw request body bytes.
        content_type: Content-Type header value (must contain boundary=...).

    Returns:
        A dictionary of parsed fields.
    """
    result: dict = {}
    boundary = _extract_boundary(content_type)
    if not boundary:
        return result

    boundary_bytes = boundary.encode("utf-8")
    parts = data.split(b"--" + boundary_bytes)

    for part in parts:
        if not part or part.strip() == b"--" or part.strip() == b"":
            continue
        # Split headers from body at the first \r\n\r\n or \n\n
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            header_end = part.find(b"\n\n")
        if header_end == -1:
            continue

        headers_raw = part[:header_end].decode("utf-8", errors="replace")
        body = part[header_end:]
        # Strip trailing \r\n-- (end marker)
        if body.endswith(b"\r\n"):
            body = body[:-2]
        if body.endswith(b"--"):
            body = body[:-2]
        if body.endswith(b"\r\n"):
            body = body[:-2]

        # Extract name from Content-Disposition
        name = _extract_field_name(headers_raw)
        if name:
            result[name] = body.decode("utf-8", errors="replace")

    return result


def _extract_boundary(content_type: str) -> Optional[str]:
    """Extract the boundary string from a multipart Content-Type header."""
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part[len("boundary="):].strip('"')
    return None


def _extract_field_name(headers: str) -> Optional[str]:
    """Extract the ``name`` parameter from a Content-Disposition header."""
    for line in headers.split("\r\n"):
        line = line.strip()
        if line.lower().startswith("content-disposition"):
            for segment in line.split(";"):
                segment = segment.strip()
                if segment.startswith("name="):
                    return segment[len("name="):].strip('"')
    return None


# ---------------------------------------------------------------------------
# T004 — Log Formatting
# ---------------------------------------------------------------------------


def format_log_entry(
    client_ip: str,
    method: str,
    path: str,
    status_code: int,
    size: int,
) -> str:
    """Format a log entry in the Apache Common Log Format style.

    Args:
        client_ip: Client IP address.
        method: HTTP method (e.g. ``GET``, ``POST``).
        path: Request path.
        status_code: HTTP response status code.
        size: Response body size in bytes.

    Returns:
        A formatted log string suitable for stderr output.
    """
    timestamp = time.strftime("[%d/%b/%Y %H:%M:%S]", time.gmtime())
    return (
        f'{client_ip} - - {timestamp} '
        f'"{method} {path} HTTP/1.1" {status_code} {size}'
    )


# ---------------------------------------------------------------------------
# T005 — CLI Argument Parser
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the HTTP server.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        An ``argparse.Namespace`` with ``port``, ``host``, and ``root`` fields.

    Raises:
        SystemExit: If validation fails (invalid port, missing root, etc.).
    """
    parser = argparse.ArgumentParser(
        description="Simple HTTP Server — serve static files with GET/POST support.",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        default=DEFAULT_HOST,
        help=f"Bind address (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--root", "-r",
        type=str,
        default=DEFAULT_ROOT,
        help=f"Document root directory (default: '{DEFAULT_ROOT}')",
    )

    args = parser.parse_args(argv)

    # Validate port
    if args.port < 1 or args.port > 65535:
        print(f"Error: Invalid port number {args.port}", file=sys.stderr)
        sys.exit(1)

    # Validate root directory
    root_path = os.path.abspath(args.root)
    if not os.path.exists(root_path):
        print(f"Error: Root directory {root_path} does not exist", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(root_path):
        print(f"Error: Root path {root_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    args.root = root_path
    return args


# ---------------------------------------------------------------------------
# T006 — ThreadingHTTPServer
# ---------------------------------------------------------------------------


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded HTTP server.

    Each request is handled in a separate thread, allowing concurrent
    processing without blocking other requests.

    Attributes:
        allow_reuse_address: Allow re-binding to a recently used address.
        daemon_threads: Worker threads exit when the main thread exits.
    """

    allow_reuse_address = True
    daemon_threads = True


# ---------------------------------------------------------------------------
# T007 — SimpleHTTPRequestHandler (core class)
# ---------------------------------------------------------------------------


class SimpleHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP request handler with GET/POST support, file routing,
    and custom 404 error pages.

    Class attributes set by the server before serving:
        doc_root (str): Absolute path to the document root directory.
        max_post_size (int): Maximum allowed POST body size (default 10 MB).
    """

    server_version = SERVER_VERSION
    doc_root: str = ""
    max_post_size: int = MAX_POST_SIZE

    # ------------------------------------------------------------------
    # Helper: send a complete response with body
    # ------------------------------------------------------------------

    def _send_response(
        self,
        status_code: int,
        body: bytes,
        content_type: str = "text/plain",
        headers: Optional[dict] = None,
    ) -> None:
        """Send a complete HTTP response with the given status, body and headers.

        Args:
            status_code: HTTP status code.
            body: Response body as bytes.
            content_type: Value for the Content-Type header.
            headers: Additional response headers as a dict.
        """
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # T007 — serve_file
    # ------------------------------------------------------------------

    def serve_file(self, filepath: str, status_code: int = 200) -> None:
        """Read a file from disk and send it as the HTTP response.

        Uses ``shutil.copyfileobj`` for efficient streaming of large files.

        Args:
            filepath: Absolute path to the file to serve.
            status_code: HTTP status code to return (default 200).
        """
        try:
            with open(filepath, "rb") as f:
                fs = os.fstat(f.fileno())
                content_length = fs.st_size
                content_type = get_mime_type(filepath)

                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(content_length))
                self.end_headers()

                # Stream file content in chunks
                import shutil
                shutil.copyfileobj(f, self.wfile)
        except OSError:
            self.handle_error(500, "500 Internal Server Error")

    # ------------------------------------------------------------------
    # T007 — handle_404
    # ------------------------------------------------------------------

    def handle_404(self) -> None:
        """Return a 404 Not Found response.

        If the document root contains a ``404.html`` file, its content is
        returned with ``Content-Type: text/html``.  Otherwise a plain-text
        fallback message is returned.
        """
        custom_404_path = os.path.join(self.doc_root, "404.html")
        if os.path.isfile(custom_404_path):
            try:
                with open(custom_404_path, "rb") as f:
                    body = f.read()
                self._send_response(404, body, "text/html")
            except OSError:
                self._send_response(404, b"404 Not Found", "text/plain")
        else:
            self._send_response(404, b"404 Not Found", "text/plain")

    # ------------------------------------------------------------------
    # T007 — handle_403
    # ------------------------------------------------------------------

    def handle_403(self) -> None:
        """Return a 403 Forbidden response for path-traversal attempts."""
        self._send_response(
            403,
            b"403 Forbidden - Path traversal detected",
            "text/plain",
        )

    # ------------------------------------------------------------------
    # T007 — handle_error (generic)
    # ------------------------------------------------------------------

    def handle_error(
        self,
        status_code: int,
        message: str,
        content_type: str = "text/plain",
    ) -> None:
        """Send a generic error response.

        Args:
            status_code: HTTP status code.
            message: Response body string.
            content_type: Content-Type header value (default ``text/plain``).
        """
        self._send_response(status_code, message.encode("utf-8"), content_type)

    # ------------------------------------------------------------------
    # T007 — list_directory
    # ------------------------------------------------------------------

    def list_directory(self, dir_path: str) -> None:
        """Generate and return an HTML directory listing.

        Args:
            dir_path: Absolute path to the directory to list.
        """
        try:
            entries = sorted(os.listdir(dir_path))
        except OSError:
            self.handle_error(500, "500 Internal Server Error")
            return

        # Build a simple HTML page
        lines = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'>",
            "<title>Directory listing</title>",
            "</head><body>",
            "<h1>Directory listing</h1>",
            "<ul>",
        ]
        # Add parent directory link if not at root
        request_path = self.path.rstrip("/")
        if request_path and request_path != "/":
            parent = posixpath.dirname(request_path) or "/"
            lines.append(f'<li><a href="{parent}">..</a></li>')

        for entry in entries:
            # Skip hidden files
            if entry.startswith("."):
                continue
            full_path = os.path.join(dir_path, entry)
            display = entry + "/" if os.path.isdir(full_path) else entry
            href = posixpath.join(self.path.rstrip("/"), entry)
            lines.append(f'<li><a href="{href}">{display}</a></li>')

        lines.append("</ul></body></html>")
        body = "\n".join(lines).encode("utf-8")
        self._send_response(200, body, "text/html; charset=utf-8")

    # ------------------------------------------------------------------
    # T007 — send_head (path validation shared by GET/POST)
    # ------------------------------------------------------------------

    def send_head(self) -> Optional[str]:
        """Validate the request path and return the resolved file path.

        Performs the following checks:
        - Path must start with ``/`` (else 400).
        - Path length must not exceed ``MAX_URI_LENGTH`` (else 414).
        - Path must not contain ``..`` (else 403).

        Returns:
            The absolute file path to serve, or ``None`` if an error response
            was sent.
        """
        if not self.path.startswith("/"):
            self.handle_error(400, "400 Bad Request")
            return None

        if len(self.path) > MAX_URI_LENGTH:
            self.handle_error(414, "414 URI Too Long")
            return None

        if not is_safe_path(self.path):
            self.handle_403()
            return None

        # Normalise path
        parsed_path = urllib.parse.urlparse(self.path).path
        normalised_path = posixpath.normpath(parsed_path)

        # Construct absolute filesystem path
        # Strip leading slash and join with doc_root
        relative = normalised_path.lstrip("/")
        abs_path = os.path.join(self.doc_root, relative)

        return abs_path

    # ------------------------------------------------------------------
    # T008 — do_GET
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        """Handle GET requests.

        Supported routes:
        - ``/api/hello`` → JSON greeting.
        - ``/`` or ``/index.html`` → serve index.html or directory listing.
        - ``/path/to/file`` → serve static file.
        """
        # API route
        if self.path == "/api/hello":
            body = json.dumps({"message": "Hello, World!"}).encode("utf-8")
            self._send_response(200, body, "application/json")
            self._log_request(200, len(body))
            return

        # Path validation
        abs_path = self.send_head()
        if abs_path is None:
            # Error response already sent
            self._log_request(
                int(self.responses.get(self.responses.get(self.command, ""), (500,))[0]),
                0,
            )
            return

        # Check if path exists
        if not os.path.exists(abs_path):
            self.handle_404()
            self._log_request(404, 0)
            return

        # If it's a directory, look for index.html or list contents
        if os.path.isdir(abs_path):
            index_path = os.path.join(abs_path, "index.html")
            if os.path.isfile(index_path):
                self.serve_file(index_path)
                try:
                    self._log_request(200, os.path.getsize(index_path))
                except OSError:
                    self._log_request(200, 0)
            else:
                # Only show directory listing for root or explicitly allowed
                self.list_directory(abs_path)
                self._log_request(200, 0)
            return

        # It's a file — serve it
        try:
            file_size = os.path.getsize(abs_path)
        except OSError:
            file_size = 0
        self.serve_file(abs_path)
        self._log_request(200, file_size)

    # ------------------------------------------------------------------
    # T009 — do_POST
    # ------------------------------------------------------------------

    def do_POST(self) -> None:
        """Handle POST requests.

        Only ``/submit`` and ``/api/hello`` are accepted (others return 405).

        - ``POST /submit``: Parses form data and returns JSON with received data.
        - ``POST /api/hello``: Returns a JSON greeting (same as GET).
        """
        if self.path not in ("/submit", "/api/hello"):
            self.handle_error(405, "405 Method Not Allowed")
            self._log_request(405, 0)
            return

        # Read Content-Length
        content_length_str = self.headers.get("Content-Length", "0")
        try:
            content_length = int(content_length_str)
        except (ValueError, TypeError):
            content_length = 0

        if content_length > self.max_post_size:
            self.handle_error(413, "413 Request Entity Too Large")
            self._log_request(413, 0)
            # Drain the remaining request body to keep TCP connection clean
            if content_length > 0:
                try:
                    remaining = content_length
                    while remaining > 0:
                        chunk_size = min(remaining, 65536)
                        chunk = self.rfile.read(chunk_size)
                        if not chunk:
                            break
                        remaining -= len(chunk)
                except Exception:
                    pass
            return

        # Read request body
        try:
            raw_data = self.rfile.read(content_length) if content_length > 0 else b""
        except Exception:
            self.handle_error(400, "400 Bad Request - Invalid form data")
            self._log_request(400, 0)
            return

        if self.path == "/api/hello":
            body = json.dumps({"message": "Hello, World!"}).encode("utf-8")
            self._send_response(200, body, "application/json")
            self._log_request(200, len(body))
            return

        # Path: /submit
        content_type = self.headers.get("Content-Type", "")

        # Validate Content-Type
        supported_types = [
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        ]
        if not any(t in content_type.lower() for t in supported_types):
            self.handle_error(400, "400 Bad Request - Unsupported Content-Type")
            self._log_request(400, 0)
            return

        try:
            parsed = parse_post_data(raw_data, content_type)
        except Exception:
            self.handle_error(400, "400 Bad Request - Invalid form data")
            self._log_request(400, 0)
            return

        response = {"status": "ok", "received": parsed}
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self._send_response(200, body, "application/json")
        self._log_request(200, len(body))

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log_request(self, status_code: int, size: int) -> None:
        """Log the current request to stderr.

        Args:
            status_code: HTTP response status code.
            size: Response body size in bytes.
        """
        log_entry = format_log_entry(
            client_ip=self.client_address[0],
            method=self.command,
            path=self.path,
            status_code=status_code,
            size=size,
        )
        logger.info(log_entry)

    # ------------------------------------------------------------------
    # Override log_message to use our custom logger
    # ------------------------------------------------------------------

    def log_message(self, format: str, *args: object) -> None:
        """Override default log_message to redirect to our logger."""
        logger.info(format % args)


# ---------------------------------------------------------------------------
# T010 — main() Entry Point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point for the HTTP server.

    Parses CLI arguments, validates settings, creates the server, and starts
    the event loop.  Handles SIGINT for graceful shutdown.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).
    """
    args = parse_args(argv)

    # Set doc_root on the handler class
    SimpleHTTPRequestHandler.doc_root = args.root

    server: Optional[ThreadingHTTPServer] = None

    try:
        server = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
    except OSError as e:
        if "Address already in use" in str(e) or "addr already in use" in str(e).lower():
            logger.error("Error: Port %d is already in use", args.port)
        else:
            logger.error("Error: %s", e)
        sys.exit(1)

    logger.info("Starting HTTP server on %s:%d", args.host, args.port)

    # Register SIGINT handler for graceful shutdown
    def signal_handler(sig: int, frame: object) -> None:
        logger.info("Shutting down server...")
        if server:
            server.shutdown()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        if server:
            server.server_close()


if __name__ == "__main__":
    main()
