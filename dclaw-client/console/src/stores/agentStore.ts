import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentSummary } from "../api/types/agents";
import type { ExpertTeamRun, ExpertTeamTemplate } from "../api/types/expertTeams";

/**
 * Storage key used by both sessionStorage (per-tab state) and localStorage
 * (cross-tab shared state).
 */
const STORAGE_KEY = "qwenpaw-agent-storage";

/**
 * localStorage key that remembers the last-used agent across browser sessions.
 * New tabs read this to set their initial selectedAgent.
 */
const LAST_USED_AGENT_KEY = "qwenpaw-last-used-agent";

/** WorkBuddy-style interaction modes: Craft (execute), Plan (plan+execute), Ask (Q&A only), or empty (specific expert) */
export type ActiveMode = "craft" | "plan" | "ask" | "";

interface AgentStore {
  selectedAgent: string;
  /** Current interaction mode — purely a frontend UI concept, does NOT change selectedAgent */
  activeMode: ActiveMode;
  selectedSkill: any | null;
  setSelectedSkill: (skill: any | null) => void;
  selectedExpertTeam: ExpertTeamTemplate | null;
  currentExpertTeamRun: ExpertTeamRun | null;
  setSelectedExpertTeam: (team: ExpertTeamTemplate | null) => void;
  setCurrentExpertTeamRun: (run: ExpertTeamRun | null) => void;

  // --- Claw Specific State ---
  clawSelectedAgent: string;
  clawActiveMode: ActiveMode;
  clawSelectedSkill: any | null;
  setClawSelectedAgent: (agentId: string) => void;
  setClawActiveMode: (mode: ActiveMode) => void;
  setClawSelectedSkill: (skill: any | null) => void;
  // ---------------------------
  recentAgents: string[];
  agents: AgentSummary[];
  /** Per-agent last active chat ID for restoring on agent switch */
  lastChatIdByAgent: Record<string, string>;
  setSelectedAgent: (agentId: string) => void;
  /** Switch interaction mode without changing the underlying agent */
  setActiveMode: (mode: ActiveMode) => void;
  setAgents: (agents: AgentSummary[]) => void;
  addAgent: (agent: AgentSummary) => void;
  removeAgent: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<AgentSummary>) => void;
  setLastChatId: (agentId: string, chatId: string) => void;
  getLastChatId: (agentId: string) => string | undefined;
}

/**
 * Determines the initial selectedAgent for this tab.
 *
 * Priority:
 *  1. sessionStorage (returning to a tab that already picked an agent)
 *  2. localStorage lastUsedAgent (new tab inherits the most recent choice)
 *  3. "default"
 */
function getInitialSelectedAgent(): string {
  // 1. sessionStorage: returning to a tab that already picked an agent
  try {
    const sessionValue = sessionStorage.getItem(STORAGE_KEY);
    if (sessionValue) {
      const parsed = JSON.parse(sessionValue);
      const agent = parsed?.state?.selectedAgent;
      if (agent) return agent;
    }
  } catch {
    /* ignore */
  }
  // 2. Dedicated localStorage key (written by setSelectedAgent)
  try {
    const lastUsed = localStorage.getItem(LAST_USED_AGENT_KEY);
    if (lastUsed) return lastUsed;
  } catch {
    /* ignore */
  }
  // 3. Shared localStorage state (written by persist middleware)
  try {
    const shared = localStorage.getItem(STORAGE_KEY);
    if (shared) {
      const parsed = JSON.parse(shared);
      const agent = parsed?.state?.selectedAgent;
      if (agent) return agent;
    }
  } catch {
    /* ignore */
  }
  return "default";
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set, get) => ({
      selectedAgent: getInitialSelectedAgent(),
      activeMode: "craft" as ActiveMode,
      selectedSkill: null,
      selectedExpertTeam: null,
      currentExpertTeamRun: null,

      clawSelectedAgent: "default",
      clawActiveMode: "craft" as ActiveMode,
      clawSelectedSkill: null,

      recentAgents: [],
      agents: [],
      lastChatIdByAgent: {},

      setSelectedAgent: (agentId) => {
        set((state) => {
          const filtered = state.recentAgents.filter((id) => id !== agentId);
          return {
            selectedAgent: agentId,
            recentAgents: [agentId, ...filtered].slice(0, 3),
            selectedExpertTeam: null,
            currentExpertTeamRun: null,
          };
        });
        // Persist to localStorage so new tabs inherit this choice
        try {
          localStorage.setItem(LAST_USED_AGENT_KEY, agentId);
        } catch {
          /* ignore */
        }
      },

      setActiveMode: (mode) =>
        set({
          activeMode: mode,
          selectedExpertTeam: mode ? null : get().selectedExpertTeam,
        }),

      setSelectedSkill: (skill) => set({ selectedSkill: skill }),
      setSelectedExpertTeam: (team) =>
        set({
          selectedExpertTeam: team,
          activeMode: team ? "" : get().activeMode,
          currentExpertTeamRun: team ? null : get().currentExpertTeamRun,
        }),
      setCurrentExpertTeamRun: (run) => set({ currentExpertTeamRun: run }),

      setClawSelectedAgent: (agentId) => set((state) => {
        const filtered = state.recentAgents.filter((id) => id !== agentId);
        return {
          clawSelectedAgent: agentId,
          recentAgents: [agentId, ...filtered].slice(0, 3),
        };
      }),
      setClawActiveMode: (mode) => set({ clawActiveMode: mode }),
      setClawSelectedSkill: (skill) => set({ clawSelectedSkill: skill }),

      setAgents: (agents) => set({ agents }),

      addAgent: (agent) =>
        set((state) => ({
          agents: [...state.agents, agent],
        })),

      removeAgent: (agentId) =>
        set((state) => {
          const { [agentId]: _, ...remainingChatIds } = state.lastChatIdByAgent;
          return {
            agents: state.agents.filter((a) => a.id !== agentId),
            lastChatIdByAgent: remainingChatIds,
            ...(state.selectedAgent === agentId
              ? { selectedAgent: "default" }
              : {}),
          };
        }),

      updateAgent: (agentId, updates) =>
        set((state) => ({
          agents: state.agents.map((a) =>
            a.id === agentId ? { ...a, ...updates } : a,
          ),
        })),

      setLastChatId: (agentId, chatId) =>
        set((state) => ({
          lastChatIdByAgent: { ...state.lastChatIdByAgent, [agentId]: chatId },
        })),

      getLastChatId: (agentId) => get().lastChatIdByAgent[agentId],
    }),
    {
      name: STORAGE_KEY,
      storage: {
        getItem: (name) => {
          try {
            // Read per-tab state from sessionStorage
            const value = sessionStorage.getItem(name);
            if (value) return JSON.parse(value);
          } catch {
            /* ignore */
          }
          // Fall back to localStorage for shared data (agents list, etc.)
          try {
            const shared = localStorage.getItem(name);
            return shared ? JSON.parse(shared) : null;
          } catch (error) {
            console.error(`Failed to parse agent storage "${name}":`, error);
            localStorage.removeItem(name);
            return null;
          }
        },
        setItem: (name, value) => {
          try {
            // Per-tab state (includes selectedAgent)
            sessionStorage.setItem(name, JSON.stringify(value));
          } catch {
            /* ignore */
          }
          try {
            // Shared state (agents list, lastChatIdByAgent)
            localStorage.setItem(name, JSON.stringify(value));
          } catch (error) {
            console.error(`Failed to save agent storage "${name}":`, error);
          }
        },
        removeItem: (name) => {
          sessionStorage.removeItem(name);
          localStorage.removeItem(name);
        },
      },
    },
  ),
);
