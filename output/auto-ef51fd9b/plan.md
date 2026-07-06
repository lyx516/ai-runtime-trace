# Simple HTTP Server — 技术方案 (Plan)

## 1. 架构设计

### 1.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                     Simple HTTP Server                        │
│                                                              │
│  ┌──────────────┐    ┌──────────────────────────────────┐   │
│  │    CLI Arg    │    │       ThreadingHTTPServer         │   │
│  │    Parser     │───▶│   (socketserver.ThreadingMixIn   │   │
│  │  (argparse)   │    │    + http.server.HTTPServer)     │   │
│  └──────────────┘    └──────────┬───────────────────────┘   │
│                                 │                           │
│                                 ▼                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SimpleHTTPRequestHandler                  │   │
│  │         (继承 http.server.BaseHTTPRequestHandler)      │   │
│  │                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ do_GET() │  │do_POST() │  │ 辅助方法          │   │   │
│  │  └────┬─────┘  └────┬─────┘  │  - serve_file()   │   │   │
│  │       │              │       │  - handle_404()    │   │   │
│  │       ▼              ▼       │  - handle_403()    │   │   │
│  │  ┌──────────────────────┐   │  - parse_post_data()│   │   │
│  │  │  文件系统 / 内存响应  │   │  - get_mime_type() │   │   │
│  │  └──────────────────────┘   │  - is_safe_path()   │   │   │
│  │                             └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              日志系统 (stderr)                        │   │
│  │  - 启动日志  - 请求日志  - 错误日志  - 关闭日志      │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 组件划分

| 组件 | 职责 | 文件 |
|------|------|------|
| **CLI 参数解析** | 解析 `--port`、`--host`、`--root` 等启动参数，进行合法性校验 | `server.py` — `parse_args()` 函数 |
| **ThreadingHTTPServer** | 多线程并发 HTTP 服务器，管理线程池和连接 | `server.py` — `ThreadingHTTPServer` 类 |
| **SimpleHTTPRequestHandler** | 核心请求处理器，处理 GET/POST、文件路由、错误页面 | `server.py` — `SimpleHTTPRequestHandler` 类 |
| **MIME 类型映射** | 根据文件扩展名返回 Content-Type | `server.py` — `get_mime_type()` 函数 |
| **路径安全检查** | 检查路径是否包含 `..` 遍历攻击 | `server.py` — `is_safe_path()` 函数 |
| **POST 数据解析** | 解析 `application/x-www-form-urlencoded` 和 `multipart/form-data` | `server.py` — `parse_post_data()` 函数 |
| **日志记录** | 格式化并输出日志到 stderr | `server.py` — `format_log_entry()` 函数 + 内联日志调用 |
| **入口点** | `main()` 函数，组装各组件并启动服务器 | `server.py` — `main()` 函数 |

### 1.3 模块依赖关系

```
main()
 ├── parse_args()          ← argparse
 ├── 校验端口/根目录
 ├── ThreadingHTTPServer
 │    └── SimpleHTTPRequestHandler
 │         ├── do_GET()
 │         │    ├── is_safe_path()       ← 路径安全检查
 │         │    ├── serve_file()         ← 文件服务
 │         │    │    ├── get_mime_type() ← MIME 映射
 │         │    │    └── handle_404()    ← 404 处理
 │         │    └── 目录列表生成
 │         ├── do_POST()
 │         │    ├── 路径路由 (/submit, /api/hello)
 │         │    ├── parse_post_data()    ← POST 数据解析
 │         │    └── JSON 响应生成
 │         └── 错误处理 (400/403/404/405/413/414/500)
 └── server.serve_forever()
     └── 信号处理 (SIGINT → 优雅关闭)
```

## 2. 接口定义

### 2.1 类接口

#### SimpleHTTPRequestHandler

```python
class SimpleHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    自定义 HTTP 请求处理器。
    
    类属性:
        server_version: str = "SimpleHTTPServer/1.0"
        doc_root: str              — 文档根目录路径
        max_post_size: int = 10 * 1024 * 1024  — POST 最大字节数
    """

    def do_GET(self) -> None:
        """处理 GET 请求。路由到文件服务、目录列表或 API。"""

    def do_POST(self) -> None:
        """处理 POST 请求。仅允许 /submit 和 /api/hello。"""

    def serve_file(self, filepath: str) -> None:
        """读取并返回文件内容，自动设置 Content-Type。"""

    def handle_404(self) -> None:
        """返回 404 页面（自定义 404.html 或默认消息）。"""

    def handle_403(self) -> None:
        """返回 403 Forbidden 响应。"""

    def handle_error(self, status_code: int, message: str, content_type: str = "text/plain") -> None:
        """通用错误响应方法。"""

    def list_directory(self, dir_path: str) -> None:
        """生成目录列表 HTML。"""

    def parse_post_data(self) -> dict:
        """解析 POST 请求体数据。"""
```

