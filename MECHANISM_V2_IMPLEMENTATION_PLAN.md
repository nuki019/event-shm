# mechanism-v2 实施计划（冻结前草案）

> 状态：**仅计划，尚未启动。** 该文件不构成协议冻结、数据访问授权或实验启动。除本文件外，不创建协议、不下载/解包/读取新数据波形、不运行编码或评分。
>
> 目标：将工作从“SoD 在既有 benchmark 上的负结果审计”转为“硬包约束下 level-crossing eventization 丢失或保留导波损伤信息的可证伪机制研究”。所有结果均以预注册协议、数据角色和一次性确认边界为准。

## 1. 不可变边界

1. `protocols/strict_evaluation_v1.json`、E7、E8 及其已有结果保持原样；不得重新计算、替换或混入 mechanism-v2 的确认结果。
2. E7 的 OGW D04/D24 只可作为已观察的**机制发现集**。它们不能选择 capacity、事件特征、delta、统计量、阈值或结论强度，也不能作为新的确认结果。
3. 铝板 `2021_03 -> 2021_04` 仍仅是既有 E8 冷启动证据。`2021_06`、`2022_07`、`2022_08` 不具健康到损伤资格，禁止重包装成确认实验。
4. 不写入 MCU、ADC、能耗、实时采集、端侧延迟、现场 FAR、PoD 或部署结论。软件回放只证明表示/编码行为。
5. 记录（record）是分析单位；路径、接收器和重复波形只组成该记录，绝不成为独立样本。任何跨日期、block、campaign、重复波形的泄漏均为结果无效。

## 2. 冻结前须写入的协议资产

后续实施的第一项工作是新建而非修改下列资产；完成 SHA-256 记录并人工确认后，才允许接触新数据波形。

- `protocols/mechanism_v2.json`：协议版本、代码版本、随机种子、数据角色、容量、delta、特征、聚合头、统计方法、排除规则与一次性确认声明。
- `protocols/mechanism_v2_result_schema.json`：全部结果 JSON 的必需字段、类型、枚举值及拒绝条件。
- `protocols/mechanism_v2_data_manifest.json`：官方 URL/DOI、许可、官方 MD5、归档文件名、下载收据、数据 SHA-256、角色和允许的读取阶段。
- `src/experiments/audit_mechanism_v2.py`：只读审计器，验证协议/数据哈希、数据角色、group split、完整网格、cap 证据、排除原因和选择路径。

协议必须明确以下固定值，且不得在看到 D12/D16 或外部结果后修改：

- 沿用 E7 的训练/验证日期、量化器、序列化字节计费与四档等效容量；所有数据集同时报告实际 `bytes/record` 与等效 `bits/original sample`，不按样本数匹配。
- 全部预声明 delta、容量、事件特征、波形指标、频带、控制注入网格、聚合头、bootstrap 重采样次数、置信区间和配对比较。
- “global”与“max-path”两个事件域头均固定输出；不得因 AUC、显著性或视觉效果选择其中一个。
- 训练、验证、确认、schema 失败和排除的显式 data-role 枚举；发现集永远不得进入选择路径。

## 3. 数据角色、资格门槛与不可替换规则

| 数据 | 固定角色 | 允许用途 | 启动前/读取前硬门槛 |
| --- | --- | --- | --- |
| OGW D04/D24 | 发现集 | 图示与机制假设生成 | 不参与任何参数或结论选择 |
| OGW D12/D16 | 同板盲确认 | 一次性同域确认 | 冻结后下载，官方 MD5 校验通过，归档和解包内容留存 SHA-256 收据 |
| MORPHO (`10.5281/zenodo.14627730`) | 主第三数据集 | 跨结构确认 | ReadMe/HDF5 必须有可排序 fatigue block、健康阶段和退化/失效阶段字段；同一 block 的 10 次重复不得跨 split |
| COQTEL (`10.5281/zenodo.14193336`) | 材料独立复现 | 独立 campaign 复现 | 波形读取前，HDF5 必须有官方时间或腐蚀阶段字段及两次实验标识；相邻 10 秒波形不得作独立样本 |
| COPV | schema 失败备选 | 仅替换未通过元数据门槛的数据集 | 只有 MORPHO 或 COQTEL 在任何信号评分前 schema 失败才可启用；记录触发原因，之后不得因性能替换 |

外部数据一律先做元数据/schema 审计，后读取波形。MORPHO 按连续 fatigue block 划分训练、验证、测试；COQTEL 以两次实验为 campaign group，并按时间顺序处理。任何缺少所需官方字段的数据集都以 `schema_ineligible` 记录，不评分、不替换、不作“失败结果”。

## 4. 实现工作包

### WP1：可审计编码器统计与序列化一致性

在不改变冻结 E7 实现/结果的前提下，为 mechanism-v2 新建独立封装，逐 record 暴露：

- 量化 level、事件时间、事件幅值变化、末事件位置；
- 封包事件数/字节数、cap 饱和标记、cap 后末值保持长度与比例；
- 原始与反序列化/重构表示的一致性收据。

验收：事件统计可由序列化 payload 复算；bytes 计费与 payload 长度一致；硬 cap 后不会再传递后续波形变化。

### WP2：两条表示层命题与损失分解

对每一容量和每一个预声明 delta，固定计算并完整输出：

1. **量化/level-crossing collision**：构造小于边界的连续扰动，验证其可映射为相同事件流；
2. **包截断/terminal hold**：构造 cap 后差异，验证后续差异被末值保持截断；
3. **头失配**：在同一固定输入下区分编码表示损失与 waveform reconstruction/scoring-head 引入的损失。

全量指标（不择优展示）：waveform correlation、相对误差、峰值互相关时延、预声明频带保留、cap 后保持比例、事件密度，以及三类损失分量。所有图表和 JSON 均保留完整容量 × delta 网格。

