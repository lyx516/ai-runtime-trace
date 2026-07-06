
## 文件操作示例
- 读取文件前，先使用 `os.path.exists()` 或类似方法检查文件是否存在，若不存在则使用默认内容替代。
- 写入文件时，确保目录存在（如使用 `os.makedirs(os.path.dirname(path), exist_ok=True)`），并使用完整路径避免歧义。
- 示例代码：
```python
import os

def safe_read(path, default=""):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return default

def safe_write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
```
## 文件操作注意事项
- 使用 `file_read` 前，务必先检查文件是否存在；若不存在，则使用默认内容或创建文件。
- 使用 `file_write` 时，确保目标目录存在，并始终使用完整绝对路径。
- 示例：
  ```python
  import os
  # 读文件：若不存在则使用默认内容
  if os.path.exists('path/to/file'):
      content = file_read('path/to/file')
  else:
      content = '默认内容'
  # 写文件：确保目录存在
  os.makedirs(os.path.dirname('path/to/output'), exist_ok=True)
  file_write('path/to/output', content)
  ```

