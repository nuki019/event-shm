# MSSP 投稿导向交接文档

**快照日期：2026-08-04（Asia/Shanghai）**  
**当前结论：MSSP 投稿 `NO-GO`。**

本项目已经形成一套可复现、泄漏受控的 SoD 严格负结果审计；它可以支撑一篇范围明确的评测/审计型论文，但目前不足以支撑以 *Mechanical Systems and Signal Processing*（MSSP）为目标的机制论文。最关键的原因不是结果“负”，而是机制确认链在 v2.5 的 D12 一次性运行后被审计判定为无效：后续 D16 和 MORPHO 均未启动，不能将当前产物包装成跨数据集机制证据。

本文件将“已验证结果”“探索性诊断”“作废证据”和“未来工作”严格分开。任何接手者都应先阅读本文件与相应协议，再决定是否设计新的 successor；不得恢复已暂停的 v2.5 自动任务。

## 1. 一页决策摘要

| 决策问题 | 当前判断 | 证据/原因 |
| --- | --- | --- |
| 现在能否投 MSSP？ | **不能** | 没有通过审计的机制确认、没有有效外部复现，且仅有一块 CFRP 板与一次长期转变的严格证据。 |
| 严格 E7/E8 是否可用？ | **可用，但限于负结果审计** | `strict_evaluation_v1` 已冻结；E7/E8 均完整，边界清楚。 |
| v2.5 D12 是否可作论文结果？ | **不可用** | D12 一次性结果的终端保持命题审计失败；它仅是作废证据。 |
| D16/MORPHO/COQTEL 是否已完成独立验证？ | **否** | D16 与 MORPHO 未进入 waveform scoring；COQTEL 仅有 metadata-only gate，且无官方二元切点。 |
| 当前论文适合怎样定位？ | **严格评测/负结果审计** | 贡献是防止字节计费、数据泄漏、指标误用和事后选择造成假阳性，而不是提出优于现有 codec 的 SoD 方法。 |
| v2.6 是否可自动启动？ | **不可** | 新的容量感知 terminal-hold 契约、独立数据角色和确认门槛必须先由 successor 协议冻结；D12 不能重跑或重新包装为盲确认。 |

## 2. 可复核快照与版本边界

| 工件 | 当前状态 | SHA-256 |
| --- | --- | --- |
| [`protocols/strict_evaluation_v1.json`](protocols/strict_evaluation_v1.json) | 冻结且为当前严格评测唯一论文级协议 | `9c780aee880c46580978d949c737573d59a9eee7092d9b90fc64a56d99858154` |
| [`results/e7_strict_codec_benchmark_v1.json`](results/e7_strict_codec_benchmark_v1.json) | 完成的 E7 全网格结果 | `dda083e903837f42aea9452ccf75862552c610b07db7fd63634a5d5990de8d3b` |
| [`results/e8_cold_start_alarm_v1.json`](results/e8_cold_start_alarm_v1.json) | 完成的 E8 全阈值网格结果 | `62a59de1f3aa97d27b1489f894304048cf088895144390526d62eae7ad7447c1` |
| [`protocols/mechanism_v2_5_invalidation_receipt.json`](protocols/mechanism_v2_5_invalidation_receipt.json) | v2.5 机制确认正式作废收据 | `71c96b4444f951f2c4bdfc181cf0c05847ce62d2f03434f2daff55d2559308a5` |
| [`paper/main.pdf`](paper/main.pdf) | 本地已编译论文 PDF；不能代替投稿前的最终构建验收 | `d77bc12ad3e7c190373493fd31c26bd810b1b77373ae61a1f70943f7d037e404` |

不可变边界如下：

- `strict_evaluation_v1`、E7、E8，以及历史 OGW D04/D24 的发现性证据均不得修改或用于未来选择。
- mechanism v2.1--v2.5 均是历史/作废链的一部分，不能授权 successor 的数据访问、缓存、schema 或结论复用。
- v2.5 的 D12 已被一次性运行消耗；其输出只能解释作废原因，不能被重跑、调参、择优或改称为盲确认。
- COQTEL 只通过了结构元数据门槛，未冻结官方健康/腐蚀二元切点；不得评分，也不得将 v2.5 作废伪装为 COPV schema 失败。

## 3. 当前进度统计

### 3.1 严格评测轨

