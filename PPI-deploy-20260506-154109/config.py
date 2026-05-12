import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv:
    load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class FeishuSettings:
    feishu_app_id: str
    feishu_app_secret: str
    feishu_app_token: str
    ppi_table_name: str
    rsp_table_name: str
    rsp_column_name: str
    ppi_link_field: str


@dataclass(frozen=True)
class LorealSettings:
    loreal_azure_client_id: str
    loreal_azure_client_secret: str
    loreal_azure_tenant_id: str
    loreal_azure_resource: str
    loreal_context_id: str
    loreal_config_id: str


def load_feishu_settings() -> FeishuSettings:
    return FeishuSettings(
        feishu_app_id=require_env("FEISHU_APP_ID"),
        feishu_app_secret=require_env("FEISHU_APP_SECRET"),
        feishu_app_token=require_env("FEISHU_APP_TOKEN"),
        ppi_table_name=os.getenv("PPI_TABLE_NAME", "PPI CALCULATOR"),
        rsp_table_name=os.getenv("RSP_TABLE_NAME", "RSP REFERENCE-CPD"),
        rsp_column_name=os.getenv("RSP_COLUMN_NAME", "RSP(Y26 38)"),
        ppi_link_field=os.getenv("PPI_LINK_FIELD", "Link"),
    )


def load_loreal_settings() -> LorealSettings:
    return LorealSettings(
        loreal_azure_client_id=require_env("LOREAL_AZURE_CLIENT_ID"),
        loreal_azure_client_secret=require_env("LOREAL_AZURE_CLIENT_SECRET"),
        loreal_azure_tenant_id=require_env("LOREAL_AZURE_TENANT_ID"),
        loreal_azure_resource=require_env("LOREAL_AZURE_RESOURCE"),
        loreal_context_id=require_env("LOREAL_CONTEXT_ID"),
        loreal_config_id=require_env("LOREAL_CONFIG_ID"),
    )
