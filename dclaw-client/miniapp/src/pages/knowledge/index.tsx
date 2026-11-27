import { Button, Input, Text, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import AssetImage from "../../components/AssetImage";
import StateView from "../../components/StateView";
import usePageShare from "../../hooks/usePageShare";
import { requireAuth } from "../../services/auth";
import {
  searchKnowledge,
  type KnowledgeHit,
} from "../../services/knowledge";

import "./index.scss";

export default function KnowledgePage() {
  usePageShare({
    title: "DClaw｜企业知识搜索",
    path: "/pages/knowledge/index",
  });

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useDidShow(() => {
    requireAuth();
  });

  const submit = async () => {
    if (!requireAuth()) {
      return;
    }
    const normalized = query.trim();
    if (!normalized) {
      Taro.showToast({ title: "请输入搜索内容", icon: "none" });
      return;
    }
    setLoading(true);
    setErrorMessage("");
    try {
      const response = await searchKnowledge(normalized);
      setHits(response.hits || []);
      setSearched(true);
    } catch (error) {
      setHits([]);
      setSearched(true);
      setErrorMessage(error instanceof Error ? error.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell className="knowledge-page">
      <Text className="page-title">知识搜索</Text>
      <View className="knowledge-hero">
        <View className="knowledge-hero__copy">
          <Text className="knowledge-hero__title">查企业知识，少翻文件</Text>
          <Text className="knowledge-hero__desc">输入关键词，DClaw 会优先匹配企业知识库内容</Text>
        </View>
        <AssetImage slot="mascotKnowledge" className="knowledge-hero__mascot" />
      </View>
      <View className="card search-card">
        <Input
          className="search-input"
          value={query}
          placeholder="搜索企业知识"
          onInput={(event) => setQuery(String(event.detail.value || ""))}
        />
        <Button className="search-button" loading={loading} onClick={submit}>
          搜索
        </Button>
      </View>

      <View className="hint-row">
        <Text className="hint-chip">产品需求</Text>
        <Text className="hint-chip">项目资料</Text>
        <Text className="hint-chip">销售数据</Text>
      </View>

      <View className="hit-list">
        {loading && (
          <StateView
            type="loading"
            title="正在搜索企业知识"
            description="DClaw 正在匹配相关资料"
          />
        )}
        {!!errorMessage && !loading && (
          <StateView
            type="error"
            title="知识搜索失败"
            description={errorMessage}
            actionText="重新搜索"
            onAction={submit}
          />
        )}
        {!loading &&
          !errorMessage &&
          hits.map((hit, index) => (
            <View
              key={`${hit.id || hit.title || index}`}
              className="card hit-card"
            >
              <Text className="hit-title">{hit.title || "知识片段"}</Text>
              <Text className="hit-source">{hit.source || "企业知识库"}</Text>
              <Text className="hit-snippet">{hit.snippet || "暂无摘要"}</Text>
            </View>
          ))}
        {searched && !loading && !errorMessage && hits.length === 0 && (
          <StateView
            type="empty"
            title="没有找到相关知识"
            description="换个更具体的关键词试试"
          />
        )}
      </View>
    </AppShell>
  );
}
