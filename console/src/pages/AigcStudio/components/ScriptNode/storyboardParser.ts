import type { ScriptShot } from "./scriptNodeState";

export type StoryboardParseResult =
  | {
      ok: true;
      title: string;
      shots: ScriptShot[];
      rawText: string;
    }
  | {
      ok: false;
      error: string;
      rawText: string;
    };

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const numberValue = (value: unknown) => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.trim());
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
};

function extractJsonText(rawText: string) {
  const trimmed = rawText.trim();
  const fencedMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fencedMatch?.[1]) return fencedMatch[1].trim();
  return trimmed;
}

function joinPromptParts(parts: string[]) {
  return parts.map((part) => part.trim()).filter(Boolean).join("，");
}

function plainTextSegments(rawText: string) {
  const cleaned = rawText
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\r/g, "\n")
    .trim();
  if (cleaned.length < 12) return [];

  return (
    cleaned
      .split(/\n+/)
      .flatMap((line) => line.match(/[^。！？!?；;]+[。！？!?；;]?/g) ?? [line])
      .map((segment) => segment.trim())
      .filter((segment) => segment.length >= 12)
      .slice(0, 12)
  );
}

function fallbackShotsFromPlainText(rawText: string): ScriptShot[] {
  return plainTextSegments(rawText).map((segment, index) => {
    const prompt = joinPromptParts([
      segment,
      "电影感画面",
      "中景",
      "自然光",
      "叙事感",
    ]);
    return {
      id: `shot-${index + 1}`,
      no: index + 1,
      duration: 5,
      imageDescription: segment,
      character: "待确认角色",
      characterDescription: "根据原文补充角色形象",
      scene: "待确认场景",
      shotType: "中景",
      camera: "缓慢推进",
      action: segment,
      emotion: "怀旧",
      lightingMood: "自然光",
      soundEffect: "环境声",
      dialogue: "",
      prompt,
      videoPrompt: `${prompt}，镜头缓慢推进，保持叙事氛围。`,
    };
  });
}

function normalizeShot(rawShot: unknown, index: number): ScriptShot {
  const shot =
    rawShot && typeof rawShot === "object"
      ? (rawShot as Record<string, unknown>)
      : {};
  const no = numberValue(shot.no) ?? index + 1;
  const duration = numberValue(shot.duration);
  const imageDescription = textValue(shot.imageDescription);
  const scene = textValue(shot.scene);
  const shotType = textValue(shot.shotType);
  const camera = textValue(shot.camera);
  const emotion = textValue(shot.emotion);
  const action = textValue(shot.action);
  const prompt =
    textValue(shot.prompt) ||
    textValue(shot.finalPrompt) ||
    textValue(shot.final_prompt) ||
    joinPromptParts([imageDescription, scene, shotType, camera, emotion]);
  const videoPrompt =
    textValue(shot.videoPrompt) ||
    textValue(shot.video_prompt) ||
    joinPromptParts([prompt, action]).replace(/，([^，]*)$/, "。$1");

  return {
    id: textValue(shot.id) || `shot-${index + 1}`,
    no,
    duration: duration && duration > 0 ? duration : 5,
    imageDescription,
    character: textValue(shot.character),
    characterDescription: textValue(shot.characterDescription),
    character2: textValue(shot.character2) || undefined,
    characterDescription2: textValue(shot.characterDescription2) || undefined,
    scene,
    shotType,
    camera: camera || undefined,
    action,
    emotion,
    sceneMood: textValue(shot.sceneMood) || undefined,
    lightingMood: textValue(shot.lightingMood) || undefined,
    soundEffect: textValue(shot.soundEffect) || undefined,
    dialogue: textValue(shot.dialogue),
    prompt,
    videoPrompt,
  };
}

export function parseStoryboardScriptOutput(
  raw: unknown,
): StoryboardParseResult {
  const rawText = textValue(raw);
  if (!rawText) {
    return {
      ok: false,
      error: "Storyboard output is empty.",
      rawText,
    };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(extractJsonText(rawText));
  } catch {
    const fallbackShots = fallbackShotsFromPlainText(rawText);
    if (fallbackShots.length) {
      return {
        ok: true,
        title: "自动分镜草稿",
        shots: fallbackShots,
        rawText,
      };
    }
    return {
      ok: false,
      error: "Storyboard output is not valid JSON.",
      rawText,
    };
  }

  if (!parsed || typeof parsed !== "object") {
    return {
      ok: false,
      error: "Storyboard output must be a JSON object with shots.",
      rawText,
    };
  }

  const data = parsed as Record<string, unknown>;
  if (!Array.isArray(data.shots) || data.shots.length === 0) {
    return {
      ok: false,
      error: "Storyboard output must include a non-empty shots array.",
      rawText,
    };
  }

  const shots = data.shots.map(normalizeShot).filter((shot) => shot.prompt);
  if (!shots.length) {
    return {
      ok: false,
      error: "Storyboard output shots must include promptable content.",
      rawText,
    };
  }

  return {
    ok: true,
    title: textValue(data.title),
    shots,
    rawText,
  };
}
