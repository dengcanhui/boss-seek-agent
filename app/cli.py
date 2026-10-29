from __future__ import annotations

import uvicorn
from copy import deepcopy


def main() -> None:
    """启动 boss-seek-agent Web 服务。"""
    log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    for formatter in log_config["formatters"].values():
        formatter["fmt"] = "%(asctime)s " + formatter["fmt"]
        formatter["datefmt"] = "%Y-%m-%d %H:%M:%S"
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_config=log_config)


if __name__ == "__main__":
    main()
