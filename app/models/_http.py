"""HTTP客户端共享配置."""

import httpx

READ_TIMEOUT_SECONDS = 12 * 3600

CLIENT_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=READ_TIMEOUT_SECONDS,
    write=60.0,
    pool=60.0,
)
