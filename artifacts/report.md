# CiteGuard 学术引用真实性与声明对齐核验报告

- **生成时间 (UTC)**：2026-11-24 08:37:47 UTC
- **SkillHub 技能**：`citation-integrity-verifier` (`v20261104.101003`)
- **本地推理模型**：`Spark-X2.6-4B-Q4_K_M`
- **检索源与范围声明**：Crossref REST API + arXiv API (export.arxiv.org) + OpenAlex Works API（注：检索不到≠学术不端，未收录于上述公开库的会议报告或内部文献标为「无法核验」）

## 1. 统计摘要

- 总核验条目：**10**
- ✅ 已核验存在：**5**（通过率 50.0%）
- ⚠️ 存疑：**2**
- ❌ 疑似编造：**2**（疑点/疑似编造占比 40.0%）
- ⬜ 无法核验：**1**

## 2. 逐条验证状态表

| ID | 状态 | DOI 语法 | 检索源/方式 | 声明对齐 | 耗时(s) | 核验摘要 |
| --- | --- | --- | --- | --- | ---: | --- |
| `R1` | ✅ 已核验存在 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 支持 | 4.17 | 文献条目与检索到的原始文献在标题、年份及arXiv编号上一致，但作者列表不完整（条目以et al.省略，原始文献含完整作者）且venue表述 |
| `R2` | ✅ 已核验存在 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 支持 | 4.72 | 经核对，所引文献的标题、年份与arXiv编号与手稿引用一致，但作者列表与venue表述存在差异：CITED_ENTRY作者为Hu E J等且 |
| `R3` | ✅ 已核验存在 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 部分支持 | 4.33 | 元数据方面，引用条目作者为Lewis等且年份为2020，与 ground truth 一致，但作者列表不完整且venue表述与ground  |
| `R4` | ✅ 已核验存在 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 矛盾 | 3.76 | 引用条目与检索到的 ground truth 在作者列表、会议/发表venue表述上存在差异，且核心主张完全相反：ground truth  |
| `R5` | ✅ 已核验存在 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 支持 | 5.23 | 文献条目与检索到的真实文献在标题、年份、arXiv编号上一致，但作者列表与venue表述存在差异（作者为完整列表且venue为arXiv p |
| `R6` | ⚠️ 存疑 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 部分支持 | 3.73 | 引用条目与检索到的原始文献在作者、年份、发表venue上存在差异：原始文献实际作者为Ashish Vaswani等，年份为2017，venu |
| `R7` | ⚠️ 存疑 | 无DOI | arXiv (arxiv_id_exact, HTTP 200) | 支持 | 3.82 | 文献条目与检索到的原始文献在标题、arXiv编号上一致，但作者列表、年份（条目为2019，原始为2022）及venue（条目为arXiv预印 |
| `R8` | ❌ 疑似编造 | 合法 | Crossref (doi_exact, HTTP 404) | 无关 | 2.78 | 经Crossref按DOI精确检索，该文献未找到（HTTP 404，DOI未注册），因此无法核实标题、作者、年份、会议/期刊及DOI等元数据 |
| `R9` | ❌ 疑似编造 | 合法 | Crossref (doi_exact, HTTP 404) | 无关 | 2.65 | 经Crossref按DOI精确检索，该文献未注册（HTTP 404），返回未找到任何标题、作者、年份、期刊或DOI信息，因此元数据无法与任何 |
| `R10` | ⬜ 无法核验 | 无DOI | arXiv (arxiv_title_search, HTTP -) | 未提供正文 | 1.92 | 检索在arXiv范围内因标题为非ASCII/中文而跳过，未找到对应文献条目，因此元数据无法与外部真实文献匹配；手稿正文未提供，无法进行正文层 |

## 3. 差异明细、幻觉特征与证据链

