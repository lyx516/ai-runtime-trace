# Simple HTTP Server — 任务清单 (Tasks)

## 任务总览

| 阶段 | 任务数 | 并行度 | 预估总工时 |
|------|--------|--------|-----------|
| 基础函数层 | 5 个并行任务 | 5 路并行 | 0.7 人天 |
| 核心类实现 | 1 个任务 | 串行 | 0.5 人天 |
| 请求处理层 | 2 个并行任务 | 2 路并行 | 0.6 人天 |
| 入口组装层 | 1 个任务 | 串行 | 0.2 人天 |
| 测试与文档 | 3 个并行任务 | 3 路并行 | 0.8 人天 |
| **合计** | **12 个任务** | — | **2.8 人天** |

---

## 关键路径图

```
T001 ─┐                    ┌─ T008
T002 ─┤                    │         ┌─ T011
T003 ─┼──→ T006 ─→ T007 ──┼──→ T010 ─┼─ T012
T004 ─┤         [核心类]   │         └─ T013
T005 ─┘                    └─ T009
[并行 5路]                 [并行 2路]  [并行 3路]

关键路径（最长路径）: T001/T002/T003/T004/T005 → T006 → T007 → T008 → T010 → T011
预估关键路径工时: 0.2 + 0.5 + 0.3 + 0.2 + 0.4 = 1.6 人天
```

---

## 任务详情

### T001 — 实现 MIME 类型映射函数

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | 无 |
| **产出** | `get_mime_type(path: str) -> str` 函数 |
| **验收标准** | |
| | 1. `.html` / `.htm` → `text/html` |
| | 2. `.css` → `text/css` |
| | 3. `.js` → `application/javascript` |
| | 4. `.json` → `application/json` |
| | 5. `.png` → `image/png` |
| | 6. `.jpg` / `.jpeg` → `image/jpeg` |
| | 7. `.gif` → `image/gif` |
| | 8. `.svg` → `image/svg+xml` |
| | 9. `.txt` → `text/plain` |
| | 10. `.pdf` → `application/pdf` |
| | 11. 无扩展名/未知扩展名 → `application/octet-stream` |
| | 12. 函数有完整类型注解和 docstring |
| | 13. ✅ 可独立测试 |
| **预估工时** | 0.1 人天 |
| **[P]** 并行 | ✅ 是（与 T002-T005 并行） |

---

### T002 — 实现路径安全检查函数

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | 无 |
| **产出** | `is_safe_path(path: str) -> bool` 函数 |
| **验收标准** | |
| | 1. 路径包含 `..` → 返回 `False` |
| | 2. 路径包含 `../` → 返回 `False` |
| | 3. 路径包含 `..\\` → 返回 `False` |
| | 4. 路径包含 `/../` → 返回 `False` |
| | 5. 路径以 `..` 开头 → 返回 `False` |
| | 6. 路径以 `..` 结尾 → 返回 `False` |
| | 7. 正常路径 `/index.html` → 返回 `True` |
| | 8. 正常路径 `/subdir/file.txt` → 返回 `True` |
| | 9. 根路径 `/` → 返回 `True` |
| | 10. 使用 `posixpath.normpath` 进行路径规范化 |
| | 11. 函数有完整类型注解和 docstring |
| | 12. ✅ 可独立测试 |
| **预估工时** | 0.1 人天 |
| **[P]** 并行 | ✅ 是（与 T001, T003-T005 并行） |

---

### T003 — 实现 POST 数据解析函数

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | 无 |
| **产出** | `parse_post_data(data: bytes, content_type: str) -> dict` 函数 |
| **验收标准** | |
| | 1. 支持 `application/x-www-form-urlencoded` 格式解析 |
| | 2. 支持 `multipart/form-data` 格式解析（基础支持） |
| | 3. URL 编码的键值对正确解码（如 `name=John&message=Hello%20World` → `{"name": "John", "message": "Hello World"}`） |
| | 4. 空数据 → 返回空字典 `{}` |
| | 5. 无效的 Content-Type → 返回空字典或抛出可捕获异常 |
| | 6. 使用 `urllib.parse.parse_qs` 处理 form-urlencoded |
| | 7. 函数有完整类型注解和 docstring |
| | 8. ✅ 可独立测试 |
| **预估工时** | 0.2 人天 |
| **[P]** 并行 | ✅ 是（与 T001, T002, T004-T005 并行） |

---

