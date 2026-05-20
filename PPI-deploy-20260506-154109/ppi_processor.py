from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from config import load_feishu_settings, load_loreal_settings
from feishu_client import FeishuClient
from loreal_client import LorealGPTClient
from test_vision_models import ensure_ingestion_config


VISION_MODEL_ID = os.getenv("PPI_VISION_MODEL_ID", "chat-gemini-2.5-flash")
VISION_CONFIG_ID = os.getenv("PPI_VISION_CONFIG_ID", "ppi-v-gemini-flash")
INGESTION_CONFIG_ID = os.getenv("LOREAL_INGESTION_CONFIG_ID", "demo-ingestion")

FIELD_PRODUCT = "Product"
FIELD_SIZE = "Size"
FIELD_FG_RSP = "FG RSP"
FIELD_PLV_DETAILS = "PLV Details (含赠品中FG)"
FIELD_PLV_RSP = "PLV RSP"
FIELD_FG_PLUS_PLV = "FG+ PLV"
FIELD_HERO_AMOUNT = "hero ml/pcs"
FIELD_ACTUAL_PRICE = "Actual Price"
FIELD_PA = "PA"
FIELD_PPI = "PPI"
FIELD_HERO_PRICE = "hero price per ml/pcs（全店）"
FIELD_CATEGORY_COUPON = "Category Coupon"
FIELD_PRICE_2 = "Price 2"
FIELD_PA_2 = "PA 2"
FIELD_PPI_2 = "PPI 2"
FIELD_HERO_PRICE_2 = "hero price per ml/pcs（QSI）"
FIELD_VIP_COUPON = "VIP Coupon"
FIELD_VIP_PRICE = "VIP Price"
FIELD_VIP_PPI = "VIP PPI"
FIELD_HERO_PRICE_VIP = "hero price per ml/pcs（VIP）"
FIELD_NOTE = "PPI备注"
FIELD_STATUS = "PPI Status"

OUTPUT_FIELDS = [
    FIELD_PRODUCT,
    FIELD_SIZE,
    FIELD_FG_RSP,
    FIELD_PLV_DETAILS,
    FIELD_PLV_RSP,
    FIELD_FG_PLUS_PLV,
    FIELD_HERO_AMOUNT,
    FIELD_ACTUAL_PRICE,
    FIELD_PA,
    FIELD_PPI,
    FIELD_HERO_PRICE,
    FIELD_CATEGORY_COUPON,
    FIELD_PRICE_2,
    FIELD_PA_2,
    FIELD_PPI_2,
    FIELD_HERO_PRICE_2,
    FIELD_VIP_COUPON,
    FIELD_VIP_PRICE,
    FIELD_VIP_PPI,
    FIELD_HERO_PRICE_VIP,
    FIELD_NOTE,
    FIELD_STATUS,
]

NUMBER_OUTPUT_FIELDS = {
    FIELD_FG_RSP,
    FIELD_PLV_RSP,
    FIELD_FG_PLUS_PLV,
    FIELD_HERO_AMOUNT,
    FIELD_ACTUAL_PRICE,
    FIELD_PA,
    FIELD_PPI,
    FIELD_HERO_PRICE,
    FIELD_CATEGORY_COUPON,
    FIELD_PRICE_2,
    FIELD_PA_2,
    FIELD_PPI_2,
    FIELD_HERO_PRICE_2,
    FIELD_VIP_COUPON,
    FIELD_VIP_PRICE,
    FIELD_VIP_PPI,
    FIELD_HERO_PRICE_VIP,
}

FIELD_ALIASES = {
    FIELD_PLV_DETAILS: ["PLV Details (含赠品中FG）"],
    FIELD_HERO_AMOUNT: ["hero \n ml/pcs", "hero\nml/pcs", "hero ml|pcs", "hero ml pcs"],
    FIELD_ACTUAL_PRICE: ["Actual\n Price", "Actual Price"],
    FIELD_CATEGORY_COUPON: ["Category\n Coupon", "Category Coupon"],
    FIELD_HERO_PRICE: ["hero price per ml/pcs（Actual Price 对应）", "hero price per ml|pcs（全店）", "hero price per ml pcs（全店）"],
    FIELD_HERO_PRICE_2: ["hero price per ml/pcs_1", "hero price per ml/pcs（Price 2 对应）", "hero price per ml/pcs(QSI)", "hero price per ml/pcs（QSI)", "hero price per ml|pcs（QSI）", "hero price per ml pcs（QSI）"],
    FIELD_VIP_COUPON: ["VIP \n Coupon", "VIP Coupon"],
    FIELD_HERO_PRICE_VIP: ["hero price per ml/pcs_2", "hero price per ml/pcs（VIP 对应）", "hero price per ml/pcs(VIP）", "hero price per ml|pcs（VIP）", "hero price per ml pcs（VIP）"],
    FIELD_NOTE: ["PPI 备注", "PPI Note", "PPI备注说明"],
}


