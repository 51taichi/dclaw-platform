"""Golden custom-compose fixture for the selected editorial consulting scheme."""

from __future__ import annotations

from typing import Any


FONT = "Noto Sans CJK SC"
BLUE = "1B4F9A"
SKY = "0EA5E9"
INK = "1E293B"
MUTED = "64748B"
PANEL = "F5F7FA"
RULE = "DDE5EE"
ORANGE = "F59E0B"
GREEN = "10B981"
WHITE = "FFFFFF"


def _shape(
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str,
    geometry: str = "rect",
    line: str | None = None,
    semantic_group: str = "",
) -> dict[str, Any]:
    layer: dict[str, Any] = {
        "type": "shape",
        "name": name,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "fill": fill,
        "geometry": geometry,
    }
    if line:
        layer["line"] = line
    if semantic_group:
        layer["semantic_group"] = semantic_group
    return layer


def _text(
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    bold: bool = False,
    align: str = "left",
    valign: str = "top",
    semantic_group: str = "",
) -> dict[str, Any]:
    layer: dict[str, Any] = {
        "type": "text",
        "name": name,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "text": text,
        "font_size": size,
        "color": color,
        "bold": bold,
        "align": align,
        "valign": valign,
        "margin": 0,
    }
    if semantic_group:
        layer["semantic_group"] = semantic_group
    return layer


def _cover_slide() -> dict[str, Any]:
    layers = [
        _shape("Cover blue rail", 0, 0, 0.28, 7.5, fill=BLUE),
        _shape("Cover sky rule", 0.78, 0.8, 1.25, 0.09, fill=SKY),
        _text("Cover brand", 0.78, 1.12, 4.8, 0.5, "深兆左智", size=20, color=BLUE, bold=True),
        _text(
            "Cover title",
            0.78,
            2.02,
            7.25,
            1.55,
            "企业 AI 落地\n共建服务手册",
            size=39,
            color=INK,
            bold=True,
        ),
        _text(
            "Cover positioning",
            0.82,
            4.05,
            6.7,
            0.62,
            "从认知建立，到精准诊断，再到深度执行",
            size=19,
            color=MUTED,
        ),
        _shape("Cover visual disc", 8.62, 1.2, 3.52, 3.52, fill="EAF3FB", geometry="ellipse"),
        _shape("Cover visual core", 9.48, 2.06, 1.8, 1.8, fill=BLUE, geometry="ellipse"),
        _shape("Cover visual orbit one", 8.18, 3.98, 4.42, 0.18, fill=SKY),
        _shape("Cover visual orbit two", 9.0, 4.62, 3.58, 0.12, fill=BLUE),
        _text("Cover visual label", 9.18, 2.62, 2.42, 0.48, "RESULT", size=18, color=WHITE, bold=True, align="center"),
        _text("Cover footer", 0.82, 6.62, 6.8, 0.36, "AI Native · 战略到执行 · 全程共建", size=13, color=BLUE, bold=True),
        _text("Cover edition", 10.1, 6.64, 2.35, 0.3, "SERVICE MANUAL", size=10, color=MUTED, align="right"),
    ]
    return {
        "title": "深兆左智企业 AI 落地共建服务手册",
        "archetype": "editorial_brand_cover",
        "expected_content": {
            "required_text": ["深兆左智", "企业 AI 落地", "AI Native"],
            "required_layer_names": ["Cover title", "Cover visual core"],
            "layer_type_counts": {"shape": 6, "text": 6},
        },
        "layers": layers,
    }


