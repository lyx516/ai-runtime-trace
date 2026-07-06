# Simple HTTP Server - API Documentation

## Overview

A lightweight HTTP server built with Python standard library.
Supports GET/POST, static file routing, MIME detection, custom 404.

## Quick Start

```bash
python server.py
python server.py --port 9090 --host 127.0.0.1 --root /var/www
```

## CLI Arguments

| Arg | Short | Type | Default | Description |
|-----|-------|------|---------|-------------|
| --port | -p | int | 8080 | Port to listen on |
| --host | -H | str | 0.0.0.0 | Bind address |
| --root | -r | str | . | Document root |


## GET Endpoints

### GET / or /index.html
Returns index.html or directory listing.

```
GET / HTTP/1.1
Host: localhost
```

Response 200: HTML content.

### GET /path/to/file
Returns static file with auto-detected Content-Type.

### GET /api/hello
Returns JSON greeting.

```
GET /api/hello HTTP/1.1
Host: localhost
```

Response 200: {"message": "Hello, World!"}


## POST Endpoints

### POST /submit
Receives form data, returns JSON.

```
POST /submit HTTP/1.1
Content-Type: application/x-www-form-urlencoded

name=John&message=Hello
```

Response 200: {"status":"ok","received":{"name":"John","message":"Hello"}}

### POST /api/hello
Returns JSON greeting.

Response 200: {"message":"Hello, World!"}


## HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | OK |
| 400 | Bad Request |
| 403 | Forbidden (path traversal) |
| 404 | Not Found |
| 405 | Method Not Allowed |
| 413 | Payload Too Large |
| 414 | URI Too Long |
| 500 | Internal Server Error |


## MIME Types

| Extension | Content-Type |
|-----------|-------------|
| .html/.htm | text/html |
| .css | text/css |
| .js | application/javascript |
| .json | application/json |
| .png | image/png |
| .jpg/.jpeg | image/jpeg |
| .gif | image/gif |
| .svg | image/svg+xml |
| .txt | text/plain |
| .pdf | application/pdf |
| other | application/octet-stream |

