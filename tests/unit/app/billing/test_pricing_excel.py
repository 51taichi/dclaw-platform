from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from qwenpaw.app.billing.pricing_excel import PricingExcelService
from qwenpaw.app.billing.official_pricing import OfficialPriceRegistry
from qwenpaw.app.billing.pricing_draft import PricingDraftBuilder
from qwenpaw.app.billing.pricing_inventory import PriceableModel
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings

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


class Repo:
    def __init__(self):
        self.imports = {}

    def record_import(self, digest, filename, actor_id, preview):
        self.imports.setdefault(digest, {"id": "import-1", "preview": preview})
        return self.imports[digest]


def _workbook(multiplier="1.5", cost="0.004"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(
        (
            "dashscope",
            "qwen-plus",
            "text",
            "input_tokens",
            cost,
            multiplier,
            "verified",
            "2026-08-30T00:00:00Z",
        )
    )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_import_below_floor_is_blocked_and_idempotent():
    service = PricingExcelService(Repo())
    first = service.preview_import(
        _workbook(multiplier="1.1"), "prices.xlsx", "1"
    )
    second = service.preview_import(
        _workbook(multiplier="1.1"), "copy.xlsx", "1"
    )
    assert first["id"] == second["id"]
    assert first["status"] == "blocked"
    assert first["rows"][0]["code"] == "below_safe_floor"


def test_formula_is_rejected_and_export_contains_no_foreign_currency():
    formula = _workbook(cost="=1+1")
    preview = PricingExcelService(Repo()).preview_import(
        formula, "prices.xlsx", "1"
    )
    assert preview["status"] == "blocked"
    assert preview["rows"][0]["code"] == "formula_not_allowed"

    exported = PricingExcelService(Repo()).export_workbook(
        [
            {
                "provider_id": "dashscope",
                "model_key": "qwen-plus",
                "category": "text",
                "unit_key": "input_tokens",
                "rmb_cost_decimal": "0.004",
                "multiplier_decimal": "1.5",
                "verification_status": "verified",
                "verified_at": None,
            }
        ]
    )
    sheet = load_workbook(BytesIO(exported), read_only=True).active
    values = " ".join(
        str(cell) for row in sheet.iter_rows(values_only=True) for cell in row
    )
    assert "USD" not in values
    assert "美元" not in values
    assert "人民币成本" in values


def test_confirm_creates_cost_policy_and_draft_only(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "excel.db"),
            }
        )
    )
    create_all(engine)
    repo = PricingAdminRepository(engine)
    service = PricingExcelService(
        repo,
        preview_builder=lambda actor, rows, import_id: {
            "catalog_id": "draft-1"
        },
    )
    preview = service.preview_import(_workbook(), "prices.xlsx", "1")
    result = service.confirm_import(preview["id"], "1")
    assert result["pricing_preview"] == {"catalog_id": "draft-1"}
    assert repo.latest_trusted_costs()[0]["rmb_cost_decimal"] == "0.004"
    assert repo.list_policies()[0]["multiplier_decimal"] == "1.5"
    with pytest.raises(ValueError, match="already confirmed"):
        service.confirm_import(preview["id"], "1")
    engine.dispose()


def test_confirm_can_resume_draft_creation_without_reapplying_rows(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "excel-resume.db"),
            }
        )
    )
    create_all(engine)
    repo = PricingAdminRepository(engine)
    attempts = 0

    def preview_builder(_actor, _rows, _import_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("draft creation interrupted")
        return {"catalog_id": "draft-1"}

    service = PricingExcelService(repo, preview_builder=preview_builder)
    preview = service.preview_import(_workbook(), "prices.xlsx", "1")

    with pytest.raises(RuntimeError, match="interrupted"):
        service.confirm_import(preview["id"], "1")
    result = service.confirm_import(preview["id"], "1")

    assert result["pricing_preview"] == {"catalog_id": "draft-1"}
    assert len(repo.list_cost_snapshots()) == 1
    assert repo.list_policies()[0]["revision"] == 1
    engine.dispose()


def test_draft_export_has_three_sheets_and_enabled_models_without_db_costs():
    models = [
        PriceableModel(
            "dashscope",
            "百炼",
            "qwen3-max",
            "Qwen3 Max",
            "text",
            official_model_id="qwen3-max",
        ),
        PriceableModel(
            "volcengine-cn",
            "火山方舟",
            "missing-model",
            "Missing",
            "text",
            official_model_id="missing-model",
        ),
    ]
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        models, [], [], []
    )

    exported = PricingExcelService(Repo()).export_draft(draft)
    workbook = load_workbook(BytesIO(exported), read_only=True)

    assert workbook.sheetnames == ["价格草案", "缺失与风险", "填写说明"]
    draft_values = [
        value
        for row in workbook["价格草案"].iter_rows(values_only=True)
        for value in row
    ]
    assert "qwen3-max" in draft_values
    assert "missing-model" in draft_values
    assert "1.5" in {str(value) for value in draft_values}
    risk_values = [
        value
        for row in workbook["缺失与风险"].iter_rows(values_only=True)
        for value in row
    ]
    assert "official_price_missing" in risk_values
    instructions = " ".join(
        str(value)
        for row in workbook["填写说明"].iter_rows(values_only=True)
        for value in row
        if value is not None
    )
    assert "1 元人民币 = 100 积分" in instructions
    assert "1.5" in instructions


def test_draft_round_trip_recomputes_prices_and_requires_exclusion_reason():
    model = PriceableModel(
        "volcengine-cn",
        "火山方舟",
        "missing-model",
        "Missing",
        "text",
        official_model_id="missing-model",
    )
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], [], [], []
    )
    service = PricingExcelService(Repo())
    content = service.export_draft(draft)

    workbook = load_workbook(BytesIO(content))
    sheet = workbook["价格草案"]
    headers = {cell.value: cell.column for cell in sheet[1]}
    sheet.cell(2, headers["是否纳入本次发布"], "否")
    sheet.cell(2, headers["排除原因"], None)
    output = BytesIO()
    workbook.save(output)

    blocked = service.preview_import(output.getvalue(), "draft.xlsx", "1")
    assert blocked["status"] == "blocked"
    assert blocked["rows"][0]["code"] == "exclusion_reason_required"