PROMPT = """You are an expert ecommerce promotion analyst for beauty products in China.
Read the attached ecommerce window image and extract product and promotion information.

Return only valid JSON. Do not wrap it in markdown. Use null when a value is not visible.
Do not infer RSP or original price. Extract only what is visible in the image.
Before product extraction, judge whether the image is usable for PPI calculation.
Set image_readable_for_ppi = false only when BOTH conditions are true:
1. The image does not contain enough readable product text to identify the actual beauty products,
   product line, and SPU/category used for RSP matching.
2. You cannot determine the products from visible packaging, nearby captions, brand context, or the
   explicit rules in this prompt.
Do not use this as a shortcut. If there is enough text/context to identify the products, even with
some uncertainty, set image_readable_for_ppi = true and extract the best structured product list.
When image_readable_for_ppi = false, set main_products = [], gift_products = [], and notes =
"识图失败：图上没有可用于RSP匹配的明确产品名/系列SPU信息".
Examples that may be unreadable: a decorative gift-box image that only says a collection/gift-box
name such as "花如晓一醉花礼盒", shows stylized packaging, but does not provide matchable product
SPU names or enough known context to identify the actual products behind each item.
Output product names in Chinese. Visible image text has the highest priority.
If the image visibly writes a product or gift name, copy that visible name exactly and do not replace it with a common nickname.
This is especially important for gift_products. Example: if the gift text says "闪充棒", return product_name "闪充棒"; do not rewrite it as "红蛮腰次抛精华棒" or another inferred formal name.
If both Chinese and English names are visible, return the Chinese name only for product_name.
Only if no Chinese product name is visible, translate or infer the product name into the common Chinese beauty-product nickname.
Return brand as the official English brand name when visible, for example PROYA, OLAY, LOREAL PARIS, LANCOME.
Put the brand only in the top-level "brand" field. Do not include brand names in product_name.
For example, return brand "KANS" and product_name "闪充棒", not "KANS闪充棒" or "韩束闪充棒".
For example, return brand "PROYA" and product_name "红宝石精华", not "珀莱雅红宝石精华".
For masks, sachets, pads, and pieces, use specs like "1片" when the image shows pieces.
For ampoules, sachets, sticks, pieces, masks, pads, and other multi-count gifts, preserve all
quantity information shown in the image. If the image says "5*2", "5支*2盒", "1.5ml*10支",
"10片", or similar, set quantity to the total count and keep the visible expression in
quantity_text. Examples:
- "红宝石次抛精华 5*2" means spec "1.5ml", quantity 10, quantity_text "5*2".
- "面膜 5片*2盒" means spec "1片", quantity 10, quantity_text "5片*2盒".
- "次抛 1.5ml*10支" means spec "1.5ml", quantity 10, quantity_text "1.5ml*10支".

STEP 0 - Multi-tier Promotion Selection
When the image shows multiple purchase tiers, such as "买30支" vs "买60支", or "拍1件" vs "拍2件",
always select the tier with the highest quantity or spend, because that tier usually has the deepest PPI.
Extract main_products, gift_products, and final_price from the selected tier only.
Record the selected tier description in selected_tier and notes, for example:
"selected tier: 买60支到手110支 ¥789".

STEP 1 - Spatial Layout Analysis (Main vs Gift)
Before extracting products, analyze the full image layout:
1. Identify the HERO ZONE: the large central or left product image(s). These are usually main_products.
2. Identify the GIFT ZONE: smaller products placed to the right of, below, or around the hero. These are usually gift_products.
3. Read all text blocks and map each text segment to its nearest visual product group.
   Text near the hero zone describes main_products. Text near the gift zone describes gift_products.
4. Look for gift keywords: 送, 赠, 礼, 到手, 享, 加赠, 限时加赠, 会员礼, GWP, 正装礼.
   Products mentioned after these keywords are gift_products.
   Marketing trap: phrases like "拍1享7件正装", "享X件正装", "到手X件正装" make gifts sound like full size.
   The word "正装" in these phrases does NOT make the products main_products.
   Anything listed after 送/赠/享/礼/加赠/限时加赠 is a gift_product, even if called "正装".
   Record this phrase in mechanism_text with "（商家话术，实为赠品）".
5. "买X到手Y" pattern: X is the paid main product quantity; the extra quantity Y-X is gift_product.
   Example: "买45g至高到手90g" means main is 45g and gift is 45g of the same product.
6. "买正装送正装" pattern: paid full-size is main_product; the "送" full-size is gift_product.
7. When both "限时加赠" and "520加赠" or similar named gift groups appear, combine all named gift groups into gift_products.
8. Member gifts, such as 会员礼, ¥0.01确权礼, 会员确权礼, are gift_products with limited_edition = "会员礼".
   Include them only if they are beauty products; exclude non-beauty member gifts.
9. If a product appears both in a purchase photo and a gift listing, trust the gift listing label.
10. Gift-box / set hierarchy rule:
   Many Douyin images write the product line or set name only once in a title or caption, and then use
   short category names for each bottle, such as 洁面, 水, 乳, 精华, 面霜, 面膜.
   When several products are visually grouped inside the same box, same border, same caption line, or
   same gift group, inherit the nearest visible product-line / set / SPU context for every product.
   Do not output generic product_name values like "洁面", "水", "乳", "精华", "面霜", "面膜" by themselves
   when a nearby title/caption/packaging identifies the line or SPU.
   Expand each item to a matchable name such as "超A肽洁面", "超A肽水", "超A肽乳", "超A肽精华",
   "超A肽面霜", "凝时鲜颜水", "凝时鲜颜乳", "凝时鲜颜眼霜".
11. A gift box, set box, or paper bag is packaging, not a replacement for product extraction.
   If the image shows "礼盒/套装" with visible bottle/tube/jar products or a text list in parentheses,
   list every beauty product inside as separate main_products or gift_products.
   Do not return only the gift-box name as the paid product.
12. Parentheses/list parsing rule:
   Text like "某某礼盒（洁面100g+精华水100ml+精华乳100ml+精华30ml+面霜50g）"
   means all listed items inherit "某某" as the product-line/SPU context.
   Return separate products such as "某某洁面", "某某精华水", "某某精华乳", "某某精华", "某某面霜".
   Apply the same rule to gift captions such as "水115ml*2+乳115g*2+眼霜15g+面霜50g" when a nearby
   set title or product packaging identifies the shared line.

STEP 2 - Product Information Extraction
For each product, extract matching qualifiers when visible. These are used only for RSP matching
and should be separate from the short product_name:
- category: the product category/SPU class, such as 防晒, 精华, 面膜, 面霜, 水, 乳液,
  眼霜, 洁面, 卸妆, 粉底, 气垫, 口红, 唇釉, 腮红, 眼影, 散粉, 眉笔, 睫毛膏.
  Fill category for every main_product and gift_product whenever visible or inferable from the product name.
- spec: the visible size/count must be attached to the exact product it belongs to.
  If the image shows "40ml", "60ml", "100ml", "1.5ml*5", "5片", or similar near a product,
  put that value in the product's spec and quantity/quantity_text. Do not leave spec null when the
  size/count is visible anywhere in the product caption, packaging, or nearby list.
- version: such as "1.0", "2.0", "3.0", "第三代"
- variant: such as "干皮版", "油皮版", "滋润版", "轻盈版", "清爽版", "经典型", "轻润型"
- shade: shade number or color name, such as "01", "象牙白", "粉色", "#01黄油可颂"
- certificate: such as "特证", "美白特证"
- limited_edition: special edition, limited edition, collaboration edition, anniversary edition, or special color packaging.
  Examples: "510周年庆限定", "520限定", "联名款"

Important classification rules:
- main_products: only the paid/core full-size product the shopper is buying.
- gift_products: all free gifts, mini sizes, extra bottles/tubes, masks, samples, member gifts, and extra volume included in "到手/享".
- Example: "买50ml到手110ml" means 50ml is main product, the additional 60ml should be gift products.

STEP 3 - Price Extraction
Extract final_price as the actual checkout price visible in the image.
Price priority rules:
1. Use the price labeled 到手价, 实付价, 券后价, 到手 ¥. This is the true final_price.
2. If only a strikethrough price is visible with no final checkout price, set final_price = null.
3. If multiple prices appear, use the price matching the selected_tier from STEP 0.
4. For makeup/cosmetics images, it is common that no final_price is shown.
   If no checkout price is visible, set final_price = null and add "彩妆图无到手价，需人工填写" to notes.
5. Member vouchers, such as 会员券 ¥45 or 满减券, are not deducted from final_price. Record them in mechanism_text only.
6. If the image only shows a voucher or discount offer with no base price, set final_price = null.

STEP 4 - Spec and Quantity for Makeup/Cosmetics
For makeup products such as eyeshadow palettes, lipsticks, blush, powder, foundation, cushion, mascara, eyebrow pencil:
- spec: use piece count or weight when visible, for example "6.5g", "8g", "1pcs", "1支". If not visible, set null.
- quantity: usually 1 unless the image shows multiple units sold together.
- hero_unit: for makeup, the unit is usually pcs rather than ml. Add "彩妆，hero单位为pcs" to notes.
- If neither ml/g nor pcs is determinable from the image, set spec = null and add "规格不可见，需人工填写" to notes.

STEP 5 - Non-Beauty GWP Filter
Do not include the following non-beauty gift types in gift_products:
化妆包, 收纳包, 包包, 手提包, 帆布包, 托特包, 洗漱包,
化妆镜, 镜子, 梳子, 发箍, 发夹, 头绳,
毛巾, 浴巾, 洗脸巾,
杯子, 水杯, 保温杯,
钥匙扣, 挂件, 徽章, 贴纸, 冰箱贴,
玩偶, 公仔, 周边, ip周边,
礼盒, 礼袋, 手账, 明信片,
承诺贺卡, 贺卡, 卡片

Exception: if the item name also contains a beauty keyword, include it as a gift_product.
Beauty keywords: 精华, 面霜, 面膜, 乳液, 爽肤水, 精华水, 眼霜, 洁面, 卸妆, 防晒,
粉底, 气垫, 口红, 唇釉, 腮红, 眼影, 散粉, 眉笔, 睫毛膏, 香水, 小样, 试用装.
When a non-beauty gift is excluded, add it to mechanism_text as:
"非美妆GWP（不计入PPI）: [产品名] x[数量]".

Nickname rules for product_name:
- First use the visible product/gift name from the image exactly when present.
- Only infer a short Chinese nickname when the image does not show a clear product/gift name.
- If the image shows a long formal product name but no clear short nickname, infer nickname as "product line + category".
- Product names must be specific enough for RSP matching. Avoid standalone generic category names:
  洁面, 水, 乳, 精华, 面霜, 面膜, 眼霜, 防晒, 唇膏, 口红.
  If any of these appear without a series/SPU name, look at the nearest group title, set name,
  package text, caption before parentheses, or visually repeated packaging line and prepend the inherited context.
- For a paid gift box or skincare set, output the individual included products, not only the set name.
  Keep the set/gift-box name in notes or selected_tier if useful, but main_products/gift_products must contain
  the actual products used for RSP lookup.
- For PECHOIN/百雀羚 examples:
  - "超A肽/3D环肽/超A肽3.0" line + 洁面/水/乳/精华/面霜 => "超A肽洁面", "超A肽水", "超A肽乳", "超A肽精华", "超A肽面霜".
- For CHANDO/自然堂 examples:
  - "凝时鲜颜/焕活/抗皱/紧致淡纹" line + 洁面/水/乳/眼霜/面霜 => "凝时鲜颜洁面", "凝时鲜颜水", "凝时鲜颜乳", "凝时鲜颜眼霜", "凝时鲜颜面霜".
  - If the visible product packaging says "NATURE DECODING" and the caption says 自然堂紧致焕活礼盒2.0,
    use "凝时鲜颜" or "紧致焕活" as the inherited line, not just "水" or "乳".
- For PROYA/珀莱雅 examples:
  - 红宝石 line + 精华/essence/serum => "红宝石精华"
  - 红宝石 line + 面膜/mask => "红宝石面膜"
  - 红宝石 line + 面霜/cream => "红宝石面霜"
  - 双抗 line + 精华/essence/serum => "双抗精华"
  - 双抗 line + 面膜/mask => "双抗面膜"
  - 能量 line + 精华/essence/serum => "能量精华"
  - 源力 line + 精华/essence/serum => "源力精华"
- For PROYA 双抗 line, do not put version or certificate clues into product_name.
  For example, if visible text contains "双抗3.0特证精华", return product_name "双抗精华",
  version "3.0", and certificate "特证".
- Use the same nickname for gift mini sizes if it is the same product line/category as the main product.

PROYA/珀莱雅 visual common-sense rules:
- If text is unclear but the package is clearly red, treat it as 红宝石系列.
- If text is unclear but the package is clearly yellow, treat it as 双抗系列.
- If text is unclear but the package is clearly misty blue / grey-blue, treat it as 源力系列.
- If text is unclear but the package is clearly brown/dark gold, treat it as 能量系列.
- Combine the inferred line with the visible or likely category, for example 精华, 面霜, 面膜, 水, 乳液, 眼霜.
- Mention color-based inference briefly in notes when you use it.

Schema:
{
  "image_readable_for_ppi": true,
  "readability_issue": null,
  "brand": null,
  "final_price": null,
  "currency": "CNY",
  "selected_tier": null,
  "main_products": [
    {
      "product_name": "中文产品名或中文昵称",
      "category": null,
      "spec": null,
      "quantity": null,
      "quantity_text": null,
      "version": null,
      "variant": null,
      "shade": null,
      "certificate": null,
      "limited_edition": null
    }
  ],
  "gift_products": [
    {
      "product_name": "中文产品名或中文昵称",
      "category": null,
      "spec": null,
      "quantity": null,
      "quantity_text": null,
      "version": null,
      "variant": null,
      "shade": null,
      "certificate": null,
      "limited_edition": null
    }
  ],
  "mechanism_text": [],
  "confidence": 0.0,
  "notes": null
}
"""


@dataclass
class RspEntry:
    brand: str
    category: str
    product_name: str
    product_nickname: str
    spec: str
    rsp: float | None
    record: dict[str, Any]


@dataclass
class RspLookupNote:
    kind: str
    text: str


def loreal_client(config_id: str = VISION_CONFIG_ID) -> LorealGPTClient:
    settings = load_loreal_settings()
    return LorealGPTClient(
        client_id=settings.loreal_azure_client_id,
        client_secret=settings.loreal_azure_client_secret,
        tenant_id=settings.loreal_azure_tenant_id,
        resource=settings.loreal_azure_resource,
        context_id=settings.loreal_context_id,
        config_id=config_id,
    )


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", "", str(value).lower())
    return text.replace("菁华", "精华")


QUALIFIER_RULES: list[tuple[str, list[str]]] = [
    ("1.0", ["1.0", "一代", "第1代", "第一代"]),
    ("2.0", ["2.0", "二代", "第2代", "第二代"]),
    ("3.0", ["3.0", "三代", "第3代", "第三代"]),
    ("干皮版", ["干皮版", "干皮", "滋润版", "滋润型", "滋润", "经典型"]),
    ("油皮版", ["油皮版", "油皮", "清爽版", "清爽型", "轻盈版", "轻盈型", "轻盈", "轻润型"]),
    ("特证", ["特证", "美白特证"]),
    ("限定", ["限定", "限定版", "特别版", "联名", "联名款", "礼盒限定", "特殊限定", "周年庆限定", "会员礼"]),
]


PRODUCT_QUALIFIER_FIELDS = [
    "version",
    "variant",
    "shade",
    "color",
    "certificate",
    "limited_edition",
    "edition",
]


