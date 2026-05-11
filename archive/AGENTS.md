# 参考文献

## 主要参考文献

| 论文 | 链接 | 说明 |
|------|------|------|
| MemoryBank: Enhancing Large Language Models with Long-Term Memory | [arxiv-2305.10250](https://arxiv.org/abs/2305.10250) | 记忆系统理论基础——三层记忆架构、Ebbinghaus 遗忘曲线、分层摘要 |
| VehicleMemBench: An Executable Benchmark for Multi-User Long-Term Memory in In-Vehicle Agents | [arxiv-2603.23840](https://arxiv.org/abs/2603.23840) | 基准测试框架——50 组数据集、23 模块模拟器、五种记忆策略对比 |

## 论文参考文献

论文正文引用 [1]-[10] 以及本文分析确认的额外可引文献。

## 论文稿已收录 [1]-[10]

| 编号 | 文献 | 正文引用位置 |
|------|------|-------------|
| [1] | Zhong W, Guo L, Gao Q, et al. MemoryBank: Enhancing Large Language Models with Long-Term Memory[C]. NeurIPS, 2023. | §1.2, §2.2, §3.2 |
| [2] | Chen Y, Xu Y, Ding X, et al. VehicleMemBench: An Executable Benchmark for Multi-User Long-Term Memory in In-Vehicle Agents[J]. arXiv:2603.23840, 2026. | §1.2, §2.3, §5.1 |
| [3] | Ablaßmeier M, Poitschke T, Reifinger S, et al. Context-Aware Information Agents for the Automotive Domain Using Bayesian Networks[C]. HCII, 2007. | §1.2, §2.1 |
| [4] | Kim G, Lee J, Yeo D, et al. Physiological Indices to Predict Driver Situation Awareness in VR[C]. UbiComp/ISWC Adjunct, 2023. | §2.1 |
| [5] | Chen X, Wang X, Fang C, et al. Emotion-aware Design in Automobiles[C]. CHI, 2025. | §2.1 |
| [6] | Parwani K, Das S, Vijay D K. Model Context Protocol (MCP): A Scalable Framework for Context-Aware Multi-Agent Coordination[Z]. Zenodo, 2025. | §1.2, §2.1 |
| [7] | Karpukhin V, Oğuz B, Min S, et al. Dense Passage Retrieval for Open-Domain Question Answering[C]. EMNLP, 2020. | §3.3 |
| [8] | Johnson J, Douze M, Jégou H. Billion-scale Similarity Search with GPUs[J]. IEEE Trans. Big Data, 2019, 7(3): 535-547. | §3.3 |
| [9] | Ebbinghaus H. Memory: A Contribution to Experimental Psychology[M]. Dover, 1964 (1885). | §3.2 |
| [10] | Lu J, An S, Lin M, et al. MemoChat: Tuning LLMs to Use Memos for Consistent Long-Range Open-Domain Conversation[J]. arXiv:2308.08239, 2023. | §1.2, §2.2 |

## 论文稿提及但未引（建议补引）

以下文献在论文正文中以名称或描述出现，但缺少正式引用编号。

| 文献 | 链接 | 正文提及位置与补引理由 |
|------|------|------------------------|
| Graves A, Wayne G, Danihelka I. Neural Turing Machines[J]. arXiv:1410.5401, 2014. | [arxiv-1410.5401](https://arxiv.org/abs/1410.5401) | §2.2："Memory-Augmented Neural Networks（MANNs）如Neural Turing Machines" |
| Xu J, Szlam A, Weston J. Beyond Goldfish Memory: Long-Term Open-Domain Conversation[J]. arXiv:2107.07567, 2021. | [arxiv-2107.07567](https://arxiv.org/abs/2107.07567) | §2.2："Xu等人提出了多会话长程对话数据集" |
| Chhikara P, et al. Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory[J]. arXiv:2504.19413, 2025. | [arxiv-2504.19413](https://arxiv.org/abs/2504.19413) | §2.2："在工业应用方面，Mem0、MemOS等第三方记忆系统" |
| Li Z, et al. MemOS: A Memory OS for AI System[J]. arXiv:2507.03724, 2025. | [arxiv-2507.03724](https://arxiv.org/abs/2507.03724) | §2.2：同上（MemOS） |

## 建议补充至论文稿的理论基础文献

以下文献论文稿尚未提及，但相关章节的内容（情境意识、多资源理论、仿真环境）需这些文献作为理论支撑。

| 文献 | 链接 | 建议补充位置与理由 |
|------|------|-------------------|
| Endsley M R. Toward a Theory of Situation Awareness in Dynamic Systems[J]. Human Factors, 1995, 37(1): 32-64. | DOI:10.1177/001872089503700107 | §1.1/§2.1："情境意识"为核心概念但无引用。规则引擎中疲劳抑制、过载延后约束的设计依据 |
| Wickens C D. Multiple Resources and Mental Workload[J]. Human Factors, 2008, 50(3): 449-455. | DOI:10.1518/001872008X288394 | §4.2：高速仅音频规则的理论基础——驾驶占用视觉通道，非驾驶交互应使用音频通道 |
| Yang J, et al. VehicleWorld: A Highly Integrated Multi-Device Environment for Intelligent Vehicle Interaction[J]. arXiv:2509.06736, 2025. | [arxiv-2509.06736](https://arxiv.org/abs/2509.06736) | §5.1：VehicleMemBench 的执行环境底层，提供23个车辆模块111个可执行工具 |
