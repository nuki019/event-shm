# 严格负结果与适用边界论文：转向计划

状态：文稿与证据治理计划；不是新实验协议、不是数据访问授权、不是
mechanism-v2.7 的冻结件。本文档不改变 strict-evaluation-v1，也不改变
任何历史结果、失效收据或 v2.6/v2.7 边界。

## 1. 转向决定

当前可投稿的科学对象不是“新的 SoD 机制”，也不是“跨数据集机制复现”，
而是一篇范围受限的严格负结果 / 适用边界评测论文：

> 在冻结的后补偿软件编码与冷启动回放设置中，SoD 事件化没有显示出相对于
> 三个已实现通用 codec 的记录级优势，也没有把健康期校准的两类特征转化为
> 可宣称的运行级报警；该结论只适用于明确声明的数据、任务、实现和指标。

这一路线可以独立于 mechanism-v2.7 推进。不得等待、恢复、重算、改名或
重新包装 D12、D16、MORPHO、v2.x mechanism 用途下的历史 D04/D24 工件或
v2.6 中断物来“补强”本文。strict-evaluation-v1 已冻结的 E7 D04/D24
比较仍是本文的正式证据，二者不得混同。

### 论文类型

- 类型：评测审计 / 可证伪的适用边界论文，不是新方法论文，也不是新数据集
  benchmark 论文。
- 载荷：冻结的评测契约、可复核的全网格负结果、以及不能越过的外推边界。
- 不应宣称：SoD 普遍失效、SoD 的物理失效机制、独立外部复现、部署性能、
  现场 FAR、PoD、能耗、MCU 内存、吞吐或端到端延迟。
- 不应硬造 companion method 或机制解释；当前证据不足以支撑它们。

## 2. 当前证据快照与可用性

| 证据 | 当前状态 | 论文中允许的用途 | 明确禁止的用途 |
| --- | --- | --- | --- |
| protocols/strict_evaluation_v1.json | 冻结；SHA-256 为 9c780aee880c46580978d949c737573d59a9eee7092d9b90fc64a56d99858154 | 划定数据分割、容量、选择规则、指标和非主张 | 用协议替代结果，或在查看结果后改选点 |
| results/e7_strict_codec_benchmark_v1.json | 完整正式输出；SHA-256 为 5b44ff3fbdd30a07101c0c2971455f8ed56bda1e41ba7b050eec2f75896638fa | E7 的逐容量、逐条件 codec 比较 | 普遍 codec 排名、硬件收益或跨结构泛化 |
| results/e8_cold_start_alarm_v1.json | 完整正式输出；SHA-256 为 53228251c6607e01b17288a4723ba60d0201eb0d81f62463820871d684c49e94 | E8 的全阈值网格、false calls/day、new-alarm delay 和 coverage | population PoD、校准 field FAR 或运行级检测保证 |
| src/experiments/audit_strict_evaluation.py | 只读产物一致性审计已通过 | 说明网格、容量和选择描述符的结构一致性检查 | 证明完整执行时间线或排除一切未记录访问 |
| E2--E4、PCA 早期输出和日志 | 历史实现诊断 | 仅作为内部重构背景 | 标题、主表、主图、参数选择或科学结论 |
| mechanism-v2.1--v2.6、D12/D16/MORPHO 及收据 | 历史 / 作废链 | 最多在范围声明中解释其被排除 | 性能、负结果、机制、外部确认或新盲验证 |
| v2.7 合成 contract/checkpoint 测试 | 预访问基础设施测试 | 仅作未来工程治理背景 | 数据资格、机制结果、复现实验或论文证据 |

2026-08-05 的只读审计输出为：

    STRICT-OUTPUT AUDIT PASSED: 4 codecs x 4 capacities;
    2 alarm features x 9 frozen thresholds.

这是一项产物一致性检查，不应被写成独立的科学实验或执行时间线证明。

## 3. 论文问题、结果与边界

### 3.1 可回答的研究问题