#### ThreadingHTTPServer

```python
class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    多线程 HTTP 服务器。
    
    类属性:
        allow_reuse_address: bool = True
        daemon_threads: bool = True
    """
```

### 2.2 函数接口

```python
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """
    解析命令行参数。
    
    Returns:
        argparse.Namespace 包含 port, host, root 字段
    """

def get_mime_type(path: str) -> str:
    """
    根据文件扩展名返回 MIME 类型。
    
    Args:
        path: 文件路径或文件名
        
    Returns:
        对应的 MIME 类型字符串，未知类型返回 application/octet-stream
    """

def is_safe_path(path: str) -> bool:
    """
    检查 URL 路径是否安全（无路径遍历攻击）。
    
    Args:
        path: URL 路径
        
    Returns:
        True 如果路径安全，False 如果包含 '..'
    """

def format_log_entry(client_ip: str, method: str, path: str, 
                     status_code: int, size: int) -> str:
    """
    格式化日志条目。
    
    Returns:
        格式化的日志字符串
    """
```

### 2.3 HTTP 响应接口

所有响应遵循标准 HTTP 协议格式：

| 场景 | 状态行 | 必含响应头 | 响应体 |
|------|--------|-----------|--------|
| 成功 GET 文件 | `200 OK` | Content-Type, Content-Length | 文件内容 |
| 成功 GET /api/hello | `200 OK` | Content-Type: application/json | `{"message": "Hello, World!"}` |
| 成功 POST /submit | `200 OK` | Content-Type: application/json | `{"status": "ok", "received": {...}}` |
| 404 文件不存在 | `404 Not Found` | Content-Type, Content-Length | 自定义 404.html 或 "404 Not Found" |
| 403 路径遍历 | `403 Forbidden` | Content-Type: text/plain | "403 Forbidden - Path traversal detected" |
| 400 请求错误 | `400 Bad Request` | Content-Type: text/plain | "400 Bad Request" |
| 405 方法不允许 | `405 Method Not Allowed` | Content-Type: text/plain | "405 Method Not Allowed" |
| 413 请求体过大 | `413 Payload Too Large` | Content-Type: text/plain | "413 Request Entity Too Large" |
| 414 URI 过长 | `414 URI Too Long` | Content-Type: text/plain | "414 URI Too Long" |
| 500 服务器错误 | `500 Internal Server Error` | Content-Type: text/plain | "500 Internal Server Error" |

## 3. 数据流

### 3.1 GET 请求数据流

```
Client                          Server
  │                               │
  │──── GET /index.html ────────▶│
  │                               │
  │                          ┌────┴────┐
  │                          │ 路径检查  │
  │                          │ 是否安全  │
  │                          └────┬────┘
  │                               │
  │                    ┌──────────┴──────────┐
  │                    │                     │
  │                 安全/                 不安全/
  │                 继续                  返回 403
  │                    │                     │
  │              ┌─────┴─────┐              │
  │              │ 检查路径   │              │
  │              │ 长度≤2048 │              │
  │              └─────┬─────┘              │
  │                    │                    │
  │          ┌─────────┴─────────┐         │
  │          │                   │         │
  │       通过/               不通过/       │
  │       继续              返回 414       │
  │          │                   │         │
  │    ┌─────┴─────┐            │         │
  │    │ 映射到     │            │         │
  │    │ 文件系统   │            │         │
  │    └─────┬─────┘            │         │
  │          │                  │         │
  │    ┌─────┴─────┐           │         │
  │    │ 文件存在?  │           │         │
  │    └─────┬─────┘           │         │
  │          │                 │         │
  │     ┌────┴────┐           │         │
  │     │         │           │         │
  │   存在/     不存在/        │         │
  │   读取      返回 404      │         │
  │   文件       (自定义      │         │
  │   内容        或默认)     │         │
  │     │         │           │         │
  │     ▼         ▼           ▼         │
  │  ＜─── 200 OK ─────────────         │
  │  ＜─── 404 Not Found ──────────     │
  │  ＜─── 403 Forbidden ─────────      │
  │  ＜─── 414 URI Too Long ───────     │
```

### 3.2 POST 请求数据流

