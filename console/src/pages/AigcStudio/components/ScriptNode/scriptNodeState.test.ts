import { describe, expect, it } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import {
  SCRIPT_SHOTS,
  scriptMode,
  scriptSelectedShotIds,
  scriptSelectedStoryboardVideoShotIds,
  scriptShotsFromNode,
  scriptStoryboardImageShotIds,
  scriptViewMode,
  scriptWorkflowStep,
} from "./scriptNodeState";

const scriptNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "script-1",
  type: "script_generate",
  position: { x: 100, y: 120 },
  data,
});

describe("scriptNodeState", () => {
  it("falls back to idle script mode, script view, and the default shot set", () => {
    const node = scriptNode();

    expect(scriptMode(node)).toBe("idle");
    expect(scriptViewMode(node)).toBe("script");
    expect(scriptShotsFromNode(node)).toBe(SCRIPT_SHOTS);
    expect(scriptSelectedShotIds(node)).toEqual(
      SCRIPT_SHOTS.map((shot) => shot.id),
    );
    expect(scriptWorkflowStep(node)).toBe("shots");
  });

  it("filters stale selected shot ids for storyboard image and video flows", () => {
    const node = scriptNode({
      scriptMode: "storyboard_grid",
      scriptView: "creative",
      scriptShots: SCRIPT_SHOTS.slice(0, 3),
      selectedShotIds: ["shot-1", "missing-shot", "shot-3"],
      storyboardImageShotIds: ["shot-3", "ghost-shot"],
      selectedStoryboardVideoShotIds: ["ghost-shot"],
    });

    expect(scriptMode(node)).toBe("storyboard_grid");
    expect(scriptViewMode(node)).toBe("creative");
    expect(scriptSelectedShotIds(node)).toEqual(["shot-1", "shot-3"]);
    expect(scriptStoryboardImageShotIds(node)).toEqual(["shot-3"]);
    expect(scriptSelectedStoryboardVideoShotIds(node)).toEqual(["shot-3"]);
  });

  it("recovers failed plain-text storyboard output as selectable fallback shots", () => {
    const node = scriptNode({
      scriptParseStatus: "failed",
      scriptRawOutput: "那时的梧桐叶又大又密，风一吹就哗啦啦地响。",
      scriptShots: [],
      selectedShotIds: [],
    });

    const shots = scriptShotsFromNode(node);
    expect(shots).toHaveLength(1);
    expect(shots[0]).toMatchObject({
      id: "shot-1",
      imageDescription: "那时的梧桐叶又大又密，风一吹就哗啦啦地响。",
    });
    expect(scriptSelectedShotIds(node)).toEqual(["shot-1"]);
  });

  it("keeps the script workflow step constrained to known workbench steps", () => {
    expect(
      scriptWorkflowStep(scriptNode({ scriptWorkflowStep: "assets" })),
    ).toBe("assets");
    expect(
      scriptWorkflowStep(scriptNode({ scriptWorkflowStep: "unknown-step" })),
    ).toBe("shots");
  });
});
