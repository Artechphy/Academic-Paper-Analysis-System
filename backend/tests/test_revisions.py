"""Phase 5 behavior through real documents, the seeded evaluator and the HTTP API."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from uuid import UUID, uuid4

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
import httpx
import pymupdf
import pytest
from sqlalchemy import func, select

from app.config import Settings, settings
from app.db.models import CheckRun, Paper, RevisionFeedback, RevisionSession
from app.db.seed import FJNU_MASTER_RULES, FJNU_RULES_BY_CODE
from app.engine.evaluator import Violation, evaluate
from app.parsers.docx_parser import parse_docx
from app.parsers.pdf_parser import parse_pdf
from app.revisions import docx_fixer, latex_annotator, llm_advisor
from app.revisions.consolidator import consolidate, select_pdf_annotations
from app.revisions.incremental import (
    edit_paragraph, evaluate_incremental, find_paragraph_element, resolved_findings, update_paragraph_ir,
)
from app.schemas.revisions import ParagraphEditRequest
from tests.fixtures_generator import CHAPTER, EXAMPLE, _PdfSample, _png, make_damaged, make_fjnu_docx
from tests.test_api import API, _json, _upload, master  # noqa: F401

PARAMS = {rule.code: rule.params for rule in FJNU_MASTER_RULES}


def _violation(code, page=None, paragraph=None, *, expected="规范", actual="待修正", severity="error"):
    rule = FJNU_RULES_BY_CODE[code]
    location = {}
    if page is not None:
        location.update(page=page, bbox=[40, 90, 130, 102], excerpt="原文")
    if paragraph is not None:
        location["paragraph_index"] = paragraph
    return Violation(rule_code=code, rule_name=rule.name, category=rule.category, severity=severity,
                     location=location, expected=expected, actual=actual, message="请修正格式。")


def _word_bytes(document):
    result = BytesIO()
    document.save(result)
    return result.getvalue()


def test_rulebook_scopes_fixed_points_and_caps():
    current = [
        _violation("FILE_NAME_PATTERN"),
        *(_violation("BODY_TYPOGRAPHY", page, index) for page in range(1, 40) for index in range(2)),
        *(_violation("REFERENCE_GBT7714", page, page + 100) for page in range(1, 40)),
        *(_violation("FIGURE_TABLE_CAPTION", 1, index + 200) for index in range(10)),
        _violation("LINE_SPACING_MIN", 4, 80),
    ]
    original = current + [_violation("REFERENCE_GBT7714", 40, 140), _violation("PAGE_MARGINS", 2)]
    notes = {"LINE_SPACING_MIN": llm_advisor.AdvisorNote(ignore=True, bubble_note="跳过")}
    book = consolidate(current, original, FJNU_MASTER_RULES, notes=notes)
    global_entry = next(e for e in book if e.rule_code == "FILE_NAME_PATTERN")
    cluster = next(e for e in book if e.rule_code == "BODY_TYPOGRAPHY")
    fixed = [e for e in book if e.status == "fixed"]
    assert global_entry.scope == "global"
    assert cluster.scope == "cluster" and cluster.original_count == cluster.total_count == 78
    assert len(cluster.representative_anchors) == 39
    assert [(e.rule_code, e.scope, e.total_count) for e in fixed] == [
        ("PAGE_MARGINS", "global", 0), ("REFERENCE_GBT7714", "point", 0),
    ]
    ignored = next(e for e in book if e.rule_code == "LINE_SPACING_MIN")
    assert ignored.status == "ignored" and ignored.total_count == 1
    annotations = select_pdf_annotations(book)
    assert len(annotations) == 25
    assert max(Counter(a.anchor.page for a in annotations).values()) <= 4
    assert all(a.entry.status != "ignored" for a in annotations)


def test_rulebook_keeps_rule_errors_and_warnings_on_separate_cards():
    wrong_header = _violation("HEADER_FORMAT", 5, expected="章名", actual="错误页眉")
    wrong_distance = _violation("HEADER_FORMAT", severity="warning", expected="页眉距", actual="当前距离")
    entries = consolidate([wrong_distance], [wrong_distance, wrong_header], FJNU_MASTER_RULES)
    assert [(e.severity, e.status, e.total_count, e.original_count) for e in entries] == [
        ("error", "fixed", 0, 1), ("warning", "open", 1, 1),
    ]
    assert entries[0].affected_pages == [5] and entries[1].affected_pages == []


def test_partially_corrected_compound_finding_keeps_its_open_rulebook_entry():
    code = "FIGURE_TABLE_CAPTION"
    original = _violation(code, 1, 0, expected="位置正确；编号正确")
    remaining = _violation(code, 2, 0, expected="编号正确")
    entry, = consolidate([remaining], [original], FJNU_MASTER_RULES)
    assert (entry.status, entry.total_count, entry.original_count, entry.affected_pages) == ("open", 1, 1, [2])
    assert resolved_findings([original], [remaining]) == 0
    assert resolved_findings([original], []) == 1


def test_docx_bilingual_captions_can_match_an_object_two_paragraphs_away():
    doc = Document()
    doc.add_heading(CHAPTER, level=1)
    doc.add_paragraph("表1 汇总结果")
    doc.add_paragraph("Table 1 Summary")
    doc.add_table(rows=2, cols=2)
    ir = parse_docx(_word_bytes(doc))
    table, = ir.figures_tables
    assert table.caption_text == "表1 汇总结果" and table.relative_position == "above"


def test_pdf_bboxes_for_wrapped_text_objects_headers_and_findings():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1, chapter=True)
        sample.heading(CHAPTER)
        sample.text(EXAMPLE[:29], 137)
        sample.text("with English", 137, font="tiro", left=sample.left + 29 * 12)
        sample.text(EXAMPLE[:18], 158, left=sample.left)
        sample.page.insert_image((180, 195, 360, 310), stream=_png())
        sample.text("图1 研究流程", 329, left=sample.left)
        sample.new_page(2)
        sample.heading("参考文献")
        sample.text("[1] " + EXAMPLE, 141)
        sample.text("参考文献续行。", 164, left=sample.left + 18)
        document = parse_pdf(sample.pdf.tobytes(), "20260001_测试.pdf")

    first_body = next(p for p in document.paragraphs if "English" in p.text)
    assert first_body.line_count == 2 and first_body.bbox[3] > 158
    assert first_body.line_spacings_pt == pytest.approx([21])
    assert document.headers_footers.odd_headers[0].bbox[3] < first_body.bbox[1]
    assert document.headers_footers.page_numbers[0].bbox[1] > first_body.bbox[3]
    reference, = document.references
    assert "续行" in reference.raw_text
    assert document.paragraphs[reference.paragraph_index].bbox[3] > 164
    figure, = document.figures_tables
    assert figure.bbox == document.paragraphs[figure.paragraph_index].bbox
    result = evaluate(document, [FJNU_RULES_BY_CODE["FIGURE_TABLE_CAPTION"], FJNU_RULES_BY_CODE["REFERENCE_GBT7714"]])
    assert result.violations and all(len(v.location["bbox"]) == 4 for v in result.violations)


def test_ooxml_mapping_keeps_graphics_and_revert_exact(tmp_path):
    document = Document()
    document.add_paragraph("先有段落")
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "表格文字"
    mixed = document.add_paragraph()
    mixed.add_run("图片前的原文").bold = True
    mixed.add_run().add_picture(BytesIO(_png()), width=Mm(15))
    math = OxmlElement("m:oMath")
    mixed._p.append(math)
    source = _word_bytes(document)
    ir = parse_docx(source)
    assert ir.paragraphs[1].object_kind == "table"
    assert ir.paragraphs[2].text == "表格文字"
    with pytest.raises(ValueError, match="占位符"):
        find_paragraph_element(document, 1)
    cell_element = edit_paragraph(document, 2, ParagraphEditRequest(text="改单元格"))
    assert cell_element.text == "改单元格"
    element = edit_paragraph(document, 3, ParagraphEditRequest(text="新文本", font_name="simsun", font_size_pt=12.5,
                                                              alignment="justify", line_spacing_pt=20))
    assert next(element.iter(qn("w:drawing")), None) is not None
    assert next(element.iter(qn("m:oMath")), None) is not None
    after = parse_docx(_word_bytes(document)).paragraphs[3]
    assert (after.text, after.font_name, after.font_size_pt, after.bold, after.alignment, after.line_spacing_pt) == (
        "新文本", "simsun", 12.5, True, "justify", 20,
    )
    original_document = Document(BytesIO(source))
    original_element = find_paragraph_element(original_document, 3)
    restored = edit_paragraph(document, 3, ParagraphEditRequest(revert=True), original=original_document)
    assert restored.xml == original_element.xml
    assert parse_docx(_word_bytes(document)).paragraphs[3] == ir.paragraphs[3]


@pytest.mark.parametrize(("original", "replace", "violation"), [
    ("body_text", {"font_name": "simsun", "font_size_pt": 12}, "BODY_TYPOGRAPHY"),
    ("keywords_cn", {"text": "关键词：版面；格式；文档"}, "ABSTRACT_CONTENT_RULES"),
    ("references", {"text": "[2] 李四. 版面数据规范[EB/OL]. [2025-05-18]. https://example.org/layout"}, "REFERENCE_GBT7714"),
    ("abstract_cn", {"text": "一个没有被识别成标题的段落。"}, None),
])
def test_incremental_matches_fresh_full_check(tmp_path, original, replace, violation):
    path = make_fjnu_docx(tmp_path, violation=violation)
    previous = parse_docx(path)
    document = Document(path)
    before = evaluate(previous, FJNU_MASTER_RULES)
    if original == "body_text":
        index = before.violations[0].location["paragraph_index"]
    elif original == "references":
        index = previous.references[-1].paragraph_index
    elif original == "abstract_cn":
        index = next(s.start_paragraph_index for s in previous.sections if s.key == original)
    else:
        index = next(p.index for p in previous.paragraphs if p.role == original)
    node = edit_paragraph(document, index, ParagraphEditRequest(**replace))
    current = update_paragraph_ir(previous, document, node, index)
    incremental = evaluate_incremental(current, previous, before.violations, FJNU_MASTER_RULES, index)
    full = evaluate(parse_docx(_word_bytes(document), path.name), FJNU_MASTER_RULES)
    assert incremental.model_dump(exclude={"duration_ms", "violations"}) == full.model_dump(
        exclude={"duration_ms", "violations"}
    )
    assert Counter(v.model_dump_json() for v in incremental.violations) == Counter(
        v.model_dump_json() for v in full.violations
    )


@pytest.mark.parametrize("code", [
    "PAGE_SIZE_A4", "PAGE_MARGINS", "HEADER_FORMAT", "HEADER_DOUBLE_BORDER", "PAGE_NUMBER_STYLE",
    "LINE_SPACING_MIN", "DECLARATION_TYPOGRAPHY", "ABSTRACT_CN_TYPOGRAPHY", "ABSTRACT_EN_TYPOGRAPHY",
    "TOC_TYPOGRAPHY", "HEADING_TYPOGRAPHY", "BODY_TYPOGRAPHY", "COVER_ELEMENTS",
])
def test_deterministic_repair_fixes_each_supported_fixture(tmp_path, code):
    file = make_fjnu_docx(tmp_path, violation=code)
    document = Document(file)
    original = parse_docx(file)
    checks = evaluate(original, FJNU_MASTER_RULES)
    assert {v.rule_code for v in checks.violations} == {code}
    docx_fixer.fix_document_layout(document, original, PARAMS, {code})
    docx_fixer.fix_typography(document, original, PARAMS, {code}, checks.violations)
    data = _word_bytes(document)
    assert Document(BytesIO(data)).inline_shapes
    result = evaluate(parse_docx(data, file.name), FJNU_MASTER_RULES)
    assert not result.violations, result.violations[:3]


def test_numbering_splits_mixed_word_section_without_adding_paragraphs():
    document = Document()
    for title, body in (
        ("论文标题", "福建师范大学"), ("摘要", "中文摘要内容"),
        ("Abstract", "English abstract text"), ("目录", f"{CHAPTER} . . . 1"),
        (CHAPTER, "论文主体正文"),
    ):
        document.add_paragraph(title, style="Heading 1" if title == CHAPTER else None)
        document.add_paragraph(body)
    before = parse_docx(_word_bytes(document))
    docx_fixer.fix_document_layout(document, before, PARAMS, {"PAGE_NUMBER_STYLE"})
    after = parse_docx(_word_bytes(document))
    assert len(after.paragraphs) == len(before.paragraphs)
    result = evaluate(after, [FJNU_RULES_BY_CODE["PAGE_NUMBER_STYLE"]])
    assert not result.violations, result.violations


def test_header_repair_for_plain_chapters_keeps_even_footer():
    document = Document()
    titles = ("第一章 研究背景", "第二章 研究方法")
    for index, title in enumerate(titles):
        document.add_paragraph(title)
        document.add_paragraph("正文内容。" if index == 0 else "第二章正文内容。")
    footer = document.sections[0].footer.paragraphs[0]
    footer.alignment = 1
    docx_fixer._put_field(footer, "PAGE", "1")
    before = parse_docx(_word_bytes(document))

    docx_fixer.fix_document_layout(document, before, PARAMS, {"HEADER_FORMAT", "HEADER_DOUBLE_BORDER"})
    after = parse_docx(_word_bytes(document))
    assert [p.text for p in after.paragraphs] == [p.text for p in before.paragraphs]
    assert [item.text for item in after.headers_footers.odd_headers] == list(titles)
    assert len([item for item in after.headers_footers.page_numbers
                if item.variant == "even" and item.num_format == "decimal"]) == 2
    rules = [FJNU_RULES_BY_CODE[code] for code in ("HEADER_FORMAT", "HEADER_DOUBLE_BORDER", "PAGE_NUMBER_STYLE")]
    assert not evaluate(after, rules).violations


def test_unstyled_long_docx_heading_survives_fixer_and_incremental_judgment():
    document = Document()
    document.add_paragraph(CHAPTER, style="Heading 1")
    title = "1.1 研究材料：纸质档案数字化的文本校对方法及其在教学资源中的应用"
    assert document.add_paragraph(title).style.name == "Normal" and len(title) > 24
    document.add_paragraph("这里是独立的正文。")
    original = parse_docx(_word_bytes(document))
    heading = original.paragraphs[1]
    assert heading.role == "section_l2_heading" and heading.unit_kind == "heading"
    rule = FJNU_RULES_BY_CODE["HEADING_TYPOGRAPHY"]
    before = evaluate(original, [rule])
    assert any(v.location["paragraph_index"] == 1 for v in before.violations)

    docx_fixer.fix_typography(document, original, PARAMS, {rule.code}, before.violations)
    repaired = parse_docx(_word_bytes(document))
    assert repaired.paragraphs[1].text == title and repaired.paragraphs[1].role == heading.role
    assert not evaluate(repaired, [rule]).violations
    node = edit_paragraph(document, 1, ParagraphEditRequest(font_size_pt=10))
    updated = update_paragraph_ir(repaired, document, node, 1)
    incremental = evaluate_incremental(updated, repaired, [], [rule], 1)
    full = evaluate(parse_docx(_word_bytes(document)), [rule])
    assert incremental.violations == full.violations
    assert full.violations[0].location["paragraph_index"] == 1


def test_advisor_mock_json_and_safe_fallback(tmp_path, monkeypatch):
    path = make_fjnu_docx(tmp_path, violation="ABSTRACT_CONTENT_RULES")
    ir = parse_docx(path)
    findings = evaluate(ir, FJNU_MASTER_RULES).violations
    book = consolidate(findings, findings, FJNU_MASTER_RULES)
    keywords = next(p for p in ir.paragraphs if p.role == "keywords_cn")
    normal = next(p for p in ir.paragraphs if p.section_key == "body" and p.role == "body_text")
    selected = {"ABSTRACT_CONTENT_RULES"}

    def reply(request):
        assert str(request.url).endswith("/v1/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-chat" and payload["response_format"] == {"type": "json_object"}
        context = json.loads(payload["messages"][1]["content"])
        assert context["instruction"] == "保留版面"
        assert context["paragraphs"][0]["paragraph_index"] == keywords.index
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "summary": "统一关键词分隔符",
            "rulebook_notes": {"ABSTRACT_CONTENT_RULES": {"bubble_note": "关键词使用全角分号"}},
            "text_replacements": [
                {"paragraph_index": keywords.index, "new_text": "关键词：版面；格式；文档"},
                {"paragraph_index": normal.index, "new_text": "正文不应更改"},
            ],
        })}}]})

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "deepseek-chat")
    with httpx.Client(transport=httpx.MockTransport(reply)) as http:
        advice = llm_advisor.advise(ir, book, PARAMS, selected, instruction="保留版面", client=http)
    assert advice.llm_used
    assert [r.paragraph_index for r in advice.output.text_replacements] == [keywords.index]
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": '{"summary":2}'}}]
    }))) as http:
        fallback = llm_advisor.advise(ir, book, PARAMS, selected, client=http)
    assert not fallback.llm_used and fallback.output.text_replacements[0].new_text == "关键词：版面；格式；文档"
    monkeypatch.setattr(settings, "llm_api_key", None)
    assert llm_advisor.advise(ir, book, PARAMS, selected) == fallback


@pytest.mark.parametrize("on_path", [True, False], ids=["path-discovery", "homebrew-fallback"])
def test_rendering_executable_defaults(monkeypatch, on_path):
    monkeypatch.delenv("XELATEX_BIN", raising=False)
    monkeypatch.delenv("SOFFICE_BIN", raising=False)
    monkeypatch.setattr("app.config.shutil.which", lambda binary: f"/usr/bin/{binary}" if on_path else None)

    config = Settings(_env_file=None)
    directory = "/usr/bin" if on_path else "/opt/homebrew/bin"
    assert (config.xelatex_bin, config.soffice_bin) == (f"{directory}/xelatex", f"{directory}/soffice")


def test_rendering_executable_environment_overrides_path_discovery(monkeypatch):
    monkeypatch.setenv("XELATEX_BIN", "/custom/bin/xelatex")
    monkeypatch.setenv("SOFFICE_BIN", "/custom/bin/soffice")
    monkeypatch.setattr("app.config.shutil.which", lambda binary: f"/usr/bin/{binary}")

    config = Settings(_env_file=None)
    assert (config.xelatex_bin, config.soffice_bin) == ("/custom/bin/xelatex", "/custom/bin/soffice")


def test_latex_uses_ordered_cjk_font_fallbacks():
    with pymupdf.open() as pdf:
        pdf.new_page()
        tex, _ = latex_annotator._tex(pdf, [], [], "论文.pdf", "issues_only")

    assert (
        r"\IfFontExistsTF{Songti SC}{\setCJKmainfont{Songti SC}}{"
        r"\IfFontExistsTF{Noto Serif CJK SC}{\setCJKmainfont{Noto Serif CJK SC}}{"
        r"\IfFontExistsTF{FandolSong}{\setCJKmainfont{FandolSong}}{\setCJKmainfont{STSong}}}}"
    ) in tex


def test_real_latex_has_source_and_balloon_at_separate_coordinates(tmp_path):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((70, 101), "Source text & original placement")
        document.new_page()
        page = document.new_page()
        page.insert_text((55, 150), "Last page")
        document.save(source)
    issue = _violation("BODY_TYPOGRAPHY", 1, 2)
    issues = consolidate([issue], [issue], FJNU_MASTER_RULES)
    issues[0].bubble_note = "中文，危险字符 \\{}$&#%^~_ 均转义"
    output = tmp_path / "annotated.pdf"
    count = latex_annotator.compile_annotated_pdf(source, output, issues, file_name="论文_&%{}.pdf")
    assert count == 2
    with pymupdf.open(output) as document:
        assert "论文修订批注" in document[0].get_text().replace(" ", "")
        assert "Source text" in document[1].get_text()
        error, = document[1].search_for("ERROR")
        source_box, = document[1].search_for("Source text")
        assert source_box.x0 < 130 < error.x0
        assert 70 < error.y0 < 150
    assert latex_annotator.compile_annotated_pdf(source, output, issues, file_name="论文.pdf", page_mode="full") == 4


def _session(client, template_id, path):
    run = _json(_upload(client, template_id, path), 201)["results"][0]
    url = f"{API}/check-runs/{run['id']}/revisions"
    return run, url, _json(client.post(url), 201)


def test_legacy_cached_violations_are_merged_in_read_and_saved_on_revision(
    client, master, tmp_path, db_sessions, monkeypatch,
):
    monkeypatch.setattr(settings, "llm_api_key", None)
    path = tmp_path / "20260001_测试.pdf"
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.heading(CHAPTER)
        sample.text("异常格式段落", 150, 9)
        sample.pdf.save(path)
    _, _, created = _session(client, master["id"], path)
    session_id = UUID(created["id"])
    with db_sessions.begin() as db:
        session = db.get(RevisionSession, session_id)
        issues = session.current_violations
        original = next(issue for issue in issues if issue["rule_code"] == "BODY_TYPOGRAPHY")
        duplicate = original | {"id": str(uuid4()), "expected": "第二项要求", "severity": "warning"}
        session.current_violations = [*issues, duplicate]
        session.warning_count += 1
        session.current_ir = session.current_ir | {"_original_violations": [*issues, duplicate | {"severity": "error"}]}
        session.original_error_count += 1

    url = f"{API}/revisions/{session_id}"
    detail = _json(client.get(url))
    body, = [issue for issue in detail["violations"] if issue["rule_code"] == "BODY_TYPOGRAPHY"]
    assert body["expected"].endswith("；第二项要求") and body["severity"] == "error"
    assert (detail["warning_count"], detail["original_error_count"]) == (
        created["warning_count"], created["original_error_count"],
    )
    saved = _json(client.post(f"{url}/auto-fix", json={"rule_codes": ["BODY_TYPOGRAPHY"]}))
    assert saved["violations"] == detail["violations"]
    with db_sessions() as db:
        session = db.get(RevisionSession, session_id)
        assert len(session.current_violations) == len(session.current_ir["_original_violations"]) == len(issues)


def test_revision_creation_rejudges_historical_severity_with_current_rules(client, master, tmp_path):
    item = next(rule for rule in master["rule_items"] if rule["rule_code"] == "LINE_SPACING_MIN")
    patch_url = f"{API}/rule-items/{item['id']}"
    _json(client.patch(patch_url, json={"severity": "error"}))
    path = make_fjnu_docx(tmp_path, violation="LINE_SPACING_MIN")
    run = _json(_upload(client, master["id"], path), 201)["results"][0]
    assert run["verdict"] == "fail" and run["error_count"] == 1
    _json(client.patch(patch_url, json={"severity": "warning"}))

    session = _json(client.post(f"{API}/check-runs/{run['id']}/revisions"), 201)
    assert session["verdict"] == "pass" and session["warning_count"] == 1
    assert session["error_count"] == session["original_error_count"] == 0
    item, = session["violations"]
    assert item["severity"] == "warning" and UUID(item["id"]).version == 5
    assert [(e["severity"], e["original_count"]) for e in session["rulebook"]] == [("warning", 1)]
    historical = _json(client.get(f"{API}/check-runs/{run['id']}"))
    assert historical["violations"][0]["severity"] == "error"


def test_revision_http_workflow_including_native_files_and_conversion(client, master, tmp_path, db_sessions, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", None)
    source = make_fjnu_docx(tmp_path, violation="BODY_TYPOGRAPHY")
    raw = Document(source)
    raw.sections[0].page_width = Mm(220)
    raw.sections[0].left_margin = Mm(40)
    raw.save(source)
    renamed_source = source.with_name("待修订.docx")
    source.rename(renamed_source)
    original_hash = sha256(renamed_source.read_bytes()).hexdigest()
    run, create_url, created = _session(client, master["id"], renamed_source)
    base = f"{API}/revisions/{created['id']}"
    assert created["version"] == 1 and created["editable"] and not created["comparison_ready"]
    assert _json(client.post(create_url), 201)["id"] == created["id"]
    cloned = _json(client.post(create_url, params={"force_new": True}), 201)
    assert cloned["id"] != created["id"]
    assert _json(client.post(create_url), 201)["id"] == cloned["id"]
    assert _json(client.get(base))["id"] == created["id"]
    assert all(UUID(item["id"]).version in {4, 5} for item in created["violations"])
    _json(client.get(f"{base}/download/annotated_pdf"), 404)

    issue = next(v for v in created["violations"] if v["rule_code"] == "BODY_TYPOGRAPHY")
    index = issue["location"]["paragraph_index"]
    edit_url = f"{base}/paragraphs/{index}"
    edited = _json(client.patch(edit_url, json={"font_name": "simsun", "font_size_pt": 12, "line_spacing_pt": 22}))
    assert edited["version"] == 2 and edited["resolved_count"] == 1 and edited["remaining_count"] == 0
    assert edited["changes"][0]["source"] == "manual"
    reverted = _json(client.patch(edit_url, json={"revert": True}))
    assert reverted["version"] == 3 and reverted["paragraph_violations"][0]["rule_code"] == "BODY_TYPOGRAPHY"
    assert not reverted["modified_paragraphs"]
    placeholder = next(p["index"] for p in created["current_paragraphs"] if p["object_kind"] == "table")
    _json(client.patch(f"{base}/paragraphs/{placeholder}", json={"text": "不可替换"}), 400)

    settings_url = f"{base}/document-settings"
    _json(client.patch(settings_url, json={"target_file_name": "../错误.docx"}), 400)
    adjusted = _json(client.patch(settings_url, json={
        "target_file_name": "20260001_测试.docx", "fix_page_size_a4": True, "fix_margins": True, "fix_headers": True,
    }))
    assert adjusted["version"] == 4
    assert {v["rule_code"] for v in adjusted["violations"]} == {"BODY_TYPOGRAPHY"}
    auto = _json(client.post(f"{base}/auto-fix", json={"instruction": "请保留所有正文措辞"}))
    assert auto["comparison_ready"] and not auto["llm_used"] and auto["verdict"] == "pass"
    assert auto["version"] == 5 and auto["error_count"] == 0 and auto["original_error_count"] > 0
    assert [item["author"] for item in auto["feedbacks"]] == ["user", "agent"]
    docx_response = client.get(f"{base}/download/docx")
    assert docx_response.status_code == 200
    assert "20260001_" in docx_response.headers["content-disposition"]
    downloaded = Document(BytesIO(docx_response.content))
    assert len(downloaded.inline_shapes) == len(raw.inline_shapes)
    assert not evaluate(parse_docx(docx_response.content, auto["target_file_name"]), FJNU_MASTER_RULES).violations

    pdf = _json(client.post(f"{base}/export/annotated-pdf"))
    assert pdf["page_mode"] == "issues_only" and pdf["page_count"] > 1
    response = client.get(pdf["download_url"])
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    with pymupdf.open(stream=response.content, filetype="pdf") as result:
        assert result.page_count == pdf["page_count"]
        assert any("FIXED" in p.get_text() for p in list(result)[1:])
    assert len(list((settings.revisions_dir / "pdf-cache").glob("*.pdf"))) == 1
    assert _json(client.post(f"{base}/export/annotated-pdf")) == pdf
    _json(client.patch(edit_url, json={"text": edited["paragraph"]["text"] + "人工续订"}))
    _json(client.get(pdf["download_url"]), 404)
    with db_sessions() as db:
        paper = db.get(Paper, UUID(run["paper_id"]))
        assert sha256(Path(paper.storage_path).read_bytes()).hexdigest() == original_hash
        assert db.scalar(select(func.count()).select_from(RevisionFeedback)) == 2
        assert db.get(RevisionSession, UUID(created["id"])).annotated_pdf_path is None


def test_read_only_pdf_suggestions_and_failed_run_boundaries(client, master, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", None)
    sample = _PdfSample(None)
    path = tmp_path / "20260001_测试.pdf"
    with closing(sample.pdf):
        sample.new_page("I")
        sample.heading("摘要")
        sample.text("研究内容引用了已有工作[1]并分析结果。", 140)
        sample.text("关键词：版面;结构;测试", 162)
        sample.pdf.save(path)
    run, _, session = _session(client, master["id"], path)
    base = f"{API}/revisions/{session['id']}"
    assert session["editable"] is False
    assert _json(client.get(base))["paper_id"] == run["paper_id"]
    _json(client.patch(f"{base}/paragraphs/0", json={"text": "示例"}), 400)
    _json(client.patch(f"{base}/document-settings", json={"fix_margins": True}), 400)
    _json(client.get(f"{base}/download/docx"), 400)
    fixed = _json(client.post(f"{base}/auto-fix", json={
        "rule_codes": ["ABSTRACT_CONTENT_RULES"], "instruction": "保留原有术语",
    }))
    assert fixed["comparison_ready"] and fixed["changes"]
    assert fixed["violations"] == session["violations"]
    assert fixed["original_paragraphs"] == session["original_paragraphs"]
    assert "[1]" not in next(change["after_text"] for change in fixed["changes"] if "[1]" in change["before_text"])
    full = _json(client.post(f"{base}/export/annotated-pdf", json={"page_mode": "full"}))
    assert full["page_count"] == 2
    _json(client.get(f"{API}/revisions/{uuid4()}"), 404)
    _json(client.post(f"{API}/check-runs/{uuid4()}/revisions"), 404)
    damaged = make_damaged(tmp_path, "docx")
    failed = _json(_upload(client, master["id"], damaged), 201)["results"][0]
    _json(client.post(f"{API}/check-runs/{failed['id']}/revisions"), 400)


def test_existing_pdf_revision_refreshes_findings_and_advice_when_rules_change(
    client, master, tmp_path, db_sessions, monkeypatch,
):
    monkeypatch.setattr(settings, "llm_api_key", None)
    path = tmp_path / "20260001_测试.pdf"
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page("I")
        sample.heading("摘要")
        sample.text("研究采用文档分析法。", 140)
        sample.text("关键词：版面;结构;测试", 162)
        sample.pdf.save(path)
    code = "ABSTRACT_CONTENT_RULES"
    run, _, created = _session(client, master["id"], path)
    base = f"{API}/revisions/{created['id']}"
    options = {"rule_codes": [code]}
    suggested = _json(client.post(f"{base}/auto-fix", json=options))
    issues = [v for v in suggested["violations"] if v["rule_code"] == code]
    assert issues and all(v["severity"] == "error" for v in issues)
    assert any("版面；结构；测试" in diff["after_text"] for diff in suggested["changes"])
    session_id = UUID(created["id"])
    with db_sessions() as db:
        original_signature = db.get(RevisionSession, session_id).current_ir["_rules_signature"]

    item = next(rule for rule in master["rule_items"] if rule["rule_code"] == code)
    _json(client.patch(f"{API}/rule-items/{item['id']}", json={"severity": "warning"}))
    adviser = llm_advisor.advise
    seen = []

    def record_advice(document, rulebook, *args, **kwargs):
        seen.extend((e.severity, e.status) for e in rulebook if e.rule_code == code)
        return adviser(document, rulebook, *args, **kwargs)

    monkeypatch.setattr(llm_advisor, "advise", record_advice)
    refreshed = _json(client.post(f"{base}/auto-fix", json=options))
    assert seen and set(seen) == {("warning", "open")}
    current = [v for v in refreshed["violations"] if v["rule_code"] == code]
    assert [v["actual"] for v in current] == [v["actual"] for v in issues]
    assert {v["severity"] for v in current} == {"warning"}
    assert refreshed["error_count"] == suggested["error_count"] - len(issues)
    assert refreshed["warning_count"] == suggested["warning_count"] + len(issues)
    assert _json(client.get(base))["violations"] == refreshed["violations"]
    with db_sessions() as db:
        stored = db.get(RevisionSession, session_id).current_ir
        assert stored["_rules_signature"] != original_signature
        assert {v["severity"] for v in stored["_original_violations"] if v["rule_code"] == code} == {"warning"}
    historical = _json(client.get(f"{API}/check-runs/{run['id']}"))
    assert {v["severity"] for v in historical["violations"] if v["rule_code"] == code} == {"error"}


def test_revision_feedback_and_sessions_cascade_from_run(client, master, tmp_path, db_sessions, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", None)
    run, _, revision = _session(client, master["id"], make_fjnu_docx(tmp_path, violation="REQUIRED_SECTIONS"))
    base = f"{API}/revisions/{revision['id']}"
    fixed = _json(client.post(f"{base}/auto-fix", json={"instruction": "保留现有内容"}))
    assert {v["rule_code"] for v in fixed["violations"]} == {"REQUIRED_SECTIONS"}
    response = client.get(f"{base}/download/docx")
    revised_file = Document(BytesIO(response.content))
    assert any("答辩签名表" in comment.text for comment in revised_file.comments)
    with db_sessions.begin() as db:
        db.delete(db.get(CheckRun, UUID(run["id"])))
    with db_sessions() as db:
        assert db.get(RevisionSession, UUID(revision["id"])) is None
        assert db.scalar(select(func.count()).select_from(RevisionFeedback)) == 0


def test_auto_fix_uses_advisor_and_records_real_text_diff(client, master, tmp_path, monkeypatch):
    path = make_fjnu_docx(tmp_path, violation="ABSTRACT_CONTENT_RULES")
    _, _, initial = _session(client, master["id"], path)
    keywords = next(p for p in initial["current_paragraphs"] if p["role"] == "keywords_cn")
    base = f"{API}/revisions/{initial['id']}"
    monkeypatch.setattr(settings, "llm_api_key", "local-test-key")
    monkeypatch.setattr(settings, "llm_model", "deepseek-chat")
    advise = llm_advisor.advise

    def response(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "summary": "按意见整理关键词。",
            "text_replacements": [{"paragraph_index": keywords["index"], "new_text": "关键词：版面；格式；文档",
                                   "reason": "保留术语并统一分隔符"}],
        })}}]})

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        monkeypatch.setattr(llm_advisor, "advise", lambda *args, **kwargs: advise(*args, **kwargs, client=http))
        revised = _json(client.post(f"{base}/auto-fix", json={
            "instruction": "请保留术语", "rule_codes": ["ABSTRACT_CONTENT_RULES"],
        }))
    assert revised["llm_used"] and revised["llm_model"] == "deepseek-chat"
    change, = revised["changes"]
    assert change["source"] == "llm" and change["summary"] == "保留术语并统一分隔符"
    assert revised["verdict"] == "pass" and revised["feedbacks"][0]["instruction"] == "请保留术语"


def test_saved_word_page_break_remains_during_text_edit():
    original = Document()
    paragraph = original.add_paragraph()
    paragraph.add_run("旧文字")._r.insert(0, OxmlElement("w:lastRenderedPageBreak"))
    paragraph.add_run().add_break()
    original.add_paragraph("后续段落")
    before = parse_docx(_word_bytes(original))
    edit_paragraph(original, 0, ParagraphEditRequest(text="新文字"))
    node = find_paragraph_element(original, 0)
    assert next(node.iter(qn("w:lastRenderedPageBreak")), None) is not None
    revised = parse_docx(_word_bytes(original))
    assert revised.paragraphs[0].text == "新文字"
    assert revised.paragraphs[1].page_no == before.paragraphs[1].page_no