### [R1] ✅ 已核验存在 · 对齐：支持
- **原始引文**：`[1] Vaswani A, Shazeer N, Parmar N, et al. Attention Is All You Need[C]//Advances in Neural Information Processing Systems. 2017. arXiv:1706.03762`
- **正文声明**：Vaswani et al. (2017) proposed the Transformer architecture based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=1706.03762](https://export.arxiv.org/api/query?id_list=1706.03762)
- **字段比对**：
  - `title`：一致（引用：`Attention Is All You Need` vs 检索：`Attention Is All You Need`）
  - `year`：一致（引用：`2017` vs 检索：`2017`）
  - `author`：一致（引用：`Vaswani A, Shazeer N, Parmar N` vs 检索：`Ashish Vaswani, Noam Shazeer, Niki Parmar`）
- **文献原文证据片段**（✅ 原文命中）：> We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "venue"],   "claim_alignment": "支持",   "evidence_quote": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolution`

### [R2] ✅ 已核验存在 · 对齐：支持
- **原始引文**：`[2] Hu E J, Shen Y, Wallis P, et al. LoRA: Low-Rank Adaptation of Large Language Models[J]. 2021. arXiv:2106.09685`
- **正文声明**：LoRA freezes pre-trained model weights and injects trainable rank decomposition matrices into Transformer layers to reduce trainable parameters.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=2106.09685](https://export.arxiv.org/api/query?id_list=2106.09685)
- **字段比对**：
  - `title`：一致（引用：`LoRA: Low-Rank Adaptation of Large Language Models` vs 检索：`LoRA: Low-Rank Adaptation of Large Language Models`）
  - `year`：一致（引用：`2021` vs 检索：`2021`）
  - `author`：一致（引用：`Hu E J, Shen Y, Wallis P` vs 检索：`Edward J. Hu, Yelong Shen, Phillip Wallis`）
- **文献原文证据片段**（✅ 原文命中）：> We propose Low-Rank Adaptation, or LoRA, which freezes the pre-trained model weights and injects trainable rank decomposition matrices into each layer of the Transformer architecture, greatly reducing the number of trainable parameters for downstream tasks.
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "venue"],   "claim_alignment": "支持",   "evidence_quote": "We propose Low-Rank Adaptation, or LoRA, which freezes the pre-trained model weights and injects trainable rank decomposition matrices into eac`

### [R3] ✅ 已核验存在 · 对齐：部分支持
- **原始引文**：`[3] Lewis P, Perez E, Piktus A, et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks[C]//NeurIPS. 2020. arXiv:2005.11401`
- **正文声明**：RAG combines pre-trained parametric memory with a non-parametric dense vector index of Wikipedia, achieving exact 100% factual accuracy without any hallucinations on medical licensing exams.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=2005.11401](https://export.arxiv.org/api/query?id_list=2005.11401)
- **字段比对**：
  - `title`：一致（引用：`Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks` vs 检索：`Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks`）
  - `year`：一致（引用：`2020` vs 检索：`2020`）
  - `author`：一致（引用：`Lewis P, Perez E, Piktus A` vs 检索：`Patrick Lewis, Ethan Perez, Aleksandra Piktus`）
- **文献原文证据片段**（✅ 原文命中）：> We introduce RAG models where the parametric memory is a pre-trained seq2seq model and the non-parametric memory is a dense vector index of Wikipedia, accessed with a pre-trained neural retriever.
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "venue"],   "claim_alignment": "部分支持",   "evidence_quote": "We introduce RAG models where the parametric memory is a pre-trained seq2seq model and the non-parametric memory is a dense vector index of W`

### [R4] ✅ 已核验存在 · 对齐：矛盾
- **原始引文**：`[4] Devlin J, Chang M W, Lee K, et al. BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding[C]//NAACL. 2018. arXiv:1810.04805`
- **正文声明**：Devlin et al. (2018) restricted BERT pre-training to strictly unidirectional left-to-right causal attention so that it cannot condition on right context.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=1810.04805](https://export.arxiv.org/api/query?id_list=1810.04805)
- **字段比对**：
  - `title`：一致（引用：`BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding` vs 检索：`BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding`）
  - `year`：一致（引用：`2018` vs 检索：`2018`）
  - `author`：一致（引用：`Devlin J, Chang M W, Lee K` vs 检索：`Jacob Devlin, Ming-Wei Chang, Kenton Lee`）
- **文献原文证据片段**（✅ 原文命中）：> Unlike recent language representation models, BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "venue"],   "claim_alignment": "矛盾",   "evidence_quote": "Unlike recent language representation models, BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly c`

