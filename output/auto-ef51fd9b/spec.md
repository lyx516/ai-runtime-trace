# Simple HTTP Server — 规格文档 (Specification)

## 1. 概述

实现一个基于标准库 `http.server` 和 `socketserver` 的轻量级 HTTP 服务器，支持基本的 GET/POST 请求处理、静态文件路由以及自定义 404 错误页面。

## 2. 功能需求

### 2.1 HTTP 方法支持

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/` 或 `/index.html` | 返回服务器根目录的 index.html（如果存在），否则返回目录列表或 404 |
| GET | `/path/to/file` | 返回静态文件内容 |
| POST | `/submit` | 接收表单数据（application/x-www-form-urlencoded 或 multipart/form-data），返回 JSON 响应 |
| GET | `/api/hello` | 返回 JSON 格式的问候消息 `{"message": "Hello, World!"}` |

### 2.2 文件路由

- 服务器以指定目录（默认为当前目录）作为文档根目录（Document Root）。
- 请求路径映射到文档根目录下的文件路径。
- 路径分隔符统一使用 `/`，自动转换为操作系统路径分隔符。
- 若请求路径指向一个目录，则尝试返回该目录下的 `index.html` 文件。
- 若 `index.html` 不存在且路径为 `/`，则返回目录列表（HTML 格式）。
- 路径遍历攻击防护：拒绝包含 `..` 的请求路径，返回 403 Forbidden。

### 2.3 自定义 404 页面

- 当请求的文件不存在时，返回 404 状态码。
- 如果文档根目录下存在 `404.html`，则返回该文件内容作为 404 页面。
- 如果 `404.html` 不存在，则返回默认的纯文本 404 消息：`"404 Not Found"`。
- 响应头中 Content-Type 根据文件扩展名自动识别；对于自定义 404 页面，Content-Type 为 `text/html`。

### 2.4 启动参数

服务器支持以下命令行启动参数：

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `--port` / `-p` | int | 8080 | 监听端口号 |
| `--host` / `-H` | str | "0.0.0.0" | 绑定地址 |
| `--root` / `-r` | str | "." | 文档根目录路径 |

### 2.5 MIME 类型映射

服务器至少支持以下文件扩展名到 Content-Type 的映射：

| 扩展名 | Content-Type |
|--------|-------------|
| `.html` / `.htm` | `text/html` |
| `.css` | `text/css` |
| `.js` | `application/javascript` |
| `.json` | `application/json` |
| `.png` | `image/png` |
| `.jpg` / `.jpeg` | `image/jpeg` |
| `.gif` | `image/gif` |
| `.svg` | `image/svg+xml` |
| `.txt` | `text/plain` |
| `.pdf` | `application/pdf` |
| 其他 | `application/octet-stream` |

## 3. 边界条件

### 3.1 路径安全性

- 任何包含 `..` 的请求路径必须被拒绝，返回 **403 Forbidden**。
- 请求路径必须以 `/` 开头，否则返回 **400 Bad Request**。
- 请求路径长度不得超过 2048 字符，超过则返回 **414 URI Too Long**。

### 3.2 请求大小限制

- POST 请求体大小限制为 10 MB（10 × 1024 × 1024 字节），超过返回 **413 Payload Too Large**。
- POST 请求仅允许路径 `/submit` 和 `/api/hello`，其他路径返回 **405 Method Not Allowed**。

### 3.3 并发处理

- 服务器使用 `ThreadingHTTPServer`（Python 3.7+）或 `ThreadingMixIn` + `HTTPServer`，支持多线程并发处理请求。
- 每个请求在独立线程中处理，不阻塞其他请求。

### 3.4 连接处理

- 支持 Keep-Alive（HTTP/1.1 默认）。
- 空闲连接超时时间为 30 秒。
- 服务器收到 SIGINT（Ctrl+C）时优雅关闭。

## 4. 输入输出定义

### 4.1 GET 请求

**请求示例：**
```
GET /index.html HTTP/1.1
Host: localhost:8080
```

**成功响应（200 OK）：**
```
HTTP/1.1 200 OK
Content-Type: text/html
Content-Length: 1234

<!DOCTYPE html>
<html>...
```

**文件不存在响应（404 Not Found）：**
```
HTTP/1.1 404 Not Found
Content-Type: text/html
Content-Length: 456

<!DOCTYPE html><html><body><h1>404 - Page Not Found</h1></body></html>
```

### 4.2 POST 请求

**请求示例：**
```
POST /submit HTTP/1.1
Host: localhost:8080
Content-Type: application/x-www-form-urlencoded
Content-Length: 27

name=John&message=Hello%20World
```

**成功响应（200 OK）：**
```
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: 78