def _insight_slide() -> dict[str, Any]:
    layers = [
        _text("Insight kicker", 0.72, 0.48, 2.8, 0.3, "AI 转型困局", size=12, color=SKY, bold=True),
        _text("Insight title", 0.72, 0.9, 11.5, 0.68, "95%的企业卡在工具层，根本原因是什么？", size=29, bold=True),
        _shape("Insight divider", 0.72, 1.62, 11.9, 0.04, fill=RULE),
        _text("Insight metric", 0.7, 1.95, 4.0, 1.6, "95%", size=68, color=BLUE, bold=True),
        _text("Insight thesis", 0.82, 3.66, 3.48, 1.18, "不是工具不够好，\n是完整落地机制缺失。", size=21, color=INK, bold=True),
        _shape("Insight thesis rule", 0.82, 5.18, 2.24, 0.1, fill=ORANGE),
    ]
    cards = [
        ("认知断层", "上下级对 AI 理解存在代差，推进找不到切入点"),
        ("价值迷失", "采购了 AI 工具，却难以量化经营价值"),
        ("方法缺失", "使用方法不对，投入产出比为负"),
        ("数据孤岛", "各部门各自为战，无法形成企业级协作能力"),
    ]
    for index, (title, body) in enumerate(cards):
        col = index % 2
        row = index // 2
        x = 4.82 + col * 3.82
        y = 1.95 + row * 2.32
        layers.extend(
            [
                _shape(f"Insight card {index + 1}", x, y, 3.48, 1.92, fill=PANEL, line=RULE, semantic_group="insight_card"),
                _shape(f"Insight icon {index + 1}", x + 0.28, y + 0.28, 0.42, 0.42, fill=ORANGE, geometry="ellipse"),
                _text(f"Insight card title {index + 1}", x + 0.86, y + 0.22, 2.25, 0.4, title, size=17, color=BLUE, bold=True, semantic_group="insight_card"),
                _text(f"Insight card body {index + 1}", x + 0.3, y + 0.88, 2.88, 0.72, body, size=13, color=MUTED),
            ],
        )
    return {
        "title": "95%的企业卡在工具层",
        "archetype": "dominant_metric_insight_grid",
        "expected_content": {
            "required_text": ["95%", "认知断层", "价值迷失", "方法缺失", "数据孤岛"],
            "semantic_group_counts": {"insight_card": 8},
            "layer_type_counts": {"shape": 10, "text": 12},
        },
        "layers": layers,
    }


def _method_slide() -> dict[str, Any]:
    layers = [
        _text("Method kicker", 0.72, 0.46, 2.8, 0.3, "三阶聚焦方法论", size=12, color=SKY, bold=True),
        _text("Method title", 0.72, 0.88, 10.8, 0.62, "从广撒网到精准穿透：找到 AI 化切入点", size=29, bold=True),
        _text("Method caption", 0.74, 1.56, 6.0, 0.38, "从无限可能，收敛到 3 个以内最高价值场景", size=15, color=MUTED),
        _shape("Funnel top", 0.92, 2.18, 6.02, 1.18, fill="DCEAF7", geometry="trapezoid", semantic_group="funnel_stage"),
        _shape("Funnel middle", 1.58, 3.46, 4.7, 1.12, fill="8FC9E8", geometry="trapezoid", semantic_group="funnel_stage"),
        _shape("Funnel bottom", 2.28, 4.7, 3.3, 1.06, fill=BLUE, geometry="trapezoid", semantic_group="funnel_stage"),
        _text("Funnel top label", 0.92, 2.52, 6.02, 0.36, "STEP 1  关键场景选定", size=17, color=BLUE, bold=True, align="center"),
        _text("Funnel middle label", 1.58, 3.79, 4.7, 0.36, "STEP 2  业务流深度拆解", size=16, color=INK, bold=True, align="center"),
        _text("Funnel bottom label", 2.28, 5.02, 3.3, 0.36, "STEP 3  AI 化部署建议", size=15, color=WHITE, bold=True, align="center"),
    ]
    steps = [
        ("01", "精选关键场景", "精选 3 个以内最具 AI 化潜力的关键场景"),
        ("02", "拆解业务流", "绘制业务流节点图，定位 AI 介入环节"),
        ("03", "给出部署路线", "匹配 Agent / Skill 配置，输出优先级路线图"),
    ]
    for index, (number, title, body) in enumerate(steps):
        y = 2.18 + index * 1.45
        layers.extend(
            [
                _shape(f"Method step marker {index + 1}", 7.48, y, 0.66, 0.66, fill=SKY if index < 2 else BLUE, geometry="ellipse", semantic_group="method_step"),
                _text(f"Method step number {index + 1}", 7.48, y + 0.16, 0.66, 0.28, number, size=12, color=WHITE, bold=True, align="center"),
                _text(f"Method step title {index + 1}", 8.45, y - 0.02, 3.74, 0.42, title, size=18, color=BLUE, bold=True, semantic_group="method_step"),
                _text(f"Method step body {index + 1}", 8.45, y + 0.48, 3.78, 0.54, body, size=13, color=MUTED),
            ],
        )
    return {
        "title": "三阶聚焦方法论",
        "archetype": "native_three_stage_funnel",
        "expected_content": {
            "required_text": ["关键场景选定", "业务流深度拆解", "AI 化部署建议"],
            "required_layer_names": ["Funnel top", "Funnel middle", "Funnel bottom"],
            "semantic_group_counts": {"funnel_stage": 3, "method_step": 6},
            "layer_type_counts": {"shape": 6, "text": 15},
        },
        "layers": layers,
    }


