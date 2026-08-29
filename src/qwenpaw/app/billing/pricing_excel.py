"""Strict RMB-only XLSX import previews and exports."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Protocol
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

HEADERS = ("供应商", "模型", "分类", "计价维度", "人民币成本", "倍数", "来源状态", "验证时间")
MAX_WORKBOOK_BYTES = 5 * 1024 * 1024


class ImportRepository(Protocol):
    def record_import(self, digest: str, filename: str, actor_id: str,
                      preview: dict[str, Any]) -> dict[str, Any]: ...


class PricingExcelService:
    def __init__(self, repository: ImportRepository, *,
                 preview_builder: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.repository = repository
        self.preview_builder = preview_builder

    def preview_import(self, content: bytes, filename: str,
                       actor_id: str) -> dict[str, Any]:
        problems: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        if len(content) > MAX_WORKBOOK_BYTES:
            problems.append({"row": 0, "code": "file_too_large"})
        elif filename.lower().endswith((".xlsm", ".xltm")):
            problems.append({"row": 0, "code": "macro_not_allowed"})
        else:
            try:
                sheet = load_workbook(
                    BytesIO(content), read_only=True, data_only=False,
                ).active
                header = tuple(cell.value for cell in next(sheet.iter_rows()))
                if header != HEADERS:
                    problems.append({"row": 1, "code": "invalid_headers"})
                else:
                    seen: set[tuple[str, str, str]] = set()
                    for number, values in enumerate(
                        sheet.iter_rows(min_row=2, values_only=True), start=2,
                    ):
                        if not any(value is not None for value in values):
                            continue
                        if any(isinstance(value, str) and value.startswith("=")
                               for value in values):
                            problems.append({"row": number,
                                             "code": "formula_not_allowed"})
                            continue
                        problem, row = self._parse_row(number, values, seen)
                        if problem:
                            problems.append(problem)
                        elif row:
                            rows.append(row)
            except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError):
                problems.append({"row": 0, "code": "invalid_workbook"})
        preview = {
            "status": "blocked" if problems else "ready",
            "rows": problems if problems else rows,
            "valid_rows": rows,
        }
        digest = hashlib.sha256(content).hexdigest()
        stored = self.repository.record_import(
            digest, filename, actor_id, preview,
        )
        return {"id": stored["id"], **preview}

    @staticmethod
    def _parse_row(number: int, values: tuple[Any, ...],
                   seen: set[tuple[str, str, str]]):
        provider, model, category, unit, cost, multiplier, status, verified = values
        key = (str(provider).strip(), str(model).strip(), str(unit).strip())
        if key in seen:
            return {"row": number, "code": "duplicate_key"}, None
        seen.add(key)
        try:
            cost_value, multiplier_value = Decimal(str(cost)), Decimal(str(multiplier))
        except InvalidOperation:
            return {"row": number, "code": "invalid_decimal"}, None
        if cost_value < 0:
            return {"row": number, "code": "negative_cost"}, None
        if multiplier_value < Decimal("1.3"):
            return {"row": number, "code": "below_safe_floor"}, None
        return None, {
            "provider_id": key[0], "model_key": key[1],
            "category": str(category), "unit_key": key[2],
            "rmb_cost_decimal": str(cost_value),
            "multiplier_decimal": str(multiplier_value),
            "verification_status": str(status),
            "verified_at": str(verified) if verified is not None else None,
        }

    def export_workbook(self, rows: list[dict[str, Any]]) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "人民币模型价格"
        sheet.append(HEADERS)
        for row in rows:
            verified_at = row.get("verified_at")
            if isinstance(verified_at, datetime):
                verified_at = verified_at.isoformat()
            sheet.append((
                row["provider_id"], row["model_key"], row.get("category", ""),
                row["unit_key"], row["rmb_cost_decimal"],
                row.get("multiplier_decimal", ""),
                row.get("verification_status", ""), verified_at,
            ))
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def confirm_import(self, import_id: str, actor_id: str) -> dict[str, Any]:
        stored = self.repository.get_import(import_id)  # type: ignore[attr-defined]
        if stored is None:
            raise KeyError(import_id)
        if stored["status"] != "previewed":
            raise ValueError("import already confirmed or missing")
        preview = stored["preview"]
        if preview["status"] != "ready":
            raise ValueError("blocked import cannot be confirmed")
        policy_revisions: dict[str, int] = {}
        for row in preview["valid_rows"]:
            self.repository.append_cost_snapshot({  # type: ignore[attr-defined]
                "provider_id": row["provider_id"], "model_key": row["model_key"],
                "capability": row["category"], "unit_key": row["unit_key"],
                "source_type": "excel", "source_reference": stored["filename"],
                "original_currency": "CNY",
                "original_price_decimal": row["rmb_cost_decimal"],
                "fx_rate_decimal": "1", "rmb_cost_decimal": row["rmb_cost_decimal"],
                "conditions": {}, "verification_status": row["verification_status"],
                "verified_at": datetime.fromisoformat(
                    row["verified_at"].replace("Z", "+00:00")),
            })
            scope_key = f"{row['provider_id']}/{row['model_key']}"
            revision = policy_revisions.get(scope_key, 0)
            saved = self.repository.replace_policy(  # type: ignore[attr-defined]
                scope_type="model", scope_key=scope_key,
                multiplier_decimal=row["multiplier_decimal"], settings={},
                actor_id=actor_id, expected_revision=revision)
            policy_revisions[scope_key] = saved["revision"]
        self.repository.confirm_import(import_id)  # type: ignore[attr-defined]
        pricing_preview = self.preview_builder(actor_id) if self.preview_builder else None
        self.repository.append_audit(  # type: ignore[attr-defined]
            "excel.confirmed", actor_id, {},
            {"import_id": import_id,
             "catalog_id": (pricing_preview or {}).get("catalog_id")},
        )
        return {"id": import_id, "status": "confirmed",
                "pricing_preview": pricing_preview}
