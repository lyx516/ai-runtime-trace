#!/usr/bin/env python3
"""Generate test_server.py"""
import os, unittest
p = os.path.join(os.path.dirname(__file__), "test_server.py")
l = []
def a(s=""): l.append(s)
a("#!/usr/bin/env python3")
a('"""Test suite for Simple HTTP Server."""')
a("from __future__ import annotations")
a("import io, json, os, socket, sys, tempfile, threading, unittest")
a("from pathlib import Path")
a("from unittest.mock import MagicMock, patch")
a("sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))")
a("import server")
a("")
# TestGetMimeType
class TestGetMimeType(unittest.TestCase):
    """Test MIME type mapping."""
    def test_html(self):
        self.assertEqual(server.get_mime_type("x.html"), "text/html")
    def test_css(self):
        self.assertEqual(server.get_mime_type("x.css"), "text/css")
    def test_js(self):
        self.assertEqual(server.get_mime_type("x.js"), "application/javascript")
    def test_json(self):
        self.assertEqual(server.get_mime_type("x.json"), "application/json")
    def test_png(self):
        self.assertEqual(server.get_mime_type("x.png"), "image/png")
    def test_jpg(self):
        self.assertEqual(server.get_mime_type("x.jpg"), "image/jpeg")
    def test_gif(self):
        self.assertEqual(server.get_mime_type("x.gif"), "image/gif")
    def test_svg(self):
        self.assertEqual(server.get_mime_type("x.svg"), "image/svg+xml")
    def test_txt(self):
        self.assertEqual(server.get_mime_type("x.txt"), "text/plain")
    def test_pdf(self):
        self.assertEqual(server.get_mime_type("x.pdf"), "application/pdf")
    def test_unknown(self):
        self.assertEqual(server.get_mime_type("x.xyz"), "application/octet-stream")
    def test_no_ext(self):
        self.assertEqual(server.get_mime_type("Makefile"), "application/octet-stream")

class TestIsSafePath(unittest.TestCase):
    """Test path security check."""
    def test_safe_normal(self):
        self.assertTrue(server.is_safe_path("/index.html"))
    def test_safe_subdir(self):
        self.assertTrue(server.is_safe_path("/sub/file.txt"))
    def test_safe_root(self):
        self.assertTrue(server.is_safe_path("/"))
    def test_unsafe_dotdot(self):
        self.assertFalse(server.is_safe_path("/../etc/passwd"))
    def test_unsafe_mid(self):
        self.assertFalse(server.is_safe_path("/foo/../bar"))
    def test_unsafe_end(self):
        self.assertFalse(server.is_safe_path("/foo/.."))
    def test_unsafe_encoded(self):
        self.assertFalse(server.is_safe_path("/foo/%2e%2e/bar"))

class TestParsePostData(unittest.TestCase):
    """Test POST data parsing."""
    def test_urlencoded(self):
        d = b"name=John&msg=Hello%20World"
        r = server.parse_post_data(d, "application/x-www-form-urlencoded")
        self.assertEqual(r, {"name": "John", "msg": "Hello World"})
    def test_empty(self):
        self.assertEqual(server.parse_post_data(b"", "form"), {})
    def test_unsupported(self):
        self.assertEqual(server.parse_post_data(b"x=y", "text/plain"), {})
    def test_multipart(self):
        b = "----B"
        body = f"--{b}\r\nContent-Disposition: form-data; name=\"f1\"\r\n\r\nv1\r\n--{b}--\r\n".encode()
        ct = f"multipart/form-data; boundary={b}"
        self.assertEqual(server.parse_post_data(body, ct), {"f1": "v1"})

class TestFormatLogEntry(unittest.TestCase):
    """Test log formatting."""
    def test_format(self):
        r = server.format_log_entry("1.2.3.4", "GET", "/x", 200, 99)
        self.assertIn("1.2.3.4", r)
        self.assertIn("GET", r)
        self.assertIn("/x", r)
        self.assertIn("200", r)
        self.assertIn("99", r)
        self.assertIn("[INFO]", r)

class TestParseArgs(unittest.TestCase):
    """Test CLI argument parsing."""
    def test_defaults(self):
        a = server.parse_args([])
        self.assertEqual(a.port, 8080)
        self.assertEqual(a.host, '0.0.0.0')
    def test_custom_port(self):
        a = server.parse_args(['--port', '9090'])
        self.assertEqual(a.port, 9090)
    def test_custom_host(self):
        a = server.parse_args(['--host', '127.0.0.1'])
        self.assertEqual(a.host, '127.0.0.1')
    def test_custom_root(self):
        a = server.parse_args(['--root', '.'])
        self.assertTrue(os.path.isabs(a.root))
    def test_port_too_high(self):
        with self.assertRaises(SystemExit):
            server.parse_args(['--port', '99999'])
    def test_root_not_exist(self):
        with self.assertRaises(SystemExit):
            server.parse_args(['--root', '/nonexistent_path_xyz'])

class TestHandlerServeFile(unittest.TestCase):
    """Test serve_file and related handler methods."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        Path(self.tmp, 'test.txt').write_text('Hello')
        Path(self.tmp, 'index.html').write_text('<h1>Index</h1>')
        Path(self.tmp, '404.html').write_text('<h1>Custom 404</h1>')
    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)
    def _handler(self, method='GET', path='/'):
        h = server.SimpleHTTPRequestHandler
        h.doc_root = self.tmp
        return h
    def test_get_mime_type(self):
        self.assertEqual(server.get_mime_type('test.txt'), 'text/plain')
    def test_is_safe_path(self):
        self.assertTrue(server.is_safe_path('/test.txt'))
        self.assertFalse(server.is_safe_path('/../x'))
    def test_parse_post_data(self):
        r = server.parse_post_data(b'a=1&b=2', 'application/x-www-form-urlencoded')
        self.assertEqual(r, {'a': '1', 'b': '2'})
    def test_format_log(self):
        r = server.format_log_entry('1.2.3.4', 'GET', '/x', 200, 5)
        self.assertIn('1.2.3.4', r)
    def test_parse_args(self):
        a = server.parse_args([])
        self.assertEqual(a.port, 8080)

class TestHandlerWithMock(unittest.TestCase):
    """Test handler with mocked socket."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        Path(self.tmp, 'test.txt').write_text('Hello')
        Path(self.tmp, 'index.html').write_text('<h1>Index</h1>')
        Path(self.tmp, '404.html').write_text('<h1>Custom 404</h1>')
    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)
    def _mk_handler(self, path='/', method='GET'):
        h = server.SimpleHTTPRequestHandler
        h.doc_root = self.tmp
        return h
    def test_unknown_ext(self):
        self.assertEqual(server.get_mime_type('file.zzzzz'), 'application/octet-stream')
    def test_multipart2(self):
        b = 'BOUNDARY123'
        body = f'--{b}\r\nContent-Disposition: form-data; name="f1"\r\n\r\nv1\r\n--{b}--\r\n'.encode()
        ct = f'multipart/form-data; boundary={b}'
        r = server.parse_post_data(body, ct)
        self.assertEqual(r, {'f1': 'v1'})
