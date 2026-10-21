# 六篇试点：已确认决定与执行记录（2026-10-21）

本文记录用户最新决定，补充并在有差异时替代 2026-10-19 计划。只涉及指定六篇论文、模型对照及交付内容。

## 已确认的产品要求

- 交付内容是关系总览、议题详情、证据说明、问题线索的综合。关系图与文字是期望方向；最终格式和界面在交付阶段决定。
- 当前 JSON、Markdown 等仅是中间记录，不能据此认定最终产品必须输出 Markdown 或网页。
- API 可以由个人在本地配置，也可以由多人产品的后端统一提供；用户不需要逐个环节手动调用。用户自带凭据与平台承担费用属于后续产品决策。
- 先检验简单模型流程是否足够，不能因预先画了多个阶段就强制每个阶段调用模型。一个模型可以承担多个任务；是否使用多模型由实测决定。
- 用户已选择 GLM 与 DeepSeek 各做一次小规模对照。模型具体版本、实际请求范围和费用上限仍待确认；选择服务不等于授权任意付费调用。
- 复用现有全文档案。压缩主要减少无关文本和重复输入，保留限定条件、反向证据及原文定位。文件字节变小不保证文本 token 下降。

## 用户指定的试点

| 代号 | 文献 | 已有档案目录 | PDF物理页数 |
| --- | --- | --- | --- |
| LI | 郦菁、张纬松《从“职业”到“知识”：医学社会学的转向和重构》 | `9088a34e5b727e60` | 12 |
| OLEARY | O’Leary 等，The Boundaries of the Social Work Relationship Revisited | `6eeeeee72fac2987` | 19 |
| LIU | Liu 与 Emirbayer，Field and Ecology | `64bdf14d7898e583` | 19 |
| ABBOTT | Abbott，Boundaries of Social Work or Social Work of Boundaries | `c5df574d26d2647d` | 19 |
| KING | King 等，Contested professional role boundaries in health care | `f3a487226c718887` | 9 |
| HEINZ | Heinz 与 Laumann，The Legal Profession: Client Interests, Professional Roles, and Social Hierarchies | `fcb0979b05ee8a0a` | 33 |

名单和已知质量疑点保存在 [配置](../configs/pilot-six-papers.json)。作者及题名按实际档案核对；中文文件名仅标郦菁，首页另列张纬松。六篇共 111 页。

## Skill 核查结果

“不存在能完成类似任务的 skill”不是正确结论。已找到以下明确覆盖相关需求的公开流程：

