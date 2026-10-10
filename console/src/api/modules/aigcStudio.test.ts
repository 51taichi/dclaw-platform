import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { aigcStudioApi } from "./aigcStudio";

describe("aigcStudioApi", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => ""),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ capabilities: [] }),
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.stubGlobal("fetch", originalFetch);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads capabilities from the backend registry endpoint", async () => {
    await aigcStudioApi.listCapabilities();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/capabilities",
    );
  });

  it("loads and compiles Visual DNA through dedicated endpoints", async () => {
    await aigcStudioApi.listVisualDnaDimensions();
    await aigcStudioApi.listVisualDnaElements({
      dimension: "lighting",
      q: "电影",
    });
    await aigcStudioApi.compileVisualDna({
      selections: [{ element_id: "lighting.cinematic_contrast", weight: 0.9 }],
      provider_id: "openai",
      model_id: "gpt-image-2",
    });

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/visual-dna/dimensions",
    );
    const elementsUrl = String(vi.mocked(fetch).mock.calls[1][0]);
    expect(elementsUrl).toContain("/aigc-studio/visual-dna/elements?");
    expect(elementsUrl).toContain("dimension=lighting");
    expect(elementsUrl).toContain("q=%E7%94%B5%E5%BD%B1");
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain(
      "/aigc-studio/visual-dna/compile",
    );
    expect(vi.mocked(fetch).mock.calls[2][1]).toMatchObject({ method: "POST" });
    expect(
      JSON.parse(String(vi.mocked(fetch).mock.calls[2][1]?.body)),
    ).toMatchObject({
      provider_id: "openai",
      model_id: "gpt-image-2",
      selections: [{ element_id: "lighting.cinematic_contrast", weight: 0.9 }],
    });
  });

  it("loads style templates from the AIGC template registry endpoint", async () => {
    await aigcStudioApi.listStyleTemplates({
      type: "style",
      model_family: "seedream-4.5",
      category: "推荐",
      q: "国漫",
      commercial_only: true,
    });

    const requestedUrl = String(vi.mocked(fetch).mock.calls[0][0]);
    expect(requestedUrl).toContain("/aigc-studio/style-templates?");
    expect(requestedUrl).toContain("type=style");
    expect(requestedUrl).toContain("model_family=seedream-4.5");
    expect(requestedUrl).toContain("category=%E6%8E%A8%E8%8D%90");
    expect(requestedUrl).toContain("q=%E5%9B%BD%E6%BC%AB");
    expect(requestedUrl).toContain("commercial_only=true");
  });

  it("records style template usage through the AIGC template endpoint", async () => {
    await aigcStudioApi.markStyleTemplateUsed("style-cgv2");

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/style-templates/style-cgv2/use",
    );
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({
      method: "POST",
    });
  });

  it("loads favorite and recent style templates from dedicated endpoints", async () => {
    await aigcStudioApi.listFavoriteStyleTemplates();
    await aigcStudioApi.listRecentStyleTemplates();

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/style-templates/favorites",
    );
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain(
      "/aigc-studio/style-templates/recent",
    );
  });

  it("updates style template favorite state through the favorite endpoint", async () => {
    await aigcStudioApi.updateStyleTemplateFavorite("style-cgv2", true);

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/style-templates/style-cgv2/favorite",
    );
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({
      method: "POST",
    });
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual(
      {
        favorite: true,
      },
    );
  });

  it("creates aesthetic profiles through the AIGC template endpoint", async () => {
    await aigcStudioApi.createStyleTemplate({
      title: "国漫 CG",
      description: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
      supplemental_prompt: "保持角色造型克制。",
      prompt_template: "",
      visual_dna: [{ element_id: "lighting.cinematic_contrast", weight: 0.9 }],
      reference_image_urls: ["/api/user/aigc-studio/assets/style-ref/file"],
      profile_version: "1.0",
      category: "我的风格",
      tags: ["我的风格"],
      model_family: null,
      runtime_mode: "prompt_style",
    });

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/style-templates",
    );
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({
      method: "POST",
    });
    expect(
      JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body)),
    ).toMatchObject({
      title: "国漫 CG",
      description: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
      supplemental_prompt: "保持角色造型克制。",
      prompt_template: "",
      visual_dna: [{ element_id: "lighting.cinematic_contrast", weight: 0.9 }],
      reference_image_urls: ["/api/user/aigc-studio/assets/style-ref/file"],
      profile_version: "1.0",
      category: "我的风格",
      tags: ["我的风格"],
      model_family: null,
      runtime_mode: "prompt_style",
    });
  });

  it("updates and deletes user style templates through scoped endpoints", async () => {
    await aigcStudioApi.updateStyleTemplate("style-custom", {
      title: "高端品牌海报",
      description: "只影响背景、光影、版式和氛围。",
      supplemental_prompt: "只影响背景、光影、版式和氛围。",
      category: "我的风格",
      tags: ["我的风格"],
      model_family: null,
      runtime_mode: "prompt_style",
    });
    await aigcStudioApi.deleteStyleTemplate("style-custom");

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/style-templates/style-custom",
    );
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({
      method: "PUT",
    });
    expect(
      JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body)),
    ).toMatchObject({
      title: "高端品牌海报",
      description: "只影响背景、光影、版式和氛围。",
      supplemental_prompt: "只影响背景、光影、版式和氛围。",
    });
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain(
      "/aigc-studio/style-templates/style-custom",
    );
    expect(vi.mocked(fetch).mock.calls[1][1]).toMatchObject({
      method: "DELETE",
    });
  });

  it("uses isolated AIGC job and canvas mutation endpoints", async () => {
    await aigcStudioApi.cancelJob("job-1");
    await aigcStudioApi.retryJob("job-1");
    await aigcStudioApi.deleteCanvas("canvas-1");

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/jobs/job-1/cancel",
    );
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain(
      "/aigc-studio/jobs/job-1/retry",
    );
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain(
      "/aigc-studio/canvases/canvas-1",
    );
    expect(vi.mocked(fetch).mock.calls[2][1]).toMatchObject({
      method: "DELETE",
    });
  });

  it("requests long-image export through the dedicated layout endpoint", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          full_asset: {
            id: "full-asset",
            kind: "image",
            name: "long-1-full.png",
            path: "aigc_studio/long/full.png",
            url: "/api/aigc-studio/assets/full-asset/file",
            mime_type: "image/png",
            created_at: "2026-07-02T00:00:00Z",
            meta: {},
          },
          slice_assets: [],
          width: 750,
          height: 1600,
          slice_height: 1400,
          section_count: 3,
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
    );

    const exported = await aigcStudioApi.exportLongImage({
      canvas_id: "canvas-1",
      node_id: "long-1",
      width: 750,
      slice_height: 1400,
    });

    expect(exported.full_asset.id).toBe("full-asset");
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/long-image-exports",
    );
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({
      method: "POST",
    });
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual(
      {
        canvas_id: "canvas-1",
        node_id: "long-1",
        width: 750,
        slice_height: 1400,
      },
    );
  });

  it("starts AIGC jobs in the background and polls for completion", async () => {
    const runningJob = {
      id: "job-1",
      canvas_id: "canvas-1",
      node_id: "image-1",
      capability: "text_to_image",
      provider_id: "mxapi",
      model_id: "nano-banana-2",
      inputs: {},
      parameters: {},
      status: "running",
      outputs: [],
      logs: ["Job started."],
      created_at: "2026-06-30T00:00:00Z",
      updated_at: "2026-06-30T00:00:01Z",
    };
    const succeededJob = {
      ...runningJob,
      status: "succeeded",
      outputs: [
        {
          id: "asset-1",
          kind: "image",
          name: "poster.png",
          path: "oss://bucket/aigc/generated/poster.png",
          url: "https://static.deepmega.cn/aigc/generated/poster.png",
          mime_type: "image/png",
          created_at: "2026-06-30T00:00:02Z",
          meta: {},
        },
      ],
      logs: ["Job started.", "Job succeeded."],
      updated_at: "2026-06-30T00:00:02Z",
    };

    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(runningJob), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(succeededJob), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

    const job = await aigcStudioApi.runJob("job-1");

    expect(job.status).toBe("succeeded");
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/jobs/job-1/run?background=true",
    );
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain(
      "/aigc-studio/jobs/job-1",
    );
  });

  it("keeps polling when one background status request has a write timeout", async () => {
    vi.useFakeTimers();
    const runningJob = {
      id: "job-write-timeout",
      canvas_id: "canvas-1",
      node_id: "image-1",
      capability: "text_to_image",
      provider_id: "mxapi",
      model_id: "gpt-image-2",
      inputs: {},
      parameters: {},
      status: "running",
      outputs: [],
      logs: ["Job started."],
      created_at: "2026-07-21T00:00:00Z",
      updated_at: "2026-07-21T00:00:01Z",
    };
    const succeededJob = {
      ...runningJob,
      status: "succeeded",
      outputs: [
        {
          id: "asset-1",
          kind: "image",
          name: "poster.png",
          path: "aigc/poster.png",
          created_at: "2026-07-21T00:00:03Z",
        },
      ],
    };

    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(runningJob), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockRejectedValueOnce(new Error("WriteTimeout"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(succeededJob), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

    const resultPromise = aigcStudioApi.runJob("job-write-timeout");
    await vi.advanceTimersByTimeAsync(1500);
    const result = await resultPromise;

    expect(result.status).toBe("succeeded");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain(
      "/aigc-studio/jobs/job-write-timeout",
    );
  });

  it("resumes an accepted provider task in query-only mode while it is still running", async () => {
    vi.useFakeTimers();
    const runningJob = {
      id: "job-provider-pending",
      canvas_id: "canvas-1",
      node_id: "image-1",
      capability: "text_to_image",
      provider_id: "mxapi",
      model_id: "gpt-image-2",
      inputs: {},
      parameters: {},
      status: "running",
      outputs: [],
      logs: ["Job started."],
      created_at: "2026-10-10T08:19:02Z",
      updated_at: "2026-10-10T08:19:02Z",
    };
    const succeededJob = {
      ...runningJob,
      status: "succeeded",
      outputs: [
        {
          id: "asset-recovered",
          kind: "image",
          name: "recovered.png",
          path: "aigc/recovered.png",
          created_at: "2026-10-10T08:24:00Z",
        },
      ],
    };
    let runRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/jobs/job-provider-pending/run?background=true")) {
        runRequests += 1;
        return new Response(
          JSON.stringify(runRequests === 1 ? runningJob : succeededJob),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(JSON.stringify(runningJob), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });

    const resultPromise = aigcStudioApi.runJob("job-provider-pending");
    await vi.advanceTimersByTimeAsync(30_000);
    const result = await resultPromise;

    expect(result.status).toBe("succeeded");
    expect(runRequests).toBe(2);
    expect(
      vi.mocked(fetch).mock.calls.filter(([input]) =>
        String(input).endsWith("/aigc-studio/jobs"),
      ),
    ).toHaveLength(0);
    expect(
      vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(2);
  });

  it("uploads assets directly to signed OSS URLs before completing metadata", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            asset_id: "asset-1",
            upload_url:
              "https://static.example.test/uploads/asset-1.png?signature=1",
            method: "PUT",
            headers: { "Content-Type": "image/png" },
            token: "complete-token",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "asset-1",
            kind: "image",
            name: "reference.png",
            path: "oss://qwenpaw-aigc/aigc/generated/aigc_studio/uploads/asset-1.png",
            url: "/api/user/aigc-studio/assets/asset-1/file",
            mime_type: "image/png",
            created_at: "2026-06-27T00:00:00Z",
            meta: {},
          }),
          { status: 201, headers: { "content-type": "application/json" } },
        ),
      );

    const file = new File(["image"], "reference.png", { type: "image/png" });
    const asset = await aigcStudioApi.uploadAsset(file);

    expect(asset.id).toBe("asset-1");
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/aigc-studio/assets/direct-upload",
    );
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual(
      {
        filename: "reference.png",
        mime_type: "image/png",
        size: 5,
      },
    );
    expect(vi.mocked(fetch).mock.calls[1]).toEqual([
      "https://static.example.test/uploads/asset-1.png?signature=1",
      {
        method: "PUT",
        headers: { "Content-Type": "image/png" },
        body: file,
      },
    ]);
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain(
      "/aigc-studio/assets/direct-upload/complete",
    );
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[2][1]?.body))).toEqual(
      {
        asset_id: "asset-1",
        token: "complete-token",
      },
    );
  });
});
