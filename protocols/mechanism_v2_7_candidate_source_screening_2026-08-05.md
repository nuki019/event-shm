# mechanism-v2.7 候选确认源筛选记录（2026-08-05）

**状态：`METADATA_ONLY_NOT_AUTHORIZED_FOR_ACCESS`**

本记录只保存公开着陆页、DataCite 和公开 RO-Crate 元数据的筛选结论。没有下载、解压、打开、缓存或评分任何候选源的波形；它不是 `mechanism-v2.7` protocol、manifest、freeze receipt 或 source receipt，也不授予任何数据访问权限。

## 固定的准入门槛

一个来源只有同时满足下列项目，才可在另一次、经用户明确同意后的预访问审查中被指定为候选确认源：

1. 明确的公开许可；
2. 数据发布方明确给出的健康/无损与损伤语义；
3. 原始时序波形，而不是只含特征、图像或模拟汇总；
4. 可预注册且能在工件层面追溯的独立物理组或 campaign 定义；
5. 可取得的官方文件清单、版本、大小及后续可复核的完整性信息；
6. 相对于本仓 v2.5/v2.6 接触史为新源，且不属于被禁止复用的来源家族。

缺任一项均不得创建 v2.7 冻结件，也不得访问候选包内容。

## 当前可保留的条件候选

| 优先级 | 来源 | 已由公开元数据确认 | 仍缺失的硬门槛 | 结论 |
|---|---|---|---|---|
| A | [IEEE DataPort：small-diameter pipes](https://doi.org/10.21227/2v7s-g915) | `CC BY 4.0`；官方 DataCite 描述明确为多通道 UGW time-series waveforms，含十种损伤类别；在当前仓的 v2.6 收据、缓存和本地盘点中没有出现。 | 公开 DOI 元数据没有说明无损/健康类别、文件格式、样本到物理管段或独立 campaign 的映射、文件清单或校验信息。该站公开着陆页本轮超时，不能以推断补齐。 | `CONDITIONAL_NOT_AUTHORIZED`。不得把“十种损伤类别”误写成健康/损伤二元语义。 |

“条件候选”不是批准、不是盲确认结果，也不是可立即启动的 v2.7 数据源。

## 已淘汰或暂不合格的来源

| 来源 | 缺口或边界 | 结论 |
|---|---|---|
| [4TU：defective thermoplastic composite ultrasonic welds](https://doi.org/10.4121/uuid:190ac321-ad31-456c-919e-564f7e6333ef) | `CC BY-NC 4.0`、GW 测量和 MATLAB/CSV 格式均有公开说明，但无损 reference 与两类缺陷各自完全嵌套在三个不同制造批次；在没有“每个 condition 跨多个独立 batch”的官方证据时，任何分类结果都无法区分损伤与 batch effect。公开 RO-Crate 还只列 `data.zip`，未提供 joint/campaign 映射。 | `NO_GO_AS_CURRENT_METADATA` |
| [GFRP 两板四脱层](https://doi.org/10.5281/zenodo.15640329) | 虽为 `CC BY 4.0` 且为实测全波场，但官方描述的两块板均内含脱层，没有官方无损对照；只有两块物理试件。 | `NO_GO` |
| [UGW-3Mat-2SN](https://doi.org/10.5281/zenodo.15688321) | 有 `CC BY 4.0`、原始 UGW 类别和 damage-position 标签，但公开描述没有健康类，也没有可冻结的物理组/记录映射。 | `NO_GO_AS_CURRENT_METADATA` |
| [混凝土 splitting 波形](https://doi.org/10.34808/p2fs-5z67) | 官方描述有三块立方体、劈裂前后 CSV 时程，但 DataCite 的 rightsList 为空，着陆页被 WAF 阻断，不能确认许可。 | `NO_GO` |
| [Mendeley 钢管 UGW](https://doi.org/10.17632/ttb63krg6d.1) | `CC BY 4.0` 且有健康/腐蚀阶段描述，但全部来自同一根 6.4 m 钢管；不能将连续损伤阶段当作独立外部组。 | `NO_GO` |
| [OGW #4 CFRP omega stringer](https://doi.org/10.5281/zenodo.5105861) | 有无损、局部脱粘和大脱粘语义，且为 `CC BY 4.0`，但只有一块板，并属于既有 Open Guided Waves 来源家族；不能作为独立新确认。 | `NO_GO` |
| COPV baseline/damage | 公开元数据本身较完整，但 `MECHANISM_V2_7_PRE_ACCESS_PLAN.md` 已明确禁止把 COPV 作为 v2.6 中断/不佳后的 fallback。 | `NO_GO_BY_PROTOCOL_BOUNDARY` |
| 已消费的 D12、D16、MORPHO、D04/D24、COQTEL、E7/UDAM 与既有长期集月份 | 受 v2.5/v2.6 消耗、发现集、校准或历史用途边界约束。远端月度链接即使本地无字节，也不能凭本仓状态宣称用户从未接触。 | `NO_GO` |

## 本轮决策

1. 本轮没有任何 `GO` 来源；不得创建 `mechanism-v2.7` protocol、data manifest、result schema 或 freeze receipt。
2. `mechanism-v2.6` 的 D16 与 MORPHO 仍为不可恢复的历史作废链，禁止续跑、改名、重算或以 v2.7 名义复用。
3. v2.7 合成合约、terminal-hold 和 checkpoint 基础设施只通过了开发期 fixture 测试；它们不构成数据资格或机制证据。
4. 当前只有候选 A 仍可在不读取波形的条件下继续争取官方目录/README 元数据；它必须先补齐健康语义、物理组/campaign 映射和文件完整性信息。若不能补齐，项目应保持在预访问暂停状态，而不是降格复用 4TU 或任何已消费来源。

## 元数据来源

- DataCite record metadata：`https://api.datacite.org/dois/<DOI>`，查询于 2026-08-05。
- 4TU 公开 RO-Crate：`https://data.4tu.nl/v3/datasets/4cfaa6c7-d35a-4599-b1da-15fb4b568b0d/versions/1/ro-crate-metadata.json`，仅读取文件名和大小元数据。
- 本仓接触边界：`MECHANISM_V2_7_PRE_ACCESS_PLAN.md` 与 `protocols/mechanism_v2_6_invalidation_receipt.json`。