{"status": "ok", "received": {"name": "John", "message": "Hello World"}}
```

### 4.3 错误响应格式

| 状态码 | 短语 | 响应体 |
|--------|------|--------|
| 400 | Bad Request | `"400 Bad Request"` (text/plain) |
| 403 | Forbidden | `"403 Forbidden - Path traversal detected"` (text/plain) |
| 404 | Not Found | 自定义 404.html 或 `"404 Not Found"` (text/html 或 text/plain) |
| 405 | Method Not Allowed | `"405 Method Not Allowed"` (text/plain) |
| 413 | Payload Too Large | `"413 Request Entity Too Large"` (text/plain) |
| 414 | URI Too Long | `"414 URI Too Long"` (text/plain) |
| 500 | Internal Server Error | `"500 Internal Server Error"` (text/plain) |

## 5. 错误处理

### 5.1 服务器启动错误

| 场景 | 行为 |
|------|------|
| 端口被占用 | 打印错误信息 `"Error: Port {port} is already in use"`，退出码 1 |
| 文档根目录不存在 | 打印错误信息 `"Error: Root directory {path} does not exist"`，退出码 1 |
| 文档根目录不是目录 | 打印错误信息 `"Error: Root path {path} is not a directory"`，退出码 1 |
| 无效端口号（<1024 且非 root，或 >65535） | 打印错误信息 `"Error: Invalid port number {port}"`，退出码 1 |

### 5.2 请求处理错误

| 场景 | 行为 |
|------|------|
| 文件读取时发生 IO 错误 | 返回 **500 Internal Server Error** |
| POST 请求体解析失败 | 返回 **400 Bad Request**，响应体为 `"400 Bad Request - Invalid form data"` |
| 不支持的 Content-Type（POST） | 返回 **400 Bad Request**，响应体为 `"400 Bad Request - Unsupported Content-Type"` |

### 5.3 日志记录

服务器应将以下事件输出到 stderr：

| 事件 | 日志格式 |
|------|---------|
| 服务器启动 | `[INFO] Starting HTTP server on {host}:{port}` |
| 收到请求 | `[INFO] {client_ip} - - [{timestamp}] "{method} {path} HTTP/1.1" {status_code} {size}` |
| 错误 | `[ERROR] {error_message}` |
| 服务器关闭 | `[INFO] Shutting down server...` |

## 6. 验收标准

### 6.1 功能验收

| # | 测试场景 | 预期结果 |
|---|---------|---------|
| 1 | 启动服务器（默认参数） | 服务器监听 0.0.0.0:8080，打印启动日志 |
| 2 | 使用 `--port 9090` 启动 | 服务器监听 0.0.0.0:9090 |
| 3 | 使用 `--root /tmp/www` 启动 | 服务器以 `/tmp/www` 为文档根目录 |
| 4 | 使用 `--host 127.0.0.1` 启动 | 服务器仅监听 127.0.0.1 |
| 5 | GET 请求获取存在的文件 | 返回 200，文件内容正确，Content-Type 正确 |
| 6 | GET 请求获取不存在的文件 | 返回 404，显示自定义 404.html（如果存在）或默认消息 |
| 7 | GET 请求根路径 | 返回 index.html（如果存在）或目录列表 |
| 8 | POST 请求到 `/submit` | 返回 200，JSON 响应包含接收到的数据 |
| 9 | POST 请求到 `/api/hello` | 返回 200，JSON 响应 `{"message": "Hello, World!"}` |
| 10 | POST 请求到不允许的路径 | 返回 405 |
| 11 | GET 请求包含 `..` 的路径 | 返回 403 |
| 12 | 请求路径超过 2048 字符 | 返回 414 |
| 13 | POST 请求体超过 10MB | 返回 413 |
| 14 | 端口被占用时启动 | 打印错误并退出码 1 |
| 15 | 根目录不存在时启动 | 打印错误并退出码 1 |
| 16 | 并发请求处理 | 多个请求同时处理，均正确响应 |

### 6.2 代码质量要求

- 代码符合 PEP 8 规范。
- 所有函数和类有 docstring。
- 类型注解覆盖所有函数签名。
- 测试覆盖率达到 80% 以上。
- 使用 `unittest` 或 `pytest` 编写测试。

### 6.3 交付物

| 文件 | 描述 |
|------|------|
| `server.py` | HTTP 服务器实现代码 |
| `test_server.py` | 测试用例 |
| `api_docs.md` | API 文档 |
| `implementation-report.md` | 实现报告 |

## 7. 架构概要

```
HTTP Request  →  ThreadingHTTPServer  →  Custom RequestHandler
                                           ├── do_GET()
                                           ├── do_POST()
                                           ├── serve_file()
                                           ├── handle_404()
                                           ├── parse_post_data()
                                           └── get_mime_type()
```

### 核心类

1. **SimpleHTTPRequestHandler** — 继承 `http.server.BaseHTTPRequestHandler`，实现请求处理逻辑。
2. **ThreadingHTTPServer** — 使用 `socketserver.ThreadingMixIn` 实现多线程并发。

### 辅助函数

1. `get_mime_type(path: str) → str` — 根据文件扩展名返回 MIME 类型。
2. `is_safe_path(path: str) → bool` — 检查路径是否安全（无 `..` 遍历）。
3. `parse_post_data(data: bytes, content_type: str) → dict` — 解析 POST 表单数据。
4. `format_log_entry(client_ip, method, path, status, size) → str` — 格式化日志条目。
