from collections import Counter
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import CheckBatch, CheckRun, CheckViolation, Paper
from app.services import check_service, paper_service
from tests.fixtures_generator import DOCX_RULE_FAILURES, make_damaged, make_fjnu_docx, make_fjnu_pdf

API = "/api/v1"


def _json(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def master(client):
    templates = _json(client.get(f"{API}/rule-sets"))
    assert {item["code"] for item in templates} == {
        "fjnu_master_2019", "fjnu_doctor_2019", "general_academic_v1",
    }
    assert templates[0]["is_default"]
    assert templates[0]["rule_count"] == 21
    return _json(client.get(f"{API}/rule-sets/{templates[0]['id']}"))


def _upload(client, template_id, *paths, batch_name=None):
    data = {"rule_set_id": template_id}
    if batch_name is not None:
        data["batch_name"] = batch_name
    files = [("files", (path.name, path.read_bytes())) for path in paths]
    return client.post(f"{API}/batches/check", data=data, files=files)


def test_health(client):
    assert _json(client.get(f"{API}/health")) == {"status": "ok", "database": "connected"}


def test_list_clone_and_import_templates(client, master):
    assert len(master["rule_items"]) == master["rule_count"] == 21
    assert len(master["manual_checklist"]) == 5

    payload = {"code": "custom_master", "name": "硕士自定义", "source_rule_set_id": master["id"]}
    clone = _json(client.post(f"{API}/rule-sets", json=payload), 201)
    assert clone["id"] != master["id"]
    assert not clone["is_default"]
    assert clone["degree_level"] == master["degree_level"]
    assert clone["manual_checklist"] == master["manual_checklist"]
    assert clone["rule_count"] == master["rule_count"]
    for original, copied in zip(master["rule_items"], clone["rule_items"], strict=True):
        assert copied["id"] != original["id"]
        assert copied["rule_set_id"] == clone["id"]
        fields = set(original) - {"id", "rule_set_id"}
        assert {key: copied[key] for key in fields} == {key: original[key] for key in fields}
    _json(client.post(f"{API}/rule-sets", json=payload), 409)

    rule = next(item for item in master["rule_items"] if item["rule_code"] == "FILE_NAME_PATTERN")
    imported = _json(client.post(f"{API}/rule-sets", json={
        "code": "json_import", "name": "导入模板", "degree_level": "general",
        "manual_checklist": ["人工确认封面"],
        "rule_items": [{key: value for key, value in rule.items() if key not in {"id", "rule_set_id"}}],
    }), 201)
    assert imported["rule_count"] == 1
    assert imported["rule_items"][0]["params"] == rule["params"]
    assert imported["manual_checklist"] == ["人工确认封面"]
    listed = {item["id"]: item["rule_count"] for item in _json(client.get(f"{API}/rule-sets"))}
    assert listed[clone["id"]] == 21
    assert listed[imported["id"]] == 1


def test_mixed_batch_filters_and_details(client, master, tmp_path, db_sessions):
    paths = [
        make_fjnu_docx(tmp_path / "pass_docx"),
        make_fjnu_pdf(tmp_path / "pass_pdf"),
        make_fjnu_docx(tmp_path / "fail_docx", violation="PAGE_SIZE_A4"),
        make_fjnu_pdf(tmp_path / "fail_pdf", violation="PAGE_SIZE_A4"),
        make_damaged(tmp_path / "error_docx", "docx"),
        make_damaged(tmp_path / "error_pdf", "pdf"),
    ]
    batch = _json(_upload(client, master["id"], *paths, batch_name="混合检查"), 201)
    assert batch["name"] == "混合检查"
    assert batch["status"] == "completed"
    assert batch["completed_at"]
    assert (batch["total_count"], batch["pass_count"], batch["fail_count"], batch["error_count"]) == (6, 2, 2, 2)
    assert batch["pass_rate"] == pytest.approx(1 / 3)
    assert [row["file_name"] for row in batch["results"]] == [path.name for path in paths]
    assert [row["verdict"] for row in batch["results"]] == ["pass", "pass", "fail", "fail", "error", "error"]
    assert len({row["paper_id"] for row in batch["results"]}) == 6

    batches = _json(client.get(f"{API}/batches"))
    assert batches == [{key: value for key, value in batch.items() if key != "results"}]
    url = f"{API}/batches/{batch['id']}"
    assert len(_json(client.get(url))["results"]) == 6
    for verdict in ("pass", "fail", "error"):
        result = _json(client.get(url, params={"verdict": verdict}))
        assert result["total_count"] == 6
        assert [row["verdict"] for row in result["results"]] == [verdict, verdict]
    filtered = _json(client.get(url, params={"verdict": "error", "q": "损坏.PDF"}))
    assert [row["file_name"] for row in filtered["results"]] == [paths[-1].name]
    assert _json(client.get(url, params={"q": "%"}))["results"] == []
    _json(client.get(url, params={"verdict": "invalid"}), 422)

    failed = batch["results"][2]
    detail = _json(client.get(f"{API}/check-runs/{failed['id']}"))
    assert detail["error_count"] == len(detail["violations"]) > 0
    assert {item["rule_code"] for item in detail["violations"]} == {"PAGE_SIZE_A4"}
    finding = detail["violations"][0]
    assert finding["expected"] and finding["actual"] and finding["message"] and finding["location"]
    assert detail["manual_checklist"] == master["manual_checklist"]
    summary = detail["ir_summary"]
    assert summary["page_count"] == detail["page_count"] > 0
    assert summary["stats"]["body_chinese_chars"] >= 30000
    assert "abstract_cn" in {item["key"] for item in summary["sections"]}
    assert summary["capabilities"]["exact_margins"] is True

    pdf = _json(client.get(f"{API}/check-runs/{batch['results'][1]['id']}"))
    assert pdf["ir_summary"]["capabilities"]["exact_margins"] is False
    assert pdf["violations"] == []

    for damaged in batch["results"][-2:]:
        error = _json(client.get(f"{API}/check-runs/{damaged['id']}"))
        assert error["parse_status"] == "failed"
        assert error["parse_error"] and error["ir_summary"] is None
        assert error["score"] == 0 and error["violations"] == []
        with db_sessions() as db:
            assert db.get(Paper, UUID(error["paper_id"])).parsed_ir is None

    overview = _json(client.get(f"{API}/stats/overview"))
    assert (overview["total_count"], overview["pass_count"], overview["fail_count"], overview["error_count"]) == (6, 2, 2, 2)
    assert overview["pass_rate"] == pytest.approx(1 / 3)
    assert len(overview["top_violations"]) == 1
    top = overview["top_violations"][0]
    assert top["rule_code"] == "PAGE_SIZE_A4"
    assert top["affected_paper_count"] == 2
    assert top["violation_count"] == sum(row["error_count"] for row in batch["results"])
    assert top["violation_rank"] == top["violation_ratio"] == 1

    damaged = batch["results"][-1]
    rerun = _json(client.post(
        f"{API}/papers/{damaged['paper_id']}/recheck", json={"rule_set_id": master["id"]}
    ), 201)
    assert rerun["verdict"] == "error" and rerun["ir_summary"] is None


def test_recheck_uses_snapshot_and_updated_rules(client, master, tmp_path, db_sessions, monkeypatch):
    original = _json(_upload(
        client, master["id"], make_fjnu_docx(tmp_path, violation="PAGE_SIZE_A4")
    ), 201)["results"][0]
    assert original["verdict"] == "fail"
    item = next(rule for rule in master["rule_items"] if rule["rule_code"] == "PAGE_SIZE_A4")

    patch_url = f"{API}/rule-items/{item['id']}"
    updated = _json(client.patch(patch_url, json={"severity": "warning", "params": {"tolerance_mm": 1}}))
    assert updated["params"] == item["params"] | {"tolerance_mm": 1}
    assert updated["enabled"] and updated["severity"] == "warning"
    _json(client.patch(patch_url, json={"params": {"tolerance_mm": "invalid"}}), 422)

    with db_sessions() as db:
        paper = db.get(Paper, UUID(original["paper_id"]))
        assert paper.parsed_ir["file_name"] == original["file_name"]
        Path(paper.storage_path).unlink()

    def unexpected_parse(*args, **kwargs):
        pytest.fail("重检调用了解析器")

    monkeypatch.setattr(paper_service, "parse_document", unexpected_parse)
    url = f"{API}/papers/{original['paper_id']}/recheck"
    body = {"rule_set_id": master["id"]}
    rechecked = _json(client.post(url, json=body), 201)
    assert rechecked["id"] != original["id"]
    assert rechecked["paper_id"] == original["paper_id"]
    assert rechecked["batch_id"] is None
    assert rechecked["verdict"] == "pass"
    assert rechecked["score"] < 100
    assert rechecked["warning_count"] > 0 and rechecked["error_count"] == 0
    assert {entry["severity"] for entry in rechecked["violations"]} == {"warning"}

    _json(client.patch(patch_url, json={"enabled": False}))
    disabled = _json(client.post(url, json=body), 201)
    assert disabled["score"] == 100
    assert disabled["warning_count"] == 0 and disabled["violations"] == []
    old = _json(client.get(f"{API}/check-runs/{original['id']}"))
    assert old["verdict"] == "fail"
    assert all(entry["severity"] == "error" for entry in old["violations"])
    assert _json(client.get(f"{API}/batches/{original['batch_id']}"))["total_count"] == 1

    clone = _json(client.post(f"{API}/rule-sets", json={
        "code": "another_template", "name": "新模板", "source_rule_set_id": master["id"],
        "manual_checklist": ["复核新模板"],
    }), 201)
    switched = _json(client.post(url, json={"rule_set_id": clone["id"]}), 201)
    assert switched["rule_set_id"] == clone["id"]
    assert switched["manual_checklist"] == clone["manual_checklist"]
    assert switched["verdict"] == "pass"

    overview = _json(client.get(f"{API}/stats/overview"))
    assert overview["total_count"] == 4 and overview["pass_rate"] == 0.75
    assert overview["top_violations"][0]["affected_paper_count"] == 1


def test_deduplicate_bytes_keep_file_names(client, master, tmp_path, db_sessions):
    path = make_fjnu_docx(tmp_path)
    renamed = tmp_path / "renamed.docx"
    renamed.write_bytes(path.read_bytes())
    first = _json(_upload(client, master["id"], path), 201)["results"][0]
    second = _json(_upload(client, master["id"], renamed), 201)["results"][0]
    assert first["paper_id"] != second["paper_id"]
    assert first["verdict"] == "pass" and second["verdict"] == "fail"
    with db_sessions() as db:
        papers = db.scalars(select(Paper)).all()
        digest = sha256(path.read_bytes()).hexdigest()
        assert {paper.sha256 for paper in papers} == {digest}
        assert {paper.parsed_ir["file_name"] for paper in papers} == {path.name, renamed.name}
        (saved_path,) = {Path(paper.storage_path) for paper in papers}
        assert saved_path.read_bytes() == path.read_bytes()
        assert list(saved_path.parent.iterdir()) == [saved_path]


def test_stats_limits_results_to_ten_rules(client, master, tmp_path):
    paths = [
        make_fjnu_docx(tmp_path / code, violation=code)
        for code in DOCX_RULE_FAILURES[:11]
    ]
    batch = _json(_upload(client, master["id"], *paths), 201)
    counts = Counter()
    for run in batch["results"]:
        detail = _json(client.get(f"{API}/check-runs/{run['id']}"))
        counts.update(item["rule_code"] for item in detail["violations"])
    assert len(counts) > 10
    overview = _json(client.get(f"{API}/stats/overview"))
    expected = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    assert [(item["rule_code"], item["violation_count"]) for item in overview["top_violations"]] == expected


def test_batch_database_rollback_on_unexpected_failure(client, master, tmp_path, db_sessions, monkeypatch):
    evaluate = check_service.evaluate

    def fail_on_second(document, rules, **kwargs):
        if document["file_ext"] == "pdf":
            raise RuntimeError("forced evaluation failure")
        return evaluate(document, rules, **kwargs)

    monkeypatch.setattr(check_service, "evaluate", fail_on_second)
    paths = (
        make_fjnu_docx(tmp_path / "docx", violation="PAGE_SIZE_A4"),
        make_fjnu_pdf(tmp_path / "pdf"),
    )
    with pytest.raises(RuntimeError, match="forced evaluation failure"):
        _upload(client, master["id"], *paths)
    with db_sessions() as db:
        for model in (CheckBatch, Paper, CheckRun, CheckViolation):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_empty_queries_and_invalid_requests(client, master):
    assert _json(client.get(f"{API}/batches")) == []
    assert _json(client.get(f"{API}/stats/overview")) == {
        "total_count": 0, "pass_count": 0, "fail_count": 0, "error_count": 0,
        "pass_rate": 0, "top_violations": [],
    }
    missing = uuid4()
    for route in ("rule-sets", "batches", "check-runs"):
        _json(client.get(f"{API}/{route}/{missing}"), 404)
    _json(client.patch(f"{API}/rule-items/{missing}", json={"enabled": False}), 404)
    _json(client.patch(f"{API}/rule-items/{master['rule_items'][0]['id']}", json={"enabled": None}), 422)
    _json(client.post(f"{API}/papers/{missing}/recheck", json={"rule_set_id": master["id"]}), 404)
    _json(client.post(f"{API}/batches/check", data={"rule_set_id": master["id"]}), 422)
    files = [("files", ("unsupported.txt", b"not supported"))]
    _json(client.post(f"{API}/batches/check", data={"rule_set_id": master["id"]}, files=files), 422)
    assert _json(client.get(f"{API}/batches")) == []
