import { describe, expect, it } from "vitest";
import { buildChatToolbarModelOptions } from "./chatToolbarModelOptions";

const volcengineProvider = {
  id: "volcengine-cn",
  name: "Volcano Engine",
  api_key: "sk-xxx",
  api_key_prefix: "",
  chat_model: "OpenAIChatModel",
  require_api_key: true,
  base_url: "https://ark.cn-beijing.volces.com/api/v3",
  is_custom: false,
  is_local: false,
  support_model_discovery: true,
  support_connection_check: true,
  freeze_url: false,
  generate_kwargs: {},
  models: [
    {
      id: "glm-4-7",
      name: "GLM-4.7",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
      aigc_capabilities: [],
    },
  ],
  extra_models: [
    {
      id: "doubao-seedream-4-5-251128",
      name: "doubao-seedream-4-5",
      supports_multimodal: true,
      supports_image: true,
      supports_video: false,
      generate_kwargs: {},
      aigc_capabilities: ["text_to_image", "image_to_image", "image_edit"],
    },
  ],
};

describe("buildChatToolbarModelOptions", () => {
  it("hides generation-only AIGC models from the Workbench toolbar menu", () => {
    const options = buildChatToolbarModelOptions([volcengineProvider]);

    expect(options.map((model) => model.name)).toEqual(["GLM-4.7"]);
  });

  it("hides models from disabled providers", () => {
    const options = buildChatToolbarModelOptions([
      { ...volcengineProvider, disabled: true },
    ]);

    expect(options).toEqual([]);
  });
});