### T004 — 实现日志格式化函数

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | 无 |
| **产出** | `format_log_entry(client_ip: str, method: str, path: str, status_code: int, size: int) -> str` 函数 |
| **验收标准** | |
| | 1. 输出格式符合 Apache Common Log Format 风格：`[INFO] {client_ip} - - [{timestamp}] "{method} {path} HTTP/1.1" {status_code} {size}` |
| | 2. 时间戳格式为 `[DD/Mon/YYYY HH:MM:SS]` |
| | 3. 函数有完整类型注解和 docstring |
| | 4. ✅ 可独立测试 |
| **预估工时** | 0.1 人天 |
| **[P]** 并行 | ✅ 是（与 T001-T003, T005 并行） |

---

### T005 — 实现 CLI 参数解析函数

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | 无 |
| **产出** | `parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace` 函数 + 参数校验逻辑 |
| **验收标准** | |
| | 1. `--port` / `-p`：默认 8080，类型 int |
| | 2. `--host` / `-H`：默认 `"0.0.0.0"`，类型 str |
| | 3. `--root` / `-r`：默认 `"."`，类型 str |
| | 4. 端口号校验：< 1024 或 > 65535 → 打印错误并 `sys.exit(1)` |
| | 5. 文档根目录不存在 → 打印错误并 `sys.exit(1)` |
| | 6. 文档根路径不是目录 → 打印错误并 `sys.exit(1)` |
| | 7. 端口被占用 → 在 `main()` 中捕获并处理 |
| | 8. 函数有完整类型注解和 docstring |
| | 9. ✅ 可独立测试（通过传入 argv 列表模拟） |
| **预估工时** | 0.2 人天 |
| **[P]** 并行 | ✅ 是（与 T001-T004 并行） |

---

### T006 — 实现 ThreadingHTTPServer 类

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | 无 |
| **产出** | `ThreadingHTTPServer` 类 |
| **验收标准** | |
| | 1. 继承 `socketserver.ThreadingMixIn` 和 `http.server.HTTPServer` |
| | 2. `allow_reuse_address = True` |
| | 3. `daemon_threads = True` |
| | 4. 每个请求在独立线程中处理 |
| | 5. 支持 `serve_forever()` 和 `shutdown()` |
| | 6. 类有完整 docstring |
| **预估工时** | 0.1 人天 |
| **[P]** 并行 | ❌ 否（串行，但前置依赖无，可与 T001-T005 并行） |

> **注意**：T006 无前置依赖，可与 T001-T005 并行执行。但通常建议在基础函数完成后实现核心类，因此放在 T001-T005 之后。

---

### T007 — 实现 SimpleHTTPRequestHandler 核心类

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | T001（get_mime_type）, T002（is_safe_path）, T003（parse_post_data）, T004（format_log_entry） |
| **产出** | `SimpleHTTPRequestHandler` 类（含辅助方法，不含 do_GET/do_POST 主逻辑） |
| **验收标准** | |
| | 1. 继承 `http.server.BaseHTTPRequestHandler` |
| | 2. 类属性：`server_version = "SimpleHTTPServer/1.0"`、`doc_root`、`max_post_size = 10 * 1024 * 1024` |
| | 3. 实现 `serve_file(filepath: str, status_code: int = 200) -> None` — 读取文件并发送响应 |
| | 4. 实现 `handle_404() -> None` — 查找 `404.html` 或返回默认消息 |
| | 5. 实现 `handle_403() -> None` — 返回 403 响应 |
| | 6. 实现 `handle_error(status_code: int, message: str, content_type: str = "text/plain") -> None` — 通用错误响应 |
| | 7. 实现 `list_directory(dir_path: str) -> None` — 生成目录列表 HTML |
| | 8. `send_head()` 方法处理路径安全检查 |
| | 9. 所有方法有完整类型注解和 docstring |
| | 10. 使用 `shutil.copyfileobj` 进行大文件分块发送 |
| **预估工时** | 0.5 人天 |
| **[P]** 并行 | ❌ 否（关键路径上的串行任务） |

---

### T008 — 实现 do_GET() 方法

| 属性 | 内容 |
|------|------|
| **文件** | `server.py`（`SimpleHTTPRequestHandler` 类内） |
| **前置依赖** | T007（SimpleHTTPRequestHandler 类） |
| **产出** | `do_GET()` 方法完整实现 |
| **验收标准** | |
| | 1. 路径必须以 `/` 开头，否则返回 **400 Bad Request** |
| | 2. 路径长度超过 2048 字符 → 返回 **414 URI Too Long** |
| | 3. 路径包含 `..` → 返回 **403 Forbidden**（调用 `handle_403`） |
| | 4. 路径 `/api/hello` → 返回 **200 OK** + JSON `{"message": "Hello, World!"}` |
| | 5. 路径 `/` 或 `/index.html` → 查找 `index.html` |
| | 6. 路径指向目录 → 查找该目录下的 `index.html`，不存在则生成目录列表 |
| | 7. 路径指向文件 → 调用 `serve_file()` 返回文件内容 |
| | 8. 文件不存在 → 调用 `handle_404()` |
| | 9. 文件读取 IO 错误 → 返回 **500 Internal Server Error** |
| | 10. 所有响应包含正确的 Content-Type 和 Content-Length |
| | 11. 记录请求日志到 stderr |
| | 12. 方法有完整类型注解和 docstring |
| **预估工时** | 0.3 人天 |
| **[P]** 并行 | ✅ 是（与 T009 并行） |

