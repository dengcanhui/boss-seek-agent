from collections.abc import Callable


def agent_tool(*, name: str | None = None, description: str | None = None):
    def decorator(func: Callable):
        setattr(func, "__agent_tool__", True)
        setattr(func, "__agent_tool_name__", name or func.__name__)
        setattr(func, "__agent_tool_description__", description or (func.__doc__ or "").strip())
        return func
    return decorator
