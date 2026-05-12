from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from config import load_feishu_settings, load_loreal_settings
from feishu_client import FeishuClient
from loreal_client import LorealGPTClient


MODEL_IDS = [
    "chat-gemini-2.5-pro",
    "gpt-5-chat",
    "claude-4-sonnet",
]

CONFIG_ID_PREFIX = "ppi-v"
INGESTION_CONFIG_ID = os.getenv("LOREAL_INGESTION_CONFIG_ID", "demo-ingestion")
OUTPUT_DIR = Path("output")


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


SYSTEM_PROMPT = """You are an expert ecommerce promotion analyst for beauty products.
Extract product information from ecommerce window images. Return only valid JSON.
Use null when a value is not visible or uncertain. Do not guess brand names or prices.
"""

USER_PROMPT = """Please inspect this ecommerce product image URL and extract:
1. brand
2. final_price / 到手价
3. main products: product_name, spec, quantity
4. gift products: product_name, spec, quantity
5. any price mechanism text visible in the image

Return this exact JSON schema:
{{
  "brand": null,
  "final_price": null,
  "currency": "CNY",
  "main_products": [
    {{"product_name": null, "spec": null, "quantity": null}}
  ],
  "gift_products": [
    {{"product_name": null, "spec": null, "quantity": null}}
  ],
  "mechanism_text": [],
  "confidence": 0.0,
  "notes": null
}}

Image URL:
{image_url}
"""


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return cleaned[:14]


def make_client(config_id: str | None = None) -> LorealGPTClient:
    settings = load_loreal_settings()
    return LorealGPTClient(
        client_id=settings.loreal_azure_client_id,
        client_secret=settings.loreal_azure_client_secret,
        tenant_id=settings.loreal_azure_tenant_id,
        resource=settings.loreal_azure_resource,
        context_id=settings.loreal_context_id,
        config_id=config_id or settings.loreal_config_id,
    )


def get_first_ppi_link() -> str:
    settings = load_feishu_settings()
    client = FeishuClient(settings.feishu_app_id, settings.feishu_app_secret)
    table_id = next(
        table["table_id"]
        for table in client.list_tables(settings.feishu_app_token)
        if table.get("name") == settings.ppi_table_name
    )
    records = client.list_records(settings.feishu_app_token, table_id)
    for record in records:
        value = record.get("fields", {}).get(settings.ppi_link_field)
        if isinstance(value, dict) and value.get("link"):
            return value["link"]
        if isinstance(value, list) and value and isinstance(value[0], dict):
            link = value[0].get("link") or value[0].get("text")
            if link:
                return link
        if isinstance(value, str) and value.startswith("http"):
            return value
    raise RuntimeError("No non-empty Link found in PPI CALCULATOR.")


