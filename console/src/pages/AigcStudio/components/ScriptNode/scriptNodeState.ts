import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { parseStoryboardScriptOutput } from "./storyboardParser";

export type ScriptGeneratorMode =
  | "idle"
  | "generating_script"
  | "script_ready"
  | "storyboard_select"
  | "storyboard_image_generating"
  | "storyboard_grid";

export type StoryboardImageMode = "select" | "generating" | "grid";
export type ScriptViewMode = "script" | "creative";
export type ScriptWorkflowStep = "shots" | "assets" | "prompts";
export type ScriptTryAction = "script" | "video" | "character" | "write";

export type ScriptShot = {
  id: string;
  no: number;
  duration: number;
  imageDescription: string;
  character: string;
  characterDescription: string;
  character2?: string;
  characterDescription2?: string;
  scene: string;
  shotType: string;
  camera?: string;
  action: string;
  emotion: string;
  sceneMood?: string;
  lightingMood?: string;
  soundEffect?: string;
  dialogue: string;
  prompt: string;
  videoPrompt: string;
};

export const SCRIPT_STORY_TITLE = "我在盛唐写天下";
export const SCRIPT_STORY_SOURCE_TEXT =
  "《我在盛唐写天下》\n类型：古风 / 穿越 / 英文混剧\n时长建议：60-90秒\n基调：热血 x 盛唐史诗感 x 爽点节奏";
export const SCRIPT_STORYBOARD_INPUT_PROMPT =
  "描述剧情或添加角色参考、视频参考等，为你生成分镜脚本";

