import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  Database,
  Layers,
  Link2,
  RefreshCw,
  Trash2,
  UploadCloud,
} from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { request } from "../../../api";
import { getApiUrl } from "../../../api/config";
import { buildAuthHeaders } from "../../../api/authHeaders";

interface KnowledgeDoc {
  id: string;
  name: string;
  source_type: string;
  type?: string;
  source_url?: string;
  size: string;
  chunk_count?: number;
  slices?: number;
  status:
    | "pending"
    | "fetching"
    | "parsing"
    | "embedding"
    | "indexing"
    | "syncing"
    | "ready"
    | "failed";
  progress?: number;
  last_error?: string;
  lastError?: string;
  updated_at?: string;
  updatedAt?: string;
  category?: string;
  tags?: string[];
}

const KNOWLEDGE_CATEGORIES = [
  { value: "uncategorized", label: "未分类" },
  { value: "policy", label: "制度流程" },
  { value: "project", label: "项目资料" },
  { value: "product", label: "产品文档" },
  { value: "technology", label: "技术研发" },
  { value: "operations", label: "运营销售" },
  { value: "training", label: "培训学习" },
  { value: "other", label: "其他" },
] as const;

const categoryLabel = (value?: string) =>
  KNOWLEDGE_CATEGORIES.find((item) => item.value === value)?.label ||
  value ||
  "未分类";

