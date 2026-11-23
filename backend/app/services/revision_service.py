"""Manage revision sessions, their working copies and downloadable artifacts."""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4, uuid5

import pymupdf
from docx import Document
from docx.oxml.ns import qn
from sqlalchemy import case, select

from app.config import settings
from app.db.models import CheckRun, CheckViolation, Paper, RevisionFeedback, RevisionSession, RuleSet
from app.db.seed import DOCTOR_PARAM_OVERRIDES, FJNU_RULES_BY_CODE
from app.engine.evaluator import evaluate
from app.parsers.base import cover_elements, summarize_document
from app.parsers.docx_parser import parse_docx
from app.revisions import docx_fixer, llm_advisor
from app.revisions.consolidator import consolidate
from app.revisions.incremental import (
    edit_paragraph, evaluate_incremental, find_paragraph_element, paragraph_diff, paragraph_elements, replace_text,
    resolved_findings, update_paragraph_ir,
)
from app.revisions.latex_annotator import compile_annotated_pdf, convert_docx_to_pdf
from app.schemas.checks import ViolationResponse
from app.schemas.ir import DocumentIR, ParagraphIR, TextRunIR
from app.schemas.revisions import AnnotatedPdfExportResponse, ParagraphEditResponse, RevisionSessionDetail, RulebookEntry
from app.services.check_service import rule_items_query


class RevisionNotFound(LookupError):
    pass


def _feedbacks(db, session_id):
    return db.scalars(select(RevisionFeedback).where(RevisionFeedback.session_id == session_id).order_by(
        RevisionFeedback.version, case((RevisionFeedback.author == "user", 0), else_=1), RevisionFeedback.id,
    )).all()


def _original_violations(db, run_id):
    values = db.scalars(select(CheckViolation).where(CheckViolation.check_run_id == run_id).order_by(
        CheckViolation.rule_code, CheckViolation.id,
    )).all()
    return [ViolationResponse.model_validate(value) for value in values]


def _responses(violations, session_id):
    duplicate = {}
    responses = []
    for issue in violations:
        if isinstance(issue, ViolationResponse):
            responses.append(issue)
            continue
        payload = issue.model_dump(mode="json")
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        duplicate[key] = duplicate.get(key, 0) + 1
        responses.append(ViolationResponse(**payload, id=uuid5(session_id, f"{key}:{duplicate[key]}")))
    return responses


def _rule_signature(rules):
    data = [(str(rule.id), rule.rule_code, rule.enabled, rule.severity, rule.applies_to, rule.params) for rule in rules]
    return sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _snapshot(document, rules):
    return document.model_dump(mode="json") | {"_rules_signature": _rule_signature(rules)}


def _rule_params(rules, file_ext):
    return {rule.rule_code: rule.params for rule in rules if rule.enabled and rule.applies_to in {"both", file_ext}}


def _get(db, session_id, *, lock=False):
    session = db.scalar(select(RevisionSession).where(RevisionSession.id == session_id).with_for_update()
                        if lock else select(RevisionSession).where(RevisionSession.id == session_id))
    if session is None:
        raise RevisionNotFound("修订会话不存在。")
    return session, db.get(Paper, session.paper_id)


def _detail(db, session, paper):
    return RevisionSessionDetail(
        **{key: getattr(session, key) for key in (
            "id", "check_run_id", "paper_id", "rule_set_id", "target_file_name", "version", "comparison_ready",
            "annotated_page_mode", "llm_used", "llm_model", "verdict", "score", "error_count", "warning_count",
            "original_error_count", "rulebook", "changes", "modified_paragraphs", "updated_at",
        )},
        file_name=paper.file_name, file_ext=paper.file_ext, editable=paper.file_ext == "docx",
        annotated_pdf_ready=bool(session.annotated_pdf_path and Path(session.annotated_pdf_path).is_file()),
        original_paragraphs=paper.parsed_ir["paragraphs"], current_paragraphs=session.current_ir["paragraphs"],
        violations=session.current_violations, feedbacks=_feedbacks(db, session.id),
    )