| 模块 | 预声明单元 | 完成量 | 论文资格 | 说明 |
| --- | ---: | ---: | --- | --- |
| E7 硬容量 codec 比较 | 4 容量 × 4 codec × 2 损伤条件 = 32 codec-condition-capacity 单元 | 32/32 | 有，限于严格负结果 | 健康训练/验证/测试日期分离，真实序列化字节计费，记录级 AUC。 |
| E8 冷启动回放 | 2 特征 × 9 个 March 派生阈值 = 18 单元 | 18/18 | 有，限于描述性报警审计 | 完整 April 先评分后读标签；不报告 PoD 或 field FAR。 |
| 严格协议与结果测试 | 本次复核 | 41/41 通过 | 工程验证，不替代科学外推 | `python -m unittest discover -s tests -v`，2026-08-04。 |

E7 的四档每记录上限均已完整报告。bounded SoD 的 D04/D24 记录级 AUC 分别为 0.535--0.552 / 0.546--0.581；每一容量与两个条件下，它均低于 uniform linear、PCA 和 Haar DWT。以 Haar 为各行的最高点为例：

| 每记录容量 (B) | SoD D04 | Haar D04 | SoD D24 | Haar D24 |
| ---: | ---: | ---: | ---: |
| 2,048 | 0.552 | 0.965 | 0.554 | 0.923 |
| 4,096 | 0.535 | 0.963 | 0.558 | 0.917 |
| 8,192 | 0.545 | 0.962 | 0.581 | 0.909 |
| 16,384 | 0.544 | 0.960 | 0.546 | 0.903 |

E8 使用 March 2021 的 15,554 条健康记录作唯一校准源，并完整回放 April 2021 的 15,069 条记录。April 标注转变在第 8,401 条记录；这只是一个观察到的转变。九个冻结阈值上：

| 特征 | false calls/day | 新启动报警延迟 (min) | 转变后记录覆盖率 |
| --- | ---: | ---: | ---: |
| Dense residual energy | 0.897--5.144 | 2556.2--2584.8 | 2.6--25.6% |
| Level-A SoD event count | 0.897--4.964 | 2556.2--2584.8 | 3.0--25.6% |

这些数值支持“当前两类报警不构成 operational alarm”的范围内结论；不支持 population PoD、校准 field FAR、硬件功耗或实时部署结论。

### 3.2 机制研究轨

| 模块 | 计划量 | 当前状态 | 可用于 MSSP 机制结论？ |
| --- | ---: | --- | --- |
| v2.5 source receipt | D12、D16、MORPHO、COQTEL 共 4 个 | 4/4 完成 | 仅完整性证据 |
| metadata-only schema gate | MORPHO、COQTEL 共 2 个 | 2/2 通过 | 仅 schema 资格；COQTEL 仍不能二元评分 |
| 一次性确认 | D12、D16、MORPHO 共 3 个 | D12 运行 1/3；D16/MORPHO 0/3 | 否 |
| 结果审计 | 3 个确认结果 | 0/3 通过 | 否 |

v2.5 的 D12 结果有 32 个 capacity/delta grid rows、64 条机制 probe、1,536 条控制注入记录，但其 required audit 报错：`8192/1 terminal_hold did not pass`。所有 8 个失败项均在 8,192-byte 容量，且呈现“首轨迹未饱和、次轨迹饱和、序列化 payload 和解码结果相同”的结构。这说明冻结 probe 的饱和前提未在高容量下成立；不能把匹配 payload 本身误称为通过的 terminal-hold 命题。

因此，v2.5 是**协议/runner 契约失败**，不是“阈值碰撞与包截断导致 SoD 失败”的科学发现。详见 [`protocols/mechanism_v2_5_invalidation_receipt.json`](protocols/mechanism_v2_5_invalidation_receipt.json)。

### 3.3 探索性与不可升级结果

| 工件组 | 可做什么 | 明确不能做什么 |
| --- | --- | --- |
| E2--E6、PCA、早期长时回放日志 | 实现诊断、图形原型、后续假设来源 | 不能选 SoD 阈值/容量；不能作为论文主结果或独立验证。 |
| E4 April 内部描述 | 说明事件计数的时间行为 | 无独立健康校准月时，不能作为部署 FAR、延迟或 PoD。 |
| E7/E8 smoke 文件 | 验证代码能运行 | 不能进入表格、选择或科学结论。 |
| v2.5 D12 JSON/cache | 定位冻结契约失败 | 不能报告机制、性能或负结果结论。 |

