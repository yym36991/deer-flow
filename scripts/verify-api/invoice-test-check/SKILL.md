---
name: invoice-test-check
description: 验证用 Skill：审查测试发票数据是否符合规范。用户要求校验测试发票、跑通 skill 安装流程时使用。
---

# Invoice Test Check Skill

用于 `scripts/verify-api` 下的 `.skill` 上传 / 安装 API 手工验证。

## 工作流程

1. 读取用户提供的测试发票数据（CSV / Excel）
2. 校验字段：发票号、金额、税率、开票日期
3. 输出问题清单（Markdown）

## 触发示例

- 「用 invoice-test-check 审查这份测试发票」
- 「校验 uploads 里的 invoice 样例数据」
