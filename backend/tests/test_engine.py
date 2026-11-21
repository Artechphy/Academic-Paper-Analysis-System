from dataclasses import asdict, replace
import re
from uuid import uuid4

import pytest

from app.db.models import RuleItem
from app.db.seed import BUILTIN_TEMPLATES, FJNU_MASTER_RULES, GENERAL_ACADEMIC_RULES
from app.engine.evaluator import evaluate
from app.engine.rules_catalog import RULES_CATALOG
from app.parsers.base import parse_document
from tests.fixtures_generator import (
    DOCX_RULE_FAILURES, PDF_RULE_FAILURES, make_fjnu_docx, make_fjnu_pdf, make_general_docx, make_scan,
)


def _summarize(result):
    return [(v.rule_code, v.expected, v.actual, v.location) for v in result.violations[:15]]


def test_rules_cover_seed_codes():
    assert len(FJNU_MASTER_RULES) == 21
    assert set(RULES_CATALOG) == {rule.code for rule in FJNU_MASTER_RULES}
    assert set(DOCX_RULE_FAILURES) | set(PDF_RULE_FAILURES) == set(RULES_CATALOG)
    assert {rule.code for rule in GENERAL_ACADEMIC_RULES} <= set(RULES_CATALOG)


@pytest.mark.parametrize(("template_index", "generator", "options", "passed", "skipped"), [
    (0, make_fjnu_docx, {}, 20, 1),
    (0, make_fjnu_pdf, {}, 19, 2),
    (1, make_fjnu_docx, {"degree": "doctor"}, 20, 1),
    (2, make_general_docx, {}, 5, 1),
], ids=["master-docx", "master-pdf", "doctor-docx", "general-docx"])
def test_complete_compliant_document(tmp_path, template_index, generator, options, passed, skipped):
    snapshot = parse_document(generator(tmp_path, **options)).model_dump(mode="json")
    result = evaluate(snapshot, BUILTIN_TEMPLATES[template_index].rules)
    assert not result.violations, _summarize(result)
    assert (result.verdict, result.score) == ("pass", 100)
    assert (result.passed_rules_count, result.skipped_rules_count) == (passed, skipped)
    assert (result.error_count, result.warning_count) == (0, 0)


@pytest.mark.parametrize("rule_code", DOCX_RULE_FAILURES)
def test_one_docx_rule_failure(tmp_path, rule_code):
    ir = parse_document(make_fjnu_docx(tmp_path, violation=rule_code))
    result = evaluate(ir, FJNU_MASTER_RULES)
    assert {v.rule_code for v in result.violations} == {rule_code}, _summarize(result)
    assert result.verdict == "fail"
    assert result.error_count == len(result.violations) and result.warning_count == 0
    assert result.score == 95
    for item in result.violations:
        assert re.search(r"[\u4e00-\u9fff]", item.expected)
        assert re.search(r"[\u4e00-\u9fff]", item.actual)
        assert re.search(r"[\u4e00-\u9fff]", item.message)
        assert item.location


@pytest.mark.parametrize("rule_code", PDF_RULE_FAILURES)
def test_one_pdf_rule_failure(tmp_path, rule_code):
    ir = parse_document(make_fjnu_pdf(tmp_path, violation=rule_code))
    result = evaluate(ir, FJNU_MASTER_RULES)
    assert {v.rule_code for v in result.violations} == {rule_code}, _summarize(result)
    assert result.verdict == "fail"
    assert result.error_count == len(result.violations)
    assert result.score == round(100 * 18 / 19, 2)


def test_severity_enabled_applicability_and_parameter_update(tmp_path):
    ir = parse_document(make_fjnu_docx(tmp_path, violation="PAGE_SIZE_A4"))
    seeds = {rule.code: rule for rule in FJNU_MASTER_RULES}
    config = RuleItem(
        id=uuid4(), rule_code=seeds["PAGE_SIZE_A4"].code, category="page", name="纸张尺寸",
        severity="warning", applies_to="both", enabled=True, params=seeds["PAGE_SIZE_A4"].params,
    )
    docx_only = asdict(seeds["PAGE_MARGINS"]) | {"enabled": False}
    result = evaluate(ir, [config, docx_only, seeds["PDF_NOT_IMAGE_ONLY"], seeds["FILE_NAME_PATTERN"]])
    assert (result.verdict, result.score, result.error_count, result.warning_count) == ("pass", 50, 0, 3)
    assert (result.passed_rules_count, result.skipped_rules_count) == (1, 2)
    assert {v.rule_item_id for v in result.violations} == {config.id}
    config.params = config.params | {"width_mm": 220}
    assert evaluate(ir, [config]).score == 100


def test_general_body_consistency_checks_minor_runs(tmp_path):
    ir = parse_document(make_general_docx(tmp_path))
    body = next(p for p in ir.paragraphs if p.section_key == "body" and p.role == "body_text")
    body.runs.append(body.runs[0].model_copy(update={"text": "异常字号", "font_size_pt": 15}))
    result = evaluate(ir, GENERAL_ACADEMIC_RULES)
    assert {v.rule_code for v in result.violations} == {"BODY_TYPOGRAPHY"}


def test_scanned_and_failed_documents_have_different_verdicts(tmp_path):
    scan = parse_document(make_scan(tmp_path))
    rule = next(rule for rule in FJNU_MASTER_RULES if rule.code == "PDF_NOT_IMAGE_ONLY")
    assert evaluate(scan, [rule]).verdict == "fail"
    assert evaluate(scan, [replace(rule, params={"allow_image_only": True})]).verdict == "pass"
    failure = evaluate(None, FJNU_MASTER_RULES, parse_status="failed")
    assert failure.verdict == "error" and failure.score == 0
    assert not failure.violations


def test_title_spacing_threshold_is_inclusive(tmp_path):
    ir = parse_document(make_fjnu_docx(tmp_path))
    title = next(p for p in ir.paragraphs if p.role == "chapter_heading")
    rule = next(rule for rule in FJNU_MASTER_RULES if rule.code == "LINE_SPACING_MIN")
    title.line_spacing_pt = 21.5
    assert evaluate(ir, [rule]).verdict == "pass"
    title.line_spacing_pt = 21.45
    violation, = evaluate(ir, [rule]).violations
    assert violation.location["paragraph_index"] == title.index
