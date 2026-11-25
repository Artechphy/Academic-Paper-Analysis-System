from collections import Counter
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select

from app.db.models import CheckBatch, CheckRun, CheckViolation, Paper, RuleItem, RuleSet
from app.parsers.base import ParseError
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
    assert {item["rule_code"] for item in master["rule_items"] if item["severity"] == "warning"} == {
        "LINE_SPACING_MIN", "PAGE_MARGINS",
    }

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


def test_check_run_violations_sort_by_page_paragraph_severity_rule_and_id(client, master, tmp_path, db_sessions):
    path = make_fjnu_docx(tmp_path)
    run = _json(_upload(client, master["id"], path), 201)["results"][0]
    rows = [
        (1, {"page": 5, "paragraph_index": 0}, "error", "X"),
        (3, {"page": 2, "paragraph_index": 3}, "error", "A"),
        (2, {"page": 2, "paragraph_index": 3}, "error", "A"),
        (4, {"page": 2, "paragraph_index": 3}, "error", "B"),
        (5, {"page": 1, "paragraph_index": 20}, "warning", "A"),
        (6, {}, "warning", "A"),
        (7, {"page": 2}, "error", "A"),
        (8, {"page": 2, "paragraph_index": 0}, "warning", "A"),
        (9, {"page": 2, "paragraph_index": 3}, "warning", "A"),
        (10, {"paragraph_index": 0}, "error", "B"),
    ]
    with db_sessions.begin() as db:
        db.add_all(CheckViolation(id=UUID(int=id_), check_run_id=UUID(run["id"]), location=location,
                                  severity=severity, rule_code=code, category="page", rule_name=code,
                                  expected="要求", actual="实际", message="修正")
                   for id_, location, severity, code in rows)

    issues = _json(client.get(f"{API}/check-runs/{run['id']}"))["violations"]
    assert [UUID(item["id"]).int for item in issues] == [6, 10, 5, 7, 8, 2, 3, 4, 9, 1]


def test_reparse_refreshes_persisted_snapshot_preserves_active_revision_and_handles_errors(
    client, master, tmp_path, db_sessions, monkeypatch,
):
    path = make_fjnu_docx(tmp_path)
    run = _json(_upload(client, master["id"], path), 201)["results"][0]
    paper_id = UUID(run["paper_id"])
    with db_sessions.begin() as db:
        paper = db.get(Paper, paper_id)
        original = paper.parsed_ir
        stale = original | {"page_count": 99, "paragraphs": [
            p | {"text": "旧版解析标题"} if p["role"] == "cover_title" else p for p in original["paragraphs"]
        ]}
        paper.parsed_ir = stale
        paper.page_count, paper.detected_title, paper.parse_error = 99, "旧版解析标题", "旧状态"
    session_url = f"{API}/check-runs/{run['id']}/revisions"
    session = _json(client.post(session_url), 201)
    recheck_url = f"{API}/papers/{paper_id}/recheck"
    body = {"rule_set_id": master["id"], "reparse": True}

    fresh = _json(client.post(recheck_url, json=body), 201)
    assert fresh["verdict"] == "pass" and fresh["parse_status"] == "success"
    assert fresh["page_count"] == run["page_count"] == fresh["ir_summary"]["page_count"]
    assert fresh["detected_title"] == run["detected_title"] and fresh["parse_error"] is None
    with db_sessions() as db:
        assert db.get(Paper, paper_id).parsed_ir == original
    existing = _json(client.get(f"{API}/revisions/{session['id']}"))
    assert existing["original_paragraphs"] == session["original_paragraphs"]

    def cannot_parse(*args, **kwargs):
        raise ParseError("重解析测试错误")

    monkeypatch.setattr(paper_service, "parse_document", cannot_parse)
    failed = _json(client.post(recheck_url, json=body), 201)
    assert failed["verdict"] == "error" and failed["parse_status"] == "failed"
    assert failed["parse_error"] == "重解析测试错误"
    assert failed["ir_summary"] is failed["detected_title"] is failed["page_count"] is None
    with db_sessions() as db:
        paper = db.get(Paper, paper_id)
        assert paper.parsed_ir is None
        Path(paper.storage_path).unlink()
    missing = _json(client.post(recheck_url, json=body), 404)
    assert missing["detail"] == "论文原件不存在。"
    assert _json(client.post(session_url), 201)["id"] == session["id"]


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


def test_page_margins_warning_keeps_run_passed(client, master, tmp_path):
    file = make_fjnu_docx(tmp_path, violation="PAGE_MARGINS")
    batch = _json(_upload(client, master["id"], file), 201)
    run, = batch["results"]
    assert run["verdict"] == "pass" and run["error_count"] == 0 and run["warning_count"] > 0
    assert batch["pass_count"] == 1 and batch["fail_count"] == 0
    detail = _json(client.get(f"{API}/check-runs/{run['id']}"))
    assert {v["severity"] for v in detail["violations"]} == {"warning"}
    assert {v["rule_code"] for v in detail["violations"]} == {"PAGE_MARGINS"}


def test_spacing_severity_migration_remembers_only_updated_builtin_version_rows(db_sessions):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0003_spacing_rule_severity.py"
    spec = spec_from_file_location("spacing_severity_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db_sessions.begin() as db:
        connection = db.connection()
        with Operations.context(MigrationContext.configure(connection)):
            if inspect(connection).has_table("spacing_rule_severity_0003"):
                migration.downgrade()
            builtin = db.scalar(select(RuleSet).where(RuleSet.code == "fjnu_master_2019"))
            spacing, margins = [
                db.scalar(select(RuleItem).where(RuleItem.rule_set_id == builtin.id, RuleItem.rule_code == code))
                for code in ("LINE_SPACING_MIN", "PAGE_MARGINS")
            ]
            spacing.severity = "error"
            assert margins.severity == "warning"
            untouched = []
            for code, version in (("fjnu_master_2019", "2.0.0"), ("local_custom", "1.0.0")):
                future = RuleSet(id=uuid4(), code=code, version=version, name="Test")
                db.add(future)
                db.flush()
                rule = RuleItem(rule_set_id=future.id, rule_code="LINE_SPACING_MIN", category="page",
                                name="Test", description="Test", severity="error", applies_to="both")
                db.add(rule)
                untouched.append(rule)
            db.flush()

            migration.upgrade()
            db.expire_all()
            assert [rule.severity for rule in (spacing, margins, *untouched)] == ["warning", "warning", "error", "error"]
            migration.downgrade()
            db.expire_all()
            assert [rule.severity for rule in (spacing, margins, *untouched)] == ["error", "warning", "error", "error"]
