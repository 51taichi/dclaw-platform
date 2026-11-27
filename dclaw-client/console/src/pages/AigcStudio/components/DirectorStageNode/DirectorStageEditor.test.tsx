import {
  Children,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DirectorStageEditor from "./DirectorStageEditor";
import {
  createDefaultDirectorStageProject,
  type DirectorStageCapture,
} from "./directorStageTypes";
import type {
  DirectorStageCapturePayload,
  DirectorStageCaptureResult,
} from "./types";

vi.mock("@react-three/fiber", () => {
  const gl = {
    render: vi.fn(),
    domElement: {
      toDataURL: () => "data:image/png;base64,aGVsbG8=",
    },
  };
  const scene = {};
  const size = { width: 1280, height: 720 };

  return {
    Canvas: ({ children }: { children: ReactNode }) => (
      <div data-testid="director-stage-canvas">
        {Children.toArray(children).filter(
          (child) =>
            isValidElement(child) &&
            typeof child.type === "function" &&
            child.type.name === "CaptureBridge",
        )}
        {Children.toArray(children)
          .filter(
            (
              child,
            ): child is ReactElement<{
              object: { id: string; name: string };
              onSelect: (objectId: string) => void;
            }> =>
              isValidElement(child) &&
              typeof child.type === "function" &&
              child.type.name === "StageObject",
          )
          .map((child) => (
            <button
              key={child.props.object.id}
              type="button"
              aria-label={`视窗对象 ${child.props.object.name}`}
              onClick={() => child.props.onSelect(child.props.object.id)}
            />
          ))}
      </div>
    ),
    useThree: () => ({
      gl,
      scene,
      size,
    }),
  };
});

vi.mock("@react-three/drei", () => ({
  Grid: () => null,
  OrbitControls: () => null,
  PerspectiveCamera: () => null,
  useGLTF: () => ({
    scene: {
      clone: () => ({}),
    },
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

const baseProps = () => ({
  captures: [] as DirectorStageCapture[],
  initialProject: createDefaultDirectorStageProject(),
  onCapture: vi.fn(
    async (): Promise<DirectorStageCaptureResult> => ({
      ok: true,
    }),
  ),
  onCaptureBatch: vi.fn(async (payloads: DirectorStageCapturePayload[]) => ({
    ok: true as const,
    captures: payloads.map((payload, index) => ({
      id: `capture-${index + 1}`,
      assetId: `asset-${index + 1}`,
      name: payload.fileName,
      previewUrl: `https://example.com/${payload.fileName}`,
      createdAt: Date.now(),
    })),
  })),
  onClose: vi.fn(),
  onSave: vi.fn(),
  onUploadModel: vi.fn(async (file: File, kind: "character" | "prop") => ({
    ok: true as const,
    model: {
      id: "uploaded-model-asset-model-1",
      assetId: "asset-model-1",
      kind,
      name: file.name.replace(/\.glb$/i, ""),
      fileName: file.name,
      url: "/api/user/aigc-studio/assets/asset-model-1/file",
      assetPath: "aigc_studio/uploads/asset-model-1.glb",
      mimeType: "model/gltf-binary",
      size: file.size,
      createdAt: 1783900800000,
    },
  })),
});

describe("DirectorStageEditor", () => {
  it("shows a saved state after saving the current scene", async () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "方箱" }));
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        objects: [
          expect.objectContaining({
            kind: "prop",
          }),
        ],
      }),
    );
    expect(await screen.findByText("已保存")).toBeInTheDocument();
  });

  it("edits the selected object transform and saves it into the project", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "方箱" }));
    fireEvent.click(screen.getByRole("button", { name: "道具01" }));
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "金色方块" },
    });
    fireEvent.change(screen.getByLabelText("位置 X"), {
      target: { value: "2.5" },
    });
    fireEvent.change(screen.getByLabelText("尺寸"), {
      target: { value: "1.4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        objects: [
          expect.objectContaining({
            kind: "prop",
            name: "金色方块",
            position: [2.5, 0.35, -1],
            scale: [1.4, 1.4, 1.4],
          }),
        ],
      }),
    );
  });

  it("adds an audited character asset, applies a pose, and exposes attribution", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "人台角色" }));
    fireEvent.click(screen.getByRole("button", { name: "挥手" }));

    expect(
      screen.getByRole("link", {
        name: "UE Mannequin (Retopology) 来源",
      }),
    ).toHaveAttribute(
      "href",
      "https://sketchfab.com/3d-models/ue-mannequin-retopology-5394d9f894374a2ab7c57a21929ce4c2",
    );
    expect(
      screen.getByRole("link", {
        name: "UE Mannequin (Retopology) 授权条款",
      }),
    ).toHaveAttribute("href", "https://sketchfab.com/licenses");

    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        objects: [
          expect.objectContaining({
            kind: "character",
            modelId: "ue-mannequin-retopology",
            poseId: "wave",
          }),
        ],
      }),
    );
  });

  it("adds programmatic prop shapes from the built-in asset catalog", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "圆柱" }));
    fireEvent.click(screen.getByRole("button", { name: "球体" }));
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        objects: [
          expect.objectContaining({ modelId: "procedural-cylinder" }),
          expect.objectContaining({ modelId: "procedural-sphere" }),
        ],
      }),
    );
    expect(screen.getByText("当前仅使用程序化资产")).toBeInTheDocument();
  });

  it("uploads a GLB character, adds it to the scene, and persists its asset reference", async () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);
    const file = new File(["glb-model"], "hero.glb", {
      type: "model/gltf-binary",
    });

    fireEvent.change(screen.getByLabelText("上传 GLB 模型"), {
      target: { files: [file] },
    });

    expect(await screen.findByText("hero 已加入场景")).toBeInTheDocument();
    expect(props.onUploadModel).toHaveBeenCalledWith(file, "character");

    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        modelAssets: [
          expect.objectContaining({
            assetId: "asset-model-1",
            kind: "character",
            name: "hero",
          }),
        ],
        objects: [
          expect.objectContaining({
            kind: "character",
            modelId: "uploaded-model-asset-model-1",
            name: "hero",
          }),
        ],
      }),
    );
    expect(screen.getByText("授权由上传者确认", { exact: false })).toBeInTheDocument();
  });

  it("persists the selected lighting preset", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "夜景" }));
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        scene: expect.objectContaining({ lightingPreset: "night" }),
      }),
    );
  });

  it("applies a complete product scene template", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "产品展示" }));
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        activeCameraId: "camera-1",
        scene: expect.objectContaining({ lightingPreset: "studio" }),
        objects: [
          expect.objectContaining({ name: "主展示体" }),
          expect.objectContaining({ name: "展示台" }),
        ],
        cameras: expect.arrayContaining([
          expect.objectContaining({ name: "主视觉" }),
          expect.objectContaining({ name: "产品近景" }),
          expect.objectContaining({ name: "俯拍" }),
        ]),
      }),
    );
  });

  it("deletes the selected object from the scene", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "人台角色" }));
    fireEvent.click(screen.getByRole("button", { name: "角色01" }));
    fireEvent.click(screen.getByRole("button", { name: "删除对象" }));
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(
      screen.queryByRole("button", { name: "角色01" }),
    ).not.toBeInTheDocument();
    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        objects: [],
      }),
    );
  });

  it("switches cameras and uses the custom capture name for uploads", async () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "添加机位" }));
    fireEvent.click(screen.getByRole("button", { name: "机位02" }));
    fireEvent.change(screen.getByLabelText("截图名称"), {
      target: { value: "俯拍试镜" },
    });
    fireEvent.click(screen.getByRole("button", { name: "机位截图" }));

    expect(props.onCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        fileName: "俯拍试镜.png",
        project: expect.objectContaining({
          activeCameraId: "camera-2",
        }),
      }),
    );
  });

  it("captures every camera with distinct names in one batch", async () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "添加机位" }));
    fireEvent.change(screen.getByLabelText("截图名称"), {
      target: { value: "开场分镜" },
    });
    fireEvent.click(screen.getByRole("button", { name: "全部机位截图" }));

    expect(props.onCaptureBatch).toHaveBeenCalledTimes(1);
    expect(props.onCaptureBatch).toHaveBeenCalledWith([
      expect.objectContaining({ fileName: "开场分镜-机位01.png" }),
      expect.objectContaining({ fileName: "开场分镜-机位02.png" }),
    ]);
    expect(await screen.findByText("已回流 2 张机位截图")).toBeInTheDocument();
  });

  it("edits the active camera and saves its framing parameters", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "添加机位" }));
    fireEvent.change(screen.getByLabelText("机位名称"), {
      target: { value: "主镜头" },
    });
    fireEvent.change(screen.getByLabelText("机位位置 X"), {
      target: { value: "7.5" },
    });
    fireEvent.change(screen.getByLabelText("目标 Y"), {
      target: { value: "1.8" },
    });
    fireEvent.change(screen.getByLabelText("视场角"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        activeCameraId: "camera-2",
        cameras: expect.arrayContaining([
          expect.objectContaining({
            id: "camera-2",
            name: "主镜头",
            position: [7.5, 2.5, 5],
            target: [0, 1.8, 0],
            fov: 60,
          }),
        ]),
      }),
    );
  });

  it("selects an object directly from the 3D viewport", () => {
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "人台角色" }));
    fireEvent.click(screen.getByRole("button", { name: "方箱" }));
    fireEvent.click(screen.getByRole("button", { name: "视窗对象 角色01" }));
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "主角" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存场景" }));

    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        objects: expect.arrayContaining([
          expect.objectContaining({ kind: "character", name: "主角" }),
          expect.objectContaining({ kind: "prop", name: "道具01" }),
        ]),
      }),
    );
  });

  it("shows uploaded captures in the capture history", () => {
    const props = baseProps();
    props.captures = [
      {
        id: "capture-1",
        assetId: "asset-1",
        name: "主镜头.png",
        previewUrl: "https://example.com/director-stage-capture.png",
        createdAt: Date.now(),
      },
    ];

    render(<DirectorStageEditor {...props} />);

    expect(screen.getByRole("img", { name: "主镜头.png" })).toHaveAttribute(
      "src",
      "https://example.com/director-stage-capture.png",
    );
    expect(screen.getByText("主镜头.png")).toBeInTheDocument();
  });

  it("prevents duplicate captures while upload is pending", async () => {
    const pending = deferred<DirectorStageCaptureResult>();
    const props = baseProps();
    props.onCapture.mockReturnValue(pending.promise);
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "机位截图" }));

    expect(screen.getByRole("button", { name: "截图上传中" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "截图上传中" }));
    expect(props.onCapture).toHaveBeenCalledTimes(1);

    await act(async () => {
      pending.resolve({ ok: true });
      await pending.promise;
    });

    expect(await screen.findByText("截图已回流")).toBeInTheDocument();
  });

  it("shows capture upload failures inside the editor", async () => {
    const props = baseProps();
    props.onCapture.mockResolvedValue({
      ok: false,
      error: "upload failed",
    });
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "机位截图" }));

    expect(await screen.findByText("upload failed")).toBeInTheDocument();
  });

  it("asks for confirmation before closing a dirty scene", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const props = baseProps();
    render(<DirectorStageEditor {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "方箱" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));

    expect(confirm).toHaveBeenCalledWith("当前场景有未保存更改，确定关闭吗？");
    expect(props.onClose).not.toHaveBeenCalled();

    confirm.mockRestore();
  });
});
