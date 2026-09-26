from __future__ import annotations

import uvicorn


def main() -> None:
    """启动 boss-seek-agent Web 服务。"""
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