def _source(session, paper):
    path = Path(session.working_docx_path or paper.storage_path)
    if not path.is_file():
        raise RevisionNotFound("论文原件或工作副本不存在。")
    return path


def _directory(session):
    return settings.revisions_dir.resolve() / str(session.id)


def _write_copy(db, session, data):
    directory = _directory(session)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"v{session.version}-{uuid4().hex}.docx"
    with NamedTemporaryFile(dir=directory, suffix=".tmp") as stream:
        stream.write(data)
        stream.flush()
        path.hardlink_to(stream.name)
    db.info.setdefault("revision_artifacts", []).append(path)
    session.working_docx_path = str(path)


def _serialize(document):
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def create(db, run_id, *, force_new=False):
    run = db.scalar(select(CheckRun).where(CheckRun.id == run_id).with_for_update())
    if run is None:
        raise RevisionNotFound("检测记录不存在。")
    paper = db.get(Paper, run.paper_id)
    if paper.parse_status != "success" or paper.parsed_ir is None:
        raise ValueError("仅能修订已成功解析的论文。")
    if not force_new:
        existing = db.scalar(select(RevisionSession).where(RevisionSession.check_run_id == run_id).order_by(
            RevisionSession.updated_at.desc(), RevisionSession.created_at.desc(), RevisionSession.id.desc(),
        ).limit(1))
        if existing is not None:
            return _detail(db, existing, paper)
    rules = db.scalars(rule_items_query(run.rule_set_id)).all()
    original = _original_violations(db, run_id)
    document = DocumentIR.model_validate(paper.parsed_ir)
    now = datetime.now(timezone.utc)
    session = RevisionSession(
        id=uuid4(), check_run_id=run.id, paper_id=paper.id, rule_set_id=run.rule_set_id,
        target_file_name=paper.file_name, verdict=run.verdict, score=run.score, error_count=run.error_count,
        warning_count=run.warning_count, original_error_count=run.error_count, current_ir=_snapshot(document, rules),
        current_violations=[issue.model_dump(mode="json") for issue in original],
        rulebook=[entry.model_dump(mode="json") for entry in consolidate(original, original, rules, editable=paper.file_ext == "docx")],
        changes=[], modified_paragraphs=[], created_at=now, updated_at=now,
    )
    db.add(session)
    db.flush()
    if paper.file_ext == "docx":
        _write_copy(db, session, _source(session, paper).read_bytes())
    return _detail(db, session, paper)


def get(db, session_id):
    session, paper = _get(db, session_id)
    return _detail(db, session, paper)


def _editable(paper):
    if paper.file_ext != "docx":
        raise ValueError("PDF 仅支持只读建议和批注导出。")


def _current(session):
    return DocumentIR.model_validate(session.current_ir)


def _existing_issues(session):
    return [ViolationResponse.model_validate(item) for item in session.current_violations]


def _prior_notes(session):
    default_guidance = {}
    for issue in session.current_violations:
        default_guidance.setdefault(issue["rule_code"], set()).add(issue["message"])
    return {
        entry["rule_code"]: llm_advisor.AdvisorNote(
            ignore=entry["status"] == "ignored", guidance=entry["guidance"], bubble_note=entry["bubble_note"],
        ) for entry in session.rulebook if entry["status"] == "ignored"
        or entry["status"] == "open" and (
            entry["guidance"] not in default_guidance.get(entry["rule_code"], ())
            or entry["bubble_note"] != entry["guidance"][:60]
        )
    }


def _advance(session):
    session.version += 1
    session.updated_at = datetime.now(timezone.utc)
    session.annotated_pdf_path = None
    session.annotated_page_mode = None


