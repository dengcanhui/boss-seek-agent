from pathlib import Path

from app.main import app


def test_web_assets_exist_and_routes_are_mounted():
    web_dir = Path("app/web")
    assert (web_dir / "index.html").is_file()
    assert (web_dir / "static/styles.css").is_file()
    assert (web_dir / "static/app.js").is_file()
    assert (web_dir / "static/js/features/tasks.js").is_file()
    assert (web_dir / "static/js/features/job_records.js").is_file()

    route_paths = {route.path for route in app.routes if hasattr(route, "path")}
    api_paths = set(app.openapi()["paths"])
    assert "/" in route_paths
    assert "/static" in route_paths
    assert "/api/job-seek-tasks/options" in api_paths
    assert "/api/job-records" in api_paths
    assert "/api/job-records/{record_id}" in api_paths
    assert "/api/profile" not in api_paths
