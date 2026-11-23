"""Render source PDF pages with a XeLaTeX annotation margin."""
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unicodedata

import pymupdf

from app.config import settings
from app.engine.utils import mm_to_pt, pt_to_mm
from app.revisions.consolidator import select_pdf_annotations
from app.schemas.revisions import AnchorLocation

_PAPER_MM = 297
_SOURCE_MM = 210
_CARD_LEFT = 215
_CARD_GAP = 46
_CONTROL = {"Cc", "Cf", "Cs"}
_ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
    "#": r"\#", "%": r"\%", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}", "_": r"\_",
}


class ExportError(RuntimeError):
    pass


def latex_escape(value):
    return "".join(_ESCAPES.get(char, char) for char in str(value)
                   if unicodedata.category(char) not in _CONTROL or char in "\t\r\n").replace(
                       "\t", " ").replace("\r", " ").replace("\n", " ")


def _execute(command, directory, label, timeout):
    try:
        return subprocess.run(command, cwd=directory, capture_output=True, check=True, timeout=timeout)
    except (FileNotFoundError, PermissionError) as exc:
        raise ExportError(f"无法执行 {label}。请检查服务端工具路径。") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"{label} 运行超时。") from exc
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout + b"\n" + exc.stderr).decode(errors="replace")
        lines = output.splitlines()
        useful = next((line for line in lines if line.startswith(("!", "Error"))), "")
        raise ExportError(f"{label} 未成功生成 PDF。{useful[:230]}") from exc


def _pdf_page_count(path):
    try:
        with pymupdf.open(path, filetype="pdf") as pdf:
            if pdf.needs_pass or not pdf.page_count:
                raise ExportError("PDF 无法打开或没有页面。")
            return pdf.page_count
    except (RuntimeError, ValueError, OSError) as exc:
        raise ExportError("输出文件无法作为 PDF 打开。") from exc


def convert_docx_to_pdf(docx_path: Path, cache_dir: Path) -> Path:
    data = docx_path.read_bytes()
    digest = sha256(data).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{digest}.pdf"
    if cached.is_file():
        return cached
    with TemporaryDirectory(prefix="office-", dir=cache_dir) as temporary:
        working = Path(temporary).resolve()
        source = working / "source.docx"
        source.write_bytes(data)
        profile = (working / "profile").as_uri()
        _execute([settings.soffice_bin, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf",
                  "--outdir", str(working), str(source)], working, "LibreOffice", 120)
        rendered = working / "source.pdf"
        _pdf_page_count(rendered)
        rendered.replace(cached)
    return cached


def _normalized(value):
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold() if not char.isspace())


class _TextIndex:
    def __init__(self, pdf):
        self.pages = []
        for page in pdf:
            parts, ends, boxes = [], [], []
            length = 0
            for *points, word, _, _, _ in page.get_text("words", sort=True):
                text = _normalized(word)
                if not text:
                    continue
                parts.append(text)
                length += len(text)
                ends.append(length)
                boxes.append(pymupdf.Rect(points) * page.rotation_matrix)
            self.pages.append(("".join(parts), ends, boxes))

    def find(self, text, hinted_page=None, minimum_page=1):
        text = _normalized(text)[:92]
        if not text:
            return None
        order = list(range(minimum_page, len(self.pages) + 1)) + list(range(1, minimum_page))
        if hinted_page in order:
            order.remove(hinted_page)
            order.insert(0, hinted_page)
        lengths = list(dict.fromkeys((len(text), min(len(text), 35), min(len(text), 15))))
        for length in lengths:
            if length < 3 and hinted_page is None:
                continue
            needle = text[:length]
            for page in order:
                body, ends, boxes = self.pages[page - 1]
                start = body.find(needle)
                if start < 0:
                    continue
                first, stop = bisect_right(ends, start), bisect_right(ends, start + length - 1) + 1
                box = pymupdf.Rect(boxes[first])
                for other in boxes[first + 1:stop]:
                    box |= other
                return page, list(box)
        return None