def _recompute(db, session, paper, before, document, rules, result=None, *, sources=None, summary="", notes=None,
               reasons=None):
    if result is not None:
        session.verdict, session.score = result.verdict, result.score
        session.error_count, session.warning_count = result.error_count, result.warning_count
        session.current_violations = [v.model_dump(mode="json") for v in _responses(result.violations, session.id)]
    original_violations = _original_violations(db, session.check_run_id)
    previous_notes = _prior_notes(session)
    previous_notes.update(notes or {})
    session.rulebook = [entry.model_dump(mode="json") for entry in consolidate(
        session.current_violations, original_violations, rules, notes=previous_notes, editable=paper.file_ext == "docx",
    )]
    original = DocumentIR.model_validate(paper.parsed_ir)
    prior_diffs = {diff["paragraph_index"]: diff for diff in session.changes}
    changes = []
    before_by_index = {p.index: p for p in before.paragraphs}
    originals = {p.index: p for p in original.paragraphs}
    for p in document.paragraphs:
        if p.index not in originals:
            continue
        old = prior_diffs.get(p.index)
        unchanged = p == before_by_index.get(p.index)
        source = (sources or {}).get(p.index)
        if source is None:
            source = old["source"] if old and unchanged else "rule"
        explanation = (reasons or {}).get(p.index) or (old["summary"] if old and unchanged else summary)
        diff = paragraph_diff(originals[p.index], p, source, explanation)
        if diff:
            changes.append(diff.model_dump(mode="json"))
    session.changes = changes
    session.modified_paragraphs = [diff["paragraph_index"] for diff in changes]
    session.current_ir = _snapshot(document, rules)
    _advance(session)


def edit(db, session_id, index, request):
    session, paper = _get(db, session_id, lock=True)
    _editable(paper)
    source = _source(session, paper)
    before = _current(session)
    if not 0 <= index < len(before.paragraphs):
        raise ValueError("段落索引不存在。")
    docx = Document(str(source))
    prior_element = find_paragraph_element(docx, index)
    section = prior_element.find(f"{qn('w:pPr')}/{qn('w:sectPr')}")
    original_docx = Document(paper.storage_path) if request.revert else None
    element = edit_paragraph(docx, index, request, original=original_docx)
    new_section = element.find(f"{qn('w:pPr')}/{qn('w:sectPr')}")
    layout_changed = request.revert and (section is not None or new_section is not None)
    data = _serialize(docx)
    if layout_changed:
        current = parse_docx(data, session.target_file_name)
    else:
        restored = ParagraphIR.model_validate(paper.parsed_ir["paragraphs"][index]) if request.revert else None
        current = update_paragraph_ir(before, docx, element, index, restored=restored)
    previous = _existing_issues(session)
    rules = db.scalars(rule_items_query(session.rule_set_id)).all()
    if layout_changed or session.current_ir.get("_rules_signature") != _rule_signature(rules):
        result = evaluate(current, rules)
    else:
        result = evaluate_incremental(current, before, previous, rules, index)
    resolved = resolved_findings(previous, result.violations)
    _recompute(db, session, paper, before, current, rules, result, sources={index: "manual"},
               summary="已还原原稿段落" if request.revert else "已手动调整段落")
    _write_copy(db, session, data)
    db.flush()
    local = [issue for issue in session.current_violations if (
        issue["location"].get("paragraph_index") == index or index in issue["location"].get("paragraph_indices", [])
    )]
    return ParagraphEditResponse(
        paragraph=current.paragraphs[index], paragraph_violations=local, resolved_count=resolved,
        remaining_count=len(local), **{key: getattr(session, key) for key in (
            "verdict", "score", "error_count", "warning_count", "rulebook", "changes", "modified_paragraphs", "version",
        )},
    )


def _valid_name(name):
    if re.search(r"[\\/\x00-\x1f\x7f]", name) or name != name.strip() or Path(name).suffix.lower() != ".docx":
        raise ValueError("请输入不含路径的 .docx 文件名。")
    return name


