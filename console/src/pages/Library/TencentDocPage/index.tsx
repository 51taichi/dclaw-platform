import { useCallback, useEffect, useRef, useState } from "react";
import {
  Input,
  Button,
  Modal,
  Form,
  message,
  Dropdown,
  Segmented,
  Select,
  Tag,
  type MenuProps,
} from "antd";
import {
  FileText,
  Cloud,
  Database,
  UploadCloud,
  RefreshCw,
  Plus,
  Trash2,
  ExternalLink,
  Layers,
  Search,
  MoreVertical,
  CheckCircle2,
} from "lucide-react";
import styles from "./TencentDocPage.module.less";
import { request as apiRequest } from "../../../api";
import type { ApiRequestOptions } from "../../../api/request";
import { getApiUrl } from "../../../api/config";
import { buildAuthHeaders } from "../../../api/authHeaders";
import { AgentExperienceLibrary } from "@/components/AgentExperienceLibrary";

// This page manages the signed-in user's library, not selected Agent assets.
function request<T = unknown>(path: string, options: ApiRequestOptions = {}) {
  return apiRequest<T>(path, { ...options, includeSelectedAgent: false });
}

interface DocItem {
  id: string;
  name: string;
  type:
    | "tencent"
    | "lark"
    | "pdf"
    | "docx"
    | "pptx"
    | "xlsx"
    | "csv"
    | "md"
    | "txt"
    | "png"
    | "jpg"
    | "jpeg"
    | "webp"
    | "wiki";
  source_type?: DocItem["type"];
  scope?: "enterprise" | "personal" | "global" | "agent";
  url?: string;
  source_url?: string;
  size: string;
  slices: number;
  chunk_count?: number;
  status:
    | "pending"
    | "fetching"
    | "parsing"
    | "embedding"
    | "indexing"
    | "ready"
    | "failed"
    | "syncing";
  progress?: number;
  stage?: 1 | 2 | 3; // 1: 切片中, 2: 向量化中, 3: 写入索引中
  updatedAt: string;
  updated_at?: string;
  last_error?: string;
  lastError?: string;
  category?: string;
  tags?: string[];
}

interface ConnectorStatus {
  provider: "lark" | "tencent";
  configured: boolean;
  status: string;
  message: string;
}

interface CloudAccount {
  id: string;
  provider: "lark" | "tencent";
  provider_user_id?: string;
  display_name?: string;
  status: string;
  updated_at?: string;
  has_access_token?: boolean;
}

interface CloudProviderState {
  provider: "lark" | "tencent";
  configured: boolean;
  enabled: boolean;
  connector_url?: string;
  accounts: CloudAccount[];
}

interface MindspaceHit {
  doc_id: string;
  doc_name: string;
  chunk_id: string;
  text: string;
  score: number;
  scope: "enterprise" | "personal" | "global" | "agent";
  source_url?: string;
  locator?: string;
  match_reason?: string;
  context?: string;
  citation?: string;
  rank?: number;
}

interface WikiConcept {
  concept: string;
  scope?: DocItem["scope"];
  size?: number;
  modified_time?: string;
  updated_at?: string;
}

type KnowledgeScope = "all" | "enterprise" | "personal" | "agent-experience";

const KNOWLEDGE_SCOPE_OPTIONS = [
  { value: "personal", label: "我的知识库" },
  { value: "agent-experience", label: "我的Agent经验库" },
  { value: "enterprise", label: "企业知识库" },
  { value: "all", label: "跨库检索" },
];

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

const isWorkingStatus = (status: DocItem["status"]) =>
  [
    "pending",
    "fetching",
    "parsing",
    "embedding",
    "indexing",
    "syncing",
  ].includes(status);

const statusLabel = (status: DocItem["status"]) => {
  if (status === "fetching") return "拉取正文";
  if (status === "parsing") return "解析文本";
  if (status === "embedding") return "向量化";
  if (status === "indexing") return "写入索引";
  if (status === "pending") return "等待处理";
  return "处理中";
};

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