def _locate(rulebook, pdf, paragraphs):
    page_count = pdf.page_count
    needs_lookup = any(a.bbox is None and (a.excerpt or a.paragraph_index is not None)
                       for entry in rulebook for a in entry.representative_anchors)
    index = _TextIndex(pdf) if needs_lookup else None
    by_index = {p.index: p for p in paragraphs}
    located = []
    for entry in rulebook:
        anchors = []
        minimum_page = 1
        for anchor in entry.representative_anchors:
            page = anchor.page if anchor.page and 1 <= anchor.page <= page_count else None
            if page and anchor.bbox:
                anchors.append(anchor)
                minimum_page = page
                continue
            paragraph = by_index.get(anchor.paragraph_index)
            excerpt = (paragraph.text if paragraph else None) or anchor.excerpt
            found = index.find(excerpt, page, minimum_page) if index and excerpt else None
            if found:
                minimum_page, bbox = found
                anchors.append(anchor.model_copy(update={"page": minimum_page, "bbox": bbox}))
            else:
                anchors.append(anchor.model_copy(update={"page": page or minimum_page, "bbox": None}))
        if not anchors:
            anchors = [AnchorLocation(page=entry.affected_pages[0] if entry.affected_pages
                                      and 1 <= entry.affected_pages[0] <= page_count else 1)]
        located.append(entry.model_copy(update={"representative_anchors": anchors}))
    return located


def _picture_layout(rect):
    scale = min(mm_to_pt(_SOURCE_MM) / rect.width, mm_to_pt(_PAPER_MM) / rect.height)
    width, height = pt_to_mm(rect.width * scale), pt_to_mm(rect.height * scale)
    return scale, (_SOURCE_MM - width) / 2, (_PAPER_MM - height) / 2, width, height


def _page_overlay(annotations, layout):
    if not annotations:
        return ""
    scale, left, top, width, height = layout
    targets = []
    for slot, item in enumerate(annotations):
        bbox = item.anchor.bbox
        if bbox:
            x = left + min(width, max(0, pt_to_mm(bbox[2] * scale)))
            y = top + min(height, max(0, pt_to_mm((bbox[1] + bbox[3]) / 2 * scale)))
        else:
            x, y = left + width - 1, 40 + slot * _CARD_GAP
        targets.append((y, x, item))
    targets.sort(key=lambda target: target[0])
    cards, leaders = [], []
    last = 12 - _CARD_GAP
    for i, (y, x, item) in enumerate(targets):
        upper = _PAPER_MM - 18 - (len(targets) - 1 - i) * _CARD_GAP
        center = min(upper, max(last + _CARD_GAP, y))
        last = center
        entry = item.entry
        label, color = ("FIXED", "green!55!black") if entry.status == "fixed" else (
            ("WARN", "orange!90!black") if entry.severity == "warning" else ("ERROR", "red!70!black")
        )
        cards.append(
            rf"\node[anchor=west,align=left,text width=71mm,minimum height=19mm,inner sep=2mm,"
            rf"rounded corners=2mm,draw={color},fill=white,text=black,font=\small] "
            rf"at ({_CARD_LEFT},{center:.2f}) {{\textcolor{{{color}}}{{\textbf{{{label}}}}} "
            + latex_escape(entry.rule_name[:32]) + r"\\ " + latex_escape(entry.bubble_note[:60]) + "};"
        )
        leaders.append(
            rf"\draw[-{{Stealth[length=2mm]}},semithick,{color}] "
            rf"({_CARD_LEFT},{center:.2f}) -- (212,{center:.2f}) -- ({x:.2f},{y:.2f});"
        )
    return (r"\begin{tikzpicture}[remember picture,overlay,x=1mm,y=-1mm]"
            r"\begin{scope}[shift={(current page.north west)}]"
            + "\n".join(leaders + cards) + r"\end{scope}\end{tikzpicture}")