def download_image(image_url: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    response = requests.get(image_url, timeout=60)
    response.raise_for_status()
    raw_path = OUTPUT_DIR / "ppi_test_image_raw"
    raw_path.write_bytes(response.content)

    image_path = OUTPUT_DIR / "ppi_test_image.jpg"
    with Image.open(raw_path) as image:
        image.convert("RGB").save(image_path, format="JPEG", quality=95)
    return image_path


def ensure_ingestion_config(client: LorealGPTClient) -> None:
    data = {
        "is_active": True,
        "uid": INGESTION_CONFIG_ID,
        "name": "PPI image upload",
        "type": "ingestion",
        "description": "Ingestion config for PPI image multimodal tests",
        "params": {
            "document_loader": {
                "type": "PyPDFLoader",
            },
            "private_files": False,
            "publication_management": False,
            "text_splitter": {
                "type": "RecursiveCharacterTextSplitter",
                "args": {
                    "chunk_overlap": 500,
                    "chunk_size": 5000,
                    "add_start_index": True,
                    "length_function": "len",
                },
            },
        },
    }
    try:
        client.create_config(data)
    except Exception as exc:
        if "409" not in str(exc):
            raise


def upload_image_for_multimodal(client: LorealGPTClient, image_url: str) -> dict[str, str]:
    ensure_ingestion_config(client)
    image_path = download_image(image_url)
    upload = client.upload_file(INGESTION_CONFIG_ID, str(image_path))
    mime_type = upload.get("attachment_metadata", {}).get("mime_type")
    file_uri = upload.get("file_uri")
    if not mime_type or not file_uri:
        raise RuntimeError(f"Upload response did not include mime_type/file_uri: {upload}")
    return {"mime_type": mime_type, "file_uri": file_uri}


def ensure_chat_config(client: LorealGPTClient, model_id: str) -> str:
    config_id = f"{CONFIG_ID_PREFIX}-{slug(model_id)}"
    data = {
        "uid": config_id,
        "name": f"PPI vision {model_id}",
        "description": "Temporary PPI image extraction test config",
        "is_active": False,
        "type": "chat",
        "params": {
            "llm": {
                "model": model_id,
                "args": {},
            },
            "is_single_turn": True,
            "system_prompt": SYSTEM_PROMPT,
        },
    }

    try:
        client.create_config(data)
    except Exception as create_exc:
        if "409" in str(create_exc) and "Config already exists" in str(create_exc):
            return config_id
        try:
            patch_data = {
                "name": data["name"],
                "description": data["description"],
                "is_active": data["is_active"],
                "params": data["params"],
            }
            client.patch_config(config_id, patch_data)
        except Exception as patch_exc:
            raise RuntimeError(
                f"Failed to create or patch config for {model_id}. "
                f"create_error={create_exc}; patch_error={patch_exc}"
            ) from patch_exc
    return config_id


def build_payload(image_url: str, variant: str, media: dict[str, str] | None = None) -> dict[str, Any]:
    prompt = USER_PROMPT.format(image_url=image_url)
    if variant == "message":
        return {"message": prompt}
    if variant == "messages-text":
        return {
            "messages": [
                {
                    "type": "human",
                    "data": {
                        "content": prompt,
                    },
                }
            ]
        }
    if variant == "messages-content-list":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ]
        }
    if variant == "message-media":
        if not media:
            raise RuntimeError("message-media requires uploaded media metadata.")
        return {
            "message": [
                {"type": "text", "text": prompt},
                {
                    "type": "media",
                    "mime_type": media["mime_type"],
                    "file_uri": media["file_uri"],
                },
            ]
        }
    if variant == "messages-role-text":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        }
    raise ValueError(f"Unknown payload variant: {variant}")


def response_text(response: dict[str, Any]) -> str:
    messages = response.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            data = message.get("data") if isinstance(message, dict) else None
            content = data.get("content") if isinstance(data, dict) else None
            if isinstance(content, str):
                return content
    return json.dumps(response, ensure_ascii=False)


def print_preview(label: str, text: str, limit: int = 1200) -> None:
    print(label)
    print(text[:limit].encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    image_url = os.getenv("PPI_TEST_IMAGE_URL") or get_first_ppi_link()
    print(f"Testing image URL: {image_url}")
    media_by_model: dict[str, dict[str, str]] = {}

    rows: list[dict[str, Any]] = []
    for model_id in MODEL_IDS:
        setup_client = make_client()
        config_id = ensure_chat_config(setup_client, model_id)
        client = make_client(config_id)
        print(f"\n=== {model_id} ({config_id}) ===")

        for variant in ["message-media", "message", "messages-role-text", "messages-content-list", "messages-text"]:
            try:
                media = None
                if variant == "message-media":
                    media = media_by_model.get(model_id)
                    if media is None:
                        media = upload_image_for_multimodal(setup_client, image_url)
                        media_by_model[model_id] = media
                        print(f"Uploaded media: {media['mime_type']} {media['file_uri']}")
                payload = build_payload(image_url, variant, media)
                response = client.generation(payload)
                text = response_text(response)
                print_preview(f"[{variant}] OK", text)
                rows.append(
                    {
                        "model": model_id,
                        "config_id": config_id,
                        "variant": variant,
                        "ok": True,
                        "text": text,
                        "response": response,
                    }
                )
            except Exception as exc:
                error_text = str(exc)
                print_preview(f"[{variant}] FAILED", error_text, limit=600)
                rows.append(
                    {
                        "model": model_id,
                        "config_id": config_id,
                        "variant": variant,
                        "ok": False,
                        "error": str(exc),
                    }
                )

    out_file = OUTPUT_DIR / f"vision_model_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved raw results to {out_file}")


if __name__ == "__main__":
    main()