def _service_slide() -> dict[str, Any]:
    layers = [
        _text("Service kicker", 0.72, 0.46, 3.0, 0.3, "FDE 陪跑服务", size=12, color=SKY, bold=True),
        _text("Service title", 0.72, 0.88, 10.5, 0.62, "AI 落地专家常驻，为经营结果负责到底", size=29, bold=True),
        _text("Service caption", 0.74, 1.54, 9.6, 0.38, "不是顾问来出报告，而是深入业务流，和团队一起把能力做出来。", size=15, color=MUTED),
    ]
    services = [
        ("企业 AI 知识库建设", "全员共享、全员共创，形成可持续自进化能力", BLUE, "K"),
        ("业务流 AI 化重构", "系统优化企业运转机制，让 AI 深入每个工作节点", SKY, "F"),
        ("定制化 Agent 开发", "为关键岗位开发专属 Tools、Skill 与 Agent", ORANGE, "A"),
        ("Prompt 资产库沉淀", "搭建可复用提示词库，让方法持续成为数字资产", GREEN, "P"),
    ]
    for index, (title, body, color, icon) in enumerate(services):
        col = index % 2
        row = index // 2
        x = 0.76 + col * 6.12
        y = 2.18 + row * 2.25
        layers.extend(
            [
                _shape(f"Service card {index + 1}", x, y, 5.62, 1.86, fill=WHITE, line=RULE, semantic_group="service_module"),
                _shape(f"Service icon disc {index + 1}", x + 0.34, y + 0.38, 0.82, 0.82, fill=color, geometry="ellipse"),
                _text(f"Service icon {index + 1}", x + 0.34, y + 0.58, 0.82, 0.3, icon, size=16, color=WHITE, bold=True, align="center"),
                _text(f"Service title {index + 1}", x + 1.46, y + 0.3, 3.68, 0.42, title, size=17, color=BLUE, bold=True, semantic_group="service_module"),
                _text(f"Service body {index + 1}", x + 1.46, y + 0.88, 3.62, 0.62, body, size=13, color=MUTED),
            ],
        )
    return {
        "title": "FDE 陪跑服务",
        "archetype": "editorial_service_icon_grid",
        "expected_content": {
            "required_text": ["企业 AI 知识库建设", "业务流 AI 化重构", "定制化 Agent 开发", "Prompt 资产库沉淀"],
            "semantic_group_counts": {"service_module": 8},
            "layer_type_counts": {"shape": 8, "text": 15},
        },
        "layers": layers,
    }