### WP3：固定事件域异常诊断

实现非事后优化分类器的预声明诊断：事件密度、带符号总变差、时间质心、时间离散度、末段保持比例。

- 只以健康训练记录拟合稳健中心/尺度；不得使用确认标签、测试分位数或跨 split 归一化。
- 分别报告固定 `global` 和 `max-path` 聚合分数，不允许选择更优头。
- 不报告将单次转变误写为 PoD/field FAR 的量；如包含已有 E8 语境，仅报告 false calls/day、new-alarm delay、coverage。

### WP4：健康训练上的控制注入

在冻结网格的健康训练记录上生成两类无标签表示探针：

- 稀疏、突变、较大幅度的扰动；
- 平滑、低幅度、相位型/亚阈值扰动。

该工作包只检验表示机制（碰撞、事件保留、截断），不带真实损伤标签、不声称诊断性能或部署效益。注入随机种子、幅值、持续时间、位置和相位网格全部写入协议和结果。

### WP5：预注册一次性确认与统计

在 D12/D16 和每个通过 schema 门槛的外部数据集上按冻结配置执行一次。按 monitoring record 聚合，按 campaign/block 计算：

- AUC 及 group bootstrap 区间；
- 预声明方法间配对差异；
- 全部容量、特征、聚合头、控制网格和 cap 证据。

该阶段不得根据确认结果改 delta、容量、特征、指标、分割或数据集。若代码缺陷使结果无效，必须发布原因、作废收据、协议修订版本和新的确认边界，而不是静默重跑。

## 5. 结果结构与自动审计

每个新结果 JSON 必须包含：

```text
protocol_id + protocol_sha256
code_revision
data_manifest_sha256 + archive/content hashes
data_role + inclusion_or_exclusion_reason
official schema fields observed
group_split manifest + disjointness receipt
all capacities / deltas / features / heads / injection grid
byte-accounting and cap evidence
complete metrics and group-level intervals
label-access and selection-path receipt
```

审计器至少拒绝下列情况：缺字段或未知协议哈希；发现集进入选择；group overlap；缺少任一预声明网格单元；只输出一个聚合头；没有 cap 证据；先读波形后判定 schema；损坏/截断 JSON；用 path/repeat 代替 record 作为独立样本。

## 6. 测试、论文与文档交付

测试新增覆盖：

- 事件统计与 payload/字节数的一致性；
- collision 和 terminal-hold 两条命题；
- 健康训练拟合与无标签选择路径；
- group/block/campaign 不交叉；
- MORPHO、COQTEL 与 COPV 的 HDF5 schema 门槛；
- 完整容量/feature/head/injection 网格；
- 损坏结果、缺失 cap 收据或非法数据角色的拒绝。

论文和说明文件只在一次性结果完成后更新：

- 标题转为机制导向，例如 *Mechanisms and Limits of Level-Crossing Eventization for Guided-Wave SHM*；
- 压缩“strict/audit”措辞，将核心篇幅转为表示命题、因果分解、事件原生诊断和跨数据复现；
- 将发现、确认、schema 不合格、软件回放与硬件证据分别标记；
- 重新编译并视觉检查 PDF，且在文中保留全部负/正结果而非仅选有利结果。

## 7. 决策规则与完成标准

结果解释在协议中预先限定为双向：

- 若事件原生分数在确认集恢复分离能力：结论为“SoD 不是通用 waveform codec，但可能保留特定事件任务信息”。
- 若仍失败且 collision/截断证据完整：结论为“阈值碰撞与包截断共同造成信息损失”。

两种情形都完整报告，禁止预设负结论。高水平机制论文的 go/no-go 是：D12/D16 **及至少一个外部数据集**均通过预注册 schema 门槛并完成一次性确认。若未满足，只保留为严谨的负结果审计，面向常规 SHM 期刊；不得以“机制论文”夸大投稿定位。

## 8. 实施顺序与预估工期（授权启动后）

| 阶段 | 依赖 | 预计工作量 | 产物 |
| --- | --- | ---: | --- |
| P0：冻结协议/manifest/schema | 本计划确认 | 0.5–1 天 | 三个冻结 JSON、哈希与审计基线 |
| P1：编码器统计、命题与单元测试 | P0 | 1–1.5 天 | 独立 mechanism-v2 模块与测试 |
| P2：事件诊断、控制注入、结果 schema 审计 | P0–P1 | 1–1.5 天 | 固定网格、无标签路径、审计器 |
| P3：D12/D16 下载/MD5/一次性确认 | P0–P2 | 0.5–1.5 天 + 下载时间 | 确认收据与完整 JSON |
| P4：MORPHO/COQTEL schema 审计与确认 | P0–P2 | 1–2 天 + 下载时间 | 资格记录、至少一个外部确认或 schema 排除记录 |
| P5：统计、论文、复现说明、全量测试/PDF | P3–P4 | 1–1.5 天 | 审计通过的结果、论文与复现包 |

**纯实现与验证预计 4–6 个工作日；含数据传输、HDF5 兼容性排错和一次性确认，预计 6–9 个工作日。** MORPHO 归档约 8.34 GB，网络吞吐、官方访问可用性和 HDF5 schema 的实际复杂度可能使日历时间延长；这不应通过跳过门槛或重用发现集来压缩。

## 9. 启动授权后的第一条命令前检查

1. 用户确认本计划和预注册字段；
2. 确认数据目录空间、下载来源和官方校验和；
3. 记录当前 git 状态但不覆盖既有脏改动；
4. 生成并锁定协议/manifest 哈希；
5. 仅在以上四项完成后才下载或读取 D12/D16、MORPHO、COQTEL/COPV 的任何波形内容。
