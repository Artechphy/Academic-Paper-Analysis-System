"""Store uploads by content hash and create a separate paper for each file name."""

from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import settings
from app.db.models import Paper
from app.parsers.base import ParseError, parse_document


def upload_name(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if len(name) > 255 or "\x00" in name:
        raise ValueError("文件名无效或超过 255 个字符")
    if Path(name).suffix.lower() not in {".docx", ".pdf"}:
        raise ValueError("文件扩展名须为 .docx 或 .pdf")
    return name


def _store(data: bytes, digest: str) -> Path:
    directory = settings.storage_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / digest
    if not target.is_file():
        # Publish a complete file atomically. A simultaneous upload may publish it first.
        with NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                target.hardlink_to(temporary)
            except FileExistsError:
                if not target.is_file():
                    raise
            finally:
                temporary.unlink()
    return target


def prepare_paper(data: bytes, filename: str) -> Paper:
    digest = sha256(data).hexdigest()
    path = _store(data, digest)
    paper = Paper(
        file_name=filename,
        file_ext=Path(filename).suffix[1:].lower(),
        file_size=len(data),
        sha256=digest,
        storage_path=str(path),
    )
    parse_paper(paper, data)
    return paper


def parse_paper(paper: Paper, data: bytes) -> None:
    try:
        document = parse_document(data, paper.file_name)
    except ParseError as exc:
        paper.parse_status = "failed"
        paper.parse_error = str(exc)
        paper.parsed_ir = paper.page_count = paper.detected_title = None
        return

    paper.parse_status = "success"
    paper.parse_error = None
    paper.page_count = document.page_count
    paper.detected_title = next(
        (p.text[:512] for p in document.paragraphs if p.role == "cover_title"),
        None,
    )
    paper.parsed_ir = document.model_dump(mode="json")