- RQ1：在相同逐记录硬字节上限、健康验证期选择和记录级分析下，bounded
  SoD 在 OGW D04/D24 上是否优于 uniform linear、PCA 或 Haar DWT？
- RQ2：仅由健康 March 2021 校准的 dense residual energy 与 Level-A SoD
  count，在完整 April 2021 回放中会产生哪些预先声明的报警结果？
- RQ3：上述两个审计分别允许哪些软件表示和冷启动报警结论，又排除哪些
  泛化、部署和因果解释？

### 3.2 三条可写入摘要、结论和回复审稿人的 Finding

1. Finding 1（codec 边界）：在四个预先声明容量以及 D04、D24 两个
   held-out 条件中，bounded SoD 的记录级 AUC 均低于三个已实现的通用
   codec；因此它不是该冻结比较中的首选 codec。
2. Finding 2（alarm 边界）：在九个 March 派生阈值的完整网格上，两个特征
   均出现非零未来健康期 false calls，且第一次 newly started post-onset
   incident 距标注转变约 42.6--43.1 小时；这不足以支持 operational alarm
   claim。
3. Finding 3（外推边界）：E7 与 E8 是两个不同任务、不同数据源的范围受限
   审计；它们相互补充对“软件表示优势”和“冷启动报警可用性”的否定性证据，
   但不能合并为同一物理机制、独立复现或总体部署结论。

“第一”“全部”“无”只能带上本协议、已实现 codec、已声明容量、D04/D24 或
九阈值网格等限定语。任何脱离这些限定语的表述都需要删除或降级。

## 4. 叙事逻辑骨架

| 环节 | 建议内容 | 直接证据 |
| --- | --- | --- |
| 背景 | 导波 SHM 需要在环境变化下比较残差信息和报警，但稀疏事件流的表面压缩性不等于任务有效性或部署价值。 | 已核实的正文引用；协议中的软件边界 |
| 限制 1 | 匹配样本数而未计时间戳、路径帧和 decoder side information，不能构成公平的硬容量比较。 | strict-evaluation-v1 与 E7 |
| 限制 2 | 将同一 monitoring record 的 paths 当独立样本、或从测试性能选配置，会高估结论强度。 | strict-evaluation-v1 |
| 限制 3 | 在已见的长期月里挑阈值或将单次转变称作 PoD，会把描述性回放误写成运行保证。 | strict-evaluation-v1 与 E8 |
| 核心目标 | 用一个冻结、字节计费、健康期选择、记录级与冷启动分离的评测契约，明确 SoD 事件化在当前公共数据上的可证伪适用边界。 | E7、E8 与协议 |
| 挑战 1 -> 模块 A | 让容量比较真实可比 -> 实际序列化、硬 cap、模型字节单列、全容量报告。 | E7 |
| 挑战 2 -> 模块 B | 防止选择和统计泄漏 -> 日期分割、healthy-only selection、record-level bootstrap。 | 协议、E7 |
| 挑战 3 -> 模块 C | 防止把报警回放误作检测保证 -> March-only calibration、April full replay、new incident 计数和全阈值报告。 | 协议、E8 |
| 贡献 1 | 给出并可复核严格评测契约与边界。 | 方法、实验设置、附录 |
| 贡献 2 | 报告完整 E7 负结果，而非一个挑选容量或样本计数替代物。 | 结果第 1 节 |
| 贡献 3 | 报告完整 E8 负结果与它的统计/物理外推限制。 | 结果第 2 节、讨论 |

四项一致性检查均应在真正改稿前保持通过：每个限制均由核心目标处理；三项
挑战由三个模块逐一处理；每个模块有一个可审计的贡献；没有任何贡献依赖
历史机制链或未完成的新数据源。

## 5. 对现有文稿的具体改写清单

本次只创建计划，不直接修改下列文件。实际改稿必须在独立工作项中进行，
并在改稿前再次核对冻结文件和结果哈希。

