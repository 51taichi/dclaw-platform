import { describe, expect, it } from "vitest";
import { filterUserTaskFiles, isInternalTaskFile } from "./artifactFilters";

describe("artifactFilters", () => {
  it("hides tool result caches from user-facing artifacts", () => {
    expect(isInternalTaskFile("tool_results/result.txt")).toBe(true);
    expect(
      filterUserTaskFiles([
        "儿童节短剧_最好的礼物.md",
        "tool_results/result.txt",
      ]),
    ).toEqual(["儿童节短剧_最好的礼物.md"]);
  });

  it("hides uploaded source material directories from artifact cards", () => {
    expect(isInternalTaskFile("命理学习/补充资料/用户上传.pdf")).toBe(true);
    expect(
      filterUserTaskFiles(["命理学习/补充资料/用户上传.pdf", "考勤统计.xlsx"]),
    ).toEqual(["考勤统计.xlsx"]);
  });

  it("hides presentation compose manifests but keeps normal json outputs", () => {
    expect(isInternalTaskFile("deck.presentation.compose.json")).toBe(true);
    expect(
      filterUserTaskFiles([
        "deck.pptx",
        "deck.presentation.compose.json",
        "客户可读配置.json",
      ]),
    ).toEqual(["deck.pptx", "客户可读配置.json"]);
  });

  it("hides internal presentation draft directories", () => {
    expect(
      isInternalTaskFile("draft/深兆左智企业AI落地共建服务手册_草稿.pptx"),
    ).toBe(true);
    expect(
      filterUserTaskFiles([
        "draft/深兆左智企业AI落地共建服务手册_草稿.pptx",
        "深兆左智企业AI落地共建服务手册.pdf",
        "深兆左智企业AI落地共建服务手册.pptx",
      ]),
    ).toEqual([
      "深兆左智企业AI落地共建服务手册.pdf",
      "深兆左智企业AI落地共建服务手册.pptx",
    ]);
  });
});
