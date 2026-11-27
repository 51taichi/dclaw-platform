import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import { billingApi } from "../../../api/modules/billing";
import type {
  BillingReconciliationAudit,
  BillingReconciliationRecord,
  BillingReconciliationResolution,
} from "../../../api/types/billing";

const sourceLabels: Record<string, string> = {
  client: "客户端",
  mobile: "移动端",
  openapi: "OpenAPI",
  expert_team: "专家团",
  automation: "自动化",
  schedule: "定时任务",
  channel: "渠道",
};

const outcomeLabels: Record<string, string> = {
  pending: "供应商调用状态待确认",
  succeeded: "模型已返回，但用量不完整",
  failed: "模型调用失败，是否收费待确认",
  timed_out: "模型调用超时，是否收费待确认",
  cancelled: "调用已取消，是否收费待确认",
};

const formatNumber = (value: number) => value.toLocaleString("zh-CN");

function decisionKey(record: BillingReconciliationRecord): string {
  const randomPart = globalThis.crypto?.randomUUID?.() ?? String(Date.now());
  return `reconciliation:${record.reconciliation_id}:${randomPart}`;
}

function agentName(record: BillingReconciliationRecord): string {
  return (
    record.order.publication?.name ??
    record.order.expert ??
    record.order.expert_team ??
    "未关联"
  );
}

function EvidenceTag({ record }: { record: BillingReconciliationRecord }) {
  if (!record.item.evidence.supplier_reference_present) {
    return <Tag color="error">缺少供应商凭证</Tag>;
  }
  return <Tag color="warning">已有供应商凭证，待核实</Tag>;
}

function AuditTable() {
  const [rows, setRows] = useState<BillingReconciliationAudit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    void billingApi
      .listReconciliationAudits({ limit: 50 })
      .then((page) => setRows(page.items))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <Alert type="error" message={error} />;
  return (
    <Table
      rowKey="audit_id"
      loading={loading}
      dataSource={rows}
      pagination={{ pageSize: 10, hideOnSinglePage: true }}
      locale={{ emptyText: "暂无已处理记录" }}
      scroll={{ x: 900 }}
      columns={[
        {
          title: "处理时间",
          width: 170,
          dataIndex: "created_at",
          render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
        },
        { title: "操作人", width: 120, dataIndex: "actor_id" },
        {
          title: "处理结果",
          width: 120,
          render: (_, row) => (
            <Tag
              color={
                row.resolution.billability === "billable"
                  ? "success"
                  : "default"
              }
            >
              {row.resolution.billability === "billable"
                ? "确认收费"
                : "确认不收费"}
            </Tag>
          ),
        },
        {
          title: "实际 Token",
          width: 170,
          render: (_, row) =>
            `${formatNumber(
              row.resolution.actual_tokens.input,
            )} / ${formatNumber(row.resolution.actual_tokens.output)}`,
        },
        {
          title: "最终扣分",
          width: 110,
          render: (_, row) => formatNumber(row.resolution.charged_credits),
        },
        { title: "处理依据", dataIndex: "reason" },
      ]}
    />
  );
}

