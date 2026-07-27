import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Loader2,
  Users,
} from "lucide-react";
import { expertTeamsApi } from "../../../api/modules/expertTeams";
import type { ExpertTeamRun } from "../../../api/types/expertTeams";
import { useAgentStore } from "../../../stores/agentStore";
import styles from "../index.module.less";

interface ExpertTeamStatusStripProps {
  chatId?: string;
  visible?: boolean;
  variant?: "floating" | "composer";
}

export default function ExpertTeamStatusStrip({
  chatId,
  visible = true,
  variant = "floating",
}: ExpertTeamStatusStripProps) {
  const selectedExpertTeam = useAgentStore((state) => state.selectedExpertTeam);
  const currentExpertTeamRun = useAgentStore(
    (state) => state.currentExpertTeamRun,
  );
  const setCurrentExpertTeamRun = useAgentStore(
    (state) => state.setCurrentExpertTeamRun,
  );
  const [run, setRun] = useState<ExpertTeamRun | null>(currentExpertTeamRun);

  useEffect(() => {
    setRun(currentExpertTeamRun);
  }, [currentExpertTeamRun]);

  useEffect(() => {
    if (!visible || !chatId) return;
    let cancelled = false;

    const refresh = async () => {
      try {
        const next = await expertTeamsApi.getRunByChat(chatId);
        if (!cancelled) {
          setRun(next);
          setCurrentExpertTeamRun(next);
        }
      } catch {
        if (!cancelled) setRun(null);
      }
    };

    refresh();
    const timer = window.setInterval(() => {
      const state = run?.state;
      if (!state || state === "pending" || state === "running") {
        refresh();
      }
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [chatId, run?.state, setCurrentExpertTeamRun, visible]);

  const members = useMemo(() => {
    if (run?.members?.length) return run.members;
    if (selectedExpertTeam?.members?.length) {
      return selectedExpertTeam.members.map((member) => ({
        id: member.key,
        run_id: "",
        member_key: member.key,
        agent_id: member.agent_id,
        display_name: member.display_name,
        role: member.role,
        avatar: member.avatar,
        state: "pending" as const,
      }));
    }
    return [];
  }, [run?.members, selectedExpertTeam]);

  if (!visible || members.length === 0) return null;

  const teamName = run?.team?.name || selectedExpertTeam?.name || "专家团";
  const isRunning = run?.state === "running" || run?.state === "pending";
  const hasRunState = Boolean(run?.id && run.members?.length);
  const stateLabels: Record<string, string> = {
    pending: "待命",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };

  return (
    <div
      className={`${styles.expertTeamStrip} ${
        variant === "composer" ? styles.expertTeamStripComposer : ""
      }`}
    >
      <div className={styles.expertTeamStripTitle}>
        <Users size={14} />
        <span>{teamName}</span>
        {isRunning && <span className={styles.expertTeamRunning}>协作中</span>}
      </div>
      <div className={styles.expertTeamMembers}>
        {members.map((member) => {
          const state = member.state;
          const icon =
            state === "completed" ? (
              <CheckCircle2 size={13} />
            ) : state === "running" ? (
              <Loader2 size={13} className={styles.expertTeamSpin} />
            ) : state === "failed" ? (
              <AlertCircle size={13} />
            ) : (
              <Circle size={13} />
            );
          const stateLabel = stateLabels[state] || "待命";
          return (
            <div
              key={member.member_key}
              className={`${styles.expertTeamMember} ${
                hasRunState ? styles[`expertTeamMember_${state}`] || "" : ""
              }`}
            >
              {hasRunState && (
                <span className={styles.expertTeamMemberAvatar}>
                  {member.avatar || "•"}
                </span>
              )}
              <span className={styles.expertTeamMemberName}>
                {member.display_name}
              </span>
              {hasRunState && (
                <span
                  className={styles.expertTeamMemberStatus}
                  title={stateLabel}
                  aria-label={stateLabel}
                >
                  {icon}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