BRAND_ALIASES = {
    "proya": ["proya", "珀莱雅"],
    "olay": ["olay", "玉兰油"],
    "kans": ["kans", "韩束"],
    "lorealparis": ["lorealparis", "l'oréalparis", "欧莱雅"],
    "skinceuticals": ["skinceuticals", "修丽可"],
    "collgene": ["collgene", "可丽金", "可复美可丽金"],
    "mistine": ["mistine", "蜜丝婷"],
}


def brand_tokens(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        tokens: set[str] = set()
        for item in value:
            tokens.update(brand_tokens(item))
        return tokens

    norm = normalize_text(value)
    tokens = {norm} if norm else set()
    for canonical, aliases in BRAND_ALIASES.items():
        if any(normalize_text(alias) in norm for alias in aliases):
            tokens.add(canonical)
            tokens.update(normalize_text(alias) for alias in aliases)
    return {token for token in tokens if token}


def same_brand(left: Any, right: Any) -> bool:
    left_tokens = brand_tokens(left)
    right_tokens = brand_tokens(right)
    if not left_tokens or not right_tokens:
        return True
    return bool(left_tokens & right_tokens) or any(
        a in b or b in a for a in left_tokens for b in right_tokens
    )


def strip_brand_from_product_name(brand: Any, product_name: Any) -> Any:
    if not product_name:
        return product_name
    text = str(product_name).strip()
    brand_norm = normalize_text(brand)
    aliases: list[str] = []
    for canonical, values in BRAND_ALIASES.items():
        if canonical in brand_norm or any(normalize_text(value) in brand_norm for value in values):
            aliases.extend(values)
    aliases.extend(str(brand or "").split())

    changed = True
    while changed:
        changed = False
        for alias in sorted({alias for alias in aliases if alias}, key=len, reverse=True):
            pattern = re.compile(rf"^\s*{re.escape(alias)}[\s·・-]*", re.I)
            new_text = pattern.sub("", text).strip()
            if new_text != text:
                text = new_text
                changed = True
    return text or product_name


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    return float(match.group(0))


def first_field(fields: dict[str, Any], names: list[str]) -> Any:
    normalized_map = {normalize_text(key): value for key, value in fields.items()}
    for name in names:
        if name in fields:
            return fields[name]
        normalized_name = normalize_text(name)
        if normalized_name in normalized_map:
            return normalized_map[normalized_name]
    return None


def field_lookup_key(value: Any) -> str:
    text = normalize_text(value)
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def user_field_value(fields: dict[str, Any], field_name: str) -> Any:
    candidates = [field_name, *FIELD_ALIASES.get(field_name, [])]
    by_key = {field_lookup_key(key): value for key, value in fields.items()}
    for candidate in candidates:
        if candidate in fields:
            return fields[candidate]
        value = by_key.get(field_lookup_key(candidate))
        if value is not None:
            return value
    return None


def parse_spec_amount(spec: Any) -> tuple[float, str] | None:
    if spec is None:
        return None
    text = str(spec).lower().replace("毫升", "ml").replace("克", "g")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|g|片|pcs|pc|支|只|条|颗|个|件|套)", text)
    if not match:
        return None
    unit = match.group(2)
    if unit in {"pcs", "pc", "支", "只", "条", "颗", "个", "件", "套"}:
        unit = "pcs"
    return float(match.group(1)), unit


def parse_total_spec_amount(spec: Any) -> tuple[float, str] | None:
    if spec is None:
        return None
    text = str(spec).lower().replace("毫升", "ml").replace("克", "g")
    normalized = text.replace("×", "*").replace("x", "*")
    amount_times_count = re.search(
        r"(\d+(?:\.\d+)?)\s*(ml|g|片|pcs|pc|支|只|条|颗|个|件|套)\s*\*\s*(\d+(?:\.\d+)?)",
        normalized,
        re.I,
    )
    if amount_times_count:
        unit = amount_times_count.group(2)
        if unit in {"pcs", "pc", "支", "只", "条", "颗", "个", "件", "套"}:
            unit = "pcs"
        return float(amount_times_count.group(1)) * float(amount_times_count.group(3)), unit

    count_times_pack = re.search(
        r"(\d+(?:\.\d+)?)\s*(片|pcs|pc|支|只|条|颗|个|件|套)\s*\*\s*(\d+(?:\.\d+)?)",
        normalized,
        re.I,
    )
    if count_times_pack:
        unit = count_times_pack.group(2)
        if unit in {"pcs", "pc", "支", "只", "条", "颗", "个", "件", "套"}:
            unit = "pcs"
        return float(count_times_pack.group(1)) * float(count_times_pack.group(3)), unit

    return parse_spec_amount(spec)


def infer_total_quantity_from_text(value: Any) -> float | None:
    text = str(value or "")
    if not text.strip():
        return None
    normalized = text.replace("×", "*").replace("x", "*").replace("X", "*")

    count_unit = r"(?:支|只|条|颗|片|pcs|pc|个|件|套|盒|瓶|袋|包)"
    amount_times_count = re.search(
        rf"\d+(?:\.\d+)?\s*(?:ml|g)\s*\*\s*(\d+(?:\.\d+)?)\s*{count_unit}?",
        normalized,
        re.I,
    )
    if amount_times_count:
        return float(amount_times_count.group(1))

    count_times_pack = re.search(
        rf"(\d+(?:\.\d+)?)\s*{count_unit}?\s*\*\s*(\d+(?:\.\d+)?)\s*{count_unit}?",
        normalized,
        re.I,
    )
    if count_times_pack:
        return float(count_times_pack.group(1)) * float(count_times_pack.group(2))

    single_count = re.search(rf"(\d+(?:\.\d+)?)\s*{count_unit}", normalized, re.I)
    if single_count:
        return float(single_count.group(1))
    return None


def ensure_product_quantity(product: dict[str, Any]) -> None:
    if parse_float(product.get("quantity")):
        return
    text = " ".join(
        str(value or "")
        for value in [
            product.get("quantity_text"),
            product.get("spec"),
            product.get("raw_product_name"),
            product.get("product_name"),
        ]
    )
    inferred = infer_total_quantity_from_text(text)
    if inferred is not None:
        product["quantity"] = inferred


def is_proya_ruby_ampoule(product: dict[str, Any]) -> bool:
    text = normalize_text(f"{product.get('product_name') or ''} {product.get('raw_product_name') or ''}")
    return "红宝石" in text and ("次抛" in text or "安瓶" in text)


def apply_special_product_cases(product: dict[str, Any]) -> None:
    if is_proya_ruby_ampoule(product):
        product["matched_spec"] = product.get("matched_spec") or "1.5ml"
        product["product_name"] = "红宝石精华"
        ensure_product_quantity(product)


def entry_spec_amount(entry: RspEntry) -> tuple[float, str] | None:
    return parse_spec_amount(entry.spec) or parse_spec_amount(entry.product_name)


def product_label(product: dict[str, Any]) -> str:
    name = product.get("product_name") or ""
    spec = product.get("matched_spec") if product.get("matched_spec") and not parse_spec_amount(product.get("spec")) else product.get("spec")
    spec = spec or ""
    qty = product.get("quantity") or 1
    return f"{name} {spec} x{qty}".strip()


def format_products(products: list[dict[str, Any]]) -> str:
    return "\n".join(product_label(product) for product in products if product)


GENERIC_UNMATCHABLE_PRODUCT_NAMES = {
    "洁面",
    "洗面奶",
    "水",
    "爽肤水",
    "柔肤水",
    "精华水",
    "乳",
    "乳液",
    "精华",
    "精华液",
    "面霜",
    "霜",
    "面膜",
    "眼霜",
    "防晒",
    "唇膏",
    "口红",
}


PACKAGING_ONLY_TOKENS = [
    "礼盒",
    "套盒",
    "套装",
    "礼包",
    "组合",
    "套组",
]


BEAUTY_CATEGORY_TOKENS = [
    "洁面",
    "洗面奶",
    "水",
    "爽肤水",
    "柔肤水",
    "精华水",
    "乳",
    "乳液",
    "精华",
    "精华液",
    "面霜",
    "霜",
    "面膜",
    "眼霜",
    "防晒",
    "粉底",
    "气垫",
    "口红",
    "唇釉",
    "腮红",
    "眼影",
    "散粉",
    "眉笔",
    "睫毛膏",
    "香水",
]


def is_generic_unmatchable_product_name(value: Any) -> bool:
    norm = normalize_text(value)
    if not norm:
        return True
    return norm in {normalize_text(item) for item in GENERIC_UNMATCHABLE_PRODUCT_NAMES}


def is_packaging_only_product_name(value: Any) -> bool:
    norm = normalize_text(value)
    if not norm:
        return True
    if not any(token in norm for token in PACKAGING_ONLY_TOKENS):
        return False
    return not any(token in norm for token in BEAUTY_CATEGORY_TOKENS)


def recognition_failure_reason(extraction: dict[str, Any]) -> str | None:
    readable = extraction.get("image_readable_for_ppi")
    if isinstance(readable, bool) and not readable:
        return "识图失败"

    main_products = extraction.get("main_products") or []
    if not main_products:
        return "识图失败"

    names = [product.get("product_name") for product in main_products]
    if all(is_generic_unmatchable_product_name(name) for name in names):
        return "识图失败"
    if len(main_products) == 1 and is_packaging_only_product_name(names[0]):
        return "识图失败"
    return None


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def ai_text(response: dict[str, Any]) -> str:
    messages = response.get("messages") or []
    if messages:
        content = messages[-1].get("data", {}).get("content")
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if text_parts:
                return "\n".join(text_parts)
        if isinstance(content, str):
            return content
    return json.dumps(response, ensure_ascii=False)


def download_as_jpeg(image_url: str) -> Path:
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        image_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    suffix = ".webp" if content_type == "image/webp" else (mimetypes.guess_extension(content_type) or ".img")
    temp_dir = Path(tempfile.mkdtemp(prefix="ppi_image_"))
    raw_path = temp_dir / f"raw{suffix}"
    jpg_path = temp_dir / "image.jpg"
    raw_path.write_bytes(response.content)
    try:
        with Image.open(raw_path) as image:
            image.convert("RGB").save(jpg_path, format="JPEG", quality=95)
        return jpg_path
    except Exception:
        return raw_path


