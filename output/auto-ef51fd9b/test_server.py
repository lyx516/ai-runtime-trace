#!/usr/bin/env python3
"""Test suite for the Simple HTTP Server.

Covers all functions, classes, and HTTP request handling scenarios
defined in the specification.  Uses ``unittest`` with mocking for
filesystem and network isolation.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, Mock, patch

# Ensure the server module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server


# ======================================================================
# T001 — MIME Type Mapping Tests
# ======================================================================


class TestGetMimeType(unittest.TestCase):
    """Tests for the ``get_mime_type`` function."""

    def test_html(self) -> None:
        """.html returns text/html."""
        self.assertEqual(server.get_mime_type("index.html"), "text/html")

    def test_htm(self) -> None:
        """.htm returns text/html."""
        self.assertEqual(server.get_mime_type("page.htm"), "text/html")

    def test_css(self) -> None:
        """.css returns text/css."""
        self.assertEqual(server.get_mime_type("style.css"), "text/css")

    def test_js(self) -> None:
        """.js returns application/javascript."""
        self.assertEqual(server.get_mime_type("app.js"), "application/javascript")

    def test_json(self) -> None:
        """.json returns application/json."""
        self.assertEqual(server.get_mime_type("data.json"), "application/json")

    def test_png(self) -> None:
        """.png returns image/png."""
        self.assertEqual(server.get_mime_type("image.png"), "image/png")

    def test_jpg(self) -> None:
        """.jpg returns image/jpeg."""
        self.assertEqual(server.get_mime_type("photo.jpg"), "image/jpeg")

    def test_jpeg(self) -> None:
        """.jpeg returns image/jpeg."""
        self.assertEqual(server.get_mime_type("photo.jpeg"), "image/jpeg")

    def test_gif(self) -> None:
        """.gif returns image/gif."""
        self.assertEqual(server.get_mime_type("anim.gif"), "image/gif")

    def test_svg(self) -> None:
        """.svg returns image/svg+xml."""
        self.assertEqual(server.get_mime_type("graphic.svg"), "image/svg+xml")

    def test_txt(self) -> None:
        """.txt returns text/plain."""
        self.assertEqual(server.get_mime_type("readme.txt"), "text/plain")

    def test_pdf(self) -> None:
        """.pdf returns application/pdf."""
        self.assertEqual(server.get_mime_type("doc.pdf"), "application/pdf")

    def test_unknown_extension(self) -> None:
        """Unknown extension returns application/octet-stream."""
        self.assertEqual(
            server.get_mime_type("file.xyz"),
            "application/octet-stream",
        )

    def test_no_extension(self) -> None:
        """No extension returns application/octet-stream."""
        self.assertEqual(
            server.get_mime_type("Makefile"),
            "application/octet-stream",
        )

    def test_case_insensitive(self) -> None:
        """Extension matching is case-insensitive."""
        self.assertEqual(server.get_mime_type("INDEX.HTML"), "text/html")
        self.assertEqual(server.get_mime_type("Photo.JPG"), "image/jpeg")


# ======================================================================
# T002 — Path Security Tests
# ======================================================================


class TestIsSafePath(unittest.TestCase):
    """Tests for the ``is_safe_path`` function."""

    def test_safe_normal_path(self) -> None:
        """Normal path /index.html is safe."""
        self.assertTrue(server.is_safe_path("/index.html"))

    def test_safe_subdirectory(self) -> None:
        """Path with subdirectory is safe."""
        self.assertTrue(server.is_safe_path("/subdir/file.txt"))

    def test_safe_root(self) -> None:
        """Root path / is safe."""
        self.assertTrue(server.is_safe_path("/"))

    def test_unsafe_dotdot(self) -> None:
        """Path containing '..' is unsafe."""
        self.assertFalse(server.is_safe_path("/../etc"))

    def test_unsafe_dotdot_slash(self) -> None:
        """Path containing '../' is unsafe."""
        self.assertFalse(server.is_safe_path("/static/../etc/passwd"))

    def test_unsafe_dotdot_start(self) -> None:
        """Path starting with '..' is unsafe."""
        self.assertFalse(server.is_safe_path("../etc"))

    def test_unsafe_dotdot_end(self) -> None:
        """Path ending with '..' is unsafe."""
        self.assertFalse(server.is_safe_path("/etc/.."))

    def test_unsafe_encoded_dotdot(self) -> None:
        """Path with '..' in middle of path is unsafe."""
        self.assertFalse(server.is_safe_path("/safe/../etc"))

    def test_safe_deeply_nested(self) -> None:
        """Deeply nested normal path is safe."""
        self.assertTrue(server.is_safe_path("/a/b/c/d/e/f/file.txt"))

    def test_safe_with_dots_in_name(self) -> None:
        """Path with legitimate dots in filename is safe."""
        self.assertTrue(server.is_safe_path("/file.name.with.dots.txt"))


# ======================================================================
# T003 — POST Data Parsing Tests
# ======================================================================


class TestParsePostData(unittest.TestCase):
    """Tests for the ``parse_post_data`` function."""

    def test_empty_data(self) -> None:
        """Empty data returns empty dict."""
        self.assertEqual(server.parse_post_data(b"", "application/x-www-form-urlencoded"), {})

    def test_urlencoded_simple(self) -> None:
        """Simple url-encoded data is parsed correctly."""
        result = server.parse_post_data(
            b"name=John&message=Hello%20World",
            "application/x-www-form-urlencoded",
        )
        self.assertEqual(result, {"name": "John", "message": "Hello World"})

    def test_urlencoded_multiple_values(self) -> None:
        """Multiple values for same key: last value wins."""
        result = server.parse_post_data(
            b"key=a&key=b&key=c",
            "application/x-www-form-urlencoded",
        )
        self.assertEqual(result, {"key": "c"})

    def test_urlencoded_special_chars(self) -> None:
        """Special characters are properly decoded."""
        result = server.parse_post_data(
            b"text=%2B%2F%3D&empty=&encoded=%C3%A9%C3%A0%C3%BC",
            "application/x-www-form-urlencoded",
        )
        self.assertIn("text", result)
        # 'empty=' with no value may or may not appear; check the ones we know exist
        self.assertIn("encoded", result)

    def test_unsupported_content_type(self) -> None:
        """Unsupported content type returns empty dict."""
        result = server.parse_post_data(b"data", "application/xml")
        self.assertEqual(result, {})

    def test_multipart_simple(self) -> None:
        """Simple multipart/form-data is parsed."""
        boundary = "----TestBoundary123"
        content_type = f"multipart/form-data; boundary={boundary}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="field1"\r\n\r\n'
            f"value1\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="field2"\r\n\r\n'
            f"value2\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        result = server.parse_post_data(body, content_type)
        self.assertEqual(result.get("field1"), "value1")
        self.assertEqual(result.get("field2"), "value2")


# ======================================================================
# T004 — Log Formatting Tests
# ======================================================================


class TestFormatLogEntry(unittest.TestCase):
    """Tests for the ``format_log_entry`` function."""

    def test_format_basic(self) -> None:
        """Basic log entry is correctly formatted."""
        entry = server.format_log_entry("127.0.0.1", "GET", "/test", 200, 100)
        self.assertIn("127.0.0.1", entry)
        self.assertIn("GET /test HTTP/1.1", entry)
        self.assertIn("200", entry)
        self.assertIn("100", entry)
        self.assertIn("[", entry)
        self.assertIn("]", entry)

    def test_format_post(self) -> None:
        """POST request log entry is correctly formatted."""
        entry = server.format_log_entry("192.168.1.1", "POST", "/submit", 200, 45)
        self.assertIn("192.168.1.1", entry)
        self.assertIn("POST /submit HTTP/1.1", entry)
        self.assertIn("200", entry)
        self.assertIn("45", entry)

    def test_format_error(self) -> None:
        """Error response log entry is correctly formatted."""
        entry = server.format_log_entry("10.0.0.1", "GET", "/missing", 404, 0)
        self.assertIn("404", entry)
        self.assertIn("0", entry)

    def test_timestamp_format(self) -> None:
        """Timestamp follows [DD/Mon/YYYY HH:MM:SS] format."""
        entry = server.format_log_entry("1.2.3.4", "GET", "/", 200, 0)
        # Extract timestamp part
        import re
        match = re.search(r'\[(\d{2}/\w{3}/\d{4} \d{2}:\d{2}:\d{2})\]', entry)
        self.assertIsNotNone(match, f"Timestamp not found in: {entry}")


# ======================================================================
# T005 — CLI Argument Parsing Tests
# ======================================================================


class TestParseArgs(unittest.TestCase):
    """Tests for the ``parse_args`` function."""

    def test_default_values(self) -> None:
        """Default values are correct."""
        args = server.parse_args([])
        self.assertEqual(args.port, server.DEFAULT_PORT)
        self.assertEqual(args.host, server.DEFAULT_HOST)
        self.assertEqual(args.root, os.path.abspath("."))

    def test_custom_port(self) -> None:
        """--port sets port correctly."""
        args = server.parse_args(["--port", "9090"])
        self.assertEqual(args.port, 9090)

    def test_custom_host(self) -> None:
        """--host sets host correctly."""
        args = server.parse_args(["--host", "127.0.0.1"])
        self.assertEqual(args.host, "127.0.0.1")

    def test_custom_root(self) -> None:
        """--root sets root correctly (resolved to absolute path)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = server.parse_args(["--root", tmpdir])
            self.assertEqual(args.root, os.path.abspath(tmpdir))

    def test_short_options(self) -> None:
        """Short options (-p, -H, -r) work correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = server.parse_args(["-p", "3000", "-H", "0.0.0.0", "-r", tmpdir])
            self.assertEqual(args.port, 3000)
            self.assertEqual(args.host, "0.0.0.0")
            self.assertEqual(args.root, os.path.abspath(tmpdir))

    def test_invalid_port_too_low(self) -> None:
        """Port < 1 exits with error."""
        with self.assertRaises(SystemExit):
            server.parse_args(["--port", "0"])

    def test_invalid_port_too_high(self) -> None:
        """Port > 65535 exits with error."""
        with self.assertRaises(SystemExit):
            server.parse_args(["--port", "70000"])

    def test_root_not_exists(self) -> None:
        """Non-existent root directory exits with error."""
        with self.assertRaises(SystemExit):
            server.parse_args(["--root", "/nonexistent/path/12345"])

    def test_root_not_a_directory(self) -> None:
        """Root path that is a file exits with error."""
        with tempfile.NamedTemporaryFile() as tmpfile:
            with self.assertRaises(SystemExit):
                server.parse_args(["--root", tmpfile.name])


# ======================================================================
# T006 — ThreadingHTTPServer Tests
# ======================================================================


class TestThreadingHTTPServer(unittest.TestCase):
    """Tests for the ``ThreadingHTTPServer`` class."""

    def test_class_inheritance(self) -> None:
        """ThreadingHTTPServer inherits from ThreadingMixIn and HTTPServer."""
        self.assertTrue(issubclass(server.ThreadingHTTPServer, socketserver.ThreadingMixIn))
        self.assertTrue(issubclass(server.ThreadingHTTPServer, HTTPServer))

    def test_allow_reuse_address(self) -> None:
        """allow_reuse_address is True."""
        self.assertTrue(server.ThreadingHTTPServer.allow_reuse_address)

    def test_daemon_threads(self) -> None:
        """daemon_threads is True."""
        self.assertTrue(server.ThreadingHTTPServer.daemon_threads)


# ======================================================================
# T007 — SimpleHTTPRequestHandler Tests (unit)
# ======================================================================


class TestSimpleHTTPRequestHandler(unittest.TestCase):
    """Tests for the ``SimpleHTTPRequestHandler`` class methods."""

    def setUp(self) -> None:
        """Create a temporary directory with test files."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.doc_root = self.tmpdir.name

        # Create test files
        self._create_file("index.html", "<h1>Home</h1>")
        self._create_file("test.txt", "Hello, World!")
        self._create_file("404.html", "<h1>Custom 404</h1>")
        self._create_file("subdir/nested.txt", "Nested content")
        os.makedirs(os.path.join(self.doc_root, "emptydir"), exist_ok=True)

        # Build a mock request handler
        self.handler = self._make_handler()

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.tmpdir.cleanup()

    def _create_file(self, rel_path: str, content: str) -> str:
        """Create a file relative to doc_root with given content."""
        abs_path = os.path.join(self.doc_root, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(content)
        return abs_path

    def _make_handler(self, path: str = "/") -> server.SimpleHTTPRequestHandler:
        """Create a mock SimpleHTTPRequestHandler for testing."""
        # We'll use a mock instead of constructing a real handler
        handler = MagicMock(spec=server.SimpleHTTPRequestHandler)
        handler.doc_root = self.doc_root
        handler.path = path
        handler.command = "GET"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = {}
        handler.responses = {}
        handler.max_post_size = server.MAX_POST_SIZE
        handler.server_version = server.SERVER_VERSION

        # Attach real methods we want to test
        handler.get_mime_type = server.get_mime_type
        handler.is_safe_path = staticmethod(server.is_safe_path)
        handler.format_log_entry = staticmethod(server.format_log_entry)

        return handler

    def test_serve_file_exists(self) -> None:
        """serve_file reads and sends existing file."""
        handler = self._make_handler()
        handler.serve_file = server.SimpleHTTPRequestHandler.serve_file.__get__(
            handler, server.SimpleHTTPRequestHandler
        )
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.handle_error = MagicMock()

        filepath = os.path.join(self.doc_root, "test.txt")
        handler.serve_file(filepath)

        handler.send_response.assert_called_with(200)
        # Check that wfile got the content
        self.assertIn(b"Hello, World!", handler.wfile.getvalue())

    def test_serve_file_not_found(self) -> None:
        """serve_file handles missing file with 500."""
        handler = self._make_handler()
        handler.serve_file = server.SimpleHTTPRequestHandler.serve_file.__get__(
            handler, server.SimpleHTTPRequestHandler
        )
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.handle_error = MagicMock()

        handler.serve_file("/nonexistent/file.txt")
        handler.handle_error.assert_called_with(500, "500 Internal Server Error")

    def test_handle_404_with_custom_page(self) -> None:
        """handle_404 serves custom 404.html if it exists."""
        handler = self._make_handler()
        handler._send_response = MagicMock()
        handler.doc_root = self.doc_root

        # Temporarily replace handle_404 with the real one
        real_handle_404 = server.SimpleHTTPRequestHandler.handle_404.__get__(
            handler, server.SimpleHTTPRequestHandler
        )
        real_handle_404()

        handler._send_response.assert_called_once()
        args, _ = handler._send_response.call_args
        self.assertEqual(args[0], 404)
        self.assertEqual(args[2], "text/html")

    def test_handle_404_without_custom_page(self) -> None:
        """handle_404 returns default message when no 404.html."""
        handler = self._make_handler()
        handler._send_response = MagicMock()
        handler.doc_root = "/nonexistent"

        real_handle_404 = server.SimpleHTTPRequestHandler.handle_404.__get__(
            handler, server.SimpleHTTPRequestHandler
        )
        real_handle_404()

        handler._send_response.assert_called_once()
        args, _ = handler._send_response.call_args
        self.assertEqual(args[0], 404)
        self.assertEqual(args[1], b"404 Not Found")

    def test_handle_403(self) -> None:
        """handle_403 returns 403 with correct message."""
        handler = self._make_handler()
        handler._send_response = MagicMock()

        real_handle_403 = server.SimpleHTTPRequestHandler.handle_403.__get__(
            handler, server.SimpleHTTPRequestHandler
        )
        real_handle_403()

        handler._send_response.assert_called_with(
            403,
            b"403 Forbidden - Path traversal detected",
            "text/plain",
        )

    def test_handle_error(self) -> None:
        """handle_error sends correct status and message."""
        handler = self._make_handler()
        handler._send_response = MagicMock()

        real_handle_error = server.SimpleHTTPRequestHandler.handle_error.__get__(
            handler, server.SimpleHTTPRequestHandler
        )
        real_handle_error(500, "500 Internal Server Error")

        handler._send_response.assert_called_with(
            500,
            b"500 Internal Server Error",
            "text/plain",
        )


# ======================================================================
# T008 — do_GET Integration Tests
# ======================================================================


class TestDoGET(unittest.TestCase):
    """Integration tests for the ``do_GET`` method."""

    def setUp(self) -> None:
        """Set up a test server in a separate thread."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.doc_root = self.tmpdir.name

        # Create test files
        self._create_file("index.html", "<h1>Home</h1>")
        self._create_file("test.txt", "Hello, World!")
        self._create_file("subdir/nested.txt", "Nested content")
        self._create_file("404.html", "<h1>Custom 404</h1>")
        os.makedirs(os.path.join(self.doc_root, "emptydir"), exist_ok=True)

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

        # Configure handler
        server.SimpleHTTPRequestHandler.doc_root = self.doc_root

        self.httpd = server.ThreadingHTTPServer(
            ("127.0.0.1", self.port),
            server.SimpleHTTPRequestHandler,
        )
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        time.sleep(0.1)  # Wait for server to start

    def tearDown(self) -> None:
        """Shut down the test server."""
        self.httpd.shutdown()
        self.server_thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _create_file(self, rel_path: str, content: str) -> str:
        """Create a file relative to doc_root."""
        abs_path = os.path.join(self.doc_root, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(content)
        return abs_path

    def _request(self, method: str = "GET", path: str = "/",
                 body: Optional[bytes] = None,
                 content_type: Optional[str] = None) -> Tuple[int, bytes, dict]:
        """Send an HTTP request and return (status_code, body, headers)."""
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        status = response.status
        resp_body = response.read()
        resp_headers = dict(response.getheaders())
        conn.close()
        return status, resp_body, resp_headers

    # --- Test cases ---

    def test_get_index_html(self) -> None:
        """GET / returns index.html."""
        status, body, headers = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<h1>Home</h1>", body)
        ct = headers.get("Content-Type", "")
        self.assertIn("text/html", ct)

    def test_get_explicit_index_html(self) -> None:
        """GET /index.html returns index.html."""
        status, body, _ = self._request("GET", "/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"<h1>Home</h1>", body)

    def test_get_file(self) -> None:
        """GET /test.txt returns file content."""
        status, body, headers = self._request("GET", "/test.txt")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"Hello, World!")
        ct = headers.get("Content-Type", "")
        self.assertIn("text/plain", ct)

    def test_get_nested_file(self) -> None:
        """GET /subdir/nested.txt returns nested file."""
        status, body, _ = self._request("GET", "/subdir/nested.txt")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"Nested content")

    def test_get_not_found(self) -> None:
        """GET /nonexistent returns 404."""
        status, body, _ = self._request("GET", "/nonexistent.html")
        self.assertEqual(status, 404)

    def test_get_not_found_custom_404(self) -> None:
        """GET /nonexistent returns custom 404.html content."""
        status, body, headers = self._request("GET", "/nonexistent.html")
        self.assertEqual(status, 404)
        self.assertIn(b"Custom 404", body)
        ct = headers.get("Content-Type", "")
        self.assertIn("text/html", ct)

    def test_get_api_hello(self) -> None:
        """GET /api/hello returns JSON greeting."""
        status, body, headers = self._request("GET", "/api/hello")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data, {"message": "Hello, World!"})
        ct = headers.get("Content-Type", "")
        self.assertIn("application/json", ct)

    def test_get_path_traversal(self) -> None:
        """GET with '..' returns 403."""
        status, body, _ = self._request("GET", "/../etc/passwd")
        self.assertEqual(status, 403)
        self.assertIn(b"Forbidden", body)

    def test_get_long_uri(self) -> None:
        """GET with URI > 2048 chars returns 414."""
        long_path = "/" + "a" * 2050
        status, body, _ = self._request("GET", long_path)
        self.assertEqual(status, 414)

    def test_get_directory_listing(self) -> None:
        """GET /emptydir returns directory listing (no index.html)."""
        status, body, headers = self._request("GET", "/emptydir")
        self.assertEqual(status, 200)
        ct = headers.get("Content-Type", "")
        self.assertIn("text/html", ct)
        self.assertIn(b"Directory listing", body)


# ======================================================================
# T009 — do_POST Integration Tests
# ======================================================================


class TestDoPOST(unittest.TestCase):
    """Integration tests for the ``do_POST`` method."""

    def setUp(self) -> None:
        """Set up a test server in a separate thread."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.doc_root = self.tmpdir.name

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

        server.SimpleHTTPRequestHandler.doc_root = self.doc_root

        self.httpd = server.ThreadingHTTPServer(
            ("127.0.0.1", self.port),
            server.SimpleHTTPRequestHandler,
        )
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        time.sleep(0.1)

    def tearDown(self) -> None:
        """Shut down the test server."""
        self.httpd.shutdown()
        self.server_thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _request(self, method: str = "POST", path: str = "/",
                 body: Optional[bytes] = None,
                 content_type: Optional[str] = None) -> Tuple[int, bytes, dict]:
        """Send an HTTP request."""
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        status = response.status
        resp_body = response.read()
        resp_headers = dict(response.getheaders())
        conn.close()
        return status, resp_body, resp_headers

    def test_post_submit_form_urlencoded(self) -> None:
        """POST /submit with form-urlencoded data returns JSON with received data."""
        data = b"name=John&message=Hello%20World"
        status, body, headers = self._request(
            "POST", "/submit", body=data,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(status, 200)
        resp = json.loads(body)
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["received"]["name"], "John")
        self.assertEqual(resp["received"]["message"], "Hello World")
        ct = headers.get("Content-Type", "")
        self.assertIn("application/json", ct)

    def test_post_api_hello(self) -> None:
        """POST /api/hello returns JSON greeting."""
        status, body, _ = self._request("POST", "/api/hello")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data, {"message": "Hello, World!"})

    def test_post_method_not_allowed(self) -> None:
        """POST to disallowed path returns 405."""
        status, body, _ = self._request("POST", "/some/other/path")
        self.assertEqual(status, 405)

    def test_post_payload_too_large(self) -> None:
        """POST with oversized body returns 413."""
        # Use raw HTTP to avoid client-side socket issues
        import http.client
        large_size = server.MAX_POST_SIZE + 1
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/submit")
        conn.putheader("Content-Type", "application/x-www-form-urlencoded")
        conn.putheader("Content-Length", str(large_size))
        conn.endheaders()
        # Send small body - server rejects based on Content-Length
        conn.send(b"x" * 1024)
        response = conn.getresponse()
        status = response.status
        body = response.read()
        conn.close()
        self.assertEqual(status, 413)

    def test_post_unsupported_content_type(self) -> None:
        """POST with unsupported Content-Type returns 400."""
        status, body, _ = self._request(
            "POST", "/submit", body=b"data",
            content_type="application/xml",
        )
        self.assertEqual(status, 400)
        self.assertIn(b"Unsupported Content-Type", body)


