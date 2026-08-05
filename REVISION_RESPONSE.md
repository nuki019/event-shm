# 对 suggestions.md 审稿意见的修订回应

## 修订后的中心结论

本稿不再试图证明 SoD 是通用的低码率导波编码器或可部署报警方案。冻结
E7 和 E8 的全量运行已经完成，得到的是两个可复算的负结果：

1. 在四个预先声明的逐记录硬容量下，bounded SoD 在 D04 和 D24 的
   held-out record AUC 都低于 uniform linear、PCA 和 Haar DWT。
2. 对完整的 2021_04 冷启动回放，两类报警特征在全部九个
   2021_03 派生阈值下均有 0.897 以上 false calls/day，首次新的
   onset 后报警延迟为 2556--2585 分钟，不能支持运行级报警主张。

这不是通过挑选有利阈值得到的最好点结论。论文和结果表报告全部容量与
全部冻结阈值网格的范围。

## 逐条处理

| 审稿关切 | 本轮处理 | 证据边界 |
| --- | --- | --- |
| 数据泄漏与事后选择 | 协议把训练、验证、测试日期分开；量化器、编码器、容量配置、参考库、归一化和阈值均在允许的数据上冻结。 | strict_evaluation_v1.json、E7/E8 JSON；不能把旧 E2--E4 用于重新选择点。 |
| 指标误用和路径伪重复 | E7 的分析单元是 monitoring record，66 条 path 只作为该记录的组成部分；AUC 给出分层 bootstrap 区间。 | 不把 path 当作独立样本。 |
| 错误 benchmark | E7 将 SoD 的时间戳间隔、幅值变化和路径帧序列化，以真实 bytes/record 比较 SoD、uniform linear、PCA 与 Haar DWT；PCA decoder model bytes 单列。 | 这是后补偿软件编码比较，不是 ADC 或 MCU 比较。 |
| SoD 优势主张 | 全部四个容量、两种损伤条件的 SoD AUC 均低于三个通用编码器。 | 结论是本协议下的负结果，不推广为所有 SoD 实现或所有结构。 |
| 阈值鲁棒性 | E7 的配置只能按健康验证规则确定；E8 的九个高尾阈值全由 2021_03 得到，论文报告全部范围。 | 不从测试 AUC、FAR、延迟或覆盖中选择阈值。 |
| 长期报警与 PoD | E8 先完整计算 2021_04，再读取标签报告；30 分钟内连续超阈合并为一个事件，onset 前仍活跃的事件不得计为检测。 | 只有一次 observed onset，故报告 false calls/day、new-alarm delay 和 coverage，禁止称为 population PoD。 |
| 单一结构与物理解释 | 正文明确 OGW 是单块 CFRP 板和可逆盘片条件；不把 event count 关联写成物理机制证明。 | 无多结构、真实裂纹或独立安装泛化主张。 |
| 硬件和部署 | 删除 MCU、能耗、实时性、端侧采集节省和现场 FAR 的结果性表述。 | 现有证据仅为软件重放。 |

## 当前主证据与历史诊断

| 审计 | 脚本 | 当前用途 |
| --- | --- | --- |
| E7: 严格字节率基准 | src/experiments/e7_strict_codec_benchmark.py | 论文主结果：全容量 codec comparison。 |
| E8: 跨月冷启动报警 | src/experiments/e8_cold_start_alarm.py | 论文主结果：全阈值 alarm audit。 |
| E2--E4 及更早分析 | src/experiments/e2_record_robustness.py 等 | 仅保留为历史实现诊断，不得作为标题、表格、图或运行点选择的证据。 |

运行命令、数据边界和结果文件见 REPRODUCIBILITY.md 与
RUN_STRICT_EVALUATION.md。

## 尚不能诚实补齐的证据

- 多个独立结构、材料、传感器和安装条件上的预注册验证；
- 多个独立健康校准期和未来损伤期上的阈值迁移、FAR 与延迟评估；
- 真实工业干扰、传感器老化、丢包条件；
- MCU 上的内存、吞吐、能耗和端到端延迟测量；
- 与任务特定 dense、预训练或自监督模型在匹配训练预算下的比较。

因此，修订后的论文是一个严格的负结果审计，而不是对实际部署能力的
宣称。