---

### T009 — 实现 do_POST() 方法

| 属性 | 内容 |
|------|------|
| **文件** | `server.py`（`SimpleHTTPRequestHandler` 类内） |
| **前置依赖** | T007（SimpleHTTPRequestHandler 类） |
| **产出** | `do_POST()` 方法完整实现 |
| **验收标准** | |
| | 1. 仅允许路径 `/submit` 和 `/api/hello`，其他路径 → **405 Method Not Allowed** |
| | 2. 检查 Content-Length > 10MB → **413 Payload Too Large** |
| | 3. 路径 `/submit`：解析 POST 数据，返回 **200 OK** + JSON `{"status": "ok", "received": {...}}` |
| | 4. 路径 `/api/hello`：返回 **200 OK** + JSON `{"message": "Hello, World!"}` |
| | 5. 不支持的 Content-Type → **400 Bad Request** + `"400 Bad Request - Unsupported Content-Type"` |
| | 6. POST 数据解析失败 → **400 Bad Request** + `"400 Bad Request - Invalid form data"` |
| | 7. 记录请求日志到 stderr |
| | 8. 方法有完整类型注解和 docstring |
| **预估工时** | 0.3 人天 |
| **[P]** 并行 | ✅ 是（与 T008 并行） |

---

### T010 — 实现 main() 入口函数

| 属性 | 内容 |
|------|------|
| **文件** | `server.py` |
| **前置依赖** | T005（parse_args）, T006（ThreadingHTTPServer）, T008（do_GET）, T009（do_POST） |
| **产出** | `main()` 函数 + `if __name__ == "__main__"` 入口 |
| **验收标准** | |
| | 1. 调用 `parse_args()` 获取配置 |
| | 2. 创建 `ThreadingHTTPServer` 实例，传入 `(host, port)` 和 `SimpleHTTPRequestHandler` |
| | 3. 设置 `SimpleHTTPRequestHandler.doc_root` |
| | 4. 打印启动日志 `[INFO] Starting HTTP server on {host}:{port}` |
| | 5. 调用 `server.serve_forever()` |
| | 6. 注册 SIGINT 信号处理器，实现优雅关闭（打印 `[INFO] Shutting down server...`） |
| | 7. 端口被占用时捕获异常，打印 `[ERROR] Error: Port {port} is already in use`，`sys.exit(1)` |
| | 8. 函数有完整类型注解和 docstring |
| **预估工时** | 0.2 人天 |
| **[P]** 并行 | ❌ 否（关键路径上的串行任务，所有前置必须完成） |

---

### T011 — 编写测试用例

| 属性 | 内容 |
|------|------|
| **文件** | `test_server.py` |
| **前置依赖** | T010（main 入口，表示所有代码已完成） |
| **产出** | 完整的测试套件 |
| **验收标准** | |
| | 1. 使用 `unittest` 框架 |
| | 2. 覆盖所有 16 个验收测试场景（spec 6.1 节） |
| | 3. 使用 `unittest.mock` 模拟文件系统和网络请求 |
| | 4. 测试 MIME 类型映射（T001 的函数） |
| | 5. 测试路径安全检查（T002 的函数） |
| | 6. 测试 POST 数据解析（T003 的函数） |
| | 7. 测试日志格式化（T004 的函数） |
| | 8. 测试 CLI 参数解析（T005 的函数） |
| | 9. 测试 do_GET 的各种场景（200、404、403、414、500） |
| | 10. 测试 do_POST 的各种场景（200、405、413、400） |
| | 11. 测试并发请求处理 |
| | 12. 测试服务器启动错误场景 |
| | 13. 测试覆盖率 ≥ 80% |
| | 14. 测试代码符合 PEP 8 |
| | 15. 所有测试函数有 docstring |
| **预估工时** | 0.4 人天 |
| **[P]** 并行 | ✅ 是（与 T012, T013 并行） |

---

### T012 — 编写 API 文档

