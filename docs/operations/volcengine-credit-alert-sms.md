# 火山引擎积分预警短信（二阶段接入手册）

当前版本不会发送短信：`DisabledSmsSender` 只把新跨线事件终结为
`skipped_unconfigured`；缺少手机号时记录 `skipped_missing_phone`。不要把这两类
历史事件重新排队。启用火山引擎只影响启用之后新产生的跨线事件。

## 1. 平台准备

1. 在火山引擎开通短信服务，创建用于积分通知的消息组，保存消息组 ID。
2. 提交企业资质并等待通过，再提交与资质相符的短信签名。签名不要手写方括号；
   火山引擎会自动添加。签名和模板通过平台审核后还需等待运营商实名报备，发布
   计划应预留数个工作日。
3. 在同一消息组创建“通知短信”模板，建议内容（不含 URL）：

   `您的账户当前可用积分为${balance}，已达到${threshold}积分预警线，请及时充值。`

4. 先用控制台测试号码验证签名、模板变量、实际落款和长短信拆分情况，再进行 API
   接入。签名规则见[官方签名审核规范](https://www.volcengine.com/docs/6361/170338?lang=zh)。

## 2. 配置与密钥

通过部署平台的 Secret Store 或加密环境变量提供以下六项配置：

- `DCLAW_VOLCENGINE_SMS_ENABLED=false`
- `DCLAW_VOLCENGINE_SMS_ACCESS_KEY_ID`
- `DCLAW_VOLCENGINE_SMS_SECRET_ACCESS_KEY`
- `DCLAW_VOLCENGINE_SMS_ACCOUNT`（消息组 ID / `SmsAccount`）
- `DCLAW_VOLCENGINE_SMS_SIGN`（审核通过的签名正文）
- `DCLAW_VOLCENGINE_SMS_TEMPLATE_ID`（审核通过的模板 ID）

AK/SK 不得进入源码、浏览器配置、数据库、镜像层、诊断包或日志；生产环境使用短信
发送所需的最小权限子账号并建立轮换流程。`ENABLED` 默认保持 `false`，其余任一项
缺失时启动应拒绝启用真实发送器，而不是退化成半配置状态。

## 3. 适配器实现映射

在一次单独评审的依赖变更中安装官方 `volcengine` Python SDK，并实现现有
`SmsSender` 协议。官方[Python SDK 示例](https://docs.volcengine.com/docs/SMSservice/PythonSDK-4?lang=zh)
展示了 `SmsService.send_sms` 的基本用法。每个新事件只发送一个收件人，请按
[SendSms API](https://www.volcengine.com/docs/6361/67380?lang=zh)映射：

| SendSms 字段 | 本系统来源 |
| --- | --- |
| `SmsAccount` | `DCLAW_VOLCENGINE_SMS_ACCOUNT` |
| `Sign` | `DCLAW_VOLCENGINE_SMS_SIGN` |
| `TemplateID` | `DCLAW_VOLCENGINE_SMS_TEMPLATE_ID` |
| `TemplateParam` | JSON 字符串：`balance` 与 `threshold` 的事件快照 |
| `PhoneNumbers` | 事件的 E.164 手机快照；大陆号码可保留 `+86` |
| `Tag` | 稳定的 `credit_alert_events.id` |

先持久化 `pending` 事件，再提交。受理成功时保存 provider message ID 并标为
`submitted`；明确拒绝或重试耗尽时标为 `failed`。日志只允许 user ID、event ID、
tier 和提供商错误码，不得记录 AK/SK 或完整手机号。超时结果未知时以同一事件 ID
进行受控幂等核查，不要创建第二个积分预警事件。

## 4. 送达回执

如需跟踪送达状态，在短信控制台“通用管理 > 回执配置”设置公网 HTTPS 状态报告
地址；参见[配置消息接收地址](https://www.volcengine.com/docs/6361/171583?lang=zh)和
[短信发送状态回调](https://docs.volcengine.com/docs/SMSservice/SMSstatusreportcallback?lang=zh)。
回调处理器必须：

1. 验证请求来源/签名与载荷结构，并限制请求体大小和速率。
2. 用回执 `ext`（即发送时的 `Tag`）定位事件，核对 provider message ID。
3. 幂等地把成功回执更新为 `delivered`，失败回执更新为 `failed`；重复、乱序和未知
   `ext` 只记录脱敏审计，不改变其他事件。
4. 成功接收后返回 HTTP 200。回执接口不得修改钱包、阈值或告警状态。

## 5. 限流、灰度与回滚

- 上线前从当前短信套餐/控制台确认账号、消息组、模板和运营商的实时限流；应用侧
  设置更低的全局与单手机号速率，并保留每次跨线一次的数据库唯一约束。不要把
  SendSms 单次最多 200 个号码的能力用于本功能的批量发送。
- 先在预生产使用测试账号和测试号码，再以少量内部客户灰度。检查：跨线事件数、
  `submitted/delivered/failed` 比例、提供商错误码、回执延迟、同一事件是否只提交
  一次，以及账本延迟和成功率是否不受影响。
- 全量前验证签名/模板仍为审核通过状态、余额充足、告警阈值与手机号快照正确。
- 紧急回滚只需把 `DCLAW_VOLCENGINE_SMS_ENABLED=false` 并滚动重启发送进程。
  客户端横幅和积分账本继续工作；回滚前已经 `submitted` 的事件仍可接收回执，
  但所有 `skipped_unconfigured`、`skipped_missing_phone` 和其他历史终态都不得补发。

