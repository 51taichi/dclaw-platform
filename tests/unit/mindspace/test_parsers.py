# -*- coding: utf-8 -*-
"""Tests for Mindspace document text extraction adapters."""

from __future__ import annotations

import io
import zipfile

import pytest

from qwenpaw.mindspace.parsers import DocumentParseError, parse_document_bytes


def _zip(entries: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(
                name,
                content.encode("utf-8") if isinstance(content, str) else content,
            )
    return buffer.getvalue()


def test_parse_text_and_csv_documents():
    txt = parse_document_bytes(
        name="notes.txt",
        source_type="txt",
        content="Mercury launch policy".encode("utf-8"),
    )
    csv = parse_document_bytes(
        name="sheet.csv",
        source_type="csv",
        content="name,value\nMercury,approved\n".encode("utf-8"),
    )

    assert "Mercury launch policy" in txt.text
    assert "Row 2: Mercury | approved" in csv.text


def test_parse_docx_text_from_openxml():
    content = _zip(
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Enterprise handbook</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        }
    )

    parsed = parse_document_bytes(name="handbook.docx", source_type="docx", content=content)

    assert "Enterprise handbook" in parsed.text


def test_parse_pptx_text_from_slides():
    content = _zip(
        {
            "ppt/slides/slide1.xml": """
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Q3 roadmap</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
            </p:sld>
            """,
        }
    )

    parsed = parse_document_bytes(name="roadmap.pptx", source_type="pptx", content=content)

    assert "Slide 1" in parsed.text
    assert "Q3 roadmap" in parsed.text


def test_parse_xlsx_text_from_shared_strings():
    content = _zip(
        {
            "xl/sharedStrings.xml": """
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <si><t>Project</t></si><si><t>Mercury</t></si>
            </sst>
            """,
            "xl/worksheets/sheet1.xml": """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
              </sheetData>
            </worksheet>
            """,
        }
    )

    parsed = parse_document_bytes(name="projects.xlsx", source_type="xlsx", content=content)

    assert "Sheet 1" in parsed.text
    assert "A1=Project" in parsed.text
    assert "B1=Mercury" in parsed.text


def test_parse_pdf_text_operands():
    content = b"%PDF-1.4\nstream\nBT (Mercury approval) Tj ET\nendstream\n%%EOF"

    parsed = parse_document_bytes(name="approval.pdf", source_type="pdf", content=content)

    assert "Mercury approval" in parsed.text


def test_image_without_ocr_fails_closed():
    with pytest.raises(DocumentParseError, match="OCR|Image"):
        parse_document_bytes(
            name="image.png",
            source_type="png",
            content=b"not-really-an-image",
            mime_type="image/png",
        )
