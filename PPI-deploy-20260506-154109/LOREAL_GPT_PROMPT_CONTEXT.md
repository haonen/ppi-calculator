# Loreal GPT 橱窗图识别 Prompt 与规则整理 v2

本文档整理当前 PPI Calculator 后端用于橱窗图识别的 Loreal GPT 提示词，以及识别结果进入 RSP 匹配和 PPI 计算前的代码侧规则。

源码位置：
- `ppi_processor.py` 中的 `PROMPT`
- `ppi_processor.py` 中的 `ensure_vision_config`
- `ppi_processor.py` 中的识别结果标准化、昵称归一、数量补全、特殊 case、GWP 过滤和 RSP 匹配规则

---

## 1. 当前实际发送给 Loreal GPT 的用户提示词

```text
You are an expert ecommerce promotion analyst for beauty products in China.
Read the attached ecommerce window image and extract product and promotion information.

Return only valid JSON. Do not wrap it in markdown. Use null when a value is not visible.
Do not infer RSP or original price. Extract only what is visible in the image.
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

---

### STEP 0 — Multi-tier Promotion Selection

When the image shows multiple purchase tiers (e.g., "买30支" vs "买60支", or "拍1件" vs "拍2件"),
always select the tier with the HIGHEST quantity / spend, as that tier typically has the deepest PPI.
Extract main_products, gift_products, and final_price from the selected tier only.
Record the selected tier description in the "notes" field, e.g. "selected tier: 买60支到手110支 ¥789".

---

### STEP 1 — Spatial Layout Analysis (Main vs Gift)

Before extracting any product, first analyze the full image layout:

1. Identify the HERO ZONE: the large central or left product image(s). These are almost always main_products.
2. Identify the GIFT ZONE: smaller products usually placed to the right of, below, or around the hero. These are gift_products.
3. Read ALL text blocks in the image. Map each text segment to its nearest visual product group.
   - Text near the hero zone → describes main_products.
   - Text near the gift zone → describes gift_products.
4. Look for explicit gift keywords: 送, 赠, 礼, 到手, 享, 加赠, 限时加赠, 会员礼, GWP, 正装礼.
   Any product mentioned after these keywords is a gift_product.
   IMPORTANT — "正装" marketing talk trap: phrases like "拍1享7件正装", "享X件正装", "到手X件正装"
   are merchant marketing language designed to make gifts sound more valuable.
   The word "正装" here does NOT mean the product is a main_product.
   Rule: any product listed after 送/赠/享/礼/加赠/限时加赠 is always a gift_product,
   even if the merchant calls it "正装". Only the core product the shopper actually pays for is main_product.
   Record the marketing phrase in mechanism_text with a note: "（商家话术，实为赠品）".
5. "买X到手Y" pattern: the quantity X is the main product; the extra volume (Y minus X) is gift_product.
   Example: "买45g至高到手90g" → main is 45g, gift is 45g (same product, smaller jar).
6. "买正装送正装" pattern: the paid full-size is main_product; the "送" full-size is gift_product.
7. When both "限时加赠" and "520加赠" (or similar named gift groups) appear,
   combine all named gift groups into gift_products. Do NOT add them to main_products.
8. Member gifts (会员礼, ¥0.01确权礼, 会员确权礼) are gift_products with limited_edition = "会员礼".
   Include them in gift_products only if they are beauty products; exclude non-beauty member gifts.
9. If a product appears in both a purchase photo and a gift listing, trust the gift listing label.

---

### STEP 2 — Product Information Extraction

For each product identified in STEP 1, extract:

For each product, extract matching qualifiers when visible. These are used only for RSP matching
and should be separate from the short product_name:
- version: such as "1.0", "2.0", "3.0", "第三代"
- variant: such as "干皮版", "油皮版", "滋润版", "轻盈版", "清爽版", "经典型", "轻润型"
- shade: shade number or color name, such as "01", "象牙白", "粉色", "#01黄油可颂"
- certificate: such as "特证", "美白特证"
- limited_edition: special edition, limited edition, collaboration edition, anniversary edition, or special color packaging.
  Example: "510周年庆限定", "520限定", "联名款"

Important classification rules:
- main_products: only the paid/core full-size product the shopper is buying.
- gift_products: all free gifts, mini sizes, extra bottles/tubes, masks, samples, member gifts, and extra volume included in "到手/享".
- Example: "买50ml到手110ml" means 50ml is main product, the additional 60ml should be gift products.

---

### STEP 3 — Price Extraction

Extract final_price as the actual checkout price visible in the image.

Price priority rules:
1. Use the price labeled 到手价, 实付价, 券后价, 到手 ¥ — this is the true final_price.
2. If only a "划线价" (strikethrough) is visible with no final price, set final_price = null.
3. If multiple prices appear (e.g. per-tier prices), use the price matching the selected tier from STEP 0.
4. For makeup/cosmetics (彩妆) images: it is common for no final_price to be shown.
   If no checkout price is visible, set final_price = null and add "彩妆图无到手价，需人工填写" to notes.
5. Member vouchers (会员券 ¥45, 满减券) are NOT deducted from final_price.
   Record them separately in mechanism_text only.
6. If the image only shows a voucher or discount offer with no base price, set final_price = null.

---

### STEP 4 — Spec and Quantity for Cosmetics (彩妆)

For makeup products (eyeshadow palettes, lipsticks, blush, powder, foundation):
- spec: use piece count or weight when visible, e.g. "6.5g", "8g", "1片". If not visible, set null.
- quantity: typically 1 unless the image shows multiple units being sold together.
- hero_unit: for makeup, the unit is usually "pcs" not "ml". Add "彩妆，hero单位为pcs" to notes.
- If neither ml nor pcs is determinable from the image, set spec = null and note "规格不可见，需人工填写".

---

### STEP 5 — Non-Beauty GWP Filter

Do NOT include the following non-beauty gift types in gift_products:
化妆包, 收纳包, 包包, 手提包, 帆布包, 托特包, 洗漱包,
化妆镜, 镜子, 梳子, 发箍, 发夹, 头绳,
毛巾, 浴巾, 洗脸巾,
杯子, 水杯, 保温杯,
钥匙扣, 挂件, 徽章, 贴纸, 冰箱贴,
玩偶, 公仔, 周边, ip周边,
礼盒, 礼袋, 手账, 明信片,
承诺贺卡, 贺卡, 卡片

Exception: if the item name also contains a beauty keyword (精华, 面霜, 面膜, 乳液, 爽肤水, 精华水,
眼霜, 洁面, 卸妆, 防晒, 粉底, 气垫, 口红, 唇釉, 腮红, 眼影, 散粉, 眉笔, 睫毛膏, 香水, 小样, 试用装),
include it as a gift_product.

When a non-beauty gift is excluded, add it to mechanism_text as: "非美妆GWP（不计入PPI）: [产品名] x[数量]".

---

### Nickname Rules for product_name

- First use the visible product/gift name from the image exactly when present.
- Only infer a short Chinese nickname when the image does not show a clear product/gift name.
- If the image shows a long formal product name but no clear short nickname, infer nickname as "product line + category".
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

---

### PROYA/珀莱雅 Visual Common-Sense Rules

- If text is unclear but the package is clearly red, treat it as 红宝石系列.
- If text is unclear but the package is clearly yellow, treat it as 双抗系列.
- If text is unclear but the package is clearly misty blue / grey-blue, treat it as 源力系列.
- If text is unclear but the package is clearly brown/dark gold, treat it as 能量系列.
- Combine the inferred line with the visible or likely category, for example 精华, 面霜, 面膜, 水, 乳液, 眼霜.
- Mention color-based inference briefly in notes when you use it.

---

### Schema

{
  "brand": null,
  "final_price": null,
  "currency": "CNY",
  "selected_tier": null,
  "main_products": [
    {
      "product_name": "中文产品名或中文昵称",
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
```