```
Client                          Server
  │                               │
  │──── POST /submit ───────────▶│
  │    Content-Type:              │
  │    application/x-www-         │
  │    form-urlencoded            │
  │    Content-Length: 27         │
  │                               │
  │                          ┌────┴────┐
  │                          │ 路径检查  │
  │                          │ /submit  │
  │                          │ 或       │
  │                          │ /api/hello│
  │                          └────┬────┘
  │                               │
  │                    ┌──────────┴──────────┐
  │                    │                     │
  │                 允许/                 不允许/
  │                 继续                  返回 405
  │                    │                     │
  │              ┌─────┴─────┐             │
  │              │ 检查       │             │
  │              │ Content-   │             │
  │              │ Length     │             │
  │              │ ≤ 10MB    │             │
  │              └─────┬─────┘             │
  │                    │                   │
  │          ┌─────────┴─────────┐        │
  │          │                   │        │
  │       通过/               不通过/      │
  │       继续              返回 413       │
  │          │                   │        │
  │    ┌─────┴─────┐           │        │
  │    │ 解析       │           │        │
  │    │ POST 数据  │           │        │
  │    └─────┬─────┘           │        │
  │          │                 │        │
  │    ┌─────┴─────┐          │        │
  │    │ 解析成功?  │          │        │
  │    └─────┬─────┘          │        │
  │          │                │        │
  │     ┌────┴────┐          │        │
  │     │         │          │        │
  │   成功/     失败/         │        │
  │   返回      返回 400      │        │
  │   JSON      Bad Request   │        │
  │     │         │           │        │
  │     ▼         ▼           ▼        │
  │  ＜─── 200 OK ─────────────        │
  │  ＜─── 400 Bad Request ───────     │
  │  ＜─── 405 Method Not Allowed ─    │
  │  ＜─── 413 Payload Too Large ──    │
```

## 4. 技术选型理由

### 4.1 核心库选择

| 组件 | 选择 | 理由 |
|------|------|------|
| HTTP 服务器 | `http.server.HTTPServer` | 标准库，零依赖，足够满足需求 |
| 多线程 | `socketserver.ThreadingMixIn` | 标准库，与 HTTPServer 无缝集成 |
| 请求处理 | `http.server.BaseHTTPRequestHandler` | 标准库，提供请求解析、响应发送基础 |
| 参数解析 | `argparse` | 标准库，功能完善，支持短/长选项 |
| 测试框架 | `unittest` + `unittest.mock` | 标准库，无需额外安装，覆盖率工具支持好 |
| URL 解析 | `urllib.parse` | 标准库，用于解析查询参数和 POST 数据 |

### 4.2 技术选型理由

1. **纯标准库方案**：所有功能使用 Python 标准库实现，零外部依赖。用户无需 `pip install` 任何包即可运行。

2. **ThreadingHTTPServer vs asyncio**：
   - 选择 ThreadingHTTPServer 因为：实现简单直观，适合 I/O 密集型静态文件服务场景
   - 替代方案：`asyncio` + `aiohttp` — 更高效但需要外部依赖，增加复杂度

3. **BaseHTTPRequestHandler vs 框架**：
   - 选择 BaseHTTPRequestHandler 因为：完全控制响应生成，无框架抽象开销
   - 替代方案：Flask/FastAPI — 功能更丰富但需要外部依赖，违背"纯标准库"目标

4. **unittest vs pytest**：
   - 选择 unittest 因为：标准库内置，无需额外安装
   - 替代方案：pytest — 更简洁的语法，更好的 fixture 系统，但需额外安装

### 4.3 替代方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| **ThreadingHTTPServer（当前选择）** | 零依赖，简单，Python 3.7+ 内置 | 性能不如异步方案 | 学习项目、轻量服务 |
| asyncio + aiohttp | 高并发性能好 | 外部依赖，复杂度高 | 高并发生产环境 |
| Flask | 生态丰富，扩展多 | 外部依赖，启动慢 | Web 应用开发 |
| http.server + ForkingMixIn | 进程隔离好 | 资源消耗大 | CPU 密集型场景 |

## 5. 实现细节

### 5.1 文件结构

```
output/auto-ef51fd9b/
├── spec.md                    # 规格文档（已完成）
├── plan.md                    # 技术方案（本文档）
├── tasks.md                   # 任务清单（后续产出）
├── server.py                  # HTTP 服务器实现
├── test_server.py             # 测试用例
├── api_docs.md                # API 文档
├── implementation-report.md   # 实现报告
└── review.md                  # 审查报告
```

### 5.2 核心实现策略

#### 路径安全处理

```python
def is_safe_path(path: str) -> bool:
    """检查路径是否安全，防止路径遍历攻击。"""
    # 规范化路径，移除多余的斜杠和点
    normalized = posixpath.normpath(path)
    # 检查是否包含 '..'
    return '..' not in path.split('/')
```

注意：使用 `posixpath.normpath` 而不是 `os.path.normpath`，因为 URL 路径使用 `/` 分隔符，与操作系统无关。