## 4. 面向 MSSP 的论文定位审计

### 4.1 现在的稿件是什么，而不是什么

当前稿件题为 *A Strict Evaluation of Send-on-Delta Eventization for Guided-Wave Structural Health Monitoring*，实质是**评测/审计型负结果论文**，并非新的 SHM 方法论文。它的可检验问题是：在真实字节上限、健康期选择和记录级统计下，SoD 是否仍具 codec 竞争力；以及 March 校准的报警在 April 会产生什么结果。

这一定义是诚实的，但对 MSSP 的风险很高：文章目前没有新的信号处理机制、没有已审计的跨结构机制复现，也没有从负结果导出的可验证设计原则。把“严格”本身包装为方法创新，或把单板负结果外推为 SoD 普遍无效，都会削弱可信度。

### 4.2 评测论文五支柱（适配）

| 支柱 | 当前状态 | MSSP 风险/缺口 |
| --- | --- | --- |
| Research gap | 部分覆盖 | 已清楚指出未计费 payload、路径伪重复、标签泄漏和事后阈值选择；但与现有 SHM codec/事件化评测的系统性文献比较不足。 |
| Construction pipeline | 部分覆盖 | 日期分离、健康期拟合、真实序列化与 cache manifest 可复现；但不是多结构、多材料的构建管线。 |
| Evaluation framework | 强（限本地范围） | 4 档容量、记录级 bootstrap、温度配对、全阈值报警网格完整；但外部独立组、重复实验和损伤多样性不足。 |
| Empirical findings | 强但窄 | 负结果清晰；仅涵盖一块 CFRP 板的 D04/D24 与一次 April 转变，无法建立一般机制边界。 |
| Companion mechanism/method | 缺失且不应虚构 | 目前没有机制模型、补救算法或已验证的任务条件；不能把未审计的 v2.5 当作补充方法。 |

该五支柱审计表明：严格评测适合做当前论文的核心，但它尚不是 MSSP 级机制研究的充分证据链。

### 4.3 未来 MSSP 机制论文的逻辑骨架（条件性，不是现有贡献）

建议 v2.6 以后将目标明确为“受硬包约束的 level-crossing eventization 在何种可验证条件下发生信息碰撞或截断”的**机制研究**，而非继续扩大 codec leaderboard。

| 环节 | 条件性内容 | 当前状态 |
| --- | --- | --- |
| 背景 | 导波 SHM 需要在信息预算下保留损伤相关表示，但事件流不是通用 waveform codec。 | 可由 E7/E8 支撑问题动机。 |
| 限制 1 | 样本数匹配或未计费时间戳的比较不能说明真实受包约束信息损失。 | 已由 strict protocol 处理。 |
| 限制 2 | 单一 AUC 无法区分量化碰撞、cap 截断和评分头失配。 | v2.5 计划过，但无有效确认。 |
| 限制 3 | 单板/单转变无法建立跨 campaign 的机制边界。 | 未解决。 |
| 核心目标 | 用预注册、容量感知且可审计的 probe，分解 eventization 在不同容量/扰动条件下保留与丢失的信息。 | 需要新的 v2.6 冻结。 |
| 挑战 1 → 模块 A | 每个 capacity/delta 都必须实际满足 probe 的 cap 前提。→ capacity-aware terminal-hold generator 与独立 auditor。 | v2.5 在此失败。 |
| 挑战 2 → 模块 B | 避免用损伤标签选择事件特征或条件。→ 健康期拟合的固定诊断、全网格报告。 | 设计已有，尚未有效确认。 |
| 挑战 3 → 模块 C | 机制必须跨独立 group/campaign 检验。→ 预定义的 group split、外部确认和 group bootstrap。 | 未完成。 |

四项一致性检查的当前结论：

1. 限制 → 核心目标：**部分通过**；严格评测能动机化机制研究，但还缺真实外部机制差异。
2. 核心目标 → 挑战：**通过（设计层面）**；三项挑战均由目标自然导出。
3. 挑战 → 方法模块：**失败（证据层面）**；模块 A 的冻结契约在 8,192 B 失效，B/C 未完成确认。
4. 方法 → 贡献：**失败（投稿层面）**；当前没有可声明的机制贡献或跨数据集发现。