def _tex(pdf, rulebook, annotations, file_name, page_mode):
    by_page = defaultdict(list)
    for item in annotations:
        by_page[item.anchor.page].append(item)
    source_pages = sorted(by_page) if page_mode == "issues_only" else range(1, pdf.page_count + 1)
    open_count = sum(entry.total_count for entry in rulebook if entry.status == "open")
    fixed_count = sum(entry.original_count for entry in rulebook if entry.status == "fixed")
    text = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[paperwidth=297mm,paperheight=297mm,margin=18mm]{geometry}",
        r"\usepackage{fontspec,xeCJK,pdfpages,tikz}",
        r"\usetikzlibrary{arrows.meta}",
        r"\IfFontExistsTF{Songti SC}{\setCJKmainfont{Songti SC}}{\setCJKmainfont{STSong}}",
        r"\pagestyle{empty}\parindent=0pt",
        r"\begin{document}",
        r"{\Huge 论文修订批注}\par\vspace{8mm}",
        r"{\Large " + latex_escape(file_name[:190]) + r"}\par\vspace{4mm}",
        f"原文 {pdf.page_count} 页，附录 {len(source_pages)} 页，标注 {len(annotations)} 处。"
        f"当前待处理 {open_count} 条，已修复 {fixed_count} 条。"
        + r"\par\vspace{7mm}",
    ]
    grouped = defaultdict(lambda: [0, 0])
    for entry in rulebook:
        stats = grouped[entry.rule_name]
        stats[0] += entry.total_count
        stats[1] += entry.original_count
    for name, (current, before) in list(grouped.items())[:22]:
        text.append(r"\textbf{" + latex_escape(name[:60]) + rf"}}\quad 原 {before} 条，现 {current} 条。\par")
    if not grouped:
        text.append(r"当前检测没有违规记录。\par")
    text.append(r"\clearpage")
    for page in source_pages:
        rect = pdf[page - 1].rect
        layout = _picture_layout(rect)
        scale, left, _, width, _ = layout
        horizontal_offset = left + width / 2 - _PAPER_MM / 2
        overlay = _page_overlay(by_page[page], layout)
        text.append(
            rf"\includepdf[pages={{{page}}},noautoscale,scale={scale:.7f},"
            rf"offset={{{horizontal_offset:.4f}mm 0mm}},pagecommand={{{overlay}}}]{{source.pdf}}"
        )
    text.append(r"\end{document}")
    return "\n".join(text), len(source_pages) + 1


def compile_annotated_pdf(source_pdf, output_path, rulebook, *, file_name,
                          page_mode="issues_only", paragraphs=()):
    if page_mode not in {"issues_only", "full"}:
        raise ValueError("不支持的 PDF 导出模式。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="xelatex-", dir=output_path.parent) as temporary:
        working = Path(temporary).resolve()
        source = working / "source.pdf"
        shutil.copyfile(source_pdf, source)
        with pymupdf.open(source, filetype="pdf") as pdf:
            # xdvipdfmx requires a content stream even on a genuinely blank included page.
            blank = [page.number for page in pdf if not page.get_contents()]
            for page_index in blank:
                pdf[page_index].draw_rect((0, 0, 1, 1), color=None, fill=(1, 1, 1), fill_opacity=0)
            if blank:
                pdf.saveIncr()
            located = _locate(rulebook, pdf, paragraphs)
            annotations = select_pdf_annotations(located)
            template, expected = _tex(pdf, located, annotations, file_name, page_mode)
        (working / "annotation.tex").write_text(template, encoding="utf-8")
        command = [settings.xelatex_bin, "-interaction=nonstopmode", "-halt-on-error",
                   "-no-shell-escape", "annotation.tex"]
        _execute(command, working, "XeLaTeX", 120)
        if annotations:
            # TikZ resolves remembered page coordinates from the previous pass.
            _execute(command, working, "XeLaTeX", 120)
        compiled = working / "annotation.pdf"
        count = _pdf_page_count(compiled)
        if count != expected:
            raise ExportError(f"批注 PDF 页数不符（预期 {expected}，实际 {count}）。")
        compiled.replace(output_path)
    return count