def document_settings(db, session_id, request):
    session, paper = _get(db, session_id, lock=True)
    _editable(paper)
    rules = db.scalars(rule_items_query(session.rule_set_id)).all()
    params = _rule_params(rules, paper.file_ext)
    degree = db.get(RuleSet, session.rule_set_id).degree_level
    selected = set()
    if request.fix_page_size_a4:
        selected.add("PAGE_SIZE_A4")
    if request.fix_margins:
        selected.add("PAGE_MARGINS")
    if request.fix_headers:
        selected.update({"HEADER_FORMAT", "HEADER_DOUBLE_BORDER"})
    for code in selected:
        params.setdefault(code, FJNU_RULES_BY_CODE[code].params | (
            DOCTOR_PARAM_OVERRIDES.get(code, {}) if degree == "doctor" else {}
        ))

    before = _current(session)
    target = _valid_name(request.target_file_name) if request.target_file_name is not None else session.target_file_name
    if selected:
        docx = Document(str(_source(session, paper)))
        docx_fixer.fix_document_layout(docx, before, params, selected, degree=degree)
        data = _serialize(docx)
        current = parse_docx(data, target)
    else:
        current = before.model_copy(update={"file_name": target})
    session.target_file_name = target
    _recompute(db, session, paper, before, current, rules, evaluate(current, rules), summary="已修复文档设置")
    if selected:
        _write_copy(db, session, data)
    db.flush()
    return _detail(db, session, paper)


def _suggest_name(document, params):
    current = document.file_name
    pattern = params.get("pattern")
    if not pattern or re.fullmatch(pattern, current):
        return current
    elements = cover_elements(document.paragraphs)
    if "student_id" in elements and "author_name" in elements:
        student = re.sub(r"\s+", "", elements["student_id"][0])
        author = re.sub(r"\s+", "", elements["author_name"][0])
        candidate = f"{student}_{author}.docx"
        if len(candidate) <= 255 and re.fullmatch(pattern, candidate) and not re.search(r"[\\/\x00-\x1f\x7f]", candidate):
            return candidate
    return current


def _apply_replacements(document, ir, replacements):
    sources = {}
    elements = dict(paragraph_elements(document)) if document is not None else {}
    indexed = {p.index: p for p in ir.paragraphs}
    for change in replacements:
        if document is None:
            p = indexed[change.paragraph_index]
            p.text = change.new_text
            p.runs = [TextRunIR(text=p.text, font_name=p.font_name, font_size_pt=p.font_size_pt,
                                font_name_latin=p.font_name_latin, bold=p.bold)]
        else:
            try:
                replace_text(elements[change.paragraph_index], change.new_text)
            except (KeyError, ValueError):
                continue
        sources[change.paragraph_index] = "llm"
    return sources