def extract_product_info(image_url: str) -> tuple[dict[str, Any], str, str]:
    setup_client = loreal_client()
    ensure_vision_config(setup_client)
    ensure_ingestion_config(setup_client)

    image_path = download_as_jpeg(image_url)
    upload = setup_client.upload_file(INGESTION_CONFIG_ID, str(image_path))
    mime_type = upload.get("attachment_metadata", {}).get("mime_type")
    file_uri = upload.get("file_uri")
    if not mime_type or not file_uri:
        raise RuntimeError(f"Image upload failed: {upload}")

    response = setup_client.generation(
        {
            "message": [
                {"type": "text", "text": PROMPT},
                {"type": "media", "mime_type": mime_type, "file_uri": file_uri},
            ]
        }
    )
    text = ai_text(response)
    data = normalize_extraction(extract_json(text))
    return data, json.dumps(response, ensure_ascii=False), "media_upload"


def ensure_vision_config(client: LorealGPTClient) -> None:
    data = {
        "uid": VISION_CONFIG_ID,
        "name": f"PPI vision {VISION_MODEL_ID}",
        "description": "PPI image extraction config",
        "is_active": False,
        "type": "chat",
        "params": {
            "llm": {
                "model": VISION_MODEL_ID,
                "args": {},
            },
            "is_single_turn": True,
            "system_prompt": "You extract product information from ecommerce images. Return valid JSON only.",
        },
    }
    try:
        client.create_config(data)
    except Exception as exc:
        if "409" not in str(exc):
            raise


def normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    main_products = list(data.get("main_products") or [])
    gift_products = list(data.get("gift_products") or [])

    for product in main_products + gift_products:
        raw_product_name = product.get("product_name")
        product["raw_product_name"] = raw_product_name
        product["match_qualifiers"] = product_match_qualifiers(product)
        product["product_name"] = strip_brand_from_product_name(
            data.get("brand"),
            raw_product_name,
        )
        product["product_name"] = normalize_product_nickname(
            data.get("brand"),
            product.get("product_name"),
        )
        product["category"] = product.get("category") or product_category(product)
        ensure_product_quantity(product)
        apply_special_product_cases(product)
        product["match_qualifiers"] = product_match_qualifiers(product)

    by_name: dict[str, list[tuple[int, dict[str, Any], tuple[float, str] | None]]] = {}
    for idx, product in enumerate(main_products):
        name = normalize_text(product.get("product_name"))
        if not name:
            continue
        by_name.setdefault(name, []).append((idx, product, parse_spec_amount(product.get("spec"))))

    move_indexes: set[int] = set()
    for products in by_name.values():
        measured = [item for item in products if item[2] is not None]
        if len(measured) <= 1:
            continue
        units = {item[2][1] for item in measured if item[2]}
        if len(units) != 1:
            continue
        largest = max(measured, key=lambda item: item[2][0] if item[2] else 0)
        for idx, product, spec in measured:
            if idx != largest[0]:
                move_indexes.add(idx)

    if move_indexes:
        new_main = []
        for idx, product in enumerate(main_products):
            if idx in move_indexes:
                gift_products.append(product)
            else:
                new_main.append(product)
        data["main_products"] = new_main
        data["gift_products"] = gift_products

    return data


def add_unique(values: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def detected_qualifiers(text: Any) -> list[str]:
    norm = normalize_text(text)
    labels: list[str] = []
    if not norm:
        return labels
    for label, aliases in QUALIFIER_RULES:
        if any(normalize_text(alias) in norm for alias in aliases):
            add_unique(labels, label)
    return labels


def product_match_qualifiers(product: dict[str, Any]) -> list[str]:
    qualifiers: list[str] = []
    source_values = [
        product.get("raw_product_name"),
        product.get("product_name"),
        product.get("spec"),
    ]
    for field in PRODUCT_QUALIFIER_FIELDS:
        value = product.get(field)
        if isinstance(value, list):
            for item in value:
                add_unique(qualifiers, item)
                source_values.append(item)
        else:
            add_unique(qualifiers, value)
            source_values.append(value)

    for value in source_values:
        for label in detected_qualifiers(value):
            add_unique(qualifiers, label)
    return qualifiers


CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("防晒", ["防晒", "spf", "sunscreen", "sunblock", "小黄帽"]),
    ("洁面", ["洁面", "洗面奶", "cleanser"]),
    ("卸妆", ["卸妆", "cleansing"]),
    ("精华", ["精华", "精华液", "serum", "essence", "次抛", "安瓶"]),
    ("面膜", ["面膜", "mask"]),
    ("面霜", ["面霜", "cream", "霜"]),
    ("乳液", ["乳液", "乳", "lotion", "emulsion"]),
    ("水", ["爽肤水", "精华水", "柔肤水", "水", "toner"]),
    ("眼霜", ["眼霜", "eyecream", "eye cream", "eye"]),
    ("粉底", ["粉底", "foundation"]),
    ("气垫", ["气垫", "cushion"]),
    ("口红", ["口红", "唇膏", "lipstick"]),
    ("唇釉", ["唇釉", "lip glaze"]),
    ("腮红", ["腮红", "blush"]),
    ("眼影", ["眼影", "eyeshadow"]),
    ("散粉", ["散粉", "粉饼", "powder"]),
    ("眉笔", ["眉笔", "eyebrow"]),
    ("睫毛膏", ["睫毛膏", "mascara"]),
    ("香水", ["香水", "perfume"]),
]


def infer_category_from_text(value: Any) -> str:
    norm = normalize_text(value)
    if not norm:
        return ""
    for label, aliases in CATEGORY_RULES:
        if any(normalize_text(alias) and normalize_text(alias) in norm for alias in aliases):
            return label
    return ""


def product_category(product: dict[str, Any]) -> str:
    for value in [
        product.get("category"),
        product.get("product_name"),
        product.get("raw_product_name"),
        product.get("spec"),
    ]:
        category = infer_category_from_text(value)
        if category:
            return category
    return ""


def entry_category(entry: RspEntry) -> str:
    for value in [entry.category, entry.product_nickname, entry.product_name, entry.spec]:
        category = infer_category_from_text(value)
        if category:
            return category
    return ""


def same_category(product: dict[str, Any], entry: RspEntry) -> bool:
    product_cat = product_category(product)
    entry_cat = entry_category(entry)
    if not product_cat or not entry_cat:
        return False
    return normalize_text(product_cat) == normalize_text(entry_cat)


def qualifier_match_score(entry: RspEntry, qualifiers: list[str]) -> int:
    entry_norm = normalize_text(f"{entry.product_name} {entry.product_nickname} {entry.spec}")
    score = 0
    for qualifier in qualifiers:
        qualifier_norm = normalize_text(qualifier)
        if not qualifier_norm:
            continue
        aliases = [qualifier]
        for label, rule_aliases in QUALIFIER_RULES:
            if qualifier == label or qualifier_norm == normalize_text(label) or qualifier_norm in {
                normalize_text(alias) for alias in rule_aliases
            }:
                aliases = [label, *rule_aliases]
                break
        if any(normalize_text(alias) and normalize_text(alias) in entry_norm for alias in aliases):
            score += 1
    return score


def disambiguate_entries_with_qualifiers(
    product: dict[str, Any],
    entries: list[RspEntry],
) -> list[RspEntry]:
    if len(entries) <= 1:
        return entries
    qualifiers = product_match_qualifiers(product)
    if not qualifiers:
        return entries
    scored = [(qualifier_match_score(entry, qualifiers), entry) for entry in entries]
    best_score = max(score for score, _entry in scored)
    if best_score <= 0:
        return entries
    return [entry for score, entry in scored if score == best_score]


def normalize_product_nickname(brand: Any, product_name: Any) -> Any:
    if not product_name:
        return product_name
    text = str(product_name)
    norm = normalize_text(text)
    brand_norm = normalize_text(brand)

    is_proya = "proya" in brand_norm or "珀莱雅" in brand_norm or any(
        token in norm for token in ["红宝石", "双抗", "能量", "源力"]
    )
    if not is_proya:
        return product_name

    line_rules = [
        ("红宝石", ["红宝石", "ruby", "胜肽", "紧致"]),
        ("双抗", ["双抗", "抗氧", "抗糖"]),
        ("能量", ["能量"]),
        ("源力", ["源力"]),
    ]
    category_rules = [
        ("面膜", ["面膜", "mask"]),
        ("面霜", ["面霜", "cream", "霜"]),
        ("精华", ["精华", "essence", "serum", "次抛", "安瓶"]),
        ("乳液", ["乳液", "乳"]),
        ("水", ["爽肤水", "精华水", "柔肤水", "水"]),
        ("眼霜", ["眼霜", "eyecream", "eye"]),
    ]

    line = None
    category = None
    for label, tokens in line_rules:
        if any(token in norm for token in tokens):
            line = label
            break
    for label, tokens in category_rules:
        if any(token in norm for token in tokens):
            category = label
            break

    if line and category:
        return f"{line}{category}"
    return product_name


def is_proya_dual_special_version(value: Any) -> bool:
    norm = normalize_text(value)
    if not norm:
        return False
    has_dual = any(token in norm for token in ["双抗", "抗氧", "抗糖"])
    has_special = any(token in norm for token in ["特证", "3.0", "第三代", "美白特证"])
    return has_dual and has_special


def product_requires_proya_dual_special(product: dict[str, Any]) -> bool:
    qualifier_text = " ".join(product_match_qualifiers(product))
    return (
        is_proya_dual_special_version(product.get("product_name"))
        or is_proya_dual_special_version(product.get("raw_product_name"))
        or is_proya_dual_special_version(f"{product.get('product_name')} {qualifier_text}")
    )


def is_proya_dual_product(value: Any) -> bool:
    norm = normalize_text(value)
    return any(token in norm for token in ["双抗", "抗氧", "抗糖"])


def product_is_proya_dual(product: dict[str, Any]) -> bool:
    return is_proya_dual_product(product.get("product_name")) or is_proya_dual_product(product.get("raw_product_name"))


def entry_is_proya_dual_special(entry: RspEntry) -> bool:
    return is_proya_dual_special_version(f"{entry.product_name} {entry.product_nickname}")


def rsp_column_for_campaign(
    campaign: Any,
    rsp_records: list[dict[str, Any]],
    preferred_column: str | None = None,
) -> str | None:
    sample_fields = rsp_records[0].get("fields", {}) if rsp_records else {}
    if preferred_column:
        if preferred_column in sample_fields:
            return preferred_column
        preferred_normalized = normalize_text(preferred_column)
        for key in sample_fields:
            if normalize_text(key) == preferred_normalized:
                return key

    campaign_text = str(campaign or "").strip()
    if not campaign_text:
        return None
    candidate = f"RSP ({campaign_text})"
    if candidate in sample_fields:
        return candidate
    normalized = normalize_text(campaign_text)
    for key in sample_fields:
        if key.startswith("RSP") and normalized in normalize_text(key):
            return key
    return None