| 目标 | 具体改动 | 完成判据 |
| --- | --- | --- |
| paper/main.tex | 保留“Strict Evaluation”主语，标题可改为 “Applicability Limits of Send-on-Delta Eventization for Guided-Wave SHM: A Strict Evaluation”，或保留现标题并在副标题/摘要首句显式说明 applicability limits。 | 标题不暗示新机制、跨结构复现或部署。 |
| 摘要 | 按“评测缺口 -> 冻结契约 -> E7 -> E8 -> 限定结论”重写。E7 和 E8 的数据源与问题分开命名；保留关键数量但不要把 range 说成不确定性区间或最佳操作点。 | 摘要中没有 universal、deployment、PoD、field FAR、energy、latency 或 mechanism claim。 |
| sections/intro.tex | 用三个明确 RQ 取代泛泛的“两个 testable questions”；新增一段说明 E7 和 E8 不是同一机制的两次复现，而是回答两个互补的适用性问题。 | 每个 RQ 在结果节都有唯一对应的表/图和 Finding。 |
| sections/related.tex | 从“方法介绍”扩展为经过文献核验的评测缺口比较：字节计费、选择隔离、记录级分析、冷启动报警的四个维度。没有全文、方法或实验细节的引用不得支撑强比较。 | 新增比较表只包含已逐篇核验的工作；当前 E6 的 metadata-only 状态被消除或相关强主张删除。 |
| 新增 scope/contract 小节 | 在 Method 前或 Method 开头增加“Study contract and claim boundary”：列出 in-scope、out-of-scope、E7/E8 不可合并的事项，以及历史机制链的排除原则。 | 审稿人无需读仓库收据也能判断可写和不可写的结论。 |
| sections/data.tex | 将“单 CFRP plate + reversible discs”和“一个 April labelled transition + 5.5% temperature-support gap”提升为每个数据源的 validity boundary，而非文末一句保留。 | 数据节每个数据源都有独立的可外推性限制。 |
| sections/experiments.tex | 用与 RQ 对齐的小节标题说明预先声明的选择路径；明确 audit 是结构审计而非执行时间线证明。 | 不把代码测试或 audit pass 当作额外科学结果。 |
| sections/results.tex | 以 Finding 1/2 的粗体句开始两个结果小节；表格保留所有容量和阈值范围。新增一句说明 E7 与 E8 不做 pooled score、元分析或因果归因。 | 结果没有选出的“推荐 delta/容量/阈值”。 |
| sections/discussion.tex | 拆为“哪些负结论是实质性的”“哪些替代解释仍未区分”“不能外推什么”“下一步需要什么独立证据”。删除任何暗示 terminal-hold、D12/D16/MORPHO 是性能原因或补充复现的内容。 | 讨论把实验失败与协议/runner 作废严格分开。 |
| sections/conclusion.tex | 结论只复述三条 Finding 和未来证据门槛；未来工作写成条件，而不是承诺已存在的 successor 数据。 | 结论与摘要、协议和 EVIDENCE_MAP 完全一致。 |
| paper/EVIDENCE_MAP.md | 改稿时补一张“可用、仅工程、历史排除”的证据谱系表，并记录结果哈希与审计范围。 | 每个正文数字能追溯到 E7/E8 JSON；无历史数据渗入。 |

## 6. 推荐的主文结构与图表

建议将正文组织为七部分，而非将它包装成方法优越性论文：

1. Introduction：评测盲点、三个 RQ、范围受限的贡献。
2. Evaluation Gap and Claim Contract：何谓公平字节计费、选择隔离和
   冷启动计数；明确非主张。
3. Frozen Evaluation Design：数据分割、codec contract、报警 contract。
4. Results for RQ1：E7 的全容量表与现有 codec 图，随后是 Finding 1。
5. Results for RQ2：E8 的全阈值表与现有报警图，随后是 Finding 2。
6. Applicability Boundary and Threats to Validity：数据、任务、统计、
   实现和部署五层边界，随后是 Finding 3。
7. Related Work and Conclusion：仅使用可核验引用，结论不超出前三个
   Finding。

推荐补充但尚未创建的非经验图表：

- 图 1：同一残差记录的“匹配样本数比较”与“实际包字节 + healthy-only
  selection + record-level outcome”对照；它解释评测缺口，不展示未审计
  数值。
