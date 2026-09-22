"""Strict RMB-only XLSX import previews and exports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Protocol
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.comments import Comment
from openpyxl.utils.exceptions import InvalidFileException

from .pricing_draft import PricingDraftResult
from .pricing_spec import normalize_spec, spec_key

HEADERS = (
    "供应商",
    "模型",
    "分类",
    "计价维度",
    "人民币成本",
    "倍数",
    "来源状态",
    "验证时间",
)
DRAFT_HEADERS = (
    "平台ID",
    "平台名称",
    "模型ID",
    "模型名称",
    "官方平台ID",
    "官方模型ID",
    "分类",
    "能力",
    "计价维度",
    "单位数量",
    "规格条件",
    "人民币成本",
    "默认倍率",
    "人民币销售价",
    "积分价格",
    "来源类型",
    "官方来源",
    "验证状态",
    "登记版本",
    "是否纳入本次发布",
    "排除原因",
    "证据等级",
    "候选摘要",
    "审批理由",
)
MAX_WORKBOOK_BYTES = 5 * 1024 * 1024


class ImportRepository(Protocol):
    def record_import(  # noqa: E704
        self,
        digest: str,
        filename: str,
        actor_id: str,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class PricingExcelService:
    def __init__(
        self,
        repository: ImportRepository,
        *,
        preview_builder: (
            Callable[[str, list[dict[str, Any]] | None, str], dict[str, Any]] | None
        ) = None,
        confirmation_builder: (
            Callable[[str, list[dict[str, Any]] | None, str], dict[str, Any]] | None
        ) = None,
        draft_builder: (
            Callable[[str, list[dict[str, Any]] | None, str], dict[str, Any]] | None
        ) = None,
    ) -> None:
        self.repository = repository
        self.preview_builder = preview_builder
        self.confirmation_builder = confirmation_builder or preview_builder
        self.draft_builder = draft_builder or self.confirmation_builder

    def preview_import(
        self, content: bytes, filename: str, actor_id: str
    ) -> dict[str, Any]:
        problems: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        if len(content) > MAX_WORKBOOK_BYTES:
            problems.append({"row": 0, "code": "file_too_large"})
        elif filename.lower().endswith((".xlsm", ".xltm")):
            problems.append({"row": 0, "code": "macro_not_allowed"})
        else:
            try:
                sheet = load_workbook(
                    BytesIO(content),
                    read_only=True,
                    data_only=False,
                ).active
                header = tuple(cell.value for cell in next(sheet.iter_rows()))
                if header not in (HEADERS, DRAFT_HEADERS):
                    problems.append({"row": 1, "code": "invalid_headers"})
                else:
                    seen: set[tuple[str, ...]] = set()
                    for number, values in enumerate(
                        sheet.iter_rows(min_row=2, values_only=True),
                        start=2,
                    ):
                        if not any(value is not None for value in values):
                            continue
                        if any(
                            isinstance(value, str) and value.startswith("=")
                            for value in values
                        ):
                            problems.append(
                                {"row": number, "code": "formula_not_allowed"}
                            )
                            continue
                        parser = (
                            self._parse_draft_row
                            if header == DRAFT_HEADERS
                            else self._parse_row
                        )
                        problem, row = parser(number, values, seen)
                        if problem:
                            problems.append(problem)
                        elif row:
                            rows.append(row)
            except (
                BadZipFile,
                InvalidFileException,
                KeyError,
                OSError,
                ValueError,
            ):
                problems.append({"row": 0, "code": "invalid_workbook"})
        preview = {
            "status": "blocked" if problems else "ready",
            "rows": problems if problems else rows,
            "valid_rows": rows,
        }
        digest = hashlib.sha256(content).hexdigest()
        stored = self.repository.record_import(
            digest,
            filename,
            actor_id,
            preview,
        )
        stored_preview = json.loads(str(stored.get("preview_json") or "{}"))
        if stored_preview.get("pricing_preview"):
            return {"id": stored["id"], **stored_preview}
        if not problems and self.preview_builder:
            try:
                pricing_preview = self.preview_builder(
                    actor_id, rows, str(stored["id"])
                )
                preview["pricing_preview"] = pricing_preview
                if pricing_preview.get("publishable") is False:
                    preview["status"] = "blocked"
                    preview["rows"] = pricing_preview.get("blockers", [])
            except ValueError as exc:
                preview["status"] = "blocked"
                preview["rows"] = [
                    {
                        "row": 0,
                        "code": "pricing_preflight_failed",
                        "detail": str(exc),
                    }
                ]
            self.repository.replace_import_preview(  # type: ignore[attr-defined]  # noqa: E501
                str(stored["id"]), preview
            )
        return {"id": stored["id"], **preview}

    @staticmethod
    def _parse_row(number: int, values: tuple[Any, ...], seen: set[tuple[str, ...]]):
        (
            provider,
            model,
            category,
            unit,
            cost,
            multiplier,
            status,
            verified,
        ) = values
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
        if multiplier_value < Decimal("1"):
            return {"row": number, "code": "below_safe_floor"}, None
        return None, {
            "provider_id": key[0],
            "model_key": key[1],
            "category": str(category),
            "unit_key": key[2],
            "rmb_cost_decimal": str(cost_value),
            "multiplier_decimal": str(multiplier_value),
            "verification_status": str(status),
            "verified_at": str(verified) if verified is not None else None,
        }

    @staticmethod
    def _parse_draft_row(
        number: int, values: tuple[Any, ...], seen: set[tuple[str, ...]]
    ):
        (
            provider_id,
            _provider_name,
            model_key,
            _model_name,
            official_provider_id,
            official_model_id,
            category,
            capability,
            unit_key,
            unit_size,
            conditions,
            cost,
            multiplier,
            sale_price,
            credits,
            source_type,
            source_url,
            verification_status,
            registry_version,
            include,
            exclusion_reason,
            evidence_level,
            candidate_digest,
            approval_reason,
        ) = values
        try:
            parsed_conditions = json.loads(str(conditions or "{}"))
        except json.JSONDecodeError:
            return {"row": number, "code": "invalid_conditions"}, None
        try:
            unit_size_value, parsed_conditions = normalize_spec(
                str(unit_key or ""), unit_size, parsed_conditions
            )
            key = spec_key(
                {
                    "provider_id": str(provider_id).strip(),
                    "model_key": str(model_key).strip(),
                    "capability": str(capability or ""),
                    "unit_key": str(unit_key or "").strip(),
                    "unit_size": unit_size_value,
                    "conditions": parsed_conditions,
                }
            )
        except ValueError:
            return {"row": number, "code": "invalid_specification"}, None
        if key in seen:
            return {"row": number, "code": "duplicate_key"}, None
        seen.add(key)
        include_value = str(include).strip()
        if include_value not in {"是", "否"}:
            return {"row": number, "code": "invalid_inclusion"}, None
        included = include_value == "是"
        reason = str(exclusion_reason or "").strip() or None
        if not included and reason is None:
            return {
                "row": number,
                "code": "exclusion_reason_required",
            }, None
        if cost in (None, ""):
            if included:
                return {"row": number, "code": "trusted_cost_missing"}, None
            return None, {
                "provider_id": key[0],
                "model_key": key[1],
                "official_provider_id": str(official_provider_id or ""),
                "official_model_id": str(official_model_id or ""),
                "category": str(category or ""),
                "capability": str(capability or ""),
                "unit_key": key[3],
                "unit_size": unit_size_value,
                "conditions": parsed_conditions,
                "excluded": True,
                "exclusion_reason": reason,
                "verification_status": str(verification_status),
                "registry_version": str(registry_version or ""),
                "source_type": str(source_type or ""),
                "source_url": str(source_url or ""),
                "evidence_level": str(evidence_level or ""),
                "candidate_digest": str(candidate_digest or ""),
                "approval_reason": str(approval_reason or ""),
            }
        try:
            cost_value = Decimal(str(cost))
            multiplier_value = Decimal(str(multiplier))
            if not cost_value.is_finite() or not multiplier_value.is_finite():
                raise ValueError("nonfinite price")
            if cost_value < 0:
                return {"row": number, "code": "negative_cost"}, None
            expected_sale = cost_value * multiplier_value
            expected_credits = int(
                (expected_sale * 100).to_integral_value(rounding="ROUND_CEILING")
            )
        except (InvalidOperation, TypeError, ValueError):
            return {"row": number, "code": "invalid_decimal"}, None
        if multiplier_value < Decimal("1"):
            return {"row": number, "code": "below_safe_floor"}, None
        # These columns are display-only snapshots. Never trust stale Excel
        # derived values after an administrator edits cost or multiplier.
        return None, {
            "provider_id": key[0],
            "model_key": key[1],
            "official_provider_id": str(official_provider_id or ""),
            "official_model_id": str(official_model_id or ""),
            "category": str(category or ""),
            "capability": str(capability or ""),
            "unit_key": key[3],
            "unit_size": unit_size_value,
            "conditions": parsed_conditions,
            "rmb_cost_decimal": str(cost_value),
            "multiplier_decimal": str(multiplier_value),
            "rmb_sale_price": str(expected_sale),
            "credits": expected_credits,
            "verification_status": str(verification_status),
            "registry_version": str(registry_version or ""),
            "source_type": str(source_type),
            "source_url": str(source_url or ""),
            "excluded": not included,
            "exclusion_reason": reason,
            "evidence_level": str(evidence_level or ""),
            "candidate_digest": str(candidate_digest or ""),
            "approval_reason": str(approval_reason or ""),
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
            sheet.append(
                (
                    row["provider_id"],
                    row["model_key"],
                    row.get("category", ""),
                    row["unit_key"],
                    row["rmb_cost_decimal"],
                    row.get("multiplier_decimal", ""),
                    row.get("verification_status", ""),
                    verified_at,
                )
            )
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def export_draft(self, draft: PricingDraftResult) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "价格草案"
        sheet.append(DRAFT_HEADERS)
        for row in draft.rows:
            sheet.append(
                (
                    row.provider_id,
                    row.provider_name,
                    row.model_key,
                    row.model_name,
                    row.official_provider_id,
                    row.official_model_id,
                    row.category,
                    row.capability,
                    row.unit_key,
                    row.unit_size,
                    json.dumps(
                        row.conditions,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    str(row.rmb_cost) if row.rmb_cost is not None else None,
                    str(row.multiplier),
                    (
                        str(row.rmb_sale_price)
                        if row.rmb_sale_price is not None
                        else None
                    ),
                    row.credits,
                    row.source_type,
                    row.source_url,
                    row.verification_status,
                    row.registry_version,
                    "是" if row.include_in_publish else "否",
                    (
                        row.exclusion_reason
                        or ("暂无可信价格" if not row.include_in_publish else None)
                    ),
                    row.evidence_level,
                    row.candidate_digest,
                    row.approval_reason,
                )
            )
        editable = {"人民币成本", "默认倍率", "是否纳入本次发布", "排除原因"}
        derived = {"人民币销售价", "积分价格"}
        for column in sheet.iter_cols():
            title = column[0].value
            color = "DDEEFF" if title in editable else "F2F2F2"
            hint = "可编辑；成本按本行单位数量填写。" if title in editable else "规格和来源信息，无需修改。"
            if title in derived:
                hint = "参考值；导入时根据成本和倍率自动重新计算，无需手动修改。"
            column[0].comment = Comment(hint, "DClaw")
            for cell in column:
                cell.fill = PatternFill("solid", fgColor=color)
        sheet.column_dimensions["L"].width = 18
        sheet.column_dimensions["M"].width = 16
        sheet.column_dimensions["N"].width = 20
        sheet.column_dimensions["O"].width = 18
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions

        risks = workbook.create_sheet("缺失与风险")
        risks.append(("风险代码", "平台ID", "模型ID", "计价维度"))
        for risk in draft.risks:
            risks.append(
                (
                    risk.code,
                    risk.provider_id,
                    risk.model_key,
                    risk.unit_key,
                )
            )
        risks.freeze_panes = "A2"

        instructions = workbook.create_sheet("填写说明")
        instructions.append(("项目", "说明"))
        instructions.append(("可编辑字段", "人民币成本、默认倍率（不低于1）、是否纳入本次发布、排除原因；成本按本行单位数量填写。"))
        instructions.append(
            ("只读规格", "平台、模型、能力、计价维度、单位数量、规格条件及内部来源信息无需修改；规格调整请重新生成报价单。")
        )
        instructions.append(("自动计算", "人民币销售价、积分价格仅供参考；修改成本或倍率后无需修改这两列，导入时服务端重新计算。"))
        instructions.append(("默认倍率", "人民币可信成本 × 1.5"))
        instructions.append(("积分换算", "1 元人民币 = 100 积分"))
        instructions.append(
            (
                "发布流程",
                "上传 → 格式校验 → 差异预检 → 人工确认 → 草稿 → 发布",
            )
        )
        instructions.append(("缺价模型", "必须补齐可信价格，或选择不纳入并填写排除原因"))
        instructions.append(
            (
                "人工补价",
                "缺价文本模型已自动生成输入、输出两个计价维度；管理员只需填写人民币成本，来源信息无需修改；成本调整会标记为人工待确认，销售价与积分由系统重新计算。",
            )
        )
        instructions.append(
            (
                "精确映射",
                "模型别名应先在管理页面配置官方平台ID与官方模型ID，再重新生成草案；禁止模糊匹配。",
            )
        )
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def confirm_import(
        self,
        import_id: str,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        stored = self.repository.get_import(import_id)  # type: ignore[attr-defined]
        if stored is None:
            raise KeyError(import_id)
        if stored["status"] == "confirmed" and stored["preview"].get("pricing_preview"):
            return {
                "id": import_id,
                "status": "confirmed",
                "pricing_preview": stored["preview"]["pricing_preview"],
                "already_confirmed": True,
            }
        preview = stored["preview"]
        if preview["status"] != "ready":
            raise ValueError("blocked import cannot be confirmed")
        pricing_preview = preview.get("pricing_preview")
        if stored["status"] == "previewed":
            if self.confirmation_builder is not None:
                current_review = self.confirmation_builder(
                    actor_id,
                    preview["valid_rows"],
                    import_id,
                )
                if _approval_view(current_review) != _approval_view(
                    pricing_preview or {}
                ):
                    raise ValueError(
                        "pricing preview is stale; upload and approve again"
                    )
            if self.draft_builder is not None:
                pricing_preview = self.draft_builder(
                    actor_id,
                    preview["valid_rows"],
                    import_id,
                )
            self.repository.apply_import_rows(  # type: ignore[attr-defined]
                import_id,
                preview["valid_rows"],
                stored["filename"],
                actor_id,
                pricing_preview,
                ip_address,
            )
        return {
            "id": import_id,
            "status": "confirmed",
            "pricing_preview": pricing_preview,
        }


def _approval_view(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in preview.items()
        if key not in {"catalog_id", "version"}
    }
