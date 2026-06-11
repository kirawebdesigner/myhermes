"""Document text extraction for Telegram uploads."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any


@dataclass
class ExtractedDocument:
    filename: str
    mime_type: str | None
    text: str
    status: str = "ok"
    detail: str | None = None


def extract_document_text(filename: str, content: bytes, *, mime_type: str | None = None) -> ExtractedDocument:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf" or mime_type == "application/pdf":
            return ExtractedDocument(filename, mime_type, _extract_pdf(content))
        if suffix == ".docx" or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return ExtractedDocument(filename, mime_type, _extract_docx(content))
        if suffix in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css"}:
            return ExtractedDocument(filename, mime_type, content.decode("utf-8", errors="replace"))
    except Exception as exc:
        return ExtractedDocument(filename, mime_type, "", status="failed", detail=str(exc))
    return ExtractedDocument(
        filename,
        mime_type,
        "",
        status="unsupported",
        detail="Supported text extraction: PDF, DOCX, TXT, Markdown, CSV, JSON, YAML, and source files.",
    )


def document_memory_body(document: ExtractedDocument, *, max_chars: int = 12000) -> str:
    text = document.text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Truncated for memory indexing.]"
    return (
        f"Filename: {document.filename}\n"
        f"MIME type: {document.mime_type or 'unknown'}\n"
        f"Extraction status: {document.status}\n"
        f"Detail: {document.detail or 'none'}\n\n"
        "## Extracted Text\n\n"
        f"{text or '[No extractable text found.]'}"
    )


def document_summary(document: ExtractedDocument, *, max_chars: int = 700) -> str:
    text = " ".join(document.text.split())
    if not text:
        return document.detail or "No extractable text found."
    return text[:max_chars]


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [(page.extract_text() or "").strip() for page in reader.pages[:25]]
    return "\n\n".join(page for page in pages if page)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(BytesIO(content))
    paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
    return "\n\n".join(paragraphs)
