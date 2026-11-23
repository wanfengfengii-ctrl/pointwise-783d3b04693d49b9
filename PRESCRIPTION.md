# 青岚校验室延时补偿处方

夜班使用已实收的 V1 固定件。签发只需中心实收库与报告库，次班只需报告库。原双链复检与补测清单继续使用 README 所列接口。

## 处方申请与定稿

在 `review/request.py` 提供 `PrescriptionRequest(batch, primary_receipt, reference_receipt, max_order, c0, threshold)` 和 `prescribe(receipts, reports, request)`。`receipts` 和 `reports` 沿用 `ReceiptCatalog` 和 `ReportRepository`。批次与有序实收件沿用 V1 核对方式。`max_order` 为 0 至 3 的整数，排除布尔值。`c0` 与 `threshold` 接受 V1 有理数格式，门槛须非负。

记 V1 固定件的完整脉冲响应为 `direct + q * numerator / denominator`，其中 q 延迟一拍。主件响应为 P，对照响应为 R，约定处方 `F(q) = c0 + c1*q + ... + cK*q^K`，K 等于 `max_order`，允许尾端系数为零。残余为 `P - F*R`，全拍能量是从第零拍开始的残余系数平方和。对每份固定件使用约分后可见的极点，单件非衰减极点 λ 仅允许 1 和 2（对应分母因子 `1 - λ*q`），允许任意 V1 衰减极点与重数。即使超出范围的极点在两件之间完全相消，申请也须拒绝。

`prescribe` 成功返回一份定稿，公开属性为 `prescription_id`、`request`、`sources`、`status`、`energy`、`coefficients`。处方号为正整数，由处方接口解释。`request` 保留全部申请字段，其中 `c0` 和 `threshold` 以 `Fraction` 表示。`sources` 为按主件、对照件排列的 `ReportSource` 二元组，保留实收号、发行号、摘要和完整原出处。

| `status` | 业务含义 | `energy` | `coefficients` |
| --- | --- | --- | --- |
| `no_finite` | 约定首项和阶数下无法获得有限残余 | `None` | `None` |
| `over_threshold` | 最优能量有限且超过门槛 | 精确 `Fraction` | `None` |
| `executable` | 最优能量有限且小于或等于门槛 | 精确 `Fraction` | 按延时从零到 K 的 `Fraction` 元组，含尾端零项 |

对照恒零且可执行时，固定首项照录，其余系数均为零。原申请、有序双出处及结果须一次提交，任何提交失败均不得留下新定稿或孤立出处，并保留 SQLite 异常。非法申请、超范围来件或批次、出处不匹配抛 `ValueError`，缺实收抛 `KeyError`，拒绝时不写定稿。

## 次班领用

`reports.history.read_prescription(reports, prescription_id)` 返回当时定稿的各字段。`reports.followup.collect_prescription(reports, prescription_id)` 从定稿交付 `executable` 项的完整系数元组，另两态返回 `None`。未知处方号抛 `KeyError`。实收库和站库关闭后，重开报告库仍可执行两项操作。来源勘误和后续申请不得改写已签结果。

## 样例与核验

`samples/prescription.json` 中 `primary` 和 `reference` 是站端模型参数，`v1` 为同拍复检结果，`requests` 为本次处方的申请参数和预期结果。`prescription_sample.receive_pair(station, receipts, case)` 通过实际发件和实收接口返回主件、对照件各自的 `(修订号, 实收号)`。`receive_model(station, receipts, batch, channel, values, parent_id=None)` 可用同样流程接收单件或带父修订的勘误。`prescription_sample.verify_prescriptions(cases)` 逐条核对申请结果、出处顺序、定稿回读、领用交付、勘误后的 `no_finite`，以及关库后仅凭报告库按号重放；`verify_commit_failure()` 用延迟外键制造提交失败并确认无新定稿。运行 `python3 -B prescription_sample.py` 可查这些样例的 V1 复检、补测与处方结果。

`QL-FIR-17` 的完整主响应为 `1/(1−2q) + q/(1−q/2)`，对照为 `1/(1−2q)`。首项 1、门槛 1/3 时，一阶只能签有限超限 4/3，二阶应签可执行 `(1,1,−2)`、能量 1/3。按原对照修订接收样例的 `amendment` 后，用新实收号提交同样的二阶申请应得 `no_finite`。关闭站库与实收库后重开报告库，原号仍应领出原设置及固定出处。`QL-FIR-REPEATED` 核对重复极点的消除，`QL-FIR-ZERO` 核对恒零对照与有限瞬态，`QL-FIR-OUTSIDE` 核对单件范围拒绝。

沿用 `.pointwise-runtime.json` 的核验和演示约定。verify 运行完整 V1 回归和处方业务核验，失败时退出非零。`tests/test_prescription.py` 覆盖三态判定、门槛等号、重复极点、恒零对照、单件越界拒绝、非法申请、批次与顺序、关库回读和提交回滚；`tests/test_prescription_sample.py` 直接驱赶 `prescription_sample.py` 的样例核验（含延迟外键提交失败，检查解除故障后能继续签发）。demo 保留原工作日演示，并展示事故双件的处方签发及关库后按号领用。
