"""HTTP客户端共享超时配置."""

import httpx

# 覆盖长摘要 + 低 token/s 场景，消融实验由 asyncio.wait_for 单独管控
READ_TIMEOUT_SECONDS = 600

CLIENT_TIMEOUT = httpx.Timeout(
    connect=10.0,  # 快速发现连接问题
    read=READ_TIMEOUT_SECONDS,
    write=60.0,  # 发送请求体通常很快
    pool=60.0,  # 从连接池获取连接的超时
)
