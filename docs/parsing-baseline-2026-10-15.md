# 解析基线与版面保留改造（2026-10-15）

已完成环境恢复、11 篇/167 页的基线评估，以及带逐页回退和来源定位的解析层。没有实施研究信息抽取、LLM 调用、聚类或 OCR。原 PDF、旧 JSON、旧 Markdown 和旧解析脚本保持原样，新结果写入 `data/processed/`。

## 1. 是否必须输出 Markdown

不必须。建议将两种用途分开：

- **档案 JSON**：保留原始文本、页码、block/line/span、坐标、字体、字号、模型版面候选、质量警报、章节建议。用于核查、调试和重新导出，不直接全部发给大模型。
- **模型输入文本**：每段文本只出现一次，附 `[p2.b3]` 这样的来源标记。对应的 provenance 文件在本地保存字符区间、行 ID 和坐标。
- **可选 Markdown**：用于人工查看或需要表格排版的场景，转换失败不会导致原始文本被舍弃。

格式扩展名不会改变 token；实际文本、转义、重复字段和附加标记才会影响。此次采用 `tiktoken 0.14.0 / cl100k_base` 做固定编码的比较，不代表未来选定模型的账单 token 数，也没有调用远程模型。

11 篇合计：

| 输入内容 | Token 数 |
|---|---:|
| 旧完整 JSON（全文、逐页、清洗和章节等重复内容） | 1,013,847 |
| 原生提取全文一份 | 195,482 |
| 新模型输入文本（去除有记录的重复/页边内容，含来源标记） | 187,234 |
| 同一份模型文本包入单字段 JSON | 196,802 |
| 同一份模型文本包入 Markdown text 代码块 | 187,289 |
| 原有 Markdown（部分正文缺失，不能视为等量内容） | 129,401 |

新模型输入比旧完整 JSON 少约 **81.5%** token，主要来自避免重复传输以及去除重叠重复文字，并非 Markdown 格式本身的作用。原有 Markdown 更短的一部分原因是丢失了正文。这里的同文 Markdown 对照只衡量代码块包装开销，不是完整 Markdown 重排的普遍结论。

## 2. 环境与复现

原 `.venv` 仍保留；其基础解释器 `D:\Anaconda3\python.exe` 已失效。新环境为 `.venv-review`，Python 3.12.14。运行时依赖固定为 PyMuPDF / PyMuPDF4LLM / pymupdf-layout 1.27.2.3，与原目录的解析库版本一致；其余依赖的精确版本见 `requirements-lock.txt`。此锁文件记录本次 Windows x64 环境，跨平台需重新验证。

在项目根目录运行：

```powershell
# 当前机器环境已经准备好，直接运行下列命令。
& .venv-review/Scripts/python.exe -X utf8 -m pytest -q
& .venv-review/Scripts/python.exe -X utf8 -m src.pipeline --input data/pdf --output data/processed --markdown
& .venv-review/Scripts/python.exe -X utf8 -m scripts.evaluate_corpus --tokens
```

在新机器或新环境中，先提供可用且带 pip 的 Python 3.12 解释器：

```powershell
./scripts/bootstrap.ps1 -Python 'C:/path/to/python.exe'
```

bootstrap 使用新的 `.venv-review`，不覆盖旧 `.venv`。运行无需激活虚拟环境。项目将 pytest 临时目录固定在 `tmp/pytest`；该目录仅供测试使用。token 评估首次运行需下载公开词表到 `tmp/tiktoken`，本机已缓存。

其他用法：

```powershell
# 只保存原生文字证据，不运行版面模型。
& .venv-review/Scripts/python.exe -X utf8 -m src.pipeline --no-layout --output data/processed-native

# 不重新解析 PDF，从已有 JSON 重新生成模型输入。
& .venv-review/Scripts/python.exe -X utf8 -m src.export_model

# 仅在检查过章节建议后使用：另存排除参考文献的模型输入。
& .venv-review/Scripts/python.exe -X utf8 -m src.export_model --exclude-references --output data/processed-no-references
```

后两种自定义输出目录也应作为本地产物保留，默认 `.gitignore` 覆盖 `data/processed*/`。全语料评估默认读取 `data/processed`。如果旧基线输入文件发生变化，评估会拒绝覆盖原基线，使用 `--output reports/another-baseline` 新建基线。

## 3. 实现与数据契约

主入口为 `python -m src.pipeline`，不需要依次运行旧脚本。每篇输出目录以 PDF SHA-256 的前 16 位命名，完整 SHA-256 存在 JSON 内：

```text
data/processed/<document-id>/
  document.json          # schema_version = layout-0.2
  model.txt              # 给模型的一份文本
  model.provenance.json  # 输出字符区间 -> 原生行、页码、bbox
  candidate.md           # 只有 --markdown 才另外输出
```

