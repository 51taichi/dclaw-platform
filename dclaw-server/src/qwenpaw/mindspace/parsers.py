# -*- coding: utf-8 -*-
"""Document text extraction adapters for Mindspace ingestion."""

from __future__ import annotations

import csv
import html
import io
import re
import zlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree


class DocumentParseError(RuntimeError):
    """Raised when no truthful text can be extracted from a document."""


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    source_type: str
    diagnostics: str = ""


TEXT_TYPES = {"txt", "md", "markdown", "csv"}
OFFICE_TYPES = {"docx", "pptx", "xlsx"}
IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "tif"}


def source_type_from_name(name: str, fallback: str = "txt") -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    if suffix == "markdown":
        return "md"
    if suffix in {
        "txt",
        "md",
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "xls",
        "csv",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "bmp",
        "gif",
        "tiff",
        "tif",
    }:
        return "xlsx" if suffix == "xls" else suffix
    return fallback


def parse_document_bytes(
    *,
    name: str,
    source_type: str,
    content: bytes,
    mime_type: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ParsedDocument:
    normalized_type = (source_type or source_type_from_name(name)).lower()
    if normalized_type == "markdown":
        normalized_type = "md"
    if normalized_type == "xls":
        normalized_type = "xlsx"

    if normalized_type in TEXT_TYPES:
        text = _decode_text(content)
        if normalized_type == "csv":
            text = _csv_to_text(text)
        return _require_text(text, normalized_type)

    if normalized_type == "pdf":
        return _require_text(
            _extract_pdf_text(content, progress_callback=progress_callback),
            normalized_type,
        )

    if normalized_type == "docx":
        return _require_text(_extract_docx_text(content), normalized_type)

    if normalized_type == "pptx":
        return _require_text(_extract_pptx_text(content), normalized_type)

    if normalized_type == "xlsx":
        return _require_text(_extract_xlsx_text(content), normalized_type)

    if normalized_type in IMAGE_TYPES:
        return _extract_image_text(content, normalized_type, mime_type)

    raise DocumentParseError(f"{normalized_type.upper()} parsing is not supported yet.")


def _require_text(text: str, source_type: str) -> ParsedDocument:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not normalized:
        raise DocumentParseError(
            f"{source_type.upper()} did not contain extractable text."
        )
    return ParsedDocument(text=normalized, source_type=source_type)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("Text file encoding is not supported.")


def _csv_to_text(text: str) -> str:
    rows: list[str] = []
    reader = csv.reader(io.StringIO(text))
    for row_index, row in enumerate(reader, start=1):
        cells = [cell.strip() for cell in row if cell.strip()]
        if cells:
            rows.append(f"Row {row_index}: " + " | ".join(cells))
    return "\n".join(rows)


def _extract_docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as docx:
        names = [
            "word/document.xml",
            *sorted(
                name
                for name in docx.namelist()
                if name.startswith("word/header") or name.startswith("word/footer")
            ),
        ]
        parts = []
        for name in names:
            if name in docx.namelist():
                parts.append(_xml_text(docx.read(name)))
        return "\n\n".join(part for part in parts if part.strip())


def _extract_pptx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as pptx:
        slide_names = sorted(
            name
            for name in pptx.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        notes_names = sorted(
            name
            for name in pptx.namelist()
            if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")
        )
        parts = []
        for index, name in enumerate(slide_names, start=1):
            text = _xml_text(pptx.read(name))
            if text.strip():
                parts.append(f"Slide {index}\n{text}")
        for index, name in enumerate(notes_names, start=1):
            text = _xml_text(pptx.read(name))
            if text.strip():
                parts.append(f"Notes {index}\n{text}")
        return "\n\n".join(parts)


def _extract_xlsx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as xlsx:
        shared_strings = _xlsx_shared_strings(xlsx)
        sheet_names = sorted(
            name
            for name in xlsx.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        parts = []
        for sheet_index, name in enumerate(sheet_names, start=1):
            rows = _xlsx_sheet_rows(xlsx.read(name), shared_strings)
            if rows:
                parts.append(
                    f"Sheet {sheet_index}\n"
                    + "\n".join(
                        f"Row {row_index}: " + " | ".join(cells)
                        for row_index, cells in rows
                    )
                )
        return "\n\n".join(parts)


def _extract_pdf_text(
    content: bytes,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    parser_error: Exception | None = None
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(content))
        total_pages = max(1, len(reader.pages))
        page_text: list[str] = []
        for page_index, page in enumerate(reader.pages, start=1):
            page_text.append(page.extract_text() or "")
            if progress_callback:
                progress_callback(page_index, total_pages)
        text = "\n\n".join(page_text)
        if text.strip():
            return text
    except Exception as exc:
        parser_error = exc

    # Raw stream scanning exists only for tiny/simple compatibility fixtures.
    # On production-size image/vector PDFs it can decompress huge image streams
    # and monopolize a worker without page-level progress.
    if len(content) > 2 * 1024 * 1024:
        detail = (
            f" ({type(parser_error).__name__}: {parser_error})"
            if parser_error
            else ""
        )
        raise DocumentParseError(
            "Large PDF extraction requires the Poppler/OCR path"
            + detail[:300]
            + "."
        )

    parts: list[str] = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", content, re.S):
        for candidate in _pdf_stream_candidates(stream):
            parts.extend(_pdf_text_operands(candidate))
    if parts:
        return "\n".join(parts)

    plain = _decode_pdf_plaintext(content)
    if plain.strip():
        return plain
    raise DocumentParseError(
        "PDF text extraction needs selectable text or an installed PDF parser/OCR."
    )


def _pdf_stream_candidates(stream: bytes) -> list[bytes]:
    candidates = [stream]
    try:
        candidates.append(zlib.decompress(stream.strip()))
    except Exception:
        pass
    return candidates


def _pdf_text_operands(stream: bytes) -> list[str]:
    text: list[str] = []
    for raw in re.findall(rb"\(((?:\\.|[^\\)])*)\)\s*Tj", stream):
        text.append(_decode_pdf_string(raw))
    for array in re.findall(rb"\[((?:.|\n)*?)\]\s*TJ", stream):
        pieces = re.findall(rb"\(((?:\\.|[^\\)])*)\)", array)
        if pieces:
            text.append("".join(_decode_pdf_string(piece) for piece in pieces))
    return [part for part in text if part.strip()]


def _decode_pdf_string(raw: bytes) -> str:
    escaped = (
        raw.replace(rb"\(", b"(")
        .replace(rb"\)", b")")
        .replace(rb"\\", b"\\")
        .replace(rb"\n", b"\n")
        .replace(rb"\r", b"\r")
        .replace(rb"\t", b"\t")
    )
    return escaped.decode("utf-8", errors="ignore") or escaped.decode(
        "latin-1",
        errors="ignore",
    )


def _decode_pdf_plaintext(content: bytes) -> str:
    text = content.decode("latin-1", errors="ignore")
    runs = re.findall(r"[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff ,.;:!?_\-/]{4,}", text)
    filtered = [
        run.strip()
        for run in runs
        if not run.startswith(("/Type", "/Filter", "obj", "endobj"))
    ]
    return "\n".join(filtered)


def _extract_image_text(
    content: bytes,
    source_type: str,
    mime_type: str | None,
) -> ParsedDocument:
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        return _require_text(text, source_type)
    except ImportError as exc:
        raise DocumentParseError(
            "Image OCR is not configured. Install pytesseract and a Tesseract OCR runtime."
        ) from exc
    except Exception as exc:
        raise DocumentParseError(f"Image OCR failed: {exc}") from exc


def _xml_text(content: bytes) -> str:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return ""
    values = []
    for node in root.iter():
        if node.text and node.text.strip():
            values.append(html.unescape(node.text.strip()))
    return "\n".join(values)


def _xlsx_shared_strings(xlsx: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in xlsx.namelist():
        return []
    try:
        root = ElementTree.fromstring(xlsx.read("xl/sharedStrings.xml"))
    except ElementTree.ParseError:
        return []
    values = []
    for item in root:
        parts = [
            node.text.strip()
            for node in item.iter()
            if node.tag.endswith("}t") and node.text and node.text.strip()
        ]
        values.append("".join(parts))
    return values


def _xlsx_sheet_rows(
    content: bytes,
    shared_strings: list[str],
) -> list[tuple[int, list[str]]]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []
    rows: list[tuple[int, list[str]]] = []
    for row in root.iter():
        if not row.tag.endswith("}row"):
            continue
        row_number = int(row.attrib.get("r") or len(rows) + 1)
        cells: list[str] = []
        for cell in row:
            if not cell.tag.endswith("}c"):
                continue
            value = _xlsx_cell_value(cell, shared_strings)
            if value:
                ref = cell.attrib.get("r", "")
                cells.append(f"{ref}={value}" if ref else value)
        if cells:
            rows.append((row_number, cells))
    return rows


def _xlsx_cell_value(node: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = node.attrib.get("t")
    inline_text: list[str] = []
    value = ""
    for child in node.iter():
        if child.tag.endswith("}t") and child.text:
            inline_text.append(child.text.strip())
        if child.tag.endswith("}v") and child.text:
            value = child.text.strip()
    if inline_text:
        return "".join(inline_text)
    if cell_type == "s" and value:
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value
    return value
