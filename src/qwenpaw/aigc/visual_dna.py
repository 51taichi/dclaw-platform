"""Model-neutral visual language primitives and prompt compilation.

Visual DNA stores reusable aesthetic intent instead of provider-specific prompt
snippets. Rendering adapters can consume the same selections and compile them
for GPT Image, Seedream, Flux, video models, or future providers.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field


VisualDnaDimension = Literal[
    "art_direction",
    "lighting",
    "camera",
    "composition",
    "color",
    "material",
    "emotion",
    "environment",
    "narrative",
    "constraint",
]
VisualDnaScope = Literal[
    "aesthetic_profile",
    "shot",
    "creation_template",
    "asset_constraint",
]
VisualDnaStatus = Literal["enabled", "disabled"]


class VisualDnaSelection(BaseModel):
    """A weighted reference to one reusable visual element."""

    element_id: str
    weight: float = Field(default=1.0, ge=0, le=1)
    note: str = ""


class VisualDnaElement(BaseModel):
    """The smallest reusable unit in the model-neutral visual language."""

    id: str
    dimension: VisualDnaDimension
    name: str
    aliases: list[str] = Field(default_factory=list)
    definition: str
    visual_effect: str
    prompt_text: str
    tags: list[str] = Field(default_factory=list)
    compatible_with: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    status: VisualDnaStatus = "enabled"
    version: str = "1.0"


class VisualDnaDimensionInfo(BaseModel):
    id: VisualDnaDimension
    name: str
    description: str
    scope: VisualDnaScope
    element_count: int = 0


class VisualDnaElementList(BaseModel):
    elements: list[VisualDnaElement]
    total: int


class VisualDnaCompileRequest(BaseModel):
    selections: list[VisualDnaSelection] = Field(default_factory=list)
    provider_id: str = ""
    model_id: str = ""
    constraints: list[str] = Field(default_factory=list)


class CompiledVisualDna(BaseModel):
    selections: list[VisualDnaSelection]
    elements: list[VisualDnaElement]
    prompt_appendix: str
    constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_DIMENSIONS: tuple[VisualDnaDimensionInfo, ...] = (
    VisualDnaDimensionInfo(
        id="art_direction",
        name="艺术方向",
        description="作品的整体媒介语言、写实程度与视觉表达方式。",
        scope="aesthetic_profile",
    ),
    VisualDnaDimensionInfo(
        id="lighting",
        name="光影",
        description="光源、方向、软硬、层次与时间氛围。",
        scope="aesthetic_profile",
    ),
    VisualDnaDimensionInfo(
        id="camera",
        name="镜头",
        description="焦段、景深、机位与摄影观察方式。",
        scope="shot",
    ),
    VisualDnaDimensionInfo(
        id="composition",
        name="构图",
        description="主体位置、视觉重心、空间与画面节奏。",
        scope="shot",
    ),
    VisualDnaDimensionInfo(
        id="color",
        name="色彩",
        description="主色关系、冷暖、饱和度与综合色调。",
        scope="aesthetic_profile",
    ),
    VisualDnaDimensionInfo(
        id="material",
        name="材质",
        description="表面纹理、反射、透明度与触感表现。",
        scope="aesthetic_profile",
    ),
    VisualDnaDimensionInfo(
        id="emotion",
        name="情绪氛围",
        description="画面希望建立的心理感受与人物气质。",
        scope="aesthetic_profile",
    ),
    VisualDnaDimensionInfo(
        id="environment",
        name="环境基调",
        description="可跨画面复用的空间、天气、时间与场景氛围倾向。",
        scope="aesthetic_profile",
    ),
    VisualDnaDimensionInfo(
        id="narrative",
        name="叙事",
        description="画面所处的故事时刻、动机与前后关系。",
        scope="creation_template",
    ),
    VisualDnaDimensionInfo(
        id="constraint",
        name="约束",
        description="必须保留、禁止改变或禁止新增的视觉条件。",
        scope="asset_constraint",
    ),
)


_ELEMENTS: tuple[VisualDnaElement, ...] = (
    VisualDnaElement(
        id="art_direction.cinematic_realism",
        dimension="art_direction",
        name="电影写实",
        aliases=["Cinematic Realism", "电影级写实"],
        definition="以真实摄影逻辑为基础，用电影制作的光线、层次和调色组织画面。",
        visual_effect="真实可信、叙事集中，兼具摄影细节与电影完成度。",
        prompt_text="整体采用电影级写实视觉语言，遵循真实摄影、材质和空间逻辑，画面精致但不过度人工锐化",
        tags=["电影感", "写实", "商业摄影"],
    ),
    VisualDnaElement(
        id="art_direction.premium_editorial",
        dimension="art_direction",
        name="高端编辑视觉",
        aliases=["Premium Editorial", "杂志大片"],
        definition="以高端杂志和品牌发布视觉为基准，强调克制、留白与精确的视觉层级。",
        visual_effect="现代、克制、具有品牌感和编辑完成度。",
        prompt_text="整体采用高端编辑视觉语言，控制装饰密度和视觉噪声，以克制、准确的层级呈现品牌质感",
        tags=["品牌", "杂志", "高级感"],
    ),
    VisualDnaElement(
        id="art_direction.stylized_animation",
        dimension="art_direction",
        name="风格化动画",
        aliases=["Stylized Animation", "动画视觉"],
        definition="保留可信的体积与光照，同时使用经过设计的造型、比例和色块语言。",
        visual_effect="造型鲜明、统一，适合角色、世界观与动画视觉开发。",
        prompt_text="整体采用统一的风格化动画视觉语言，造型和色块经过设计，同时保持可信的体积、光照和空间关系",
        tags=["动画", "角色", "风格化"],
    ),
    VisualDnaElement(
        id="lighting.golden_hour_rim",
        dimension="lighting",
        name="黄金时刻轮廓光",
        aliases=["Golden Hour Rim Light", "日落轮廓光"],
        definition="日出或日落前后，低角度暖色光从主体后侧勾勒边缘。",
        visual_effect="温暖、通透、浪漫，并将主体从背景中清晰分离。",
        prompt_text="低角度黄金时刻暖光从主体后侧照入，形成柔和清晰的轮廓高光，并保留自然暗部层次",
        tags=["自然光", "人像", "治愈", "户外"],
        compatible_with=["color.warm_muted", "emotion.warm_healing"],
    ),
    VisualDnaElement(
        id="lighting.soft_window",
        dimension="lighting",
        name="柔和窗光",
        aliases=["Soft Window Light", "侧窗光"],
        definition="大面积窗户形成有方向但不过硬的自然散射光。",
        visual_effect="真实、安静、细腻，适合表现皮肤与日常空间。",
        prompt_text="大面积柔和侧窗光塑造主体，明暗过渡细腻，阴影保持柔软且有方向",
        tags=["自然光", "室内", "人像", "生活方式"],
        compatible_with=["color.warm_muted", "material.soft_silk"],
    ),
    VisualDnaElement(
        id="lighting.cinematic_contrast",
        dimension="lighting",
        name="电影级戏剧光影",
        aliases=["Cinematic Contrast Lighting", "戏剧光"],
        definition="利用明确的主光方向与受控暗部建立电影场景的层次。",
        visual_effect="叙事集中、空间纵深强、主体更具戏剧张力。",
        prompt_text="使用有明确方向的电影级主光与受控暗部，形成层次丰富的明暗关系、空间纵深和主体轮廓",
        tags=["电影感", "叙事", "高对比"],
        compatible_with=["composition.diagonal_tension", "emotion.mystery_tension"],
    ),
    VisualDnaElement(
        id="camera.85mm_portrait",
        dimension="camera",
        name="85mm 人像镜头",
        aliases=["85mm Portrait", "中长焦人像"],
        definition="中长焦视角，保持自然人像比例并压缩背景空间。",
        visual_effect="人物轮廓自然、背景干净、注意力集中。",
        prompt_text="采用约 85mm 中长焦人像视角，保持自然面部比例与适度空间压缩，主体和背景清晰分层",
        tags=["人像", "中长焦", "背景压缩"],
        conflicts_with=["camera.35mm_environmental"],
    ),
    VisualDnaElement(
        id="camera.35mm_environmental",
        dimension="camera",
        name="35mm 环境叙事镜头",
        aliases=["35mm Environmental Portrait", "广角环境人像"],
        definition="适度广角视角，同时容纳主体和足够的场景信息。",
        visual_effect="临场、真实、具有明确的人物与环境关系。",
        prompt_text="采用约 35mm 环境叙事视角，主体保持自然比例，同时让周围空间参与故事表达",
        tags=["纪实", "环境人像", "叙事"],
        conflicts_with=["camera.85mm_portrait"],
    ),
    VisualDnaElement(
        id="camera.shallow_depth",
        dimension="camera",
        name="浅景深主体聚焦",
        aliases=["Shallow Depth of Field", "背景虚化"],
        definition="将清晰焦点限制在主体关键区域，背景逐渐柔化。",
        visual_effect="视觉焦点明确，画面更具摄影感和空间层次。",
        prompt_text="焦点准确落在主体关键区域，使用自然浅景深让背景渐进柔化，避免生硬抠图感",
        tags=["摄影感", "主体聚焦", "景深"],
    ),
    VisualDnaElement(
        id="composition.centered_hero",
        dimension="composition",
        name="中心英雄构图",
        aliases=["Centered Hero Composition", "英雄位"],
        definition="主体位于稳定视觉中心，以尺度和留白建立主视觉权威感。",
        visual_effect="直接、有力量，适合产品主视觉、角色海报与发布场景。",
        prompt_text="主体位于稳定的视觉中心和英雄位，轮廓完整，周围保留有组织的呼吸空间并形成明确视觉层级",
        tags=["主视觉", "产品", "角色海报"],
        compatible_with=["emotion.heroic_confidence"],
    ),
    VisualDnaElement(
        id="composition.negative_space",
        dimension="composition",
        name="叙事留白",
        aliases=["Narrative Negative Space", "留白构图"],
        definition="主动保留低信息区域，为视线、文字或故事方向提供空间。",
        visual_effect="克制、高级、便于排版，并强化主体的方向感。",
        prompt_text="构图保留有意图的低信息留白，留白方向与主体视线或动作一致，画面克制且便于后续排版",
        tags=["留白", "海报", "高级感"],
    ),
    VisualDnaElement(
        id="composition.diagonal_tension",
        dimension="composition",
        name="对角线张力",
        aliases=["Diagonal Tension", "动态对角线"],
        definition="利用主体、光线或环境结构形成斜向视觉动势。",
        visual_effect="更具速度、冲突和电影场面的瞬间感。",
        prompt_text="主体动作、空间结构或光线形成清晰的对角线动势，画面稳定但具有向前推进的视觉张力",
        tags=["动态", "电影感", "动作"],
    ),
    VisualDnaElement(
        id="color.warm_muted",
        dimension="color",
        name="低饱和暖色",
        aliases=["Muted Warm Tone", "暖灰色调"],
        definition="以暖色为基础降低饱和度，让色彩柔和统一。",
        visual_effect="温暖、耐看、治愈，避免廉价的高饱和感。",
        prompt_text="整体采用低饱和暖色体系，肤色与环境色自然协调，亮部温暖但不过曝，避免艳俗橙黄",
        tags=["暖色", "低饱和", "治愈"],
        conflicts_with=["color.cool_metallic"],
    ),
    VisualDnaElement(
        id="color.cool_metallic",
        dimension="color",
        name="冷调金属色",
        aliases=["Cool Metallic Palette", "冷银灰"],
        definition="以冷灰、深蓝和克制金属高光构成理性冷调色彩。",
        visual_effect="科技、工业、克制，突出硬质材料与秩序感。",
        prompt_text="使用冷灰与深蓝为主的克制色调，金属高光干净准确，暗部保持层次而不是纯黑",
        tags=["冷色", "工业", "科技", "金属"],
        conflicts_with=["color.warm_muted"],
        compatible_with=["material.brushed_metal", "environment.industrial_depth"],
    ),
    VisualDnaElement(
        id="color.teal_orange_controlled",
        dimension="color",
        name="克制青橙对比",
        aliases=["Controlled Teal and Orange", "青橙电影色"],
        definition="以冷青环境和暖色主体建立综合色彩对比，但控制饱和度。",
        visual_effect="主体突出、具有商业电影感，同时不显滤镜化。",
        prompt_text="冷青环境色与暖色主体形成克制的冷暖对比，综合色彩统一，避免高饱和青橙滤镜感",
        tags=["电影调色", "冷暖对比", "商业"],
    ),
    VisualDnaElement(
        id="material.brushed_metal",
        dimension="material",
        name="拉丝金属",
        aliases=["Brushed Metal", "细拉丝金属"],
        definition="带细密方向纹理的金属表面，反射柔和而有秩序。",
        visual_effect="精密、工业、高端，能表现真实加工质感。",
        prompt_text="金属表面呈现细密一致的拉丝纹理，反射受环境控制，边缘高光准确并保留真实微小粗糙度",
        tags=["工业", "产品", "金属"],
    ),
    VisualDnaElement(
        id="material.soft_silk",
        dimension="material",
        name="柔光丝绸",
        aliases=["Soft Silk", "真丝"],
        definition="细腻柔软且随褶皱产生连续高光的织物。",
        visual_effect="优雅、轻盈、具有高级服装和静物摄影质感。",
        prompt_text="丝绸呈现细腻连续的柔光反射，褶皱自然受重力影响，高光随布料走向变化而不过度塑料化",
        tags=["服装", "织物", "优雅"],
    ),
    VisualDnaElement(
        id="material.natural_skin",
        dimension="material",
        name="自然皮肤质感",
        aliases=["Natural Skin Texture", "真实肤质"],
        definition="保留皮肤微纹理、自然色差和受光变化，避免蜡像磨皮。",
        visual_effect="人物更真实、有生命感，适合商业人像和叙事镜头。",
        prompt_text="皮肤保留自然微纹理、细小色差和真实受光变化，妆容精致但不磨成蜡像或塑料表面",
        tags=["人像", "真实", "皮肤"],
    ),
    VisualDnaElement(
        id="emotion.warm_healing",
        dimension="emotion",
        name="温暖治愈",
        aliases=["Warm Healing", "治愈感"],
        definition="通过松弛姿态、柔和关系和安全氛围传递情绪安定。",
        visual_effect="亲近、舒展、值得停留，适合生活方式与情感叙事。",
        prompt_text="人物状态与环境关系传递温暖、松弛和安全感，情绪自然克制，不使用夸张笑容或表演式煽情",
        tags=["温暖", "生活方式", "情感"],
    ),
    VisualDnaElement(
        id="emotion.mystery_tension",
        dimension="emotion",
        name="神秘张力",
        aliases=["Mystery and Tension", "悬念感"],
        definition="让关键信息部分隐藏或延迟揭示，建立未知与期待。",
        visual_effect="危险、悬疑、引人继续观看，适合剧情关键帧。",
        prompt_text="通过受控遮挡、视线方向和未完全揭示的环境信息建立神秘张力，避免依赖廉价恐怖元素",
        tags=["悬疑", "剧情", "张力"],
    ),
    VisualDnaElement(
        id="emotion.heroic_confidence",
        dimension="emotion",
        name="坚定主角感",
        aliases=["Heroic Confidence", "大女主气质"],
        definition="主体呈现明确目标、稳定重心和不依赖夸张动作的自信。",
        visual_effect="有力量、有领导感，适合角色海报和品牌主视觉。",
        prompt_text="主体姿态稳定、目光明确、重心有力量，以克制自信而非夸张攻击性建立主角气质",
        tags=["角色", "力量", "自信"],
    ),
    VisualDnaElement(
        id="environment.ocean_breeze",
        dimension="environment",
        name="海风环境",
        aliases=["Ocean Breeze", "海边微风"],
        definition="海岸环境中的持续轻风影响发丝、织物、雾气和空气通透度。",
        visual_effect="自由、流动、夏日电影感，并让静态人物产生自然动态。",
        prompt_text="海岸轻风持续影响发丝和轻薄织物，空气通透并带细微海雾，动作方向保持一致",
        tags=["海边", "风", "旅行", "夏日"],
    ),
    VisualDnaElement(
        id="environment.industrial_depth",
        dimension="environment",
        name="工业空间纵深",
        aliases=["Industrial Depth", "工厂纵深"],
        definition="利用生产线、设备通道、管线和重复结构建立工业空间透视。",
        visual_effect="规模、秩序、制造实力与可信的场景深度。",
        prompt_text="真实工业空间以设备、管线和通道形成连续透视纵深，现场整洁有秩序，避免科幻飞船或脏乱作坊感",
        tags=["工业", "工厂", "品牌实力"],
    ),
    VisualDnaElement(
        id="environment.urban_rain_night",
        dimension="environment",
        name="城市雨夜",
        aliases=["Urban Rain Night", "雨夜街头"],
        definition="夜间城市、湿润路面、雨雾和局部人工光共同构成环境。",
        visual_effect="现代、孤独、具有反射层次和城市叙事感。",
        prompt_text="城市雨夜中路面湿润并产生真实局部反射，雨雾受光可见但不过度，环境灯光有明确来源",
        tags=["城市", "夜景", "雨", "电影感"],
    ),
    VisualDnaElement(
        id="narrative.before_departure",
        dimension="narrative",
        name="出发之前",
        aliases=["Before Departure", "启程前"],
        definition="人物或物体已完成准备，但关键行动尚未真正发生的瞬间。",
        visual_effect="包含期待、克制和方向性，让单帧画面拥有前后故事。",
        prompt_text="画面捕捉正式出发前的短暂停顿：准备已完成、行动尚未发生，通过人物视线和随身物品暗示下一步",
        tags=["旅行", "期待", "叙事时刻"],
    ),
    VisualDnaElement(
        id="narrative.product_launch",
        dimension="narrative",
        name="产品首次亮相",
        aliases=["Product Reveal", "新品发布"],
        definition="核心产品第一次被正式展示并成为所有视觉信息的中心。",
        visual_effect="期待、权威、新鲜，适合新品发布和品牌英雄图。",
        prompt_text="以产品首次正式亮相的叙事时刻组织画面，产品是唯一核心信息，灯光与环境共同完成揭幕感",
        tags=["产品", "发布", "商业"],
    ),
    VisualDnaElement(
        id="constraint.preserve_identity",
        dimension="constraint",
        name="保持人物身份一致",
        aliases=["Preserve Identity", "锁定人物"],
        definition="编辑或重绘时保留参考人物的核心身份特征。",
        visual_effect="跨画面角色保持可识别的一致性。",
        prompt_text="保持参考人物身份一致",
        tags=["人物一致性", "编辑"],
        constraints=["保持人物面部结构、年龄段、发型主轮廓和主要识别特征一致。"],
    ),
    VisualDnaElement(
        id="constraint.preserve_product",
        dimension="constraint",
        name="保持产品与包装一致",
        aliases=["Preserve Product", "锁定包装"],
        definition="编辑或风格化时保留产品形态、包装结构与可见品牌信息。",
        visual_effect="风格变化不破坏商品真实性和商业识别。",
        prompt_text="保持参考产品与包装一致",
        tags=["产品一致性", "包装", "编辑"],
        constraints=["保持产品外形、包装比例、主色、品牌文字和核心图案一致，不得重新设计。"],
    ),
    VisualDnaElement(
        id="constraint.no_extra_people",
        dimension="constraint",
        name="禁止新增人物",
        aliases=["No Extra People", "不新增人物"],
        definition="生成或编辑过程中不得添加未要求的人物。",
        visual_effect="控制主体数量，避免模型用路人填充场景。",
        prompt_text="不要新增未要求的人物",
        tags=["主体数量", "约束"],
        constraints=["除用户明确描述或参考图已有的人物外，不新增其他人物、脸或肢体。"],
    ),
)

_ELEMENTS_BY_ID = {element.id: element for element in _ELEMENTS}
_DIMENSION_ORDER = {dimension.id: index for index, dimension in enumerate(_DIMENSIONS)}
_DIMENSION_NAMES = {dimension.id: dimension.name for dimension in _DIMENSIONS}


def list_visual_dna_dimensions() -> list[VisualDnaDimensionInfo]:
    counts: dict[str, int] = defaultdict(int)
    for element in _ELEMENTS:
        if element.status == "enabled":
            counts[element.dimension] += 1
    return [
        dimension.model_copy(update={"element_count": counts[dimension.id]})
        for dimension in _DIMENSIONS
    ]


def list_visual_dna_elements(
    *,
    dimension: VisualDnaDimension | None = None,
    query: str | None = None,
) -> list[VisualDnaElement]:
    elements = [element for element in _ELEMENTS if element.status == "enabled"]
    if dimension:
        elements = [element for element in elements if element.dimension == dimension]
    normalized_query = (query or "").strip().casefold()
    if normalized_query:
        elements = [
            element
            for element in elements
            if normalized_query
            in " ".join(
                [
                    element.id,
                    element.name,
                    element.definition,
                    element.visual_effect,
                    *element.aliases,
                    *element.tags,
                ]
            ).casefold()
        ]
    return sorted(
        elements,
        key=lambda element: (_DIMENSION_ORDER[element.dimension], element.id),
    )


def _prompt_text_for(
    element: VisualDnaElement,
    *,
    provider_id: str,
    model_id: str,
) -> str:
    exact_key = "/".join(part for part in (provider_id, model_id) if part)
    if exact_key and exact_key in element.model_overrides:
        return element.model_overrides[exact_key]
    if provider_id and provider_id in element.model_overrides:
        return element.model_overrides[provider_id]
    return element.prompt_text


def _weight_label(weight: float) -> str:
    if weight >= 0.85:
        return "强"
    if weight >= 0.5:
        return "中"
    return "轻"


def compile_visual_dna(request: VisualDnaCompileRequest) -> CompiledVisualDna:
    """Resolve selections, detect conflicts, and build a structured appendix."""

    normalized: list[VisualDnaSelection] = []
    selected_ids: set[str] = set()
    elements: list[VisualDnaElement] = []
    warnings: list[str] = []

    for selection in request.selections:
        if selection.element_id in selected_ids:
            continue
        element = _ELEMENTS_BY_ID.get(selection.element_id)
        if not element or element.status != "enabled":
            warnings.append(f"未知或已停用的视觉元素：{selection.element_id}")
            continue
        selected_ids.add(selection.element_id)
        normalized.append(selection)
        elements.append(element)

    emitted_conflicts: set[tuple[str, str]] = set()
    for element in elements:
        for conflict_id in element.conflicts_with:
            if conflict_id not in selected_ids:
                continue
            pair = tuple(sorted((element.id, conflict_id)))
            if pair in emitted_conflicts:
                continue
            emitted_conflicts.add(pair)
            warnings.append(f"视觉元素存在冲突：{pair[0]} 与 {pair[1]}")

    selection_by_id = {selection.element_id: selection for selection in normalized}
    grouped: dict[VisualDnaDimension, list[str]] = defaultdict(list)
    constraints: list[str] = []
    for value in request.constraints:
        cleaned = value.strip()
        if cleaned and cleaned not in constraints:
            constraints.append(cleaned)

    for element in elements:
        selection = selection_by_id[element.id]
        if element.dimension != "constraint":
            prompt_text = _prompt_text_for(
                element,
                provider_id=request.provider_id.strip(),
                model_id=request.model_id.strip(),
            )
            note = selection.note.strip()
            line = f"{element.name}（{_weight_label(selection.weight)}）：{prompt_text}"
            if note:
                line += f"；本次补充：{note}"
            grouped[element.dimension].append(line)
        for value in element.constraints:
            cleaned = value.strip()
            if cleaned and cleaned not in constraints:
                constraints.append(cleaned)

    sections: list[str] = []
    for dimension in _DIMENSIONS:
        lines = grouped.get(dimension.id, [])
        if lines:
            sections.append(f"【{_DIMENSION_NAMES[dimension.id]}】\n" + "\n".join(lines))
    if constraints:
        sections.append("【必须遵守的视觉约束】\n" + "\n".join(f"- {item}" for item in constraints))

    return CompiledVisualDna(
        selections=normalized,
        elements=elements,
        prompt_appendix="\n\n".join(sections),
        constraints=constraints,
        warnings=warnings,
    )
