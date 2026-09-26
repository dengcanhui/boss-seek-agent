from pathlib import Path

from app.agent.memory.manager import MemoryManager
from app.agent.runtime import AgentRuntime
from app.agent.tools.registry import ToolRegistry
from app.application.candidate.candidate_profile_service import CandidateProfileService
from app.application.execution.job_seek_execution_service import JobSeekExecutionService
from app.application.global_config_service import GlobalConfigService
from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.boss_search_options import BossSearchOptionsService
from app.application.search.job_seek_task_service import JobSeekTaskService
from app.config import settings
from app.execution.boss.executor import BossJobExecutor
from app.execution.worker import JobSeekWorker
from app.infrastructure.browser.ruyipage import RuyiPageBrowser
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database.repositories.chat_repository import ChatRepository
from app.infrastructure.database.repositories.global_config_repository import GlobalConfigRepository
from app.infrastructure.database.repositories.job_record_repository import JobRecordRepository
from app.infrastructure.database.repositories.job_seek_task_repository import JobSeekTaskRepository
from app.infrastructure.database.repositories.profile_repository import CandidateProfileRepository
from app.infrastructure.llm import LLMClient


class Container:
    def __init__(self):
        self.job_seek_task_repository: JobSeekTaskRepository = JobSeekTaskRepository(SessionLocal)
        self.profile_repository: CandidateProfileRepository = CandidateProfileRepository(SessionLocal)
        self.chat_repository: ChatRepository = ChatRepository(SessionLocal)
        self.global_config_repository: GlobalConfigRepository = GlobalConfigRepository(SessionLocal)
        self.job_record_repository: JobRecordRepository = JobRecordRepository(SessionLocal)

        self.boss_search_options: BossSearchOptionsService = BossSearchOptionsService()
        self.search_config_compiler: BossSearchConfigCompiler = BossSearchConfigCompiler(
            self.boss_search_options.options
        )
        self.job_seek_tasks: JobSeekTaskService = JobSeekTaskService(
            self.job_seek_task_repository,
            self.search_config_compiler,
        )
        self.profile: CandidateProfileService = CandidateProfileService(self.profile_repository)
        self.global_config: GlobalConfigService = GlobalConfigService(self.global_config_repository)

        self.registry: ToolRegistry = ToolRegistry()
        self.registry.register_service(self.job_seek_tasks)
        self.registry.register_service(self.profile)
        self.registry.register_service(self.boss_search_options)

        self.memory: MemoryManager = MemoryManager(
            self.chat_repository,
            self.profile,
        )

        self._llm: LLMClient | None = None
        self._agent: AgentRuntime | None = None

        self.browser: RuyiPageBrowser = RuyiPageBrowser(
            Path(__file__).resolve().parent.parent,
            browsers_dir=settings.browser_runtime_dir,
            profile_dir=settings.browser_profile_dir,
            headless=settings.browser_headless,
        )
        self.job_executor: BossJobExecutor = BossJobExecutor(
            self.browser,
            self.global_config,
            self.job_record_repository,
        )
        self.job_seek_worker: JobSeekWorker = JobSeekWorker(
            self.job_seek_task_repository,
            self.job_executor,
        )
        self.job_seek_execution: JobSeekExecutionService = JobSeekExecutionService(
            self.job_seek_worker,
        )

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            if not settings.llm_api_key:
                raise RuntimeError("请配置 LLM_API_KEY")
            self._llm = LLMClient(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
            )
        return self._llm

    @property
    def agent(self) -> AgentRuntime:
        if self._agent is None:
            self._agent = AgentRuntime(
                self.llm,
                self.registry,
                self.memory,
                self.chat_repository,
                self.job_seek_tasks,
                self.boss_search_options,
            )
        return self._agent

    async def close_llm(self) -> None:
        if self._llm is None:
            return
        await self._llm.aclose()
        self._llm = None
        self._agent = None


container = Container()