- 表 1：Claim-to-evidence matrix。列出每条主张、证据文件、分析单位、
  可外推边界和禁止结论。
- 表 2：保留现有 E7 的 4 x 4 x 2 全量主表。
- 表 3：保留现有 E8 的 2 x 9 全量阈值结果或完整范围，并在补充材料放逐点。
- 附录 A：strict-evaluation-v1 的规范化摘要、结果 SHA-256 和只读 audit
  命令/输出。
- 附录 B：所有 E7/E8 输出字段的可复核定位；不要把原始波形或历史 v2.x
  中断物伪装成补充验证。

## 7. 可直接采用的措辞护栏

| 场景 | 允许写法 | 不允许写法 |
| --- | --- | --- |
| E7 | “在本协议的四个容量、D04/D24 和四个已实现 codec 中，bounded SoD 未领先。” | “SoD 比传统 codec 差”或“SoD 普遍无效”。 |
| E8 | “该 March-calibrated April replay 未支持 operational alarm claim。” | “检测失败”“PoD 为零”或“现场 FAR 已校准”。 |
| 统计 | “record-level bootstrap interval 描述这些条件内的重采样不确定性。” | “证明跨结构显著性”或“总体置信区间”。 |
| 温度 | “温度匹配是预先声明的诊断，且 April 有 5.5% support gap。” | “已控制所有环境混杂”。 |
| 机制历史 | “历史 mechanism 链不参与本文结论。” | “D12/MORPHO 证实 SoD 的物理失败机制”。 |
| 工程 | “post-compensation software coding/replay。” | “ADC 节能”“MCU 可部署”“实时报警”。 |

## 8. 改稿前后的硬门槛

### 改稿前

1. 将 strict-evaluation-v1、E7 JSON、E8 JSON 的 SHA-256 写入一个只读的
   提交/补充材料清单，并再次运行只读 audit。
2. 对每一篇新增 related-work 文献确认全文或可信一手来源；不能以 Crossref
   元数据替代方法、数据或性能比较。
3. 对每一张新表和每一个数字建立到 E7/E8 JSON 的字段级追溯；无法追溯则
   从正文删除。
4. 确认任何机制 v2.x 文件、MORPHO 文件和 E2--E4 历史日志均未进入主图、
   主表、数字、参数选择或结论。

### 投稿前

1. 在保留的正式结果文件上再次通过只读 strict audit；明确它的审计范围。
2. 从干净环境按文档编译 PDF，逐页检查图、表、引用、页码和 DOI。
3. 运行全套单元测试；将测试通过与科学结论区分开写。
4. 审阅标题、摘要、图注、讨论、结论和 cover letter，逐项扫描第 7 节的
   禁止术语及其同义改写。
5. 将原始结果 JSON、协议、脚本版本和结果哈希作为可访问的补充证据安排；
   若受数据许可限制，清楚说明可复核路径而不是虚称开放数据包。
6. 只有在以上条件均满足时，才能称为“严格负结果/适用边界论文已准备投稿”；
   它不需要 mechanism-v2.7 完成。

## 9. 不触碰的边界

- 不下载、打开、缓存或评分新的候选波形。
- 不修改 strict-evaluation-v1、E7/E8 JSON、历史结果、机制冻结件或失效收据。
- 不恢复或重跑 v2.6 D16/MORPHO，也不把其任何局部日志改称新的结果。
- 不用 E2--E4、旧 PCA 或早期长时回放来选择新的容量、阈值或 SoD 参数。
- 不因为论文转向而降低 v2.7 的新源资格、外部锚、冻结和审计要求。

## 10. 当前完整性判定

该论文路线的现有 E7/E8 科学证据足以支撑“严格负结果与适用边界”的窄结论，
但尚不足以支撑机制论文或高外推性 SHM 论文。当前最大的文稿风险不是负结果
本身，而是将严格的本地审计误写成机制、复现或部署结论；上述结构和护栏用于
消除这一风险。