export default function EnterpriseKnowledgePage() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [semanticSearchEnabled, setSemanticSearchEnabled] = useState(false);
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [editingDoc, setEditingDoc] = useState<KnowledgeDoc | null>(null);
  const [form] = Form.useForm();
  const [metadataForm] = Form.useForm();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchDocs = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const [res, capabilities] = await Promise.all([
        request<KnowledgeDoc[]>("/admin/knowledge/docs"),
        request<{
          semantic_search_enabled: boolean;
          embedding_model?: string;
        }>("/admin/knowledge/capabilities").catch(() => ({
          semantic_search_enabled: false,
          embedding_model: "",
        })),
      ]);
      setDocs(res || []);
      setSemanticSearchEnabled(Boolean(capabilities.semantic_search_enabled));
      setEmbeddingModel(capabilities.embedding_model || "");
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "加载企业智库失败",
      );
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDocs();
  }, [fetchDocs]);

  const hasWorkingDocs = docs.some((doc) =>
    [
      "pending",
      "fetching",
      "parsing",
      "embedding",
      "indexing",
      "syncing",
    ].includes(doc.status),
  );

  useEffect(() => {
    if (!hasWorkingDocs) return;
    const timer = window.setInterval(() => {
      void request<KnowledgeDoc[]>("/admin/knowledge/docs")
        .then((res) => setDocs(res || []))
        .catch((error) => console.error("企业知识状态轮询失败", error));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [hasWorkingDocs]);

  const uploadFile = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const headers = new Headers();
    for (const [key, value] of Object.entries(buildAuthHeaders())) {
      headers.set(key, value);
    }
    const response = await fetch(getApiUrl("/admin/knowledge/docs/upload"), {
      method: "POST",
      headers,
      body: formData,
    });
    if (!response.ok) {
      throw new Error(`上传失败：${response.status} ${response.statusText}`);
    }
    return (await response.json()) as KnowledgeDoc;
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const doc = await uploadFile(file);
      setDocs((prev) => [doc, ...prev.filter((item) => item.id !== doc.id)]);
      message.success("文件已上传，后台开始解析和建立索引");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "上传失败");
    } finally {
      event.target.value = "";
    }
  };

  const handleLink = async (values: {
    title: string;
    url: string;
    docType: "lark" | "tencent";
    cloudAccountId?: string;
    category?: string;
    tags?: string[];
  }) => {
    try {
      const doc = await request<KnowledgeDoc>("/admin/knowledge/docs/link", {
        method: "POST",
        body: JSON.stringify(values),
      });
      setDocs((prev) => [doc, ...prev.filter((item) => item.id !== doc.id)]);
      setLinkOpen(false);
      form.resetFields();
      if (doc.status === "failed") {
        message.warning(doc.last_error || doc.lastError || "云文档拉取失败");
      } else {
        message.success("企业云文档已开始同步");
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "关联失败");
    }
  };

  const handleMetadata = async (values: {
    category: string;
    tags?: string[];
  }) => {
    if (!editingDoc) return;
    try {
      const updated = await request<KnowledgeDoc>(
        `/admin/knowledge/docs/${editingDoc.id}/metadata`,
        {
          method: "PATCH",
          body: JSON.stringify({
            category: values.category || "uncategorized",
            tags: values.tags || [],
          }),
        },
      );
      setDocs((prev) =>
        prev.map((doc) => (doc.id === updated.id ? updated : doc)),
      );
      setEditingDoc(null);
      metadataForm.resetFields();
      message.success("企业知识分类与标签已更新");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "更新失败");
    }
  };

  const handleSync = async (doc: KnowledgeDoc) => {
    try {
      const updated = await request<KnowledgeDoc>(
        `/admin/knowledge/docs/${doc.id}/sync`,
        { method: "POST" },
      );
      setDocs((prev) =>
        prev.map((item) => (item.id === doc.id ? updated : item)),
      );
      message.success("已进入后台重新同步");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "同步失败");
    }
  };

  const handleDelete = async (doc: KnowledgeDoc) => {
    Modal.confirm({
      title: "移除企业知识",
      content: `确认删除「${doc.name}」及其切片、索引和 Wiki 沉淀吗？`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        await request(`/admin/knowledge/docs/${doc.id}`, { method: "DELETE" });
        setDocs((prev) => prev.filter((item) => item.id !== doc.id));
        message.success("已删除企业知识");
      },
    });
  };

  const columns: ColumnsType<KnowledgeDoc> = [
    {
      title: "文档",
      dataIndex: "name",
      render: (_, doc) => (
        <Space direction="vertical" size={2}>
          <span style={{ fontWeight: 600 }}>{doc.name}</span>
          {doc.source_url ? (
            <a href={doc.source_url} target="_blank" rel="noreferrer">
              {doc.source_url}
            </a>
          ) : null}
        </Space>
      ),
    },
    {
      title: "来源",
      width: 120,
      render: (_, doc) => (doc.source_type || doc.type || "txt").toUpperCase(),
    },
    {
      title: "分类与标签",
      width: 220,
      render: (_, doc) => (
        <Space size={[4, 4]} wrap>
          <Tag color="green">{categoryLabel(doc.category)}</Tag>
          {(doc.tags || []).map((tag) => (
            <Tag key={tag}>{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: "切片",
      width: 100,
      render: (_, doc) => doc.chunk_count ?? doc.slices ?? 0,
    },
    {
      title: "状态",
      width: 180,
      render: (_, doc) => {
        if (doc.status === "ready") return <Tag color="green">可检索</Tag>;
        if (doc.status === "failed") {
          return (
            <Space direction="vertical" size={2}>
              <Tag color="red">失败</Tag>
              <span style={{ fontSize: 12, color: "#ef4444" }}>
                {doc.last_error || doc.lastError || "未返回失败原因"}
              </span>
            </Space>
          );
        }
        const statusText: Record<string, string> = {
          pending: "等待处理",
          fetching: "拉取正文",
          parsing: "解析文本",
          embedding: "向量化",
          indexing: "写入索引",
          syncing: "等待同步",
        };
        return (
          <Tag color="blue">
            {statusText[doc.status] || "处理中"} {doc.progress ?? 0}%
          </Tag>
        );
      },
    },
    {
      title: "更新",
      width: 180,
      render: (_, doc) => doc.updated_at || doc.updatedAt || "-",
    },
    {
      title: "操作",
      width: 160,
      render: (_, doc) => (
        <Space>
          <Button
            size="small"
            icon={<RefreshCw size={13} />}
            disabled={[
              "pending",
              "fetching",
              "parsing",
              "embedding",
              "indexing",
              "syncing",
            ].includes(doc.status)}
            onClick={() => handleSync(doc)}
          />
          <Button
            size="small"
            icon={<Layers size={13} />}
            onClick={() => {
              setEditingDoc(doc);
              metadataForm.setFieldsValue({
                category: doc.category || "uncategorized",
                tags: doc.tags || [],
              });
            }}
          />
          <Button
            size="small"
            danger
            icon={<Trash2 size={13} />}
            onClick={() => handleDelete(doc)}
          />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <PageHeader parent="设置" current="企业智库" />
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        accept=".pdf,.docx,.pptx,.xlsx,.xls,.csv,.md,.txt,.png,.jpg,.jpeg,.webp"
        onChange={handleUpload}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <Space>
          <Database size={18} />
          <span style={{ color: "rgba(0,0,0,0.62)" }}>
            admin 维护企业知识库；所有登录用户可在任务和对话中检索。
          </span>
          <Tag color={semanticSearchEnabled ? "green" : "default"}>
            {semanticSearchEnabled
              ? `语义混合检索${embeddingModel ? ` · ${embeddingModel}` : ""}`
              : "关键词检索"}
          </Tag>
        </Space>
        <Space>
          <Button
            icon={<UploadCloud size={14} />}
            onClick={() => fileInputRef.current?.click()}
          >
            上传资料
          </Button>
          <Button
            type="primary"
            icon={<Link2 size={14} />}
            onClick={() => setLinkOpen(true)}
          >
            关联云文档
          </Button>
        </Space>
      </div>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={docs}
        columns={columns}
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title="关联企业云文档"
        open={linkOpen}
        onCancel={() => setLinkOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            docType: "lark",
            category: "uncategorized",
            tags: [],
          }}
          onFinish={handleLink}
        >
          <Form.Item
            name="docType"
            label="文档平台"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "lark", label: "飞书文档" },
                { value: "tencent", label: "腾讯文档" },
              ]}
            />
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="url"
            label="共享链接"
            rules={[{ required: true, type: "url" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="cloudAccountId"
            label="授权账号 ID"
            extra="使用 admin 已授权账号或企业服务账号。未填写时后端会明确返回授权失败。"
          >
            <Input placeholder="例如 lark-1-admin" />
          </Form.Item>
          <Form.Item name="category" label="业务分类">
            <Select options={[...KNOWLEDGE_CATEGORIES]} />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              tokenSeparators={[",", "，"]}
              placeholder="输入标签后回车"
            />
          </Form.Item>
          <div style={{ textAlign: "right" }}>
            <Space>
              <Button onClick={() => setLinkOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">
                开始同步
              </Button>
            </Space>
          </div>
        </Form>
      </Modal>

      <Modal
        title={`编辑分类与标签${editingDoc ? `：${editingDoc.name}` : ""}`}
        open={Boolean(editingDoc)}
        onCancel={() => {
          setEditingDoc(null);
          metadataForm.resetFields();
        }}
        footer={null}
        destroyOnClose
      >
        <Form form={metadataForm} layout="vertical" onFinish={handleMetadata}>
          <Form.Item name="category" label="业务分类">
            <Select options={[...KNOWLEDGE_CATEGORIES]} />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              tokenSeparators={[",", "，"]}
              placeholder="输入标签后回车"
            />
          </Form.Item>
          <div style={{ textAlign: "right" }}>
            <Space>
              <Button onClick={() => setEditingDoc(null)}>取消</Button>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
            </Space>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
