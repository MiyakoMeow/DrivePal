"""GraphQL 异常类."""

from graphql.error import GraphQLError


class InternalServerError(GraphQLError):
    """内部服务器错误."""

    def __init__(self) -> None:
        """初始化内部服务器错误."""
        super().__init__("Internal server error")


class GraphQLInvalidActionError(GraphQLError):
    """无效的操作类型."""

    def __init__(self, action: str) -> None:
        """初始化无效操作错误."""
        super().__init__(f"Invalid action: {action!r}")


class GraphQLEventNotFoundError(GraphQLError):
    """事件不存在."""

    def __init__(self, event_id: str) -> None:
        """初始化事件不存在错误."""
        super().__init__(f"Event not found: {event_id!r}")
