# -*- coding: utf-8 -*-
"""AIGC Studio APIs for infinite-canvas creative workflows."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import time
import uuid
from base64 import b64decode, b64encode
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse, urlunparse

import httpx
from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...aigc.workflow_compiler import CompiledWorkflow
from ...aigc.workflow_contract import workflow_node_registry
from ...aigc.visual_dna import (
    CompiledVisualDna,
    VisualDnaCompileRequest,
    VisualDnaDimension,
    VisualDnaDimensionInfo,
    VisualDnaElementList,
    VisualDnaSelection,
    compile_visual_dna,
    list_visual_dna_dimensions,
    list_visual_dna_elements,
)
from ...constant import SECRET_DIR, WORKING_DIR
from ..aigc.models import (
    JobStatus,
    CanvasNode,
    CanvasEdge,
    CanvasViewport,
    CanvasUpsert,
    Canvas,
    CanvasList,
    AigcCapabilityInfo,
    AigcCategoryDefaults,
    CapabilityList,
    WorkflowAvailableModel,
    WorkflowNodeCapability,
    WorkflowCapabilityCatalog,
    AigcJobCreate,
    AigcAsset,
    AigcJob,
    JobList,
    AssetList,
)
from ..aigc.resource_store import AigcResourceError, AigcResourceStore
from ..chat_access import current_user_id, is_admin_request
from ..object_storage import get_object_storage_client
from ..runtime.event_bus import RuntimeEvent, get_runtime_event_bus

router = APIRouter(prefix="/aigc-studio", tags=["aigc-studio"])
public_router = APIRouter(prefix="/aigc-studio", tags=["aigc-studio"])
logger = logging.getLogger(__name__)

STUDIO_ROOT = WORKING_DIR / "aigc_studio"
_JOB_RUN_TASKS: dict[str, asyncio.Task[AigcJob]] = {}
_ASSET_FILE_URL_RE = re.compile(r"/aigc-studio/assets/([^/]+)/file")
_IMAGE_RESOLUTION_LONG_EDGE = {
    "1k": 1024,
    "2k": 2048,
    "3k": 3072,
    "4k": 4096,
}
_SEEDREAM_RECOMMENDED_SIZES = {
    "2k": {
        "1:1": "2048x2048",
        "4:3": "2304x1728",
        "3:4": "1728x2304",
        "16:9": "2848x1600",
        "9:16": "1600x2848",
        "3:2": "2496x1664",
        "2:3": "1664x2496",
        "21:9": "3136x1344",
        "9:21": "1344x3136",
    },
    "3k": {
        "1:1": "3072x3072",
        "4:3": "3456x2592",
        "3:4": "2592x3456",
        "16:9": "4096x2304",
        "9:16": "2304x4096",
        "3:2": "3744x2496",
        "2:3": "2496x3744",
        "21:9": "4704x2016",
        "9:21": "2016x4704",
    },
    "4k": {
        "1:1": "4096x4096",
        "4:3": "4704x3520",
        "3:4": "3520x4704",
        "16:9": "5504x3040",
        "9:16": "3040x5504",
        "3:2": "4992x3328",
        "2:3": "3328x4992",
        "21:9": "6240x2656",
        "9:21": "2656x6240",
    },
}

AigcCapability = Literal[
    "text_to_image",
    "image_edit",
    "image_to_image",
    "mask_edit",
    "reference_image",
    "text_to_video",
    "image_to_video",
    "reference_video",
    "text_to_audio",
    "storyboard",
]

SUPPORTED_AIGC_CAPABILITIES = {
    "text_to_image",
    "image_edit",
    "image_to_image",
    "mask_edit",
    "reference_image",
    "text_to_video",
    "image_to_video",
    "reference_video",
    "text_to_audio",
    "storyboard",
}
TEXT_MODEL_CAPABILITY_ALIASES = {
    "storyboard",
}
TEXT_MODEL_CAPABILITY_ALIASES_COMPACT = {
    item.replace("_", "") for item in TEXT_MODEL_CAPABILITY_ALIASES
}
OUTPUT_GENERATION_CAPABILITIES = {
    "text_to_image",
    "image_edit",
    "image_to_image",
    "mask_edit",
    "text_to_video",
    "image_to_video",
    "text_to_audio",
}



class AssetSignedUrl(BaseModel):
    url: str
    expires_in: int
    provider: Literal["aliyun_oss"]


class AssetDirectUploadRequest(BaseModel):
    filename: str = "asset"
    mime_type: str = "application/octet-stream"
    size: int | None = None


class AssetDirectUploadPrepare(BaseModel):
    asset_id: str
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    token: str


class AssetDirectUploadComplete(BaseModel):
    asset_id: str
    token: str


class LongImageExportRequest(BaseModel):
    canvas_id: str
    node_id: str
    width: int = Field(default=750, ge=320, le=1440)
    slice_height: int = Field(default=1400, ge=320, le=5000)


class LongImageExportResult(BaseModel):
    full_asset: AigcAsset
    slice_assets: list[AigcAsset]
    width: int
    height: int
    slice_height: int
    section_count: int


StyleTemplateType = Literal["style", "play"]
StyleTemplateRuntimeMode = Literal["native_effect", "prompt_style"]
StyleTemplateStatus = Literal["enabled", "disabled"]


class AigcStyleTemplate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    type: StyleTemplateType = "style"
    provider: str = "internal"
    model_family: str | None = None
    cover_url: str | None = None
    category: str = "推荐"
    tags: list[str] = Field(default_factory=list)
    keywords: str = ""
    description: str = ""
    supplemental_prompt: str = ""
    prompt_template: str = ""
    visual_dna: list[VisualDnaSelection] = Field(default_factory=list)
    reference_image_urls: list[str] = Field(default_factory=list)
    profile_version: str = "1.0"
    commercial: bool = False
    runtime_mode: StyleTemplateRuntimeMode = "prompt_style"
    effect_template_uuid: str | None = None
    effect_id: int | None = None
    use_count: int = 0
    favorite: bool = False
    status: StyleTemplateStatus = "enabled"
    created_at: str | None = None
    updated_at: str | None = None
    last_used_at: str | None = None


class StyleTemplateList(BaseModel):
    templates: list[AigcStyleTemplate]


class VisualDnaDimensionList(BaseModel):
    dimensions: list[VisualDnaDimensionInfo]


class StyleTemplateFavoriteUpdate(BaseModel):
    favorite: bool = True


class AigcStyleTemplateUpdate(BaseModel):
    title: str | None = None
    type: StyleTemplateType | None = None
    provider: str | None = None
    model_family: str | None = None
    cover_url: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    keywords: str | None = None
    description: str | None = None
    supplemental_prompt: str | None = None
    prompt_template: str | None = None
    visual_dna: list[VisualDnaSelection] | None = None
    reference_image_urls: list[str] | None = None
    profile_version: str | None = None
    commercial: bool | None = None
    runtime_mode: StyleTemplateRuntimeMode | None = None
    favorite: bool | None = None
    status: StyleTemplateStatus | None = None


BRAND_STRENGTH_POSTER_PROMPT = """高端品牌实力海报

【风格气质】
高端、沉稳、工业质感、品牌大片感。强调制造实力、产品前景和高端品牌背书，但只控制画面气质，不规定具体排版。
现代化车间、生产线、金属管道、洁净厂区、设备纵深通道等可以作为氛围来源；画面需要空间纵深、电影级光束、暗部层次、金属质感和克制的香槟金点缀。
产品和场景要自然融合，像商业摄影后期合成：有接触阴影、反光、局部遮挡和统一色调。
文字气质要接近品牌发布会、工业大片、企业实力海报，厚重克制，不要古风书法、廉价金属浮雕或直播间电商感。

【避免】
不要把产品放进生硬的浅色矩形卡片，不要上下割裂成模板分区，不要大红大绿、土豪金、促销贴纸、夸张科幻或脏乱工厂。""".strip()


GENERAL_IMAGE_CONTENT_PROMPT_TEMPLATE = """【画面内容】
画面主体：{请填写人物、产品或主要对象}
主体状态：{请填写姿态、动作、表情、摆放方式或产品展示角度}
场景背景：{请填写地点、时间、环境、道具或空间关系}
画面用途：{如：海报、封面、头像、商品图、社媒配图}

【文字内容】
画面文字：{如无需文字请写：无}

【参考素材】
参考图说明：{说明上传的产品图、人物图、logo 或参考图如何使用；没有就写无}

【补充要求】
{请填写需要保留/避免的主体、文字、构图或其他细节}""".strip()


BRAND_STRENGTH_POSTER_IMAGE_PROMPT_TEMPLATE = """高端品牌实力海报

【画面内容】
画面主体：{请填写产品、包装、品牌主视觉或需要展示的核心对象}
产品名称：{产品名称}
场景背景：{如：现代化车间、生产线、源头产地、产品展台}
画面用途：{如：品牌实力海报、生产实力海报、产品背书海报}

【文字内容】
品牌名称：{品牌名称}
主标题：{主标题}
副标题：{副标题}
卖点1：{卖点1}
卖点2：{卖点2}
卖点3：{卖点3}
品牌精神：{品牌精神}

【参考素材】
参考图说明：{说明产品图、包装图、logo 或参考图如何使用；没有就写无}

【补充要求】
{请填写需要保留/避免的主体、文字、包装信息或构图要求}""".strip()


FACTORY_HERO_POSTER_PROMPT = """巨幅标题工厂背书海报

【风格气质】
深黑与香槟金主调，工业大片质感，真实生产车间纵深，顶部电影光束，金属管道与设备反光，巨幅标题压迫感，品牌实力背书，高端稳重。
产品需要像真实商业摄影前景：有展台光环、接触阴影、反光、统一光色和空间遮挡，不要像平面贴图。
右侧卖点适合使用徽章、月桂、线性工业图标或荣誉感图形，整体要像品牌制造实力发布海报。

【避免】
不要电商促销感，不要浅色矩形卡片分区，不要把产品嵌入孤立白底框，不要虚构健康、无害、销量、排名、认证或工厂规模。""".strip()


FACTORY_HERO_POSTER_IMAGE_PROMPT_TEMPLATE = """巨幅标题工厂背书海报

【画面内容】
画面主体：{请填写产品、包装或品牌主视觉}
核心视觉：产品作为左下前景英雄位，放在金色展台或光环底座上，与工厂背景自然融合
背景场景：{如：现代化生产车间、自动化管道、两省三厂生产基地、设备纵深通道}
画面用途：{如：制造实力海报、品牌背书海报、招商海报、生产实力海报}

【文字内容】
品牌名称：{品牌名称}
主标题：{如：两省三厂}
副标题：{如：千亩级智能生产集群}
横幅短句：{如：智能制造 · 品质如一 · 匠心传承}
卖点1：{如：两省三厂}
卖点1说明：{如：规模领先}
卖点2：{如：智能生产}
卖点2说明：{如：品质如一}
卖点3：{如：精选原果}
卖点3说明：{如：地道湘潭味}
底部收束语：{如：匠心制造 品质传承}

【参考素材】
参考图说明：{说明产品包装、logo 或参考海报如何使用；没有就写无}

【构图要求】
9:16 竖版海报。顶部强视觉主标题，中部真实工厂纵深，左下产品英雄位，右侧三个徽章卖点，底部品牌收束语。
产品必须有真实接触阴影、反光和统一光色，不要放进白色矩形卡片。

【补充要求】
{请填写需要保留/避免的包装信息、文字、主体或构图要求}""".strip()


def _poster_scene_prompt_template(title: str) -> str:
    return f"""{title}

【画面内容】
画面主体：{{请填写产品、人物、空间或核心展示对象}}
产品名称：{{产品名称}}
场景背景：{{请填写具体地点、使用场景、活动场景或环境元素}}
画面用途：{{如：朋友圈海报、招商海报、新品发布图、门店物料}}

【文字内容】
品牌名称：{{品牌名称}}
主标题：{{主标题}}
副标题：{{副标题}}
卖点1：{{卖点1}}
卖点2：{{卖点2}}
卖点3：{{卖点3}}
收束语：{{收束语}}

【参考素材】
参考图说明：{{说明产品图、包装图、logo 或参考图如何使用；没有就写无}}

【补充要求】
{{请填写需要保留/避免的主体、文字、包装信息或构图要求}}""".strip()


POSTER_SCENE_STYLE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "style-product-selling-points-poster",
        "title": "产品卖点海报",
        "keywords": "产品卖点海报, 核心利益点, 产品特写, 商业摄影, 功能卖点, 口味卖点, 包装质感",
        "description": """产品卖点海报

【风格气质】
产品中心、商业摄影、包装质感清晰，突出产品核心利益点、口味特点或包装亮点。画面要干净、有购买理由和高级棚拍感。

【避免】
不要堆满卖点文字，不要直播间电商感，不要自行编造价格、功效承诺、认证、销量、排名或包装文字。""".strip(),
    },
    {
        "id": "style-source-ingredient-poster",
        "title": "源头原料海报",
        "keywords": "源头原料海报, 原料产地, 采摘, 筛选, 自然质感, 源头选料, 食材溯源",
        "description": """源头原料海报

【风格气质】
原料产地、采摘、筛选、源头选料和自然质感。整体干净、可信、有自然高级感，让产品和原料形成来源关系。

【避免】
不要乡土杂乱、廉价农贸市场感，不要自行编造产地、认证、年份、检测结论或绝对化功效。""".strip(),
    },
    {
        "id": "style-process-flow-poster",
        "title": "工艺流程海报",
        "keywords": "工艺流程海报, 步骤编号或流程线, 生产工艺, 多道工序, 品控流程, 制造流程",
        "description": """工艺流程海报

【风格气质】
步骤编号或流程线、多道工序、品控流程和标准化制造能力。视觉要专业、克制、可信，可以带洁净车间、设备局部或半透明流程层气质。

【避免】
不要复杂到影响阅读，不要编造具体技术参数、检测结果、专利或认证。""".strip(),
    },
    {
        "id": "style-channel-recruitment-poster",
        "title": "招商渠道海报",
        "keywords": "招商渠道海报, 渠道政策, 供货能力, 代理招商, 终端支持, 合作背书",
        "description": """招商渠道海报

【风格气质】
商务招商物料或品牌渠道发布页气质，稳重、可信、有规模感。适合表达渠道政策、供货能力、代理招商、终端支持和合作背书。

【避免】
不要承诺收益、保本、稳赚、第一、唯一等夸大表达，不要自行生成电话、二维码、地址、价格或招商政策细则。""".strip(),
    },
    {
        "id": "style-new-product-launch-poster",
        "title": "新品发布海报",
        "keywords": "新品发布海报, 新品发布会, 首发上市, 产品英雄图, 发布会灯光, 上新",
        "description": """新品发布海报

【风格气质】
新品发布会、首发上市、产品英雄图、发布会灯光和舞台聚焦感。画面要有期待感、新鲜感和高级棚拍质感。

【避免】
不要变成促销清仓图，不要自行编造上市日期、价格、限量数量或联名信息。""".strip(),
    },
    {
        "id": "style-festival-promotion-poster",
        "title": "节日促销海报",
        "keywords": "节日促销海报, 节日氛围, 限时活动, 礼盒, 节庆, 促销转化, 高级活动海报",
        "description": """节日促销海报

【风格气质】
节日氛围、限时活动、礼盒推荐和高级活动海报感。节庆元素做氛围辅助，整体克制、清楚、有转化感。

【避免】
不要大红大绿、爆炸贴、直播间促销感，不要自行编造折扣、赠品、倒计时或活动承诺。""".strip(),
    },
    {
        "id": "style-social-seeding-poster",
        "title": "朋友圈种草海报",
        "keywords": "朋友圈种草海报, 真实生活方式场景, 日常分享, 轻种草, 社交传播, 生活化产品图",
        "description": """朋友圈种草海报

【风格气质】
真实生活方式场景、日常分享、轻种草和社交传播感。画面亲切、有质感、像真实分享，产品自然出现。

【避免】
不要企业通稿感、过度工业化、夸张功效、虚假用户评价、聊天截图或未经提供的人物背书。""".strip(),
    },
    {
        "id": "style-store-display-poster",
        "title": "门店陈列海报",
        "keywords": "门店陈列海报, 门店货架, 收银台, 陈列端架, 终端展示, 到店购买, 陈列氛围",
        "description": """门店陈列海报

【风格气质】
门店货架、收银台、陈列端架、终端展示和到店购买氛围。产品清晰可识别，陈列整齐，有真实终端环境质感。

【避免】
不要杂乱小卖部感，不要自行生成门店地址、价格标签、二维码、电话或活动规则。""".strip(),
    },
]


DEFAULT_STYLE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "style-cgv2",
        "title": "一键国漫CGV2",
        "type": "style",
        "provider": "libtv",
        "model_family": "seedream-4.5",
        "cover_url": None,
        "category": "推荐",
        "tags": ["推荐", "商用"],
        "keywords": "国漫, CG, 角色海报, 冷色调, 金属质感",
        "description": "国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。",
        "prompt_template": f"""一键国漫CGV2

{GENERAL_IMAGE_CONTENT_PROMPT_TEMPLATE}""".strip(),
        "commercial": True,
        "runtime_mode": "native_effect",
        "effect_template_uuid": "dbc6dfc0990d46d28215bcdff87d53c3",
        "effect_id": 22910748,
        "use_count": 3300,
        "status": "enabled",
    },
    {
        "id": "style-film",
        "title": "电影感",
        "type": "style",
        "provider": "internal",
        "model_family": None,
        "cover_url": None,
        "category": "推荐",
        "tags": ["常用", "商用"],
        "keywords": "电影感, 戏剧光影, 景深, 对比色",
        "description": "电影级光影与景深，强调主体叙事和画面氛围。",
        "prompt_template": f"""电影感

