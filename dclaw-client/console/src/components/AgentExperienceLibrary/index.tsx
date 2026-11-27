import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { Database, RefreshCw, Trash2, UploadCloud } from "lucide-react";

import {
  agentExperienceLibraryApi,
  type AgentExperienceDocument,
  type AgentExperiencePublication,
} from "@/api/modules/agentExperienceLibrary";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "./index.module.less";

function publicationLabel(publication: AgentExperiencePublication) {
  return `${publication.target_name} · ${publication.name} · ${publication.public_id}`;
}

function errorStatus(error: unknown) {
  return typeof error === "object" && error !== null && "status" in error
    ? Number((error as { status: unknown }).status)
    : undefined;
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function AgentExperienceLibrary() {
  const { message } = useAppMessage();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [publications, setPublications] = useState<
    AgentExperiencePublication[]
  >([]);
  const [selectedPublicationId, setSelectedPublicationId] = useState<string>();
  const [documents, setDocuments] = useState<AgentExperienceDocument[]>([]);
  const [loadingPublications, setLoadingPublications] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [busyDocumentIds, setBusyDocumentIds] = useState<Set<string>>(
    new Set(),
  );

  const selectedPublication = useMemo(
    () =>
      publications.find(
        (publication) => publication.id === selectedPublicationId,
      ),
    [publications, selectedPublicationId],
  );

  const loadPublications = useCallback(async () => {
    setLoadingPublications(true);
    try {
      const rows = await agentExperienceLibraryApi.listPublications();
      const enabledRows = rows.filter(
        (publication) => publication.status === "enabled",
      );
      setPublications(enabledRows);
      setSelectedPublicationId((current) =>
        current && enabledRows.some((row) => row.id === current)
          ? current
          : enabledRows[0]?.id,
      );
      if (enabledRows.length === 0) setDocuments([]);
    } catch (error) {
      message.error(errorMessage(error, "加载 Agent 经验库失败"));
    } finally {
      setLoadingPublications(false);
    }
  }, [message]);

  const loadDocuments = useCallback(
    async (publicationId: string) => {
      setLoadingDocuments(true);
      try {
        setDocuments(
          await agentExperienceLibraryApi.listDocuments(publicationId),
        );
      } catch (error) {
        if (errorStatus(error) === 404) {
          await loadPublications();
        } else {
          message.error(errorMessage(error, "加载经验文档失败"));
        }
      } finally {
        setLoadingDocuments(false);
      }
    },
    [loadPublications, message],
  );

  useEffect(() => void loadPublications(), [loadPublications]);

  useEffect(() => {
    if (selectedPublicationId) {
      void loadDocuments(selectedPublicationId);
    } else {
      setDocuments([]);
    }
  }, [loadDocuments, selectedPublicationId]);

  const recoverAfterError = useCallback(
    async (error: unknown, fallback: string) => {
      if (errorStatus(error) === 404) {
        await loadPublications();
      } else {
        message.error(errorMessage(error, fallback));
      }
    },
    [loadPublications, message],
  );

  const setDocumentBusy = (docId: string, busy: boolean) => {
    setBusyDocumentIds((current) => {
      const next = new Set(current);
      if (busy) next.add(docId);
      else next.delete(docId);
      return next;
    });
  };

  const handleUpload = async (file?: File) => {
    if (!file || !selectedPublicationId || uploading) return;
    setUploading(true);
    try {
      await agentExperienceLibraryApi.uploadDocument(
        selectedPublicationId,
        file,
      );
      message.success(`「${file.name}」已加入经验库`);
      await loadDocuments(selectedPublicationId);
    } catch (error) {
      await recoverAfterError(error, "上传经验文档失败");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleSync = async (document: AgentExperienceDocument) => {
    if (!selectedPublicationId) return;
    setDocumentBusy(document.id, true);
    try {
      await agentExperienceLibraryApi.syncDocument(
        selectedPublicationId,
        document.id,
      );
      message.success("知识索引已重建");
      await loadDocuments(selectedPublicationId);
    } catch (error) {
      await recoverAfterError(error, "重建知识索引失败");
    } finally {
      setDocumentBusy(document.id, false);
    }
  };

  const handleDelete = async (document: AgentExperienceDocument) => {
    if (!selectedPublicationId) return;
    setDocumentBusy(document.id, true);
    try {
      await agentExperienceLibraryApi.deleteDocument(
        selectedPublicationId,
        document.id,
      );
      setDocuments((current) =>
        current.filter((item) => item.id !== document.id),
      );
      message.success("经验文档已删除");
    } catch (error) {
      await recoverAfterError(error, "删除经验文档失败");
    } finally {
      setDocumentBusy(document.id, false);
    }
  };

  const columns: ColumnsType<AgentExperienceDocument> = [
    {
      title: "文档",
      dataIndex: "name",
      render: (name: string, document) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{name}</Typography.Text>
          <Typography.Text type="secondary">
            {document.source_type || document.type || "文件"} ·{" "}
            {document.size || "-"}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "切片",
      width: 90,
      render: (_, document) => document.chunk_count ?? document.slices ?? 0,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (status: string) => (
        <Tag
          color={status === "ready" || status === "indexed" ? "green" : "blue"}
        >
          {status}
        </Tag>
      ),
    },
    {
      title: "操作",
      width: 190,
      render: (_, document) => (
        <Space>
          <Button
            icon={<RefreshCw size={14} />}
            loading={busyDocumentIds.has(document.id)}
            onClick={() => void handleSync(document)}
            size="small"
          >
            重建索引
          </Button>
          <Popconfirm
            title="删除经验文档"
            description="文档、切片和索引都会一并清理。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => void handleDelete(document)}
          >
            <Button
              aria-label={`删除 ${document.name}`}
              danger
              disabled={busyDocumentIds.has(document.id)}
              icon={<Trash2 size={14} />}
              size="small"
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (!loadingPublications && publications.length === 0) {
    return (
      <div className={styles.emptyState}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Space direction="vertical" size={4}>
              <Typography.Text strong>
                暂无可维护的 Agent 经验库
              </Typography.Text>
              <Typography.Text type="secondary">
                请联系管理员先发布 OpenAPI，并将归属用户设置为当前账号。
              </Typography.Text>
            </Space>
          }
        />
      </div>
    );
  }

  return (
    <div className={styles.library}>
      <div className={styles.toolbar}>
        <div>
          <Typography.Title level={5}>选择 Agent 经验库</Typography.Title>
          <Typography.Text type="secondary">
            名称优先展示，Public ID 用于辅助核对。
          </Typography.Text>
        </div>
        <Space wrap>
          <Select
            className={styles.publicationSelect}
            loading={loadingPublications}
            value={selectedPublicationId}
            showSearch
            optionFilterProp="label"
            options={publications.map((publication) => ({
              value: publication.id,
              label: publicationLabel(publication),
            }))}
            onChange={setSelectedPublicationId}
          />
          <input
            ref={fileInputRef}
            aria-label="上传经验文档"
            hidden
            type="file"
            onChange={(event) => void handleUpload(event.target.files?.[0])}
          />
          <Button
            icon={<UploadCloud size={15} />}
            loading={uploading}
            type="primary"
            onClick={() => fileInputRef.current?.click()}
          >
            上传文档
          </Button>
        </Space>
      </div>

      {selectedPublication ? (
        <div className={styles.selectionBanner}>
          <Database size={18} />
          <div>
            <Typography.Text strong>
              {publicationLabel(selectedPublication)}
            </Typography.Text>
            <Typography.Text type="secondary" className={styles.blockText}>
              专属经验库：{selectedPublication.knowledge_base_id}
            </Typography.Text>
          </div>
          <Tag
            color={
              selectedPublication.status === "enabled" ? "green" : "default"
            }
          >
            {selectedPublication.status === "enabled"
              ? "接口已启用"
              : "接口已禁用"}
          </Tag>
        </div>
      ) : null}

      <Alert
        type="info"
        showIcon
        message="一对一绑定"
        description="这里的文档只服务当前 OpenAPI 发布对象，不会混入个人知识库或企业共享知识库。"
      />

      <Table
        columns={columns}
        dataSource={documents}
        loading={loadingDocuments}
        rowKey="id"
        locale={{ emptyText: "当前 Agent 经验库暂无文档" }}
        pagination={{ pageSize: 8, showSizeChanger: false }}
        scroll={{ x: 720 }}
      />
    </div>
  );
}

export default AgentExperienceLibrary;