因此，v2.6 前任何 “Mechanisms and Limits” 标题都只能作为计划，不能进入 MSSP 投稿版本。

## 5. MSSP 投稿的关键不足（按优先级）

### Critical：必须解决

1. **机制确认链无效。** v2.5 的唯一评分 D12 未通过冻结审计；D16 与 MORPHO 未运行。任何基于 v2.5 的机制、分离能力、控制注入或外部复现说法均不可用。
2. **外部/独立泛化不足。** E7 仅一块 CFRP 板、两个可逆 disc 条件；E8 仅一次 April 标注转变。MSSP 级一般机制主张至少需要预先定义的独立 group/campaign 证据，不能以路径数替代独立样本数。
3. **D12 已不再是盲确认资源。** 它不能重跑或用于选择。新的 v2.6 必须在访问前重新决定未受污染的数据角色与最低证据门槛。
4. **投稿贡献尚非机制性。** 当前文章证明的是审计后 SoD 不占优，而非为什么、何时、以何种可重复条件失效。没有这一层，MSSP 的创新性与广泛兴趣风险很高。

### Major：应在冻结 successor 前解决

1. **机制 probe 的集成测试缺口。** 虽然本次 41 个单元测试均通过，但没有测试覆盖“每个冻结 capacity/delta 的两条 terminal-hold 轨迹均实际饱和”这一端到端不变量。v2.6 应在任何 waveform access 之前对此全网格作独立测试。
2. **相关工作过薄。** `paper/refs.bib` 有 13 条条目，但当前正文仅有 9 个引用命令、涉及 5 个条目。需要补足 SHM 温度补偿、导波压缩、稀疏/事件表示、损伤检测统计与可重复性评测的系统性比较，并逐条核验。
3. **比较范围有限。** 当前仅比较 bounded SoD、uniform、PCA、Haar；这足以支持范围内的 codec 排序，不能宣称已覆盖任务特异、学习型或自适应 dense/event 方法。
4. **统计外推有限。** E7 的 bootstrap 不等于跨结构置信；E8 的单次转变不等于 PoD。v2.6 的分析单位必须是 record/campaign/block，重复波形和路径不可随机拆分。
5. **论文尚未变成机制叙事。** 当前图表主要展示 codec AUC 与报警贸易关系，缺少量化碰撞、cap 保持、信息分解及跨 group 复现的证据图。

### Minor：投稿前完成

1. 采用 MSSP 对应的正式投稿模板、图表规格、数据/代码可用性、作者贡献与利益冲突声明；当前 `article` 文档类只是工作稿。
2. 给论文加入一张直观的运行样例图，说明“未计费比较”与“硬包约束表示”的差异；对机制稿则需要单独的碰撞/截断示意图。
3. 对所有主图实施最终可读性、字体、单位、颜色无障碍和单栏缩放检查。
4. 在提交前建立干净、可追溯的代码快照与数据获取清单；GitHub 不应存放 53.6 GB/26.8 GB 原始档案或临时 cache。

## 6. MSSP go/no-go 门槛

在以下全部完成前，不建议向 MSSP 投稿：

- [ ] 写出并测试 mechanism-v2.6 的 capacity-aware terminal-hold 契约；每一个冻结 capacity/delta 必须由独立审计器验证饱和前提，或预注册 `not_applicable` 与独立的 saturation-only 命题。
- [ ] v2.6 的协议、manifest、result schema、runner、auditor 和测试均在**任何新的 waveform scoring 前**冻结并互相哈希绑定。
- [ ] 明确 D12 已退休；在访问前定义新的、尚未使用的确认 source 及其数据角色。不能为追求结果而替换数据集。
- [ ] 至少完成预注册的一次同类确认和一次外部 group/campaign 确认，二者都通过审计；结果无论正负均全量报告。
- [ ] 对所有容量、delta、固定事件诊断、控制注入、重构指标和排除原因全网格报告，不从结果中选择最优条件。
- [ ] 用记录/块/campaign 为分析单位报告 AUC、group bootstrap、配对差异和 coverage；不报告 PoD、field FAR、功耗、实时或硬件部署结论。
- [ ] 完成与现有 SHM/压缩/事件化文献的可核验对照，形成机制贡献而不仅是“更严格的 benchmark”。
- [ ] 将最终论文、协议、代码和结果收据打成可复现提交快照；原始数据以官方 DOI/manifest 指向，而非混入代码库。