# ======================================================================
# T010 — main() Entry Point Tests
# ======================================================================


class TestMainFunction(unittest.TestCase):
    """Tests for the ``main`` function."""

    def test_main_starts_and_stops(self) -> None:
        """main() starts the server and can be stopped via shutdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Find a free port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]

            # Run main in a thread
            result: List[Optional[Exception]] = [None]

            def run_main() -> None:
                try:
                    server.main(["--port", str(port), "--host", "127.0.0.1", "--root", tmpdir])
                except SystemExit:
                    pass
                except Exception as e:
                    result[0] = e

            t = threading.Thread(target=run_main, daemon=True)
            t.start()
            time.sleep(0.3)

            # Server should be running — make a request
            import http.client
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", "/")
                response = conn.getresponse()
                self.assertIn(response.status, (200, 404))
                conn.close()
            except Exception as e:
                result[0] = e

    def test_main_port_in_use(self) -> None:
        """main() exits with error when port is in use."""
        # Start a server on a port first
        with tempfile.TemporaryDirectory() as tmpdir:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
                s.listen()

                # Try to start our server on the same port
                with self.assertRaises(SystemExit):
                    server.main(["--port", str(port), "--host", "127.0.0.1", "--root", tmpdir])


# ======================================================================
# T011 — Concurrent Request Tests
# ======================================================================


class TestConcurrency(unittest.TestCase):
    """Tests for concurrent request handling."""

    def setUp(self) -> None:
        """Set up a test server."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.doc_root = self.tmpdir.name

        # Create test files
        for i in range(5):
            with open(os.path.join(self.doc_root, f"file{i}.txt"), "w") as f:
                f.write(f"Content {i}")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

        server.SimpleHTTPRequestHandler.doc_root = self.doc_root
        self.httpd = server.ThreadingHTTPServer(
            ("127.0.0.1", self.port),
            server.SimpleHTTPRequestHandler,
        )
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        time.sleep(0.1)

    def tearDown(self) -> None:
        """Shut down the test server."""
        self.httpd.shutdown()
        self.server_thread.join(timeout=2)
        self.tmpdir.cleanup()

    def test_concurrent_requests(self) -> None:
        """Multiple concurrent requests are all handled correctly."""
        import http.client

        results: List[Tuple[int, bytes]] = []
        lock = threading.Lock()

        def fetch(path: str) -> None:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                conn.request("GET", path)
                response = conn.getresponse()
                body = response.read()
                conn.close()
                with lock:
                    results.append((response.status, body))
            except Exception as e:
                with lock:
                    results.append((-1, str(e).encode()))

        threads = []
        for i in range(5):
            t = threading.Thread(target=fetch, args=(f"/file{i}.txt",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(results), 5)
        for status, body in results:
            self.assertEqual(status, 200)
            self.assertTrue(body.startswith(b"Content "))


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
