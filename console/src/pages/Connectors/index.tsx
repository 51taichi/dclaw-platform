import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Link2, Github, FileText, Database, Mail, MessageSquare, Cloud, Globe, Settings, CheckCircle, Box } from "lucide-react";
import { message } from "antd";
import { mcpApi } from "../../api/modules/mcp";
import type { MCPClientInfo } from "../../api/types";
import styles from "../shared/ecoPage.module.less";

const CATEGORIES = [
  { key: "all", label: "全部" }, { key: "office", label: "办公工具" },
  { key: "im", label: "即时通讯" }, { key: "dev", label: "开发工具" },
  { key: "data", label: "数据存储" },
];

// Helper to guess icon and color based on client key or name
const getIconForClient = (key: string, name: string) => {
  const lowerKey = (key + name).toLowerCase();
  if (lowerKey.includes("github")) return { icon: <Github size={22} />, color: "#24292e" };
  if (lowerKey.includes("notion")) return { icon: <FileText size={22} />, color: "#000000" };
  if (lowerKey.includes("mysql") || lowerKey.includes("db") || lowerKey.includes("database") || lowerKey.includes("sql")) return { icon: <Database size={22} />, color: "#00758f" };
  if (lowerKey.includes("mail") || lowerKey.includes("smtp")) return { icon: <Mail size={22} />, color: "#ea4335" };
  if (lowerKey.includes("wechat") || lowerKey.includes("feishu") || lowerKey.includes("dingtalk")) return { icon: <MessageSquare size={22} />, color: "#3370ff" };
  if (lowerKey.includes("drive") || lowerKey.includes("cloud")) return { icon: <Cloud size={22} />, color: "#4285f4" };
  // Default fallback
  return { icon: <Box size={22} />, color: "#6366f1" };
};

export default function ConnectorsPage() {
  const navigate = useNavigate();
  const [activeCategory, setActiveCategory] = useState("all");
  const [clients, setClients] = useState<MCPClientInfo[]>([]);

  const fetchClients = async () => {
    try {
      const data = await mcpApi.listMCPClients();
      setClients(data);
    } catch (err) {
      console.error("Failed to fetch capabilities:", err);
    }
  };

  useEffect(() => {
    fetchClients();
  }, []);

  const handleToggle = async (clientKey: string) => {
    try {
      await mcpApi.toggleMCPClient(clientKey);
      message.success("状态切换成功");
      fetchClients();
    } catch (err) {
      console.error(err);
      message.error("操作失败");
    }
  };

  return (
    <div className={styles.ecoPage}>
      <div className={styles.pageHeader}>
        <div className={styles.pageTitle}>
          <span className={styles.pageTitleIcon}><Link2 size={18} /></span>
          连接器
        </div>
        <div className={styles.pageSubtitle}>将 AI 助手与你常用的工具和服务打通。基于 MCP 协议，一键连接 GitHub、飞书、钉钉等应用。</div>
      </div>

      <div className={styles.categoryTabs}>
        {CATEGORIES.map((cat) => (
          <button key={cat.key} className={`${styles.categoryTab} ${activeCategory === cat.key ? styles.categoryTabActive : ""}`} onClick={() => setActiveCategory(cat.key)}>{cat.label}</button>
        ))}
      </div>

      <div className={styles.cardGrid}>
        {clients.map((client) => {
          const clientKey = client.key || "";
          const clientName = client.name || client.key || "";
          const { icon, color } = getIconForClient(clientKey, clientName);
          const isConnected = client.enabled;
          
          return (
            <div key={client.key} className={styles.card} style={{ border: isConnected ? "1px solid rgba(16, 185, 129, 0.5)" : undefined, backgroundColor: isConnected ? "rgba(16, 185, 129, 0.02)" : undefined }}>
              <div className={styles.cardHeader}>
                <div className={styles.cardIcon} style={{ background: `${color}15`, color: color }}>{icon}</div>
                <div className={styles.cardInfo}>
                  <div className={styles.cardName}>{clientName}</div>
                  <div className={styles.cardMeta}>
                    {isConnected ? (
                       <span style={{ color: "#10b981", display: "flex", alignItems: "center", gap: 4 }}><CheckCircle size={11} /> 已连接</span>
                    ) : (
                       <span style={{ color: "#94a3b8" }}>未连接</span>
                    )}
                  </div>
                </div>
              </div>
              <div className={styles.cardDesc}>{client.description || "该连接器未提供描述信息。"}</div>
              <div className={styles.cardTags}>
                <span className={styles.cardTag}>远程 (Market)</span>
              </div>
              <div className={styles.cardFooter}>
                <span className={styles.cardStat}><Globe size={12} />MCP 协议</span>
                {isConnected ? (
                  <button className={styles.cardAction} style={{ background: "#fee2e2", color: "#ef4444", borderColor: "#fecaca" }} onClick={() => handleToggle(client.key)}>断开</button>
                ) : (
                  <button className={styles.cardAction} onClick={() => handleToggle(client.key)}>连接</button>
                )}
              </div>
            </div>
          );
        })}
        {/* 固定显示的自定义连接器入口 */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div className={styles.cardIcon} style={{ background: "#64748b15", color: "#64748b" }}><Settings size={22} /></div>
            <div className={styles.cardInfo}>
              <div className={styles.cardName}>自定义连接器</div>
              <div className={styles.cardMeta}><span style={{ color: "#94a3b8" }}>底层入口</span></div>
            </div>
          </div>
          <div className={styles.cardDesc}>通过 MCP 协议接入任意第三方服务，支持 stdio/HTTP/SSE 高级配置。</div>
          <div className={styles.cardTags}>
            <span className={styles.cardTag}>自定义</span>
            <span className={styles.cardTag}>高级</span>
          </div>
          <div className={styles.cardFooter}>
            <span className={styles.cardStat}><Globe size={12} />MCP 协议</span>
            <button className={styles.cardAction} onClick={() => navigate("/mcp")}>去配置</button>
          </div>
        </div>
      </div>
    </div>
  );
}