若这些门槛无法满足，建议保留当前 E7/E8 作为高质量、范围受限的严格负结果审计，转向更匹配评测型贡献的期刊，而不是以 MSSP 名义夸大机制或泛化性。

## 7. 当前论文的可保留内容与禁止内容

### 可以保留

- `strict_evaluation_v1` 的数据泄漏、字节计费、记录级单位和预先选择控制。
- E7 的“在四档硬容量、两种损伤条件、四类 codec 下 SoD 不领先”的范围内负结果。
- E8 的完整冻结报警网格，以及其 false calls/day、new-alarm delay、coverage 的描述性结果。
- 明确的非主张：无 MCU、能耗、实时、field FAR、population PoD、跨材料/跨结构泛化结论。

### 必须禁止

- 将 E2--E6、早期 PCA 或 E4 内部描述升级为确认结果。
- 将 v2.5 D12 输出视为机制负结果，或用它选择 v2.6 的特征、阈值、容量、结论强度。
- 启动 D16/MORPHO 来“补齐”一个已失效的 v2.5 协议。
- 因 COQTEL 没有二元切点而启用 COPV；这不是 schema gate 失败。
- 报告 PoD、field FAR、功耗、实时、MCU 或部署能力。

## 8. 交接时的安全操作顺序

1. 先只读核验本文件第 2 节的 SHA-256、`strict_evaluation_v1` 和 `mechanism_v2_5_invalidation_receipt.json`。
2. 保持 `continue-shm-mechanism-v2-1-confirmation` 自动任务暂停；不要启动下载、哈希、E9 或审计写入者。
3. 若决定做 v2.6，先单独落盘设计决定：问题、未污染数据源、capacity/delta 网格、probe 的 `passed/not_applicable` 逻辑、统计单位、go/no-go 门槛。
4. 在冻结与合成/结构测试均通过前，不打开新的波形值；协议缺陷一旦发现，立刻作废而不修补。
5. 使用 `C:\Users\wfy\.conda\envs\shm\python.exe -m unittest discover -s tests -v` 复核实现；本快照的结果是 **41 tests, OK**，但这不解除第 5 节列出的端到端测试缺口。

## 9. GitHub 同步状态与建议

截至本快照，远端 `https://github.com/nuki019/event-shm` 的 `master` 与本地基线同为 `9f6124cd50e37440286fb3937df1a637a47da45e`（旧的 C3 提交）。工作树包含 14 个已跟踪文件的未提交修改（443 行新增、421 行删除），以及协议、测试、机制 runner、日志与外部数据目录等大量未跟踪项；它**不是**可直接整体推送的干净快照。

安全同步原则：

1. 先用 `gh api` 写入本交接文档的最小范围远端快照，确保当前风险和作废边界不会丢失。
2. 不把 `data/external/`、原始压缩包、cache、临时日志或无效结果推送到 GitHub。
3. 后续再按“严格评测代码/协议/测试”“论文源文件与图”“结果收据与 manifest”三批逐文件审查、提交和哈希验收；不要使用 `git add .`。
4. 远端提交后需记录 GitHub commit SHA，并在干净的后续工作树中快进同步；不要对当前脏工作树执行 `reset --hard`、`checkout --` 或盲目 merge。

## 10. 关键入口

- [`README.md`](README.md)：严格评测范围、可复现实验入口与非主张。
- [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md)：数据、协议、测试与结果边界。
- [`paper/EVIDENCE_MAP.md`](paper/EVIDENCE_MAP.md)：论文主张到结果工件的映射。
- [`paper/PAPER_BLUEPRINT.md`](paper/PAPER_BLUEPRINT.md)：现有严格评测稿的逻辑蓝图。
- [`protocols/strict_evaluation_v1.json`](protocols/strict_evaluation_v1.json)：唯一的当前论文级严格协议。
- [`protocols/mechanism_v2_5_invalidation_receipt.json`](protocols/mechanism_v2_5_invalidation_receipt.json)：必须优先遵守的 v2.5 停止边界。
- [`src/experiments/e7_strict_codec_benchmark.py`](src/experiments/e7_strict_codec_benchmark.py) 与 [`src/experiments/e8_cold_start_alarm.py`](src/experiments/e8_cold_start_alarm.py)：严格实验实现。
- [`tests/`](tests)：协议、泄漏、序列化、group split 与 pre-access 不变量测试。