- `pages[].page_number` 为从 1 开始的物理 PDF 页码，不是文章印刷页码。
- 坐标单位为 PDF point，左上角原点，未旋转页面坐标；另存页面旋转角。
- 每个原生行有稳定的 page/block/line ID；span 保留文字、字体、字号、flags、颜色、原点和 bbox。
- 原生证据先提取，再交给现成的 PyMuPDF4LLM 版面模型。版面模型提供区域类型和区域阅读顺序。
- 模型候选文本相对原生文字的规范化字符召回低于 0.97、5-gram 召回低于 0.90、膨胀超过 1.35 倍、原生行未映射或解析异常时，退回 PDF 原生文字流顺序并记录原因。不会直接按 y/x 排序来假装解决双栏问题。
- 每个原生行都留在档案。只有页边页码、至少跨 3 页重复的页边文字、相同位置的相同文字可从模型视图排除，并记录 `excluded_reason`；重叠重复文字另存 `duplicate_of`。
- 数字独立成行也不会被全局删除。模型视图将不可打印控制字符替换为空格，原文保留，provenance 记录该变换。
- 每个非排除行必须恰好属于一个章节。无标题、首标题之前的内容保留为 `front_matter_or_unknown`，JSTOR 封面单列为 `cover`。
- 章节使用版面模型建议，加上原生字号/字形、编号或标准节名佐证；跨行标题合并。所有章节均标记 `needs_review`。正文参考文献标题可以开启 references 区域，封面上的 REFERENCES 不会误触发。
- 默认模型输入保留参考文献。`--exclude-references` 只影响派生文本，建议人工核对章节边界后再使用，尤其是文末有英文摘要的中文文章。
- 单篇失败不会阻断其余文献；命令以非零状态退出并生成 `run-errors.json`。逐页版面失败则保留原生结果和警报。

## 4. 基线结果和可核查边界

机器可读文件位于 `reports/baseline/`：

| 文件 | 内容 |
|---|---|
| `corpus.csv` | 逐篇全文规模、Markdown 覆盖、异常字符、章节数、排除行、表格区域统计 |
| `pages.csv` | 167 页的候选召回、回退理由、OCR 核查标志 |
| `tokens.csv` | 每篇各类文本的 token 对照 |
| `baseline-manifest.json` | 33 个原 PDF / JSON / Markdown 文件的 SHA-256 和大小 |
| `environment.json` | Python、包版本、代码和标注文件校验值 |
| `annotation-results.json` | 人工标注页的标题与关键片段检查 |
| `summary.json` | 汇总指标 |

11 篇、167 页均完成，没有最终版面解析异常。原生提取文本与档案行文本的规范化字符计数召回均为 1.0，且验证了行覆盖和模型输入字符区间对应关系。**这只证明已提取的文字被保存，不能证明 PDF 所有可见信息都已被正确识别。**

采用保守阈值后，138 页使用原生文字流顺序，29 页使用模型区域顺序；这些回退页面不能宣称已经解决阅读顺序。24 页被低文本量或异常 Unicode 指标标为需要 OCR/编码核查，并不等于都需要重新 OCR。

三篇旧文献原 Markdown 的规范化字符计数召回：Abbott 约 7.9%、Heinz & Laumann 约 5.3%、Liu & Emirbayer 约 2.2%。重新运行同版本仍复现缺失。回退路径保留了原生文字。

Liu 文献发现 887 个相同坐标、相同内容的重复行。它们仍存在档案中，但模型视图只保留一份。因此该文献模型文字相对原生字符计数约为一半，是有来源记录的去重，不能与 Markdown 正文缺失混为一谈。

在 3 篇文献的 6 个页面上，通过 Poppler 渲染进行人工核查并建立小型标注集：16 个节标题、15 个文本/数值片段；新版保留 15/15 片段，Markdown 保留 13/15。保守标题策略命中 13/16，额外误报 0；Hu 第 2 页的三个方法小标题由于字体信息未提供足够佐证而未自动接受，正文仍完整保留。详情见 `annotation-results.json`。这个集合用于开发调试，不是独立专家标注，也不是留出测试集，不能将其准确率推广到全部语料。

16 项自动测试通过，覆盖原文与来源区间、无标题/空页、候选正文丢失、解析失败、双栏顺序、封面与参考文献、页边去除、控制字符、中文字体 bbox、多行标题、重复 OCR 层、旋转页面和 CLI 部分失败等情况。

表格检查只覆盖表格区域/候选输出及少量数值片段，没有验证所有单元格的二维对应。公式、图片内文字、隐藏 OCR 层的识别错误也未自动修复。Abbott 与 Heinz 的正文已保留，但章节大多仍是 unknown；这是明确保留的待解决项。

## 5. Skill / 工具选择

本轮直接复用了环境中已有的 PDF skill（Poppler 页面渲染核查）和项目现有解析库，没有另写 PDF 解析引擎。新增代码负责档案、质量比较、模型输入导出和本项目的章节候选约束。

检索并阅读了 [Docling 官方 skill](https://github.com/docling-project/docling/blob/main/docling/.agents/skills/docling/SKILL.md) 及其 [CLI 说明](https://github.com/docling-project/docling/blob/main/docling/.agents/skills/docling/references/cli.md)。它由上游项目维护，适合作为后续复杂文献解析候选。但 native pipeline 不提供标题/表格/阅读顺序推断；standard/VLM 路线又会增加模型依赖。因此本轮没有额外安装 Docling 或第三方 skill 包，也没有将本地文献发送到外部服务。

现有 PyMuPDF4LLM 已提供逐页块、坐标与版面类别，见 [官方 API 文档](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html)。本次以固定版本的实际运行和源码为准，不依赖最新文档假定旧版本行为。

下一阶段可以在当前相同基线下评估 Docling/OCR 对扫描文献的改进，并增加独立标注页面；在需要人工核查的页面上，避免直接相信章节边界或表格数值关系。
