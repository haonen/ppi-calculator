from __future__ import annotations

from typing import Any

import requests


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self._tenant_access_token: str | None = None
        self.session = requests.Session()
        self.session.trust_env = False

    def tenant_access_token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token

        response = self.session.post(
            f"{self.base_url}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get tenant token: {data}")

        self._tenant_access_token = data["tenant_access_token"]
        return self._tenant_access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_access_token()}"}

    def list_tables(self, app_token: str) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.base_url}/bitable/v1/apps/{app_token}/tables",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to list tables: {data}")
        return data["data"]["items"]

    def list_records(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token

            response = self.session.get(
                f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Failed to list records: {data}")

            payload = data["data"]
            records.extend(payload.get("items", []))
            if not payload.get("has_more"):
                return records
            page_token = payload.get("page_token")

    def batch_update_records(
        self,
        app_token: str,
        table_id: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
            headers=self._headers(),
            json={"records": records},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to update records: {data}")
        return data["data"]

    def list_fields(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token

            response = self.session.get(
                f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Failed to list fields: {data}")

            payload = data["data"]
            fields.extend(payload.get("items", []))
            if not payload.get("has_more"):
                return fields
            page_token = payload.get("page_token")

    def create_text_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
    ) -> dict[str, Any]:
        return self.create_field(app_token, table_id, field_name, 1)

    def create_number_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
    ) -> dict[str, Any]:
        return self.create_field(app_token, table_id, field_name, 2)

    def create_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        field_type: int,
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=self._headers(),
            json={"field_name": field_name, "type": field_type},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to create field {field_name!r}: {data}")
        return data["data"]["field"]

    def update_field(
        self,
        app_token: str,
        table_id: str,
        field_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.session.put(
            f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to update field {field_id!r}: {data}")
        return data["data"]["field"]

    def delete_field(
        self,
        app_token: str,
        table_id: str,
        field_id: str,
    ) -> dict[str, Any]:
        response = self.session.delete(
            f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to delete field {field_id!r}: {data}")
        return data.get("data", {})