#### POST 数据解析

```python
def parse_post_data(data: bytes, content_type: str) -> dict:
    """解析 POST 数据。
    
    支持:
    - application/x-www-form-urlencoded
    - multipart/form-data (基础支持)
    """
```

对于 `multipart/form-data`，使用 `cgi.FieldStorage`（Python 3.8+ 仍可用但已弃用）或手动解析 boundary。

**推荐方案**：对于 `application/x-www-form-urlencoded`，使用 `urllib.parse.parse_qs`。对于 `multipart/form-data`，使用 `cgi.FieldStorage` 的基础支持。

#### 自定义 404 页面

```python
def handle_404(self) -> None:
    """返回 404 页面。"""
    custom_404_path = os.path.join(self.doc_root, '404.html')
    if os.path.isfile(custom_404_path):
        self.serve_file(custom_404_path, status_code=404)
    else:
        self.send_error(404, "Not Found")
```

#### 目录列表

当请求路径为 `/` 且不存在 `index.html` 时，生成简单的 HTML 目录列表，包含目录中的文件和子目录链接。

#### 优雅关闭

```python
def signal_handler(sig, frame):
    """处理 SIGINT 信号，优雅关闭服务器。"""
    logger.info("Shutting down server...")
    server.shutdown()
    sys.exit(0)
```

### 5.3 日志格式

请求日志格式（类似 Apache Common Log Format）：
```
[INFO] 127.0.0.1 - - [10/Oct/2024 13:55:36] "GET /index.html HTTP/1.1" 200 1234
```

### 5.4 错误处理策略

1. **启动时错误**：在 `main()` 中捕获，打印到 stderr，`sys.exit(1)`
2. **请求时错误**：在 `do_GET()`/`do_POST()` 中用 try/except 包裹，返回对应状态码
3. **未预期异常**：`handle_error(500, ...)` 兜底

## 6. 任务分解与估算

### 6.1 任务清单

| # | 任务 | 描述 | 前置依赖 | 人天 |
|---|------|------|---------|------|
| 1 | 实现 MIME 类型映射 | `get_mime_type()` 函数 | 无 | 0.1 |
| 2 | 实现路径安全检查 | `is_safe_path()` 函数 | 无 | 0.1 |
| 3 | 实现 POST 数据解析 | `parse_post_data()` 函数 | 无 | 0.2 |
| 4 | 实现日志格式化 | `format_log_entry()` 函数 | 无 | 0.1 |
| 5 | 实现 CLI 参数解析 | `parse_args()` + 校验 | 无 | 0.2 |
| 6 | 实现 ThreadingHTTPServer | 多线程服务器类 | 无 | 0.1 |
| 7 | 实现 SimpleHTTPRequestHandler | 核心请求处理类 | 1,2,3,4 | 0.5 |
| 8 | 实现 do_GET() | GET 请求处理逻辑 | 7 | 0.3 |
| 9 | 实现 do_POST() | POST 请求处理逻辑 | 7 | 0.3 |
| 10 | 实现 main() 入口 | 组装各组件，启动服务器 | 5,6,8,9 | 0.2 |
| 11 | 编写测试用例 | 覆盖所有功能场景和边界条件 | 10 | 0.5 |
| 12 | 编写 API 文档 | 描述所有 API 接口 | 10 | 0.2 |
| 13 | 编写实现报告 | 实现总结 | 10 | 0.1 |
| **合计** | | | | **2.9 人天** |

### 6.2 关键路径

```
任务 1-5 (并行) → 任务 7 → 任务 8,9 (并行) → 任务 10 → 任务 11,12,13 (并行)
```

## 7. 风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| `cgi.FieldStorage` 在 Python 3.13+ 被移除 | POST multipart 解析失效 | 中 | 手动实现 multipart 解析，或使用 `email` 模块解析 |
| 高并发下线程数过多 | 资源耗尽 | 低 | 设置 `max_workers` 限制线程池大小 |
| 大文件读取导致内存溢出 | OOM | 低 | 使用分块读取/发送（`shutil.copyfileobj`） |
| 路径规范化与预期不符 | 安全漏洞 | 低 | 严格使用 `posixpath.normpath` 并双重检查 |

## 8. 安全考虑

1. **路径遍历防护**：双重检查 — 先检查 `..`，再规范化路径，确保最终路径在文档根目录下
2. **请求大小限制**：POST 请求体硬限制 10MB
3. **URI 长度限制**：2048 字符上限
4. **Content-Type 验证**：POST 仅接受 `application/x-www-form-urlencoded` 和 `multipart/form-data`
5. **路径前缀检查**：所有请求路径必须以 `/` 开头
