# 阿里云积分预警短信接入手册

短信发送默认关闭。只有 `DCLAW_SMS_PROVIDER=aliyun` 且配置完整时，新产生的积分跨线
事件才会调用阿里云国内短信；历史 `skipped_unconfigured` 或
`skipped_missing_phone` 事件不会补发。

## 1. 当前资源

- 短信签名：`湖南星芒物联科技`
- 模板代码：`SMS_512581202`
- 模板变量：`balance`、`threshold`
- 模板参数示例：`{"balance":"4800","threshold":"5000"}`

启用前必须确认签名和模板均已审核通过，并且目标运营商报备已完成。报备未完成时保持
`DCLAW_SMS_PROVIDER=disabled`。

## 2. 环境变量

```dotenv
DCLAW_SMS_PROVIDER=disabled
DCLAW_ALIYUN_SMS_ACCESS_KEY_ID=
DCLAW_ALIYUN_SMS_ACCESS_KEY_SECRET=
DCLAW_ALIYUN_SMS_SIGN_NAME=湖南星芒物联科技
DCLAW_ALIYUN_SMS_TEMPLATE_CODE=SMS_512581202
```

也可用阿里云标准凭据变量 `ALIBABA_CLOUD_ACCESS_KEY_ID` 和
`ALIBABA_CLOUD_ACCESS_KEY_SECRET`。`DCLAW_` 前缀变量优先。可选项：

- `DCLAW_ALIYUN_SMS_ENDPOINT`，默认 `dysmsapi.aliyuncs.com`
- `DCLAW_ALIYUN_SMS_CONNECT_TIMEOUT_MS`，默认 `3000`
- `DCLAW_ALIYUN_SMS_READ_TIMEOUT_MS`，默认 `5000`

AK/SK 必须通过部署平台的 Secret Store 或受保护环境变量提供，不得写入源码、镜像、
数据库、日志或诊断包。使用仅包含短信发送权限的 RAM 用户，并建立密钥轮换流程。

## 3. 发送与事件状态

每次新的余额跨线先写入唯一的 `pending` 事件，再调用 `SendSms`：

| 阿里云字段 | 本系统来源 |
| --- | --- |
| `PhoneNumbers` | 用户 E.164 手机号去除中国区号后的 11 位号码 |
| `SignName` | `DCLAW_ALIYUN_SMS_SIGN_NAME` |
| `TemplateCode` | `DCLAW_ALIYUN_SMS_TEMPLATE_CODE` |
| `TemplateParam` | 事件快照中的 `balance`、`threshold` 字符串 |
| `OutId` | `credit_alert_events.id` |

阿里云返回 `Code=OK` 和 `BizId` 时，事件更新为 `submitted` 并保存 `BizId`。明确拒绝、
SDK 异常、超时、号码格式错误或配置错误均更新为 `failed` 并保存脱敏错误原因。SDK
自动重试关闭，避免结果未知时重复发送。短信错误会在积分账本的嵌套事务内被吸收，
不会回滚余额扣减。

## 4. 上线步骤

1. 等待移动、联通、电信全部完成报备，并在阿里云控制台用测试号码验证模板。
2. 在服务器 Secret Store 配置 AK/SK，保持 `DCLAW_SMS_PROVIDER=disabled`。
3. 在非生产环境制造一次跨线，确认事件包含正确手机号快照、余额和阈值。
4. 将 `DCLAW_SMS_PROVIDER` 改为 `aliyun`，重启应用进程后只对内部号码灰度。
5. 检查 `submitted/failed` 比例、`provider_error`、账本成功率和接口延迟。

紧急回滚只需恢复 `DCLAW_SMS_PROVIDER=disabled` 并重启应用进程。已提交短信不撤回，
历史终态事件不补发。