def build_rsp_entries(rsp_records: list[dict[str, Any]], rsp_column: str) -> list[RspEntry]:
    entries: list[RspEntry] = []
    for record in rsp_records:
        fields = record.get("fields", {})
        brand_parts = [
            first_field(fields, ["英文品牌名", "English Brand", "Brand EN"]),
            first_field(fields, ["中文品牌名", "Chinese Brand", "Brand CN"]),
            first_field(fields, ["英文品牌名(中文品牌名)", "品牌", "品牌名", "Brand"]),
        ]
        brand = " ".join(str(part).strip() for part in brand_parts if str(part or "").strip())
        entries.append(
            RspEntry(
                brand=brand,
                category=str(
                    first_field(
                        fields,
                        [
                            "品类",
                            "产品品类",
                            "类别",
                            "Category",
                        ],
                    )
                    or ""
                ),
                product_name=str(
                    first_field(
                        fields,
                        [
                            "产品名(产品昵称)",
                            "产品名",
                            "商品名",
                            "Product Name",
                        ],
                    )
                    or ""
                ),
                product_nickname=str(
                    first_field(
                        fields,
                        [
                            "产品昵称",
                            "产品别名",
                            "昵称",
                            "Product Nickname",
                            "Nickname",
                        ],
                    )
                    or ""
                ),
                spec=str(first_field(fields, ["规格", "Spec", "规格/ml", "容量"]) or ""),
                rsp=parse_float(fields.get(rsp_column)),
                record=record,
            )
        )
    return entries


def entry_search_text(entry: RspEntry) -> str:
    return " ".join(part for part in [entry.product_nickname, entry.product_name] if part).strip()


