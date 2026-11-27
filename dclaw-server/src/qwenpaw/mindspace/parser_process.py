# -*- coding: utf-8 -*-
"""Hard-isolated document parsing for knowledge ingestion.

PDF extraction is intentionally executed in a disposable child process. A
thread is not enough here: pure-Python PDF parsers can monopolize the GIL and a
stuck thread cannot be forcefully terminated. The parent monitors page
progress and can terminate the child without taking the API service down.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .pdf_parser import PdfPathParserConfig, parse_pdf_path
from .parsers import DocumentParseError, ParsedDocument, parse_document_bytes

ParseProgressCallback = Callable[[int, int], None]


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class ParserProcessConfig:
    """Resource and time boundaries for one parser child process."""

    total_timeout_seconds: float = 180.0
    page_stall_timeout_seconds: float = 45.0
    poll_interval_seconds: float = 0.2
    max_memory_mb: int = 768
    max_cpu_seconds: int = 180
    pdf_text_timeout_seconds: float = 30.0
    pdf_ocr_enabled: bool = True
    pdf_ocr_min_chars: int = 80
    pdf_ocr_concurrency: int = 2
    pdf_ocr_page_timeout_seconds: float = 30.0
    pdf_ocr_render_max_pixels: int = 2000
    pdf_ocr_language: str = "chi_sim+eng"
    pdf_ocr_min_confidence: float = 50.0

    @classmethod
    def from_env(cls) -> "ParserProcessConfig":
        total_timeout = _env_float(
            "QWENPAW_KNOWLEDGE_PARSE_TIMEOUT_SECONDS",
            180.0,
            minimum=5.0,
        )
        return cls(
            total_timeout_seconds=total_timeout,
            page_stall_timeout_seconds=_env_float(
                "QWENPAW_KNOWLEDGE_PDF_PAGE_TIMEOUT_SECONDS",
                45.0,
                minimum=5.0,
            ),
            poll_interval_seconds=_env_float(
                "QWENPAW_KNOWLEDGE_PARSE_POLL_SECONDS",
                0.2,
                minimum=0.02,
            ),
            max_memory_mb=_env_int(
                "QWENPAW_KNOWLEDGE_PARSE_MAX_MEMORY_MB",
                768,
                minimum=0,
            ),
            max_cpu_seconds=_env_int(
                "QWENPAW_KNOWLEDGE_PARSE_MAX_CPU_SECONDS",
                max(5, int(total_timeout)),
                minimum=0,
            ),
            pdf_text_timeout_seconds=_env_float(
                "QWENPAW_KNOWLEDGE_PDF_TEXT_TIMEOUT_SECONDS",
                30.0,
                minimum=5.0,
            ),
            pdf_ocr_enabled=_env_bool(
                "QWENPAW_KNOWLEDGE_PDF_OCR_ENABLED",
                True,
            ),
            pdf_ocr_min_chars=_env_int(
                "QWENPAW_KNOWLEDGE_PDF_OCR_MIN_CHARS",
                80,
                minimum=0,
            ),
            pdf_ocr_concurrency=_env_int(
                "QWENPAW_KNOWLEDGE_PDF_OCR_CONCURRENCY",
                2,
                minimum=1,
            ),
            pdf_ocr_page_timeout_seconds=_env_float(
                "QWENPAW_KNOWLEDGE_PDF_OCR_PAGE_TIMEOUT_SECONDS",
                30.0,
                minimum=5.0,
            ),
            pdf_ocr_render_max_pixels=_env_int(
                "QWENPAW_KNOWLEDGE_PDF_OCR_RENDER_MAX_PIXELS",
                2000,
                minimum=800,
            ),
            pdf_ocr_language=(
                os.getenv(
                    "QWENPAW_KNOWLEDGE_PDF_OCR_LANGUAGE",
                    "chi_sim+eng",
                ).strip()
                or "chi_sim+eng"
            ),
            pdf_ocr_min_confidence=_env_float(
                "QWENPAW_KNOWLEDGE_PDF_OCR_MIN_CONFIDENCE",
                50.0,
                minimum=0.0,
            ),
        )


def _apply_resource_limits(config: ParserProcessConfig) -> None:
    """Apply best-effort Unix resource limits inside the parser process."""
    try:
        import resource
    except ImportError:  # pragma: no cover - non-Unix platforms
        return

    if config.max_memory_mb > 0:
        memory_bytes = config.max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (OSError, ValueError):
            pass
    if config.max_cpu_seconds > 0:
        hard_limit = config.max_cpu_seconds + 2
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (config.max_cpu_seconds, hard_limit),
            )
        except (OSError, ValueError):
            pass


def _safe_send(connection: Any, payload: dict[str, Any]) -> None:
    try:
        connection.send(payload)
    except (BrokenPipeError, EOFError, OSError):
        pass


def _isolated_parser_worker(
    connection: Any,
    path_value: str,
    name: str,
    source_type: str,
    mime_type: str | None,
    config_values: dict[str, Any],
) -> None:
    """Child-process entrypoint. It must remain top-level for spawn mode."""
    config = ParserProcessConfig(**config_values)
    try:
        os.setsid()
    except (AttributeError, OSError):
        pass
    _apply_resource_limits(config)

    def emit_progress(completed: int, total: int) -> None:
        _safe_send(
            connection,
            {
                "kind": "progress",
                "completed": int(completed),
                "total": max(1, int(total)),
            },
        )

    try:
        normalized_type = str(source_type or "").strip().lower()
        if normalized_type == "pdf":
            parsed = parse_pdf_path(
                Path(path_value),
                progress_callback=emit_progress,
                config=PdfPathParserConfig(
                    text_timeout_seconds=config.pdf_text_timeout_seconds,
                    ocr_enabled=config.pdf_ocr_enabled,
                    ocr_min_chars=config.pdf_ocr_min_chars,
                    ocr_concurrency=config.pdf_ocr_concurrency,
                    ocr_page_timeout_seconds=(
                        config.pdf_ocr_page_timeout_seconds
                    ),
                    ocr_render_max_pixels=config.pdf_ocr_render_max_pixels,
                    ocr_language=config.pdf_ocr_language,
                    ocr_min_confidence=config.pdf_ocr_min_confidence,
                ),
            )
        else:
            content = Path(path_value).read_bytes()
            parsed = parse_document_bytes(
                name=name,
                source_type=source_type,
                content=content,
                mime_type=mime_type,
                progress_callback=emit_progress,
            )
        _safe_send(
            connection,
            {
                "kind": "result",
                "text": parsed.text,
                "source_type": parsed.source_type,
                "diagnostics": parsed.diagnostics,
            },
        )
    except BaseException as exc:  # child boundary must serialize every failure
        _safe_send(
            connection,
            {
                "kind": "error",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _terminate_process(process: mp.Process) -> None:
    if not process.is_alive():
        process.join(timeout=0.2)
        return
    used_process_group = False
    try:
        process_group = os.getpgid(process.pid)
        if process_group == process.pid:
            os.killpg(process_group, signal.SIGTERM)
            used_process_group = True
    except (AttributeError, OSError, ProcessLookupError):
        pass
    if not used_process_group:
        process.terminate()
    process.join(timeout=1.0)
    if process.is_alive() and hasattr(process, "kill"):
        if used_process_group:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (AttributeError, OSError, ProcessLookupError):
                process.kill()
        else:
            process.kill()
        process.join(timeout=1.0)


def parse_document_path_isolated(
    *,
    path: Path,
    name: str,
    source_type: str,
    mime_type: str | None = None,
    progress_callback: ParseProgressCallback | None = None,
    config: ParserProcessConfig | None = None,
    _worker_target: Callable[..., None] = _isolated_parser_worker,
    _start_method: str = "spawn",
) -> ParsedDocument:
    """Parse a document in a killable process with progress and hard limits."""
    resolved_config = config or ParserProcessConfig.from_env()
    context = mp.get_context(_start_method)
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_target,
        args=(
            sender,
            str(Path(path).resolve()),
            name,
            source_type,
            mime_type,
            asdict(resolved_config),
        ),
        name=f"knowledge-parser-{Path(path).stem[:32]}",
        daemon=True,
    )
    started_at = time.monotonic()
    last_progress_at = started_at
    normalized_type = str(source_type or "").strip().lower()
    process.start()
    sender.close()

    try:
        while True:
            now = time.monotonic()
            if now - started_at > resolved_config.total_timeout_seconds:
                _terminate_process(process)
                raise DocumentParseError(
                    "Document parsing timed out after "
                    f"{resolved_config.total_timeout_seconds:.0f} seconds."
                )
            if (
                normalized_type == "pdf"
                and now - last_progress_at
                > resolved_config.page_stall_timeout_seconds
            ):
                _terminate_process(process)
                raise DocumentParseError(
                    "PDF page parsing made no progress for "
                    f"{resolved_config.page_stall_timeout_seconds:.0f} seconds."
                )

            if receiver.poll(resolved_config.poll_interval_seconds):
                try:
                    message = receiver.recv()
                except EOFError:
                    message = None
                if isinstance(message, dict):
                    kind = message.get("kind")
                    if kind == "progress":
                        last_progress_at = time.monotonic()
                        if progress_callback:
                            progress_callback(
                                int(message.get("completed") or 0),
                                max(1, int(message.get("total") or 1)),
                            )
                    elif kind == "result":
                        process.join(timeout=1.0)
                        return ParsedDocument(
                            text=str(message.get("text") or ""),
                            source_type=str(message.get("source_type") or source_type),
                            diagnostics=str(message.get("diagnostics") or ""),
                        )
                    elif kind == "error":
                        process.join(timeout=1.0)
                        raise DocumentParseError(
                            str(message.get("error") or "Document parsing failed.")
                        )

            if not process.is_alive():
                if receiver.poll():
                    continue
                raise DocumentParseError(
                    "Document parser process exited unexpectedly "
                    f"(exit code {process.exitcode})."
                )
    finally:
        _terminate_process(process)
        receiver.close()
