"""Standalone, isolated multi-project HTTP checks.

Run directly with the project's Python; deliberately excluded from unittest
discovery. Importing this module does not change environment or load the app.
All records, screenshots and project registrations live in a temporary home.
No browser windows, provider requests, or background workers are permitted.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from unittest.mock import AsyncMock, patch


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)

    with tempfile.TemporaryDirectory(prefix="geo-multi-project-") as folder:
        env = {
            "JUNHE_HOME": folder,
            "JUNHE_DISABLE_WORKER": "1",
            "PYTHON_DOTENV_DISABLED": "1",
        }
        with patch.dict(os.environ, env):
            # Imports must remain here: the real user's runtime is never opened.
            from fastapi.testclient import TestClient
            import app
            import engine
            import storage
            from config import HOME
            from projects import project_scope
            from browser_bridge import NeedsSetup

            check(Path(HOME).resolve() == Path(folder).resolve(), "The app must use only the temporary home")
            sends = AsyncMock(side_effect=AssertionError("Browser sending is forbidden in project checks"))
            api_sends = AsyncMock(side_effect=AssertionError("Provider calls are forbidden in project checks"))
            mutation_header = {"X-Workspace-Request": "junhe-local"}
            active = "default"

            def headers(project: str | None = None) -> dict[str, str]:
                return {**mutation_header, "X-Workspace-Project": project or active}

            def expect(response, status: int = 200):
                check(response.status_code == status,
                      f"{response.request.method} {response.request.url.path}: expected {status}, got {response.status_code}: {response.text[:300]}")
                return response

            def get(client, path: str, *, project: str | None = None, **kwargs):
                return client.get(path, headers=headers(project), **kwargs)

            def post(client, path: str, body: dict, *, project: str | None = None):
                return client.post(path, json=body, headers=headers(project))

            def put(client, path: str, body: dict, *, project: str | None = None):
                return client.put(path, json=body, headers=headers(project))

            def listed(client):
                result = expect(client.get("/api/projects")).json()
                check(isinstance(result.get("projects"), list), "Project management must return its project list")
                return result

            def activate(client, project_id: str):
                nonlocal active
                result = expect(post(client, f"/api/projects/{project_id}/activate", {})).json()
                active = project_id
                check(result.get("active_project_id") == project_id, "Activation response must name the selected project")
                check(listed(client)["active_project_id"] == project_id, "The project registry must reflect activation")

            def rows_by_id(rows):
                return sorted(rows, key=lambda item: item["id"])

            def fixture_task(profile: dict, suffix: str, screenshot: str = "") -> dict:
                stamp = storage.now()
                row = {
                    "id": storage.ident(), "batch_id": storage.ident(),
                    "platform": "doubao", "channel": "web", "mode": "visibility",
                    "keyword": f"隔离验收的行业合作品牌有哪些 {suffix}",
                    "prompt": f"仅用于隔离夹具的不可发送问题 {suffix}",
                    "status": "completed",
                    "answer": f"隔离夹具回答 {suffix}：{profile['brand_name']}，{profile['company_name']}。https://{profile['domain']}/",
                    "note": "Local synthetic fixture; never sent.", "screenshot": screenshot,
                    "metrics": json.dumps({"goal": "discovery", "brand_hint": False,
                                           "conversation_mode": "fresh", "context_contaminated": False,
                                           "source_directed": False, "fixture_only": True}, ensure_ascii=False),
                    "reviewed": 1, "sent_at": stamp, "created_at": stamp, "updated_at": stamp,
                }
                with project_scope(active), storage.db() as connection:
                    connection.execute("INSERT INTO batches(id,request_key,body_hash,created_at) VALUES(?,?,?,?)",
                                       (row["batch_id"], f"isolated-{suffix}-{storage.ident()}", "fixture-only", stamp))
                    connection.execute("INSERT INTO tasks(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", list(row.values()))
                return row

            def snapshot(client):
                boot = expect(get(client, "/api/bootstrap")).json()
                selected = {key: boot[key] for key in ("profile", "documents", "keywords", "schedules", "platform_schedules")}
                for key in ("documents", "keywords", "schedules", "platform_schedules"):
                    selected[key] = rows_by_id(selected[key])
                selected["tasks"] = expect(get(client, "/api/tasks?page_size=100")).json()
                selected["insights"] = expect(get(client, "/api/insights?scope=all")).json()["totals"]
                selected["keyword_plan"] = expect(get(client, "/api/keyword-candidates")).json()["settings"]
                return selected

            with patch.object(type(app.runner.browser), "send", sends), patch.object(engine, "api_send", api_sends):
                with TestClient(app.app, base_url="http://127.0.0.1:8020") as client:
                    registry = listed(client)
                    check(registry["active_project_id"] == "default", "A first migration must retain the original default project")
                    originals = [item for item in registry["projects"] if item["id"] == "default"]
                    check(len(originals) == 1 and originals[0]["is_default"], "The default project must be registered exactly once")
                    check(expect(client.get("/api/bootstrap")).headers.get("X-Workspace-Project") == "default",
                          "Headerless legacy reads must still target the original project while it is active")
                    original = expect(get(client, "/api/bootstrap")).json()
                    check(bool(original["documents"]) and bool(original["keywords"]), "Original seeded materials and questions must remain available")
                    profile = original["profile"]

                    document_id = expect(post(client, "/api/documents", {
                        "title": "原项目隔离夹具资料", "body": "只能出现在原项目的公开资料夹具。",
                        "source": "本地隔离测试", "approved": True,
                    })).json()["id"]
                    expect(post(client, "/api/keywords", {"text": "原项目专属隔离问题", "kind": "自定义"}))
                    original = expect(get(client, "/api/bootstrap")).json()
                    keyword_id = next(row["id"] for row in original["keywords"] if row["text"] == "原项目专属隔离问题")
                    expect(post(client, "/api/schedules", {"time": "23:59", "keyword_ids": [keyword_id], "platforms": ["doubao"], "mode": "visibility", "enabled": True}))
                    schedule_id = expect(post(client, "/api/platform-schedules", {
                        "time": "23:59", "items": [{"platform": "doubao", "text": "原项目的来源核验专属夹具", "goal": "source_audit"}],
                        "mode": "visibility", "conversation_mode": "fresh", "enabled": True,
                    })).json()["id"]
                    expect(put(client, "/api/keyword-plan", {"enabled": True, "time": "23:59", "count": 2, "goal": "discovery", "platforms": ["doubao"]}))
                    image_name = storage.ident() + ".png"
                    screenshot_folder = Path(folder) / "screenshots"
                    screenshot_folder.mkdir(parents=True, exist_ok=True)
                    pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
                    (screenshot_folder / image_name).write_bytes(pixel)
                    original_task = fixture_task(profile, "original", image_name)
                    original_image = expect(get(client, f"/api/screenshots/{image_name}?project=default"))
                    check(original_image.content == pixel, "Original screenshot bytes must be readable before switching")
                    before = snapshot(client)
                    check(before["insights"]["samples"] == 1 and before["insights"]["brand_mentions"] == 1,
                          "The original completed fixture must contribute only to its own statistics")

                    created = expect(post(client, "/api/projects", {
                        "name": "南风品牌观察", "company_name": "南风实验室有限公司",
                        "brand_name": "南风日常", "domain": "nanfeng.example",
                    }), 201).json()
                    project_id = created["project"]["id"]
                    check(project_id != "default", "A new project must have a separate stable identifier")
                    check(created["active_project_id"] == "default" and listed(client)["active_project_id"] == "default",
                          "Creating a project must register it without activating it")
                    check(snapshot(client) == before, "Registration must not alter original records or enabled plans")

                    for attribute, value in (("_legacy_current", "fixture-current"), ("active", {"fixture-current": "doubao"})):
                        with patch.object(app.runner, attribute, value):
                            expect(post(client, f"/api/projects/{project_id}/activate", {}), 409)
                        check(listed(client)["active_project_id"] == "default", "Busy activation must leave the active project unchanged")

                    previous_runner = app.runner
                    with patch.object(previous_runner.browser, "check_project_switch",
                                      new=AsyncMock(side_effect=NeedsSetup("平台输入框有未发送草稿，请先处理草稿"))):
                        expect(post(client, f"/api/projects/{project_id}/activate", {}), 409)
                    check(app.runner is previous_runner and not previous_runner.suspended,
                          "A rejected draft check must restore the existing runner")
                    check(listed(client)["active_project_id"] == "default", "A browser draft must prevent switching")

                    # Hold a real scoped HTTP read in flight. The management
                    # endpoint must refuse a switch until that request completes.
                    entered, release = Event(), Event()
                    real_platform_view = app.platform_view

                    def held_platform_view(pid):
                        if pid == "doubao":
                            entered.set()
                            if not release.wait(10):
                                raise AssertionError("Scoped HTTP fixture was not released")
                        return real_platform_view(pid)

                    with patch.object(app, "platform_view", held_platform_view), ThreadPoolExecutor(max_workers=1) as pool:
                        pending = pool.submit(get, client, "/api/bootstrap")
                        try:
                            check(entered.wait(5), "The scoped HTTP read must enter before attempting activation")
                            expect(post(client, f"/api/projects/{project_id}/activate", {}), 409)
                            check(listed(client)["active_project_id"] == "default", "An in-flight request must prevent switching")
                        finally:
                            release.set()
                        expect(pending.result(timeout=15))

                    activate(client, project_id)
                    fresh = expect(get(client, "/api/bootstrap")).json()
                    check(fresh["profile"]["company_name"] == "南风实验室有限公司" and fresh["profile"]["brand_name"] == "南风日常",
                          "A new project's configured company and brand must replace default seed names")
                    check(fresh["profile"].get("domain") == "nanfeng.example", "New project domain must be kept")
                    for key in ("documents", "keywords", "tasks", "schedules", "platform_schedules", "platform_keywords"):
                        check(fresh[key] == [], f"The new project must begin with an empty {key} collection")
                    check(expect(get(client, "/api/tasks")).json()["total"] == 0, "Task search must not leak original records")
                    check(expect(get(client, "/api/insights?scope=all")).json()["totals"]["samples"] == 0, "Statistics must start empty in a new project")
                    new_csv = expect(get(client, "/api/export/tasks.csv")).text
                    check(original_task["keyword"] not in new_csv and original_task["answer"] not in new_csv,
                          "Exports must not include the original project's records")
                    expect(get(client, "/api/tasks/" + original_task["id"]), 404)
                    check(expect(get(client, "/api/tasks", params={"q": original_task["keyword"]})).json()["total"] == 0,
                          "Filtered task searches must not find the other project's records")
                    expect(put(client, "/api/documents/" + document_id, {
                        "title": "不应覆盖原项目", "body": "跨项目的资料编号不得覆盖原资料。", "source": "测试", "approved": True,
                    }), 404)
                    expect(get(client, f"/api/screenshots/{image_name}?project={project_id}"), 404)

                    # Old tabs, absent headers, unknown IDs, and explicit URL/header
                    # disagreement must be rejected before any current-project data is read.
                    for path in ("/api/bootstrap", "/api/tasks", "/api/insights?scope=all", "/api/export/tasks.csv"):
                        expect(client.get(path), 409)
                        expect(get(client, path, project="default"), 409)
                    expect(client.get(f"/api/screenshots/{image_name}?project=default"), 409)
                    expect(client.get("/api/export/tasks.csv?project=default"), 409)
                    check(expect(client.get(f"/api/export/tasks.csv?project={project_id}")).text == new_csv,
                          "A matching project-tagged download must remain usable without custom headers")
                    expect(post(client, "/api/keywords", {"text": "旧标签页不应写入", "kind": "自定义"}, project="default"), 409)
                    expect(client.post("/api/keywords", json={"text": "缺少项目头不应写入"}, headers=mutation_header), 409)
                    for url_project, header_project in (("default", project_id), (project_id, "default")):
                        expect(get(client, f"/api/screenshots/{image_name}?project={url_project}", project=header_project), 400)
                        expect(get(client, f"/api/export/tasks.csv?project={url_project}", project=header_project), 400)
                    expect(client.get("/api/bootstrap", headers=[("X-Workspace-Project", project_id), ("X-Workspace-Project", "default")]), 400)
                    expect(client.get(f"/api/export/tasks.csv?project={project_id}&project=default"), 400)
                    unknown = "f" * 32
                    unknown_read = get(client, "/api/bootstrap", project=unknown)
                    check(unknown_read.status_code in (404, 409, 422), "An unknown project header must not return current project data")
                    expect(get(client, "/api/bootstrap", project="invalid-project-id"), 400)
                    expect(get(client, f"/api/screenshots/{image_name}?project=invalid-project-id"), 400)
                    unknown_activation = post(client, f"/api/projects/{unknown}/activate", {})
                    check(unknown_activation.status_code in (404, 422), "An unknown project must not be activated")
                    check(not (Path(folder) / "projects" / unknown).exists(), "Unknown project requests must not initialize storage")
                    check(listed(client)["active_project_id"] == project_id, "Rejected requests must not change the active project")

                    new_document = expect(post(client, "/api/documents", {
                        "title": "南风项目专属资料", "body": "此资料仅属于南风隔离项目。", "source": "本地夹具", "approved": True,
                    })).json()["id"]
                    expect(post(client, "/api/keywords", {"text": "南风项目独立测试问题", "kind": "自定义"}))
                    new_task = fixture_task(fresh["profile"], "new-project")
                    after_new = snapshot(client)
                    check([row["id"] for row in after_new["documents"]] == [new_document], "New documents must remain scoped to the new project")
                    check(after_new["tasks"]["total"] == 1 and after_new["tasks"]["items"][0]["id"] == new_task["id"], "New fixture tasks must be isolated")
                    check(after_new["insights"]["samples"] == 1 and after_new["insights"]["brand_mentions"] == 1,
                          "The new brand must be analyzed against its own profile")
                    new_csv = expect(get(client, "/api/export/tasks.csv")).text
                    check(new_task["answer"] in new_csv and original_task["answer"] not in new_csv,
                          "Exports must use the active brand and records only")
                    filtered_csv = expect(get(client, "/api/export/tasks.csv", params={"q": original_task["keyword"]})).text
                    check(original_task["answer"] not in filtered_csv and new_task["answer"] not in filtered_csv,
                          "Filtered exports must remain confined to the current project")
                    filtered_csv = expect(get(client, "/api/export/tasks.csv", params={"q": new_task["keyword"]})).text
                    check(new_task["answer"] in filtered_csv and original_task["answer"] not in filtered_csv,
                          "Matching exports must include only the current project's selected answer")

                # A new Python process proves active selection is persisted on
                # disk, rather than retained only in this TestClient's globals.
                probe = """