def char_ngrams(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    grams = list(normalized)
    grams.extend(normalized[index : index + 2] for index in range(len(normalized) - 1))
    return grams


def tfidf_cosine_score(query: str, documents: list[str], index: int) -> float:
    if index < 0 or index >= len(documents):
        return 0.0
    query_terms = char_ngrams(query)
    doc_terms = char_ngrams(documents[index])
    if not query_terms or not doc_terms:
        return 0.0

    doc_counters = [Counter(char_ngrams(document)) for document in documents]
    query_counter = Counter(query_terms)
    df: Counter[str] = Counter()
    for counter in doc_counters:
        for term in counter:
            df[term] += 1

    total_docs = max(len(doc_counters), 1)

    def tfidf_vector(counter: Counter[str]) -> dict[str, float]:
        vector: dict[str, float] = {}
        for term, tf in counter.items():
            idf = math.log((1 + total_docs) / (1 + df.get(term, 0))) + 1.0
            vector[term] = tf * idf
        return vector

    query_vector = tfidf_vector(query_counter)
    doc_vector = tfidf_vector(doc_counters[index])
    dot = sum(query_vector.get(term, 0.0) * doc_vector.get(term, 0.0) for term in query_vector)
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    doc_norm = math.sqrt(sum(value * value for value in doc_vector.values()))
    if query_norm == 0 or doc_norm == 0:
        return 0.0
    return dot / (query_norm * doc_norm)


def top_tfidf_candidates(query: str, entries: list[RspEntry], top_n: int = 5) -> list[tuple[RspEntry, float]]:
    documents = [entry_search_text(entry) for entry in entries]
    scored = [
        (entry, tfidf_cosine_score(query, documents, index))
        for index, entry in enumerate(entries)
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_n]


def match_rsp(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
) -> tuple[RspEntry | None, float | None]:
    product_name = normalize_text(product.get("product_name"))
    product_spec = parse_spec_amount(product.get("spec"))

    scored: list[tuple[int, RspEntry]] = []
    for entry in entries:
        if entry.rsp is None:
            continue
        score = 0
        if same_brand(brand, entry.brand):
            score += 20
        for source, entry_name in entry_match_names(entry):
            normalized_name = normalize_text(entry_name)
            if product_name and (product_name in normalized_name or normalized_name in product_name):
                score += 70 if source == "nickname" else 50
                break
            if product_name and any(token and token in normalized_name for token in re.split(r"[^\w\u4e00-\u9fff]+", product_name)):
                score += 15 if source == "nickname" else 10
                break
        entry_spec = parse_spec_amount(entry.spec)
        if product_spec and entry_spec and product_spec == entry_spec:
            score += 30
        if score >= 50:
            scored.append((score, entry))

    if not scored:
        return None, None
    scored.sort(key=lambda item: item[0], reverse=True)
    best = scored[0][1]
    return best, best.rsp


def entry_match_names(entry: RspEntry) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    if entry.product_nickname:
        names.append(("nickname", entry.product_nickname))
    if entry.product_name and normalize_text(entry.product_name) != normalize_text(entry.product_nickname):
        names.append(("product_name", entry.product_name))
    return names


def entry_label(entry: RspEntry) -> str:
    nickname = f" / {entry.product_nickname}" if entry.product_nickname else ""
    return f"{entry.product_name}{nickname} {entry.spec}".strip()


def parse_pack_count(value: Any) -> float | None:
    text = str(value or "")
    if not text.strip():
        return None
    normalized = text.replace("×", "*").replace("x", "*").replace("X", "*")
    patterns = [
        r"\(\s*\d+(?:\.\d+)?\s*(?:ml|g)?\s*\*\s*(\d+(?:\.\d+)?)\s*\)",
        r"\[\s*\d+(?:\.\d+)?\s*(?:ml|g)?\s*\*\s*(\d+(?:\.\d+)?)\s*\]",
        r"(\d+(?:\.\d+)?)\s*(?:支|片|pcs|pc|个|件|套)(?!\s*\*)",
        r"\d+(?:\.\d+)?\s*(?:ml|g)\s*\*\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            return float(match.group(1))
    return infer_total_quantity_from_text(normalized)


def product_total_spec_amount(product: dict[str, Any]) -> tuple[float, str] | None:
    spec = parse_spec_amount(product.get("spec")) or parse_spec_amount(product.get("matched_spec"))
    if not spec:
        return None
    quantity = parse_float(product.get("quantity")) or 1
    return spec[0] * quantity, spec[1]


def entry_total_spec_amount(entry: RspEntry) -> tuple[float, str] | None:
    return parse_total_spec_amount(entry.spec) or parse_total_spec_amount(entry.product_name)


def product_pack_count(product: dict[str, Any]) -> float | None:
    quantity = parse_float(product.get("quantity"))
    if quantity and quantity > 1:
        return quantity
    return parse_pack_count(product.get("quantity_text")) or parse_pack_count(product.get("raw_product_name")) or parse_pack_count(product.get("product_name"))


def entry_pack_count(entry: RspEntry) -> float | None:
    return parse_pack_count(entry.product_name) or parse_pack_count(entry.product_nickname) or parse_pack_count(entry.spec)


def is_pack_level_rsp_match(product: dict[str, Any], entry: RspEntry) -> bool:
    product_count = product_pack_count(product)
    entry_count = entry_pack_count(entry)
    if product_count is not None and entry_count is not None and round(product_count, 6) == round(entry_count, 6):
        return True
    product_total_spec = product_total_spec_amount(product)
    entry_total_spec = entry_total_spec_amount(entry)
    return bool(product_total_spec and entry_total_spec and product_total_spec == entry_total_spec and (product_count or 0) > 1)


def same_product_name(product_name: str, entry_name: str) -> bool:
    product_norm = normalize_text(product_name)
    entry_norm = normalize_text(entry_name)
    if not product_norm or not entry_norm:
        return False
    if product_norm == entry_norm or product_norm in entry_norm:
        return True

    def first_matching_label(text: str, rules: list[tuple[str, list[str]]]) -> str | None:
        text_norm = normalize_text(text)
        for label, aliases in rules:
            if any(normalize_text(alias) in text_norm for alias in aliases):
                return label
        return None

    line_rules = [
        ("红宝石", ["红宝石", "ruby"]),
        ("双抗", ["双抗", "抗氧", "抗糖", "特证"]),
        ("能量", ["能量"]),
        ("源力", ["源力"]),
        ("水动力", ["水动力"]),
        ("紧致肌密", ["紧致肌密"]),
    ]
    category_rules = [
        ("面膜", ["面膜", "mask"]),
        ("面霜", ["面霜", "霜", "cream"]),
        ("精华", ["精华", "精华液", "serum", "essence"]),
        ("乳液", ["乳液", "活肤乳", "净透乳", "盈润乳", "乳"]),
        ("眼霜", ["眼霜", "eyecream", "eye"]),
        ("水", ["活肤水", "净透水", "精华水", "爽肤水", "柔肤水"]),
    ]

    product_line = first_matching_label(str(product_name), line_rules)
    product_category = first_matching_label(str(product_name), category_rules)
    entry_line = first_matching_label(str(entry_name), line_rules)
    entry_category = first_matching_label(str(entry_name), category_rules)
    return bool(product_line and product_category) and (
        product_line == entry_line and product_category == entry_category
    )


def qualifier_match_score_value(product: dict[str, Any], entry: RspEntry) -> float:
    qualifiers = product_match_qualifiers(product)
    if not qualifiers:
        return 0.0
    entry_norm = normalize_text(f"{entry.product_name} {entry.product_nickname} {entry.spec}")
    matched = 0
    for qualifier in qualifiers:
        qualifier_norm = normalize_text(qualifier)
        if not qualifier_norm:
            continue
        aliases = [qualifier]
        for label, rule_aliases in QUALIFIER_RULES:
            normalized_aliases = {normalize_text(label), *(normalize_text(alias) for alias in rule_aliases)}
            if qualifier_norm in normalized_aliases:
                aliases = [label, *rule_aliases]
                break
        if any(normalize_text(alias) and normalize_text(alias) in entry_norm for alias in aliases):
            matched += 1
    if matched == 0:
        return 0.0
    if matched == len(qualifiers):
        return 1.0
    return 0.5


def spec_match_score_value(product: dict[str, Any], entry: RspEntry) -> float:
    product_total_spec = product_total_spec_amount(product)
    entry_total_spec = entry_total_spec_amount(entry)
    if product_total_spec and entry_total_spec and product_total_spec == entry_total_spec:
        return 1.0
    product_count = product_pack_count(product)
    entry_count = entry_pack_count(entry)
    if product_count is not None and entry_count is not None and round(product_count, 6) == round(entry_count, 6):
        return 1.0
    return 0.0


def price_values(entries: list[RspEntry]) -> set[float]:
    return {round(float(entry.rsp), 6) for entry in entries if entry.rsp is not None}


def conflict_note(product: dict[str, Any], entries: list[RspEntry]) -> str:
    parts = [
        f"{entry_label(entry)}={entry.rsp:g}"
        for entry in entries
        if entry.rsp is not None
    ]
    return f"Multiple RSP matches with different prices for {product_label(product)}: " + "; ".join(parts)


def render_ppi_note(conversion_notes: list[str], unmatched_notes: list[str], other_notes: list[str] | None = None) -> str:
    sections: list[str] = []
    if conversion_notes:
        sections.append("折算说明：" + "；".join(conversion_notes))
    if unmatched_notes:
        sections.append("未匹配产品：" + "；".join(unmatched_notes))
    if other_notes:
        sections.append("其他：" + "；".join(other_notes))
    return "\n".join(sections)


def append_other_note(note: str, text: str) -> str:
    if not note:
        return "其他：" + text
    lines = note.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("其他："):
            lines[index] = line + "；" + text
            return "\n".join(lines)
    return note + "\n其他：" + text


def is_non_beauty_gwp(product: dict[str, Any]) -> bool:
    text = normalize_text(
        " ".join(
            str(value or "")
            for value in [
                product.get("product_name"),
                product.get("raw_product_name"),
                product.get("spec"),
                product.get("notes"),
            ]
        )
    )
    if not text:
        return False

    non_beauty_tokens = [
        "化妆包",
        "收纳包",
        "包包",
        "手提包",
        "帆布包",
        "托特包",
        "洗漱包",
        "化妆镜",
        "镜子",
        "梳子",
        "发箍",
        "发夹",
        "头绳",
        "毛巾",
        "浴巾",
        "洗脸巾",
        "杯子",
        "水杯",
        "保温杯",
        "钥匙扣",
        "挂件",
        "徽章",
        "贴纸",
        "冰箱贴",
        "玩偶",
        "公仔",
        "周边",
        "ip周边",
        "礼盒",
        "礼袋",
        "手账",
        "明信片",
        "承诺贺卡",
        "贺卡",
        "卡片",
    ]
    beauty_tokens = [
        "精华",
        "面霜",
        "面膜",
        "乳液",
        "爽肤水",
        "精华水",
        "眼霜",
        "洁面",
        "卸妆",
        "防晒",
        "粉底",
        "气垫",
        "口红",
        "唇釉",
        "腮红",
        "眼影",
        "散粉",
        "眉笔",
        "睫毛膏",
        "香水",
        "小样",
        "试用装",
    ]
    return any(token in text for token in non_beauty_tokens) and not any(
        token in text for token in beauty_tokens
    )


def lookup_rsp_by_name_and_spec(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
) -> tuple[float | None, RspLookupNote | None]:
    product_name = product.get("product_name") or ""
    product_spec = parse_spec_amount(product.get("spec")) or parse_spec_amount(product.get("matched_spec"))
    product_total_spec = product_total_spec_amount(product)
    product_count = product_pack_count(product)
    requires_special = product_requires_proya_dual_special(product)

    brand_candidates: list[RspEntry] = []
    nickname_entries: list[RspEntry] = []
    product_name_entries: list[RspEntry] = []
    for entry in entries:
        if entry.rsp is None:
            continue
        if not same_brand(brand, entry.brand):
            continue
        brand_candidates.append(entry)
        if requires_special and not entry_is_proya_dual_special(entry):
            continue
        if entry.product_nickname and same_product_name(product_name, entry.product_nickname):
            nickname_entries.append(entry)
        elif same_product_name(product_name, entry.product_name):
            product_name_entries.append(entry)

    if not brand_candidates:
        return None, RspLookupNote("unmatched", product_label(product))

    product_cat = product_category(product)
    category_candidates = [
        entry
        for entry in brand_candidates
        if product_cat and same_category(product, entry)
    ]
    detailed_candidate_pool = category_candidates or brand_candidates

    same_name_entries = nickname_entries or product_name_entries
    if same_name_entries and category_candidates:
        category_same_name_entries = [
            entry for entry in same_name_entries if same_category(product, entry)
        ]
        if category_same_name_entries:
            same_name_entries = category_same_name_entries

    if not same_name_entries:
        tfidf_ranked = top_tfidf_candidates(product_name, detailed_candidate_pool, top_n=5)
        scored_candidates: list[tuple[RspEntry, float, float]] = []
        for entry, tfidf_score in tfidf_ranked:
            final_score = tfidf_score * 0.6 + spec_match_score_value(product, entry) * 0.3 + qualifier_match_score_value(product, entry) * 0.1
            scored_candidates.append((entry, tfidf_score, final_score))
        if not scored_candidates:
            if requires_special:
                return None, RspLookupNote("unmatched", f"{product_label(product)}：需要匹配双抗3.0/特证版本，但RSP中未找到对应特证产品")
            return None, RspLookupNote("unmatched", product_label(product))

        best_entry, best_tfidf_score, best_score = max(scored_candidates, key=lambda item: item[2])
        if category_candidates and len(category_candidates) == 1 and best_score < 0.8:
            return category_candidates[0].rsp, RspLookupNote(
                "low_confidence",
                f"{product_label(product)} 低置信匹配：品牌+品类候选唯一，匹配到 {entry_label(category_candidates[0])} (score={best_score:.2f})",
            )
        if best_score < 0.5:
            if requires_special:
                return None, RspLookupNote("unmatched", f"{product_label(product)}：需要匹配双抗3.0/特证版本，但RSP中未找到对应特证产品")
            return None, RspLookupNote("unmatched", f"{product_label(product)}：TF-IDF候选不足，最高分 {best_score:.2f}")
        if best_score < 0.8:
            return best_entry.rsp, RspLookupNote(
                "conversion" if spec_match_score_value(product, best_entry) == 0 and (product_total_spec or product_spec) else "matched",
                f"{product_label(product)} 通过TF-IDF匹配到 {entry_label(best_entry)} (score={best_score:.2f}, tfidf={best_tfidf_score:.2f})",
            )
        return best_entry.rsp, None

    if product_is_proya_dual(product) and not requires_special:
        regular_entries = [entry for entry in same_name_entries if not entry_is_proya_dual_special(entry)]
        if regular_entries:
            same_name_entries = regular_entries

    same_name_entries = disambiguate_entries_with_qualifiers(product, same_name_entries)

    if product_spec:
        exact_total_spec_entries = [
            entry
            for entry in same_name_entries
            if product_total_spec and entry_total_spec_amount(entry) == product_total_spec
        ]
        if exact_total_spec_entries:
            exact_total_spec_entries = disambiguate_entries_with_qualifiers(product, exact_total_spec_entries)
            prices = price_values(exact_total_spec_entries)
            if len(prices) == 1:
                return exact_total_spec_entries[0].rsp, None
            return None, RspLookupNote("unmatched", f"{product_label(product)}：{conflict_note(product, exact_total_spec_entries)}")

        exact_spec_entries = [
            entry
            for entry in same_name_entries
            if entry_spec_amount(entry) == product_spec and not entry_pack_count(entry)
        ]
        if exact_spec_entries:
            exact_spec_entries = disambiguate_entries_with_qualifiers(product, exact_spec_entries)
            prices = price_values(exact_spec_entries)
            if len(prices) == 1:
                return exact_spec_entries[0].rsp, None
            return None, RspLookupNote("unmatched", f"{product_label(product)}：{conflict_note(product, exact_spec_entries)}")

        if product_count is not None:
            exact_count_entries = [
                entry
                for entry in same_name_entries
                if entry_pack_count(entry) is not None and round(entry_pack_count(entry), 6) == round(product_count, 6)
            ]
            if exact_count_entries:
                exact_count_entries = disambiguate_entries_with_qualifiers(product, exact_count_entries)
                prices = price_values(exact_count_entries)
                if len(prices) == 1:
                    return exact_count_entries[0].rsp, RspLookupNote(
                        "conversion",
                        f"{product_label(product)} 按支数匹配到 {entry_label(exact_count_entries[0])}",
                    )
                return None, RspLookupNote("unmatched", f"{product_label(product)}：{conflict_note(product, exact_count_entries)}")

        compatible_entries = [
            entry
            for entry in same_name_entries
            if (entry_spec_amount(entry) and entry_spec_amount(entry)[1] == product_spec[1])
        ]
        if compatible_entries:
            compatible_entries = disambiguate_entries_with_qualifiers(product, compatible_entries)
            unit_prices = {
                round(entry.rsp / entry_total_spec_amount(entry)[0], 6)
                for entry in compatible_entries
                if entry_total_spec_amount(entry) and entry_total_spec_amount(entry)[0] > 0
            }
            if len(unit_prices) == 1:
                reference = compatible_entries[0]
                reference_spec = entry_total_spec_amount(reference)
                unit_rsp = reference.rsp / reference_spec[0]
                return (
                    unit_rsp * product_spec[0],
                    RspLookupNote(
                        "conversion",
                        f"{product_label(product)} 按 {entry_label(reference)} 折算",
                    ),
                )
            return None, RspLookupNote("unmatched", f"{product_label(product)}：{conflict_note(product, compatible_entries)}")

    prices = price_values(same_name_entries)
    if len(prices) == 1:
        return same_name_entries[0].rsp, None
    return None, RspLookupNote("unmatched", f"{product_label(product)}：找到同名产品，但没有可用规格")


def product_rsp_total(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
) -> tuple[float | None, RspLookupNote | None]:
    quantity = parse_float(product.get("quantity")) or 1
    rsp, note = lookup_rsp_by_name_and_spec(product, brand, entries)
    if rsp is not None:
        if has_pack_level_rsp_candidate(product, brand, entries, rsp):
            quantity = 1
        return rsp * quantity, note
    return None, note or RspLookupNote("unmatched", product_label(product))


def matched_entries_for_rsp(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
    rsp: float | None,
) -> list[RspEntry]:
    if rsp is None:
        return []
    product_name = product.get("product_name") or ""
    requires_special = product_requires_proya_dual_special(product)
    candidates: list[RspEntry] = []
    for entry in entries:
        if entry.rsp is None or round(float(entry.rsp), 6) != round(float(rsp), 6):
            continue
        if not same_brand(brand, entry.brand):
            continue
        if requires_special and not entry_is_proya_dual_special(entry):
            continue
        if entry.product_nickname and same_product_name(product_name, entry.product_nickname):
            candidates.append(entry)
        elif same_product_name(product_name, entry.product_name):
            candidates.append(entry)

    if product_is_proya_dual(product) and not requires_special:
        regular_candidates = [entry for entry in candidates if not entry_is_proya_dual_special(entry)]
        if regular_candidates:
            candidates = regular_candidates
    return disambiguate_entries_with_qualifiers(product, candidates)


def matched_entry_for_rsp(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
    rsp: float | None,
) -> RspEntry | None:
    candidates = matched_entries_for_rsp(product, brand, entries, rsp)
    return candidates[0] if len(candidates) == 1 else None


def has_pack_level_rsp_candidate(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
    rsp: float | None,
) -> bool:
    return any(
        is_pack_level_rsp_match(product, entry)
        for entry in matched_entries_for_rsp(product, brand, entries, rsp)
    )


def format_spec_quantity(product: dict[str, Any]) -> str:
    spec = product.get("matched_spec") if product.get("matched_spec") and not parse_spec_amount(product.get("spec")) else product.get("spec")
    spec = str(spec or "").strip()
    quantity = parse_float(product.get("quantity")) or 1
    quantity_text = f"{quantity:g}"
    return f"{spec}*{quantity_text}" if spec else f"*{quantity_text}"


def format_number(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def product_amount(product: dict[str, Any]) -> tuple[float, str] | None:
    return parse_spec_amount(product.get("spec")) or parse_spec_amount(product.get("matched_spec"))


def same_hero_product_name(product: dict[str, Any], hero_product: dict[str, Any]) -> bool:
    product_name = normalize_text(product.get("product_name"))
    hero_name = normalize_text(hero_product.get("product_name"))
    if not product_name or not hero_name:
        return False
    return product_name == hero_name


def same_hero_product(product: dict[str, Any], hero_product: dict[str, Any], unit: str | None) -> bool:
    product_spec = product_amount(product)
    if unit and product_spec and product_spec[1] != unit:
        return False
    return same_hero_product_name(product, hero_product)


def hero_amount(
    main_products: list[dict[str, Any]],
    gift_products: list[dict[str, Any]],
) -> float | None:
    if not main_products:
        return None
    total = 0.0
    hero_specs: list[tuple[dict[str, Any], tuple[float, str]]] = []

    for product in main_products:
        spec = product_amount(product)
        if not spec:
            continue
        quantity = parse_float(product.get("quantity")) or 1
        total += spec[0] * quantity
        hero_specs.append((product, spec))

    for product in gift_products:
        spec = product_amount(product)
        if not spec:
            continue
        if not any(same_hero_product(product, hero_product, hero_spec[1]) for hero_product, hero_spec in hero_specs):
            continue
        quantity = parse_float(product.get("quantity")) or 1
        total += spec[0] * quantity

    return total or None


def product_name_summary(products: list[dict[str, Any]]) -> str:
    names = [str(product.get("product_name") or "").strip() for product in products]
    return "\n".join(name for name in names if name)


def size_summary(products: list[dict[str, Any]]) -> str:
    sizes = [format_spec_quantity(product) for product in products if product]
    return "\n".join(size for size in sizes if size)


def split_multiline_value(value: Any) -> list[str]:
    if value is None:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def parse_product_line(line: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"\[RSP（.*$", "", line).strip()
    pattern = re.compile(
        r"^(?P<name>.*?)(?P<spec>\d+(?:\.\d+)?\s*(?:ml|g|片|pcs|pc|支|只|条|颗|个|件|套))"
        r"(?:\s*[*x×]\s*(?P<quantity>\d+(?:\.\d+)?))?",
        re.I,
    )
    match = pattern.search(cleaned)
    if not match:
        return None
    name = match.group("name").strip(" ：:-")
    spec = re.sub(r"\s+", "", match.group("spec"))
    quantity = parse_float(match.group("quantity")) or 1
    if not name:
        return {"spec": spec, "quantity": quantity}
    return {"product_name": name, "spec": spec, "quantity": quantity}


def parse_user_size(value: Any) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for line in split_multiline_value(value):
        parsed = parse_product_line(line)
        if parsed:
            products.append(parsed)
            continue
        match = re.search(
            r"(?P<spec>\d+(?:\.\d+)?\s*(?:ml|g|片|pcs|pc|支|只|条|颗|个|件|套))"
            r"(?:\s*[*x×]\s*(?P<quantity>\d+(?:\.\d+)?))?",
            line,
            re.I,
        )
        if match:
            products.append(
                {
                    "spec": re.sub(r"\s+", "", match.group("spec")),
                    "quantity": parse_float(match.group("quantity")) or 1,
                }
            )
    return products


def parse_user_plv_details(value: Any) -> list[dict[str, Any]]:
    products = [parsed for line in split_multiline_value(value) if (parsed := parse_product_line(line))]
    for product in products:
        product.setdefault("raw_product_name", product.get("product_name"))
        product["product_name"] = normalize_product_nickname("", product.get("product_name"))
        product["category"] = product.get("category") or product_category(product)
        ensure_product_quantity(product)
        apply_special_product_cases(product)
        product["match_qualifiers"] = product_match_qualifiers(product)
    return [product for product in products if product.get("product_name")]


def apply_user_filled_products(extraction: dict[str, Any], fields: dict[str, Any]) -> None:
    main_products = extraction.get("main_products") or []
    user_products = [
        parse_product_line(line) or {"product_name": re.sub(r"\[RSP（.*$", "", line).strip()}
        for line in split_multiline_value(user_field_value(fields, FIELD_PRODUCT))
    ]
    user_sizes = parse_user_size(user_field_value(fields, FIELD_SIZE))

    for index, product in enumerate(main_products):
        if index < len(user_products):
            user_product = user_products[index]
            if user_product.get("product_name"):
                product["product_name"] = user_product["product_name"]
                product["raw_product_name"] = product.get("raw_product_name") or user_product["product_name"]
            if user_product.get("spec") and not product.get("spec"):
                product["spec"] = user_product["spec"]
            if user_product.get("quantity") is not None and not parse_float(product.get("quantity")):
                product["quantity"] = user_product["quantity"]
            product["product_name"] = normalize_product_nickname(extraction.get("brand"), product.get("product_name"))
            product["category"] = product.get("category") or product_category(product)
            apply_special_product_cases(product)
        if index < len(user_sizes):
            user_size = user_sizes[index]
            if user_size.get("product_name"):
                product["product_name"] = normalize_product_nickname(extraction.get("brand"), user_size.get("product_name"))
                product["raw_product_name"] = product.get("raw_product_name") or user_size.get("product_name")
                product["category"] = product.get("category") or product_category(product)
                apply_special_product_cases(product)
            if user_size.get("spec"):
                product["spec"] = user_size["spec"]
            if user_size.get("quantity") is not None:
                product["quantity"] = user_size["quantity"]

    user_gifts = parse_user_plv_details(user_field_value(fields, FIELD_PLV_DETAILS))
    if user_gifts:
        extraction["gift_products"] = user_gifts


def lookup_line_item(
    product: dict[str, Any],
    brand: str,
    entries: list[RspEntry],
) -> dict[str, Any]:
    quantity = parse_float(product.get("quantity")) or 1
    rsp, note = lookup_rsp_by_name_and_spec(product, brand, entries)
    matched_entry = matched_entry_for_rsp(product, brand, entries, rsp)
    if matched_entry and not parse_spec_amount(product.get("spec")):
        product["matched_spec"] = product.get("matched_spec") or matched_entry.spec
    pricing_quantity = 1 if has_pack_level_rsp_candidate(product, brand, entries, rsp) else quantity
    status = "未查询到数据"
    if rsp is not None:
        if note and note.kind == "conversion":
            status = "折算"
        elif note and note.kind == "low_confidence":
            status = "低置信匹配"
        else:
            status = "匹配"
    total = rsp * pricing_quantity if rsp is not None else None
    return {
        "product": product,
        "quantity": pricing_quantity,
        "raw_quantity": quantity,
        "unit_rsp": rsp,
        "total": total,
        "status": status,
        "note": note,
    }


def format_plv_details(items: list[dict[str, Any]]) -> str:
    return format_line_item_details(items)


def format_line_item_details(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        product = item["product"]
        name = str(product.get("product_name") or "").strip()
        spec_quantity = format_spec_quantity(product)
        quantity = item["quantity"]
        unit_rsp = item["unit_rsp"]
        if unit_rsp is None:
            rsp_text = "未查询到数据"
        else:
            rsp_text = f"{format_number(unit_rsp):g}*{quantity:g}"
        lines.append(f"{name} {spec_quantity} [RSP（{item['status']}）: {rsp_text}]".strip())
    return "\n".join(lines)


def calculate_rsp(
    extraction: dict[str, Any],
    campaign: Any,
    rsp_records: list[dict[str, Any]],
    fallback_brand: str = "",
    rsp_column_name: str | None = None,
) -> dict[str, Any]:
    rsp_column = rsp_column_for_campaign(campaign, rsp_records, rsp_column_name)
    if not rsp_column:
        return {
            "can_calculate": False,
            "note": f"RSP column not found: {rsp_column_name or campaign}",
        }

    entries = build_rsp_entries(rsp_records, rsp_column)
    brand_candidates = [
        brand
        for brand in [extraction.get("brand"), fallback_brand]
        if str(brand or "").strip()
    ]
    brand = brand_candidates or ""
    main_products = extraction.get("main_products") or []
    all_gift_products = extraction.get("gift_products") or []
    gift_products = [product for product in all_gift_products if not is_non_beauty_gwp(product)]
    ignored_gwps = [product for product in all_gift_products if is_non_beauty_gwp(product)]

    main_items = [lookup_line_item(product, brand, entries) for product in main_products]
    gift_items = [lookup_line_item(product, brand, entries) for product in gift_products]
    main_totals = [item["total"] for item in main_items if item["total"] is not None]
    gift_totals = [item["total"] for item in gift_items if item["total"] is not None]
    conversion_notes: list[str] = []
    low_confidence_notes: list[str] = []
    unmatched_notes: list[str] = []
    other_notes: list[str] = []

    for item in main_items + gift_items:
        note = item["note"]
        if item["total"] is None:
            unmatched_notes.append(note.text if note else product_label(item["product"]))
        elif note and note.kind == "conversion":
            conversion_notes.append(note.text)
        elif note and note.kind == "low_confidence":
            low_confidence_notes.append(note.text)
    if ignored_gwps:
        other_notes.append("未计入PPI的GWP周边：" + "；".join(product_label(product) for product in ignored_gwps))

    total_rsp = sum(main_totals) + sum(gift_totals)
    final_price = parse_float(extraction.get("final_price"))
    hero_total = hero_amount(main_products, gift_products)
    if main_products and hero_total is None:
        other_notes.append("橱窗图未识别到主品毫升数/克数/片数，无法计算hero ml/pcs及hero price per ml/pcs")
    note_text = render_ppi_note(conversion_notes, unmatched_notes, [*other_notes, *low_confidence_notes])
    base_result = {
        "product": format_line_item_details(main_items),
        "size": size_summary(main_products),
        "plv_details": format_plv_details(gift_items),
        "hero_amount": hero_total,
        "main_rsp": sum(main_totals) if main_totals else None,
        "gift_rsp": sum(gift_totals) if gift_totals else None,
        "total_rsp": total_rsp if total_rsp else None,
        "final_price": final_price,
        "note": note_text,
    }
    if unmatched_notes:
        return {
            **base_result,
            "can_calculate": False,
            "needs_review": True,
            "ppi": None,
        }
    if not final_price:
        return {**base_result, "can_calculate": False, "note": render_ppi_note(conversion_notes, [], [*other_notes, *low_confidence_notes, "到手价未识别"])}
    if not total_rsp:
        return {**base_result, "can_calculate": False, "note": render_ppi_note(conversion_notes, [], [*other_notes, *low_confidence_notes, "总RSP为空"])}

    return {
        **base_result,
        "can_calculate": True,
        "needs_review": bool(conversion_notes or low_confidence_notes),
        "ppi": final_price / total_rsp * 100,
        "note": note_text,
    }


def link_from_record(record: dict[str, Any], link_field: str) -> str | None:
    value = record.get("fields", {}).get(link_field)
    if isinstance(value, dict):
        return value.get("link") or value.get("text")
    if isinstance(value, str):
        return value
    return None


def process_record(
    record: dict[str, Any],
    rsp_records: list[dict[str, Any]],
    link_field: str,
    rsp_column_name: str,
    field_types: dict[str, int],
    field_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    fields = record.get("fields", {})
    link = link_from_record(record, link_field)
    if not link:
        return {FIELD_STATUS: "Skipped: empty Link", FIELD_NOTE: "No Link"}

    extraction, raw, method = extract_product_info(link)
    apply_user_filled_products(extraction, fields)
    failure_reason = recognition_failure_reason(extraction)
    if failure_reason:
        output = {
            FIELD_PRODUCT: product_name_summary(extraction.get("main_products") or []),
            FIELD_NOTE: failure_reason,
            FIELD_STATUS: "Needs review",
        }
        mapped_output = map_output_fields(output, field_map or {})
        return coerce_output_for_field_types(mapped_output, field_types)

    user_actual_price = parse_float(user_field_value(fields, FIELD_ACTUAL_PRICE))
    if user_actual_price is not None:
        extraction["final_price"] = user_actual_price

    rsp_result = calculate_rsp(
        extraction,
        fields.get("Campaign"),
        rsp_records,
        fallback_brand=str(fields.get("Brand") or ""),
        rsp_column_name=rsp_column_name,
    )

    actual_price = rsp_result.get("final_price")
    fg_rsp = rsp_result.get("main_rsp")
    plv_rsp = rsp_result.get("gift_rsp")
    total_rsp = rsp_result.get("total_rsp")
    hero_total = rsp_result.get("hero_amount")
    user_hero_total = parse_float(user_field_value(fields, FIELD_HERO_AMOUNT))
    if user_hero_total is not None:
        hero_total = user_hero_total
    category_coupon = parse_float(user_field_value(fields, FIELD_CATEGORY_COUPON)) or 0
    vip_coupon = parse_float(user_field_value(fields, FIELD_VIP_COUPON)) or 0
    price_2 = actual_price - category_coupon if actual_price is not None else None
    vip_price = actual_price - vip_coupon if actual_price is not None else None
    ppi = safe_ratio(actual_price, total_rsp)
    can_calculate = ppi is not None and not rsp_result.get("needs_review")
    note = rsp_result.get("note") or ""
    if user_actual_price is not None:
        note = append_other_note(note, "使用飞书已填Actual Price")
    if user_hero_total is not None:
        note = append_other_note(note, "使用飞书已填hero ml/pcs")

    output: dict[str, Any] = {
        FIELD_PRODUCT: rsp_result.get("product"),
        FIELD_SIZE: rsp_result.get("size"),
        FIELD_FG_RSP: format_number(fg_rsp),
        FIELD_PLV_DETAILS: rsp_result.get("plv_details"),
        FIELD_PLV_RSP: format_number(plv_rsp),
        FIELD_FG_PLUS_PLV: format_number(total_rsp),
        FIELD_HERO_AMOUNT: format_number(hero_total),
        FIELD_ACTUAL_PRICE: format_number(actual_price),
        FIELD_PA: format_number(safe_ratio(actual_price, fg_rsp) * 100 if safe_ratio(actual_price, fg_rsp) is not None else None),
        FIELD_PPI: format_number(ppi * 100 if ppi is not None else None),
        FIELD_HERO_PRICE: format_number(safe_ratio(actual_price, hero_total)),
        FIELD_CATEGORY_COUPON: format_number(category_coupon),
        FIELD_PRICE_2: format_number(price_2),
        FIELD_PA_2: format_number(safe_ratio(price_2, fg_rsp) * 100 if safe_ratio(price_2, fg_rsp) is not None else None),
        FIELD_PPI_2: format_number(safe_ratio(price_2, total_rsp) * 100 if safe_ratio(price_2, total_rsp) is not None else None),
        FIELD_HERO_PRICE_2: format_number(safe_ratio(price_2, hero_total)),
        FIELD_VIP_COUPON: format_number(vip_coupon),
        FIELD_VIP_PRICE: format_number(vip_price),
        FIELD_VIP_PPI: format_number(safe_ratio(vip_price, total_rsp) * 100 if safe_ratio(vip_price, total_rsp) is not None else None),
        FIELD_HERO_PRICE_VIP: format_number(safe_ratio(vip_price, hero_total)),
        FIELD_NOTE: note,
        FIELD_STATUS: (
            "Needs review"
            if rsp_result.get("needs_review")
            else ("Done" if can_calculate else "Needs review")
        ),
    }
    mapped_output = map_output_fields(output, field_map or {})
    return coerce_output_for_field_types(mapped_output, field_types)


def coerce_output_for_field_types(output: dict[str, Any], field_types: dict[str, int]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in output.items():
        if value is None:
            if field_types.get(key) == 2:
                continue
            coerced[key] = ""
            continue
        if field_types.get(key) == 2:
            coerced[key] = value
        else:
            coerced[key] = str(value)
    return coerced


def canonical_field_key(value: Any) -> str:
    return field_lookup_key(value)


def output_field_candidates(field_name: str) -> list[str]:
    return [field_name, *FIELD_ALIASES.get(field_name, [])]


def resolve_output_fields(client: FeishuClient, app_token: str, table_id: str) -> tuple[dict[str, str], dict[str, int]]:
    fields = client.list_fields(app_token, table_id)
    by_key = {
        canonical_field_key(field.get("field_name")): field
        for field in fields
        if field.get("field_name")
    }
    field_map: dict[str, str] = {}
    for field_name in OUTPUT_FIELDS:
        matched = None
        for candidate in output_field_candidates(field_name):
            matched = by_key.get(canonical_field_key(candidate))
            if matched:
                break
        if matched:
            field_map[field_name] = matched["field_name"]
            continue
        if field_name == FIELD_NOTE:
            created = client.create_text_field(app_token, table_id, FIELD_NOTE)
            fields.append(created)
            by_key[canonical_field_key(created.get("field_name"))] = created
            field_map[field_name] = created["field_name"]
            continue

    field_types = {
        field.get("field_name"): field.get("type")
        for field in fields
        if field.get("field_name")
    }
    return field_map, field_types


def map_output_fields(output: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    return {field_map[key]: value for key, value in output.items() if key in field_map}


def process_records(record_ids: list[str] | None = None, ppi_table_id: str | None = None) -> dict[str, Any]:
    settings = load_feishu_settings()
    client = FeishuClient(settings.feishu_app_id, settings.feishu_app_secret)
    tables = client.list_tables(settings.feishu_app_token)
    table_by_name = {table["name"]: table["table_id"] for table in tables}
    ppi_table_id = ppi_table_id or table_by_name[settings.ppi_table_name]
    rsp_table_id = table_by_name[settings.rsp_table_name]

    field_map, field_types = resolve_output_fields(client, settings.feishu_app_token, ppi_table_id)
    ppi_records = client.list_records(settings.feishu_app_token, ppi_table_id)
    rsp_records = client.list_records(settings.feishu_app_token, rsp_table_id)

    selected = [
        record
        for record in ppi_records
        if (not record_ids or record["record_id"] in record_ids)
        and link_from_record(record, settings.ppi_link_field)
    ]

    updates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for record in selected:
        try:
            fields = process_record(
                record,
                rsp_records,
                settings.ppi_link_field,
                settings.rsp_column_name,
                field_types,
                field_map,
            )
            if fields:
                updates.append({"record_id": record["record_id"], "fields": fields})
        except Exception as exc:
            errors.append({"record_id": record["record_id"], "error": str(exc)})
            error_fields = map_output_fields({FIELD_STATUS: "Error", FIELD_NOTE: str(exc)}, field_map)
            error_fields = coerce_output_for_field_types(error_fields, field_types)
            if error_fields:
                updates.append({"record_id": record["record_id"], "fields": error_fields})

    if updates:
        client.batch_update_records(settings.feishu_app_token, ppi_table_id, updates)

    missing_output_fields = [field for field in OUTPUT_FIELDS if field not in field_map]
    return {
        "processed": len(selected),
        "updated": len(updates),
        "errors": errors,
        "missing_output_fields": missing_output_fields,
    }
