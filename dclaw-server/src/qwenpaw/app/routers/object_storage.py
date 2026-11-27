# -*- coding: utf-8 -*-
"""Admin APIs for object storage configuration."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..object_storage import (
    MASKED_SECRET,
    AliyunOssClient,
    ObjectStorageConfig,
    ObjectStorageStore,
)

router = APIRouter(prefix="/object-storage", tags=["object-storage"])


class ObjectStorageConfigRequest(BaseModel):
    enabled: bool = False
    endpoint: str = ""
    bucket: str = ""
    access_key_id: str = ""
    access_key_secret: str | None = None
    prefix: str = "aigc/generated"
    signed_url_ttl_seconds: int = 900


def _store() -> ObjectStorageStore:
    return ObjectStorageStore()


def _config_from_request(payload: ObjectStorageConfigRequest) -> ObjectStorageConfig:
    data = payload.model_dump()
    if data.get("access_key_secret") in {None, MASKED_SECRET}:
        data["access_key_secret"] = _store().get_config().access_key_secret
    return ObjectStorageConfig(**data)


def _xml_text(body: str, tag: str) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    value = root.findtext(tag)
    return str(value or "").strip()


def _bucket_from_string_to_sign(string_to_sign: str) -> str:
    resource = string_to_sign.strip().splitlines()[-1].strip()
    if not resource.startswith("/"):
        return ""
    return resource.lstrip("/").split("/", 1)[0].strip()


def _oss_error_detail(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text.strip()
        code = _xml_text(body, "Code")
        message = _xml_text(body, "Message")
        if code or message:
            detail = f"Aliyun OSS test upload failed: HTTP {exc.response.status_code}"
            if code:
                detail = f"{detail} {code}"
            if message:
                detail = f"{detail}: {message}"
            if code == "SignatureDoesNotMatch":
                bucket = _bucket_from_string_to_sign(_xml_text(body, "StringToSign"))
                if bucket:
                    detail = (
                        f"{detail} OSS 返回的签名 bucket 是 {bucket}，"
                        "请检查 Bucket 与自定义域名绑定关系。"
                    )
            return detail
        if len(body) > 500:
            body = f"{body[:500]}..."
        return f"Aliyun OSS test upload failed: HTTP {exc.response.status_code} {body}"
    if isinstance(exc, httpx.RequestError):
        return f"Aliyun OSS test upload failed: {exc.__class__.__name__}: {exc}"
    return f"Aliyun OSS test upload failed: {exc}"


@router.get("/config")
async def get_object_storage_config() -> dict:
    return {"config": _store().get_config().to_public_dict()}


@router.put("/config")
async def put_object_storage_config(payload: ObjectStorageConfigRequest) -> dict:
    config = _store().update_config(payload.model_dump())
    return {"config": config.to_public_dict()}


@router.post("/test")
async def test_object_storage_config(payload: ObjectStorageConfigRequest) -> dict:
    config = _config_from_request(payload)
    if not config.configured:
        raise HTTPException(status_code=400, detail="Aliyun OSS config is incomplete.")
    client = AliyunOssClient(config)
    try:
        stored = await client.upload(
            relative_path=f"connection-tests/{uuid.uuid4().hex}.txt",
            content=b"qwenpaw object storage test",
            mime_type="text/plain",
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_oss_error_detail(exc)) from exc
    return {
        "ok": True,
        "provider": stored["provider"],
        "bucket": stored["bucket"],
        "object_key": stored["object_key"],
    }
