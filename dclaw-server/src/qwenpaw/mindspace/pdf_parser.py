# -*- coding: utf-8 -*-
"""Fast, truthful PDF extraction with selective OCR.

Poppler is the primary extractor because it handles production PDFs without
walking every drawing operator in Python. Pages with too little selectable
text are rendered and OCRed individually so Illustrator/scanned documents do
not silently produce an incomplete knowledge index.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .parsers import DocumentParseError, ParsedDocument

ParseProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class PdfPathParserConfig:
    """Runtime limits for Poppler extraction and selective page OCR."""

    text_timeout_seconds: float = 30.0
    ocr_enabled: bool = True
    ocr_min_chars: int = 80
    ocr_concurrency: int = 2
    ocr_page_timeout_seconds: float = 30.0
    ocr_render_max_pixels: int = 2000
    ocr_language: str = "chi_sim+eng"
    ocr_min_confidence: float = 50.0


@dataclass(frozen=True)
class _OcrPageResult:
    page_number: int
    text: str = ""
    error: str = ""


def _text_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _normalize_ocr_line(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return re.sub(
        r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])",
        "",
        normalized,
    )


def _meaningful_ocr_line(text: str) -> bool:
    if re.search(r"[\u3400-\u9fff]", text):
        return True
    compact = re.sub(r"[^A-Za-z0-9]", "", text)
    if len(compact) < 4:
        return False
    if compact.isdigit():
        return len(compact) >= 3
    return bool(re.search(r"[A-Za-z]{4,}", text) or re.search(r"\d", text))


def _parse_tesseract_tsv(tsv: str, *, min_confidence: float) -> str:
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf") or -1)
        except (TypeError, ValueError):
            confidence = -1
        if not text or confidence < min_confidence:
            continue
        key = (
            row.get("page_num") or "",
            row.get("block_num") or "",
            row.get("par_num") or "",
            row.get("line_num") or "",
        )
        lines.setdefault(key, []).append(text)
    normalized_lines = [
        _normalize_ocr_line(" ".join(words)) for words in lines.values()
    ]
    return "\n".join(
        line for line in normalized_lines if _meaningful_ocr_line(line)
    )


def _run_command(
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1.0, timeout),
        check=False,
    )


def _extract_poppler_pages(
    path: Path,
    *,
    timeout: float,
) -> tuple[list[str], str]:
    executable = shutil.which("pdftotext")
    if not executable:
        raise DocumentParseError(
            "PDF text extraction requires Poppler pdftotext, but it is not installed."
        )
    try:
        result = _run_command(
            [
                executable,
                "-enc",
                "UTF-8",
                "-layout",
                str(path),
                "-",
            ],
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocumentParseError(
            f"Poppler PDF extraction timed out after {timeout:.0f} seconds."
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:500]
        raise DocumentParseError(
            "Poppler PDF extraction failed"
            + (f": {detail}" if detail else ".")
        )

    pages = result.stdout.split("\f")
    # pdftotext terminates every page with a form feed. Remove only the final
    # sentinel so a genuinely blank last page remains represented.
    if pages and not pages[-1].strip():
        pages.pop()
    if not pages:
        pages = [""]
    return pages, (result.stderr or "").strip()


def _ocr_tools(config: PdfPathParserConfig) -> tuple[str, str]:
    renderer = shutil.which("pdftoppm")
    ocr = shutil.which("tesseract")
    if not renderer or not ocr:
        missing = [
            name
            for name, executable in (
                ("pdftoppm", renderer),
                ("tesseract", ocr),
            )
            if not executable
        ]
        raise DocumentParseError(
            "PDF contains pages without enough selectable text, but OCR is not "
            f"available. Missing runtime: {', '.join(missing)}."
        )

    languages = _run_command([ocr, "--list-langs"], timeout=10.0)
    available = {
        item.strip()
        for item in languages.stdout.splitlines()
        if item.strip() and "available languages" not in item.lower()
    }
    requested = {
        item.strip()
        for item in config.ocr_language.split("+")
        if item.strip()
    }
    missing_languages = sorted(requested - available)
    if languages.returncode != 0 or missing_languages:
        detail = ", ".join(missing_languages) or (languages.stderr or "unknown")
        raise DocumentParseError(
            "PDF OCR language data is unavailable: " + detail.strip()[:300]
        )
    return renderer, ocr


def _ocr_page(
    *,
    path: Path,
    page_number: int,
    renderer: str,
    ocr: str,
    config: PdfPathParserConfig,
) -> _OcrPageResult:
    started_at = time.monotonic()
    timeout = max(1.0, config.ocr_page_timeout_seconds)
    try:
        with tempfile.TemporaryDirectory(prefix="qwenpaw-pdf-ocr-") as directory:
            output_prefix = Path(directory) / f"page-{page_number}"
            render_result = _run_command(
                [
                    renderer,
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-singlefile",
                    "-scale-to",
                    str(max(800, config.ocr_render_max_pixels)),
                    "-png",
                    str(path),
                    str(output_prefix),
                ],
                timeout=timeout,
            )
            if render_result.returncode != 0:
                return _OcrPageResult(
                    page_number=page_number,
                    error=(render_result.stderr or "PDF page rendering failed.")[:500],
                )

            image_path = output_prefix.with_suffix(".png")
            if not image_path.exists():
                return _OcrPageResult(
                    page_number=page_number,
                    error="PDF page renderer did not create an image.",
                )
            remaining = timeout - (time.monotonic() - started_at)
            if remaining <= 0:
                return _OcrPageResult(
                    page_number=page_number,
                    error=f"OCR page timed out after {timeout:.0f} seconds.",
                )
            ocr_result = _run_command(
                [
                    ocr,
                    str(image_path),
                    "stdout",
                    "-l",
                    config.ocr_language,
                    "--psm",
                    "11",
                    "tsv",
                ],
                timeout=remaining,
            )
            if ocr_result.returncode != 0:
                return _OcrPageResult(
                    page_number=page_number,
                    error=(ocr_result.stderr or "PDF page OCR failed.")[:500],
                )
            return _OcrPageResult(
                page_number=page_number,
                text=_parse_tesseract_tsv(
                    ocr_result.stdout,
                    min_confidence=config.ocr_min_confidence,
                ),
            )
    except subprocess.TimeoutExpired:
        return _OcrPageResult(
            page_number=page_number,
            error=f"OCR page timed out after {timeout:.0f} seconds.",
        )
    except Exception as exc:
        return _OcrPageResult(
            page_number=page_number,
            error=f"{type(exc).__name__}: {exc}",
        )


def parse_pdf_path(
    path: Path,
    *,
    progress_callback: ParseProgressCallback | None = None,
    config: PdfPathParserConfig | None = None,
) -> ParsedDocument:
    """Extract one PDF with Poppler and OCR only low-text pages."""
    resolved = config or PdfPathParserConfig()
    pages, poppler_diagnostics = _extract_poppler_pages(
        Path(path),
        timeout=resolved.text_timeout_seconds,
    )
    total_pages = max(1, len(pages))
    ocr_indexes = [
        index
        for index, text in enumerate(pages)
        if _text_char_count(text) < resolved.ocr_min_chars
    ]

    if not ocr_indexes or not resolved.ocr_enabled:
        if progress_callback:
            progress_callback(total_pages, total_pages)
    else:
        renderer, ocr = _ocr_tools(resolved)
        completed = total_pages - len(ocr_indexes)
        if completed and progress_callback:
            progress_callback(completed, total_pages)

        worker_count = min(
            len(ocr_indexes),
            max(1, resolved.ocr_concurrency),
        )
        failures: list[str] = []
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="knowledge-pdf-ocr",
        ) as executor:
            futures = {
                executor.submit(
                    _ocr_page,
                    path=Path(path),
                    page_number=index + 1,
                    renderer=renderer,
                    ocr=ocr,
                    config=resolved,
                ): index
                for index in ocr_indexes
            }
            for future in as_completed(futures):
                index = futures[future]
                result = future.result()
                if _text_char_count(result.text) > _text_char_count(pages[index]):
                    pages[index] = result.text
                if result.error:
                    failures.append(f"page {result.page_number}: {result.error}")
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_pages)

        ocr_diagnostics = (
            f"OCR attempted for {len(ocr_indexes)} of {total_pages} pages."
        )
        if failures:
            ocr_diagnostics += " Failures: " + "; ".join(failures)[:1000]
        poppler_diagnostics = " ".join(
            part for part in (poppler_diagnostics, ocr_diagnostics) if part
        )

    page_sections = [
        f"Page {index}\n{text.strip()}"
        for index, text in enumerate(pages, start=1)
        if text.strip()
    ]
    extracted = "\n\n".join(page_sections).strip()
    if not extracted:
        raise DocumentParseError(
            "PDF did not contain extractable text after Poppler and OCR processing."
        )
    return ParsedDocument(
        text=extracted,
        source_type="pdf",
        diagnostics=poppler_diagnostics,
    )