export default function ReconciliationTab() {
  const [rows, setRows] = useState<BillingReconciliationRecord[]>([]);
  const [userNames, setUserNames] = useState<Record<string, string>>({});
  const [pageCursors, setPageCursors] = useState<Array<string | undefined>>([
    undefined,
  ]);
  const [pageIndex, setPageIndex] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [selected, setSelected] = useState<BillingReconciliationRecord>();
  const [detail, setDetail] = useState<BillingReconciliationRecord>();
  const [billability, setBillability] = useState<"billable" | "not_billable">();
  const [submitting, setSubmitting] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [form] = Form.useForm<BillingReconciliationResolution>();

  useEffect(() => {
    void adminUsersApi
      .listUsers()
      .then((users) =>
        setUserNames(
          Object.fromEntries(
            users.map((user) => [String(user.id), user.username]),
          ),
        ),
      );
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(undefined);
    void billingApi
      .listReconciliation({ limit: 20, cursor: pageCursors[pageIndex] })
      .then((page) => {
        setRows(page.items);
        setNextCursor(page.next_cursor);
      })
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoading(false));
  }, [pageCursors, pageIndex, reloadToken]);

  const openDecision = useCallback(
    (
      record: BillingReconciliationRecord,
      decision: "billable" | "not_billable",
    ) => {
      setSelected(record);
      setBillability(decision);
      form.resetFields();
      form.setFieldsValue({
        billability: decision,
        reason: "",
        actual_input_tokens: record.item.tokens.input,
        actual_output_tokens: record.item.tokens.output,
      });
    },
    [form],
  );

  const submitDecision = useCallback(
    async (values: BillingReconciliationResolution) => {
      if (!selected || !billability) return;
      setSubmitting(true);
      setError(undefined);
      try {
        await billingApi.resolveReconciliation(
          selected.reconciliation_id,
          {
            ...values,
            billability,
            actual_input_tokens:
              billability === "billable" ? values.actual_input_tokens ?? 0 : 0,
            actual_output_tokens:
              billability === "billable" ? values.actual_output_tokens ?? 0 : 0,
          },
          decisionKey(selected),
        );
        setNotice(
          billability === "billable"
            ? "已确认收费，积分已按价格快照结算。"
            : "已确认不收费，冻结积分已释放。",
        );
        setSelected(undefined);
        setBillability(undefined);
        setPageCursors([undefined]);
        setPageIndex(0);
        setReloadToken((value) => value + 1);
      } catch (reason) {
        setError(String(reason));
      } finally {
        setSubmitting(false);
      }
    },
    [billability, selected],
  );

  const columns = useMemo(
    () => [
      {
        title: "客户",
        width: 145,
        render: (_: unknown, record: BillingReconciliationRecord) => {
          const ownerId = record.order.owner_user_id;
          return (
            <Space direction="vertical" size={0}>
              <Typography.Text strong>
                {ownerId ? userNames[ownerId] ?? "未知账号" : "系统"}
              </Typography.Text>
              {ownerId && (
                <Typography.Text type="secondary">ID {ownerId}</Typography.Text>
              )}
            </Space>
          );
        },
      },
      {
        title: "来源 / Agent",
        width: 190,
        render: (_: unknown, record: BillingReconciliationRecord) => (
          <Space direction="vertical" size={0}>
            <span>
              {sourceLabels[record.order.source] ?? record.order.source}
            </span>
            <Typography.Text type="secondary">
              {agentName(record)}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: "模型 / 供应商",
        width: 190,
        render: (_: unknown, record: BillingReconciliationRecord) => (
          <Space direction="vertical" size={0}>
            <span>{record.item.model}</span>
            <Typography.Text type="secondary">
              {record.item.provider}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: "调用时间",
        width: 170,
        render: (_: unknown, record: BillingReconciliationRecord) =>
          dayjs(record.item.created_at).format("YYYY-MM-DD HH:mm:ss"),
      },
      {
        title: "待确认积分",
        width: 120,
        align: "right" as const,
        render: (_: unknown, record: BillingReconciliationRecord) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>
              {formatNumber(record.item.quoted_credits)}
            </Typography.Text>
            <Typography.Text type="secondary">
              已扣 {formatNumber(record.order.captured_credits)}
            </Typography.Text>
            <Typography.Text type="secondary">
              已释放 {formatNumber(record.order.released_credits)}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: "证据状态",
        width: 220,
        render: (_: unknown, record: BillingReconciliationRecord) => (
          <Space direction="vertical" size={2}>
            <EvidenceTag record={record} />
            <Typography.Text type="secondary">
              {outcomeLabels[record.item.evidence.execution_outcome] ??
                record.item.evidence.execution_outcome}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: "操作",
        width: 230,
        fixed: "right" as const,
        render: (_: unknown, record: BillingReconciliationRecord) => (
          <Space size={4}>
            <Button type="link" onClick={() => setDetail(record)}>
              详情
            </Button>
            <Button
              type="link"
              onClick={() => openDecision(record, "billable")}
            >
              确认收费
            </Button>
            <Button
              danger
              type="link"
              onClick={() => openDecision(record, "not_billable")}
            >
              确认不收费
            </Button>
          </Space>
        ),
      },
    ],
    [openDecision, userNames],
  );

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Alert
        type="info"
        showIcon
        message="这里处理供应商调用结果不明确的计费记录"
        description="请根据供应商后台、调用日志或请求凭证确认是否收费；确认收费后按原价格目录和实际 Token 结算，确认不收费则释放冻结积分。"
      />
      {notice && (
        <Alert
          closable
          type="success"
          message={notice}
          onClose={() => setNotice(undefined)}
        />
      )}
      {error && (
        <Alert
          closable
          type="error"
          message={error}
          onClose={() => setError(undefined)}
        />
      )}
      <Card title="模型调用待对账">
        <Table
          rowKey="reconciliation_id"
          loading={loading}
          dataSource={rows}
          columns={columns}
          pagination={false}
          locale={{ emptyText: "当前没有待对账记录" }}
          scroll={{ x: 1260 }}
        />
        <Space
          style={{ width: "100%", justifyContent: "flex-end", marginTop: 16 }}
        >
          <Button
            disabled={pageIndex === 0}
            onClick={() => setPageIndex((value) => value - 1)}
          >
            上一页
          </Button>
          <Typography.Text type="secondary">
            第 {pageIndex + 1} 页
          </Typography.Text>
          <Button
            disabled={!nextCursor}
            onClick={() => {
              if (!nextCursor) return;
              setPageCursors((current) => {
                const next = current.slice(0, pageIndex + 1);
                next.push(nextCursor);
                return next;
              });
              setPageIndex((value) => value + 1);
            }}
          >
            下一页
          </Button>
        </Space>
      </Card>
      <Card title="已处理对账记录">
        <AuditTable />
      </Card>

      <Modal
        title={billability === "billable" ? "确认收费" : "确认不收费"}
        open={Boolean(selected && billability)}
        footer={null}
        destroyOnHidden
        onCancel={() => {
          setSelected(undefined);
          setBillability(undefined);
        }}
      >
        {selected && (
          <Alert
            style={{ marginBottom: 16 }}
            type={billability === "billable" ? "warning" : "info"}
            showIcon
            message={
              billability === "billable"
                ? `将根据实际 Token 结算，最高不超过预留的 ${formatNumber(
                    selected.item.quoted_credits,
                  )} 积分。`
                : `将释放预留的 ${formatNumber(
                    selected.item.quoted_credits,
                  )} 积分，不向客户收费。`
            }
          />
        )}
        <Form form={form} layout="vertical" onFinish={submitDecision}>
          <Form.Item name="billability" hidden>
            <Input />
          </Form.Item>
          {billability === "billable" && (
            <Space size="middle" style={{ width: "100%" }}>
              <Form.Item
                label="实际输入 Token"
                name="actual_input_tokens"
                rules={[{ required: true }]}
              >
                <InputNumber min={0} precision={0} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item
                label="实际输出 Token"
                name="actual_output_tokens"
                rules={[{ required: true }]}
              >
                <InputNumber min={0} precision={0} style={{ width: 180 }} />
              </Form.Item>
            </Space>
          )}
          <Form.Item
            label="处理依据"
            name="reason"
            rules={[
              { required: true, whitespace: true, message: "请填写核对依据" },
            ]}
          >
            <Input.TextArea
              rows={4}
              placeholder="例如：供应商后台请求记录显示未产生费用"
            />
          </Form.Item>
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button onClick={() => setSelected(undefined)}>取消</Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              提交对账结果
            </Button>
          </Space>
        </Form>
      </Modal>

      <Modal
        title="对账详情"
        open={Boolean(detail)}
        footer={null}
        width={760}
        onCancel={() => setDetail(undefined)}
      >
        {detail && (
          <>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="客户">
                {detail.order.owner_user_id
                  ? `${
                      userNames[detail.order.owner_user_id] ?? "未知账号"
                    }（ID ${detail.order.owner_user_id}）`
                  : "系统"}
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                {sourceLabels[detail.order.source] ?? detail.order.source}
              </Descriptions.Item>
              <Descriptions.Item label="Agent">
                {agentName(detail)}
              </Descriptions.Item>
              <Descriptions.Item label="应用">
                {detail.order.application?.name ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="模型">
                {detail.item.model}
              </Descriptions.Item>
              <Descriptions.Item label="供应商">
                {detail.item.provider}
              </Descriptions.Item>
              <Descriptions.Item label="待确认积分">
                {formatNumber(detail.item.quoted_credits)}
              </Descriptions.Item>
              <Descriptions.Item label="价格目录">
                {detail.item.catalog_version}
              </Descriptions.Item>
              <Descriptions.Item label="执行结果" span={2}>
                {outcomeLabels[detail.item.evidence.execution_outcome] ??
                  detail.item.evidence.execution_outcome}
              </Descriptions.Item>
              <Descriptions.Item label="对账编号" span={2}>
                {detail.reconciliation_id}
              </Descriptions.Item>
              <Descriptions.Item label="计费单号" span={2}>
                {detail.order.id}
              </Descriptions.Item>
            </Descriptions>
            <details style={{ marginTop: 16 }}>
              <summary>查看原始结构化详情</summary>
              <pre style={{ overflow: "auto", maxHeight: 320 }}>
                {JSON.stringify(detail, null, 2)}
              </pre>
            </details>
          </>
        )}
      </Modal>
    </Space>
  );
}