---

## 2. Loreal GPT 配置里的 system prompt

代码会尝试创建或复用一个 vision config，里面的 system prompt 是：

```text
You extract product information from ecommerce images. Return valid JSON only.
```

当前模型和配置 ID：

```text
VISION_MODEL_ID = chat-gemini-2.5-flash
VISION_CONFIG_ID = ppi-v-gemini-flash
INGESTION_CONFIG_ID = demo-ingestion
```

---

## 3. 识别结果标准化规则（代码侧）

这些规则不是直接发给 Loreal GPT 的 prompt，但会在模型返回 JSON 后立刻处理，因此也会影响最终写入表格、匹配 RSP 和计算 PPI。

### 3.1 品牌别名

用于判断品牌是否相同，以及从产品名开头剥离品牌：

```text
proya: proya, 珀莱雅
olay: olay, 玉兰油
kans: kans, 韩束
lorealparis: lorealparis, l'oréalparis, 欧莱雅
skinceuticals: skinceuticals, 修丽可
```

### 3.2 匹配限定信息 qualifiers

识别结果中的这些字段会被汇总为 `match_qualifiers`，用于同名多条 RSP 记录时做进一步筛选：

```text
version
variant
shade
color
certificate
limited_edition
edition
```

当前 qualifier 规则：