{GENERAL_IMAGE_CONTENT_PROMPT_TEMPLATE}""".strip(),
        "visual_dna": [
            {"element_id": "art_direction.cinematic_realism", "weight": 0.9},
            {"element_id": "lighting.cinematic_contrast", "weight": 0.95},
            {"element_id": "color.teal_orange_controlled", "weight": 0.65},
            {"element_id": "emotion.mystery_tension", "weight": 0.55},
        ],
        "commercial": True,
        "runtime_mode": "prompt_style",
        "use_count": 3300,
        "status": "enabled",
    },
    {
        "id": "style-premium-industrial-editorial",
        "title": "高端工业品牌大片",
        "type": "style",
        "provider": "internal",
        "model_family": None,
        "cover_url": None,
        "category": "电商营销",
        "tags": ["品牌", "工业", "商用"],
        "keywords": "高端工业, 品牌大片, 制造质感, 香槟金, 金属",
        "description": "高端工业品牌大片审美，强调电影级光影、金属质感、空间纵深与克制的香槟金点缀。",
        "prompt_template": "",
        "visual_dna": [
            {"element_id": "art_direction.premium_editorial", "weight": 0.9},
            {"element_id": "lighting.cinematic_contrast", "weight": 0.85},
            {"element_id": "material.brushed_metal", "weight": 0.7},
            {"element_id": "environment.industrial_depth", "weight": 0.85},
            {"element_id": "emotion.heroic_confidence", "weight": 0.65},
        ],
        "commercial": True,
        "runtime_mode": "prompt_style",
        "use_count": 0,
        "status": "enabled",
    },
    {
        "id": "style-brand-strength-poster",
        "title": "高端品牌实力海报",
        "type": "play",
        "provider": "internal",
        "model_family": None,
        "cover_url": None,
        "category": "海报场景",
        "tags": ["品牌", "产品", "商用"],
        "keywords": "高端品牌实力海报, 生产实力海报, 产品背书海报, 源头工艺海报, 制造实力, 产品前景, 高端品牌背书",
        "description": BRAND_STRENGTH_POSTER_PROMPT,
        "prompt_template": BRAND_STRENGTH_POSTER_IMAGE_PROMPT_TEMPLATE,
        "commercial": True,
        "runtime_mode": "prompt_style",
        "use_count": 0,
        "status": "enabled",
    },
    {
        "id": "style-factory-hero-poster",
        "title": "巨幅标题工厂背书海报",
        "type": "play",
        "provider": "internal",
        "model_family": None,
        "cover_url": None,
        "category": "海报场景",
        "tags": ["制造实力", "品牌", "商用"],
        "keywords": "巨幅标题工厂背书海报, 两省三厂, 制造实力, 智能生产, 工厂纵深, 产品英雄位, 右侧徽章卖点, 香槟金",
        "description": FACTORY_HERO_POSTER_PROMPT,
        "prompt_template": FACTORY_HERO_POSTER_IMAGE_PROMPT_TEMPLATE,
        "commercial": True,
        "runtime_mode": "prompt_style",
        "use_count": 0,
        "status": "enabled",
    },
    *[
        {
            **template,
            "type": "play",
            "provider": "internal",
            "model_family": None,
            "cover_url": None,
            "category": "海报场景",
            "tags": ["海报场景", "商用"],
            "prompt_template": _poster_scene_prompt_template(str(template["title"])),
            "commercial": True,
            "runtime_mode": "prompt_style",
            "use_count": 0,
            "status": "enabled",
        }
        for template in POSTER_SCENE_STYLE_TEMPLATES
    ],
]
DEFAULT_STYLE_TEMPLATE_IDS = {
    str(template["id"]) for template in DEFAULT_STYLE_TEMPLATES
}
REFERENCE_IMAGE_PRESERVATION_PROMPT = (
    "参考图使用规则：已上传或连接的参考图优先作为主体、产品或构图参考。"
    "生成时必须保留参考图主体的外形、主色、比例和主要识别元素；"
    "如果参考图是产品或包装，必须保留品牌文字、核心图案和包装结构。"
    "风格只影响背景、光影、版式和氛围，不要把参考图主体替换成无关示意物或重新设计。"
)
STYLE_REFERENCE_IMAGE_PROMPT = (
    "风格参考图使用规则：风格参考图只用于理解整体艺术方向、光影、色彩、材质和氛围，"
    "不要复制其中的具体人物、产品、文字、标志、构图或场景内容。"
)
ANNOTATION_IMAGE_EDITING_PROMPT = (
    "标注使用规则：标注图中的红色圈选、画笔、框选或文字只表示需要编辑的区域和意图，"
    "不是最终画面内容。生成时不要保留标注线条、标注颜色或标注文字；"
    "只在被标注区域执行用户指令，未标注区域尽量保持原图。"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dir(name: str) -> Path:
    try:
        return _resource_store(STUDIO_ROOT).directory(name)
    except AigcResourceError as exc:
        raise _resource_http_error(exc) from exc


@lru_cache(maxsize=16)
def _resource_store(root: Path) -> AigcResourceStore:
    return AigcResourceStore(root)


def _resource_http_error(error: AigcResourceError) -> HTTPException:
    if error.code == "RESOURCE_NOT_FOUND":
        return HTTPException(status_code=404, detail="AIGC Studio resource not found")
    if error.code == "CORRUPT_RESOURCE":
        return HTTPException(status_code=500, detail=f"Corrupt Studio file: {error.resource_name}")
    return HTTPException(status_code=400, detail="Invalid AIGC Studio resource id")


def _safe_id(item_id: str) -> str:
    try:
        return AigcResourceStore.safe_id(item_id)
    except AigcResourceError as exc:
        raise _resource_http_error(exc) from exc


def _json_path(kind: str, item_id: str) -> Path:
    try:
        return _resource_store(STUDIO_ROOT).path(kind, item_id)
    except AigcResourceError as exc:
        raise _resource_http_error(exc) from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return _resource_store(STUDIO_ROOT).read_path(path)
    except AigcResourceError as exc:
        raise _resource_http_error(exc) from exc


def _write_json(path: Path, payload: BaseModel | dict[str, Any]) -> None:
    data = payload.model_dump() if isinstance(payload, BaseModel) else payload
    try:
        _resource_store(STUDIO_ROOT).write_path(path, data)
    except AigcResourceError as exc:
        raise _resource_http_error(exc) from exc


def _delete_json(path: Path) -> None:
    try:
        _resource_store(STUDIO_ROOT).delete_path(path)
    except AigcResourceError as exc:
        raise _resource_http_error(exc) from exc


def _should_refresh_builtin_prompt_template(template: AigcStyleTemplate) -> bool:
    prompt_template = template.prompt_template.strip()
    if not prompt_template:
        return True
    if prompt_template == template.description.strip():
        return True
    return any(
        marker in prompt_template
        for marker in (
            "【风格约束】",
            "【画面要求】",
            "【视觉风格】",
            "不要复刻原图构图、字体、光线、产品角度、文字内容或具体排版。",
        )
    )


def _ensure_default_style_templates() -> None:
    now = _now()
    for payload in DEFAULT_STYLE_TEMPLATES:
        template_path = _style_template_path(str(payload["id"]))
        if template_path.exists():
            existing = AigcStyleTemplate(**_read_json(template_path))
            refreshed = AigcStyleTemplate.model_validate(
                {
                    **existing.model_dump(),
                    **payload,
                    "created_at": existing.created_at or now,
                    "updated_at": existing.updated_at or now,
                    "last_used_at": existing.last_used_at,
                    "use_count": existing.use_count,
                    "favorite": existing.favorite,
                    "cover_url": existing.cover_url or payload.get("cover_url"),
                    "prompt_template": (
                        payload.get("prompt_template", "")
                        if _should_refresh_builtin_prompt_template(existing)
                        else existing.prompt_template
                    ),
                    "status": (
                        "disabled"
                        if existing.status == "disabled"
                        else payload.get("status", existing.status)
                    ),
                },
            )
            if refreshed.model_dump() != existing.model_dump():
                refreshed = refreshed.model_copy(update={"updated_at": now})
                _write_json(template_path, refreshed)
            continue
        template = AigcStyleTemplate(
            **{
                **payload,
                "created_at": now,
                "updated_at": now,
            },
        )
        _write_json(template_path, template)


def _style_template_path(template_id: str) -> Path:
    return _json_path("style_templates", template_id)


def _load_style_template(template_id: str) -> AigcStyleTemplate:
    _ensure_default_style_templates()
    return AigcStyleTemplate(**_read_json(_style_template_path(template_id)))


def _save_style_template(template: AigcStyleTemplate) -> AigcStyleTemplate:
    now = _now()
    payload = template.model_copy(
        update={
            "created_at": template.created_at or now,
            "updated_at": now,
        },
    )
    _write_json(_style_template_path(payload.id), payload)
    return payload


def _style_template_is_user_editable(template: AigcStyleTemplate) -> bool:
    return (
        template.id not in DEFAULT_STYLE_TEMPLATE_IDS
        and template.type == "style"
        and template.provider == "internal"
        and template.runtime_mode == "prompt_style"
        and template.category == "我的风格"
    )


def _ensure_editable_style_template(
    template: AigcStyleTemplate,
    request: Request,
) -> None:
    if is_admin_request(request):
        return
    if not _style_template_is_user_editable(template):
        raise HTTPException(
            status_code=403,
            detail="Only user prompt style templates can be edited.",
        )


def _list_style_templates() -> list[AigcStyleTemplate]:
    _ensure_default_style_templates()
    templates: list[AigcStyleTemplate] = []
    for path in sorted(_dir("style_templates").glob("*.json")):
        try:
            templates.append(AigcStyleTemplate(**_read_json(path)))
        except HTTPException:
            continue
    return templates


def _matches_style_template_query(
    template: AigcStyleTemplate,
    *,
    template_type: StyleTemplateType | None,
    model_family: str | None,
    category: str | None,
    q: str | None,
    commercial_only: bool,
) -> bool:
    if template.status != "enabled":
        return False
    if template_type and template.type != template_type:
        return False
    if model_family and template.model_family not in {None, "", model_family}:
        return False
    if commercial_only and not template.commercial:
        return False
    if category and category != "推荐":
        category_text = " ".join([template.category, *template.tags, template.keywords])
        if category not in category_text:
            return False
    if q:
        query = q.casefold()
        haystack = " ".join(
            [
                template.title,
                template.category,
                template.keywords,
                template.description,
                template.prompt_template,
                *template.tags,
            ],
        ).casefold()
        if query not in haystack:
            return False
    return True


def _slice_items(items: list[Any], *, limit: int, offset: int) -> list[Any]:
    safe_offset = max(0, int(offset))
    safe_limit = min(max(1, int(limit)), 500)
    return items[safe_offset : safe_offset + safe_limit]


def get_aigc_studio_diagnostics() -> dict[str, Any]:
    """Return lightweight file-backed AIGC Studio counters."""
    job_status_counts: Counter[str] = Counter()
    corrupt_jobs = 0
    for path in _dir("jobs").glob("*.json"):
        try:
            job_status_counts[str(_read_json(path).get("status") or "unknown")] += 1
        except HTTPException:
            corrupt_jobs += 1
    return {
        "canvas_count": len(list(_dir("canvases").glob("*.json"))),
        "job_count": sum(job_status_counts.values()),
        "job_status_counts": dict(job_status_counts),
        "corrupt_job_count": corrupt_jobs,
        "asset_count": len(list(_dir("assets").glob("*.json"))),
    }


def _load_canvas(canvas_id: str) -> Canvas:
    return Canvas(**_read_json(_json_path("canvases", canvas_id)))


def _load_job(job_id: str) -> AigcJob:
    return AigcJob(**_read_json(_json_path("jobs", job_id)))


def _owned_meta_for_request(
    request: Request,
    meta: dict[str, Any] | None = None,
    *,
    existing_owner: str | None = None,
) -> dict[str, Any]:
    next_meta = dict(meta or {})
    next_meta["owner_user_id"] = existing_owner or current_user_id(request)
    return next_meta


def _canvas_owner_user_id(canvas: Canvas) -> str | None:
    owner = canvas.meta.get("owner_user_id")
    if owner is None:
        owner = canvas.meta.get("user_id")
    if owner is None:
        return None
    owner_text = str(owner).strip()
    return owner_text or None


def _request_owns_canvas(request: Request, canvas: Canvas) -> bool:
    owner = _canvas_owner_user_id(canvas)
    if owner is None:
        return current_user_id(request) == "0" or is_admin_request(request)
    return owner == current_user_id(request)


def _load_canvas_for_request(request: Request, canvas_id: str) -> Canvas:
    canvas = _load_canvas(canvas_id)
    if not _request_owns_canvas(request, canvas):
        raise HTTPException(status_code=404, detail="Canvas not found.")
    return canvas


def provision_super_expert_aigc_workspace(
    *,
    owner_user_id: str,
    material_task_id: str,
    operation_id: str,
    arguments: dict[str, Any],
) -> dict[str, str]:
    """Create the real user-owned canvas and node for one guided task."""
    if not str(owner_user_id).strip() or not str(material_task_id).strip():
        raise ValueError("AIGC workspace ownership is incomplete")
    if operation_id != "aigc.text_to_video.create":
        raise ValueError("AIGC operation cannot be provisioned")
    # Prefix physical identifiers so every generated value remains valid for
    # the shared super-expert domain-id contract even when a UUID starts with
    # a digit.
    canvas_id = f"canvas-{uuid.uuid4()}"
    node_id = f"video-{uuid.uuid4()}"
    now = _now()
    node = CanvasNode(
        id=node_id,
        type="video_generate",
        position={"x": 120.0, "y": 120.0},
        data={
            "title": "视频节点",
            "text": str(arguments["prompt"]),
            "videoMode": "blank",
            "showTryOptions": False,
            "aspectRatio": str(arguments["aspect_ratio"]),
            "videoResolution": "720P",
            "videoDuration": int(arguments["duration_seconds"]),
            "videoAudio": True,
            "videoCount": 1,
            "activeVideoTab": "text_to_video",
            "modelId": str(arguments["model_id"]),
        },
    )
    canvas = Canvas(
        id=canvas_id,
        name=str(arguments["project_name"]),
        nodes=[node],
        edges=[],
        viewport=CanvasViewport(),
        thumbnail=None,
        meta={
            "version": 1,
            "owner_user_id": str(owner_user_id),
            "super_expert_material_task_id": str(material_task_id),
            "super_expert_operation_id": operation_id,
        },
        created_at=now,
        updated_at=now,
    )
    _write_json(_json_path("canvases", canvas_id), canvas)
    return {"canvas_id": canvas_id, "node_id": node_id}


def provision_super_expert_aigc_workflow(
    *,
    owner_user_id: str,
    material_task_id: str,
    compiled: CompiledWorkflow,
) -> Canvas:
    """Persist one fully validated, DClaw-owned workflow canvas."""
    if not str(owner_user_id).strip() or not str(material_task_id).strip():
        raise ValueError("AIGC workspace ownership is incomplete")
    canvas_id = f"canvas-{uuid.uuid4()}"
    now = _now()
    canvas = Canvas(
        id=canvas_id,
        name=compiled.title,
        nodes=[
            CanvasNode(
                id=node.physical_node_id,
                type=node.kind,
                position=node.position,
                data=node.data,
            )
            for node in compiled.nodes
        ],
        edges=[
            CanvasEdge(
                id=edge.edge_id,
                source=edge.source,
                target=edge.target,
                data={"role": edge.target_slot},
            )
            for edge in compiled.edges
        ],
        viewport=CanvasViewport(**compiled.viewport),
        thumbnail=None,
        meta={
            "version": 2,
            "owner_user_id": str(owner_user_id),
            "super_expert_material_task_id": str(material_task_id),
            "workflow_id": compiled.workflow_id,
            "execution_mode": "PREBUILT_WORKFLOW",
        },
        created_at=now,
        updated_at=now,
    )
    _write_json(_json_path("canvases", canvas_id), canvas)
    return canvas


def provision_blank_super_expert_aigc_workspace(
    *,
    owner_user_id: str,
    material_task_id: str,
    workflow_id: str,
    title: str,
) -> Canvas:
    """Create the only valid starting point for an explicit manual fallback."""
    if not all(
        str(value).strip()
        for value in (owner_user_id, material_task_id, workflow_id, title)
    ):
        raise ValueError("AIGC manual workspace binding is incomplete")
    canvas_id = f"canvas-{uuid.uuid4()}"
    now = _now()
    canvas = Canvas(
        id=canvas_id,
        name=str(title),
        nodes=[],
        edges=[],
        viewport=CanvasViewport(),
        thumbnail=None,
        meta={
            "version": 2,
            "owner_user_id": str(owner_user_id),
            "super_expert_material_task_id": str(material_task_id),
            "workflow_id": str(workflow_id),
            "execution_mode": "MANUAL_BUILD",
        },
        created_at=now,
        updated_at=now,
    )
    _write_json(_json_path("canvases", canvas_id), canvas)
    return canvas


def discard_super_expert_aigc_workspace(
    *,
    owner_user_id: str,
    material_task_id: str,
    canvas_id: str,
) -> None:
    """Remove only a just-provisioned, still-unpublished task canvas."""
    try:
        canvas = _load_canvas(canvas_id)
    except HTTPException:
        return
    if (
        _canvas_owner_user_id(canvas) != str(owner_user_id)
        or canvas.meta.get("super_expert_material_task_id") != material_task_id
    ):
        raise ValueError("AIGC workspace cleanup binding mismatch")
    _delete_json(_json_path("canvases", canvas_id))


def resolve_owned_asset_for_workflow(
    owner_user_id: str,
    asset_id: str,
) -> dict[str, Any] | None:
    """Resolve only an existing asset explicitly owned by the target user."""
    if not str(owner_user_id).strip() or not str(asset_id).strip():
        return None
    try:
        asset = AigcAsset(**_read_json(_json_path("assets", asset_id)))
    except HTTPException:
        return None
    owner = asset.meta.get("owner_user_id") or asset.meta.get("user_id")
    if str(owner or "").strip() != str(owner_user_id).strip():
        return None
    return asset.model_dump(mode="json")


def load_super_expert_aigc_workflow_context(
    *,
    canvas_id: str,
    material_task_id: str,
) -> tuple[Canvas | None, list[AigcJob]]:
    """Load only the canvas and jobs bound to one authoritative material task."""
    try:
        canvas = _load_canvas(canvas_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None, []
        raise
    if (
        str(canvas.meta.get("super_expert_material_task_id") or "")
        != str(material_task_id)
    ):
        return None, []
    jobs = [
        AigcJob(**_read_json(path))
        for path in sorted(_dir("jobs").glob("*.json"))
    ]
    return canvas, [job for job in jobs if job.canvas_id == canvas_id]


def _request_can_access_asset(request: Request, asset: AigcAsset) -> bool:
    owner = asset.meta.get("owner_user_id") or asset.meta.get("user_id")
    if owner is not None:
        return str(owner) == current_user_id(request)
    canvas_id = str(asset.meta.get("canvas_id") or "")
    if canvas_id:
        try:
            _load_canvas_for_request(request, canvas_id)
        except HTTPException:
            return False
        return True
    return current_user_id(request) == "0" or is_admin_request(request)


def _load_asset_for_request(request: Request, asset_id: str) -> AigcAsset:
    path = _json_path("assets", asset_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found.")
    asset = AigcAsset(**_read_json(path))
    if not _request_can_access_asset(request, asset):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return asset


def _request_can_access_job(request: Request, job: AigcJob) -> bool:
    try:
        _load_canvas_for_request(request, job.canvas_id)
    except HTTPException:
        return False
    return True


def _load_job_for_request(request: Request, job_id: str) -> AigcJob:
    job = _load_job(job_id)
    if not _request_can_access_job(request, job):
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


async def _find_capability(
    request: Request,
    provider_id: str,
    model_id: str,
    capability: str,
) -> AigcCapabilityInfo | None:
    available = await list_capabilities(request)
    for item in available.capabilities:
        if (
            item.provider_id == provider_id
            and item.model_id == model_id
            and item.capability == capability
        ):
            return item
    return None


async def _find_provider_model(
    request: Request,
    provider_id: str,
    model_id: str,
) -> tuple[Any, Any] | tuple[None, None]:
    manager = getattr(request.app.state, "provider_manager", None)
    if manager is None:
        return None, None
    get_provider = getattr(manager, "get_provider", None)
    runtime_provider = get_provider(provider_id) if callable(get_provider) else None
    if runtime_provider is not None:
        models = list(getattr(runtime_provider, "models", []) or []) + list(
            getattr(runtime_provider, "extra_models", []) or [],
        )
        for model in models:
            if getattr(model, "id", None) == model_id:
                return runtime_provider, model

    for provider in await manager.list_provider_info():
        models = list(getattr(provider, "models", []) or []) + list(
            getattr(provider, "extra_models", []) or [],
        )
        for model in models:
            if (
                getattr(provider, "id", None) == provider_id
                and getattr(model, "id", None) == model_id
            ):
                return provider, model
    return None, None


def _authoritative_workflow_execution_binding(
    canvas_id: str,
    node_id: str,
) -> tuple[str, str, str] | None:
    from .super_expert_platform import get_super_expert_platform_service

    return get_super_expert_platform_service().workflow_node_execution_binding(
        canvas_id=canvas_id,
        node_id=node_id,
    )


async def _validate_job_submission(request: Request, body: AigcJobCreate) -> None:
    canvas = _load_canvas_for_request(request, body.canvas_id)
    target_node = next((node for node in canvas.nodes if node.id == body.node_id), None)
    if target_node is None:
        raise HTTPException(
            status_code=400,
            detail=f"Node '{body.node_id}' not found in canvas '{body.canvas_id}'.",
        )
    authoritative = _authoritative_workflow_execution_binding(
        body.canvas_id,
        body.node_id,
    )
    workflow_marker = str(
        target_node.data.get("workflowLogicalNodeId") or ""
    ).strip()
    if authoritative is not None or workflow_marker:
        expected = authoritative or (
            str(target_node.data.get("providerId") or "").strip(),
            str(target_node.data.get("modelId") or "").strip(),
            str(target_node.data.get("modelCapability") or "").strip(),
        )
        actual = (body.provider_id, body.model_id, body.capability)
        if not all(expected) or actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Workflow-bound node execution mismatch.",
            )
    await _assert_job_model_policy_allowed(request, body)
    capability = await _find_capability(
        request,
        body.provider_id,
        body.model_id,
        body.capability,
    )
    if capability is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested capability is not available for provider "
                f"'{body.provider_id}' model '{body.model_id}'."
            ),
        )


async def _assert_job_model_policy_allowed(
    request: Request,
    body: AigcJobCreate,
) -> None:
    if body.provider_id.startswith("plugin:"):
        return
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from ..aigc.model_policy import (
        AigcModelPolicyService,
        category_for_capability,
        policy_enforcement_enabled,
    )
    from ..billing.model_publication import ModelPublicationService
    from ..storage.engine import get_app_engine
    from ..storage.repos.aigc_model_policy_repo import (
        AigcModelPolicyRepository,
    )
    from ..storage.repos.price_catalog_repo import PriceCatalogRepository

    if not policy_enforcement_enabled():
        return
    engine = get_app_engine()
    repository = AigcModelPolicyRepository(engine)
    category = category_for_capability(body.capability)
    try:
        policy = repository.get(category)
    except (OperationalError, ProgrammingError):
        return
    if not policy or not policy.get("configured", True):
        return
    published = ModelPublicationService(
        PriceCatalogRepository(engine)
    ).effective_pairs() or set()
    manager = getattr(request.app.state, "provider_manager", None)
    effective = await AigcModelPolicyService(
        repository,
        published_pairs=published,
        priced_pairs=published,
    ).effective(category, manager)
    allowed = {
        (item.provider_id, item.model_id) for item in effective.models
    }
    if (body.provider_id, body.model_id) not in allowed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "aigc_model_not_allowed",
                "category": category,
                "provider_id": body.provider_id,
                "model_id": body.model_id,
            },
        )


def _create_queued_job(
    body: AigcJobCreate, extra_logs: list[str] | None = None
) -> AigcJob:
    now = _now()
    logs = [
        "Job queued. AIGC adapter execution is handled asynchronously by configured providers.",
    ]
    if extra_logs:
        logs.extend(extra_logs)
    return AigcJob(
        id=str(uuid.uuid4()),
        status="queued",
        created_at=now,
        updated_at=now,
        logs=logs,
        **body.model_dump(),
    )


def _job_event_payload(job: AigcJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "canvas_id": job.canvas_id,
        "node_id": job.node_id,
        "capability": job.capability,
        "provider_id": job.provider_id,
        "model_id": job.model_id,
        "status": job.status,
        "error": job.error,
        "output_count": len(job.outputs),
        "updated_at": job.updated_at,
    }


async def _publish_job_event(job: AigcJob, message: str) -> None:
    try:
        await get_runtime_event_bus().publish(
            RuntimeEvent(
                type="aigc.job.updated",
                scope="aigc",
                job_id=job.id,
                status=job.status,
                message=message,
                payload=_job_event_payload(job),
            ),
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.debug("Failed to publish AIGC job runtime event: %s", exc)


async def _artifact_root_for_request(request: Request) -> Path:
    override = getattr(request.app.state, "aigc_artifact_root", None)
    if override:
        root = Path(override).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    try:
        from ..agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        root = Path(workspace.workspace_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root
    except Exception:
        fallback = _dir("workspace_artifacts").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _asset_kind_for_capability(
    capability: str,
) -> Literal["image", "video", "audio", "file"]:
    if "image" in capability:
        return "image"
    if "video" in capability:
        return "video"
    if "audio" in capability or "music" in capability:
        return "audio"
    return "file"


def _asset_mime_for_kind(kind: str) -> str:
    if kind == "image":
        return "image/svg+xml"
    if kind == "video":
        return "application/json"
    if kind == "audio":
        return "application/json"
    return "application/json"


def _asset_filename_for_kind(job: AigcJob, kind: str, suffix: str | None = None) -> str:
    if suffix:
        return f"{job.node_id}-{job.id}.{suffix.lstrip('.')}"
    if kind == "image":
        return f"{job.node_id}-{job.id}.svg"
    if kind == "video":
        return f"{job.node_id}-{job.id}.json"
    if kind == "audio":
        return f"{job.node_id}-{job.id}.json"
    return f"{job.node_id}-{job.id}.json"


def _public_base_url() -> str:
    return _clean_text(
        os.environ.get("AIGC_STUDIO_PUBLIC_BASE_URL")
        or os.environ.get("QWENPAW_PUBLIC_BASE_URL")
        or os.environ.get("PUBLIC_BASE_URL")
    ).rstrip("/")


def _rewrite_url_with_public_base(value: str, public_base: str) -> str:
    parsed_value = urlparse(value)
    base = urlparse(public_base)
    path = parsed_value.path or value
    if not path.startswith("/"):
        path = f"/{path}"
    return urlunparse((base.scheme, base.netloc, path, "", parsed_value.query, ""))


def _asset_file_url(request: Request, asset_id: str) -> str | None:
    try:
        url = str(request.url_for("get_asset_file", asset_id=asset_id))
    except Exception:
        return None
    public_base = _public_base_url()
    if public_base:
        return _rewrite_url_with_public_base(url, public_base)
    return url


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _cloud_storage_meta(asset: AigcAsset) -> dict[str, Any] | None:
    storage = asset.meta.get("storage")
    if not isinstance(storage, dict):
        return None
    if storage.get("provider") != "aliyun_oss":
        return None
    object_key = str(storage.get("object_key") or "").strip()
    if not object_key:
        return None
    return storage


def _cloud_storage_client_or_error():
    client = get_object_storage_client(require_enabled=False)
    if client is None:
        raise RuntimeError("Aliyun OSS storage is not configured.")
    return client


def _signed_cloud_asset_url(
    asset: AigcAsset,
    *,
    ttl_seconds: int | None = None,
) -> str | None:
    storage = _cloud_storage_meta(asset)
    if not storage:
        return None
    client = _cloud_storage_client_or_error()
    object_key = str(storage["object_key"])
    if ttl_seconds is None:
        return client.signed_get_url(object_key)
    return client.signed_get_url(object_key, ttl_seconds=ttl_seconds)


def _asset_kind_for_mime(mime_type: str) -> Literal["image", "video", "audio", "file"]:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "file"


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename or "asset").name.strip()
    return name or "asset"


def _direct_upload_signature(encoded_payload: str) -> str:
    return hmac.new(
        _public_asset_signing_secret().encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _direct_upload_token(payload: dict[str, Any]) -> str:
    token_payload = dict(payload)
    token_payload["expires_at"] = int(time.time()) + 3600
    encoded_payload = b64encode(
        json.dumps(
            token_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).decode("ascii")
    return f"{encoded_payload}.{_direct_upload_signature(encoded_payload)}"


def _verify_direct_upload_token(asset_id: str, token: str) -> dict[str, Any] | None:
    try:
        encoded_payload, provided_signature = token.split(".", 1)
        expected_signature = _direct_upload_signature(encoded_payload)
        if not hmac.compare_digest(provided_signature, expected_signature):
            return None
        payload = json.loads(b64decode(encoded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("asset_id") or "") != asset_id:
        return None
    try:
        expires_at = int(payload.get("expires_at"))
    except (TypeError, ValueError):
        return None
    if expires_at < int(time.time()):
        return None
    object_key = str(payload.get("object_key") or "").strip()
    if not object_key:
        return None
    return payload


async def _cloud_asset_file_response(asset: AigcAsset) -> Response | None:
    storage = _cloud_storage_meta(asset)
    if not storage:
        return None
    try:
        content, media_type = await _cloud_storage_client_or_error().download(
            str(storage["object_key"])
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Asset file not found."
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Asset file could not be downloaded.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Asset file could not be downloaded.",
        ) from exc
    return Response(
        content=content,
        media_type=media_type or asset.mime_type or "application/octet-stream",
    )


async def _asset_file_path_for_request(request: Request, asset: AigcAsset) -> Path:
    artifact_root = await _artifact_root_for_request(request)
    asset_files_root = _dir("asset_files").resolve()
    raw_path = Path(asset.path)
    if raw_path.is_absolute():
        target = raw_path.expanduser().resolve()
    else:
        target = (artifact_root / raw_path).resolve()

    allowed_roots = [artifact_root.resolve(), asset_files_root]
    if not any(_path_is_relative_to(target, root) for root in allowed_roots):
        raise HTTPException(
            status_code=403, detail="Asset file is outside allowed roots."
        )
    return target


_GENERATED_ASSET_UPLOAD_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_generated_asset_upload_sleep = asyncio.sleep


def _generated_asset_upload_attempts() -> int:
    raw = _clean_text(os.environ.get("AIGC_STUDIO_ASSET_UPLOAD_ATTEMPTS"))
    try:
        attempts = int(raw)
    except (TypeError, ValueError):
        attempts = 4
    return max(1, min(attempts, 6))


async def _upload_generated_asset(
    storage_client: Any,
    *,
    relative_path: str,
    content: bytes | str,
    mime_type: str,
) -> dict[str, Any]:
    """Retry an idempotent OSS object write without rerunning model generation."""
    attempts = _generated_asset_upload_attempts()
    for attempt in range(attempts):
        try:
            return await storage_client.upload(
                relative_path=relative_path,
                content=content,
                mime_type=mime_type,
            )
        except httpx.HTTPStatusError as exc:
            retryable = (
                exc.response.status_code
                in _GENERATED_ASSET_UPLOAD_RETRYABLE_STATUS_CODES
            )
            if not retryable or attempt + 1 >= attempts:
                raise
        except httpx.TransportError:
            if attempt + 1 >= attempts:
                raise
        await _generated_asset_upload_sleep(min(0.5 * (2**attempt), 4.0))

    raise RuntimeError("Generated asset upload failed without a response.")


async def _save_generated_asset(
    request: Request,
    job: AigcJob,
    content: bytes | str,
    *,
    kind: Literal["image", "video", "audio", "file"],
    filename: str,
    mime_type: str,
    adapter: str,
) -> AigcAsset:
    rel_dir = Path("aigc_studio") / job.canvas_id / job.id
    relative_path = (rel_dir / filename).as_posix()
    storage_client = get_object_storage_client(require_enabled=True)

    asset_id = str(uuid.uuid4())
    storage_meta: dict[str, Any] | None = None
    asset_path = relative_path
    if storage_client is not None:
        storage_meta = await _upload_generated_asset(
            storage_client,
            relative_path=relative_path,
            content=content,
            mime_type=mime_type,
        )
        asset_path = f"oss://{storage_meta['bucket']}/{storage_meta['object_key']}"
    else:
        root = await _artifact_root_for_request(request)
        target_dir = root / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    asset = AigcAsset(
        id=asset_id,
        kind=kind,
        name=filename,
        path=asset_path,
        url=_asset_file_url(request, asset_id),
        mime_type=mime_type,
        created_at=_now(),
        meta={
            "owner_user_id": current_user_id(request),
            "canvas_id": job.canvas_id,
            "job_id": job.id,
            "node_id": job.node_id,
            "provider_id": job.provider_id,
            "model_id": job.model_id,
            "adapter": adapter,
            "parameters": job.parameters,
        },
    )
    if storage_meta is not None:
        asset.meta["storage"] = storage_meta
    _write_json(_json_path("assets", asset.id), asset)
    return asset


def _long_image_upstream_nodes(canvas: Canvas, target_node_id: str) -> list[CanvasNode]:
    nodes_by_id = {node.id: node for node in canvas.nodes}
    result: list[CanvasNode] = []
    for edge in canvas.edges:
        if edge.target != target_node_id:
            continue
        node = nodes_by_id.get(edge.source)
        if not node or node.type == "reference_note":
            continue
        if node.data.get("participatesInGeneration") is False:
            continue
        result.append(node)
    return result


def _long_image_text_paragraphs(value: Any) -> list[str]:
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    paragraphs = re.split(r"\n\s*\n+", text)
    if len(paragraphs) == 1:
        paragraphs = text.split("\n")
    return [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]


def _asset_from_output_record(record: Any) -> AigcAsset | None:
    if not isinstance(record, dict):
        return None
    if str(record.get("kind") or "image") != "image":
        return None
    try:
        return AigcAsset(**record)
    except Exception:
        return None


def _long_image_asset_from_node(node: CanvasNode) -> AigcAsset | None:
    outputs = node.data.get("outputs")
    if isinstance(outputs, list):
        for output in outputs:
            asset = _asset_from_output_record(output)
            if asset is not None:
                return asset

    preview_url = _clean_text(
        node.data.get("assetPreviewUrl")
        or node.data.get("referencePreviewUrl")
        or node.data.get("url")
    )
    asset_id = _clean_text(node.data.get("assetId")) or (
        _asset_id_from_file_url(preview_url) if preview_url else ""
    )
    if asset_id:
        asset_path = _json_path("assets", asset_id)
        if asset_path.exists():
            try:
                asset = AigcAsset(**_read_json(asset_path))
            except HTTPException:
                asset = None
            if asset is not None and asset.kind == "image":
                return asset
    return None


def _long_image_sections(canvas: Canvas, target_node_id: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for node in _long_image_upstream_nodes(canvas, target_node_id):
        title = _clean_text(node.data.get("title")) or node.type
        if node.type == "prompt":
            for index, paragraph in enumerate(
                _long_image_text_paragraphs(node.data.get("text")),
                start=1,
            ):
                sections.append(
                    {
                        "id": f"{node.id}-{index}",
                        "kind": "text",
                        "title": title,
                        "text": paragraph,
                        "source_node_id": node.id,
                    }
                )
            continue

        asset = _long_image_asset_from_node(node)
        if asset is not None:
            sections.append(
                {
                    "id": f"{node.id}-{asset.id}",
                    "kind": "image",
                    "title": title,
                    "asset": asset,
                    "source_node_id": node.id,
                }
            )
            continue

        if node.type != "reference_asset":
            for index, paragraph in enumerate(
                _long_image_text_paragraphs(node.data.get("text")),
                start=1,
            ):
                sections.append(
                    {
                        "id": f"{node.id}-{index}",
                        "kind": "text",
                        "title": title,
                        "text": paragraph,
                        "source_node_id": node.id,
                    }
                )
    return sections


def _load_long_image_font(size: int):
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_long_image_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        candidate = f"{current}{char}"
        try:
            width = draw.textlength(candidate, font=font)
        except Exception:
            width = len(candidate) * 14
        if current and width > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


async def _long_image_asset_image(request: Request, asset: AigcAsset):
    from PIL import Image as PILImage

    storage = _cloud_storage_meta(asset)
    if storage:
        content, _media_type = await _cloud_storage_client_or_error().download(
            str(storage["object_key"])
        )
        return PILImage.open(BytesIO(content)).convert("RGB")

    target = await _asset_file_path_for_request(request, asset)
    return PILImage.open(target).convert("RGB")


async def _render_long_image(
    request: Request,
    *,
    title: str,
    width: int,
    sections: list[dict[str, Any]],
):
    from PIL import Image as PILImage, ImageDraw

    padding = max(32, round(width * 0.064))
    gap = 28
    content_width = width - padding * 2
    title_font = _load_long_image_font(38)
    label_font = _load_long_image_font(22)
    body_font = _load_long_image_font(28)
    line_height = 46
    loaded_images: dict[str, Any] = {}

    measure = PILImage.new("RGB", (width, 100), "#faf7ef")
    draw = ImageDraw.Draw(measure)
    blocks: list[dict[str, Any]] = []
    y = padding
    header_lines = _wrap_long_image_text(
        draw, title or "公众号长图", title_font, content_width
    )
    y += len(header_lines) * 50 + 28

    for section in sections:
        if section["kind"] == "text":
            lines = _wrap_long_image_text(
                draw, str(section["text"]), body_font, content_width - 40
            )
            height = 24 + len(lines) * line_height + 28
            blocks.append({**section, "lines": lines, "height": height})
            y += height + gap
            continue

        asset = section.get("asset")
        image = await _long_image_asset_image(request, asset)
        scale = content_width / max(1, image.width)
        scaled_height = max(1, min(1800, round(image.height * scale)))
        image = image.resize((content_width, scaled_height))
        canvas = PILImage.new("RGB", image.size, "#ffffff")
        canvas.paste(image)
        loaded_images[section["id"]] = canvas
        height = 34 + canvas.height + 24
        blocks.append({**section, "height": height})
        y += height + gap

    total_height = max(y + padding, width)
    image = PILImage.new("RGB", (width, total_height), "#faf7ef")
    draw = ImageDraw.Draw(image)
    y = padding
    for line in header_lines:
        draw.text((padding, y), line, fill="#111827", font=title_font)
        y += 50
    draw.text(
        (padding, y), "自动排版 · 公众号上传切片", fill="#6b7280", font=label_font
    )
    y += 42

    for block in blocks:
        if block["kind"] == "text":
            height = int(block["height"])
            draw.rounded_rectangle(
                (padding, y, width - padding, y + height),
                radius=10,
                fill="#ffffff",
            )
            text_y = y + 24
            for line in block["lines"]:
                draw.text((padding + 20, text_y), line, fill="#1f2937", font=body_font)
                text_y += line_height
            y += height + gap
            continue

        loaded = loaded_images.get(block["id"])
        if loaded is None:
            continue
        draw.text((padding, y), str(block["title"]), fill="#6b7280", font=label_font)
        y += 32
        x = padding + max(0, (content_width - loaded.width) // 2)
        image.paste(loaded, (x, y))
        y += loaded.height + 24 + gap
    return image


def _long_image_slices(height: int, slice_height: int) -> list[dict[str, int]]:
    slices: list[dict[str, int]] = []
    y = 0
    index = 1
    while y < height:
        part_height = min(slice_height, height - y)
        slices.append({"index": index, "y": y, "height": part_height})
        y += part_height
        index += 1
    return slices


async def _save_long_image_png_asset(
    request: Request,
    job: AigcJob,
    image: Any,
    *,
    filename: str,
    role: str,
) -> AigcAsset:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    asset = await _save_generated_asset(
        request,
        job,
        buffer.getvalue(),
        kind="image",
        filename=filename,
        mime_type="image/png",
        adapter="long_image_export",
    )
    asset.meta["role"] = role
    asset.meta["width"] = image.width
    asset.meta["height"] = image.height
    _write_json(_json_path("assets", asset.id), asset)
    return asset


def _merge_long_image_export_output(
    canvas: Canvas,
    node_id: str,
    full_asset: AigcAsset,
    slice_assets: list[AigcAsset],
) -> Canvas:
    now = _now()
    nodes = []
    for node in canvas.nodes:
        if node.id != node_id:
            nodes.append(node)
            continue
        data = {
            **node.data,
            "job_status": "succeeded",
            "longImageState": "exported",
            "longImageExportedAt": now,
            "outputs": [
                full_asset.model_dump(),
                *[asset.model_dump() for asset in slice_assets],
            ],
            "longImageFullAssetId": full_asset.id,
            "longImageSliceAssetIds": [asset.id for asset in slice_assets],
        }
        nodes.append(node.model_copy(update={"data": data}))
    return canvas.model_copy(update={"nodes": nodes, "updated_at": now})


async def _create_stub_artifact(request: Request, job: AigcJob) -> AigcAsset:
    """Create a deterministic local artifact for adapter dry-runs and tests."""
    kind = _asset_kind_for_capability(job.capability)
    filename = _asset_filename_for_kind(job, kind)
    prompt = str(job.inputs.get("prompt") or job.parameters.get("prompt") or "")

    if kind == "image":
        safe_prompt = escape(prompt[:260])
        content = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" '
            'viewBox="0 0 1024 1024">'
            '<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1">'
            '<stop offset="0" stop-color="#dbeafe"/>'
            '<stop offset="1" stop-color="#fee2e2"/>'
            "</linearGradient></defs>"
            '<rect width="1024" height="1024" fill="url(#g)"/>'
            '<rect x="96" y="384" width="832" height="256" rx="28" fill="#ffffff" opacity="0.82"/>'
            '<text x="512" y="478" text-anchor="middle" font-size="42" '
            'font-family="Arial, sans-serif" fill="#0f172a">AIGC Studio</text>'
            f'<text x="512" y="548" text-anchor="middle" font-size="26" '
            f'font-family="Arial, sans-serif" fill="#475569">{safe_prompt}</text>'
            "</svg>"
        )
    else:
        content = json.dumps(
            {
                "job_id": job.id,
                "canvas_id": job.canvas_id,
                "node_id": job.node_id,
                "capability": job.capability,
                "provider_id": job.provider_id,
                "model_id": job.model_id,
                "prompt": prompt,
                "parameters": job.parameters,
            },
            ensure_ascii=False,
            indent=2,
        )

    return await _save_generated_asset(
        request,
        job,
        content,
        kind=kind,
        filename=filename,
        mime_type=_asset_mime_for_kind(kind),
        adapter="artifact_stub",
    )


def _openai_client(api_key: str, base_url: str | None = None) -> Any:
    from openai import AsyncOpenAI

    kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)


def _response_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


_MXAPI_DEFAULT_BASE_URL = "https://open.mxapi.org"
_MXAPI_VALID_QUALITIES = {"low", "medium", "high", "auto"}
_MXAPI_GPT_IMAGE_RESOLUTIONS = {"1K", "2K", "4K"}
_MXAPI_GPT_IMAGE_ASPECT_RATIOS = {
    "1:1",
    "3:2",
    "2:3",
    "4:3",
    "3:4",
    "16:9",
    "9:16",
    "21:9",
    "9:21",
    "3:1",
    "1:3",
}
_MXAPI_NANO2_IMAGE_SIZES = {"1K", "2K", "4K"}
_MXAPI_NANO2_ASPECT_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9", "21:9"}
_MXAPI_SEEDANCE_ENDPOINTS = {"seedance2", "seedance2-fast", "seedance2-mini"}
_MXAPI_GROK_VIDEO_MODELS = {
    "grok-imagine-video-1.5-fast",
    "grok-imagine-video-1.5",
}
_MXAPI_GROK_VIDEO_ASPECT_RATIOS = {"2:3", "3:2", "1:1", "9:16", "16:9"}
_MXAPI_GROK_VIDEO_RESOLUTIONS = {"480p", "720p", "1080p"}
_MXAPI_JIMENG_VIDEO_MODELS = {
    "doubao-seedance-1-0-pro-fast-251015",
    "doubao-seedance-1-5-pro-251215",
}
_MXAPI_JIMENG_VIDEO_ASPECT_RATIOS = {
    "16:9",
    "9:16",
    "1:1",
    "4:3",
    "3:4",
    "adaptive",
}
_MXAPI_JIMENG_VIDEO_RESOLUTIONS = {"480p", "720p", "1080p"}
_MXAPI_SEEDANCE_SUCCESS_STATUSES = {
    "succeeded",
    "success",
    "completed",
    "complete",
    "done",
}
_MXAPI_SEEDANCE_FAILED_STATUSES = {
    "failed",
    "failure",
    "error",
    "expired",
    "cancelled",
    "canceled",
}
_mxapi_sleep = asyncio.sleep
_REFERENCE_INPUT_URL_KEYS = (
    "source_preview_url",
    "sourcePreviewUrl",
    "annotationSourcePreviewUrl",
    "preview_url",
    "previewUrl",
    "url",
    "assetPreviewUrl",
    "referencePreviewUrl",
    "image",
    "annotated_preview_url",
    "annotatedPreviewUrl",
    "annotationPreviewUrl",
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _is_text_reference_record(value: dict[str, Any]) -> bool:
    markers = (
        value.get("type"),
        value.get("kind"),
        value.get("assetKind"),
        value.get("asset_kind"),
        value.get("role"),
    )
    if any(_clean_text(marker).lower() in {"prompt", "text"} for marker in markers):
        return True
    preview = _clean_text(
        value.get("preview_url")
        or value.get("previewUrl")
        or value.get("assetPreviewUrl")
        or value.get("url")
    ).lower()
    return preview == "prompt"


def _append_reference_candidate(values: list[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            values.append(stripped)
        return
    if isinstance(value, list):
        for item in value:
            _append_reference_candidate(values, item)
        return
    if isinstance(value, dict):
        if _is_text_reference_record(value):
            return
        for key in _REFERENCE_INPUT_URL_KEYS:
            nested_value = value.get(key)
            if nested_value:
                _append_reference_candidate(values, nested_value)
                return


def _image_output_format(parameters: dict[str, Any]) -> tuple[str, str]:
    output_format = str(parameters.get("output_format") or "png").lower()
    if output_format not in {"png", "jpeg", "jpg", "webp"}:
        output_format = "png"
    suffix = "jpg" if output_format == "jpeg" else output_format
    mime_type = f"image/{'jpeg' if suffix == 'jpg' else suffix}"
    return suffix, mime_type


def _suffix_for_mime_type(mime_type: str, fallback: str = "png") -> str:
    clean_mime = mime_type.split(";", 1)[0].strip().lower()
    if clean_mime == "image/jpeg":
        return "jpg"
    if clean_mime in {"image/png", "image/webp", "image/gif", "image/svg+xml"}:
        suffix = mimetypes.guess_extension(clean_mime) or f".{fallback}"
        return suffix.lstrip(".")
    if clean_mime in {
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
    }:
        suffix = mimetypes.guess_extension(clean_mime) or f".{fallback}"
        if suffix == ".jpe":
            suffix = ".jpg"
        if suffix == ".mpe":
            suffix = ".mp3"
        return suffix.lstrip(".")
    return fallback


def _image_count(parameters: dict[str, Any]) -> int | None:
    raw = parameters.get("imageCount", parameters.get("n"))
    if raw is None:
        return None
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, min(count, 20))


def _size_from_image_parameters(parameters: dict[str, Any]) -> str | None:
    explicit_size = parameters.get("size")
    if explicit_size:
        return str(explicit_size)

    ratio = str(
        parameters.get("aspectRatio")
        or parameters.get("aspect_ratio")
        or parameters.get("ratio")
        or "",
    ).strip()
    if not ratio or ratio.lower() in {"auto", "adaptive"} or ratio == "自适应":
        return None

    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", ratio)
    if match is None:
        return None

    ratio_width = float(match.group(1))
    ratio_height = float(match.group(2))
    if ratio_width <= 0 or ratio_height <= 0:
        return None

    resolution = (
        str(
            parameters.get("resolution")
            or parameters.get("imageResolution")
            or parameters.get("clarity")
            or "2K",
        )
        .strip()
        .lower()
    )
    long_edge = _IMAGE_RESOLUTION_LONG_EDGE.get(resolution)
    if long_edge is None:
        numeric = re.search(r"\d+", resolution)
        if numeric is None:
            long_edge = _IMAGE_RESOLUTION_LONG_EDGE["2k"]
        else:
            parsed = int(numeric.group(0))
            long_edge = parsed * 1024 if parsed <= 8 else parsed

    if ratio_width >= ratio_height:
        width = long_edge
        height = round(long_edge * ratio_height / ratio_width)
    else:
        height = long_edge
        width = round(long_edge * ratio_width / ratio_height)
    return f"{width}x{height}"


def _mxapi_aspect_ratio(parameters: dict[str, Any]) -> str:
    ratio = _clean_text(
        parameters.get("aspect_ratio")
        or parameters.get("aspectRatio")
        or parameters.get("ratio"),
    )
    if not ratio or ratio.lower() in {"auto", "adaptive"} or ratio == "自适应":
        return "1:1"
    return ratio


def _mxapi_resolution(parameters: dict[str, Any]) -> str:
    raw = _clean_text(
        parameters.get("resolution")
        or parameters.get("imageResolution")
        or parameters.get("clarity")
        or os.environ.get("MXAPI_GPT_IMAGE_RESOLUTION")
        or os.environ.get("GPT_IMAGE_RESOLUTION")
        or "1K",
    )
    return raw.upper() if raw else "1K"


def _mxapi_nano2_image_size(parameters: dict[str, Any]) -> str:
    image_size = _mxapi_resolution(parameters)
    return image_size if image_size in _MXAPI_NANO2_IMAGE_SIZES else "1K"


def _mxapi_nano2_aspect_ratio(parameters: dict[str, Any]) -> str:
    aspect_ratio = _mxapi_aspect_ratio(parameters)
    return aspect_ratio if aspect_ratio in _MXAPI_NANO2_ASPECT_RATIOS else "1:1"


def _mxapi_gpt_image_resolution(parameters: dict[str, Any]) -> str:
    resolution = _mxapi_resolution(parameters)
    return resolution if resolution in _MXAPI_GPT_IMAGE_RESOLUTIONS else "1K"


def _mxapi_gpt_image_aspect_ratio(parameters: dict[str, Any]) -> str:
    aspect_ratio = _mxapi_aspect_ratio(parameters)
    return aspect_ratio if aspect_ratio in _MXAPI_GPT_IMAGE_ASPECT_RATIOS else "1:1"


def _mxapi_quality(parameters: dict[str, Any], channel: str = "default") -> str:
    raw = _clean_text(
        parameters.get("quality")
        or parameters.get("imageQuality")
        or os.environ.get("MXAPI_GPT_IMAGE_QUALITY")
        or os.environ.get("GPT_IMAGE_QUALITY")
        or "auto",
    )
    mapped = {
        "低画质": "low",
        "标准画质": "medium",
        "高画质": "high",
    }.get(raw, raw.lower())
    if mapped not in _MXAPI_VALID_QUALITIES:
        return "auto"
    if channel.strip().lower() == "default" and mapped != "auto":
        return "auto"
    return mapped


def _mxapi_config_value(
    provider: Any,
    key: str,
    env_key: str,
    default: str = "",
) -> str:
    provider_meta = getattr(provider, "meta", {}) or {}
    value = (
        getattr(provider, key, None)
        if key in {"api_key", "base_url"}
        else provider_meta.get(key)
    )
    return _clean_text(value or os.environ.get(env_key) or default)


def _mxapi_base_url(provider: Any) -> str:
    return _mxapi_config_value(
        provider,
        "base_url",
        "MXAPI_BASE_URL",
        _MXAPI_DEFAULT_BASE_URL,
    ).rstrip("/")


def _mxapi_channel(provider: Any, parameters: dict[str, Any]) -> str:
    provider_meta = getattr(provider, "meta", {}) or {}
    return (
        _clean_text(
            parameters.get("mxapiChannel")
            or parameters.get("channel")
            or provider_meta.get("channel")
            or os.environ.get("MXAPI_CHANNEL")
            or "default",
        )
        or "default"
    )


def _mxapi_reference_candidates(job: AigcJob) -> list[str]:
    values: list[str] = []

    _append_reference_candidate(values, job.parameters.get("reference_images"))
    _append_reference_candidate(values, job.parameters.get("referenceImages"))
    _append_reference_candidate(
        values,
        job.parameters.get("annotationSourcePreviewUrl"),
    )
    _append_reference_candidate(values, job.parameters.get("referencePreviewUrl"))
    _append_reference_candidate(values, job.parameters.get("annotationPreviewUrl"))
    _append_reference_candidate(values, job.inputs.get("reference_images"))
    _append_reference_candidate(values, job.inputs.get("annotations"))
    _append_reference_candidate(values, job.inputs.get("reference_nodes"))
    _append_reference_candidate(values, _style_reference_candidates(job))
    return values


def _aesthetic_profile_snapshot(job: AigcJob) -> dict[str, Any]:
    snapshot = job.parameters.get("aestheticProfileSnapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _style_reference_candidates(job: AigcJob) -> list[str]:
    values: list[str] = []
    if "styleReferenceImages" in job.parameters:
        _append_reference_candidate(
            values,
            job.parameters.get("styleReferenceImages"),
        )
        return values
    _append_reference_candidate(
        values,
        _aesthetic_profile_snapshot(job).get("reference_image_urls"),
    )
    return values


def _mxapi_public_asset_base_url() -> str:
    return _public_base_url()


def _mxapi_public_asset_url_ttl_seconds() -> int:
    raw = _clean_text(os.environ.get("AIGC_STUDIO_PUBLIC_ASSET_URL_TTL_SECONDS"))
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = 86400
    return max(60, min(ttl, 604800))


@lru_cache(maxsize=1)
def _public_asset_signing_secret() -> str:
    env_secret = _clean_text(os.environ.get("AIGC_STUDIO_PUBLIC_ASSET_SECRET"))
    if env_secret:
        return env_secret

    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    secret_path = SECRET_DIR / "aigc_studio_public_asset_secret"
    if secret_path.exists():
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    secret = secrets.token_hex(32)
    secret_path.write_text(secret, encoding="utf-8")
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return secret


def _public_asset_signature(asset_id: str, expires_at: int) -> str:
    message = f"{asset_id}.{expires_at}".encode("utf-8")
    return hmac.new(
        _public_asset_signing_secret().encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _public_asset_token(asset_id: str) -> str:
    expires_at = int(time.time()) + _mxapi_public_asset_url_ttl_seconds()
    return f"{expires_at}.{_public_asset_signature(asset_id, expires_at)}"


def _verify_public_asset_token(asset_id: str, token: str) -> bool:
    try:
        raw_expires, provided_signature = token.split(".", 1)
        expires_at = int(raw_expires)
    except (ValueError, TypeError):
        return False
    if expires_at < int(time.time()):
        return False
    expected_signature = _public_asset_signature(asset_id, expires_at)
    return hmac.compare_digest(provided_signature, expected_signature)


def _is_private_or_local_host(hostname: str | None) -> bool:
    host = (hostname or "").strip().strip("[]").lower()
    if not host:
        return True
    if host in {"localhost", "test", "0.0.0.0"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _rewrite_reference_with_public_base(value: str, public_base: str) -> str:
    return _rewrite_url_with_public_base(value, public_base)


def _public_asset_reference_url(request: Request, asset_id: str) -> str:
    token = _public_asset_token(asset_id)
    try:
        url = str(request.url_for("get_public_asset_file", asset_id=asset_id))
    except Exception:
        url = f"/api/aigc-studio/public-assets/{asset_id}/file"
    public_base = _mxapi_public_asset_base_url()
    if public_base:
        url = _rewrite_reference_with_public_base(url, public_base)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}token={token}"


def _external_asset_reference_url(request: Request, asset_id: str) -> str | None:
    public_base = _mxapi_public_asset_base_url()
    asset_path = _json_path("assets", asset_id)
    if asset_path.exists():
        asset = _load_asset_for_request(request, asset_id)
        signed_cloud_url = _signed_cloud_asset_url(
            asset,
            ttl_seconds=_mxapi_public_asset_url_ttl_seconds(),
        )
        if signed_cloud_url:
            return signed_cloud_url
        if public_base:
            return _public_asset_reference_url(request, asset_id)
    if public_base:
        return _public_asset_reference_url(request, asset_id)
    return None


def _mxapi_reference_requires_public_url(value: str) -> RuntimeError:
    return RuntimeError(
        "GPT Image 2 reference images must be public image URLs. "
        f"Current reference is not accessible to MXAPI: {value}"
    )


def _mxapi_public_reference_image(request: Request, value: str) -> str:
    if value.startswith("data:"):
        raise RuntimeError(
            "GPT Image 2 through MXAPI does not support base64 reference images. "
            "Use a public image URL instead."
        )
    if value.startswith("blob:"):
        raise RuntimeError(
            "GPT Image 2 through MXAPI cannot read browser blob reference images. "
            "Upload the image to a public URL first."
        )

    asset_id = _asset_id_from_file_url(value)
    if asset_id:
        asset_url = _external_asset_reference_url(request, asset_id)
        if asset_url:
            return asset_url
        raise _mxapi_reference_requires_public_url(value)

    public_base = _mxapi_public_asset_base_url()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if _is_private_or_local_host(parsed.hostname):
            if public_base:
                return _rewrite_reference_with_public_base(value, public_base)
            raise _mxapi_reference_requires_public_url(value)
        return value

    if value.startswith("/") and public_base:
        return _rewrite_reference_with_public_base(value, public_base)

    raise _mxapi_reference_requires_public_url(value)


def _mxapi_reference_images(request: Request, job: AigcJob) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    for value in _mxapi_reference_candidates(job):
        image_url = _mxapi_public_reference_image(request, value)
        if image_url not in seen:
            images.append(image_url)
            seen.add(image_url)
    return images[:16]


def _mxapi_task_id(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    candidates = [
        data.get("task_id"),
        data.get("id"),
        payload.get("task_id"),
        payload.get("id"),
    ]
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _mxapi_http_error_message(response: httpx.Response) -> str:
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        candidates = [
            payload.get("message"),
            payload.get("error"),
            payload.get("detail"),
            data.get("message"),
            data.get("error"),
            data.get("error_message"),
            data.get("error_msg"),
        ]
        message = next(
            (_clean_text(item) for item in candidates if _clean_text(item)),
            "",
        )
    if not message:
        message = _clean_text(response.text)
    if not message:
        message = f"HTTP {response.status_code}"
    return f"MXAPI task submission failed: {message}"


def _mxapi_submit_url(provider: Any, adapter: str) -> str:
    endpoint = "nano2" if adapter == "mxapi_nano2" else "gpt-image-2"
    return f"{_mxapi_base_url(provider)}/api/v2/{endpoint}"


def _mxapi_task_query_urls(provider: Any, task_id: str, adapter: str) -> list[str]:
    base_url = _mxapi_base_url(provider)
    if adapter == "mxapi_nano2":
        return [
            f"{base_url}/api/v2/nano/task?task_id={task_id}",
            f"{base_url}/api/v2/nano/task/{task_id}",
        ]
    return [
        f"{base_url}/api/v2/gpt-image/task?task_id={task_id}",
        f"{base_url}/api/v2/gpt-image/task/{task_id}",
    ]


def _mxapi_submit_body(
    job: AigcJob,
    *,
    prompt: str,
    reference_images: list[str],
    adapter: str,
    channel: str | None = None,
) -> dict[str, Any]:
    if adapter == "mxapi_nano2":
        body: dict[str, Any] = {
            "prompt": prompt,
            "image_size": _mxapi_nano2_image_size(job.parameters),
            "aspect_ratio": _mxapi_nano2_aspect_ratio(job.parameters),
        }
    else:
        active_channel = _clean_text(
            channel
            or job.parameters.get("mxapiChannel")
            or job.parameters.get("channel")
            or "default",
        )
        body = {
            "prompt": prompt,
            "aspect_ratio": _mxapi_gpt_image_aspect_ratio(job.parameters),
            "quality": _mxapi_quality(job.parameters, active_channel),
            "resolution": _mxapi_gpt_image_resolution(job.parameters),
        }
    if reference_images:
        body["reference_images"] = reference_images
    return body


async def _mxapi_submit_task(
    provider: Any,
    job: AigcJob,
    *,
    prompt: str,
    reference_images: list[str],
    adapter: str,
) -> str:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError(f"Provider '{job.provider_id}' is missing an API key.")

    channel = _mxapi_channel(provider, job.parameters)
    body = _mxapi_submit_body(
        job,
        prompt=prompt,
        reference_images=reference_images,
        adapter=adapter,
        channel=channel,
    )
    url = _mxapi_submit_url(provider, adapter)
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-Channel": channel,
                },
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_mxapi_http_error_message(exc.response)) from exc
    payload = response.json()
    task_id = _mxapi_task_id(payload)
    if payload.get("code") not in {None, 200} or not task_id:
        message = _clean_text(payload.get("message")) or "MXAPI task submission failed."
        raise RuntimeError(message)
    return task_id


def _mxapi_completed_image_url(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    images = result.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                return image.strip()
    return None


def _mxapi_error_message(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return (
        _clean_text(data.get("error_message"))
        or _clean_text(data.get("error_msg"))
        or _clean_text(payload.get("message"))
        or "MXAPI image generation failed."
    )


async def _mxapi_query_task(
    provider: Any,
    task_id: str,
    adapter: str,
) -> tuple[str, str | None]:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError("MXAPI_KEY not configured.")

    urls = _mxapi_task_query_urls(provider, task_id, adapter)
    timeout = httpx.Timeout(30.0, connect=10.0)
    last_not_found = False
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        for url in urls:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
            except httpx.TimeoutException:
                return "running", None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    last_not_found = True
                    continue
                raise
            payload = response.json()
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            status = _clean_text(data.get("status"))
            if status == "completed":
                image_url = _mxapi_completed_image_url(payload)
                if image_url:
                    return "completed", image_url
                raise RuntimeError("MXAPI completed without an image URL.")
            if status == "failed":
                raise RuntimeError(_mxapi_error_message(payload))
            return "running", None
    if last_not_found:
        return "running", None
    return "running", None


def _exception_message(exc: Exception) -> str:
    return _clean_text(str(exc)) or exc.__class__.__name__


async def _mxapi_poll_task(provider: Any, task_id: str, adapter: str) -> str:
    timeout_seconds = float(os.environ.get("MXAPI_POLL_TIMEOUT_SECONDS") or 240)
    interval_seconds = float(os.environ.get("MXAPI_POLL_INTERVAL_SECONDS") or 1.5)
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    while loop.time() - started_at < timeout_seconds:
        status, image_url = await _mxapi_query_task(provider, task_id, adapter)
        if status == "completed" and image_url:
            return image_url
        await _mxapi_sleep(interval_seconds)
    raise RuntimeError("MXAPI image generation timed out.")


def _mxapi_seedance_endpoint(model: Any, job: AigcJob) -> str:
    model_kwargs = getattr(model, "generate_kwargs", {}) or {}
    endpoint = _clean_text(
        job.parameters.get("mxapiVideoEndpoint")
        or job.parameters.get("mxapi_video_endpoint")
        or model_kwargs.get("mxapi_video_endpoint")
    )
    if not endpoint:
        model_id = str(getattr(model, "id", "") or job.model_id).strip().lower()
        endpoint = model_id if model_id in _MXAPI_SEEDANCE_ENDPOINTS else "seedance2"
    endpoint = endpoint.strip().lower()
    if endpoint not in _MXAPI_SEEDANCE_ENDPOINTS:
        raise RuntimeError(f"Unsupported MXAPI Seedance endpoint: {endpoint}")
    return endpoint


def _mxapi_seedance_resolution(parameters: dict[str, Any]) -> str:
    raw = _clean_text(
        parameters.get("resolution")
        or parameters.get("videoResolution")
        or parameters.get("video_resolution")
        or "720p"
    )
    normalized = raw.strip()
    if normalized.upper() == "4K":
        return "4K"
    lowered = normalized.lower()
    if lowered in {"480p", "720p", "1080p"}:
        return lowered
    return "720p"


def _mxapi_seedance_ratio(parameters: dict[str, Any]) -> str:
    raw = _clean_text(
        parameters.get("ratio")
        or parameters.get("aspectRatio")
        or parameters.get("aspect_ratio")
        or "16:9"
    )
    if not raw or raw.lower() in {"auto", "adaptive"} or raw == "自适应":
        return "adaptive"
    if raw in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"}:
        return raw
    return "16:9"


def _mxapi_seedance_duration(parameters: dict[str, Any]) -> int:
    raw = parameters.get("duration", parameters.get("videoDuration", 5))
    try:
        duration = int(float(str(raw)))
    except (TypeError, ValueError):
        duration = 5
    return max(4, min(duration, 15))


def _bool_parameter(
    parameters: dict[str, Any],
    keys: tuple[str, ...],
    *,
    default: bool,
) -> bool:
    for key in keys:
        if key not in parameters:
            continue
        value = parameters.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y", "on"}:
                return True
            if lowered in {"false", "0", "no", "n", "off"}:
                return False
        return bool(value)
    return default


def _video_prompt_from_job(job: AigcJob) -> str:
    return _clean_text(
        job.inputs.get("prompt")
        or job.parameters.get("prompt")
        or job.parameters.get("lastRunPrompt")
        or job.parameters.get("text")
    )


def _append_seedance_reference_item(items: list[dict[str, Any]], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            _append_seedance_reference_item(items, item)
        return
    if isinstance(value, dict):
        items.append(value)
        return
    if isinstance(value, str) and value.strip():
        items.append({"url": value.strip()})


def _seedance_reference_items(job: AigcJob) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in (
        "videoReferenceAssets",
        "video_reference_assets",
        "referenceMedia",
        "reference_media",
        "referenceAssets",
        "reference_assets",
    ):
        _append_seedance_reference_item(items, job.parameters.get(key))
    _append_seedance_reference_item(items, job.inputs.get("reference_media"))
    _append_seedance_reference_item(items, job.inputs.get("reference_nodes"))
    return items


def _seedance_reference_url(item: dict[str, Any]) -> str:
    for key in _REFERENCE_INPUT_URL_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _seedance_reference_kind(item: dict[str, Any], url: str) -> str:
    markers = [
        item.get("kind"),
        item.get("assetKind"),
        item.get("asset_kind"),
        item.get("previewKind"),
        item.get("preview_kind"),
        item.get("mime_type"),
        item.get("mimeType"),
        item.get("role"),
    ]
    for marker in markers:
        clean = _clean_text(marker).lower()
        if not clean:
            continue
        if "audio" in clean:
            return "audio"
        if "video" in clean:
            return "video"
        if "image" in clean or clean in {"first_frame", "last_frame"}:
            return "image"

    guessed_mime = mimetypes.guess_type(urlparse(url).path)[0] or ""
    if guessed_mime.startswith("audio/"):
        return "audio"
    if guessed_mime.startswith("video/"):
        return "video"
    return "image"


def _seedance_video_mode(job: AigcJob) -> str:
    return _clean_text(
        job.parameters.get("videoMode")
        or job.parameters.get("activeVideoTab")
        or job.capability
    ).lower()


def _seedance_reference_role(
    job: AigcJob,
    item: dict[str, Any],
    kind: str,
    image_index: int,
) -> str:
    raw_role = _clean_text(item.get("role") or item.get("assetRole")).lower()
    if raw_role in {
        "first_frame",
        "last_frame",
        "reference_image",
        "reference_video",
        "reference_audio",
    }:
        return raw_role

    mode = _seedance_video_mode(job)
    if kind == "audio":
        return "reference_audio"
    if kind == "video":
        return "reference_video"
    if mode == "first_last_frames":
        return "last_frame" if image_index == 1 else "first_frame"
    if mode in {"image_to_video", "first_frame"} or job.capability == "image_to_video":
        return "first_frame"
    return "reference_image"


def _mxapi_seedance_reference_requires_public_url(
    value: str,
    *,
    service: str = "Seedance",
) -> RuntimeError:
    return RuntimeError(
        f"{service} reference media must be public media URLs or cloud-signed "
        f"AIGC assets. Current reference is not accessible to MXAPI: {value}"
    )


def _mxapi_public_reference_media(
    request: Request,
    value: str,
    *,
    service: str = "Seedance",
) -> str:
    if value.startswith("data:"):
        raise RuntimeError(
            f"{service} through MXAPI does not support base64 reference media. "
            "Upload the asset and use a public URL instead."
        )
    if value.startswith("blob:"):
        raise RuntimeError(
            f"{service} through MXAPI cannot read browser blob reference media. "
            "Upload the asset before generation."
        )

    asset_id = _asset_id_from_file_url(value)
    if asset_id:
        asset_url = _external_asset_reference_url(request, asset_id)
        if asset_url:
            return asset_url
        raise _mxapi_seedance_reference_requires_public_url(
            value,
            service=service,
        )

    public_base = _mxapi_public_asset_base_url()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if _is_private_or_local_host(parsed.hostname):
            if public_base:
                return _rewrite_reference_with_public_base(value, public_base)
            raise _mxapi_seedance_reference_requires_public_url(
                value,
                service=service,
            )
        return value

    if value.startswith("/") and public_base:
        return _rewrite_reference_with_public_base(value, public_base)

    raise _mxapi_seedance_reference_requires_public_url(
        value,
        service=service,
    )


def _mxapi_seedance_reference_content(
    request: Request,
    job: AigcJob,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    image_index = 0

    for item in _seedance_reference_items(job):
        raw_url = _seedance_reference_url(item)
        if not raw_url:
            continue
        kind = _seedance_reference_kind(item, raw_url)
        public_url = _mxapi_public_reference_media(request, raw_url)
        role = _seedance_reference_role(job, item, kind, image_index)
        if kind == "image":
            image_index += 1
            entry = {
                "type": "image_url",
                "image_url": {"url": public_url},
                "role": role,
            }
        elif kind == "video":
            entry = {
                "type": "video_url",
                "video_url": {"url": public_url},
                "role": role,
            }
        elif kind == "audio":
            entry = {
                "type": "audio_url",
                "audio_url": {"url": public_url},
                "role": role,
            }
        else:
            continue
        dedupe_key = (role, public_url)
        if dedupe_key in seen:
            continue
        content.append(entry)
        seen.add(dedupe_key)

    if content and all(item.get("role") == "reference_audio" for item in content):
        raise RuntimeError("Seedance reference audio cannot be used alone.")

    mode = _seedance_video_mode(job)
    frame_roles = {str(item.get("role") or "") for item in content}
    if job.capability == "image_to_video" and mode != "all_reference":
        if "first_frame" not in frame_roles:
            raise RuntimeError(
                "Seedance image-to-video requires a first-frame image URL."
            )
        if mode == "first_last_frames" and "last_frame" not in frame_roles:
            raise RuntimeError(
                "Seedance first-last-frame mode requires a last-frame image URL."
            )

    return content


def _mxapi_seedance_submit_body(request: Request, job: AigcJob) -> dict[str, Any]:
    prompt = _video_prompt_from_job(job)
    if not prompt:
        raise RuntimeError("Prompt is required for Seedance video generation.")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(_mxapi_seedance_reference_content(request, job))

    return {
        "content": content,
        "resolution": _mxapi_seedance_resolution(job.parameters),
        "ratio": _mxapi_seedance_ratio(job.parameters),
        "duration": _mxapi_seedance_duration(job.parameters),
        "generate_audio": _bool_parameter(
            job.parameters,
            ("generate_audio", "videoAudio"),
            default=False,
        ),
        "return_last_frame": _bool_parameter(
            job.parameters,
            ("return_last_frame", "returnLastFrame"),
            default=False,
        ),
    }


def _mxapi_seedance_submit_url(provider: Any, model: Any, job: AigcJob) -> str:
    endpoint = _mxapi_seedance_endpoint(model, job)
    return f"{_mxapi_base_url(provider)}/api/v2/video/{endpoint}"


async def _mxapi_seedance_submit_task(
    request: Request,
    provider: Any,
    model: Any,
    job: AigcJob,
) -> str:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError(f"Provider '{job.provider_id}' is missing an API key.")

    body = _mxapi_seedance_submit_body(request, job)
    url = _mxapi_seedance_submit_url(provider, model, job)
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_mxapi_http_error_message(exc.response)) from exc
    payload = response.json()
    task_id = _mxapi_task_id(payload)
    if payload.get("code") not in {None, 200, "200"} or not task_id:
        message = (
            _clean_text(payload.get("message"))
            or "MXAPI Seedance task submission failed."
        )
        raise RuntimeError(message)
    return task_id


def _mxapi_seedance_task_query_url(provider: Any, task_id: str) -> str:
    return f"{_mxapi_base_url(provider)}/api/v2/video/task?task_id={quote(task_id)}"


def _mxapi_seedance_video_url_from_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            url = _mxapi_seedance_video_url_from_value(item)
            if url:
                return url
        return None
    if not isinstance(value, dict):
        return None

    for key in ("video_url", "videoUrl", "url"):
        url = _mxapi_seedance_video_url_from_value(value.get(key))
        if url:
            return url
    for key in ("content", "output", "result", "data", "video", "videos"):
        url = _mxapi_seedance_video_url_from_value(value.get(key))
        if url:
            return url
    return None


def _mxapi_seedance_error_message(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    candidates = [
        data.get("error_message"),
        data.get("error_msg"),
        data.get("error"),
        data.get("message"),
        payload.get("error"),
        payload.get("message"),
    ]
    return next(
        (_clean_text(item) for item in candidates if _clean_text(item)),
        "MXAPI Seedance video generation failed.",
    )


def _mxapi_seedance_status(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return _clean_text(data.get("status") or payload.get("status")).lower()


async def _mxapi_seedance_query_task(
    provider: Any,
    task_id: str,
) -> tuple[str, str | None, dict[str, Any]]:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError("MXAPI_KEY not configured.")

    url = _mxapi_seedance_task_query_url(provider, task_id)
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            return "running", None, {}
    payload = response.json()
    status = _mxapi_seedance_status(payload)
    video_url = _mxapi_seedance_video_url_from_value(payload)
    if status in _MXAPI_SEEDANCE_SUCCESS_STATUSES or (not status and video_url):
        if video_url:
            return "completed", video_url, payload
        raise RuntimeError("MXAPI Seedance completed without a video URL.")
    if status in _MXAPI_SEEDANCE_FAILED_STATUSES:
        raise RuntimeError(_mxapi_seedance_error_message(payload))
    return "running", None, payload


async def _mxapi_seedance_poll_task(
    provider: Any,
    task_id: str,
) -> tuple[str, dict[str, Any]]:
    timeout_seconds = float(
        os.environ.get("AIGC_STUDIO_VIDEO_POLL_TIMEOUT_SECONDS")
        or os.environ.get("MXAPI_SEEDANCE_POLL_TIMEOUT_SECONDS")
        or os.environ.get("MXAPI_POLL_TIMEOUT_SECONDS")
        or 1800
    )
    interval_seconds = float(
        os.environ.get("AIGC_STUDIO_VIDEO_POLL_INTERVAL_SECONDS")
        or os.environ.get("MXAPI_SEEDANCE_POLL_INTERVAL_SECONDS")
        or os.environ.get("MXAPI_POLL_INTERVAL_SECONDS")
        or 3
    )
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    while loop.time() - started_at < timeout_seconds:
        status, video_url, payload = await _mxapi_seedance_query_task(provider, task_id)
        if status == "completed" and video_url:
            return video_url, payload
        await _mxapi_sleep(interval_seconds)
    raise RuntimeError("MXAPI Seedance video generation timed out.")


def _mxapi_seedance_response_meta(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    meta: dict[str, Any] = {}
    for key in (
        "ratio",
        "resolution",
        "duration",
        "points_cost",
        "points_refunded",
    ):
        value = data.get(key, payload.get(key))
        if value is not None:
            meta[key] = value
    return meta


def _mxapi_jimeng_model_id(model: Any, job: AigcJob) -> str:
    model_id = _clean_text(getattr(model, "id", "") or job.model_id).lower()
    if model_id not in _MXAPI_JIMENG_VIDEO_MODELS:
        raise RuntimeError(f"Unsupported MXAPI Jimeng video model: {model_id}")
    return model_id


def _mxapi_jimeng_aspect_ratio(parameters: dict[str, Any]) -> str:
    ratio = _clean_text(
        parameters.get("aspect_ratio")
        or parameters.get("aspectRatio")
        or parameters.get("ratio")
        or "16:9"
    )
    if ratio.lower() in {"auto", "adaptive"} or ratio == "自适应":
        return "adaptive"
    return ratio if ratio in _MXAPI_JIMENG_VIDEO_ASPECT_RATIOS else "16:9"


def _mxapi_jimeng_resolution(parameters: dict[str, Any]) -> str:
    resolution = _clean_text(
        parameters.get("resolution")
        or parameters.get("resolution_name")
        or parameters.get("videoResolution")
        or parameters.get("video_resolution")
        or "1080p"
    ).lower()
    if resolution not in _MXAPI_JIMENG_VIDEO_RESOLUTIONS:
        return "1080p"
    return resolution


def _mxapi_jimeng_duration(parameters: dict[str, Any]) -> int:
    raw = parameters.get("duration", parameters.get("videoDuration", 5))
    try:
        duration = int(float(str(raw)))
    except (TypeError, ValueError):
        duration = 5
    return max(2, min(duration, 12))


def _mxapi_jimeng_prompt(job: AigcJob) -> str:
    prompt = _video_prompt_from_job(job)
    if not prompt:
        raise RuntimeError("Prompt is required for Jimeng video generation.")
    prompt = re.sub(
        r"(?:^|\s)--(?:ratio|rs|dur)\s+\S+",
        " ",
        prompt,
        flags=re.IGNORECASE,
    )
    prompt = " ".join(prompt.split())
    ratio = _mxapi_jimeng_aspect_ratio(job.parameters)
    resolution = _mxapi_jimeng_resolution(job.parameters)
    duration = _mxapi_jimeng_duration(job.parameters)
    return f"{prompt} --ratio {ratio} --rs {resolution} --dur {duration}"


def _mxapi_jimeng_reference_images(request: Request, job: AigcJob) -> list[str]:
    values: list[str] = []
    for item in _seedance_reference_items(job):
        if _is_text_reference_record(item):
            continue
        raw_url = _seedance_reference_url(item)
        if not raw_url:
            continue
        if _seedance_reference_kind(item, raw_url) != "image":
            raise RuntimeError(
                "Jimeng video generation only supports image references."
            )
        values.append(raw_url)

    for key in (
        "referenceImages",
        "reference_images",
        "styleReferenceImages",
    ):
        _append_reference_candidate(values, job.parameters.get(key))

    images: list[str] = []
    seen: set[str] = set()
    for value in values:
        image_url = _mxapi_public_reference_media(
            request,
            value,
            service="Jimeng",
        )
        if image_url in seen:
            continue
        images.append(image_url)
        seen.add(image_url)
    return images


def _mxapi_jimeng_submit_body(
    request: Request,
    model: Any,
    job: AigcJob,
) -> dict[str, Any]:
    model_id = _mxapi_jimeng_model_id(model, job)
    reference_images = _mxapi_jimeng_reference_images(request, job)
    is_first_last_model = model_id == "doubao-seedance-1-5-pro-251215"

    if is_first_last_model and len(reference_images) != 2:
        raise RuntimeError("Jimeng Seedance 1.5 Pro requires exactly 2 frame images.")
    if not is_first_last_model and len(reference_images) > 1:
        raise RuntimeError("Jimeng Seedance 1.0 Pro Fast supports at most 1 image.")
    if (
        not is_first_last_model
        and job.capability == "image_to_video"
        and len(reference_images) != 1
    ):
        raise RuntimeError("Jimeng image-to-video requires exactly 1 image.")

    content: list[dict[str, Any]] = [
        {"type": "text", "text": _mxapi_jimeng_prompt(job)},
    ]
    if is_first_last_model:
        content.extend(
            [
                {
                    "type": "image_url",
                    "image_url": {"url": reference_images[0]},
                    "role": "first_frame",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": reference_images[1]},
                    "role": "last_frame",
                },
            ]
        )
    elif reference_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": reference_images[0]},
            }
        )
    return {"model": model_id, "content": content}


async def _mxapi_jimeng_submit_task(
    request: Request,
    provider: Any,
    model: Any,
    job: AigcJob,
) -> str:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError(f"Provider '{job.provider_id}' is missing an API key.")

    url = f"{_mxapi_base_url(provider)}/api/v2/video/generate"
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=_mxapi_jimeng_submit_body(request, model, job),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_mxapi_http_error_message(exc.response)) from exc
    payload = response.json()
    task_id = _mxapi_task_id(payload)
    if payload.get("code") not in {None, 0, 200, "200"} or not task_id:
        message = _clean_text(payload.get("message")) or (
            "MXAPI Jimeng task submission failed."
        )
        raise RuntimeError(message)
    return task_id


def _mxapi_grok_model_id(model: Any, job: AigcJob) -> str:
    model_id = _clean_text(getattr(model, "id", "") or job.model_id).lower()
    if model_id not in _MXAPI_GROK_VIDEO_MODELS:
        raise RuntimeError(f"Unsupported MXAPI Grok video model: {model_id}")
    return model_id


def _mxapi_grok_aspect_ratio(parameters: dict[str, Any]) -> str:
    ratio = _clean_text(
        parameters.get("aspect_ratio")
        or parameters.get("aspectRatio")
        or parameters.get("ratio")
        or "16:9"
    )
    return ratio if ratio in _MXAPI_GROK_VIDEO_ASPECT_RATIOS else "16:9"


def _mxapi_grok_resolution(model_id: str, parameters: dict[str, Any]) -> str:
    resolution = _clean_text(
        parameters.get("resolution_name")
        or parameters.get("videoResolution")
        or parameters.get("video_resolution")
        or parameters.get("resolution")
        or "720p"
    ).lower()
    if resolution not in _MXAPI_GROK_VIDEO_RESOLUTIONS:
        resolution = "720p"
    if model_id.endswith("-fast") and resolution == "1080p":
        raise RuntimeError("Grok Imagine Video 1.5 Fast does not support 1080p.")
    return resolution


def _mxapi_grok_duration(model_id: str, parameters: dict[str, Any]) -> int:
    is_fast = model_id.endswith("-fast")
    minimum, maximum, default = (6, 30, 10) if is_fast else (5, 15, 5)
    raw = parameters.get(
        "video_length",
        parameters.get("videoDuration", parameters.get("duration", default)),
    )
    try:
        duration = int(float(str(raw)))
    except (TypeError, ValueError):
        duration = default
    return max(minimum, min(duration, maximum))


def _mxapi_grok_reference_images(request: Request, job: AigcJob) -> list[str]:
    values: list[str] = []
    for key in (
        "refer_images",
        "reference_images",
        "referenceImages",
        "styleReferenceImages",
    ):
        _append_reference_candidate(values, job.parameters.get(key))

    for item in _seedance_reference_items(job):
        if _is_text_reference_record(item):
            continue
        raw_url = _seedance_reference_url(item)
        if not raw_url:
            continue
        if _seedance_reference_kind(item, raw_url) != "image":
            raise RuntimeError("Grok video generation only supports image references.")
        values.append(raw_url)

    images: list[str] = []
    seen: set[str] = set()
    for value in values:
        image_url = _mxapi_public_reference_media(
            request,
            value,
            service="Grok",
        )
        if image_url in seen:
            continue
        images.append(image_url)
        seen.add(image_url)
    return images


def _mxapi_grok_submit_body(
    request: Request,
    model: Any,
    job: AigcJob,
) -> dict[str, Any]:
    prompt = _video_prompt_from_job(job)
    if not prompt:
        raise RuntimeError("Prompt is required for Grok video generation.")

    model_id = _mxapi_grok_model_id(model, job)
    reference_images = _mxapi_grok_reference_images(request, job)
    if model_id.endswith("-fast"):
        if len(reference_images) > 7:
            raise RuntimeError("Grok Imagine Video 1.5 Fast supports at most 7 images.")
    elif len(reference_images) != 1:
        raise RuntimeError("Grok Imagine Video 1.5 requires exactly 1 image.")

    body: dict[str, Any] = {
        "prompt": prompt,
        "model": model_id,
        "aspect_ratio": _mxapi_grok_aspect_ratio(job.parameters),
        "video_length": str(_mxapi_grok_duration(model_id, job.parameters)),
        "resolution_name": _mxapi_grok_resolution(model_id, job.parameters),
    }
    if reference_images:
        body["refer_images"] = reference_images
    return body


async def _mxapi_grok_submit_task(
    request: Request,
    provider: Any,
    model: Any,
    job: AigcJob,
) -> str:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError(f"Provider '{job.provider_id}' is missing an API key.")

    body = _mxapi_grok_submit_body(request, model, job)
    channel = _mxapi_channel(provider, job.parameters)
    url = f"{_mxapi_base_url(provider)}/api/v2/video/grok"
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-Channel": channel,
                },
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_mxapi_http_error_message(exc.response)) from exc
    payload = response.json()
    task_id = _mxapi_task_id(payload)
    if payload.get("code") not in {None, 0, 200, "200"} or not task_id:
        message = _clean_text(payload.get("message")) or (
            "MXAPI Grok task submission failed."
        )
        raise RuntimeError(message)
    return task_id


def _mxapi_grok_task_query_url(provider: Any, task_id: str) -> str:
    base_url = _mxapi_base_url(provider)
    return f"{base_url}/api/v2/video/grok/task?task_id={quote(task_id)}"


def _mxapi_grok_error_message(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    candidates = [
        data.get("error_message"),
        data.get("error_msg"),
        data.get("error"),
        data.get("message"),
        payload.get("error"),
        payload.get("message"),
    ]
    return next(
        (_clean_text(item) for item in candidates if _clean_text(item)),
        "MXAPI Grok video generation failed.",
    )


async def _mxapi_grok_query_task(
    provider: Any,
    task_id: str,
) -> tuple[str, str | None, dict[str, Any]]:
    api_key = _mxapi_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError("MXAPI_KEY not configured.")

    url = _mxapi_grok_task_query_url(provider, task_id)
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            return "running", None, {}
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_mxapi_http_error_message(exc.response)) from exc

    payload = response.json()
    if payload.get("code") not in {None, 0, 200, "200"}:
        raise RuntimeError(_mxapi_grok_error_message(payload))
    status = _mxapi_seedance_status(payload)
    video_url = _mxapi_seedance_video_url_from_value(payload)
    if status in _MXAPI_SEEDANCE_SUCCESS_STATUSES or (not status and video_url):
        if video_url:
            return "completed", video_url, payload
        raise RuntimeError("MXAPI Grok completed without a video URL.")
    if status in _MXAPI_SEEDANCE_FAILED_STATUSES:
        raise RuntimeError(_mxapi_grok_error_message(payload))
    return "running", None, payload


async def _mxapi_grok_poll_task(
    provider: Any,
    task_id: str,
) -> tuple[str, dict[str, Any]]:
    timeout_seconds = float(
        os.environ.get("AIGC_STUDIO_VIDEO_POLL_TIMEOUT_SECONDS")
        or os.environ.get("MXAPI_GROK_POLL_TIMEOUT_SECONDS")
        or os.environ.get("MXAPI_POLL_TIMEOUT_SECONDS")
        or 1800
    )
    interval_seconds = float(
        os.environ.get("AIGC_STUDIO_VIDEO_POLL_INTERVAL_SECONDS")
        or os.environ.get("MXAPI_GROK_POLL_INTERVAL_SECONDS")
        or os.environ.get("MXAPI_POLL_INTERVAL_SECONDS")
        or 3
    )
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    while loop.time() - started_at < timeout_seconds:
        status, video_url, payload = await _mxapi_grok_query_task(
            provider,
            task_id,
        )
        if status == "completed" and video_url:
            return video_url, payload
        await _mxapi_sleep(interval_seconds)
    raise RuntimeError("MXAPI Grok video generation timed out.")


def _mxapi_grok_response_meta(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    meta: dict[str, Any] = {}
    for key in (
        "job_id",
        "video_id",
        "aspect_ratio",
        "video_length",
        "resolution_name",
        "quota",
        "finish_time",
        "points_cost",
        "points_refunded",
    ):
        value = data.get(key, payload.get(key))
        if value is not None:
            meta[key] = value
    return meta


def _image_resolution_tier(parameters: dict[str, Any]) -> str:
    resolution = str(
        parameters.get("resolution")
        or parameters.get("imageResolution")
        or parameters.get("clarity")
        or "2K",
    ).strip()
    normalized = resolution.lower()
    if normalized in {"2k", "3k", "4k"}:
        return normalized
    numeric = re.search(r"\d+", normalized)
    if numeric:
        parsed = int(numeric.group(0))
        if parsed <= 2:
            return "2k"
        if parsed == 3:
            return "3k"
        if parsed >= 4:
            return "4k"
    return "2k"


def _seedream_size_from_image_parameters(parameters: dict[str, Any]) -> str:
    explicit_size = parameters.get("size")
    if explicit_size:
        return str(explicit_size)

    tier = _image_resolution_tier(parameters)
    ratio = str(
        parameters.get("aspectRatio")
        or parameters.get("aspect_ratio")
        or parameters.get("ratio")
        or "",
    ).strip()
    if not ratio or ratio.lower() in {"auto", "adaptive"} or ratio == "自适应":
        return tier.upper()

    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", ratio)
    if match is None:
        return tier.upper()

    ratio_width = float(match.group(1))
    ratio_height = float(match.group(2))
    if ratio_width <= 0 or ratio_height <= 0:
        return tier.upper()

    ratio_key = f"{int(ratio_width)}:{int(ratio_height)}"
    return _SEEDREAM_RECOMMENDED_SIZES.get(tier, {}).get(ratio_key, tier.upper())


def _aigc_adapter_for(provider: Any, model: Any, job: AigcJob) -> str | None:
    provider_meta = getattr(provider, "meta", {}) or {}
    model_kwargs = getattr(model, "generate_kwargs", {}) or {}
    model_configured = model_kwargs.get("aigc_adapter")
    if model_configured:
        return str(model_configured)

    provider_id = str(getattr(provider, "id", "") or job.provider_id).lower()
    base_url = str(getattr(provider, "base_url", "") or "").lower()
    model_id = str(getattr(model, "id", "") or job.model_id).lower()
    if (
        job.capability in {"text_to_image", "image_to_image", "image_edit"}
        and model_id in {"nano2", "v2-nano2"}
        and ("mxapi" in provider_id or "open.mxapi.org" in base_url)
    ):
        return "mxapi_nano2"

    if (
        "video" in job.capability
        and model_id in _MXAPI_JIMENG_VIDEO_MODELS
        and ("mxapi" in provider_id or "open.mxapi.org" in base_url)
    ):
        return "mxapi_jimeng_video"

    if (
        "video" in job.capability
        and ("seedance" in model_id or model_id in _MXAPI_SEEDANCE_ENDPOINTS)
        and ("mxapi" in provider_id or "open.mxapi.org" in base_url)
    ):
        return "mxapi_seedance2"

    if (
        "video" in job.capability
        and model_id in _MXAPI_GROK_VIDEO_MODELS
        and ("mxapi" in provider_id or "open.mxapi.org" in base_url)
    ):
        return "mxapi_grok_video"

    provider_configured = provider_meta.get("aigc_adapter")
    if provider_configured:
        return str(provider_configured)

    if job.capability in {"text_to_image", "image_to_image", "image_edit"} and (
        "mxapi" in provider_id or "open.mxapi.org" in base_url
    ):
        return "mxapi_gpt_image"
    if (
        job.capability == "text_to_image"
        and "seedream" in model_id
        and ("volc" in provider_id or "volces.com" in base_url)
    ):
        return "volcengine_seedream"
    return None


_REMOTE_ASSET_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_remote_asset_sleep = asyncio.sleep


def _remote_asset_download_attempts() -> int:
    raw = _clean_text(os.environ.get("AIGC_STUDIO_ASSET_DOWNLOAD_ATTEMPTS"))
    try:
        attempts = int(raw)
    except (TypeError, ValueError):
        attempts = 4
    return max(1, min(attempts, 6))


async def _download_remote_asset(url: str) -> tuple[bytes, str]:
    """Download a completed provider artifact without resubmitting its generation task."""
    timeout = httpx.Timeout(120.0, connect=15.0)
    attempts = _remote_asset_download_attempts()
    for attempt in range(attempts):
        try:
            # A fresh client prevents a truncated keep-alive connection from being reused.
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
            mime_type = response.headers.get(
                "content-type",
                "application/octet-stream",
            )
            return response.content, mime_type
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in _REMOTE_ASSET_RETRYABLE_STATUS_CODES
            if not retryable or attempt + 1 >= attempts:
                raise
        except httpx.TransportError:
            if attempt + 1 >= attempts:
                raise
        await _remote_asset_sleep(min(0.5 * (2**attempt), 4.0))

    raise RuntimeError("Remote asset download failed without a response.")


def _seedream_reference_candidates(job: AigcJob) -> list[str]:
    values: list[str] = []

    _append_reference_candidate(
        values,
        job.parameters.get("annotationSourcePreviewUrl"),
    )
    _append_reference_candidate(values, job.inputs.get("annotations"))
    _append_reference_candidate(values, job.parameters.get("referenceImages"))
    _append_reference_candidate(values, job.parameters.get("reference_images"))
    _append_reference_candidate(values, job.parameters.get("image"))
    _append_reference_candidate(values, job.parameters.get("referencePreviewUrl"))
    _append_reference_candidate(values, job.parameters.get("annotationPreviewUrl"))
    _append_reference_candidate(values, job.inputs.get("image"))
    _append_reference_candidate(values, job.inputs.get("referenceImages"))
    _append_reference_candidate(values, job.inputs.get("reference_images"))
    _append_reference_candidate(values, job.inputs.get("reference_nodes"))
    _append_reference_candidate(values, _style_reference_candidates(job))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _asset_id_from_file_url(value: str) -> str | None:
    match = _ASSET_FILE_URL_RE.search(value)
    return match.group(1) if match else None


def _ensure_reference_image_mime(mime_type: str | None, source: str) -> str:
    clean = (mime_type or "application/octet-stream").split(";", 1)[0].strip()
    if not clean.startswith("image/"):
        raise RuntimeError(f"Reference asset '{source}' is not an image.")
    return clean


async def _image_file_to_data_url(
    path: Path, mime_type: str | None, source: str
) -> str:
    if not path.is_file():
        raise RuntimeError(f"Reference image '{source}' was not found.")
    clean_mime = _ensure_reference_image_mime(
        mime_type or mimetypes.guess_type(path.name)[0],
        source,
    )
    return f"data:{clean_mime};base64,{b64encode(path.read_bytes()).decode('ascii')}"


def _image_bytes_to_data_url(content: bytes, mime_type: str | None, source: str) -> str:
    clean_mime = _ensure_reference_image_mime(mime_type, source)
    return f"data:{clean_mime};base64,{b64encode(content).decode('ascii')}"


async def _asset_to_image_data_url(request: Request, asset_id: str) -> str:
    try:
        asset = _load_asset_for_request(request, asset_id)
    except HTTPException as exc:
        raise RuntimeError(f"Reference asset '{asset_id}' was not found.") from exc
    storage = _cloud_storage_meta(asset)
    if storage:
        content, mime_type = await _cloud_storage_client_or_error().download(
            str(storage["object_key"])
        )
        return _image_bytes_to_data_url(
            content,
            mime_type or asset.mime_type,
            asset.name or asset_id,
        )
    target = await _asset_file_path_for_request(request, asset)
    return await _image_file_to_data_url(
        target,
        asset.mime_type,
        asset.name or asset_id,
    )


async def _relative_reference_to_data_url(request: Request, value: str) -> str:
    artifact_root = await _artifact_root_for_request(request)
    asset_files_root = _dir("asset_files").resolve()
    raw_path = Path(value)
    target = (
        raw_path.expanduser().resolve()
        if raw_path.is_absolute()
        else (artifact_root / raw_path).resolve()
    )
    allowed_roots = [artifact_root.resolve(), asset_files_root]
    if not any(_path_is_relative_to(target, root) for root in allowed_roots):
        raise RuntimeError(f"Reference image '{value}' is outside allowed roots.")
    return await _image_file_to_data_url(target, None, value)


async def _seedream_reference_images(request: Request, job: AigcJob) -> list[str]:
    images: list[str] = []
    for value in _seedream_reference_candidates(job):
        if value.startswith("data:image/"):
            images.append(value)
            continue
        if value.startswith("blob:"):
            raise RuntimeError(
                "Reference image is a browser-only blob URL. "
                "Upload it as an AIGC asset before generation.",
            )

        asset_id = _asset_id_from_file_url(value)
        if asset_id:
            images.append(await _asset_to_image_data_url(request, asset_id))
            continue

        if value.startswith("http://") or value.startswith("https://"):
            images.append(value)
            continue

        images.append(await _relative_reference_to_data_url(request, value))
    return images


def _seedream_multi_image_prompt(prompt: str, count: int) -> str:
    if count <= 1:
        return prompt
    instruction = f"务必一次生成 {count} 张图片结果（不是 1 张）。"
    if instruction in prompt:
        return prompt
    return f"{prompt}\n\n{instruction}"


async def _iter_stream_events(result: Any):
    if hasattr(result, "__aiter__"):
        async for event in result:
            yield event
        return
    for event in result:
        yield event


async def _save_b64_image_asset(
    request: Request,
    job: AigcJob,
    b64_json: str,
    *,
    index: int,
    total_hint: int,
    adapter: str,
) -> AigcAsset:
    suffix, mime_type = _image_output_format(job.parameters)
    filename = _asset_filename_for_kind(
        job,
        "image",
        suffix=f"{index}.{suffix}" if total_hint > 1 else suffix,
    )
    return await _save_generated_asset(
        request,
        job,
        b64decode(b64_json),
        kind="image",
        filename=filename,
        mime_type=mime_type,
        adapter=adapter,
    )


async def _save_seedream_response_asset(
    request: Request,
    job: AigcJob,
    item: Any,
    *,
    index: int,
    total_hint: int,
    adapter: str,
) -> AigcAsset:
    fallback_suffix, fallback_mime_type = _image_output_format(job.parameters)
    b64_json = _response_value(item, "b64_json")
    image_url = _response_value(item, "url")
    if b64_json:
        content = b64decode(str(b64_json))
        suffix = fallback_suffix
        mime_type = fallback_mime_type
    elif image_url:
        content, mime_type = await _download_remote_asset(str(image_url))
        suffix = _suffix_for_mime_type(mime_type, fallback=fallback_suffix)
    else:
        raise RuntimeError("Seedream response did not include b64_json or url.")
    return await _save_generated_asset(
        request,
        job,
        content,
        kind="image",
        filename=_asset_filename_for_kind(
            job,
            "image",
            suffix=f"{index}.{suffix}" if total_hint > 1 else suffix,
        ),
        mime_type=mime_type,
        adapter=adapter,
    )


async def _seedream_assets_from_response(
    request: Request,
    job: AigcJob,
    result: Any,
    *,
    start_index: int,
    total_hint: int,
    adapter: str,
    limit: int | None = None,
) -> list[AigcAsset]:
    data = list(getattr(result, "data", []) or [])
    if not data:
        raise RuntimeError("Seedream image generation returned no image data.")
    if limit is not None:
        data = data[:limit]
    return [
        await _save_seedream_response_asset(
            request,
            job,
            item,
            index=start_index + offset,
            total_hint=total_hint,
            adapter=adapter,
        )
        for offset, item in enumerate(data)
    ]


async def _collect_seedream_stream_assets(
    request: Request,
    job: AigcJob,
    result: Any,
    *,
    expected_count: int,
    adapter: str,
) -> list[AigcAsset]:
    assets: list[AigcAsset] = []
    async for event in _iter_stream_events(result):
        if event is None:
            continue
        event_type = _response_value(event, "type")
        if event_type != "image_generation.partial_succeeded":
            continue
        b64_json = _response_value(event, "b64_json")
        if not b64_json:
            continue
        assets.append(
            await _save_b64_image_asset(
                request,
                job,
                str(b64_json),
                index=len(assets) + 1,
                total_hint=expected_count,
                adapter=adapter,
            ),
        )
        if len(assets) >= expected_count:
            break
    if not assets:
        raise RuntimeError("Seedream streaming generation returned no image data.")
    return assets


def _is_annotation_input(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    marker_values = [
        value.get("role"),
        value.get("assetRole"),
        value.get("assetKind"),
        value.get("previewKind"),
        value.get("imageMode"),
        value.get("annotationKind"),
    ]
    if any(
        _clean_text(item)
        in {
            "annotation",
            "image_annotation",
            "image_region",
            "region_annotation",
            "region_edit",
        }
        for item in marker_values
    ):
        return True
    title = _clean_text(value.get("title"))
    if title not in {"标注", "图像标注", "Annotation"}:
        return False
    return any(_clean_text(value.get(key)) for key in _REFERENCE_INPUT_URL_KEYS)


def _iter_annotation_inputs(job: AigcJob) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []

    def append(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                append(item)
            return
        if _is_annotation_input(value):
            annotations.append(value)

    append(job.inputs.get("annotations"))
    append(job.inputs.get("reference_nodes"))
    if any(
        _clean_text(job.parameters.get(key))
        for key in (
            "annotationSourcePreviewUrl",
            "annotationPreviewUrl",
            "annotationInstruction",
            "annotationMode",
            "imageEditScope",
        )
    ):
        annotations.append(
            {
                "role": "image_annotation",
                "source_preview_url": job.parameters.get("annotationSourcePreviewUrl"),
                "annotated_preview_url": job.parameters.get("annotationPreviewUrl"),
                "instruction": job.parameters.get("annotationInstruction"),
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for annotation in annotations:
        marker = "|".join(
            _clean_text(annotation.get(key))
            for key in (
                "node_id",
                "source_preview_url",
                "annotationSourcePreviewUrl",
                "annotated_preview_url",
                "annotationPreviewUrl",
                "instruction",
            )
        )
        if marker in seen:
            continue
        deduped.append(annotation)
        seen.add(marker)
    return deduped


def _annotation_instruction(value: dict[str, Any]) -> str:
    return (
        _clean_text(value.get("instruction"))
        or _clean_text(value.get("annotationInstruction"))
        or _clean_text(value.get("annotationText"))
        or _clean_text(value.get("text"))
        or _clean_text(value.get("target"))
    )


def _annotation_prompt_sections(job: AigcJob) -> list[str]:
    annotations = _iter_annotation_inputs(job)
    if not annotations:
        return []

    lines: list[str] = []
    for index, annotation in enumerate(annotations[:6], start=1):
        title = (
            _clean_text(annotation.get("title"))
            or _clean_text(annotation.get("asset_name"))
            or _clean_text(annotation.get("assetName"))
            or f"标注{index}"
        )
        instruction = _annotation_instruction(annotation)
        target = (
            _clean_text(annotation.get("target"))
            or _clean_text(annotation.get("annotationTarget"))
            or _clean_text(annotation.get("annotationLabel"))
        )
        parts = [title]
        if target:
            parts.append(f"区域：{target}")
        if instruction:
            parts.append(f"意图：{instruction}")
        lines.append("；".join(parts))

    if not lines:
        return [ANNOTATION_IMAGE_EDITING_PROMPT]
    return [
        ANNOTATION_IMAGE_EDITING_PROMPT,
        "标注说明：\n"
        + "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1)),
    ]


def _image_prompt_from_job(job: AigcJob) -> str:
    prompt = str(job.inputs.get("prompt") or job.parameters.get("prompt") or "").strip()
    if not prompt:
        return prompt
    prompt_sections: list[str] = []
    profile_snapshot = _aesthetic_profile_snapshot(job)
    raw_visual_dna = job.parameters.get("visualDna")
    if raw_visual_dna is None:
        raw_visual_dna = job.parameters.get("visual_dna")
    if raw_visual_dna is None:
        raw_visual_dna = profile_snapshot.get("visual_dna")
    compiled_visual_dna: CompiledVisualDna | None = None
    if isinstance(raw_visual_dna, list) and raw_visual_dna:
        try:
            compiled_visual_dna = compile_visual_dna(
                VisualDnaCompileRequest(
                    selections=raw_visual_dna,
                    provider_id=job.provider_id,
                    model_id=job.model_id,
                    constraints=(
                        job.parameters.get("visualDnaConstraints")
                        if isinstance(
                            job.parameters.get("visualDnaConstraints"),
                            list,
                        )
                        else []
                    ),
                ),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Ignoring invalid Visual DNA job parameters: %s", exc)
    runtime_mode = str(job.parameters.get("styleRuntimeMode") or "").strip()
    if runtime_mode in {"prompt_style", "native_effect"}:
        style_name = str(
            job.parameters.get("styleReferenceName")
            or profile_snapshot.get("title")
            or ""
        ).strip()
        style_description = str(job.parameters.get("styleDescription") or "").strip()
        style_keywords = str(job.parameters.get("styleKeywords") or "").strip()
        supplemental_prompt = str(
            job.parameters.get("styleSupplementalPrompt")
            or profile_snapshot.get("supplemental_prompt")
            or ""
        ).strip()
        style_lines: list[str] = []
        if style_name:
            style_lines.append(f"风格参考：{style_name}。")
        if supplemental_prompt:
            style_lines.append(f"风格补充说明：{supplemental_prompt}")
        elif style_description and not compiled_visual_dna:
            style_lines.append(f"风格描述：{style_description}")
        if style_keywords and not compiled_visual_dna:
            style_lines.append(f"风格关键词：{style_keywords}")
        if style_lines:
            prompt_sections.append("\n".join(style_lines))
    if compiled_visual_dna and compiled_visual_dna.prompt_appendix:
        prompt_sections.append(
            "【结构化视觉 DNA】\n" + compiled_visual_dna.prompt_appendix,
        )
    prompt_sections.extend(_annotation_prompt_sections(job))
    style_reference_candidates = set(_style_reference_candidates(job))
    if style_reference_candidates:
        prompt_sections.append(STYLE_REFERENCE_IMAGE_PROMPT)
    if any(
        candidate not in style_reference_candidates
        for candidate in _seedream_reference_candidates(job)
    ):
        prompt_sections.append(REFERENCE_IMAGE_PRESERVATION_PROMPT)
    if not prompt_sections:
        return prompt
    return f"{prompt}\n\n" + "\n\n".join(prompt_sections)


async def _execute_seedream_image(
    request: Request,
    job: AigcJob,
    provider: Any,
    *,
    adapter: str,
) -> list[AigcAsset]:
    if job.capability not in {
        "text_to_image",
        "image_to_image",
        "image_edit",
        "mask_edit",
    }:
        raise RuntimeError(f"Seedream image adapter does not support {job.capability}.")

    api_key = getattr(provider, "api_key", "") or ""
    if not api_key:
        raise RuntimeError(f"Provider '{job.provider_id}' is missing an API key.")

    count = _image_count(job.parameters) or 1
    count = max(1, min(count, 15))
    base_prompt = _image_prompt_from_job(job)
    prompt = _seedream_multi_image_prompt(base_prompt, count)
    if not base_prompt:
        raise RuntimeError("Prompt is required for Seedream generation.")

    reference_images = await _seedream_reference_images(request, job)

    extra_body: dict[str, Any] = {
        "watermark": bool(job.parameters.get("watermark", True)),
    }
    if reference_images:
        extra_body["image"] = (
            reference_images[0] if len(reference_images) == 1 else reference_images
        )

    request_kwargs: dict[str, Any] = {
        "model": job.model_id,
        "prompt": prompt,
        "size": _seedream_size_from_image_parameters(job.parameters),
        "response_format": "url",
        "extra_body": extra_body,
    }
    if count > 1:
        request_kwargs["response_format"] = "b64_json"
        request_kwargs["stream"] = True
        extra_body["sequential_image_generation"] = "auto"
        extra_body["sequential_image_generation_options"] = {"max_images": count}
    elif reference_images:
        extra_body["sequential_image_generation"] = "disabled"

    client = _openai_client(api_key, getattr(provider, "base_url", "") or None)
    result = await client.images.generate(**request_kwargs)
    if request_kwargs.get("stream") is True:
        assets = await _collect_seedream_stream_assets(
            request,
            job,
            result,
            expected_count=count,
            adapter=adapter,
        )
        assets = assets[:count]
        asset_indexes = list(range(1, len(assets) + 1))
        missing_count = count - len(assets)
        fill_failures: list[tuple[int, str]] = []
        if missing_count > 0:
            # Volcengine documents max_images as an upper bound and lets the
            # model decide the actual group size in auto mode. The canvas count
            # selector is an exact user request, so fill any missing slots with
            # independent single-image calls instead of silently completing a
            # four-image job with only one result.
            job.logs.append(
                "Seedream group returned "
                f"{len(assets)}/{count} images; filling {missing_count} missing slots.",
            )

            async def generate_fill_asset(index: int) -> AigcAsset:
                fill_extra_body = dict(extra_body)
                fill_extra_body["sequential_image_generation"] = "disabled"
                fill_extra_body.pop("sequential_image_generation_options", None)
                fill_result = await client.images.generate(
                    model=job.model_id,
                    prompt=base_prompt,
                    size=_seedream_size_from_image_parameters(job.parameters),
                    response_format="b64_json",
                    extra_body=fill_extra_body,
                )
                fill_assets = await _seedream_assets_from_response(
                    request,
                    job,
                    fill_result,
                    start_index=index,
                    total_hint=count,
                    adapter=adapter,
                    limit=1,
                )
                return fill_assets[0]

            fill_indexes = range(len(assets) + 1, count + 1)
            fill_results = await asyncio.gather(
                *(generate_fill_asset(index) for index in fill_indexes),
                return_exceptions=True,
            )
            for index, fill_result in zip(fill_indexes, fill_results, strict=True):
                if isinstance(fill_result, Exception):
                    fill_failures.append((index, _exception_message(fill_result)))
                elif isinstance(fill_result, BaseException):
                    raise fill_result
                else:
                    assets.append(fill_result)
                    asset_indexes.append(index)

        for index, asset in zip(asset_indexes, assets, strict=True):
            asset.meta["image_index"] = index
            asset.meta["image_count"] = count
            if fill_failures:
                asset.meta["partial_failure_count"] = len(fill_failures)
                asset.meta["partial_failure_errors"] = [
                    {"image_index": failed_index, "message": message}
                    for failed_index, message in fill_failures
                ]
            _write_json(_json_path("assets", asset.id), asset)
        if fill_failures:
            job.logs.append(
                "Seedream image batch partially succeeded: "
                f"{len(assets)}/{count} generated; {len(fill_failures)} failed. "
                + "; ".join(
                    f"Image {index}: {message}" for index, message in fill_failures
                ),
            )
        return assets

    return await _seedream_assets_from_response(
        request,
        job,
        result,
        start_index=1,
        total_hint=count,
        adapter=adapter,
    )


async def _execute_mxapi_gpt_image(
    request: Request,
    job: AigcJob,
    provider: Any,
    *,
    adapter: str,
) -> list[AigcAsset]:
    if job.capability not in {"text_to_image", "image_to_image", "image_edit"}:
        raise RuntimeError(f"MXAPI image adapter does not support {job.capability}.")

    prompt = _image_prompt_from_job(job)
    if not prompt:
        raise RuntimeError("Prompt is required for MXAPI image generation.")

    reference_images = _mxapi_reference_images(request, job)
    if job.capability != "text_to_image" and not reference_images:
        raise RuntimeError(
            "MXAPI image editing requires at least one reference image URL."
        )

    count = _image_count(job.parameters) or 1

    async def finish_single(index: int, task_id: str) -> AigcAsset:
        image_url = await _mxapi_poll_task(provider, task_id, adapter)
        content, mime_type = await _download_remote_asset(image_url)
        fallback_suffix, _fallback_mime_type = _image_output_format(job.parameters)
        suffix = _suffix_for_mime_type(mime_type, fallback=fallback_suffix)
        filename_suffix = f"{index + 1}.{suffix}" if count > 1 else suffix
        asset = await _save_generated_asset(
            request,
            job,
            content,
            kind="image",
            filename=_asset_filename_for_kind(
                job,
                "image",
                suffix=filename_suffix,
            ),
            mime_type=mime_type,
            adapter=adapter,
        )
        asset.meta["mxapi_task_id"] = task_id
        asset.meta["source_url"] = image_url
        if count > 1:
            asset.meta["image_index"] = index + 1
            asset.meta["image_count"] = count
        _write_json(_json_path("assets", asset.id), asset)
        return asset

    async def submit_single() -> str:
        return await _mxapi_submit_task(
            provider,
            job,
            prompt=prompt,
            reference_images=reference_images,
            adapter=adapter,
        )

    if count == 1:
        task_id = await submit_single()
        return [await finish_single(0, task_id)]

    # MXAPI exposes a single-image task endpoint. Submit batch slots one by one so
    # a burst of writes does not overload the provider, then poll accepted tasks
    # concurrently. Each slot is isolated: one safety rejection or timeout must
    # not discard images that were generated successfully by the other slots.
    submitted: list[tuple[int, str]] = []
    failures: list[tuple[int, str]] = []
    for index in range(count):
        try:
            submitted.append((index, await submit_single()))
        except Exception as exc:
            failures.append((index, _exception_message(exc)))

    results = await asyncio.gather(
        *(finish_single(index, task_id) for index, task_id in submitted),
        return_exceptions=True,
    )
    assets: list[AigcAsset] = []
    for (index, _task_id), result in zip(submitted, results, strict=True):
        if isinstance(result, Exception):
            failures.append((index, _exception_message(result)))
        elif isinstance(result, BaseException):
            raise result
        else:
            assets.append(result)

    failures.sort(key=lambda item: item[0])
    if not assets:
        details = "; ".join(
            f"Image {index + 1}: {message}" for index, message in failures
        )
        raise RuntimeError(
            f"MXAPI image batch failed (0/{count} succeeded). {details}",
        )

    if failures:
        failure_details = [
            {"image_index": index + 1, "message": message}
            for index, message in failures
        ]
        succeeded_count = len(assets)
        failed_count = len(failures)
        for asset in assets:
            asset.meta["image_count"] = count
            asset.meta["partial_failure_count"] = failed_count
            asset.meta["partial_failure_errors"] = failure_details
            _write_json(_json_path("assets", asset.id), asset)
        job.logs.append(
            "Image batch partially succeeded: "
            f"{succeeded_count}/{count} generated; {failed_count} failed. "
            + "; ".join(f"Image {index + 1}: {message}" for index, message in failures),
        )
    return assets


async def _execute_mxapi_seedance_video(
    request: Request,
    job: AigcJob,
    provider: Any,
    model: Any,
    *,
    adapter: str,
) -> list[AigcAsset]:
    if job.capability not in {"text_to_video", "image_to_video", "reference_video"}:
        raise RuntimeError(f"MXAPI Seedance adapter does not support {job.capability}.")

    task_id = await _mxapi_seedance_submit_task(request, provider, model, job)
    video_url, payload = await _mxapi_seedance_poll_task(provider, task_id)
    content, mime_type = await _download_remote_asset(video_url)
    suffix = _suffix_for_mime_type(mime_type, fallback="mp4")
    asset = await _save_generated_asset(
        request,
        job,
        content,
        kind="video",
        filename=_asset_filename_for_kind(job, "video", suffix=suffix),
        mime_type=mime_type,
        adapter=adapter,
    )
    asset.meta["mxapi_task_id"] = task_id
    asset.meta["seedance_task_id"] = task_id
    asset.meta["source_url"] = video_url
    asset.meta.update(_mxapi_seedance_response_meta(payload))
    _write_json(_json_path("assets", asset.id), asset)
    return [asset]


async def _execute_mxapi_grok_video(
    request: Request,
    job: AigcJob,
    provider: Any,
    model: Any,
    *,
    adapter: str,
) -> list[AigcAsset]:
    if job.capability not in {"text_to_video", "image_to_video"}:
        raise RuntimeError(f"MXAPI Grok adapter does not support {job.capability}.")

    task_id = await _mxapi_grok_submit_task(request, provider, model, job)
    video_url, payload = await _mxapi_grok_poll_task(provider, task_id)
    content, mime_type = await _download_remote_asset(video_url)
    suffix = _suffix_for_mime_type(mime_type, fallback="mp4")
    asset = await _save_generated_asset(
        request,
        job,
        content,
        kind="video",
        filename=_asset_filename_for_kind(job, "video", suffix=suffix),
        mime_type=mime_type,
        adapter=adapter,
    )
    asset.meta["mxapi_task_id"] = task_id
    asset.meta["grok_task_id"] = task_id
    asset.meta["source_url"] = video_url
    asset.meta["model"] = _mxapi_grok_model_id(model, job)
    asset.meta.update(_mxapi_grok_response_meta(payload))
    _write_json(_json_path("assets", asset.id), asset)
    return [asset]


async def _execute_mxapi_jimeng_video(
    request: Request,
    job: AigcJob,
    provider: Any,
    model: Any,
    *,
    adapter: str,
) -> list[AigcAsset]:
    if job.capability not in {"text_to_video", "image_to_video"}:
        raise RuntimeError(f"MXAPI Jimeng adapter does not support {job.capability}.")

    task_id = await _mxapi_jimeng_submit_task(request, provider, model, job)
    video_url, payload = await _mxapi_seedance_poll_task(provider, task_id)
    content, mime_type = await _download_remote_asset(video_url)
    suffix = _suffix_for_mime_type(mime_type, fallback="mp4")
    asset = await _save_generated_asset(
        request,
        job,
        content,
        kind="video",
        filename=_asset_filename_for_kind(job, "video", suffix=suffix),
        mime_type=mime_type,
        adapter=adapter,
    )
    asset.meta["mxapi_task_id"] = task_id
    asset.meta["jimeng_task_id"] = task_id
    asset.meta["source_url"] = video_url
    asset.meta["model"] = _mxapi_jimeng_model_id(model, job)
    asset.meta.update(_mxapi_seedance_response_meta(payload))
    _write_json(_json_path("assets", asset.id), asset)
    return [asset]


async def _execute_openai_image(
    request: Request,
    job: AigcJob,
    provider: Any,
    *,
    adapter: str = "openai_image",
) -> list[AigcAsset]:
    if job.capability not in {
        "text_to_image",
        "image_to_image",
        "image_edit",
        "mask_edit",
    }:
        raise RuntimeError(f"OpenAI image adapter does not support {job.capability}.")
    if job.capability != "text_to_image":
        raise RuntimeError(
            "OpenAI image edit/reference execution is not configured yet. "
            "Use text_to_image or install an edit adapter.",
        )

    api_key = getattr(provider, "api_key", "") or ""
    if not api_key:
        raise RuntimeError(f"Provider '{job.provider_id}' is missing an API key.")

    prompt = str(job.inputs.get("prompt") or job.parameters.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("Prompt is required for text_to_image generation.")

    request_kwargs: dict[str, Any] = {
        "model": job.model_id,
        "prompt": prompt,
    }
    if adapter == "volcengine_seedream":
        request_kwargs["size"] = _seedream_size_from_image_parameters(job.parameters)
        count = _image_count(job.parameters)
        if count is not None:
            request_kwargs["n"] = count
        request_kwargs["response_format"] = "url"
        request_kwargs["extra_body"] = {
            "watermark": bool(job.parameters.get("watermark", True)),
        }
    else:
        allowed_params = {
            "size",
            "quality",
            "background",
            "output_format",
            "output_compression",
            "n",
            "moderation",
        }
        for key in allowed_params:
            value = job.parameters.get(key)
            if value is not None:
                request_kwargs[key] = value
        count = _image_count(job.parameters)
        if count is not None and "n" not in request_kwargs:
            request_kwargs["n"] = count

    client = _openai_client(api_key, getattr(provider, "base_url", "") or None)
    result = await client.images.generate(**request_kwargs)
    data = list(getattr(result, "data", []) or [])
    if not data:
        raise RuntimeError("OpenAI image generation returned no image data.")

    fallback_suffix, fallback_mime_type = _image_output_format(job.parameters)

    assets: list[AigcAsset] = []
    for index, item in enumerate(data):
        b64_json = _response_value(item, "b64_json")
        image_url = _response_value(item, "url")
        if b64_json:
            content = b64decode(str(b64_json))
            suffix = fallback_suffix
            mime_type = fallback_mime_type
        elif image_url:
            content, mime_type = await _download_remote_asset(str(image_url))
            suffix = _suffix_for_mime_type(mime_type, fallback=fallback_suffix)
        else:
            raise RuntimeError(
                "Image generation response did not include b64_json or url.",
            )
        filename = _asset_filename_for_kind(
            job,
            "image",
            suffix=f"{index + 1}.{suffix}" if len(data) > 1 else suffix,
        )
        assets.append(
            await _save_generated_asset(
                request,
                job,
                content,
                kind="image",
                filename=filename,
                mime_type=mime_type,
                adapter=adapter,
            ),
        )
    return assets


def _job_prompt_text(job: AigcJob) -> str:
    return str(job.inputs.get("prompt") or job.parameters.get("prompt") or "").strip()


def _text_reference_urls(job: AigcJob) -> list[str]:
    urls: list[str] = []
    for item in job.inputs.get("reference_nodes") or []:
        if isinstance(item, dict):
            preview_url = str(item.get("preview_url") or item.get("url") or "").strip()
            if preview_url:
                urls.append(preview_url)
    for item in job.parameters.get("referenceImages") or []:
        preview_url = str(item or "").strip()
        if preview_url:
            urls.append(preview_url)
    return list(dict.fromkeys(urls))


def _model_supports_text_images(model: Any) -> bool:
    if getattr(model, "supports_image", False) or getattr(
        model, "supports_vision", False
    ):
        return True
    capabilities = set(
        str(item) for item in getattr(model, "aigc_capabilities", []) or []
    )
    return "reference_image" in capabilities or "image_to_prompt" in capabilities


def _external_text_reference_urls(request: Request, job: AigcJob) -> list[str]:
    urls: list[str] = []
    for value in _text_reference_urls(job):
        asset_id = _asset_id_from_file_url(value)
        if asset_id:
            external_url = _external_asset_reference_url(request, asset_id)
            if not external_url:
                raise RuntimeError(
                    "Visual text model reference images must be externally accessible. "
                    f"Current reference is not accessible: {value}"
                )
            value = external_url
        urls.append(value)
    return urls


def _text_job_messages(
    request: Request,
    job: AigcJob,
    model: Any,
) -> list[dict[str, Any]]:
    prompt = _job_prompt_text(job)
    text_mode = str(job.parameters.get("textMode") or "").strip()
    output_format = str(job.parameters.get("outputFormat") or "").strip()
    reference_urls = _text_reference_urls(job)
    if reference_urls and not _model_supports_text_images(model):
        raise RuntimeError(
            "Selected text model does not support image understanding. "
            "Choose a visual text model for image-to-prompt jobs.",
        )
    if reference_urls:
        reference_urls = _external_text_reference_urls(request, job)

    is_storyboard_script = job.capability == "storyboard" and (
        text_mode == "storyboard_script" or output_format == "storyboard_shots_json"
    )
    if is_storyboard_script:
        system_prompt = (
            "你是 AIGC Studio 的小说/短剧分镜导演。请把用户输入的剧情、故事、"
            "人物设定或素材拆解为可直接进入图片与视频生成流程的分镜脚本。"
            "只输出一个合法 JSON 对象，不要输出 Markdown、代码块、解释或额外文字。"
            "JSON 顶层必须包含 title 和 shots；shots 是非空数组，默认生成 6 到 12 个镜头，"
            "如果用户明确指定镜头数量则遵循用户要求。"
            "每个镜头对象必须包含：no、duration、imageDescription、character、"
            "characterDescription、scene、shotType、camera、action、emotion、"
            "lightingMood、dialogue、soundEffect、prompt、finalPrompt、videoPrompt。"
            "prompt 和 finalPrompt 都填写同一份最终画面提示词，需适合生成分镜图；"
            "videoPrompt 填写适合生成视频片段的运动与镜头提示词。"
            "不要省略 shots，不要返回纯文本脚本。"
        )
        fallback_prompt = "请根据输入剧情生成结构化分镜脚本 JSON。"
    elif text_mode == "image_to_prompt":
        system_prompt = (
            "你是 AIGC Studio 的视觉提示词助手。根据用户输入和参考图，"
            "生成结构化中文提示词，覆盖主体、环境、光影、镜头语言、风格关键词。"
        )
        fallback_prompt = "请把参考图片反推成可用于图像生成的结构化中文提示词。"
    else:
        system_prompt = "你是 AIGC Studio 的文本生成助手。请根据用户输入生成清晰、可直接用于创意生产的中文文本。"
        fallback_prompt = "请生成一段适合 AIGC 创意生产的中文文本。"

    user_text = prompt or fallback_prompt
    if not reference_urls:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]

    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url}} for url in reference_urls
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def _text_from_chat_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response.strip()
    if isinstance(response, list):
        for item in response:
            text = _text_from_chat_response(item)
            if text:
                return text
        return ""
    for key in ("content", "text", "output_text"):
        value = _response_value(response, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            text = _text_from_chat_response(value)
            if text:
                return text
    content = _response_value(_response_value(response, "message"), "content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        text = _text_from_chat_response(content)
        if text:
            return text
    choices = _response_value(response, "choices")
    if isinstance(choices, list):
        for choice in choices:
            text = _text_from_chat_response(choice)
            if text:
                return text
    if isinstance(response, dict):
        for key in ("message", "delta"):
            text = _text_from_chat_response(response.get(key))
            if text:
                return text
    return ""


async def _consume_text_chat_response(result: Any) -> str:
    if hasattr(result, "__await__"):
        result = await result
    if hasattr(result, "__aiter__"):
        generated_text = ""
        async for chunk in result:
            text = _text_from_chat_response(chunk)
            if text:
                generated_text = text
        return generated_text.strip()
    return _text_from_chat_response(result)


async def _execute_text_generation(
    request: Request,
    job: AigcJob,
    provider: Any,
    model: Any,
) -> list[AigcAsset]:
    get_chat_model = getattr(provider, "get_chat_model_instance", None)
    if not callable(get_chat_model):
        raise RuntimeError(
            "No chat model runtime is configured for "
            f"{job.provider_id}/{job.model_id}.",
        )
    chat_model = get_chat_model(job.model_id)
    messages = _text_job_messages(request, job, model)
    result = chat_model(messages)
    generated_text = await _consume_text_chat_response(result)
    if not generated_text:
        raise RuntimeError("Text model returned an empty response.")

    asset = await _save_generated_asset(
        request,
        job,
        generated_text,
        kind="file",
        filename=_asset_filename_for_kind(job, "file", "txt"),
        mime_type="text/plain",
        adapter="chat_model",
    )
    asset.meta["text"] = generated_text
    asset.meta["prompt"] = _job_prompt_text(job)
    _write_json(_json_path("assets", asset.id), asset)
    return [asset]


async def _execute_job(request: Request, job: AigcJob) -> list[AigcAsset]:
    provider, model = await _find_provider_model(request, job.provider_id, job.model_id)
    adapter = _aigc_adapter_for(provider, model, job)
    if adapter == "artifact_stub":
        return [await _create_stub_artifact(request, job)]
    if job.capability == "storyboard":
        return await _execute_text_generation(request, job, provider, model)
    if (
        job.capability in {"text_to_image", "image_to_image", "image_edit"}
        and getattr(provider, "id", "") in {"openai", "azure-openai"}
        and adapter is None
    ):
        adapter = "openai_image"
    if adapter == "volcengine_seedream":
        return await _execute_seedream_image(request, job, provider, adapter=adapter)
    if adapter in {"mxapi_gpt_image", "mxapi_nano2"}:
        return await _execute_mxapi_gpt_image(request, job, provider, adapter=adapter)
    if adapter == "mxapi_seedance2":
        return await _execute_mxapi_seedance_video(
            request,
            job,
            provider,
            model,
            adapter=adapter,
        )
    if adapter == "mxapi_grok_video":
        return await _execute_mxapi_grok_video(
            request,
            job,
            provider,
            model,
            adapter=adapter,
        )
    if adapter == "mxapi_jimeng_video":
        return await _execute_mxapi_jimeng_video(
            request,
            job,
            provider,
            model,
            adapter=adapter,
        )
    if adapter == "openai_image":
        return await _execute_openai_image(request, job, provider, adapter=adapter)
    raise RuntimeError(
        "No AIGC adapter is configured for "
        f"{job.provider_id}/{job.model_id}. Set aigc_adapter metadata or install a provider adapter.",
    )


async def _mark_job_running(job: AigcJob) -> AigcJob:
    job.status = "running"
    job.updated_at = _now()
    if not job.logs or job.logs[-1] != "Job started.":
        job.logs.append("Job started.")
    _write_json(_json_path("jobs", job.id), job)
    await _publish_job_event(job, "AIGC job running")
    return job


async def _run_job_to_completion(request: Request, job_id: str) -> AigcJob:
    job = _load_job(job_id)
    if job.status in {"cancelled", "succeeded"}:
        return job
    if job.status != "running":
        job = await _mark_job_running(job)

    try:
        from ..billing.model_publication import ModelPublicationService
        from ..storage.engine import get_app_engine
        from ..storage.repos.price_catalog_repo import PriceCatalogRepository

        if not ModelPublicationService(
            PriceCatalogRepository(get_app_engine())
        ).is_published(job.provider_id, job.model_id):
            raise RuntimeError("Model is not published in the active price catalog")
        outputs = await _execute_job(request, job)
        job.outputs = outputs
        job.status = "succeeded"
        job.error = None
        job.logs.append("Job succeeded.")
        job.updated_at = _now()
        _write_json(_json_path("jobs", job_id), job)
        await _publish_job_event(job, "AIGC job succeeded")

        canvas = _load_canvas(job.canvas_id)
        updated_canvas = _merge_node_output(canvas, job)
        _write_json(_json_path("canvases", canvas.id), updated_canvas)
        return job
    except Exception as exc:
        error_message = _exception_message(exc)
        job.status = "failed"
        job.error = error_message
        job.updated_at = _now()
        job.logs.append(f"Job failed: {error_message}")
        _write_json(_json_path("jobs", job_id), job)
        await _publish_job_event(job, "AIGC job failed")
        return job


def _start_background_job_run(request: Request, job_id: str) -> None:
    current_task = _JOB_RUN_TASKS.get(job_id)
    if current_task is not None and not current_task.done():
        return

    task = asyncio.create_task(_run_job_to_completion(request, job_id))
    _JOB_RUN_TASKS[job_id] = task

    def cleanup(finished_task: asyncio.Task[AigcJob]) -> None:
        if _JOB_RUN_TASKS.get(job_id) is finished_task:
            _JOB_RUN_TASKS.pop(job_id, None)
        try:
            finished_task.result()
        except Exception:
            logger.exception("Background AIGC job runner crashed for job %s", job_id)

    task.add_done_callback(cleanup)


def _merge_node_output(canvas: Canvas, job: AigcJob) -> Canvas:
    output_payload = [asset.model_dump() for asset in job.outputs]
    nodes = []
    for node in canvas.nodes:
        if node.id != job.node_id:
            nodes.append(node)
            continue
        data = {
            **node.data,
            "job_id": job.id,
            "job_status": job.status,
            "outputs": output_payload,
        }
        if node.type == "image_generate" and job.status == "succeeded":
            data["imageState"] = "generated"
            data["imageProgress"] = None
            data["generatedAspectRatio"] = job.parameters.get("aspectRatio")
        if node.type == "prompt" and job.status == "succeeded":
            generated_text = next(
                (
                    str(asset.meta.get("text") or "").strip()
                    for asset in job.outputs
                    if str(asset.meta.get("text") or "").strip()
                ),
                "",
            )
            data["textState"] = "generated"
            data["showTryOptions"] = False
            if generated_text:
                data["text"] = generated_text
        if node.type == "video_generate" and job.status == "succeeded":
            data["videoState"] = "generated"
            data["videoProgress"] = None
            data["generatedAspectRatio"] = job.parameters.get(
                "aspectRatio",
                job.parameters.get("aspect_ratio"),
            )
        if node.type == "audio_generate" and job.status == "succeeded":
            data["audioState"] = "generated"
            data["audioProgress"] = None
        nodes.append(node.model_copy(update={"data": data}))
    return canvas.model_copy(update={"nodes": nodes, "updated_at": _now()})


def _aigc_generation_capabilities_from_model_id(model_id: str) -> list[str]:
    model_key = model_id.lower()
    if "seedream" in model_key:
        return ["text_to_image"]
    if "seededit" in model_key:
        return ["image_edit"]
    return []


def _normalized_capability_token(value: Any) -> str:
    return re.sub(
        r"[^0-9a-zA-Z_\u4e00-\u9fff]+",
        "_",
        str(value).strip(),
    ).lower()


def _is_text_model_capability(value: Any) -> bool:
    token = _normalized_capability_token(value)
    compact = token.replace("_", "")
    return (
        token in TEXT_MODEL_CAPABILITY_ALIASES
        or compact in TEXT_MODEL_CAPABILITY_ALIASES_COMPACT
    )


def _normalized_aigc_capabilities(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    capabilities: list[str] = []
    for item in values:
        if item is None:
            continue
        token = _normalized_capability_token(item)
        if not token:
            continue
        if token in SUPPORTED_AIGC_CAPABILITIES:
            capabilities.append(token)
            continue
        if token == "image_to_prompt":
            capabilities.extend(["storyboard", "reference_image"])
            continue
        if token in {"vision", "visual_text", "image_understanding"}:
            capabilities.extend(["storyboard", "reference_image"])
            continue
        if _is_text_model_capability(item):
            capabilities.append("storyboard")
    return list(dict.fromkeys(capabilities))


def _append_reference_capabilities(
    capabilities: list[str],
    model: Any,
) -> list[str]:
    next_capabilities = list(capabilities)
    if getattr(model, "supports_image", False):
        next_capabilities.append("reference_image")
    if getattr(model, "supports_video", False):
        next_capabilities.append("reference_video")
    return list(dict.fromkeys(next_capabilities))


def _has_output_generation_capability(capabilities: list[str]) -> bool:
    return any(item in OUTPUT_GENERATION_CAPABILITIES for item in capabilities)


def _capabilities_from_model(model: Any, provider: Any) -> list[str]:
    direct = _normalized_aigc_capabilities(
        list(getattr(model, "aigc_capabilities", []) or []),
    )
    if direct:
        if _has_output_generation_capability(direct):
            return direct
        return _append_reference_capabilities(direct, model)

    generate_kwargs = getattr(model, "generate_kwargs", {}) or {}
    from_kwargs = _normalized_aigc_capabilities(
        generate_kwargs.get("aigc_capabilities"),
    )
    if from_kwargs:
        if _has_output_generation_capability(from_kwargs):
            return from_kwargs
        return _append_reference_capabilities(from_kwargs, model)

    provider_meta = getattr(provider, "meta", {}) or {}
    provider_caps = provider_meta.get("aigc_capabilities", {})
    if isinstance(provider_caps, dict):
        caps = _normalized_aigc_capabilities(
            provider_caps.get(getattr(model, "id", "")),
        )
        if caps:
            if _has_output_generation_capability(caps):
                return caps
            return _append_reference_capabilities(caps, model)

    generation_caps = _aigc_generation_capabilities_from_model_id(
        str(getattr(model, "id", "") or ""),
    )
    if generation_caps:
        return generation_caps

    return []


def _tool_capabilities(tool_name: str) -> list[str]:
    name = tool_name.lower()
    if name.startswith("generate_image") or "text_to_image" in name:
        return ["text_to_image"]
    if name.startswith("edit_image") or "image_edit" in name:
        return ["image_edit"]
    if name.startswith("text_to_video"):
        return ["text_to_video"]
    if name.startswith("image_to_video"):
        return ["image_to_video"]
    if name.startswith("reference_to_video"):
        return ["reference_video", "text_to_video"]
    if name.startswith("text_to_audio") or name.startswith("generate_audio"):
        return ["text_to_audio"]
    if name.startswith("text_to_music") or name.startswith("generate_music"):
        return ["text_to_audio"]
    return []


def _reference_image_limit_for_model(
    *,
    provider_id: str = "",
    model_id: str = "",
    model_name: str = "",
    capability: str = "",
) -> int | None:
    if capability not in {"text_to_image", "image_to_image", "image_edit", "mask_edit"}:
        return None
    token = re.sub(
        r"[^a-z0-9]+",
        " ",
        f"{provider_id} {model_id} {model_name}".lower(),
    )
    if "gpt image" in token and "2" in token:
        return 16
    if "nano2" in token or "banana2" in token:
        return 16
    if "seedream" in token and "4 5" in token:
        return 10
    return 4


def _parameter_schema_for(
    capability: str,
    *,
    provider_id: str = "",
    model_id: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "negative_prompt": {"type": "string"},
            "seed": {"type": "integer"},
        },
    }
    if capability == "storyboard":
        common["properties"].update(
            {
                "textMode": {"type": "string"},
                "referenceImages": {"type": "array", "items": {"type": "string"}},
            },
        )
    elif capability.endswith("video"):
        common["properties"].update(
            {
                "duration": {
                    "type": "number",
                    "minimum": 4,
                    "maximum": 15,
                    "default": 5,
                },
                "aspect_ratio": {"type": "string"},
                "fps": {"type": "integer"},
            },
        )
        normalized_model_id = model_id.strip().lower()
        if normalized_model_id in _MXAPI_SEEDANCE_ENDPOINTS:
            is_compact = normalized_model_id in {"seedance2-fast", "seedance2-mini"}
            common["properties"].update(
                {
                    "duration": {
                        "type": "number",
                        "minimum": 4,
                        "maximum": 15,
                        "default": 5,
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": [
                            "Auto",
                            "16:9",
                            "9:16",
                            "1:1",
                            "4:3",
                            "3:4",
                            "21:9",
                        ],
                        "default": "16:9",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": (
                            ["480P", "720P"]
                            if is_compact
                            else ["480P", "720P", "1080P", "4K"]
                        ),
                        "default": "720P",
                    },
                    "generate_audio": {"type": "boolean", "default": False},
                    "return_last_frame": {"type": "boolean", "default": False},
                },
            )
        elif normalized_model_id in _MXAPI_GROK_VIDEO_MODELS:
            is_fast = normalized_model_id.endswith("-fast")
            minimum, maximum, default = (6, 30, 10) if is_fast else (5, 15, 5)
            reference_max = 7 if is_fast else 1
            common["max_reference_images"] = reference_max
            common["properties"].update(
                {
                    "duration": {
                        "type": "number",
                        "minimum": minimum,
                        "maximum": maximum,
                        "default": default,
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["2:3", "3:2", "1:1", "9:16", "16:9"],
                        "default": "16:9",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": (
                            ["480P", "720P"] if is_fast else ["480P", "720P", "1080P"]
                        ),
                        "default": "720P",
                    },
                    "referenceImages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 0 if is_fast else 1,
                        "maxItems": reference_max,
                    },
                },
            )
        elif normalized_model_id in _MXAPI_JIMENG_VIDEO_MODELS:
            is_first_last = normalized_model_id == "doubao-seedance-1-5-pro-251215"
            reference_min = 2 if is_first_last else 0
            reference_max = 2 if is_first_last else 1
            common["max_reference_images"] = reference_max
            common["supported_video_modes"] = (
                ["first_last_frames"]
                if is_first_last
                else ["text_to_video", "image_to_video"]
            )
            if is_first_last:
                common["preferred_video_mode"] = "first_last_frames"
            common["properties"].update(
                {
                    "duration": {
                        "type": "number",
                        "minimum": 2,
                        "maximum": 12,
                        "default": 5,
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4"],
                        "default": "16:9",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["480P", "720P", "1080P"],
                        "default": "1080P",
                    },
                    "referenceImages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": reference_min,
                        "maxItems": reference_max,
                    },
                },
            )
    elif "audio" in capability or "music" in capability:
        common["properties"].update(
            {
                "duration": {"type": "number"},
                "voice": {"type": "string"},
                "speech_rate": {"type": "number"},
                "audio_mode": {"type": "string"},
            },
        )
    else:
        common["properties"].update(
            {
                "size": {"type": "string"},
                "quality": {"type": "string"},
                "n": {"type": "integer"},
            },
        )
        reference_limit = _reference_image_limit_for_model(
            provider_id=provider_id,
            model_id=model_id,
            model_name=model_name,
            capability=capability,
        )
        if reference_limit:
            common["max_reference_images"] = reference_limit
            common["properties"]["referenceImages"] = {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": reference_limit,
            }
    return common


def _provider_configured_for_aigc(provider: Any) -> bool:
    if bool(getattr(provider, "disabled", False)):
        return False
    if getattr(provider, "require_api_key", True) is False:
        return True
    return bool(str(getattr(provider, "api_key", "") or "").strip())


async def build_capability_list(manager: Any | None) -> CapabilityList:
    """Build the AIGC inventory from an already resolved provider manager.

    This keeps the inventory reusable by non-HTTP callers such as sealed
    workspace runtimes without making them impersonate a Starlette request.
    """
    capabilities: list[AigcCapabilityInfo] = []
    published: set[tuple[str, str]] | None = None
    if manager is not None:
        from ..billing.model_publication import ModelPublicationService
        from ..storage.engine import get_app_engine
        from ..storage.repos.price_catalog_repo import PriceCatalogRepository

        published = ModelPublicationService(
            PriceCatalogRepository(get_app_engine())
        ).effective_pairs()
        if published is None:
            return CapabilityList(capabilities=[])
        for provider in await manager.list_provider_info():
            if not _provider_configured_for_aigc(provider):
                continue
            models = list(getattr(provider, "models", []) or []) + list(
                getattr(provider, "extra_models", []) or [],
            )
            for model in models:
                if (provider.id, model.id) not in published:
                    continue
                for capability in _capabilities_from_model(model, provider):
                    capabilities.append(
                        AigcCapabilityInfo(
                            provider_id=provider.id,
                            provider_name=provider.name,
                            model_id=model.id,
                            model_name=model.name,
                            capability=capability,
                            source="model_registry",
                            parameter_schema=_parameter_schema_for(
                                capability,
                                provider_id=provider.id,
                                model_id=model.id,
                                model_name=model.name,
                            ),
                        ),
                    )

    try:
        from ...plugins.registry import PluginRegistry

        registry = PluginRegistry()
        for manifest in registry.get_all_plugin_manifests().values():
            plugin_id = manifest.get("id") or manifest.get("name", "plugin")
            plugin_name = manifest.get("name", plugin_id)
            for tool in (manifest.get("meta") or {}).get("tools", []):
                if not isinstance(tool, dict) or not tool.get("name"):
                    continue
                for capability in _tool_capabilities(str(tool["name"])):
                    capabilities.append(
                        AigcCapabilityInfo(
                            provider_id=f"plugin:{plugin_id}",
                            provider_name=plugin_name,
                            model_id=str(tool["name"]),
                            model_name=tool.get("description") or str(tool["name"]),
                            capability=capability,
                            source="plugin_tool",
                            parameter_schema=_parameter_schema_for(
                                capability,
                                model_id=str(tool["name"]),
                                model_name=str(tool.get("description") or ""),
                            ),
                        ),
                    )
    except Exception:
        pass

    deduped = {
        (c.provider_id, c.model_id, c.capability, c.source): c for c in capabilities
    }
    result = CapabilityList(capabilities=list(deduped.values()))
    if manager is None or published is None:
        return result

    from ..aigc.model_policy import (
        AIGC_MODEL_CATEGORIES,
        AigcModelPolicyService,
        filter_capabilities,
        policy_enforcement_enabled,
    )
    from ..storage.repos.aigc_model_policy_repo import (
        AigcModelPolicyRepository,
    )

    if not policy_enforcement_enabled():
        return result

    policy_service = AigcModelPolicyService(
        AigcModelPolicyRepository(get_app_engine()),
        published_pairs=published,
        priced_pairs=published,
    )
    try:
        effective = {
            category: await policy_service.effective(category, manager)
            for category in AIGC_MODEL_CATEGORIES
        }
    except Exception as exc:
        from sqlalchemy.exc import OperationalError, ProgrammingError

        if not isinstance(exc, (OperationalError, ProgrammingError)):
            raise
        logger.warning(
            "AIGC model-policy tables are unavailable; preserving legacy inventory",
        )
        return result
    allowed = {
        category: {
            (item.provider_id, item.model_id) for item in policy.models
        }
        for category, policy in effective.items()
        if policy.configured
    }
    defaults = {
        category: AigcCategoryDefaults(
            configured=policy.configured,
            configured_default=(
                {
                    "provider_id": policy.configured_default.provider_id,
                    "model_id": policy.configured_default.model_id,
                }
                if policy.configured_default
                else None
            ),
            effective_default=(
                {
                    "provider_id": policy.effective_default.provider_id,
                    "model_id": policy.effective_default.model_id,
                }
                if policy.effective_default
                else None
            ),
            fallback_active=policy.fallback_active,
            fallback_reason=list(policy.fallback_reason),
        )
        for category, policy in effective.items()
    }
    return CapabilityList(
        capabilities=filter_capabilities(result.capabilities, allowed),
        defaults=defaults,
    )


def project_workflow_capability_catalog(
    inventory: CapabilityList,
) -> WorkflowCapabilityCatalog:
    """Project the live priced model inventory onto the closed node registry."""
    registry = workflow_node_registry()
    models = tuple(
        WorkflowAvailableModel(**item.model_dump(mode="python"))
        for item in sorted(
            inventory.capabilities,
            key=lambda value: (
                value.provider_id,
                value.model_id,
                value.capability,
                value.source,
            ),
        )
    )
    nodes = tuple(
        WorkflowNodeCapability(
            kind=registration.kind,
            title=registration.title,
            provisioning=registration.provisioning,
            provisioning_reason=registration.provisioning_reason,
            capabilities=registration.capabilities,
            input_keys=tuple(sorted(registration.input_keys)),
            parameter_keys=tuple(sorted(registration.parameter_keys)),
            input_slots={
                key: tuple(values)
                for key, values in sorted(registration.input_slots.items())
            },
            output_type=registration.output_type,
            control_id=registration.control_id,
            customer_actions=registration.customer_actions,
        )
        for registration in registry.values()
    )
    return WorkflowCapabilityCatalog(nodes=nodes, available_models=models)


async def build_workflow_capability_catalog(
    manager: Any | None,
) -> WorkflowCapabilityCatalog:
    """Return workflow nodes plus only currently published/priced models."""
    return project_workflow_capability_catalog(await build_capability_list(manager))


@router.get("/capabilities", response_model=CapabilityList)
async def list_capabilities(request: Request) -> CapabilityList:
    """List AIGC-capable provider/model/tool entries."""
    return await build_capability_list(
        getattr(request.app.state, "provider_manager", None),
    )


@router.get("/workflow-capabilities", response_model=WorkflowCapabilityCatalog)
async def list_workflow_capabilities(request: Request) -> WorkflowCapabilityCatalog:
    return await build_workflow_capability_catalog(
        getattr(request.app.state, "provider_manager", None),
    )


@router.get("/visual-dna/dimensions", response_model=VisualDnaDimensionList)
async def get_visual_dna_dimensions() -> VisualDnaDimensionList:
    return VisualDnaDimensionList(dimensions=list_visual_dna_dimensions())


@router.get("/visual-dna/elements", response_model=VisualDnaElementList)
async def get_visual_dna_elements(
    dimension: VisualDnaDimension | None = None,
    q: str | None = None,
    limit: int = 80,
    offset: int = 0,
) -> VisualDnaElementList:
    elements = list_visual_dna_elements(dimension=dimension, query=q)
    return VisualDnaElementList(
        elements=_slice_items(elements, limit=limit, offset=offset),
        total=len(elements),
    )


@router.post("/visual-dna/compile", response_model=CompiledVisualDna)
async def compile_visual_dna_prompt(
    body: VisualDnaCompileRequest = Body(...),
) -> CompiledVisualDna:
    return compile_visual_dna(body)


@router.get("/style-templates", response_model=StyleTemplateList)
async def list_style_templates(
    type: StyleTemplateType | None = None,
    model_family: str | None = None,
    category: str | None = None,
    q: str | None = None,
    commercial_only: bool = False,
    limit: int = 80,
    offset: int = 0,
) -> StyleTemplateList:
    templates = [
        template
        for template in _list_style_templates()
        if _matches_style_template_query(
            template,
            template_type=type,
            model_family=model_family,
            category=category,
            q=q,
            commercial_only=commercial_only,
        )
    ]
    templates.sort(
        key=lambda item: (
            item.last_used_at or "",
            item.use_count,
            item.updated_at or "",
        ),
        reverse=True,
    )
    return StyleTemplateList(
        templates=_slice_items(templates, limit=limit, offset=offset)
    )


@router.get("/style-templates/recent", response_model=StyleTemplateList)
async def list_recent_style_templates(
    limit: int = 30, offset: int = 0
) -> StyleTemplateList:
    templates = [
        template
        for template in _list_style_templates()
        if template.status == "enabled" and template.last_used_at
    ]
    templates.sort(key=lambda item: item.last_used_at or "", reverse=True)
    return StyleTemplateList(
        templates=_slice_items(templates, limit=limit, offset=offset)
    )


@router.get("/style-templates/favorites", response_model=StyleTemplateList)
async def list_favorite_style_templates(
    limit: int = 50, offset: int = 0
) -> StyleTemplateList:
    templates = [
        template
        for template in _list_style_templates()
        if template.status == "enabled" and template.favorite
    ]
    templates.sort(key=lambda item: item.updated_at or "", reverse=True)
    return StyleTemplateList(
        templates=_slice_items(templates, limit=limit, offset=offset)
    )


@router.post("/style-templates", response_model=AigcStyleTemplate, status_code=201)
async def upsert_style_template(
    body: AigcStyleTemplate = Body(...),
) -> AigcStyleTemplate:
    _safe_id(body.id)
    return _save_style_template(body)


@router.put("/style-templates/{template_id}", response_model=AigcStyleTemplate)
async def update_style_template(
    request: Request,
    template_id: str,
    body: AigcStyleTemplateUpdate = Body(...),
) -> AigcStyleTemplate:
    template = _load_style_template(template_id)
    _ensure_editable_style_template(template, request)
    updates = body.model_dump(exclude_unset=True)
    if "title" in updates and not str(updates["title"] or "").strip():
        raise HTTPException(status_code=400, detail="Style template title is required.")
    if "description" in updates and not str(updates["description"] or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Style template description is required.",
        )
    update_payload: dict[str, Any]
    if is_admin_request(request):
        update_payload = {
            **updates,
            "id": template.id,
            "type": updates.get("type", template.type),
            "provider": updates.get("provider", template.provider),
            "category": updates.get("category", template.category),
            "tags": updates.get("tags") if "tags" in updates else template.tags,
            "runtime_mode": updates.get("runtime_mode", template.runtime_mode),
            "effect_template_uuid": template.effect_template_uuid,
            "effect_id": template.effect_id,
        }
    else:
        update_payload = {
            **updates,
            "id": template.id,
            "type": "style",
            "provider": "internal",
            "category": "我的风格",
            "tags": updates.get("tags") or template.tags or ["我的风格"],
            "runtime_mode": "prompt_style",
            "effect_template_uuid": None,
            "effect_id": None,
        }
    updated = AigcStyleTemplate.model_validate(
        {**template.model_dump(), **update_payload},
    )
    return _save_style_template(updated)


@router.delete("/style-templates/{template_id}", status_code=204)
async def delete_style_template(request: Request, template_id: str) -> Response:
    template = _load_style_template(template_id)
    _ensure_editable_style_template(template, request)
    if template.id in DEFAULT_STYLE_TEMPLATE_IDS:
        _save_style_template(template.model_copy(update={"status": "disabled"}))
        return Response(status_code=204)
    _delete_json(_style_template_path(template.id))
    return Response(status_code=204)


@router.post("/style-templates/{template_id}/use", response_model=AigcStyleTemplate)
async def mark_style_template_used(template_id: str) -> AigcStyleTemplate:
    template = _load_style_template(template_id)
    updated = template.model_copy(
        update={
            "use_count": template.use_count + 1,
            "last_used_at": _now(),
        },
    )
    return _save_style_template(updated)


@router.post(
    "/style-templates/{template_id}/favorite", response_model=AigcStyleTemplate
)
async def update_style_template_favorite(
    template_id: str,
    body: StyleTemplateFavoriteUpdate = Body(
        default_factory=StyleTemplateFavoriteUpdate
    ),
) -> AigcStyleTemplate:
    template = _load_style_template(template_id)
    return _save_style_template(template.model_copy(update={"favorite": body.favorite}))


@router.get("/canvases", response_model=CanvasList)
async def list_canvases(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> CanvasList:
    canvases = [
        Canvas(**_read_json(path)) for path in sorted(_dir("canvases").glob("*.json"))
    ]
    canvases = [canvas for canvas in canvases if _request_owns_canvas(request, canvas)]
    canvases.sort(key=lambda item: item.updated_at, reverse=True)
    return CanvasList(canvases=_slice_items(canvases, limit=limit, offset=offset))


@router.post("/canvases", response_model=Canvas, status_code=201)
async def create_canvas(request: Request, body: CanvasUpsert = Body(...)) -> Canvas:
    now = _now()
    data = body.model_dump()
    data["meta"] = _owned_meta_for_request(request, body.meta)
    canvas = Canvas(id=str(uuid.uuid4()), created_at=now, updated_at=now, **data)
    _write_json(_json_path("canvases", canvas.id), canvas)
    return canvas


@router.get("/canvases/{canvas_id}", response_model=Canvas)
async def get_canvas(request: Request, canvas_id: str) -> Canvas:
    return _load_canvas_for_request(request, canvas_id)


@router.put("/canvases/{canvas_id}", response_model=Canvas)
async def update_canvas(
    request: Request,
    canvas_id: str,
    body: CanvasUpsert = Body(...),
) -> Canvas:
    existing = _load_canvas_for_request(request, canvas_id)
    data = body.model_dump()
    data["meta"] = _owned_meta_for_request(
        request,
        body.meta,
        existing_owner=_canvas_owner_user_id(existing),
    )
    canvas = Canvas(
        id=canvas_id,
        created_at=existing.created_at,
        updated_at=_now(),
        **data,
    )
    _write_json(_json_path("canvases", canvas_id), canvas)
    return canvas


@router.delete("/canvases/{canvas_id}", status_code=204)
async def delete_canvas(request: Request, canvas_id: str) -> Response:
    canvas_path = _json_path("canvases", canvas_id)
    _load_canvas_for_request(request, canvas_id)
    _delete_json(canvas_path)
    for job_path in _dir("jobs").glob("*.json"):
        job = AigcJob(**_read_json(job_path))
        if job.canvas_id == canvas_id:
            _delete_json(job_path)
    return Response(status_code=204)


@router.post("/jobs", response_model=AigcJob, status_code=202)
async def submit_job(request: Request, body: AigcJobCreate = Body(...)) -> AigcJob:
    await _validate_job_submission(request, body)
    job = _create_queued_job(body)
    _write_json(_json_path("jobs", job.id), job)
    await _publish_job_event(job, "AIGC job queued")
    return job


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    request: Request,
    canvas_id: str | None = None,
    status: JobStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> JobList:
    jobs = [AigcJob(**_read_json(path)) for path in sorted(_dir("jobs").glob("*.json"))]
    if canvas_id:
        _load_canvas_for_request(request, canvas_id)
        jobs = [job for job in jobs if job.canvas_id == canvas_id]
    jobs = [job for job in jobs if _request_can_access_job(request, job)]
    if status:
        jobs = [job for job in jobs if job.status == status]
    jobs.sort(key=lambda item: item.updated_at, reverse=True)
    return JobList(jobs=_slice_items(jobs, limit=limit, offset=offset))


@router.get("/jobs/{job_id}", response_model=AigcJob)
async def get_job(request: Request, job_id: str) -> AigcJob:
    return _load_job_for_request(request, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=AigcJob)
async def cancel_job(request: Request, job_id: str) -> AigcJob:
    job = _load_job_for_request(request, job_id)
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job
    job.status = "cancelled"
    job.updated_at = _now()
    job.logs.append("Job cancelled by user.")
    _write_json(_json_path("jobs", job_id), job)
    await _publish_job_event(job, "AIGC job cancelled")
    return job


@router.post("/jobs/{job_id}/retry", response_model=AigcJob, status_code=202)
async def retry_job(request: Request, job_id: str) -> AigcJob:
    original = _load_job_for_request(request, job_id)
    body = AigcJobCreate(**original.model_dump())
    await _validate_job_submission(request, body)
    retried = _create_queued_job(
        body,
        extra_logs=[f"Retried from job {original.id}."],
    )
    _write_json(_json_path("jobs", retried.id), retried)
    await _publish_job_event(retried, "AIGC job queued")
    return retried


@router.post("/jobs/{job_id}/run", response_model=AigcJob)
async def run_job(
    request: Request,
    job_id: str,
    background: bool = False,
) -> AigcJob:
    job = _load_job_for_request(request, job_id)
    if job.status == "cancelled":
        return job
    if job.status == "succeeded":
        return job

    if background:
        if job.status != "running":
            job = await _mark_job_running(job)
        _start_background_job_run(request, job_id)
        return job

    return await _run_job_to_completion(request, job_id)


@router.post(
    "/long-image-exports",
    response_model=LongImageExportResult,
    status_code=201,
)
async def export_long_image(
    request: Request,
    body: LongImageExportRequest,
) -> LongImageExportResult:
    canvas = _load_canvas_for_request(request, body.canvas_id)
    target = next((node for node in canvas.nodes if node.id == body.node_id), None)
    if target is None:
        raise HTTPException(status_code=400, detail="Long-image node not found.")
    if target.type != "long_image_export":
        raise HTTPException(
            status_code=400, detail="Node is not a long-image export node."
        )

    sections = _long_image_sections(canvas, target.id)
    if not sections:
        raise HTTPException(
            status_code=400,
            detail="Connect at least one text or image node before exporting.",
        )

    title = _clean_text(target.data.get("title")) or "公众号长图"
    job = AigcJob(
        id=str(uuid.uuid4()),
        canvas_id=canvas.id,
        node_id=target.id,
        capability="long_image_export",
        provider_id="system",
        model_id="layout",
        inputs={"section_count": len(sections)},
        parameters={
            "width": body.width,
            "slice_height": body.slice_height,
            "title": title,
        },
        status="succeeded",
        created_at=_now(),
        updated_at=_now(),
        logs=["Long-image layout rendered and sliced for upload."],
    )
    rendered = await _render_long_image(
        request,
        title=title,
        width=body.width,
        sections=sections,
    )
    full_asset = await _save_long_image_png_asset(
        request,
        job,
        rendered,
        filename=f"{target.id}-full-{job.id}.png",
        role="full",
    )
    slice_assets: list[AigcAsset] = []
    for item in _long_image_slices(rendered.height, body.slice_height):
        cropped = rendered.crop((0, item["y"], body.width, item["y"] + item["height"]))
        slice_assets.append(
            await _save_long_image_png_asset(
                request,
                job,
                cropped,
                filename=f"{target.id}-slice-{item['index']:02d}-{job.id}.png",
                role="slice",
            )
        )

    updated_canvas = _merge_long_image_export_output(
        canvas,
        target.id,
        full_asset,
        slice_assets,
    )
    job.outputs = [full_asset, *slice_assets]
    _write_json(_json_path("jobs", job.id), job)
    _write_json(_json_path("canvases", updated_canvas.id), updated_canvas)
    return LongImageExportResult(
        full_asset=full_asset,
        slice_assets=slice_assets,
        width=rendered.width,
        height=rendered.height,
        slice_height=body.slice_height,
        section_count=len(sections),
    )


@router.get("/assets", response_model=AssetList)
async def list_assets(
    request: Request,
    canvas_id: str | None = None,
    kind: Literal["image", "video", "audio", "file"] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AssetList:
    assets = [
        AigcAsset(**_read_json(path)) for path in sorted(_dir("assets").glob("*.json"))
    ]
    if canvas_id:
        _load_canvas_for_request(request, canvas_id)
        assets = [
            asset
            for asset in assets
            if str(asset.meta.get("canvas_id") or "") == canvas_id
        ]
    assets = [asset for asset in assets if _request_can_access_asset(request, asset)]
    if kind:
        assets = [asset for asset in assets if asset.kind == kind]
    assets.sort(key=lambda item: item.created_at, reverse=True)
    return AssetList(assets=_slice_items(assets, limit=limit, offset=offset))


@router.get("/assets/{asset_id}/signed-url", response_model=AssetSignedUrl)
async def get_asset_signed_url(request: Request, asset_id: str) -> AssetSignedUrl:
    asset = _load_asset_for_request(request, asset_id)
    signed_url = _signed_cloud_asset_url(asset)
    if not signed_url:
        raise HTTPException(status_code=409, detail="Asset is not cloud-backed.")
    storage_client = _cloud_storage_client_or_error()
    return AssetSignedUrl(
        url=signed_url,
        expires_in=storage_client.config.signed_url_ttl_seconds,
        provider="aliyun_oss",
    )


@router.get("/assets/{asset_id}/file", name="get_asset_file")
async def get_asset_file(request: Request, asset_id: str) -> Response:
    return await _asset_file_response(request, asset_id, require_owner=True)


async def resolve_owned_asset_for_agent_review(
    request: Request,
    asset_id: str,
    *,
    canvas_id: str,
    node_ids: set[str],
    asset_kinds: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve one owner-authorized generated asset into a model content block."""
    asset = _load_asset_for_request(request, asset_id)
    if (
        str(asset.meta.get("canvas_id") or "") != canvas_id
        or str(asset.meta.get("node_id") or "") not in node_ids
    ):
        raise HTTPException(status_code=403, detail="Asset binding mismatch.")
    source_url = _signed_cloud_asset_url(asset)
    if source_url is None:
        target = await _asset_file_path_for_request(request, asset)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Asset file not found.")
        source_url = target.as_uri()
    if asset.kind not in {"image", "video", "audio"}:
        raise HTTPException(status_code=409, detail="Asset type cannot be reviewed.")
    if asset_kinds is not None and asset.kind not in asset_kinds:
        raise HTTPException(status_code=409, detail="Asset type does not match workflow output.")
    return {
        "type": asset.kind,
        "source": {"type": "url", "url": source_url},
    }


