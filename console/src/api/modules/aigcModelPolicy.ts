import { request } from "../request";

export type AigcModelCategory = "text" | "image" | "video" | "audio";

export interface AigcModelRef {
  provider_id: string;
  model_id: string;
}

export interface AigcInventoryItem extends AigcModelRef {
  provider_name: string;
  model_name: string;
  category: AigcModelCategory | null;
  selectable: boolean;
  reasons: string[];
  selected: boolean;
  is_default: boolean;
}

export interface AigcPolicyModel extends AigcModelRef {
  sort_order: number;
  is_default: boolean;
}

export interface AigcCategoryPolicy {
  id: number;
  category: AigcModelCategory;
  configured: boolean;
  version: number;
  updated_by: number | null;
  updated_at: string | null;
  models: AigcPolicyModel[];
}

export interface AigcPolicyInventory {
  categories: Record<AigcModelCategory, AigcInventoryItem[]>;
  uncategorized: AigcInventoryItem[];
}

export interface AigcPoliciesResponse {
  categories: Record<AigcModelCategory, AigcCategoryPolicy | null>;
}

export interface SaveAigcCategoryRequest {
  version: number | null;
  models: AigcModelRef[];
  default_model: AigcModelRef;
}

export const aigcModelPolicyApi = {
  getInventory: () =>
    request<AigcPolicyInventory>("/admin/aigc-model-policy/inventory"),
  getPolicies: () =>
    request<AigcPoliciesResponse>("/admin/aigc-model-policy"),
  saveCategory: (
    category: AigcModelCategory,
    payload: SaveAigcCategoryRequest,
  ) =>
    request<AigcCategoryPolicy>(`/admin/aigc-model-policy/${category}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};
