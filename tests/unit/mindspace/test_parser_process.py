# -*- coding: utf-8 -*-
"""Process-isolation tests for knowledge document parsing."""

from __future__ import annotations

import time

import pytest

from qwenpaw.mindspace.parser_process import (
    ParserProcessConfig,
    parse_document_path_isolated,
)
from qwenpaw.mindspace.parsers import DocumentParseError


def _test_start_method() -> str:
    return "spawn"


def _blocking_worker(connection, *_args) -> None:
    try:
        time.sleep(5)
    finally:
        connection.close()


def _progress_worker(connection, *_args) -> None:
    connection.send({"kind": "progress", "completed": 1, "total": 2})
    connection.send(
        {
            "kind": "result",
            "text": "isolated parser result",
            "source_type": "pdf",
            "diagnostics": "",
        }
    )
    connection.close()


def _config(**updates) -> ParserProcessConfig:
    values = {
        "total_timeout_seconds": 3.0,
        "page_stall_timeout_seconds": 1.0,
        "poll_interval_seconds": 0.02,
        "max_memory_mb": 0,
        "max_cpu_seconds": 0,
    }
    values.update(updates)
    return ParserProcessConfig(**values)


def test_isolated_parser_returns_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Mercury launch policy", encoding="utf-8")

    parsed = parse_document_path_isolated(
        path=path,
        name=path.name,
        source_type="txt",
        config=_config(),
        _start_method=_test_start_method(),
    )

    assert parsed.text == "Mercury launch policy"


def test_isolated_parser_forwards_page_progress(tmp_path):
    path = tmp_path / "progress.pdf"
    path.write_bytes(b"%PDF-test")
    progress = []

    parsed = parse_document_path_isolated(
        path=path,
        name=path.name,
        source_type="pdf",
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
        config=_config(),
        _worker_target=_progress_worker,
        _start_method=_test_start_method(),
    )

    assert parsed.text == "isolated parser result"
    assert progress == [(1, 2)]


def test_isolated_parser_terminates_stalled_pdf_worker(tmp_path):
    path = tmp_path / "stalled.pdf"
    path.write_bytes(b"%PDF-test")
    started_at = time.monotonic()

    with pytest.raises(DocumentParseError, match="made no progress"):
        parse_document_path_isolated(
            path=path,
            name=path.name,
            source_type="pdf",
            config=_config(
                total_timeout_seconds=2.0,
                page_stall_timeout_seconds=0.1,
            ),
            _worker_target=_blocking_worker,
            _start_method=_test_start_method(),
        )

    assert time.monotonic() - started_at < 1.5


def test_parser_process_config_reads_pdf_ocr_environment(monkeypatch):
    monkeypatch.setenv("QWENPAW_KNOWLEDGE_PDF_OCR_ENABLED", "false")
    monkeypatch.setenv("QWENPAW_KNOWLEDGE_PDF_OCR_MIN_CHARS", "120")
    monkeypatch.setenv("QWENPAW_KNOWLEDGE_PDF_OCR_CONCURRENCY", "3")
    monkeypatch.setenv(
        "QWENPAW_KNOWLEDGE_PDF_OCR_LANGUAGE",
        "chi_sim+eng",
    )
    monkeypatch.setenv(
        "QWENPAW_KNOWLEDGE_PDF_OCR_MIN_CONFIDENCE",
        "55",
    )

    config = ParserProcessConfig.from_env()

    assert config.pdf_ocr_enabled is False
    assert config.pdf_ocr_min_chars == 120
    assert config.pdf_ocr_concurrency == 3
    assert config.pdf_ocr_language == "chi_sim+eng"
    assert config.pdf_ocr_min_confidence == 55