@public_router.get("/public-assets/{asset_id}/file", name="get_public_asset_file")
async def get_public_asset_file(
    request: Request,
    asset_id: str,
    token: str = "",
) -> Response:
    if not _verify_public_asset_token(asset_id, token):
        raise HTTPException(status_code=403, detail="Invalid or expired asset token.")
    return await _asset_file_response(request, asset_id, require_owner=False)


async def _asset_file_response(
    request: Request,
    asset_id: str,
    *,
    require_owner: bool,
) -> Response:
    path = _json_path("assets", asset_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found.")
    asset = AigcAsset(**_read_json(path))
    if require_owner and not _request_can_access_asset(request, asset):
        raise HTTPException(status_code=404, detail="Asset not found.")
    cloud_response = await _cloud_asset_file_response(asset)
    if cloud_response is not None:
        return cloud_response
    target = await _asset_file_path_for_request(request, asset)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Asset file not found.")
    return FileResponse(
        target,
        media_type=asset.mime_type or "application/octet-stream",
        filename=asset.name,
    )


@router.post("/assets/direct-upload", response_model=AssetDirectUploadPrepare)
async def prepare_direct_asset_upload(
    request: Request,
    payload: AssetDirectUploadRequest,
) -> AssetDirectUploadPrepare:
    storage_client = get_object_storage_client(require_enabled=True)
    if storage_client is None:
        raise HTTPException(status_code=409, detail="Object storage is not enabled.")
    asset_id = str(uuid.uuid4())
    filename = _safe_upload_filename(payload.filename)
    suffix = Path(filename).suffix
    safe_name = f"{asset_id}{suffix}"
    mime_type = payload.mime_type or "application/octet-stream"
    relative_path = (Path("aigc_studio") / "uploads" / safe_name).as_posix()
    object_key = storage_client.build_object_key(relative_path)
    token = _direct_upload_token(
        {
            "asset_id": asset_id,
            "bucket": storage_client.config.bucket,
            "endpoint": storage_client.config.endpoint,
            "filename": filename,
            "mime_type": mime_type,
            "object_key": object_key,
            "owner_user_id": current_user_id(request),
            "size": payload.size,
        }
    )
    return AssetDirectUploadPrepare(
        asset_id=asset_id,
        upload_url=storage_client.signed_put_url(object_key, mime_type),
        headers={"Content-Type": mime_type},
        token=token,
    )


@router.post(
    "/assets/direct-upload/complete",
    response_model=AigcAsset,
    status_code=201,
)
async def complete_direct_asset_upload(
    request: Request,
    payload: AssetDirectUploadComplete,
) -> AigcAsset:
    token_payload = _verify_direct_upload_token(payload.asset_id, payload.token)
    if token_payload is None:
        raise HTTPException(status_code=403, detail="Invalid or expired upload token.")
    if str(token_payload.get("owner_user_id") or "0") != current_user_id(request):
        raise HTTPException(status_code=403, detail="Invalid or expired upload token.")
    now = _now()
    mime_type = (
        str(token_payload.get("mime_type") or "application/octet-stream").strip()
        or "application/octet-stream"
    )
    object_key = str(token_payload["object_key"])
    bucket = str(token_payload.get("bucket") or "")
    storage_meta: dict[str, Any] = {
        "provider": "aliyun_oss",
        "bucket": bucket,
        "endpoint": str(token_payload.get("endpoint") or ""),
        "object_key": object_key,
    }
    size = token_payload.get("size")
    if isinstance(size, int) and size >= 0:
        storage_meta["size"] = size
    asset = AigcAsset(
        id=payload.asset_id,
        kind=_asset_kind_for_mime(mime_type),
        name=_safe_upload_filename(str(token_payload.get("filename") or "asset")),
        path=f"oss://{bucket}/{object_key}",
        url=_asset_file_url(request, payload.asset_id),
        mime_type=mime_type,
        created_at=now,
        meta={
            "owner_user_id": current_user_id(request),
            "storage": storage_meta,
            "upload": {"mode": "direct"},
        },
    )
    _write_json(_json_path("assets", asset.id), asset)
    return asset


@router.post("/assets/upload", response_model=AigcAsset, status_code=201)
async def upload_asset(request: Request, file: UploadFile = File(...)) -> AigcAsset:
    now = _now()
    asset_id = str(uuid.uuid4())
    suffix = Path(file.filename or "asset").suffix
    safe_name = f"{asset_id}{suffix}"
    content = await file.read()
    mime_type = file.content_type or "application/octet-stream"
    kind = _asset_kind_for_mime(mime_type)

    storage_client = get_object_storage_client(require_enabled=True)
    storage_meta: dict[str, Any] | None = None
    if storage_client is not None:
        relative_path = (Path("aigc_studio") / "uploads" / safe_name).as_posix()
        storage_meta = await storage_client.upload(
            relative_path=relative_path,
            content=content,
            mime_type=mime_type,
        )
        asset_path = f"oss://{storage_meta['bucket']}/{storage_meta['object_key']}"
    else:
        target = _dir("asset_files") / safe_name
        target.write_bytes(content)
        asset_path = str(target)

    asset = AigcAsset(
        id=asset_id,
        kind=kind,
        name=file.filename or safe_name,
        path=asset_path,
        url=_asset_file_url(request, asset_id),
        mime_type=mime_type,
        created_at=now,
        meta={"owner_user_id": current_user_id(request)},
    )
    if storage_meta is not None:
        asset.meta["storage"] = storage_meta
    _write_json(_json_path("assets", asset_id), asset)
    return asset