import json
from fastapi.testclient import TestClient
import app
with TestClient(app.app,base_url='http://127.0.0.1:8020') as client:
    response=client.get('/api/projects')
    assert response.status_code==200, response.text
    assert app.runner.jobs==[]
    print(json.dumps({'active_project_id':response.json()['active_project_id']}))
"""
                result = subprocess.run([sys.executable, "-c", probe], cwd=root, env=dict(os.environ),
                                        check=True, capture_output=True, text=True, encoding="utf-8", timeout=45)
                persisted = json.loads(result.stdout.strip().splitlines()[-1])
                check(persisted["active_project_id"] == project_id, "The active project must survive a fresh process")

                with TestClient(app.app, base_url="http://127.0.0.1:8020") as client:
                    check(listed(client)["active_project_id"] == project_id, "Service re-entry must retain the active project")
                    check(snapshot(client) == after_new, "New project data must survive service re-entry")
                    activate(client, "default")
                    restored = snapshot(client)
                    check(restored == before, "Returning to the original project must preserve every stored fixture and enabled plan")
                    check(any(row["id"] == document_id for row in restored["documents"]), "Original approved materials must remain intact")
                    check(any(row["id"] == schedule_id and row["enabled"] for row in restored["platform_schedules"]), "Original enabled platform schedules must remain enabled")
                    check(any(row["enabled"] for row in restored["schedules"]), "Original enabled legacy schedules must remain enabled")
                    expect(get(client, "/api/tasks/" + new_task["id"]), 404)
                    check(expect(get(client, f"/api/screenshots/{image_name}?project=default")).content == pixel,
                          "Original screenshot bytes must remain intact after multiple switches")
                    expect(get(client, f"/api/screenshots/{image_name}?project={project_id}"), 400)
                    activate(client, project_id)
                    check(snapshot(client) == after_new, "Switching a second time must not reseed or erase the new project")
                    check(app.runner.jobs == [], "Workers must remain disabled throughout HTTP checks")

                check(sends.await_count == 0 and api_sends.await_count == 0, "No provider sends may occur")
                print(json.dumps({"checks": checks, "result": "passed", "projects": 2,
                                  "external_sends": 0, "temporary_home_only": True,
                                  "fresh_process_persistence": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
