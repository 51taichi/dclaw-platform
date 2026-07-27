# -*- coding: utf-8 -*-
"""Cloud document connector adapters for Mindspace.

Connectors deliberately fail closed. If credentials or an official connector
endpoint are unavailable, no placeholder document text is returned or indexed.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass

from .cloud_auth import CloudAuthStore
from .parsers import DocumentParseError, parse_document_bytes


class MindspaceConnectorError(RuntimeError):
    """Raised when a cloud connector cannot pull real document content."""


@dataclass
class ConnectorStatus:
    provider: str
    configured: bool
    status: str
    message: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "status": self.status,
            "message": self.message,
        }


class CloudConnectorRegistry:
    """Small registry around officially configured connector paths."""

    def __init__(self, auth_store: CloudAuthStore | None = None) -> None:
        self.auth_store = auth_store

    def status(self) -> list[ConnectorStatus]:
        lark_config = self.auth_store.get_app_config("lark") if self.auth_store else None
        tencent_config = self.auth_store.get_app_config("tencent") if self.auth_store else None
        lark_enabled = bool(lark_config and lark_config.enabled)
        tencent_enabled = bool(tencent_config and tencent_config.enabled)
        lark_external = bool(lark_enabled and lark_config and lark_config.connector_url)
        tencent_external = bool(
            tencent_enabled
            and (
                (tencent_config and tencent_config.connector_url)
                or os.environ.get("QWENPAW_TENCENT_DOC_FETCH_URL")
            )
        )
        return [
            ConnectorStatus(
                provider="lark",
                configured=lark_enabled,
                status=(
                    "external"
                    if lark_external
                    else ("builtin" if lark_enabled else "not_configured")
                ),
                message=(
                    "Feishu/Lark external document fetch connector is configured."
                    if lark_external
                    else (
                        "Feishu/Lark built-in connector uses official export tasks with the user's authorization."
                        if lark_enabled
                        else "Configure Feishu/Lark app in admin Mindspace settings."
                    )
                ),
            ),
            ConnectorStatus(
                provider="tencent",
                configured=tencent_enabled,
                status=(
                    "external"
                    if tencent_external
                    else ("builtin" if tencent_enabled else "not_configured")
                ),
                message=(
                    "Tencent Docs external fetch connector is configured."
                    if tencent_external
                    else (
                        "Tencent Docs requires an official OpenAPI/MCP fetch connector before real content can be indexed."
                        if tencent_enabled
                        else "Configure Tencent Docs app in admin Mindspace settings."
                    )
                ),
            ),
        ]

    async def fetch_text(
        self,
        source_type: str,
        url: str,
        title: str,
        *,
        cloud_account_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        if source_type == "tencent":
            return await self._fetch_with_cloud_account(
                provider="tencent",
                url=url,
                title=title,
                cloud_account_id=cloud_account_id,
                user_id=user_id,
            )

        if source_type in {"lark", "feishu"}:
            return await self._fetch_with_cloud_account(
                provider="lark",
                url=url,
                title=title,
                cloud_account_id=cloud_account_id,
                user_id=user_id,
            )

        raise MindspaceConnectorError(f"Unsupported cloud source type: {source_type}")

    async def _fetch_via_configured_endpoint(
        self,
        endpoint: str,
        url: str,
        title: str,
        provider: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        cloud_account_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                endpoint,
                json={
                    "provider": provider,
                    "url": url,
                    "title": title,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "cloud_account_id": cloud_account_id,
                    "user_id": user_id,
                },
            )
            response.raise_for_status()
            data = response.json()
        text = data.get("text") or data.get("content")
        if not isinstance(text, str) or not text.strip():
            raise MindspaceConnectorError(
                f"{provider} connector returned no extractable document text."
            )
        return text

    def _lark_configured(self) -> bool:
        return bool(os.environ.get("LARK_APP_ID") and os.environ.get("LARK_APP_SECRET"))

    def _tencent_configured(self) -> bool:
        return bool(os.environ.get("QWENPAW_TENCENT_DOC_FETCH_URL"))

    async def _fetch_with_cloud_account(
        self,
        provider: str,
        url: str,
        title: str,
        cloud_account_id: str | None,
        user_id: str | None,
    ) -> str:
        if not self.auth_store:
            raise MindspaceConnectorError(
                f"{provider} cloud document account authorization is required."
            )
        if not cloud_account_id:
            raise MindspaceConnectorError(
                f"{provider} cloud document account authorization is required."
            )
        account = self.auth_store.get_account(
            cloud_account_id,
            user_id=str(user_id) if user_id is not None else None,
        )
        if not account or account.provider != provider:
            raise MindspaceConnectorError(
                f"{provider} cloud document account authorization is required."
            )
        config = self.auth_store.get_app_config(provider)
        if config and self.auth_store.account_token_expires_soon(account):
            try:
                account = await self.auth_store.refresh_account_token(account, config)
            except Exception as exc:
                raise MindspaceConnectorError(
                    f"{provider} cloud document account authorization expired: {exc}"
                ) from exc
        connector_url = ""
        if config and config.enabled:
            connector_url = config.connector_url
        if not connector_url and provider == "tencent":
            connector_url = os.environ.get("QWENPAW_TENCENT_DOC_FETCH_URL", "")
        if connector_url:
            return await self._fetch_via_configured_endpoint(
                connector_url,
                url,
                title,
                provider,
                access_token=account.access_token,
                refresh_token=account.refresh_token,
                cloud_account_id=account.id,
                user_id=account.user_id,
            )
        return await self._fetch_via_builtin_connector(
            provider,
            url,
            title,
            account.access_token,
        )

    async def _fetch_via_builtin_connector(
        self,
        provider: str,
        url: str,
        title: str,
        access_token: str,
    ) -> str:
        """Fetch text through QwenPaw's built-in official-API adapter.

        The adapter is intentionally fail-closed until a provider's official
        export/read API mapping is implemented. This keeps the product flow
        internal without silently indexing placeholder text.
        """
        if provider == "lark":
            return await self._fetch_lark_builtin(url, title, access_token)
        if provider == "tencent":
            return await self._fetch_tencent_builtin(url, title, access_token)
        raise MindspaceConnectorError(f"Unsupported built-in provider: {provider}")

    async def _fetch_lark_builtin(self, url: str, title: str, access_token: str) -> str:
        file_type, file_token = self._parse_lark_file(url)
        extension = self._lark_export_extension(file_type)
        base_url = os.environ.get("QWENPAW_LARK_OPEN_BASE_URL", "https://open.feishu.cn").rstrip("/")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with self._http_client(timeout=60.0) as client:
            ticket = await self._create_lark_export_task(
                client,
                base_url,
                headers,
                file_type=file_type,
                file_token=file_token,
                extension=extension,
            )
            export_file_token = await self._wait_lark_export_file_token(
                client,
                base_url,
                headers,
                ticket,
            )
            response = await client.get(
                f"{base_url}/open-apis/drive/v1/export_tasks/file/{export_file_token}/download",
                headers=headers,
            )
            response.raise_for_status()
            content = response.content
        if extension == "txt":
            text = self._decode_text(content)
        else:
            try:
                text = parse_document_bytes(
                    name=f"{title}.{extension}",
                    source_type=extension,
                    content=content,
                    mime_type=None,
                ).text
            except DocumentParseError as exc:
                raise MindspaceConnectorError(
                    f"Feishu/Lark export downloaded but parsing failed: {exc}"
                ) from exc
        if not text.strip():
            raise MindspaceConnectorError("Feishu/Lark export returned no extractable text.")
        return text

    async def _fetch_tencent_builtin(self, url: str, title: str, access_token: str) -> str:
        raise MindspaceConnectorError(
            "Tencent Docs built-in connector is enabled, but the official document "
            "export/read API binding is not implemented yet."
        )

    async def _create_lark_export_task(
        self,
        client,
        base_url: str,
        headers: dict[str, str],
        *,
        file_type: str,
        file_token: str,
        extension: str,
    ) -> str:
        response = await client.post(
            f"{base_url}/open-apis/drive/v1/export_tasks",
            json={
                "file_extension": extension,
                "token": file_token,
                "type": file_type,
            },
            headers=headers,
        )
        response.raise_for_status()
        data = self._lark_response_data(response.json())
        ticket = data.get("ticket") or data.get("task_id") or data.get("taskId")
        if not isinstance(ticket, str) or not ticket.strip():
            raise MindspaceConnectorError("Feishu/Lark export task did not return a ticket.")
        return ticket

    async def _wait_lark_export_file_token(
        self,
        client,
        base_url: str,
        headers: dict[str, str],
        ticket: str,
    ) -> str:
        last_status = ""
        for attempt in range(10):
            response = await client.get(
                f"{base_url}/open-apis/drive/v1/export_tasks/{ticket}",
                headers=headers,
            )
            response.raise_for_status()
            data = self._lark_response_data(response.json())
            result = data.get("result") if isinstance(data.get("result"), dict) else data
            file_token = (
                result.get("file_token")
                or result.get("fileToken")
                or result.get("token")
            )
            if isinstance(file_token, str) and file_token.strip():
                return file_token
            last_status = str(
                result.get("job_status")
                or result.get("status")
                or result.get("jobStatus")
                or ""
            )
            if last_status.lower() in {"failed", "fail", "error", "3"}:
                raise MindspaceConnectorError(
                    f"Feishu/Lark export task failed with status {last_status}."
                )
            if attempt < 9:
                await asyncio.sleep(0.5)
        raise MindspaceConnectorError(
            f"Feishu/Lark export task did not finish in time; last status={last_status}."
        )

    def _parse_lark_file(self, url: str) -> tuple[str, str]:
        patterns = [
            (r"/docx/([^/?#]+)", "docx"),
            (r"/docs/([^/?#]+)", "doc"),
            (r"/wiki/([^/?#]+)", "wiki"),
            (r"/sheets/([^/?#]+)", "sheet"),
            (r"/base/([^/?#]+)", "bitable"),
            (r"/mindnotes/([^/?#]+)", "mindnote"),
            (r"/file/([^/?#]+)", "file"),
        ]
        for pattern, file_type in patterns:
            match = re.search(pattern, url)
            if match:
                return file_type, match.group(1)
        raise MindspaceConnectorError(
            "Feishu/Lark document URL is not recognized. Expected docx/docs/wiki/sheets/base link."
        )

    def _lark_export_extension(self, file_type: str) -> str:
        if file_type in {"sheet", "bitable"}:
            return "xlsx"
        if file_type == "file":
            return "pdf"
        return "txt"

    def _lark_response_data(self, raw: dict) -> dict:
        code = raw.get("code")
        if code not in (None, 0):
            raise MindspaceConnectorError(
                f"Feishu/Lark API returned code={code}, msg={raw.get('msg') or raw.get('message')}"
            )
        data = raw.get("data")
        return data if isinstance(data, dict) else raw

    def _decode_text(self, content: bytes) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")

    def _http_client(self, **kwargs):
        import httpx

        return httpx.AsyncClient(**kwargs)
