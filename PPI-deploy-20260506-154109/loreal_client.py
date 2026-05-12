from __future__ import annotations

from typing import Any

import requests


def _raise_for_loreal_error(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:2000]
        raise RuntimeError(f"{exc}; response={body}") from exc


class LorealGPTClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        resource: str,
        context_id: str,
        config_id: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.resource = resource
        self.context_id = context_id
        self.config_id = config_id
        self.base_url = "https://api.loreal.net/global/it4it"
        self.config_base_url = f"{self.base_url}/btdp-genaiconfig/v1"
        self.engine_base_url = f"{self.base_url}/btdp-genaiengine/v1"
        self.source_base_url = f"{self.base_url}/btdp-genaisource/v1"
        self._access_token: str | None = None
        self.session = requests.Session()
        self.session.trust_env = False

    def access_token(self) -> str:
        if self._access_token:
            return self._access_token

        response = self.session.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": f"{self.resource}/.default",
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        _raise_for_loreal_error(response)
        self._access_token = response.json()["access_token"]
        return self._access_token

    def generation(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.engine_base_url}/contexts/"
            f"{self.context_id}/configs/{self.config_id}/generations"
        )
        response = self.session.post(
            url,
            headers={"Authorization": f"Bearer {self.access_token()}"},
            json=payload,
            timeout=120,
        )
        _raise_for_loreal_error(response)
        return response.json()

    def get_models(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.engine_base_url}/models",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=30,
        )
        _raise_for_loreal_error(response)
        return response.json()

    def get_config(self, config_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.config_base_url}/contexts/{self.context_id}/configs/{config_id}",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=30,
        )
        _raise_for_loreal_error(response)
        return response.json()

    def create_config(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.config_base_url}/contexts/{self.context_id}/configs",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            json=data,
            timeout=30,
        )
        _raise_for_loreal_error(response)
        return response.json()

    def patch_config(self, config_id: str, data: dict[str, Any]) -> dict[str, Any]:
        response = self.session.patch(
            f"{self.config_base_url}/contexts/{self.context_id}/configs/{config_id}",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            json=data,
            timeout=30,
        )
        _raise_for_loreal_error(response)
        return response.json()

    def delete_config(self, config_id: str) -> bool:
        response = self.session.delete(
            f"{self.config_base_url}/contexts/{self.context_id}/configs/{config_id}",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=30,
        )
        if response.status_code == 404:
            return False
        _raise_for_loreal_error(response)
        return response.status_code == 204

    def upload_file(self, ingestion_config_id: str, file_path: str) -> dict[str, Any]:
        url = (
            f"{self.source_base_url}/contexts/{self.context_id}/configs/"
            f"{ingestion_config_id}/files"
        )
        with open(file_path, "rb") as file_obj:
            response = self.session.post(
                url,
                headers={"Authorization": f"Bearer {self.access_token()}"},
                files={"file": file_obj},
                timeout=120,
            )
        _raise_for_loreal_error(response)
        return response.json()
