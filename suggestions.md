## 总体评价

这是一篇**实验设计严谨性明显强于方法创新性的论文**。论文最大的价值在于建立了一个严格、可复现的 SoD（Send-on-Delta）评估流程，通过真实字节计费、时间隔离数据划分、避免标签泄漏等方式，证明在当前公开数据和实验范围内，SoD并不是优选编码方案。论文明确将贡献定位为“可复现的负结果审计”，而不是提出新算法。:contentReference[oaicite:0]{index=0}

但是，从高水平期刊审稿角度看，最大的问题是：**论文证明了一个方法“不够好”，但没有充分解释“为什么不好”，因此更像一篇严谨的benchmark报告，而不是具有深入科学贡献的方法论文。**

---

# 主要优点

## 1. 实验协议非常严谨，这是全文最大亮点

论文很好地解决了以往SoD评价中的几个关键漏洞：

- 没有只比较保存样本数量，而是真正统计序列化后的字节数；
- 考虑timestamp、packet framing等实际开销；
- 避免测试集参与模型选择；
- 避免损伤标签泄漏；
- 使用固定容量进行公平比较。

作者明确指出过去方法存在payload未计费、测试集选择参数以及label leakage等问题，并重新设计严格评价流程。:contentReference[oaicite:1]{index=1}

这一点符合工程压缩和SHM领域对可重复性的要求。

---

## 2. 数据划分和实验流程规范

论文采用：

- healthy training；
- healthy validation；
- held-out test；

并且codec配置只利用训练和验证数据确定，没有使用damage label或test数据。:contentReference[oaicite:2]{index=2}

相比很多SHM论文存在：

- 随机划分导致时间泄漏；
- 使用全部数据调参；
- 事后选择最佳阈值；

该论文在实验规范性上明显更强。

---

## 3. 负结果报告较为客观

论文没有隐藏失败结果，而是报告所有容量：

2048、4096、8192、16384 bytes。

结果显示SoD在所有容量下均低于Uniform、PCA和Haar DWT。:contentReference[oaicite:3]{index=3}

同时，作者没有夸大结论，没有声称“SoD完全无用”，而是限定为：

“within this public data and software-only scope”。:contentReference[oaicite:4]{index=4}

这种结论边界控制是合理的。

---

# 主要问题

## 1. 最大问题：创新性不足

这是论文最容易被拒的原因。

当前核心贡献是：

> 经过严格实验发现SoD不如其他codec。

但是，“证明已有方法表现不好”本身通常不足以支撑高水平论文。

审稿人可能会问：

**这项工作除了告诉大家SoD失败，还发现了什么新的科学规律？**

目前答案不够明确。

论文应该从：

“Which method wins?”

提升到：

“Why does event-based representation fail or succeed in guided-wave SHM?”

否则更像实验审计报告，而不是研究论文。

---

## 修改方向：

增加SoD失败机制分析，例如：

- SoD丢失了哪些damage-sensitive信息？
- 小幅连续相位变化是否被delta阈值过滤？
- transient feature是否被稀疏化破坏？
- event数量和损伤程度是否存在关系？

需要解释：

为什么SoD在导波SHM中不适合，而不是简单报告AUC较低。

---

# 2. 比较指标可能偏向传统压缩方法

论文比较：

- SoD；
- Uniform interpolation；
- PCA；
- Haar DWT。

但是这些方法优化目标不同：

SoD强调：

- 稀疏事件传输；
- 数据减少；
- 边缘通信效率。

而PCA/Haar主要优化：

- 重构误差；
- 信息压缩率。

最终评价使用reconstruction energy和AUC，可能天然偏向保持完整波形的方法。

审稿人可能提出：

> SoD不是为了最小化波形误差设计，用重构指标评价它是否公平？

---

## 修改方向：

增加：

- event timing feature；
- event density；
- change-point detection；
- 基于事件流的异常检测。

证明即使按照SoD设计目标评价，它仍然不足。

---

# 3. 数据规模和泛化能力不足

论文自己承认：

数据来自：

- 一个CFRP板；
- 两种damage状态。

:contentReference[oaicite:5]{index=5}

这意味着：

实验结果只能说明：

“该数据上的SoD表现”。

不能推广到：

- 飞机复材；
- 管道；
- 桥梁；
- 不同传感器系统。

---

## 修改方向：

至少增加：

- 不同材料；
- 不同结构；
- 多个损伤类型；
- 多个长期监测案例。

如果不能增加数据，应降低标题和摘要中的泛化表达。

---

# 4. 缺少理论解释

论文大量展示实验结果，但是缺少理论层面的解释。

例如：

SoD编码：

\[
|x(t_i)-x(t_{i-1})|>\delta
\]

才产生事件。

如果损伤信息表现为：

连续、小幅、相干变化，

则可能：

\[
\Delta x < \delta
\]

导致关键损伤信息被忽略。

论文应该建立这种理论联系。

否则目前只是：

“实验发现SoD不好”。

---

# 5. Alarm部分贡献较弱

Alarm实验结果显示：

- false calls/day较高；
- 新报警延迟约2556–2585分钟；
- post-onset coverage最高25.6%。

:contentReference[oaicite:6]{index=6}

但是该部分主要是在验证：

现有feature效果不好。

缺少：

- 新报警算法；
- 更强baseline；
- 自适应阈值方法。

因此容易被认为只是工程测试。

---

# 写作问题

## 1. “strict”使用过多

全文大量强调：

- strict evaluation；
- strict protocol；
- strict comparison。

虽然强调严谨没有错，但容易让论文显得像是在批评已有工作，而不是提出科学发现。

建议减少：

strict、audit、prevent misunderstanding

增加：

rigorous、controlled、reproducible。

---

## 2. 负结果描述过多，机制讨论不足

论文大量解释：

- 为什么不能claim；
- 为什么不能推广；
- 为什么不能作为概率检测。

这些都是正确的，但占用了篇幅。

应该减少免责声明，把空间用于：

- 失败原因；
- 信息损失；
- 适用边界。

---

# 最需要增加的实验

1. **SoD机制分析**

   - 分析delta阈值对损伤信息的影响；
   - 分析事件流包含哪些频率和时域信息。
2. **公平的事件检测评价**

   - 不只比较重构AUC；
   - 加入event-based anomaly detection。
3. **硬件效率验证**
   SoD最大的优势是边缘设备，而论文没有测试：

   - MCU RAM；
   - 编码时间；
   - 能耗；
   - 实时延迟。
4. **扩大数据验证**
   增加多结构、多材料、多损伤案例。

---

# 最终审稿意见

如果作为普通SHM期刊论文：

> 可以发表，实验规范性较强。

如果目标是高水平期刊：

> 当前贡献不足，需要从“严格证明SoD失败”提升到“解释事件化表示为何在导波SHM中失效，以及什么条件下可能有效”。

最终评价：

**优点：实验严谨、数据处理规范、结论诚实。**

**缺点：创新不足、理论深度不足、缺少机制解释。**

最关键修改方向：

> 不要继续增加benchmark，而应该解释SoD失败的物理和信息学原因。只有从“结果比较”提升到“规律发现”，论文才具有更高学术价值。
