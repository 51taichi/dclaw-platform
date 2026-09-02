import { useCallback, useEffect, useMemo, useState } from "react";
import { DatePicker, Select, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import dayjs, { type Dayjs } from "dayjs";
import { useTheme } from "../../../contexts/ThemeContext";
import api from "../../../api";
import type {
  CreditConsumptionRankingResponse,
  CreditRankingPeriodType,
  TokenUsageRecord,
} from "../../../api/types/tokenUsage";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PageHeader } from "@/components/PageHeader";
import {
  CreditRankingTable,
  DataTables,
  EmptyState,
  LoadingState,
  ModelTrendChart,
  SummaryCards,
  TokenTypeChart,
} from "./components";
import { useDataAggregation } from "./hooks/useDataAggregation";
import { useModelTrendConfig } from "./hooks/useModelTrendConfig";
import { useTokenTypeConfig } from "./hooks/useTokenTypeConfig";
import styles from "./index.module.less";

type UsageTab = "credits" | "tokens";

const EMPTY_RANKING: CreditConsumptionRankingResponse = {
  items: [],
  page: 1,
  page_size: 20,
  total: 0,
  period: {
    type: "month",
    anchor_date: "",
    started_at: "",
    ended_at: "",
    timezone: "Asia/Shanghai",
  },
};

function TokenUsagePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const [activeTab, setActiveTab] = useState<UsageTab>("credits");

  const [ranking, setRanking] =
    useState<CreditConsumptionRankingResponse>(EMPTY_RANKING);
  const [rankingLoading, setRankingLoading] = useState(true);
  const [rankingError, setRankingError] = useState(false);
  const [rankingPeriod, setRankingPeriod] =
    useState<CreditRankingPeriodType>("month");
  const [rankingAnchor, setRankingAnchor] = useState<Dayjs>(dayjs());
  const [rankingPage, setRankingPage] = useState(1);
  const [rankingPageSize, setRankingPageSize] = useState(20);

  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenError, setTokenError] = useState(false);
  const [records, setRecords] = useState<TokenUsageRecord[]>([]);
  const [startDate, setStartDate] = useState<Dayjs>(
    dayjs().subtract(30, "day"),
  );
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());

  const fetchRanking = useCallback(async () => {
    setRankingLoading(true);
    setRankingError(false);
    try {
      const result = await api.getCreditConsumptionRanking({
        period: rankingPeriod,
        anchor_date: rankingAnchor.format("YYYY-MM-DD"),
        page: rankingPage,
        page_size: rankingPageSize,
      });
      setRanking(result);
    } catch (err) {
      console.error("Failed to load credit consumption ranking:", err);
      message.error(
        t("tokenUsage.creditRankingLoadFailed", "加载积分消耗排行失败"),
      );
      setRanking(EMPTY_RANKING);
      setRankingError(true);
    } finally {
      setRankingLoading(false);
    }
  }, [message, rankingAnchor, rankingPage, rankingPageSize, rankingPeriod, t]);

  const fetchTokenData = useCallback(async () => {
    setTokenLoading(true);
    setTokenError(false);
    try {
      const result = await api.getTokenUsageDetails({
        start_date: startDate.format("YYYY-MM-DD"),
        end_date: endDate.format("YYYY-MM-DD"),
      });
      setRecords(result);
    } catch (err) {
      console.error("Failed to load token usage:", err);
      message.error(t("tokenUsage.loadFailed"));
      setRecords([]);
      setTokenError(true);
    } finally {
      setTokenLoading(false);
    }
  }, [endDate, message, startDate, t]);

  useEffect(() => {
    fetchRanking();
  }, [fetchRanking]);

  useEffect(() => {
    if (activeTab === "tokens") fetchTokenData();
  }, [activeTab, fetchTokenData]);

  const aggregatedData = useDataAggregation(records);
  const modelTrendConfig = useModelTrendConfig({
    byDateModel: aggregatedData?.by_date_model ?? null,
    startDate,
    endDate,
    isDark,
  });
  const tokenTypeConfig = useTokenTypeConfig({
    byDate: aggregatedData?.by_date ?? null,
    startDate,
    endDate,
    isDark,
  });

  const byModelData = useMemo(() => {
    if (!aggregatedData?.by_model) return [];
    return Object.entries(aggregatedData.by_model).map(([key, stats]) => ({
      key,
      model: key,
      prompt_tokens: stats.prompt_tokens,
      completion_tokens: stats.completion_tokens,
      call_count: stats.call_count,
    }));
  }, [aggregatedData?.by_model]);

  const byDateData = useMemo(() => {
    if (!aggregatedData?.by_date) return [];
    return Object.entries(aggregatedData.by_date)
      .map(([date, stats]) => ({
        key: date,
        date,
        prompt_tokens: stats.prompt_tokens,
        completion_tokens: stats.completion_tokens,
        call_count: stats.call_count,
      }))
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [aggregatedData?.by_date]);

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (!dates || !dates[0] || !dates[1]) return;
    setStartDate(dates[0]);
    setEndDate(dates[1]);
  };

  const handleRankingPeriodChange = (value: CreditRankingPeriodType) => {
    setRankingPeriod(value);
    setRankingAnchor(dayjs());
    setRankingPage(1);
  };

  const handleRankingPageChange = (page: number, pageSize: number) => {
    setRankingPage(pageSize === rankingPageSize ? page : 1);
    setRankingPageSize(pageSize);
  };

  const creditTab = (
    <div className={styles.tabContent}>
      <div className={styles.rankingToolbar}>
        <Select<CreditRankingPeriodType>
          value={rankingPeriod}
          onChange={handleRankingPeriodChange}
          options={[
            { value: "year", label: t("tokenUsage.byYear", "按年") },
            { value: "month", label: t("tokenUsage.byMonth", "按月") },
            { value: "week", label: t("tokenUsage.byWeek", "按周") },
            { value: "day", label: t("tokenUsage.byDay", "按日") },
          ]}
          className={styles.periodSelect}
        />
        <DatePicker
          value={rankingAnchor}
          picker={rankingPeriod === "day" ? "date" : rankingPeriod}
          onChange={(value) => {
            if (!value) return;
            setRankingAnchor(value);
            setRankingPage(1);
          }}
          allowClear={false}
          disabledDate={(current) => current.isAfter(dayjs(), "day")}
        />
      </div>
      {rankingError && !rankingLoading ? (
        <LoadingState
          message={t(
            "tokenUsage.creditRankingLoadFailed",
            "加载积分消耗排行失败",
          )}
          error
          onRetry={fetchRanking}
        />
      ) : (
        <CreditRankingTable
          items={ranking.items}
          loading={rankingLoading}
          page={rankingPage}
          pageSize={rankingPageSize}
          total={ranking.total}
          onPageChange={handleRankingPageChange}
        />
      )}
    </div>
  );

  const tokenTab = (
    <div className={styles.tabContent}>
      <div className={styles.toolbar}>
        <DatePicker.RangePicker
          value={[startDate, endDate]}
          onChange={handleDateChange}
          disabledDate={(current) => current && current.isAfter(dayjs(), "day")}
        />
      </div>
      {tokenLoading ? (
        <LoadingState message={t("common.loading", "Loading...")} />
      ) : tokenError && records.length === 0 ? (
        <LoadingState
          message={t("tokenUsage.loadFailed")}
          error
          onRetry={fetchTokenData}
        />
      ) : (
        <>
          {aggregatedData && (
            <SummaryCards
              totalCalls={aggregatedData.total_calls}
              totalPromptTokens={aggregatedData.total_prompt_tokens}
              totalCompletionTokens={aggregatedData.total_completion_tokens}
              totalTokens={
                aggregatedData.total_prompt_tokens +
                aggregatedData.total_completion_tokens
              }
            />
          )}
          <div className={styles.trendRow}>
            <ModelTrendChart chartConfig={modelTrendConfig} />
            <TokenTypeChart chartConfig={tokenTypeConfig} />
          </div>
          {byModelData.length === 0 && byDateData.length === 0 ? (
            <EmptyState message={t("tokenUsage.noData")} />
          ) : (
            <DataTables byModelData={byModelData} byDateData={byDateData} />
          )}
        </>
      )}
    </div>
  );

  return (
    <div className={styles.container}>
      <PageHeader parent={t("nav.settings")} current={t("tokenUsage.title")} />
      <div className={styles.content}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as UsageTab)}
          items={[
            {
              key: "credits",
              label: t("tokenUsage.creditTab", "积分消耗"),
              children: creditTab,
            },
            {
              key: "tokens",
              label: t("tokenUsage.tokenTab", "Token 消耗"),
              children: tokenTab,
            },
          ]}
        />
      </div>
    </div>
  );
}

export default TokenUsagePage;