export const SCRIPT_SHOTS: ScriptShot[] = [
  {
    id: "shot-1",
    no: 1,
    duration: 4,
    imageDescription: "沈昭昭在深夜办公室疯狂加班，屏幕蓝光照在疲惫的脸上。",
    character: "沈昭昭现代",
    characterDescription:
      "28岁女性，面色极度苍白，身穿宽松起皱的现代职场白衬衫，头发凌乱披散。",
    scene: "现代办公室，凌乱桌面，电脑屏幕发光",
    shotType: "特写 (Close-Up)",
    action: "机械地敲击键盘，随后动作停顿，头部垂落。",
    emotion: "极度疲惫，濒临崩溃",
    dialogue: "无",
    prompt:
      "特写，正面微仰机位，深夜办公室蓝色屏幕光，疲惫女性加班，电影感低饱和。",
    videoPrompt: "镜头缓慢向前推进，屏幕蓝光闪烁，女性手指停下，头部沉重垂落。",
  },
  {
    id: "shot-2",
    no: 2,
    duration: 3,
    imageDescription: "沈昭昭的主观视角，视线模糊，世界陷入黑暗。",
    character: "-",
    characterDescription: "-",
    scene: "黑屏过渡，意识坠落",
    shotType: "主观视角 (POV)",
    action: "视线模糊和闭眼。",
    emotion: "眩晕，无意识",
    dialogue: "无",
    prompt: "主观视角，画面逐渐失焦，办公室灯光拖影，最终坠入黑暗。",
    videoPrompt: "画面快速失焦并暗下，伴随心跳声逐渐降低。",
  },
  {
    id: "shot-3",
    no: 3,
    duration: 4,
    imageDescription: "沈昭昭在盛唐金銮殿惊醒，发现自己穿着男装官服跪在地上。",
    character: "沈昭昭唐代",
    characterDescription:
      "28岁女性，身着盛唐深色织金男装官服，头戴乌纱折上巾但发丝略显凌乱。",
    scene: "盛唐金銮殿，雕梁画栋，百官列队",
    shotType: "全景 (Wide Shot)",
    action: "猛然睁开眼，身体剧烈挣扎一下，四处环顾。",
    emotion: "极度震惊，惶恐迷惑",
    dialogue: "这是……唐朝？",
    prompt: "全景，盛唐金銮殿，女主穿男装官服跪地惊醒，百官与金甲侍卫压迫感。",
    videoPrompt: "镜头从高处俯视下降，女主猛然抬头，金殿烛火晃动。",
  },
  {
    id: "shot-4",
    no: 4,
    duration: 3,
    imageDescription: "厉声大臣指着沈昭昭怒斥她欺君罔上。",
    character: "厉声大臣",
    characterDescription:
      "50岁左右男性，身着唐代紫色高官朝服，头戴进贤冠，面容削瘦严厉。",
    scene: "朝堂之上，紫袍官员逼近",
    shotType: "近景 (Close-Up)",
    action: "怒目圆睁，抬起手指骂向沈昭昭方向。",
    emotion: "愤怒，杀气腾腾",
    dialogue: "大胆不道！假称诗才惊世，欺君罔上，当斩！",
    prompt: "近景，紫袍唐代大臣怒斥，朝堂冷光，权力压迫感。",
    videoPrompt: "镜头快速切向大臣面部，手指前伸，朝臣惊惧低语。",
  },
  {
    id: "shot-5",
    no: 5,
    duration: 3,
    imageDescription: "沈昭昭瞳孔地震，不可置信地看着眼前的一切，喃喃自语。",
    character: "沈昭昭唐代",
    characterDescription:
      "28岁女性，身着盛唐深色织金男装官服，表情惊惧但强撑冷静。",
    scene: "大殿金砖地面反光，百官注视",
    shotType: "特写 (Close-Up)",
    action: "瞳孔震颤，嘴唇微微颤抖。",
    emotion: "极度震惊，慌乱",
    dialogue: "这是一座庙？",
    prompt: "特写，女主瞳孔震颤，唐代朝堂压迫感，冷金色光影。",
    videoPrompt: "镜头缓慢推进，女主呼吸急促，背景声音压低。",
  },
  {
    id: "shot-6",
    no: 6,
    duration: 4,
    imageDescription: "大唐皇帝端坐龙椅，居高临下，目光深沉，下达生死指令。",
    character: "大唐皇帝",
    characterDescription:
      "40岁左右男性，身着极致华丽的明黄常服龙袍，不戴冕旒但长发束冠。",
    scene: "龙椅与丹陛，万盏灯火",
    shotType: "中景 (Medium Shot)",
    action: "身体微微前倾，眼神如同看死物般俯视。",
    emotion: "冷酷，帝王威严",
    dialogue: "朕给你一炷香，作诗自证。",
    prompt: "中景，大唐皇帝端坐龙椅，金色烛光，压迫构图。",
    videoPrompt: "镜头缓慢推近皇帝，龙袍暗纹浮现，群臣屏息。",
  },
  {
    id: "shot-7",
    no: 7,
    duration: 3,
    imageDescription: "侍卫拔刀，冰冷的刀光映在沈昭昭的眼眸中，大殿死寂。",
    character: "沈昭昭唐代",
    characterDescription: "28岁女性，身着唐代男装官服，眼神从惊惧转向绝望。",
    scene: "锋利横刀，金殿阴影",
    shotType: "极特写 (Extreme Close-Up)",
    action: "面对刀光不眨眼，眼神发生质变。",
    emotion: "生死边缘的觉醒",
    dialogue: "无",
    prompt: "极特写，横刀反光映入女主眼眸，金殿阴影压迫。",
    videoPrompt: "刀锋从画面划过，反光扫过女主瞳孔。",
  },
  {
    id: "shot-8",
    no: 8,
    duration: 4,
    imageDescription: "沈昭昭深吸一口气，展开侍卫的手，缓缓从地上站起。",
    character: "沈昭昭唐代",
    characterDescription:
      "28岁女性，身着盛唐深色织金男装官服，眼神从慌乱转为坚定。",
    scene: "大殿中央，退后的侍卫，沈昭昭背影转侧面",
    shotType: "中景 (Medium Shot)",
    action: "挥开束缚，缓慢但极其稳定地直身。",
    emotion: "沉着冷静，气场全开",
    dialogue: "无",
    prompt: "中景，女主从地上站起，朝堂百官震惊，逆光轮廓。",
    videoPrompt: "镜头低角度跟随起身动作，衣摆轻动。",
  },
  {
    id: "shot-9",
    no: 9,
    duration: 4,
    imageDescription:
      "沈昭昭望向敞开的大殿门外，万里无云，阳光普照的辉煌长安城尽收眼底。",
    character: "沈昭昭唐代",
    characterDescription:
      "28岁女性，唐代官服，站立于大殿门前，背后是金殿与群臣。",
    scene: "敞开的大殿朱红大门，远处长安城",
    shotType: "过肩镜头 (Over-the-Shoulder Shot)",
    action: "背对镜头，面向殿外，静静驻足。",
    emotion: "震撼，豪情万丈",
    dialogue: "既来盛唐……便与盛唐争。",
    prompt: "过肩镜头，女主看向盛唐长安城，万里晴空，史诗感。",
    videoPrompt: "镜头从女主肩后推进，长安城阳光铺开。",
  },
  {
    id: "shot-10",
    no: 10,
    duration: 4,
    imageDescription: "沈昭昭回头，面对满朝文武与皇帝，眼神无惧，声声开口。",
    character: "沈昭昭唐代",
    characterDescription: "28岁女性，身着盛唐深色织金男装官服，目光坚定。",
    scene: "大殿正面，百官与皇帝在后",
    shotType: "近景 (Medium Close-Up)",
    action: "转过身来，直视前方，微微一笑。",
    emotion: "极致的狂妄，才华锋芒初露",
    dialogue: "君不见……",
    prompt: "近景，女主回头直视满朝文武，强烈逆光，眼神锋利。",
    videoPrompt: "镜头环绕女主半圈，停在正面。",
  },
  {
    id: "shot-11",
    no: 11,
    duration: 5,
    imageDescription:
      "沈昭昭高举手臂，宽大的衣袖滑落，宛如诵仙降临，吟出千古名句。",
    character: "沈昭昭唐代",
    characterDescription: "28岁女性，唐代男装官服，衣袖如云，发丝飞扬。",
    scene: "大殿中央，飞舞的衣袖，震撼的百官",
    shotType: "全景 (Wide Shot)",
    action: "大步向前走了一步，单臂高举指向大殿穹顶。",
    emotion: "诗仙附体，豪情万丈，狂气四溢",
    dialogue: "黄河之水天上来！",
    prompt: "全景，女主高举手臂吟诗，朝堂风起，史诗级光束。",
    videoPrompt: "镜头抬升，衣袖扬起，群臣震动后退。",
  },
  {
    id: "shot-12",
    no: 12,
    duration: 3,
    imageDescription: "厉声大臣和其他官员被诗句震惊到无以复加，目瞪口呆。",
    character: "厉声大臣",
    characterDescription: "50岁左右男性，紫色高官朝服，神色从愤怒转为惊恐。",
    scene: "百官阵列，震惊表情连锁扩散",
    shotType: "特写 (Close-Up)",
    action: "嘴巴半张，手中的笏板掉落在地，身体僵硬。",
    emotion: "三观崩塌，极度震撼，哑口无言",
    dialogue: "这……",
    prompt: "特写，唐代大臣震惊失语，笏板坠地，背景百官哗然。",
    videoPrompt: "镜头切向大臣，笏板落地发出清脆声。",
  },
  {
    id: "shot-13",
    no: 13,
    duration: 4,
    imageDescription: "大唐皇帝被诗句深深触动，缓缓从龙椅上站了起来。",
    character: "大唐皇帝",
    characterDescription: "40岁左右男性，明黄龙袍，眼神从冷漠转为炽热。",
    scene: "龙椅，大唐皇帝，屏风",
    shotType: "中景 (Medium Shot)",
    action: "双手撑住龙椅扶手，缓慢而郑重地站直身体。",
    emotion: "极度惊喜，深沉的震撼，帝王的共鸣",
    dialogue: "此诗，当传万世。",
    prompt: "中景，皇帝从龙椅站起，金色背景，神情震动。",
    videoPrompt: "镜头缓慢推近皇帝起身，龙袍纹理清晰。",
  },
  {
    id: "shot-14",
    no: 14,
    duration: 4,
    imageDescription:
      "时空转换至黄昏夜晚，大风吹过，长安城的万家灯火瞬间连绵亮起。",
    character: "-",
    characterDescription: "-",
    scene: "长安城鸟瞰，万家灯火，黄昏至夜",
    shotType: "大远景 (Extreme Wide Shot)",
    action: "无",
    emotion: "繁华，盛世流转，史诗感",
    dialogue: "无",
    prompt: "大远景，盛唐长安城夜色灯火连绵，史诗级城市鸟瞰。",
    videoPrompt: "无人机镜头掠过长安城，灯火逐盏亮起。",
  },
  {
    id: "shot-15",
    no: 15,
    duration: 4,
    imageDescription: "皇帝站在高处眺望夜景，低声给予这首诗最高的历史评价。",
    character: "大唐皇帝",
    characterDescription: "40岁左右男性，龙袍披风，神情深远。",
    scene: "宫殿高台，长安灯火背后",
    shotType: "近景 (Medium Close-Up)",
    action: "负手而立，望着夜风，目光透远地眺望。",
    emotion: "敬畏才华，震撼万千",
    dialogue: "此诗，诗传万世。",
    prompt: "近景，皇帝夜晚眺望长安，灯火与龙袍形成庄重画面。",
    videoPrompt: "镜头从侧后方靠近，衣袍随风动。",
  },
  {
    id: "shot-16",
    no: 16,
    duration: 4,
    imageDescription:
      "沈昭昭站在夜风中，目光极其坚定，下定决心要在这个时代书写传奇。",
    character: "沈昭昭唐代",
    characterDescription: "28岁女性，唐代男装官服，眼神坚毅。",
    scene: "盛唐夜空，飞舞的发丝，沈昭昭面部",
    shotType: "特写 (Close-Up)",
    action: "迎风而立，直视镜头，嘴唇轻启自语。",
    emotion: "绝对的坚定，野心，通透",
    dialogue: "既然来了……那便写尽三万里长安。",
    prompt: "特写，盛唐夜风中女主坚定眼神，史诗感结尾前奏。",
    videoPrompt: "镜头保持静止，发丝与衣袖被夜风吹动。",
  },
  {
    id: "shot-17",
    no: 17,
    duration: 5,
    imageDescription:
      "镜头极速拉远，沈昭昭的背影融入宏大无垠的盛唐山河与璀璨长安之中。",
    character: "沈昭昭唐代",
    characterDescription: "28岁女性，唐代官服，背影渺小却坚定。",
    scene: "高处边缘，沈昭昭背影，浩荡山河与长安夜",
    shotType: "极远景 (Extreme Wide Shot)",
    action: "背对镜头，迎风张开衣袖，拥抱整个盛唐。",
    emotion: "自由，气吞山河的宏大叙事结尾",
    dialogue: "无",
    prompt: "极远景，盛唐山河与长安夜色，女主背影融入历史洪流。",
    videoPrompt: "镜头高速拉远，女主变小，盛唐山河铺满画面。",
  },
];