### [R5] ✅ 已核验存在 · 对齐：支持
- **原始引文**：`[5] Brown T B, Mann B, Ryder N, et al. Language Models are Few-Shot Learners[C]//NeurIPS. 2020. arXiv:2005.14165`
- **正文声明**：The Transformer architecture achieves strong zero-shot and few-shot performance by scaling autoregressive language models without gradient updates.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=2005.14165](https://export.arxiv.org/api/query?id_list=2005.14165)
- **字段比对**：
  - `title`：一致（引用：`Language Models are Few-Shot Learners` vs 检索：`Language Models are Few-Shot Learners`）
  - `year`：一致（引用：`2020` vs 检索：`2020`）
  - `author`：一致（引用：`Brown T B, Mann B, Ryder N` vs 检索：`Tom B. Brown, Benjamin Mann, Nick Ryder`）
- **文献原文证据片段**（✅ 原文命中）：> Here we show that scaling up language models greatly improves task-agnostic, few-shot performance, sometimes even reaching competitiveness with prior state-of-the-art fine-tuning approaches. Specifically, we train GPT-3, an autoregressive language model with 175 billion parameters, 10x more than any previous non-sparse language model, and test its performance in the few-shot setting. For all tasks, GPT-3 is applied without any gradient updates or fine-tuning, with tasks and few-shot demonstrations specified purely via text interaction with the model.
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "venue"],   "claim_alignment": "支持",   "evidence_quote": "Here we show that scaling up language models greatly improves task-agnostic, few-shot performance, sometimes even reaching competitiveness with`