```text
1.0: 1.0, 一代, 第1代, 第一代
2.0: 2.0, 二代, 第2代, 第二代
3.0: 3.0, 三代, 第3代, 第三代
干皮版: 干皮版, 干皮, 滋润版, 滋润型, 滋润, 经典型
油皮版: 油皮版, 油皮, 清爽版, 清爽型, 轻盈版, 轻盈型, 轻盈, 轻润型
特证: 特证, 美白特证
限定: 限定, 限定版, 特别版, 联名, 联名款, 礼盒限定, 特殊限定, 周年庆限定, 会员礼
```

### 3.3 珀莱雅产品昵称归一

如果品牌是 PROYA/珀莱雅，或者产品名里出现红宝石、双抗、能量、源力，会尝试把产品名归一为：

```text
产品线 + 品类
```

产品线规则：

```text
红宝石: 红宝石, ruby, 胜肽, 紧致
双抗: 双抗, 抗氧, 抗糖
能量: 能量
源力: 源力
```

品类规则：

```text
面膜: 面膜, mask
面霜: 面霜, cream, 霜
精华: 精华, essence, serum, 次抛, 安瓶
乳液: 乳液, 乳
水: 爽肤水, 精华水, 柔肤水, 水
眼霜: 眼霜, eyecream, eye
```

例子：

```text
珀莱雅红宝石胜肽精华 -> 红宝石精华
PROYA 双抗 serum -> 双抗精华
源力面霜 -> 源力面霜
```

### 3.4 珀莱雅双抗 3.0 / 特证规则

如果产品是双抗系列，且产品名、原始产品名或 qualifier 中出现这些信息：

```text
特证
3.0
第三代
美白特证
```

则 RSP 匹配时会认为它需要匹配"双抗 3.0 / 特证版本"。如果没有对应特证 RSP，会在备注中写：

```text
需要匹配双抗3.0/特证版本，但RSP中未找到对应特证产品
```

如果产品是双抗但没有 3.0/特证信息，则会尽量避开特证版本，优先匹配普通双抗版本。

### 3.5 数量补全规则

如果 Loreal GPT 没有给出 `quantity`，代码会从 `quantity_text`、`spec`、`raw_product_name`、`product_name` 中补推数量。

支持的模式包括：

```text
1.5ml*10支 -> quantity = 10
5*2 -> quantity = 10
5支*2盒 -> quantity = 10
10片 -> quantity = 10
```

支持的数量单位包括：

```text
支, 只, 条, 颗, 片, pcs, pc, 个, 件, 套, 盒, 瓶, 袋, 包
```

### 3.6 红宝石次抛精华特殊规则

如果产品名或原始产品名同时包含：

```text
红宝石
次抛 或 安瓶
```

则代码会把它作为红宝石精华的同品来匹配：

```text
product_name = 红宝石精华
matched_spec = 1.5ml
```

然后继续根据识别出的数量计算总 ml。比如：

```text
红宝石次抛精华 5*2 -> 1.5ml * 10 = 15ml
```

### 3.7 主品与赠品自动修正

如果 Loreal GPT 把同名、同单位的多个规格都放进了 `main_products`，代码会保留最大规格为主品，较小规格移动到赠品。

这个规则用于处理类似：

```text
买 50ml 到手 110ml
```

模型可能返回两个主品：50ml 和 60ml。代码会把较小/额外规格修正为赠品。

### 3.8 多档促销选档规则（新增）

当前主要由 prompt 要求 Loreal GPT 直接选择最高数量/最高消费档，并把该档写入 `selected_tier`、`main_products`、`gift_products`、`final_price`。

注意：代码侧不会仅凭 `mechanism_text` 重新猜测每档赠品和价格，因为橱窗图多档结构差异很大，二次猜档容易把赠品或价格配错。后续如果要做代码侧补选，建议让模型返回结构化 `promotion_tiers` 后再接入。