export function scriptMode(node: AigcCanvasNode): ScriptGeneratorMode {
  const mode = node.data.scriptMode;
  if (
    mode === "generating_script" ||
    mode === "script_ready" ||
    mode === "storyboard_select" ||
    mode === "storyboard_image_generating" ||
    mode === "storyboard_grid"
  ) {
    return mode;
  }
  return "idle";
}

export function scriptViewMode(node: AigcCanvasNode): ScriptViewMode {
  return node.data.scriptView === "creative" ? "creative" : "script";
}

export function scriptWorkflowStep(node: AigcCanvasNode): ScriptWorkflowStep {
  const step = node.data.scriptWorkflowStep;
  if (step === "assets" || step === "prompts") return step;
  return "shots";
}

export function scriptShotsFromNode(node: AigcCanvasNode): ScriptShot[] {
  const shots = Array.isArray(node.data.scriptShots)
    ? (node.data.scriptShots as ScriptShot[])
    : null;
  if (shots?.length) return shots;

  const rawOutput =
    typeof node.data.scriptRawOutput === "string"
      ? node.data.scriptRawOutput
      : "";
  if (node.data.scriptParseStatus === "failed" && rawOutput) {
    const recovered = parseStoryboardScriptOutput(rawOutput);
    if (recovered.ok) return recovered.shots;
  }

  return shots ? [] : SCRIPT_SHOTS;
}

