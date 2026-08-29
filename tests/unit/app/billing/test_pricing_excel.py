from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from qwenpaw.app.billing.pricing_excel import PricingExcelService
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings

HEADERS = ("供应商", "模型", "分类", "计价维度", "人民币成本", "倍数", "来源状态", "验证时间")


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
    sheet.append(("dashscope", "qwen-plus", "text", "input_tokens",
                  cost, multiplier, "verified", "2026-08-30T00:00:00Z"))
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_import_below_floor_is_blocked_and_idempotent():
    service = PricingExcelService(Repo())
    first = service.preview_import(_workbook(multiplier="1.1"), "prices.xlsx", "1")
    second = service.preview_import(_workbook(multiplier="1.1"), "copy.xlsx", "1")
    assert first["id"] == second["id"]
    assert first["status"] == "blocked"
    assert first["rows"][0]["code"] == "below_safe_floor"


def test_formula_is_rejected_and_export_contains_no_foreign_currency():
    formula = _workbook(cost="=1+1")
    preview = PricingExcelService(Repo()).preview_import(formula, "prices.xlsx", "1")
    assert preview["status"] == "blocked"
    assert preview["rows"][0]["code"] == "formula_not_allowed"

    exported = PricingExcelService(Repo()).export_workbook([{
        "provider_id": "dashscope", "model_key": "qwen-plus",
        "category": "text", "unit_key": "input_tokens",
        "rmb_cost_decimal": "0.004", "multiplier_decimal": "1.5",
        "verification_status": "verified", "verified_at": None,
    }])
    sheet = load_workbook(BytesIO(exported), read_only=True).active
    values = " ".join(str(cell) for row in sheet.iter_rows(values_only=True) for cell in row)
    assert "USD" not in values
    assert "美元" not in values
    assert "人民币成本" in values


def test_confirm_creates_cost_policy_and_draft_only(tmp_path):
    engine = create_engine_from_settings(get_storage_settings({
        "QWENPAW_SQLITE_PATH": str(tmp_path / "excel.db"),
    }))
    create_all(engine)
    repo = PricingAdminRepository(engine)
    service = PricingExcelService(
        repo, preview_builder=lambda actor: {"catalog_id": "draft-1"},
    )
    preview = service.preview_import(_workbook(), "prices.xlsx", "1")
    result = service.confirm_import(preview["id"], "1")
    assert result["pricing_preview"] == {"catalog_id": "draft-1"}
    assert repo.latest_trusted_costs()[0]["rmb_cost_decimal"] == "0.004"
    assert repo.list_policies()[0]["multiplier_decimal"] == "1.5"
    with pytest.raises(ValueError, match="already confirmed"):
        service.confirm_import(preview["id"], "1")
    engine.dispose()