### 3.9 彩妆无价格/规格处理（新增）

如果 `final_price = null` 且 notes 中含有"彩妆图无到手价"：
- PPI、PA、hero price per ml/pcs 均留空
- 如果飞书表格中已填写 `Actual Price`，后端会优先使用该价格继续计算
- 如果飞书表格中已填写 `Size` 或 `hero ml/pcs`，后端会优先使用这些规格/hero 信息继续计算
- 如果仍缺价格或规格，PPI 备注会说明缺失原因，PPI Status 保持 `Needs review`

### 3.10 用户手填内容优先

如果用户已经在飞书表格中填写：

```text
Product
Size
PLV Details (含赠品中FG)
Actual Price
hero ml/pcs
```

后端会用用户填写的内容覆盖或补充图片识别结果，再进行 RSP 查询和 PPI 计算。这样彩妆橱窗图如果没有到手价或规格，只要人工预先补在表格里，仍然可以进入后续计算。

---

## 4. 非美妆 GWP 过滤规则

如果赠品是化妆包、镜子、周边等非护肤/彩妆产品，不参与 PPI 计算。没匹配上也不会阻塞 PPI。

当前非美妆关键词（已新增承诺贺卡类）：

```text
化妆包, 收纳包, 包包, 手提包, 帆布包, 托特包, 洗漱包,
化妆镜, 镜子, 梳子, 发箍, 发夹, 头绳,
毛巾, 浴巾, 洗脸巾,
杯子, 水杯, 保温杯,
钥匙扣, 挂件, 徽章, 贴纸, 冰箱贴,
玩偶, 公仔, 周边, ip周边,
礼盒, 礼袋, 手账, 明信片,
承诺贺卡, 贺卡, 卡片
```

但如果同时包含美妆关键词，则不会被过滤：

```text
精华, 面霜, 面膜, 乳液, 爽肤水, 精华水, 眼霜,
洁面, 卸妆, 防晒, 粉底, 气垫, 口红, 唇釉,
腮红, 眼影, 散粉, 眉笔, 睫毛膏, 香水,
小样, 试用装
```

---

## 5. RSP 匹配相关规则

### 5.1 产品昵称优先

RSP reference 里如果有产品昵称列，会优先用 `product_name` 去匹配 RSP 的产品昵称；匹配不到再用 RSP 的正式产品名。

### 5.2 同名多条记录时用 qualifiers 消歧

如果昵称或产品名匹配出多条 RSP，代码会用这些信息进一步筛选：

```text
版本: 1.0, 2.0, 3.0
肤质/质地: 干皮版, 油皮版, 滋润版, 轻盈版, 经典型
色号/颜色
证书: 特证, 美白特证
限定: 限定, 联名, 特殊限定, 会员礼
```

### 5.3 规格匹配与折算

如果找到同名产品：

- 优先匹配完全相同规格
- 如果没有完全相同规格，但同单位产品 RSP 的单位价格一致，则按单位价格折算
- 如果同名多条 RSP 价格不一致且无法判断，会标记为未匹配

### 5.4 PPI 备注格式

备注分三段：

```text
折算说明：...
未匹配产品：...
其他：...
```

例如：

```text
折算说明：红宝石精华 15ml x1 按 红宝石精华 30ml 折算
未匹配产品：双抗精华 30ml x1：需要匹配双抗3.0/特证版本，但RSP中未找到对应特证产品
其他：非美妆GWP（不计入PPI）：化妆包 x1；承诺贺卡 x1
```

---

## 6. Hero ml/pcs 计算规则

`hero ml/pcs` 会计算：

- 所有主品的毫升数/片数/克数
- 赠品中与主品"产品名完全一致"且单位一致的产品

注意：赠品必须和主品是一模一样的产品名才计入 hero。

例子：

```text
主品: 双抗精华 30ml
赠品: 双抗精华 10ml
=> hero = 40ml
```

但：

```text
主品: 双抗精华 30ml
赠品: 双抗水 30ml
=> hero = 30ml
```

红宝石次抛精华特殊 case 会先归一为红宝石精华，因此可以计入红宝石精华的 hero：

```text
主品: 红宝石精华 30ml
赠品: 红宝石次抛精华 5*2
=> 次抛按 1.5ml * 10 = 15ml
=> hero = 45ml
```

