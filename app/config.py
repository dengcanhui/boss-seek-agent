from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用级运行配置。

    这里只保留真正会随部署环境变化的配置项；LLM 的超时、重试、思考模式等行为
    由代码内部维护默认值，避免把不常变化的实现细节暴露到 `.env`。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 应用基础配置。
    app_name: str = "boss-seek-agent"
    database_url: str = "sqlite:///./boss-seek-agent.db"

    # 大模型连接配置。兼容所有使用 OpenAI Chat Completions 协议的服务。
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "deepseek-flash"

    # 后台任务是否随应用启动自动运行。
    worker_autostart: bool = False

    # 浏览器运行时与登录缓存目录配置。
    browser_runtime_dir: str = "runtime/browsers"
    browser_profile_dir: str = "runtime/profile"
    browser_headless: bool = False


settings = Settings()