def auto_fix(db, session_id, request):
    session, paper = _get(db, session_id, lock=True)
    rules = db.scalars(rule_items_query(session.rule_set_id)).all()
    params = _rule_params(rules, paper.file_ext)
    before = _current(session)
    findings = _existing_issues(session)
    selected = set(params if request.rule_codes is None else request.rule_codes)
    if selected - params.keys():
        raise ValueError("所选规则未启用或不适用于当前论文。")
    code = next(iter(selected)) if len(selected) == 1 else None
    entries = consolidate(findings, _original_violations(db, session.check_run_id), rules,
                          notes=_prior_notes(session), editable=paper.file_ext == "docx")
    instruction = request.instruction.strip() if request.instruction else None
    history = [item.instruction for item in _feedbacks(db, session.id) if item.author == "user"]
    advice = llm_advisor.advise(before, entries, params, selected, instruction=instruction, history=history)
    output = advice.output
    selected = selected - {code for code, note in output.rulebook_notes.items() if note.ignore}
    if paper.file_ext == "docx":
        docx = Document(str(_source(session, paper)))
        layout = {issue.rule_code for issue in findings if issue.rule_code in selected} & {
            "PAGE_SIZE_A4", "PAGE_MARGINS", "HEADER_FORMAT", "HEADER_DOUBLE_BORDER", "PAGE_NUMBER_STYLE",
        }
        if "HEADER_FORMAT" in layout:
            layout |= selected & {"HEADER_DOUBLE_BORDER", "PAGE_NUMBER_STYLE"}
        degree = db.get(RuleSet, session.rule_set_id).degree_level
        docx_fixer.fix_document_layout(docx, before, params, layout, degree=degree)
        docx_fixer.fix_typography(docx, before, params, selected, findings)
        sources = _apply_replacements(docx, before, output.text_replacements)
        target = _suggest_name(before, params["FILE_NAME_PATTERN"]) if "FILE_NAME_PATTERN" in selected else session.target_file_name
        data = _serialize(docx)
        current = parse_docx(data, target)
        result = evaluate(current, rules)
        if docx_fixer.add_review_comments(docx, [issue for issue in result.violations if issue.rule_code in selected]):
            data = _serialize(docx)
            current = parse_docx(data, target)
            result = evaluate(current, rules)
        session.target_file_name = target
    else:
        current = before.model_copy(deep=True)
        sources = _apply_replacements(None, current, output.text_replacements)
        summarize_document(current, text_page_ratio=before.stats.text_page_ratio)
        result = None
    if not advice.llm_used:
        sources = dict.fromkeys(sources, "rule")
    session.comparison_ready = True
    session.llm_used = advice.llm_used
    session.llm_model = settings.llm_model[:64] if advice.llm_used else None
    _recompute(db, session, paper, before, current, rules, result, sources=sources,
               summary=output.summary, notes=output.rulebook_notes,
               reasons={change.paragraph_index: change.reason for change in output.text_replacements})
    if paper.file_ext == "docx":
        _write_copy(db, session, data)
    if instruction:
        db.add(RevisionFeedback(session_id=session.id, version=session.version, author="user",
                                instruction=instruction, rule_code=code))
    db.add(RevisionFeedback(session_id=session.id, version=session.version, author="agent",
                            instruction="一键修订", summary=output.summary, rule_code=code,
                            paragraph_index=next(iter(sources)) if len(sources) == 1 else None))
    db.flush()
    return _detail(db, session, paper)


def export_pdf(db, session_id, page_mode):
    session, paper = _get(db, session_id, lock=True)
    cached = Path(session.annotated_pdf_path) if session.annotated_pdf_path else None
    if cached is not None and cached.is_file() and session.annotated_page_mode == page_mode:
        with pymupdf.open(cached) as pdf:
            count = pdf.page_count
    else:
        source = _source(session, paper)
        if paper.file_ext == "docx":
            source = convert_docx_to_pdf(source, settings.revisions_dir.resolve() / "pdf-cache")
            paragraphs = _current(session).paragraphs
        else:
            paragraphs = DocumentIR.model_validate(paper.parsed_ir).paragraphs
        target = _directory(session) / f"annotations-v{session.version}-{page_mode}-{uuid4().hex}.pdf"
        count = compile_annotated_pdf(
            source, target, [RulebookEntry.model_validate(entry) for entry in session.rulebook],
            file_name=session.target_file_name, page_mode=page_mode, paragraphs=paragraphs,
        )
        db.info.setdefault("revision_artifacts", []).append(target)
        session.annotated_pdf_path = str(target)
        session.annotated_page_mode = page_mode
        session.updated_at = datetime.now(timezone.utc)
        db.flush()
    return AnnotatedPdfExportResponse(
        annotated_pdf_ready=True, page_mode=page_mode, page_count=count,
        download_url=f"/api/v1/revisions/{session.id}/download/annotated_pdf",
    )


def download(db, session_id, kind):
    session, paper = _get(db, session_id)
    if kind == "docx":
        _editable(paper)
        return _source(session, paper), session.target_file_name
    path = Path(session.annotated_pdf_path) if session.annotated_pdf_path else None
    if path is None or not path.is_file():
        raise RevisionNotFound("请先生成批注 PDF。")
    return path, f"{Path(session.target_file_name).stem}_修订批注.pdf"