彩妆产品（无 ml 单位）hero 单位为 pcs，计算同一产品的总件数。

---

## 7. 输出字段相关说明

这些字段来自识别和计算结果：

```text
Product
Size
FG RSP
PLV Details (含赠品中FG)
PLV RSP
FG+ PLV
hero ml/pcs
Actual Price
PA
PPI
hero price per ml/pcs（全店）
Category Coupon
Price 2
PA 2
PPI 2
hero price per ml/pcs（QSI）
VIP Coupon
VIP Price
VIP PPI
hero price per ml/pcs（VIP）
PPI备注
PPI Status
```

当前后端会尝试匹配一些字段别名，例如：

```text
PLV Details (含赠品中FG） -> PLV Details (含赠品中FG)
hero ml|pcs -> hero ml/pcs
hero price per ml|pcs（全店） -> hero price per ml/pcs（全店）
hero price per ml|pcs（QSI） -> hero price per ml/pcs（QSI）
hero price per ml|pcs（VIP） -> hero price per ml/pcs（VIP）
```

---

## 8. 典型橱窗图识别示例（Few-shot 参考）

以下 case 供调试和 prompt 优化时参考。

### Case A：PROYA 红宝石次抛（多档促销）

图像特征：显示"买30支到手45支 ¥389"和"买60支到手110支 ¥789"两档。

正确输出：
```json
{
  "brand": "PROYA",
  "final_price": 789,
  "selected_tier": "买60支到手110支",
  "main_products": [
    { "product_name": "红宝石精华", "spec": "1.5ml", "quantity": 60, "quantity_text": "60支" }
  ],
  "gift_products": [
    { "product_name": "红宝石精华", "spec": "1.5ml", "quantity": 50, "quantity_text": "50支" }
  ],
  "notes": "selected tier: 买60支到手110支 ¥789。赠品包含7件礼（details in mechanism_text）。会员礼超膜银管15ml已过滤（非次抛同品）。"
}
```

### Case B：PROYA 双抗精华（买正装送正装）

图像特征："买正装送正装"，主品双抗精华50ml特证版，赠品替换芯+双抗面膜2片，会员礼超膜银管15ml，¥329。

正确输出：
```json
{
  "brand": "PROYA",
  "final_price": 329,
  "selected_tier": "买正装送正装",
  "main_products": [
    { "product_name": "双抗精华", "spec": "50ml", "quantity": 1, "certificate": "特证" }
  ],
  "gift_products": [
    { "product_name": "双抗精华", "spec": "50ml", "quantity": 1, "quantity_text": "替换装", "certificate": "特证" },
    { "product_name": "双抗面膜", "spec": "1片", "quantity": 2 },
    { "product_name": "超膜银管", "spec": "15ml", "quantity": 1, "limited_edition": "会员礼" }
  ]
}
```

### Case C：PROYA 能量面霜（同款赠品）

图像特征："送同款 买45g至高到手90g"，主品能量面霜2.0经典型45g，赠品是同款小罐15g*2，¥459。

正确输出：
```json
{
  "brand": "PROYA",
  "final_price": 459,
  "main_products": [
    { "product_name": "能量面霜", "spec": "45g", "quantity": 1, "version": "2.0", "variant": "经典型" }
  ],
  "gift_products": [
    { "product_name": "能量面霜", "spec": "15g", "quantity": 2, "quantity_text": "15g*2", "version": "2.0", "variant": "经典型" }
  ],
  "notes": "selected tier: 买45g到手90g（45g主品+15g*2赠品）。会员礼超膜银管15ml为美妆产品，已计入gift_products。"
}
```

### Case D：KANS X肽套装（礼盒多主品 + 复杂赠品 + "正装"话术陷阱）

图像特征：X肽承爱礼盒，核心主品X肽面霜50g、X肽精华100ml、X肽精华乳100ml，"拍1享7件正装"是商家话术，把赠品包装成"正装"夸大价值感，实际上消费者只付费购买了核心产品，其余均为赠品。赠品分"限时加赠"和"520加赠"两组，有非美妆GWP承诺贺卡，¥499。

**识别陷阱说明**：
- "拍1享7件正装"、"享X件正装"、"到手X件"等话术中的"正装"不等于 main_products。
- 判断依据是消费者实际付费购买的是哪个产品，而不是商家如何描述赠品。
- 凡是出现在"送、赠、享、礼、加赠、限时加赠"等关键词后面的产品，一律视为 gift_products，即使商家称其为"正装"。