| 候选 | 与需求匹配的内容 | 适配边界 |
| --- | --- | --- |
| [paper-comparison](https://github.com/biocheming/literature-research/blob/main/skills/paper-comparison/SKILL.md) | 结构化提取、比较矩阵、共识/冲突/互补、多论文比较 | 最接近本次任务；默认字段带有实证研究取向，需要支持理论论证、规范建议和跨层次比较 |
| [evidence-synthesis](https://github.com/biocheming/literature-research/blob/main/skills/evidence-synthesis/SKILL.md) | 支持/反对证据与综合判断 | 预设研究问题及支持比例不宜原样套用到这六篇异质文献；不能用论文票数衡量理论共识 |
| [literature-review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/literature-review/SKILL.md) | 文献综述、主题综合、引用检查 | 同时包含检索/筛选流程，本次用户已给定文献；元数据/DOI校验不等于观点有原文支持 |
| 本地 text-analyst | 文本分析设计、预处理、模型与评价流程 | 可辅助方法设计，主要面向计算文本分析；并非现成的六篇论文自动综合程序 |

本轮只评估这些 skill 的说明，未安装或运行外部 skill。公开描述能证明工作流接近需求，不能证明它在本项目上的质量已验证。skill 可让宿主助手组织推理与工具，但不会自动提供一个无需模型的独立推理引擎。

## 本轮实际完成的内容

1. 新增离线准备模块 `src.pilot_prepare`，读取用户指定的六篇档案，验证文档 ID、来源区间和重复行。
2. 根据已有章节标签排除 cover、references 及空行；不修改原始档案。保留被排除的来源 ID。未知章节、脚注与表格可能仍在输入中，没有宣称完成全面清洗。
3. 保留 301,128 个来源文本字符；原始 model.txt 合计 354,206 字符。前者仅为来源行文本，后者还含导出分隔等内容，差值不能全部解释为语义内容压缩收益，更不是 token 节省比例。
4. 按完整来源行准备 35 个块，目标上限 12,000 字符；不重叠，记录相邻块，跨块论证需按邻接关系回读。该长度是离线准备参数，不代表某个模型的上下文限制。
5. 准备全部 15 个文献对；首轮直接分析暂选 LI + OLEARY，以覆盖中文和英文。此样本不充分代表扫描件质量、综述和长文难度，后续需补充。
6. 当前助手根据摘要、导论、结论和针对性正文片段，整理 17 条要点、15 对初步关系、4 个议题及4个问题线索。保存 213 条唯一证据行并校验来源；不是六篇逐行通读结果，不是人工金标准，不是外部 API 结果。

本地工作目录为 [outputs/pilot-2026-10-21](../outputs/pilot-2026-10-21/)，其中：

- `manifest.json`：档案哈希、页数、覆盖与运行状态。
- `evidence.jsonl`、`chunks/`、`chunks.json`、`exclusions.json`：来源行、分块和排除记录。
- `requests/claims.json`、`requests/direct.json`、`requests/comparison-template.json`：待调用任务输入；没有嵌入凭据或真实模型配置。
- `assistant-review.json`：当前助手撰写的初步判断，标明论点性质、条件和证据范围。
- `working-notes.md`、`review-evidence.json`、`review-validation.json`：阅读副本、实际引用文本、机械校验结果。

“本地初步结果”指当前助手读取本地材料后撰写的分析。Python 只整理文本、分块、校验引用和生成阅读副本。没有额外调用 GLM/DeepSeek，不应称为无模型分析或服务 API 测试。

2026-10-21 验证：31 项自动化测试通过；已核对原档案哈希及证据行的文档 ID、页码、字符位置和原文一致性。运行命令为 `.venv-review/Scripts/python.exe -B -X utf8 -m pytest -q -o addopts= --basetemp=tmp/pytest-pilot-20261021 -p no:cacheprovider`。机械验证不替代对论点解释和关系判断的人工复核。

## 外部 API 对照的下一步

1. 在同一组中英文材料与相同任务说明下，GLM 和 DeepSeek 各运行一次直接分析；先检验论点忠实度、跨语言比较、来源支持与实际用量。两次结果是小规模比较，不构成稳定排名。
2. 试跑前确认模型版本、上下文与输出预算。`requests/direct.json` 的系统提示和用户输入共 90,668 字符；不是 90,668 tokens。下一步用选定模型的计数方式或明确标注的近似方法估算，再给出费用上限建议。
3. 费用范围应包含输出/推理 token、可能的重试及缓存差异。不能把首次预算建立在一定命中缓存的假设上。
4. 只有在直接分析出现具体遗漏、证据错误或成本问题时，才增加逐篇提取、分批关系判断或定点复核。覆盖全部 15 对是比较范围，不等于固定 15 次 API 请求。
5. 初步助手分析可以帮助设计评价项，但不作为标准答案硬约束其他模型；盲评时隐藏模型名称，记录它发现而助手未发现的有效关联。

当前：**无 API 配置、零外部模型调用、费用上限未确定、付费试跑未获确认。**

配置建议是本地项目 `.env` 使用 `DEEPSEEK_API_KEY` 和 `ZHIPU_API_KEY`；不要在聊天中发送密钥。后续提供方适配器将读取这些约定名称，当前离线准备模块不读密钥也不发请求。现有 `src.fulltext_extract` 仍是旧 OpenAI 实验，不能用新变量直接运行它。应在适配器完成、具体请求可检查且用户确认后启动真实调用。

官方接口、模型和价格需在实际试跑时复核：[智谱模型计费](https://docs.bigmodel.cn/cn/guide/start/pricing)、[智谱结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)、[DeepSeek API 文档](https://api-docs.deepseek.com/)。
