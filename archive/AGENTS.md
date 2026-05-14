# archive/

论文写作相关文件存档。

## 目录结构

```
archive/
├── AGENTS.md              # 本文档
├── mermaid/               # Mermaid 架构图导出
│   ├── 068636d9120fc252.png
│   ├── 4c5f96646f18b2bd.png
│   └── 763ddb736e861848.png
├── figs/                  # 论文图表
│   ├── fig4-1_exact_match_overall.png
│   ├── fig4-2_exact_match_by_type.png
│   ├── fig4-3_value_f1_by_type.png
│   ├── fig4-4_tool_calls_by_type.png
│   ├── fig4-5_ablation_safety.png
│   ├── fig4-6_ablation_architecture.png
│   └── fig4-7_ablation_personalization.png
├── ref/                   # 参考文献 PDF 等原文资料
│   ├── 中期检查表参考1.md
│   └── 中期检查表参考2.md
├── legacy/                # 旧版存档
│   └── 中期检查答辩稿.md
├── 开题报告.md             # 开题报告
├── 中期检查表.md            # 中期检查表
├── 初稿-20260430.md        # 论文初稿（2026-04-30 版）
├── 初稿-20260511.md        # 论文初稿（2026-05-11 版）
└── 初稿意见-20260430.md    # 初稿审阅意见（2026-04-30）
```

## 组成

| 类别 | 文件 | 说明 |
|------|------|------|
| 论文稿 | `初稿-20260430.md` | 初稿第一版 |
| 论文稿 | `初稿-20260511.md` | 初稿第二版 |
| 审阅意见 | `初稿意见-20260430.md` | 2026-04-30 收到的初稿修改意见 |
| 开题 | `开题报告.md` | 开题报告 |
| 中期 | `中期检查表.md` | 中期检查表 |
| 架构图 | `mermaid/` | Mermaid 架构图导出（3 张，PNG 格式） |
| 图表 | `figs/` | 论文图表（fig4-1 至 fig4-7，PNG 格式） |
| 参考 | `ref/` | 参考文献原文、模板参考等辅助材料 |
| 旧版 | `legacy/` | 各阶段历史版本（如中期检查答辩稿） |

## 写作规范

### 中文标点符号

- 中文论述部分须使用中文标点。
- 引号须用 `“”` 和 `‘’`，禁用英文半角 `"` 或其全角版本。
- 代码块、内联代码、英文专有名词、数学公式中的引号不受此限制。

### 不泄露项目特有配置与实现细节

论文面向学术读者，应描述系统设计思路与架构决策，而非本项目的具体配置文件名、环境变量名、函数名或实验运行标识符。

**禁止出现的内容：**

- 配置文件名（如 `rules.toml`、`strategies.toml`、`config.yaml`）→ 改为“从外部配置文件加载”
- 环境变量名（如 `MEMORYBANK_ENABLE_FORGETTING`）→ 改为“通过配置开关启用”
- 配置段名（如 `[model_groups.judge]`）→ 改为“从配置加载”
- 函数名（如 `postprocess_decision()`）→ 改为“后处理函数”或“规则后处理”
- 实验运行标识符（如实验ID、run ID）→ 删除
- 常量名（如 `ABLATION_SEED`）→ 保留语义描述，删除标识符
- 内部阈值校准参数（如“默认3分占比≤50%”）→ 保留检测概念，删除具体参数值

**可保留的内容：**

- 数据结构的语义描述（维度、字段含义）
- 算法逻辑与公式
- 参考文献（如VehicleMemBench）中引用的API名（属框架公开接口）
- 模型名称（如 deepseek-v4-flash，属公开信息）

## 参考文献

### 主要参考文献