export default function TencentDocPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [mindspaceQuery, setMindspaceQuery] = useState("");
  const [mindspaceHits, setMindspaceHits] = useState<MindspaceHit[]>([]);
  const [semanticSearchEnabled, setSemanticSearchEnabled] = useState(false);
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [activeTab, setActiveTab] = useState("all"); // all, tencent, lark, local, wiki
  const [activeScope, setActiveScope] = useState<KnowledgeScope>("personal");
  const [activeCategory, setActiveCategory] = useState("all");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [isUploadMetadataModalOpen, setIsUploadMetadataModalOpen] =
    useState(false);
  const [pendingUploadFile, setPendingUploadFile] = useState<File | null>(null);
  const [isUploadSubmitting, setIsUploadSubmitting] = useState(false);
  const [editingDoc, setEditingDoc] = useState<DocItem | null>(null);
  const [isLinkModalOpen, setIsLinkModalOpen] = useState(false);
  const [isWikiModalOpen, setIsWikiModalOpen] = useState(false);
  const [currentWikiContent, setCurrentWikiContent] = useState("");
  const [currentWikiTitle, setCurrentWikiTitle] = useState("");
  const [form] = Form.useForm();
  const [uploadForm] = Form.useForm();
  const [metadataForm] = Form.useForm();
  const selectedDocType = Form.useWatch("docType", form) as
    | "lark"
    | "tencent"
    | undefined;

  const [documents, setDocuments] = useState<DocItem[]>([]);
  const [wikiDocuments, setWikiDocuments] = useState<DocItem[]>([]);
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [cloudProviders, setCloudProviders] = useState<CloudProviderState[]>(
    [],
  );
  const [cloudAccounts, setCloudAccounts] = useState<CloudAccount[]>([]);
  const [loading, setLoading] = useState(false);

  // Hidden native file input reference
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load documents on mount
  const fetchDocuments = useCallback(
    async (showLoading = false) => {
      if (activeScope === "agent-experience") return;
      if (showLoading) setLoading(true);
      try {
        const [resDocs, resWiki, resConnectors, resCloudAuth, resCapabilities] =
          await Promise.all([
            request<DocItem[]>(
              `/workspace/knowledge/docs?scope=${activeScope}`,
            ),
            request<{ concepts: WikiConcept[] }>(
              `/workspace/wiki/list?scope=${activeScope}`,
            ).catch(() => ({ concepts: [] })),
            request<{ connectors: ConnectorStatus[] }>(
              "/workspace/mindspace/connectors",
            ).catch(() => ({ connectors: [] })),
            request<{
              providers: CloudProviderState[];
              accounts: CloudAccount[];
            }>("/user/mindspace-cloud/accounts").catch(() => ({
              providers: [],
              accounts: [],
            })),
            request<{
              semantic_search_enabled: boolean;
              embedding_model?: string;
            }>("/workspace/knowledge/capabilities").catch(() => ({
              semantic_search_enabled: false,
              embedding_model: "",
            })),
          ]);
        setDocuments(resDocs);

        const wikiDocs: DocItem[] = (resWiki.concepts || []).map((c) => ({
          id: "wiki-" + c.concept,
          name: c.concept + ".md",
          type: "wiki",
          scope: c.scope,
          size: c.size ? (c.size / 1024).toFixed(1) + " KB" : "Wiki",
          slices: 1,
          status: "ready",
          updatedAt: c.modified_time
            ? new Date(c.modified_time).toLocaleString()
            : c.updated_at || "",
        }));
        setWikiDocuments(wikiDocs);
        setConnectors(resConnectors.connectors || []);
        setCloudProviders(resCloudAuth.providers || []);
        setCloudAccounts(resCloudAuth.accounts || []);
        setSemanticSearchEnabled(
          Boolean(resCapabilities.semantic_search_enabled),
        );
        setEmbeddingModel(resCapabilities.embedding_model || "");
      } catch (err: unknown) {
        console.error("Failed to load documents:", err);
        message.error("获取知识库文档失败: " + errorMessage(err));
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [activeScope],
  );

  useEffect(() => {
    if (activeScope !== "agent-experience") {
      fetchDocuments(true);
    }
  }, [activeScope, fetchDocuments]);

  const handleViewWiki = async (
    conceptName: string,
    scope?: DocItem["scope"],
  ) => {
    try {
      const res = await request<{ concept: string; content: string }>(
        `/workspace/wiki/${conceptName}?scope=${scope || "personal"}`,
      );
      setCurrentWikiTitle(res.concept);
      setCurrentWikiContent(res.content);
      setIsWikiModalOpen(true);
    } catch (err: unknown) {
      message.error("无法加载 Wiki 内容: " + errorMessage(err));
    }
  };

  // Poll state when any document is in syncing status
  useEffect(() => {
    const hasSyncing = documents.some((doc) => isWorkingStatus(doc.status));
    if (!hasSyncing) return;

    const timer = setInterval(async () => {
      try {
        const res = await request<DocItem[]>(
          `/workspace/knowledge/docs?scope=${activeScope}`,
        );
        setDocuments(res);
      } catch (err) {
        console.error("Error polling syncing status:", err);
      }
    }, 1500);

    return () => clearInterval(timer);
  }, [documents, activeScope]);

  // Handle document manual synchronization
  const handleSync = async (id: string) => {
    try {
      setDocuments((prev) =>
        prev.map((doc) => {
          if (doc.id === id) {
            return {
              ...doc,
              status: "syncing",
              progress: 10,
              stage: 1,
            };
          }
          return doc;
        }),
      );

      await request<DocItem>("/workspace/knowledge/sync", {
        method: "POST",
        body: JSON.stringify({
          id,
          scope: activeScope === "all" ? undefined : activeScope,
        }),
      });

      message.info("已向后端发起重新同步请求");
    } catch (err: unknown) {
      message.error("同步失败: " + errorMessage(err));
      fetchDocuments();
    }
  };

  // Handle document removal
  const handleDelete = (id: string, name: string) => {
    Modal.confirm({
      title: "确认移除文档",
      content: `确认要从知识库中移除「${name}」吗？相关切片、索引和 Wiki 沉淀也会同步清理。`,
      okText: "确认移除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await request(
            `/workspace/knowledge/docs/${id}?scope=${activeScope}`,
            {
              method: "DELETE",
            },
          );
          setDocuments((prev) => prev.filter((doc) => doc.id !== id));
          message.success("已成功从共享知识库中移出该文档");
        } catch (err: unknown) {
          message.error("移除文档失败: " + errorMessage(err));
        }
      },
    });
  };

  // Select a local file first, then confirm its business metadata before upload.
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 50 * 1024 * 1024) {
      message.error("上传失败：文件过大，单文件上限 50MB");
      e.target.value = "";
      return;
    }

    const suffix = file.name.split(".").pop()?.toLowerCase() || "";
    if (
      ![
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "xls",
        "csv",
        "md",
        "txt",
        "png",
        "jpg",
        "jpeg",
        "webp",
      ].includes(suffix)
    ) {
      message.error(
        "格式不支持：支持 PDF, DOCX, PPTX, Excel, CSV, Markdown, TXT 和常见图片格式",
      );
      e.target.value = "";
      return;
    }

    setPendingUploadFile(file);
    uploadForm.setFieldsValue({
      category: activeCategory === "all" ? "uncategorized" : activeCategory,
      tags: activeTags,
    });
    setIsUploadMetadataModalOpen(true);
    e.target.value = "";
  };

  const handleUploadSubmit = async (values: {
    category: string;
    tags?: string[];
  }) => {
    const file = pendingUploadFile;
    if (!file) {
      message.error("请重新选择要上传的文件");
      return;
    }

    try {
      setIsUploadMetadataModalOpen(false);
      setIsUploadSubmitting(true);
      message.loading({
        key: "knowledge-file-upload",
        content: `正在上传「${file.name}」...`,
        duration: 0,
      });

      const formData = new FormData();
      formData.append("file", file);

      const params = new URLSearchParams({
        scope: activeScope === "enterprise" ? "enterprise" : "personal",
        category: values.category || "uncategorized",
      });
      if (values.tags?.length) params.set("tags", values.tags.join(","));
      const uploadUrl = getApiUrl(
        `/workspace/knowledge/upload?${params.toString()}`,
      );
      const headers = new Headers();
      for (const [key, value] of Object.entries(buildAuthHeaders())) {
        if (key.toLowerCase() !== "x-agent-id") headers.set(key, value);
      }

      const response = await fetch(uploadUrl, {
        method: "POST",
        headers,
        body: formData,
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(
          detail || "上传物理网关返回异常: " + response.statusText,
        );
      }

      const newDoc = (await response.json()) as DocItem;
      setDocuments((prev) => [newDoc, ...prev]);
      message.success({
        key: "knowledge-file-upload",
        content: `「${file.name}」已提交，后台正在解析和建立索引`,
        duration: 4,
      });
    } catch (err: unknown) {
      console.error(err);
      message.error({
        key: "knowledge-file-upload",
        content: "上传本地文档失败: " + errorMessage(err),
        duration: 6,
      });
    } finally {
      setIsUploadSubmitting(false);
      setPendingUploadFile(null);
      uploadForm.resetFields();
    }
  };

  // Link cloud document and invoke OAuth backend pull
  const handleLinkSubmit = async (values: {
    title: string;
    url: string;
    docType: "tencent" | "lark";
    cloudAccountId: string;
    category: string;
    tags?: string[];
  }) => {
    try {
      setIsLinkModalOpen(false);
      const newDoc = await request<DocItem>("/workspace/knowledge/link", {
        method: "POST",
        body: JSON.stringify({
          title: values.title,
          url: values.url,
          docType: values.docType,
          cloudAccountId: values.cloudAccountId,
          scope: activeScope === "enterprise" ? "enterprise" : "personal",
          category: values.category || "uncategorized",
          tags: values.tags || [],
        }),
      });

      setDocuments((prev) => [newDoc, ...prev]);
      form.resetFields();
      if (newDoc.status === "failed") {
        message.warning(
          `云文档已记录，但未完成拉取：${
            newDoc.last_error || newDoc.lastError || "连接器未配置"
          }`,
        );
      } else {
        message.success(`已关联云文档「${values.title}」，开始同步真实正文`);
      }
    } catch (err: unknown) {
      message.error("关联云文档失败: " + errorMessage(err));
    }
  };

  const openMetadataEditor = (doc: DocItem) => {
    setEditingDoc(doc);
    metadataForm.setFieldsValue({
      category: doc.category || "uncategorized",
      tags: doc.tags || [],
    });
  };

  const handleMetadataSubmit = async (values: {
    category: string;
    tags?: string[];
  }) => {
    if (!editingDoc) return;
    try {
      const scope =
        editingDoc.scope === "enterprise" || editingDoc.scope === "global"
          ? "enterprise"
          : "personal";
      const updated = await request<DocItem>(
        `/workspace/knowledge/docs/${editingDoc.id}/metadata?scope=${scope}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            category: values.category || "uncategorized",
            tags: values.tags || [],
          }),
        },
      );
      setDocuments((prev) =>
        prev.map((doc) => (doc.id === updated.id ? updated : doc)),
      );
      setEditingDoc(null);
      metadataForm.resetFields();
      message.success("分类与标签已更新，无需重新向量化");
    } catch (err: unknown) {
      message.error("更新分类标签失败: " + errorMessage(err));
    }
  };

  const handleFormValuesChange = (changedValues: {
    docType?: "tencent" | "lark";
    url?: string;
  }) => {
    if (changedValues.docType) {
      form.setFieldsValue({ cloudAccountId: undefined });
    }
    if (changedValues.url) {
      const url = changedValues.url.toLowerCase();
      const currentType = form.getFieldValue("docType");
      if (
        (url.includes("feishu.cn") || url.includes("lark")) &&
        currentType !== "lark"
      ) {
        form.setFieldsValue({ docType: "lark", cloudAccountId: undefined });
      } else if (url.includes("docs.qq.com") && currentType !== "tencent") {
        form.setFieldsValue({
          docType: "tencent",
          cloudAccountId: undefined,
        });
      }
    }
  };

  // Filtered documents
  const allDocs = [...documents, ...wikiDocuments];
  const availableTags = Array.from(
    new Set(documents.flatMap((doc) => doc.tags || [])),
  ).sort((a, b) => a.localeCompare(b, "zh-CN"));
  const filteredDocs = allDocs.filter((doc) => {
    // Search filter
    const matchesSearch = doc.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());
    const matchesCategory =
      activeCategory === "all" ||
      (doc.category || "uncategorized") === activeCategory;
    const docTags = new Set((doc.tags || []).map((tag) => tag.toLowerCase()));
    const matchesTags = activeTags.every((tag) =>
      docTags.has(tag.toLowerCase()),
    );
    if (!matchesSearch || !matchesCategory || !matchesTags) return false;

    // Tab filter
    if (activeTab === "tencent") {
      return doc.type === "tencent";
    }
    if (activeTab === "lark") {
      return doc.type === "lark";
    }
    if (activeTab === "wiki") {
      return doc.type === "wiki";
    }
    if (activeTab === "local") {
      return (
        doc.type !== "tencent" && doc.type !== "lark" && doc.type !== "wiki"
      );
    }
    return matchesSearch;
  });

  // Calculate totals
  const totalDocs = allDocs.length;
  const totalSlices = allDocs.reduce(
    (sum, doc) => sum + (doc.chunk_count ?? doc.slices),
    0,
  );
  const readyDocs = documents.filter((doc) => doc.status === "ready").length;
  const failedDocs = documents.filter((doc) => doc.status === "failed").length;
  const isSyncingAny = documents.some((doc) => isWorkingStatus(doc.status));
  const larkConnector = connectors.find((item) => item.provider === "lark");
  const tencentConnector = connectors.find(
    (item) => item.provider === "tencent",
  );
  const larkProvider = cloudProviders.find((item) => item.provider === "lark");
  const tencentProvider = cloudProviders.find(
    (item) => item.provider === "tencent",
  );
  const larkAccounts = cloudAccounts.filter((item) => item.provider === "lark");
  const tencentAccounts = cloudAccounts.filter(
    (item) => item.provider === "tencent",
  );
  const selectedProvider =
    cloudProviders.find((item) => item.provider === selectedDocType) ||
    undefined;
  const selectedConnector =
    connectors.find((item) => item.provider === selectedDocType) || undefined;
  const selectedProviderName =
    selectedDocType === "tencent" ? "腾讯文档" : "飞书文档";
  const selectedProviderConfigured = Boolean(selectedProvider?.configured);
  const selectedConnectorStatus = selectedConnector?.status || "";
  const selectedProviderAccounts =
    selectedDocType === "lark"
      ? larkAccounts
      : selectedDocType === "tencent"
      ? tencentAccounts
      : [];

  const handleMindspaceSearch = async () => {
    if (!mindspaceQuery.trim()) return;
    const params = new URLSearchParams({
      q: mindspaceQuery,
      scope: activeScope,
      top_k: "5",
    });
    if (activeCategory !== "all") params.set("category", activeCategory);
    if (activeTags.length > 0) params.set("tags", activeTags.join(","));
    const res = await request<{
      hits: MindspaceHit[];
      semantic_search_enabled: boolean;
      embedding_model?: string;
    }>(`/workspace/knowledge/search?${params.toString()}`);
    setMindspaceHits(res.hits || []);
    setSemanticSearchEnabled(Boolean(res.semantic_search_enabled));
    setEmbeddingModel(res.embedding_model || "");
  };

  const handleAuthorizeProvider = async (provider: "lark" | "tencent") => {
    try {
      const res = await request<{ authorization_url: string }>(
        `/user/mindspace-cloud/accounts/${provider}/authorize-url`,
        { method: "POST" },
      );
      window.open(res.authorization_url, "_blank", "noopener,noreferrer");
      message.info("授权完成后返回本页刷新授权状态");
    } catch (err: unknown) {
      message.error("生成授权链接失败: " + errorMessage(err));
    }
  };

  if (activeScope === "agent-experience") {
    return (
      <div className={styles.pageContainer}>
        <div className={styles.pageHeader}>
          <div className={styles.pageHeaderLeft}>
            <div className={styles.pageTitle}>
              <span className={styles.pageTitleIcon}>
                <Database size={18} />
              </span>
              我的Agent经验库
            </div>
            <div className={styles.pageSubtitle}>
              维护绑定到当前账号的 Agent 对外经验；接口禁用后仍可继续整理。
            </div>
          </div>
          <div className={styles.headerActions}>
            <Segmented
              value={activeScope}
              options={KNOWLEDGE_SCOPE_OPTIONS}
              onChange={(value) => setActiveScope(value as KnowledgeScope)}
            />
          </div>
        </div>
        <div className={styles.experiencePanel}>
          <AgentExperienceLibrary />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.pageContainer}>
      {/* Hidden file input */}
      <input
        type="file"
        ref={fileInputRef}
        style={{ display: "none" }}
        accept=".pdf,.docx,.pptx,.xlsx,.xls,.csv,.md,.txt,.png,.jpg,.jpeg,.webp"
        onChange={handleFileChange}
      />

      {/* Page Header */}
      <div className={styles.pageHeader}>
        <div className={styles.pageHeaderLeft}>
          <div className={styles.pageTitle}>
            <span className={styles.pageTitleIcon}>
              <Cloud size={18} />
            </span>
            {activeScope === "personal"
              ? "我的知识库"
              : activeScope === "enterprise"
              ? "企业知识库"
              : "跨库检索"}
          </div>
          <div className={styles.pageSubtitle}>
            默认只展示当前用户的个人资料；可切换企业知识库或跨库检索。
            飞书/腾讯文档使用当前用户授权拉取真实正文。
          </div>
        </div>

        <div className={styles.headerActions}>
          <Segmented
            value={activeScope}
            options={KNOWLEDGE_SCOPE_OPTIONS}
            onChange={(value) => setActiveScope(value as KnowledgeScope)}
          />
          <button
            className={styles.secondaryBtn}
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploadSubmitting}
          >
            <UploadCloud size={14} />
            {isUploadSubmitting ? "正在上传文件" : "上传本地文档"}
          </button>
          <button
            className={styles.primaryBtn}
            onClick={() => setIsLinkModalOpen(true)}
          >
            <Plus size={14} /> 关联云文档
          </button>
        </div>
      </div>

      {/* RAG Stat Dashboard */}
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span className={styles.statTitle}>知识库挂载节点</span>
            <span className={styles.statIcon}>
              <Database size={16} />
            </span>
          </div>
          <div className={styles.statValue}>
            {totalDocs}{" "}
            <span style={{ fontSize: "14px", fontWeight: "normal" }}>
              个挂载
            </span>
          </div>
          <div className={styles.statDesc}>
            企业: {documents.filter((d) => d.scope === "enterprise").length} ·
            个人: {documents.filter((d) => d.scope === "personal").length} ·
            Wiki: {wikiDocuments.length}
          </div>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span className={styles.statTitle}>切片块与检索能力</span>
            <span className={styles.statIcon}>
              <Layers size={16} />
            </span>
          </div>
          <div className={styles.statValue}>
            {totalSlices}{" "}
            <span style={{ fontSize: "14px", fontWeight: "normal" }}>
              个 Block
            </span>
          </div>
          <div className={styles.statDesc}>
            {semanticSearchEnabled
              ? `语义 + 关键词混合检索${
                  embeddingModel ? ` · ${embeddingModel}` : ""
                }`
              : "当前为关键词检索，未启用语义向量"}
          </div>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span className={styles.statTitle}>同步状态</span>
            <span className={styles.statIcon}>
              {isSyncingAny ? (
                <RefreshCw size={16} className="animate-spin" />
              ) : (
                <CheckCircle2 size={16} style={{ color: "#10b981" }} />
              )}
            </span>
          </div>
          <div className={styles.statValue}>
            {isSyncingAny
              ? "处理中"
              : failedDocs > 0
              ? `${failedDocs} 个失败`
              : "可检索"}
          </div>
          <div className={styles.statDesc}>
            {isSyncingAny ? (
              <div className={styles.pulseWrapper}>
                <span
                  className={`${styles.pulseDot} ${styles.pulseDotWarning}`}
                />
                <span>拉取/解析/索引进行中</span>
              </div>
            ) : (
              <div className={styles.pulseWrapper}>
                <span className={styles.pulseDot} />
                <span>
                  就绪 {readyDocs} 个 · 失败 {failedDocs} 个
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className={styles.toolbar} style={{ alignItems: "stretch" }}>
        <div style={{ flex: 1, display: "flex", gap: 8 }}>
          <Input
            placeholder="检索知识库片段..."
            value={mindspaceQuery}
            onChange={(event) => setMindspaceQuery(event.target.value)}
            onPressEnter={handleMindspaceSearch}
          />
          <Button icon={<Search size={14} />} onClick={handleMindspaceSearch}>
            检索预览
          </Button>
        </div>
        <div
          style={{
            fontSize: 12,
            color: "rgba(0,0,0,0.55)",
            display: "flex",
            gap: 12,
            alignItems: "center",
          }}
        >
          <span>
            飞书：
            {larkProvider?.configured || larkConnector?.configured
              ? "应用已配置"
              : "应用未配置"}{" "}
            · 授权 {larkAccounts.length}
          </span>
          <span>
            腾讯：
            {tencentProvider?.configured || tencentConnector?.configured
              ? "应用已配置"
              : "应用未配置"}{" "}
            · 授权 {tencentAccounts.length}
          </span>
        </div>
      </div>

      {mindspaceHits.length > 0 && (
        <div className={styles.tableWrapper} style={{ marginBottom: 14 }}>
          <div
            style={{
              padding: "14px 18px",
              borderBottom: "1px solid rgba(0,0,0,0.06)",
              fontWeight: 600,
            }}
          >
            检索结果
          </div>
          {mindspaceHits.map((hit) => (
            <div
              key={hit.chunk_id}
              style={{
                padding: "12px 18px",
                borderBottom: "1px solid rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {hit.citation || hit.doc_name} ·{" "}
                {hit.scope === "enterprise" || hit.scope === "global"
                  ? "企业知识库"
                  : "我的知识库"}{" "}
                · score {hit.score}
              </div>
              {hit.match_reason ? (
                <div
                  style={{
                    marginTop: 4,
                    fontSize: 11,
                    color: "rgba(0,0,0,0.42)",
                  }}
                >
                  匹配依据：{hit.match_reason}
                </div>
              ) : null}
              <div
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  color: "rgba(0,0,0,0.62)",
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                }}
              >
                {hit.context || hit.text}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filter and Search Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.searchWrapper}>
          <span className={styles.searchIcon}>
            <Search size={14} />
          </span>
          <input
            className={styles.searchInput}
            placeholder="搜索知识库内文档..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <Select
          value={activeCategory}
          style={{ width: 136 }}
          options={[
            { value: "all", label: "全部分类" },
            ...KNOWLEDGE_CATEGORIES,
          ]}
          onChange={setActiveCategory}
        />
        <Select
          mode="multiple"
          allowClear
          value={activeTags}
          style={{ minWidth: 180, maxWidth: 280 }}
          placeholder="按标签筛选"
          options={availableTags.map((tag) => ({ value: tag, label: tag }))}
          onChange={setActiveTags}
        />

        <div className={styles.filterTabs}>
          <button
            className={`${styles.filterTab} ${
              activeTab === "all" ? styles.filterTabActive : ""
            }`}
            onClick={() => setActiveTab("all")}
          >
            全部文件 ({totalDocs})
          </button>
          <button
            className={`${styles.filterTab} ${
              activeTab === "lark" ? styles.filterTabActive : ""
            }`}
            onClick={() => setActiveTab("lark")}
          >
            飞书文档 ({documents.filter((d) => d.type === "lark").length})
          </button>
          <button
            className={`${styles.filterTab} ${
              activeTab === "tencent" ? styles.filterTabActive : ""
            }`}
            onClick={() => setActiveTab("tencent")}
          >
            腾讯文档 ({documents.filter((d) => d.type === "tencent").length})
          </button>
          <button
            className={`${styles.filterTab} ${
              activeTab === "wiki" ? styles.filterTabActive : ""
            }`}
            onClick={() => setActiveTab("wiki")}
          >
            Wiki 词条 ({wikiDocuments.length})
          </button>
          <button
            className={`${styles.filterTab} ${
              activeTab === "local" ? styles.filterTabActive : ""
            }`}
            onClick={() => setActiveTab("local")}
          >
            本地文档 (
            {
              documents.filter((d) => d.type !== "tencent" && d.type !== "lark")
                .length
            }
            )
          </button>
        </div>
      </div>

      {/* Documents List Panel */}
      <div className={styles.tableWrapper}>
        <div className={styles.docList}>
          <div className={styles.docRowHeader}>
            <div>文档名称</div>
            <div>来源/格式</div>
            <div>大小/规格</div>
            <div>切片块数</div>
            <div>同步状态</div>
          </div>

          {loading ? (
            <div
              style={{
                padding: "60px",
                textAlign: "center",
                color: "rgba(0,0,0,0.45)",
                fontSize: "14px",
              }}
            >
              <RefreshCw
                size={18}
                className="animate-spin"
                style={{ marginRight: "8px", verticalAlign: "middle" }}
              />
              正在安全检索 RAG 节点列表...
            </div>
          ) : filteredDocs.length === 0 ? (
            <div
              style={{
                padding: "60px",
                textAlign: "center",
                color: "rgba(0,0,0,0.35)",
                fontSize: "14px",
              }}
            >
              没有找到匹配的知识库文件
            </div>
          ) : (
            filteredDocs.map((doc) => {
              const menuItems: MenuProps["items"] = [
                {
                  key: "sync",
                  label: "重新同步",
                  icon: <RefreshCw size={12} />,
                  disabled: isWorkingStatus(doc.status),
                  onClick: () => handleSync(doc.id),
                },
                doc.type !== "wiki" &&
                (doc.scope === "personal" || doc.scope === "agent")
                  ? {
                      key: "metadata",
                      label: "编辑分类与标签",
                      icon: <Layers size={12} />,
                      onClick: () => openMetadataEditor(doc),
                    }
                  : null,
                doc.type === "wiki"
                  ? {
                      key: "view_wiki",
                      label: "查看 Wiki 词条",
                      icon: <ExternalLink size={12} />,
                      onClick: () =>
                        handleViewWiki(doc.name.replace(".md", ""), doc.scope),
                    }
                  : null,
                (doc.url || doc.source_url) && doc.type !== "wiki"
                  ? {
                      key: "view",
                      label: "在新窗口打开",
                      icon: <ExternalLink size={12} />,
                      onClick: () =>
                        window.open(doc.url || doc.source_url, "_blank"),
                    }
                  : null,
                doc.type !== "wiki"
                  ? {
                      key: "delete",
                      label: (
                        <span style={{ color: "#ff4d4f" }}>移除知识库</span>
                      ),
                      icon: <Trash2 size={12} style={{ color: "#ff4d4f" }} />,
                      onClick: () => handleDelete(doc.id, doc.name),
                    }
                  : null,
              ].filter(Boolean) as MenuProps["items"];

              return (
                <div key={doc.id} className={styles.docRow}>
                  {/* Name column */}
                  <div className={styles.docCellName}>
                    <div className={styles.docIconWrapper}>
                      <FileText size={18} />
                    </div>
                    <div className={styles.docInfo}>
                      {doc.url || doc.source_url ? (
                        <a
                          href={doc.url || doc.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.docTitle}
                          style={{ display: "block" }}
                        >
                          {doc.name}
                        </a>
                      ) : (
                        <div className={styles.docTitle}>{doc.name}</div>
                      )}
                      {doc.url || doc.source_url ? (
                        <a
                          href={doc.url || doc.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.docLink}
                        >
                          {doc.url || doc.source_url} <ExternalLink size={10} />
                        </a>
                      ) : (
                        <div
                          style={{
                            fontSize: "11px",
                            color: "rgba(0,0,0,0.35)",
                          }}
                        >
                          更新时间: {doc.updatedAt || doc.updated_at}
                        </div>
                      )}
                      <div
                        style={{ fontSize: "11px", color: "rgba(0,0,0,0.35)" }}
                      >
                        {doc.scope === "enterprise" || doc.scope === "global"
                          ? "企业知识库"
                          : doc.scope === "personal" || doc.scope === "agent"
                          ? "我的知识库"
                          : ""}
                      </div>
                      <div
                        style={{
                          marginTop: 4,
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 4,
                        }}
                      >
                        <Tag color="green" style={{ marginInlineEnd: 0 }}>
                          {categoryLabel(doc.category)}
                        </Tag>
                        {(doc.tags || []).map((tag) => (
                          <Tag key={tag} style={{ marginInlineEnd: 0 }}>
                            {tag}
                          </Tag>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Format column */}
                  <div className={styles.docCellType}>
                    {doc.type === "tencent" ? (
                      <span style={{ color: "#1890ff", fontWeight: 500 }}>
                        腾讯文档
                      </span>
                    ) : doc.type === "lark" ? (
                      <span style={{ color: "#10b981", fontWeight: 500 }}>
                        飞书文档
                      </span>
                    ) : (
                      doc.type.toUpperCase()
                    )}
                  </div>

                  {/* Size column */}
                  <div className={styles.docCellSize}>{doc.size}</div>

                  {/* Slices column */}
                  <div className={styles.docCellSlices}>
                    {doc.chunk_count ?? doc.slices} 个 Block
                  </div>

                  {/* Status column */}
                  <div className={styles.docCellStatus}>
                    <div style={{ flex: 1 }}>
                      {doc.status === "ready" ? (
                        <div
                          className={`${styles.statusIndicator} ${styles.statusIndicator_ready}`}
                        >
                          <span
                            className={`${styles.statusDot} ${styles.statusDot_ready}`}
                          />
                          已就绪
                        </div>
                      ) : doc.status === "failed" ? (
                        <div>
                          <div
                            className={`${styles.statusIndicator} ${styles.statusIndicator_failed}`}
                          >
                            <span
                              className={`${styles.statusDot} ${styles.statusDot_failed}`}
                            />
                            同步失败
                          </div>
                          <div
                            style={{
                              marginTop: 4,
                              maxWidth: 180,
                              fontSize: 10,
                              color: "#ef4444",
                              lineHeight: 1.4,
                            }}
                          >
                            {doc.last_error ||
                              doc.lastError ||
                              "后端未返回失败原因"}
                          </div>
                        </div>
                      ) : (
                        <div
                          className={`${styles.statusIndicator} ${styles.statusIndicator_syncing}`}
                        >
                          <span
                            className={`${styles.statusDot} ${styles.statusDot_syncing}`}
                          />
                          {statusLabel(doc.status)} {doc.progress ?? 0}%
                        </div>
                      )}

                      {/* Syncing mini flow progress bar */}
                      {isWorkingStatus(doc.status) &&
                        doc.progress !== undefined && (
                          <div style={{ width: "90px", marginTop: "4px" }}>
                            <div
                              className={styles.flowBarOuter}
                              style={{ height: "4px" }}
                            >
                              <div
                                className={styles.flowBarInner}
                                style={{ width: `${doc.progress}%` }}
                              />
                            </div>
                            <div
                              style={{
                                fontSize: "9px",
                                color: "rgba(0,0,0,0.45)",
                                marginTop: "2px",
                              }}
                            >
                              {doc.status === "fetching" && "拉取正文"}
                              {doc.status === "parsing" && "解析文本"}
                              {doc.status === "embedding" && "向量化"}
                              {doc.status === "indexing" && "写入索引"}
                              {doc.status === "syncing" && "同步中"}
                            </div>
                          </div>
                        )}
                    </div>

                    <Dropdown
                      menu={{ items: menuItems }}
                      trigger={["click"]}
                      placement="bottomRight"
                    >
                      <button className={styles.actionMenuBtn}>
                        <MoreVertical size={16} />
                      </button>
                    </Dropdown>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      <Modal
        title="确认上传资料"
        open={isUploadMetadataModalOpen}
        onCancel={() => {
          setIsUploadMetadataModalOpen(false);
          setPendingUploadFile(null);
          uploadForm.resetFields();
        }}
        footer={null}
        destroyOnClose
      >
        <Form
          form={uploadForm}
          layout="vertical"
          initialValues={{ category: "uncategorized", tags: [] }}
          onFinish={handleUploadSubmit}
        >
          <Form.Item label="文件">
            <Input value={pendingUploadFile?.name || ""} disabled />
          </Form.Item>
          <Form.Item name="category" label="业务分类">
            <Select options={[...KNOWLEDGE_CATEGORIES]} />
          </Form.Item>
          <Form.Item
            name="tags"
            label="标签"
            extra="最多保留 10 个标签；标签更新不会触发重新向量化。"
          >
            <Select
              mode="tags"
              tokenSeparators={[",", "，"]}
              placeholder="输入标签后回车，例如：报销、2026"
              options={availableTags.map((tag) => ({ value: tag, label: tag }))}
            />
          </Form.Item>
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => {
                setIsUploadMetadataModalOpen(false);
                setPendingUploadFile(null);
                uploadForm.resetFields();
              }}
              style={{ marginRight: 8 }}
            >
              取消
            </Button>
            <Button type="primary" htmlType="submit">
              上传并后台索引
            </Button>
          </div>
        </Form>
      </Modal>

      {/* Link Document Modal */}
      <Modal
        title="关联云端知识资料"
        open={isLinkModalOpen}
        onCancel={() => setIsLinkModalOpen(false)}
        footer={null}
        width={500}
        destroyOnClose
      >
        <div
          style={{
            background: "rgba(16, 185, 129, 0.04)",
            border: "1px dashed rgba(16, 185, 129, 0.15)",
            borderRadius: "8px",
            padding: "12px",
            marginBottom: "16px",
            fontSize: "12px",
            color: "rgba(0, 0, 0, 0.65)",
          }}
        >
          <div
            style={{
              fontWeight: 600,
              color: "#059669",
              display: "flex",
              alignItems: "center",
              gap: "6px",
              marginBottom: "4px",
            }}
          >
            <CheckCircle2 size={14} /> 使用当前用户授权账号拉取真实正文
          </div>
          飞书：应用
          {larkProvider?.configured || larkConnector?.configured
            ? "已配置"
            : "未配置"}
          ，已授权 {larkAccounts.length} 个账号；腾讯：应用
          {tencentProvider?.configured || tencentConnector?.configured
            ? "已配置"
            : "未配置"}
          ，已授权 {tencentAccounts.length} 个账号。飞书默认使用内置官方导出；
          腾讯需配置官方
          OpenAPI/MCP/Connector。未授权或正文导出失败时会保留失败原因，不会生成模拟内容。
        </div>

        <Form
          form={form}
          layout="vertical"
          onFinish={handleLinkSubmit}
          onValuesChange={handleFormValuesChange}
          initialValues={{
            docType: "lark",
            title: "核心开发任务排期",
            url: "https://feishu.cn/docx/doxcnABC123XYZ",
            category: "uncategorized",
            tags: [],
          }}
        >
          <Form.Item
            name="docType"
            label="文档类型"
            rules={[{ required: true, message: "请选择文档类型" }]}
          >
            <Select
              options={[
                { value: "lark", label: "飞书文档" },
                { value: "tencent", label: "腾讯文档" },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="title"
            label="文档标题"
            rules={[{ required: true, message: "请输入云文档标题" }]}
          >
            <Input placeholder="例如：团队敏捷开发总排期" />
          </Form.Item>

          <Form.Item
            name="url"
            label="共享文档 URL"
            rules={[
              { required: true, message: "请输入云文档共享链接" },
              { type: "url", message: "请输入合法的 URL 链接" },
            ]}
          >
            <Input placeholder="飞书 feishu.cn/... 或 腾讯 docs.qq.com/... 链接（输入时自动智能识别类型）" />
          </Form.Item>

          <Form.Item
            name="cloudAccountId"
            label="当前用户授权账号"
            rules={[{ required: true, message: "请先授权并选择账号" }]}
          >
            <Select
              disabled={
                !selectedProviderConfigured ||
                selectedProviderAccounts.length === 0
              }
              placeholder={
                selectedProviderConfigured
                  ? `选择用于拉取正文的${selectedProviderName}账号`
                  : "管理员尚未配置该平台应用"
              }
              options={selectedProviderAccounts.map((account) => ({
                value: account.id,
                label:
                  account.display_name ||
                  account.provider_user_id ||
                  account.id,
              }))}
            />
          </Form.Item>

          <Form.Item name="category" label="业务分类">
            <Select options={[...KNOWLEDGE_CATEGORIES]} />
          </Form.Item>

          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              tokenSeparators={[",", "，"]}
              placeholder="输入标签后回车"
              options={availableTags.map((tag) => ({ value: tag, label: tag }))}
            />
          </Form.Item>

          <div
            style={{
              marginTop: -8,
              marginBottom: 18,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 10,
              fontSize: 12,
              color: "rgba(0,0,0,0.55)",
            }}
          >
            <span>
              {selectedProviderConfigured
                ? selectedConnectorStatus === "external"
                  ? "应用已配置，使用外部正文 Connector"
                  : "应用已配置，使用 QwenPaw 内置 Connector"
                : "该平台应用未在后台启用"}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <Button size="small" onClick={() => fetchDocuments(false)}>
                刷新授权
              </Button>
              <Button
                size="small"
                type="primary"
                ghost
                disabled={!selectedDocType || !selectedProviderConfigured}
                onClick={() =>
                  selectedDocType && handleAuthorizeProvider(selectedDocType)
                }
              >
                授权我的账号
              </Button>
            </div>
          </div>

          <div
            style={{
              display: "flex",
              gap: "10px",
              justifyContent: "flex-end",
              marginTop: "24px",
            }}
          >
            <Button onClick={() => setIsLinkModalOpen(false)}>取消</Button>
            <Button
              type="primary"
              htmlType="submit"
              style={{ background: "#10b981", borderColor: "#10b981" }}
            >
              开始同步
            </Button>
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
        <Form
          form={metadataForm}
          layout="vertical"
          onFinish={handleMetadataSubmit}
        >
          <Form.Item name="category" label="业务分类">
            <Select options={[...KNOWLEDGE_CATEGORIES]} />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              tokenSeparators={[",", "，"]}
              placeholder="输入标签后回车"
              options={availableTags.map((tag) => ({ value: tag, label: tag }))}
            />
          </Form.Item>
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => {
                setEditingDoc(null);
                metadataForm.resetFields();
              }}
              style={{ marginRight: 8 }}
            >
              取消
            </Button>
            <Button type="primary" htmlType="submit">
              保存
            </Button>
          </div>
        </Form>
      </Modal>

      {/* View Wiki Modal */}
      <Modal
        title={`词条：${currentWikiTitle}`}
        open={isWikiModalOpen}
        onCancel={() => setIsWikiModalOpen(false)}
        footer={null}
        width={800}
        destroyOnClose
        styles={{
          body: { padding: "24px 0 0 0", height: "60vh", overflowY: "auto" },
        }}
      >
        <div
          style={{
            padding: "0 24px 24px",
            fontFamily: "system-ui, -apple-system, sans-serif",
            lineHeight: "1.6",
            color: "rgba(0, 0, 0, 0.85)",
          }}
        >
          <pre
            style={{
              whiteSpace: "pre-wrap",
              background: "#f8fafc",
              padding: "16px",
              borderRadius: "6px",
              border: "1px solid #e2e8f0",
              fontFamily: "inherit",
            }}
          >
            {currentWikiContent}
          </pre>
        </div>
      </Modal>
    </div>
  );
}
