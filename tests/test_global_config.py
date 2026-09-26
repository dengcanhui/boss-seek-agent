from app.domain.global_config import GlobalConfig, GlobalConfigUpdate


def test_global_config_cleans_and_deduplicates_blacklists():
    config = GlobalConfig(
        company_blacklist=[" 外包公司 ", "外包公司", "", "某科技"],
        job_blacklist=["销售", " 销售 "],
    )

    assert config.company_blacklist == ["外包公司", "某科技"]
    assert config.job_blacklist == ["销售"]


def test_global_config_update_preserves_explicit_empty_list():
    changes = GlobalConfigUpdate(company_blacklist=[])
    assert changes.company_blacklist == []


def test_global_config_has_per_task_job_limit():
    config = GlobalConfig()
    assert config.max_jobs_per_task == 100

    changes = GlobalConfigUpdate(max_jobs_per_task=50)
    assert changes.max_jobs_per_task == 50