def _choice_slide() -> dict[str, Any]:
    layers = [
        _text("Choice kicker", 0.72, 0.42, 3.0, 0.3, "合作方式", size=12, color=SKY, bold=True),
        _text("Choice title", 0.72, 0.82, 10.6, 0.62, "三种合作路径，从认知启动到全程共建", size=29, bold=True),
        _text("Choice subtitle", 0.74, 1.45, 9.5, 0.36, "建设深度逐级增加；全程共建型获得从认知到执行的完整闭环。", size=14, color=MUTED),
    ]
    paths = [
        ("认知启动型", "企业 AI 内训", "建立管理团队 AI 认知共识", False),
        ("战略重构型", "内训 + 咨询", "认知升级 + 精准诊断", False),
        ("全程共建型", "内训 + 咨询 + FDE", "从认知到执行完整闭环", True),
    ]
    for index, (title, offer, value, recommended) in enumerate(paths):
        x = 0.72 + index * 4.18
        panel_fill = BLUE if recommended else WHITE
        title_color = WHITE if recommended else BLUE
        body_color = "DDEBFA" if recommended else MUTED
        layers.extend(
            [
                _shape(f"Choice panel {index + 1}", x, 2.05, 3.72, 4.48, fill=panel_fill, line=BLUE if recommended else RULE, semantic_group="cooperation_path"),
                _text(f"Choice path title {index + 1}", x + 0.32, 2.48, 3.08, 0.46, title, size=20, color=title_color, bold=True, align="center", semantic_group="cooperation_path"),
                _shape(f"Choice separator {index + 1}", x + 0.42, 3.18, 2.88, 0.04, fill=SKY if recommended else RULE),
                _text(f"Choice offer {index + 1}", x + 0.42, 3.56, 2.88, 0.66, offer, size=17, color=title_color, bold=True, align="center"),
                _text(f"Choice value {index + 1}", x + 0.44, 4.55, 2.84, 0.82, value, size=14, color=body_color, align="center"),
            ],
        )
        if recommended:
            layers.extend(
                [
                    _shape("Choice recommended pill", x + 1.08, 1.84, 1.56, 0.44, fill=GREEN, geometry="roundRect"),
                    _text("Choice recommended label", x + 1.08, 1.95, 1.56, 0.2, "推荐", size=11, color=WHITE, bold=True, align="center"),
                ],
            )
    layers.extend(
        [
            _shape("Choice bet rail", 0.72, 6.82, 11.9, 0.04, fill=SKY),
            _text("Choice bet note", 0.74, 6.98, 11.4, 0.28, "阶梯对赌机制：以经营结果为验收标准，风险共担。", size=12, color=BLUE, bold=True),
        ],
    )
    return {
        "title": "三种合作路径",
        "archetype": "three_column_choice_with_recommendation",
        "expected_content": {
            "required_text": ["认知启动型", "战略重构型", "全程共建型", "阶梯对赌机制"],
            "required_layer_names": ["Choice panel 1", "Choice panel 2", "Choice panel 3", "Choice recommended label"],
            "semantic_group_counts": {"cooperation_path": 6},
            "layer_type_counts": {"shape": 8, "text": 14},
        },
        "layers": layers,
    }


def build_scheme_b_compose_spec() -> dict[str, Any]:
    """Return the five-slide visual-parity acceptance compose contract."""
    return {
        "schema_version": "2.0",
        "deck_title": "深兆左智企业 AI 落地共建服务手册 - 视觉小样",
        "slide_size": {"width": 13.333333, "height": 7.5},
        "theme": {
            "mode": "light",
            "canvas": WHITE,
            "ink": INK,
            "body": INK,
            "muted": MUTED,
            "panel": PANEL,
            "panel_alt": "EAF3FB",
            "rule": RULE,
            "accent": BLUE,
            "accent_soft": "DCEAF7",
            "font_family": FONT,
            "font_fallbacks": [
                "WenQuanYi Zen Hei",
                "Hiragino Sans GB",
                "Heiti SC",
                "PingFang SC",
                "Microsoft YaHei",
            ],
        },
        "visual_translation_contract": {
            "selected_scheme": "B - 企业咨询服务编辑风",
            "survival_rules": [
                "95% remains the dominant visual anchor",
                "methodology remains a native three-stage funnel",
                "service delivery remains a 2x2 icon grid",
                "all three cooperation paths remain visible",
                "the recommended cooperation path is visually dominant",
            ],
        },
        "native_translation_rationale": (
            "The selected scheme is an editorial system made of typography, rules, "
            "native geometry, and restrained color. The reference moodboard is not "
            "embedded as a slide image; its visual grammar is rebuilt as editable layers."
        ),
        "slides": [
            _cover_slide(),
            _insight_slide(),
            _method_slide(),
            _service_slide(),
            _choice_slide(),
        ],
    }
