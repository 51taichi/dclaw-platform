# 管理后台模型定价上线手册

本手册用于单环境 Docker 部署。目标是先建立一份经过人工复核的人民币价格目录，再开启计费；任何同步失败或价格过期都不得中断已有客户调用。

## 1. 上线前准备

1. 确认应用实际连接的 PostgreSQL，而不是容器内备用 SQLite：

   ```bash
   docker exec dclaw env | grep '^QWENPAW_DATABASE_'
   docker exec dclaw-postgres psql -U qwenpaw -d qwenpaw -c \
     "select current_database(), current_user, now();"
   ```

2. 备份数据库和持久化卷。备份文件只保存在宿主机，不写进镜像：

   ```bash
   mkdir -p /root/dclaw-backup
   docker exec dclaw-postgres pg_dump -U qwenpaw -d qwenpaw -Fc \
     > /root/dclaw-backup/qwenpaw-before-pricing.dump
   docker run --rm -v dclaw-data:/source:ro -v /root/dclaw-backup:/backup \
     alpine sh -c 'cd /source && tar czf /backup/dclaw-data-before-pricing.tgz .'
   ```

3. 记录当前容器镜像、环境变量名、网络、端口和卷，便于原样回退：

   ```bash
   docker inspect dclaw > /root/dclaw-backup/dclaw-inspect-before-pricing.json
   docker image inspect "$(docker inspect dclaw --format '{{.Config.Image}}')" \
     > /root/dclaw-backup/dclaw-image-before-pricing.json
   ```

## 2. 部署与数据库初始化

应用启动时 `create_all` 会以幂等方式创建新增表，包括可信成本、倍率策略、Excel 导入、二次解锁、审计和同步频率状态。先用与正式环境相同数据库克隆做一次演练，再替换正式容器。

启动后检查日志和表：

```bash
docker logs --tail 200 dclaw
docker exec dclaw-postgres psql -U qwenpaw -d qwenpaw -c "
select tablename from pg_tables
where schemaname='public' and tablename like 'billing_pricing_%'
order by tablename;"
```

预期至少包含 `billing_pricing_audits`、`billing_pricing_imports`、`billing_pricing_policies`、`billing_pricing_sync_state` 和 `billing_pricing_unlocks`。

## 3. 首次价格目录

1. 以管理员登录，进入“积分与计费管理 → 模型定价”。
2. 点击“解锁计费设置”，再次输入当前管理员密码。令牌只保存在当前页面内存，15 分钟后失效；不要把令牌复制到日志或工单。
3. 导出人民币模板。按实际结算平台填写成本：经百炼调用的模型以百炼结算规则为准，经火山引擎调用的模型以火山引擎结算规则为准。不要混用模型原厂官网价。
4. 每一行保留可追溯的计价维度、人民币成本、验证状态和验证时间。首次发布只接受 `verified` 的可信成本。
5. 导入 Excel，先查看差异预览。低于 1.3 倍、公式、宏、重复维度、负成本或格式不符会被阻止。
6. 确认导入只生成草稿，不会立即影响客户。检查全局、供应商、分类和模型倍率；优先级为“模型 → 分类 → 供应商 → 全局”。
7. 检查覆盖率为 100%，并确认所有启用模型的必需计价维度都有可信成本。缺失成本的新模型不得发布。
8. 发布草稿。发布后目录不可修改；后续调整必须产生新目录。

默认经济参数：100 积分/人民币元、5% 风险缓冲、最低 1.3 倍。界面和 Excel 仅显示人民币；原始币种和汇率只作为内部审计证据。

## 4. 发布后验证

检查当前生效目录及有效规则：

```bash
docker exec dclaw-postgres psql -U qwenpaw -d qwenpaw -c "
select c.id, c.version, c.status, c.effective_at, c.published_at,
       count(r.id) as active_rules
from billing_price_catalogs c
left join billing_price_rules r
  on r.catalog_id=c.id and r.status='active'
where c.status='published'
  and c.effective_at <= now()
  and c.published_at <= now()
group by c.id, c.version, c.status, c.effective_at, c.published_at
order by c.effective_at desc, c.published_at desc;"
```

检查可信成本覆盖与审计：

```bash
docker exec dclaw-postgres psql -U qwenpaw -d qwenpaw -c "
select provider_id, model_key, capability, unit_key,
       rmb_cost_decimal, verification_status, verified_at
from billing_cost_snapshots
order by provider_id, model_key, unit_key, created_at desc;"

docker exec dclaw-postgres psql -U qwenpaw -d qwenpaw -c "
select action, actor_id, created_at
from billing_pricing_audits
order by created_at desc limit 30;"
```

用测试 API Key 重放一条与之前出现 `catalog_not_ready` 相同的 OpenAPI 请求。验收标准：不再返回 503，供应商/Agent 被实际调用，使用订单保存目录版本、规则和完整经济快照。重放必须使用测试用户和小额请求，避免误扣正式客户。

## 5. 同步、复核和连续运营

- 系统每天只检查哪些价格来源已经到期，不是每天抓取全部官网。
- 官方结构化 API 默认每日；百炼、火山等聚合平台及价格页默认每周；人工来源默认每月。具体供应商可以覆盖周期。
- 同步候选必须经过单位、币种、阶梯和优惠条件标准化。来源冲突、单位变化或异常涨幅只进入待复核，不直接替换正式目录。
- 成本下降只生成草稿并等待人工发布。成本上涨的自动保护单次最多 20%，同一模型 24 小时最多一次；限制状态保存在数据库，重启容器不会清零。
- 价格过期、抓取失败、汇率失败或候选冲突只触发提醒。运行时继续锁定最后一份有效的已发布目录，绝不能给客户“拉闸断电”。
- 新启用且没有可信成本的模型保持不可售，直到补齐成本并发布新目录；这不会影响原有模型。

## 6. 回滚与故障处置

价格回滚不是修改历史目录。在后台选择目标历史版本并执行“回滚”，系统会克隆其规则、生成一个新版本并发布，保留完整审计链。

若新版本明显错误：

1. 立即在后台克隆回滚到最近正确目录；
2. 用 SQL 确认新回滚目录已生效且规则数大于零；
3. 重放小额 OpenAPI 请求；
4. 检查审计记录和使用订单的目录版本；
5. 修复成本或倍率后重新走“预览 → 人工确认 → 发布”。

只有应用本身无法启动且数据库结构损坏时，才使用上线前备份恢复。恢复数据库会覆盖上线后的业务数据，执行前必须另做故障现场备份并明确停机窗口。
