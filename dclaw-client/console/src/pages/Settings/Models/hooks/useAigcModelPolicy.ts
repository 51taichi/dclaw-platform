import { useCallback, useEffect, useMemo, useState } from "react";
import {
  aigcModelPolicyApi,
  type AigcCategoryPolicy,
  type AigcModelCategory,
  type AigcModelRef,
  type AigcPoliciesResponse,
  type AigcPolicyInventory,
} from "@/api/modules/aigcModelPolicy";

export const AIGC_MODEL_CATEGORIES: AigcModelCategory[] = [
  "text",
  "image",
  "video",
  "audio",
];

export interface AigcCategoryDraft {
  version: number | null;
  models: AigcModelRef[];
  defaultModel: AigcModelRef | null;
}

const emptyDrafts = (): Record<AigcModelCategory, AigcCategoryDraft> => ({
  text: { version: null, models: [], defaultModel: null },
  image: { version: null, models: [], defaultModel: null },
  video: { version: null, models: [], defaultModel: null },
  audio: { version: null, models: [], defaultModel: null },
});

const refKey = (model: AigcModelRef) =>
  `${model.provider_id}\u0000${model.model_id}`;

function policyDraft(policy: AigcCategoryPolicy | null): AigcCategoryDraft {
  if (!policy) return { version: null, models: [], defaultModel: null };
  const ordered = [...policy.models].sort((a, b) => a.sort_order - b.sort_order);
  return {
    version: policy.version,
    models: ordered.map(({ provider_id, model_id }) => ({
      provider_id,
      model_id,
    })),
    defaultModel: ordered.find((model) => model.is_default) ?? null,
  };
}

function draftsFromPolicies(
  policies: AigcPoliciesResponse,
): Record<AigcModelCategory, AigcCategoryDraft> {
  return Object.fromEntries(
    AIGC_MODEL_CATEGORIES.map((category) => [
      category,
      policyDraft(policies.categories[category]),
    ]),
  ) as Record<AigcModelCategory, AigcCategoryDraft>;
}

export function useAigcModelPolicy() {
  const [inventory, setInventory] = useState<AigcPolicyInventory | null>(null);
  const [policies, setPolicies] = useState<AigcPoliciesResponse | null>(null);
  const [drafts, setDrafts] = useState(emptyDrafts);
  const [dirtyCategories, setDirtyCategories] = useState<
    Set<AigcModelCategory>
  >(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextInventory, nextPolicies] = await Promise.all([
        aigcModelPolicyApi.getInventory(),
        aigcModelPolicyApi.getPolicies(),
      ]);
      setInventory(nextInventory);
      setPolicies(nextPolicies);
      setDrafts(draftsFromPolicies(nextPolicies));
      setDirtyCategories(new Set());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const updateDraft = useCallback(
    (
      category: AigcModelCategory,
      updater: (draft: AigcCategoryDraft) => AigcCategoryDraft,
    ) => {
      setDrafts((current) => ({
        ...current,
        [category]: updater(current[category]),
      }));
      setDirtyCategories((current) => new Set(current).add(category));
    },
    [],
  );

  const addModel = useCallback(
    (category: AigcModelCategory, model: AigcModelRef) => {
      updateDraft(category, (draft) => {
        if (draft.models.some((item) => refKey(item) === refKey(model))) {
          return draft;
        }
        return {
          ...draft,
          models: [...draft.models, model],
          defaultModel: draft.defaultModel ?? model,
        };
      });
    },
    [updateDraft],
  );

  const removeModel = useCallback(
    (category: AigcModelCategory, model: AigcModelRef) => {
      updateDraft(category, (draft) => {
        const models = draft.models.filter(
          (item) => refKey(item) !== refKey(model),
        );
        return {
          ...draft,
          models,
          defaultModel:
            draft.defaultModel && refKey(draft.defaultModel) !== refKey(model)
              ? draft.defaultModel
              : (models[0] ?? null),
        };
      });
    },
    [updateDraft],
  );

  const setDefault = useCallback(
    (category: AigcModelCategory, model: AigcModelRef) => {
      updateDraft(category, (draft) => ({ ...draft, defaultModel: model }));
    },
    [updateDraft],
  );

  const reorderModels = useCallback(
    (category: AigcModelCategory, models: AigcModelRef[]) => {
      updateDraft(category, (draft) => ({ ...draft, models }));
    },
    [updateDraft],
  );

  const saveCategory = useCallback(
    async (category: AigcModelCategory) => {
      const draft = drafts[category];
      if (!draft.defaultModel) throw new Error("A default model is required");
      try {
        const saved = await aigcModelPolicyApi.saveCategory(category, {
          version: draft.version,
          models: draft.models,
          default_model: draft.defaultModel,
        });
        setPolicies((current) =>
          current
            ? {
                categories: { ...current.categories, [category]: saved },
              }
            : current,
        );
        setDrafts((current) => ({
          ...current,
          [category]: policyDraft(saved),
        }));
        setDirtyCategories((current) => {
          const next = new Set(current);
          next.delete(category);
          return next;
        });
        setInventory(await aigcModelPolicyApi.getInventory());
        return saved;
      } catch (cause) {
        if (
          cause instanceof Error &&
          "status" in cause &&
          (cause as Error & { status?: number }).status === 409
        ) {
          setPolicies(await aigcModelPolicyApi.getPolicies());
        }
        throw cause;
      }
    },
    [drafts],
  );

  return useMemo(
    () => ({
      inventory,
      policies,
      drafts,
      dirtyCategories,
      loading,
      error,
      refresh,
      addModel,
      removeModel,
      setDefault,
      reorderModels,
      saveCategory,
    }),
    [
      inventory,
      policies,
      drafts,
      dirtyCategories,
      loading,
      error,
      refresh,
      addModel,
      removeModel,
      setDefault,
      reorderModels,
      saveCategory,
    ],
  );
}