export function scriptSelectedShotIds(node: AigcCanvasNode): string[] {
  const shots = scriptShotsFromNode(node);
  if (Array.isArray(node.data.selectedShotIds)) {
    const selectedIds = node.data.selectedShotIds
      .map(String)
      .filter((id) => shots.some((shot) => shot.id === id));
    if (selectedIds.length || node.data.scriptParseStatus !== "failed") {
      return selectedIds;
    }
  }
  return shots.map((shot) => shot.id);
}

export function scriptReferenceCount(node: AigcCanvasNode) {
  if (node.data.scriptInputKind === "character") return 2;
  return 1;
}

export function scriptStoryboardImageShotIds(node: AigcCanvasNode): string[] {
  const shots = scriptShotsFromNode(node);
  const fallback = scriptSelectedShotIds(node);
  if (Array.isArray(node.data.storyboardImageShotIds)) {
    const ids = node.data.storyboardImageShotIds
      .map(String)
      .filter((id) => shots.some((shot) => shot.id === id));
    return ids.length ? ids : fallback;
  }
  return fallback;
}

export function scriptSelectedStoryboardVideoShotIds(
  node: AigcCanvasNode,
): string[] {
  const imageIds = scriptStoryboardImageShotIds(node);
  if (Array.isArray(node.data.selectedStoryboardVideoShotIds)) {
    const ids = node.data.selectedStoryboardVideoShotIds
      .map(String)
      .filter((id) => imageIds.includes(id));
    return ids.length ? ids : imageIds;
  }
  return imageIds;
}

export function storyboardImageMode(node: AigcCanvasNode): StoryboardImageMode {
  const mode = node.data.storyboardImageMode;
  if (mode === "generating" || mode === "grid") return mode;
  return "select";
}

export function isStoryboardImageNode(node: AigcCanvasNode) {
  return (
    node.type === "image_generate" &&
    node.data.imageMode === "storyboard_from_script"
  );
}

export function storyboardProgressForIndex(index: number) {
  return Math.max(46, 60 - index);
}

export function storyboardVideoProgressForIndex(index: number) {
  return Math.max(1, 3 - Math.floor(index / 4));
}
