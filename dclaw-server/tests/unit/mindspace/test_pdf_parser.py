# -*- coding: utf-8 -*-
"""Tests for Poppler PDF extraction and selective OCR."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from qwenpaw.mindspace.pdf_parser import PdfPathParserConfig, parse_pdf_path
from qwenpaw.mindspace.parsers import DocumentParseError, parse_document_bytes


def _completed(
    command: list[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _tsv(*words: tuple[str, float]) -> str:
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext"
    )
    rows = [header]
    for index, (word, confidence) in enumerate(words, start=1):
        rows.append(
            "\t".join(
                [
                    "5",
                    "1",
                    "1",
                    "1",
                    "1",
                    str(index),
                    str(index * 10),
                    "10",
                    "10",
                    "10",
                    str(confidence),
                    word,
                ]
            )
        )
    return "\n".join(rows)


def test_poppler_text_and_low_text_page_ocr(monkeypatch, tmp_path):
    path = tmp_path / "brochure.pdf"
    path.write_bytes(b"%PDF-test")

    def fake_which(name: str) -> str:
        return f"/usr/bin/{name}"

    def fake_run(command: list[str], **_kwargs):
        executable = Path(command[0]).name
        if executable == "pdftotext":
            return _completed(
                command,
                stdout=(
                    "Native page contains enough searchable policy text.\f\f"
                ),
            )
        if executable == "tesseract" and "--list-langs" in command:
            return _completed(
                command,
                stdout="List of available languages in /tmp\nchi_sim\neng\n",
            )
        if executable == "pdftoppm":
            Path(command[-1]).with_suffix(".png").write_bytes(b"png")
            return _completed(command)
        if executable == "tesseract":
            return _completed(
                command,
                stdout=_tsv(
                    ("第二页", 96),
                    ("OCR", 92),
                    ("正文与业务说明", 94),
                    ("xx", 12),
                ),
            )
        raise AssertionError(command)

    monkeypatch.setattr(
        "qwenpaw.mindspace.pdf_parser.shutil.which",
        fake_which,
    )
    monkeypatch.setattr(
        "qwenpaw.mindspace.pdf_parser.subprocess.run",
        fake_run,
    )
    progress: list[tuple[int, int]] = []

    parsed = parse_pdf_path(
        path,
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
        config=PdfPathParserConfig(
            ocr_min_chars=20,
            ocr_concurrency=1,
        ),
    )

    assert "Page 1" in parsed.text
    assert "Native page contains enough searchable policy text" in parsed.text
    assert "Page 2" in parsed.text
    assert "第二页 OCR 正文与业务说明" in parsed.text
    assert "OCR attempted for 1 of 2 pages" in parsed.diagnostics
    assert progress == [(1, 2), (2, 2)]


def test_low_text_pdf_fails_closed_when_ocr_runtime_is_missing(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "outlined.pdf"
    path.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        "qwenpaw.mindspace.pdf_parser.shutil.which",
        lambda name: None if name == "tesseract" else f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        "qwenpaw.mindspace.pdf_parser.subprocess.run",
        lambda command, **_kwargs: _completed(command, stdout="\f"),
    )

    with pytest.raises(DocumentParseError, match="OCR is not available"):
        parse_pdf_path(path, config=PdfPathParserConfig(ocr_min_chars=10))


def test_ocr_can_be_explicitly_disabled_for_text_pdf(monkeypatch, tmp_path):
    path = tmp_path / "text.pdf"
    path.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        "qwenpaw.mindspace.pdf_parser.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        "qwenpaw.mindspace.pdf_parser.subprocess.run",
        lambda command, **_kwargs: _completed(
            command,
            stdout="short but truthful text\f",
        ),
    )
    progress: list[tuple[int, int]] = []

    parsed = parse_pdf_path(
        path,
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
        config=PdfPathParserConfig(
            ocr_enabled=False,
            ocr_min_chars=100,
        ),
    )

    assert "short but truthful text" in parsed.text
    assert progress == [(1, 1)]


def test_large_pdf_bytes_do_not_scan_raw_image_streams():
    content = b"%PDF-1.6\n" + (b"not-a-real-content-stream" * 100_000)

    with pytest.raises(DocumentParseError, match="Poppler/OCR"):
        parse_document_bytes(
            name="large.pdf",
            source_type="pdf",
            content=content,
        )
