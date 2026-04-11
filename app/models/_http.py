"""HTTP客户端共享超时配置."""

import httpx

# LLM 流式响应可能持续数小时（如长文档生成），设为 12 小时避免中途断开
READ_TIMEOUT_SECONDS = 12 * 3600

CLIENT_TIMEOUT = httpx.Timeout(
    connect=10.0,  # 快速发现连接问题
    read=READ_TIMEOUT_SECONDS,
    write=60.0,  # 发送请求体通常很快
    pool=60.0,  # 从连接池获取连接的超时
)
