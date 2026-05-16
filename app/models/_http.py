"""HTTP客户端共享超时配置."""

import httpx

# 单次 LLM/Embedding API 调用通常在 2-30s 内完成，
# 30s 足够容纳正常慢响应；调用方如需更长，用 asyncio.wait_for / asyncio.timeout 在调用端施加。
READ_TIMEOUT_SECONDS = 30

CLIENT_TIMEOUT = httpx.Timeout(
    connect=10.0,  # 快速发现连接问题
    read=READ_TIMEOUT_SECONDS,
    write=60.0,  # 发送请求体通常很快
    pool=60.0,  # 从连接池获取连接的超时
)