| 属性 | 内容 |
|------|------|
| **文件** | `api_docs.md` |
| **前置依赖** | T010（main 入口，表示所有代码已完成） |
| **产出** | 完整的 API 文档 |
| **验收标准** | |
| | 1. 包含服务器概述和启动方式 |
| | 2. 列出所有 CLI 启动参数（--port, --host, --root） |
| | 3. 描述 GET 接口：`GET /`、`GET /index.html`、`GET /path/to/file`、`GET /api/hello` |
| | 4. 描述 POST 接口：`POST /submit`、`POST /api/hello` |
| | 5. 每个接口包含：请求格式、成功响应示例、错误响应示例 |
| | 6. 列出所有 HTTP 状态码及含义（200, 400, 403, 404, 405, 413, 414, 500） |
| | 7. 列出 MIME 类型映射表 |
| | 8. 包含使用示例（curl 命令） |
| | 9. 文档格式清晰，使用 Markdown |
| **预估工时** | 0.2 人天 |
| **[P]** 并行 | ✅ 是（与 T011, T013 并行） |

---

### T013 — 编写实现报告

| 属性 | 内容 |
|------|------|
| **文件** | `implementation-report.md` |
| **前置依赖** | T010（main 入口，表示所有代码已完成） |
| **产出** | 实现报告 |
| **验收标准** | |
| | 1. 概述实现的功能范围 |
| | 2. 描述架构设计和组件划分 |
| | 3. 列出文件结构和每个文件的功能 |
| | 4. 说明技术选型理由 |
| | 5. 记录实现过程中遇到的问题和解决方案 |
| | 6. 说明测试覆盖情况 |
| | 7. 列出已知限制和后续改进方向 |
| | 8. 文档格式清晰，使用 Markdown |
| **预估工时** | 0.1 人天 |
| **[P]** 并行 | ✅ 是（与 T011, T012 并行） |

---

## 依赖关系矩阵

| 任务 | T001 | T002 | T003 | T004 | T005 | T006 | T007 | T008 | T009 | T010 | T011 | T012 | T013 |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| T001 | — | | | | | | **→** | | | | | | |
| T002 | | — | | | | | **→** | | | | | | |
| T003 | | | — | | | | **→** | | | | | | |
| T004 | | | | — | | | **→** | | | | | | |
| T005 | | | | | — | | | | | **→** | | | |
| T006 | | | | | | — | | | | **→** | | | |
| T007 | ← | ← | ← | ← | | | — | **→** | **→** | | | | |
| T008 | | | | | | | ← | — | | **→** | | | |
| T009 | | | | | | | ← | | — | **→** | | | |
| T010 | | | | | ← | ← | | ← | ← | — | **→** | **→** | **→** |
| T011 | | | | | | | | | | ← | — | | |
| T012 | | | | | | | | | | ← | | — | |
| T013 | | | | | | | | | | ← | | | — |

**图例**：`→` 表示该任务被依赖，`←` 表示该任务依赖其他任务

---

## 执行顺序建议

### 第 1 轮（并行执行）
```
T001 ─── get_mime_type()
T002 ─── is_safe_path()
T003 ─── parse_post_data()
T004 ─── format_log_entry()
T005 ─── parse_args()
T006 ─── ThreadingHTTPServer 类
```
**6 个任务并行**，无相互依赖。

### 第 2 轮（串行，等待第 1 轮完成）
```
T007 ─── SimpleHTTPRequestHandler 类（依赖 T001-T004）
```

### 第 3 轮（并行执行）
```
T008 ─── do_GET()（依赖 T007）
T009 ─── do_POST()（依赖 T007）
```
**2 个任务并行**。

### 第 4 轮（串行，等待第 3 轮完成）
```
T010 ─── main() 入口（依赖 T005, T006, T008, T009）
```

### 第 5 轮（并行执行）
```
T011 ─── 测试用例（依赖 T010）
T012 ─── API 文档（依赖 T010）
T013 ─── 实现报告（依赖 T010）
```
**3 个任务并行**。

---

## 风险标注

| 风险 | 涉及任务 | 说明 |
|------|---------|------|
| ⚠️ 高 | T003 | `cgi.FieldStorage` 在 Python 3.13+ 被移除，需手动实现 multipart 解析 |
| ⚠️ 中 | T007 | 文件读取大文件时需使用 `shutil.copyfileobj` 避免 OOM |
| ⚠️ 中 | T008 | 路径规范化逻辑需谨慎，防止安全漏洞 |
| ⚠️ 低 | T011 | 测试需 mock 文件系统和网络请求，确保测试独立性 |