正确输出：
```json
{
  "brand": "KANS",
  "final_price": 499,
  "main_products": [
    { "product_name": "X肽面霜", "spec": "50g", "quantity": 1 },
    { "product_name": "X肽精华", "spec": "100ml", "quantity": 1 },
    { "product_name": "X肽精华乳", "spec": "100ml", "quantity": 1 }
  ],
  "gift_products": [
    { "product_name": "X肽面膜", "spec": "25ml", "quantity": 5 },
    { "product_name": "X肽次抛", "spec": "1.2ml", "quantity": 20, "quantity_text": "1.2ml*20支" },
    { "product_name": "X肽鱼子酱次抛精华", "spec": "1.2ml", "quantity": 20, "quantity_text": "1.2ml*20支" }
  ],
  "mechanism_text": ["拍1享7件正装（商家话术，实为赠品）", "限时加赠", "520加赠", "非美妆GWP（不计入PPI）：承诺贺卡 x1"],
  "notes": "承诺贺卡为非美妆GWP已过滤。'拍1享7件正装'为商家促销话术，实际主品为消费者付费购买的X肽面霜/精华/精华乳三件套，面膜及次抛均为赠品。"
}
```

### Case E：Flower Knows 眼影（彩妆无到手价）

图像特征：天鹅芭蕾六色眼影，色号#01黄油可颂，有会员券¥45（满300用），无到手价，买2件/3件送赠品（甜心小熊发夹为非美妆GWP）。

正确输出：
```json
{
  "brand": "FLOWER KNOWS",
  "final_price": null,
  "main_products": [
    { "product_name": "天鹅芭蕾眼影", "spec": "6.5g", "quantity": 1, "shade": "#01黄油可颂" }
  ],
  "gift_products": [
    { "product_name": "甜心小熊腮红", "spec": "5g", "quantity": 1 }
  ],
  "mechanism_text": ["买2件送甜心小熊发夹x1（非美妆GWP不计入）", "买3件送甜心小熊手拿镜（奶油糖粉）x1（非美妆GWP不计入）", "实付¥179送独角兽唇釉J07杏茶绒枪x1", "会员券¥45（满300使用）"],
  "notes": "彩妆图无到手价，需人工填写。发夹和镜子为非美妆GWP已过滤。独角兽唇釉为美妆，但仅在实付¥179时触发，未计入标准gift_products。"
}
```

### Case F：PRAMY 定妆喷雾（无赠品无到手价）

图像特征：后台保湿定妆喷雾黑瓶+白瓶展示，0元入会领专属优惠券，无到手价，无赠品。

正确输出：
```json
{
  "brand": "PRAMY",
  "final_price": null,
  "main_products": [
    { "product_name": "后台定妆喷雾黑瓶", "spec": "100ml", "quantity": 1 },
    { "product_name": "后台定妆喷雾白瓶", "spec": "100ml", "quantity": 1 }
  ],
  "gift_products": [],
  "mechanism_text": ["0元入会领专属优惠券"],
  "notes": "图中无赠品、无到手价。0元入会为会员权益非产品赠品。需人工填写 Actual Price。"
}
```

---

## 9. 优化 prompt 时建议重点关注

最影响结果稳定性的部分：

1. **多档促销选档**：必须选最高档（买60支 > 买30支），否则 PPI 计算偏高。
2. **空间布局分析**：先分析主品区和赠品区，再提取文字，避免把赠品说明错认为主品规格。
3. **图片上有字时必须照抄**：不要自动替换成模型"觉得更像"的产品名。
4. **赠品数量要完整保留**：尤其是 `5*2`、`5支*2盒`、`1.5ml*10支`。
5. **主品和赠品要分清**：尤其是"买 X 到手 Y"和"买正装送正装"的场景。
6. **版本、证书、色号、干皮/油皮/轻盈/滋润这类信息要放在单独字段**：不要混进短产品名。
7. **彩妆无到手价场景**：正确设 null 并写备注，不要猜价格。
8. **非美妆 GWP 过滤**：承诺贺卡、发夹、镜子等一律过滤，写入 mechanism_text。
9. **珀莱雅色彩规则**：目前只覆盖红宝石、双抗、源力、能量，后续遇到新品牌或新系列可以继续追加。
