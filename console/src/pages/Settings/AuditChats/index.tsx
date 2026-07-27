import { useCallback, useEffect, useState } from "react";
import { Table, Button, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { api } from "../../../api";
import type { AuditChat } from "../../../api/modules/audit";

export default function AuditChatsPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [chats, setChats] = useState<AuditChat[]>([]);
  const [messages, setMessages] = useState<any[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [selectedChat, setSelectedChat] = useState<AuditChat | null>(null);
  const [isModalVisible, setIsModalVisible] = useState(false);

  const fetchChats = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAuditChats({ limit: 100 });
      setChats(data);
    } catch (err) {
      console.error("Failed to load audit chats:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchChats();
  }, [fetchChats]);

  const viewMessages = async (chat: AuditChat) => {
    setSelectedChat(chat);
    setIsModalVisible(true);
    setLoadingMessages(true);
    try {
      const data = await api.getAuditChatMessages(chat.id);
      setMessages(data);
    } catch (err) {
      console.error("Failed to load messages:", err);
      setMessages([]);
    } finally {
      setLoadingMessages(false);
    }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", ellipsis: true },
    { title: "User ID", dataIndex: "user_id", key: "user_id" },
    { title: "Agent ID", dataIndex: "agent_id", key: "agent_id" },
    { title: "Session ID", dataIndex: "session_id", key: "session_id" },
    { title: "Channel", dataIndex: "channel", key: "channel" },
    { title: "Status", dataIndex: "status", key: "status" },
    { title: "Created", dataIndex: "created_at", key: "created_at" },
    {
      title: "Action",
      key: "action",
      render: (_: any, record: AuditChat) => (
        <Button size="small" onClick={() => viewMessages(record)}>
          View Messages
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: "0 24px" }}>
      <PageHeader parent={t("nav.settings")} current="Audit Chats" />
      <Table
        rowKey="id"
        dataSource={chats}
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
      <Modal
        title={`Messages for ${selectedChat?.id}`}
        open={isModalVisible}
        onCancel={() => setIsModalVisible(false)}
        footer={null}
        width={800}
      >
        {loadingMessages ? (
          <Spin style={{ display: "block", margin: "40px auto" }} />
        ) : (
          <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
            {messages.length === 0 ? (
              <p>No messages found or failed to load.</p>
            ) : (
              messages.map((msg, i) => (
                <div key={i} style={{ marginBottom: 12, padding: 8, background: msg.role === "user" ? "#f0f2f5" : "#fff", border: "1px solid #d9d9d9", borderRadius: 4 }}>
                  <strong>{msg.role}: </strong>
                  <span>{msg.content}</span>
                </div>
              ))
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
