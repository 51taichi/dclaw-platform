import { describe, expect, it } from "vitest";

import { parseStoryboardScriptOutput } from "./storyboardParser";

describe("parseStoryboardScriptOutput", () => {
  it("parses and normalizes storyboard shot JSON", () => {
    const result = parseStoryboardScriptOutput(
      JSON.stringify({
        title: "夜班穿越",
        shots: [
          {
            id: "model-shot-1",
            no: "1",
            duration: "4",
            imageDescription: "深夜办公室里，女主伏在电脑前。",
            character: "沈昭昭现代",
            characterDescription: "白衬衫，疲惫，头发凌乱。",
            scene: "现代办公室",
            shotType: "特写",
            camera: "缓慢推进",
            action: "手指停下，头部垂落。",
            emotion: "极度疲惫",
            dialogue: "无",
            soundEffect: "键盘声停止",
            prompt: "电影感特写，深夜办公室蓝色屏幕光。",
            videoPrompt: "镜头缓慢推进，屏幕蓝光闪烁。",
          },
          {
            imageDescription: "女主在金銮殿惊醒。",
            scene: "盛唐金銮殿",
            shotType: "全景",
            action: "猛然抬头。",
            emotion: "震惊",
          },
        ],
      }),
    );

    expect(result).toMatchObject({
      ok: true,
      title: "夜班穿越",
      shots: [
        expect.objectContaining({
          id: "model-shot-1",
          no: 1,
          duration: 4,
          prompt: "电影感特写，深夜办公室蓝色屏幕光。",
          videoPrompt: "镜头缓慢推进，屏幕蓝光闪烁。",
        }),
        expect.objectContaining({
          id: "shot-2",
          no: 2,
          duration: 5,
          prompt: "女主在金銮殿惊醒。，盛唐金銮殿，全景，震惊",
          videoPrompt: "女主在金銮殿惊醒。，盛唐金銮殿，全景，震惊。猛然抬头。",
        }),
      ],
    });
  });

  it("parses fenced JSON output", () => {
    const result = parseStoryboardScriptOutput(`\n\`\`\`json\n{
      "title": "代码块故事",
      "shots": [
        {
          "no": 1,
          "duration": 3,
          "imageDescription": "雨夜街道",
          "scene": "街口",
          "shotType": "远景",
          "action": "角色跑入画面",
          "emotion": "紧张"
        }
      ]
    }\n\`\`\`\n`);

    expect(result).toMatchObject({
      ok: true,
      title: "代码块故事",
      shots: [
        expect.objectContaining({
          id: "shot-1",
          prompt: "雨夜街道，街口，远景，紧张",
        }),
      ],
    });
  });

  it("accepts finalPrompt aliases for the final image prompt", () => {
    const result = parseStoryboardScriptOutput(
      JSON.stringify({
        title: "别名字段故事",
        shots: [
          {
            no: 1,
            imageDescription: "瓦房大院里仰望梧桐树的孩子",
            scene: "旧式院落",
            shotType: "中景",
            action: "孩子抬头看向树梢",
            finalPrompt: "电影感中景，旧式院落，梧桐树荫。",
          },
        ],
      }),
    );

    expect(result).toMatchObject({
      ok: true,
      shots: [
        expect.objectContaining({
          prompt: "电影感中景，旧式院落，梧桐树荫。",
        }),
      ],
    });
  });

  it("builds editable fallback shots from plain natural-language output", () => {
    const result = parseStoryboardScriptOutput(
      "那时的梧桐叶又大又密，风一吹就哗啦啦地响。",
    );

    expect(result).toMatchObject({
      ok: true,
      title: "自动分镜草稿",
      shots: [
        expect.objectContaining({
          id: "shot-1",
          no: 1,
          imageDescription: "那时的梧桐叶又大又密，风一吹就哗啦啦地响。",
          scene: "待确认场景",
          shotType: "中景",
          prompt: expect.stringContaining("那时的梧桐叶又大又密"),
        }),
      ],
    });
  });

  it("returns a parse failure for malformed or non-shot output", () => {
    expect(parseStoryboardScriptOutput("不是 JSON")).toMatchObject({
      ok: false,
    });
    expect(
      parseStoryboardScriptOutput(JSON.stringify({ title: "空镜头" })),
    ).toMatchObject({
      ok: false,
      error: expect.stringContaining("shots"),
    });
  });
});
