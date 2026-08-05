# mechanism-v2.7 冻结前计划

状态：仅设计，不是协议授权，也不允许下载、打开新波形、评分、缓存构建或启动实验。

本计划的前提是 mechanism-v2.6 已由
protocols/mechanism_v2_6_invalidation_receipt.json 作废。v2.6 的 D16 输出、MORPHO
源访问与中断缓存均为历史完整性证据，而不是可以修补、续跑或重命名为新确认的结果。

## 1. 数据角色边界

下列来源不得作为 mechanism-v2.7 的新盲确认来源：D12、D16、MORPHO、OGW D04/D24。
D12 已在 v2.5 消耗；D16 与 MORPHO 已在 v2.6 接触；D04/D24 永远仅限发现集。
OGW UDAM/E7 仅保留为既有校准来源。COQTEL 仅保留 schema 资格，因为没有已冻结的官方二元
健康/损伤切点。2018_03/2018_04 仅可用于报警迁移描述，不能替代机制确认。COPV 不得因
v2.6 表现不佳或中断而激活。

在一个新的、此前未接触的确认源被书面选定并完成许可证、原始字节、SHA-256、结构映射、
独立组定义和健康/损伤语义审查前，mechanism-v2.7 不得进入冻结或执行阶段。

## 2. 冻结前必须完成的本地工作

1. 先实现并测试一个唯一的 canonical result envelope。runner 和 auditor 必须用同一字段模型，
   覆盖协议、清单、schema、代码、环境、源收据、schema gate、terminal-hold 收据、检查点和
   开始/结束时间的哈希。
2. 实现独立只读 auditor，并用合成正例和无效 fixture 验证：缺字段、哈希错误、时间顺序错误、
   31/32 网格、重复格、错误 runner、组泄漏、未通过 terminal-hold、断裂 checkpoint 链和已接触
   数据重入都必须被拒绝。
3. 用与实际数据角色一致的路径数、样本数和硬容量参数重写 terminal-hold 预访问测试。它应产生
   真实 UTC、实现哈希、完整适用/不适用网格、两条轨迹饱和和等价 payload/decoded 的可审计证据。
4. 实现预注册恢复机制：单 attempt UUID、单写者锁、固定工作顺序、逐格原子 checkpoint、哈希链、
   deterministic seed 和只在同一冻结输入、同一代码、无最终结果、死 writer、checkpoint 审计通过时
   才能执行的 resume。
5. 锁定 Python 与依赖版本，并将 runner、auditor、测试、共享方法和环境锁全部列入 freeze receipt。
   缺少任一可执行文件或哈希不匹配时，preflight 必须失败。

## 2.1 已完成的合成预访问基础设施

以下实现只处理合成输入，未读取真实波形、未创建 v2.7 协议或 freeze receipt，且不能授权任何
数据访问：

- src/experiments/mechanism_v2_7_contract.py：canonical synthetic result envelope、完整 4 x 8
  网格、双 SHA-256、UTC 时序和已接触数据拒绝。
- src/experiments/audit_mechanism_v2_7.py：只读 synthetic pre-access envelope auditor。
- src/experiments/test_mechanism_v2_7_terminal_hold.py：按路径数、样本数、容量和 delta 参数化的
  合成 terminal-hold 预访问测试。
- src/experiments/mechanism_v2_7_checkpoint.py：单 attempt、持久单写者 lease、强制 CAS head、原子写入、
  严格递增 UTC、哈希链、冻结/源/代码三哈希绑定和 fail-closed resume 前置条件。
- src/experiments/audit_mechanism_v2_7_checkpoint.py：独立的只读 checkpoint 账本 auditor；默认拒绝仍持有
  writer lease 的账本，并且不具备创建、更新或恢复 attempt 的能力。

2026-08-05 已运行以下定向测试，25/25 通过：

    C:\Users\wfy\.conda\envs\shm\python.exe -m unittest discover -s tests -p test_mechanism_v2_7_*.py -v

这些测试只证明开发期的合约、单写者恢复机制和只读账本审计在合成 fixture 上工作；它们不是
数据资格、机制结果、一次性运行或论文证据。第 2.3 和第 2.5 项仍必须绑定一个合格的新来源后
才能完成，且不得用历史来源补齐。

## 3. 后续决策门

只有在第 2 节全部通过、且新的确认源已完成预访问审查后，才可以创建 mechanism-v2.7
protocol、manifest、result schema 和 freeze receipt。此后按以下不可逆顺序执行：

source receipt -> metadata/schema gate -> checkpointed one-shot runner -> read-only audit -> immutable audit receipt

若新确认源不可得或任何冻结前测试失败，项目应保留 E7/E8 的严格负结果审计路线，而不是继续扩展
已失效的机制链。