### [R6] ⚠️ 存疑 · 对齐：部分支持
- **原始引文**：`[6] Touvron H, Lavril T, Izacard G, et al. Attention Is All You Need[J]. Nature, 2023. arXiv:1706.03762`
- **正文声明**：Touvron et al. (2023) introduced the Transformer architecture in Nature.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=1706.03762](https://export.arxiv.org/api/query?id_list=1706.03762)
- **字段比对**：
  - `title`：一致（引用：`Attention Is All You Need` vs 检索：`Attention Is All You Need`）
  - `year`：**不匹配**（引用：`2023` vs 检索：`2017`）
  - `author`：**不匹配**（引用：`Touvron H, Lavril T, Izacard G` vs 检索：`Ashish Vaswani, Noam Shazeer, Niki Parmar`）
- **幻觉/风险特征**：张冠李戴风险：引用作者与检索文献作者无交集; 发表年份不一致（引用 2023 vs 检索 2017）
- **文献原文证据片段**（✅ 原文命中）：> We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.
- **修复建议**：待作者自行核验：检索到的真实题录为《Attention Is All You Need》（Ashish Vaswani, Noam Shazeer, Niki Parmar, 2017）
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "year", "venue"],   "claim_alignment": "部分支持",   "evidence_quote": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and c`

### [R7] ⚠️ 存疑 · 对齐：支持
- **原始引文**：`[7] Wei J, Wang X, Schuurmans D, et al. Chain-of-Thought Prompting Elicits Reasoning in Large Language Models[J]. 2019. arXiv:2201.11903`
- **正文声明**：Chain-of-thought prompting explores how generating intermediate reasoning steps improves complex reasoning in large language models.
- **检索依据**：`arXiv` / `arxiv_id_exact` — [https://export.arxiv.org/api/query?id_list=2201.11903](https://export.arxiv.org/api/query?id_list=2201.11903)
- **字段比对**：
  - `title`：一致（引用：`Chain-of-Thought Prompting Elicits Reasoning in Large Language Models` vs 检索：`Chain-of-Thought Prompting Elicits Reasoning in Large Language Models`）
  - `year`：**不匹配**（引用：`2019` vs 检索：`2022`）
  - `author`：一致（引用：`Wei J, Wang X, Schuurmans D` vs 检索：`Jason Wei, Xuezhi Wang, Dale Schuurmans`）
- **幻觉/风险特征**：发表年份不一致（引用 2019 vs 检索 2022）
- **文献原文证据片段**（✅ 原文命中）：> We explore how generating a chain of thought -- a series of intermediate reasoning steps -- significantly improves the ability of large language models to perform complex reasoning.
- **修复建议**：待作者自行核验：检索到的真实题录为《Chain-of-Thought Prompting Elicits Reasoning in Large Language Models》（Jason Wei, Xuezhi Wang, Dale Schuurmans, 2022）
- **Spark 原始推理输出**：`{   "metadata_assessment": "partial_mismatch",   "mismatch_fields": ["author", "year", "venue"],   "claim_alignment": "支持",   "evidence_quote": "We explore how generating a chain of thought -- a series of intermediate reasoning steps -- significantly improves the ability of large`

### [R8] ❌ 疑似编造 · 对齐：无关
- **原始引文**：`[8] Chen X, Liu Y. Neural Symbolic Verification for Autonomous Agents[J]. Journal of Artificial Intelligence Research, 2024. doi:10.1145/9999999.8888888`
- **正文声明**：Chen and Liu (2024) demonstrated a 98.4% reduction in agent tool-call errors using symbolic verification.
- **检索依据**：`Crossref` / `doi_exact` — [https://api.crossref.org/works/10.1145%2F9999999.8888888](https://api.crossref.org/works/10.1145%2F9999999.8888888)
- **幻觉/风险特征**：DOI 编号格式合法但 Crossref 未注册（HTTP 404，典型 LLM 编造 DOI 模式）
- **确定性门控拦截**：Gate: 目标文献未核验存在，禁止由模型宣称正文声明被支持
- **修复建议**：建议删除该条目或由作者核对原始文献后重新补录（任何替代题录需作者自行核验）
- **Spark 原始推理输出**：`{   "metadata_assessment": "not_found",   "mismatch_fields": ["title", "author", "year", "venue", "doi"],   "claim_alignment": "未提供正文",   "evidence_quote": null,   "claim_quote": "Chen and Liu (2024) demonstrated a 98.4% reduction in agent tool-call errors using symbolic verifica`

### [R9] ❌ 疑似编造 · 对齐：无关
- **原始引文**：`[9] Zhang W, Miller R. Quantum-Enhanced Prompt Alignment in Clinical LLMs[J]. Nature Medicine, 2025. doi:10.1038/s41591-025-99999-z`
- **正文声明**：Quantum-enhanced prompt alignment eliminates diagnostic variance across clinical cohorts.
- **检索依据**：`Crossref` / `doi_exact` — [https://api.crossref.org/works/10.1038%2Fs41591-025-99999-z](https://api.crossref.org/works/10.1038%2Fs41591-025-99999-z)
- **幻觉/风险特征**：DOI 编号格式合法但 Crossref 未注册（HTTP 404，典型 LLM 编造 DOI 模式）
- **确定性门控拦截**：Gate: 目标文献未核验存在，禁止由模型宣称正文声明被支持
- **修复建议**：建议删除该条目或由作者核对原始文献后重新补录（任何替代题录需作者自行核验）
- **Spark 原始推理输出**：`{   "metadata_assessment": "not_found",   "mismatch_fields": ["title", "author", "year", "venue", "doi"],   "claim_alignment": "未提供正文",   "evidence_quote": null,   "claim_quote": "Quantum-enhanced prompt alignment eliminates diagnostic variance across clinical cohorts.",   "reaso`

### [R10] ⬜ 无法核验 · 对齐：未提供正文
- **原始引文**：`[10] Internal Lab Working Group. 2025 年度内部评测基线白皮书[R]. 内部技术报告, 2025.`
- **检索依据**：`arXiv` / `arxiv_title_search`
- **幻觉/风险特征**：检索边界外或网络受限：Skipped arXiv title search for non-ASCII / Chinese title (out of arXiv scope)
- **修复建议**：处于当前公开检索源边界之外，需人工核查原始馆藏/内部报告
- **Spark 原始推理输出**：`{   "metadata_assessment": "not_found",   "mismatch_fields": [],   "claim_alignment": "未提供正文",   "evidence_quote": null,   "claim_quote": null,   "reasoning_zh": "检索在arXiv范围内因标题为非ASCII/中文而跳过，未找到对应文献条目，因此元数据无法与外部真实文献匹配；手稿正文未提供，无法进行正文层面的核验。" }`

## 4. 合规与人工复核边界声明
- 本报告仅提供技术性元数据检索与文本对齐核验结果，不作「学术不端」定性结论；最终定性由作者、审稿人或学术机构人工判断。
- 本工具未改动用户原始参考文献列表；标注「待作者自行核验」的修复建议须由作者二次确认。