| 论文 | 链接 | 说明 |
|------|------|------|
| MemoryBank: Enhancing Large Language Models with Long-Term Memory | [arxiv-2305.10250](https://arxiv.org/abs/2305.10250) | 记忆系统理论基础——三层记忆架构、Ebbinghaus 遗忘曲线、分层摘要 |
| VehicleMemBench: An Executable Benchmark for Multi-User Long-Term Memory in In-Vehicle Agents | [arxiv-2603.23840](https://arxiv.org/abs/2603.23840) | 基准测试框架——50 组数据集、23 模块模拟器、五种记忆策略对比 |

### 论文参考文献

论文正文引用 [1]-[17] 以及本文分析确认的额外可引文献。

### 论文稿已收录 [1]-[17]

| 编号 | 文献 | 正文引用位置 |
|------|------|-------------|
| [1] | Zhong W, Guo L, Gao Q, et al. MemoryBank: Enhancing Large Language Models with Long-Term Memory[C]. NeurIPS, 2023. | §1.2, §2.2, §3.4 |
| [2] | Chen Y, Xu Y, Ding X, et al. VehicleMemBench: An Executable Benchmark for Multi-User Long-Term Memory in In-Vehicle Agents[EB/OL]. arXiv:2603.23840, 2026. | §1.2, §2.3, §4.1 |
| [3] | Ablaßmeier M, Poitschke T, Reifinger S, et al. Context-Aware Information Agents for the Automotive Domain Using Bayesian Networks[C]. HCII, 2007. | §1.1, §1.2, §2.1 |
| [4] | Kim G, Lee J, Yeo D, et al. Physiological Indices to Predict Driver Situation Awareness in VR[C]. UbiComp/ISWC, 2023. | §1.2, §2.1 |
| [5] | Chen X, Wang X, Fang C, et al. Emotion-aware Design in Automobiles: Embracing Technology Advancements to Enhance Human-Vehicle Interaction[C]. CHI, 2025. | §1.1, §1.2, §2.1 |
| [6] | Parwani K, Das S, Vijay D K. Model Context Protocol (MCP): A Scalable Framework for Context-Aware Multi-Agent Coordination[EB/OL]. Zenodo, 2025. | §1.2, §2.1 |
| [7] | Karpukhin V, Oğuz B, Min S, et al. Dense Passage Retrieval for Open-Domain Question Answering[C]. EMNLP, 2020. | §3.3 |
| [8] | Johnson J, Douze M, Jégou H. Billion-scale Similarity Search with GPUs[J]. IEEE Trans. Big Data, 2021, 7(3): 535-547. | §1.1, §3.3 |
| [9] | Ebbinghaus H. Memory: A Contribution to Experimental Psychology[M]. Dover, 1964 (1885). | §1.2, §2.2, §3.4 |
| [10] | Lu J, An S, Lin M, et al. MemoChat: Tuning LLMs to Use Memos for Consistent Long-Range Open-Domain Conversation[EB/OL]. arXiv:2308.08239, 2023. | §1.2, §2.2 |
| [11] | Graves A, Wayne G, Danihelka I. Neural Turing Machines[EB/OL]. arXiv:1410.5401, 2014. | §2.2 |
| [12] | Xu J, Szlam A, Weston J. Beyond Goldfish Memory: Long-Term Open-Domain Conversation[EB/OL]. arXiv:2107.07567, 2021. | §1.2, §2.2 |
| [13] | Chhikara P, et al. Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory[EB/OL]. arXiv:2504.19413, 2025. | §1.2, §2.2 |
| [14] | Li Z, et al. MemOS: A Memory OS for AI System[EB/OL]. arXiv:2507.03724, 2025. | §1.2, §2.2 |
| [15] | Endsley M R. Toward a Theory of Situation Awareness in Dynamic Systems[J]. Human Factors, 1995, 37(1): 32-64. | §1.1, §1.2, §2.1, §3.6, §3.8, §5.1 |
| [16] | Wickens C D. Multiple Resources and Mental Workload[J]. Human Factors, 2008, 50(3): 449-455. | §1.1, §1.2, §2.1, §3.6, §3.7, §3.8, §5.1 |
| [17] | Yang J, et al. VehicleWorld: A Highly Integrated Multi-Device Environment for Intelligent Vehicle Interaction[EB/OL]. arXiv:2509.06736, 2025. | §1.2, §2.3, §4.1 |

