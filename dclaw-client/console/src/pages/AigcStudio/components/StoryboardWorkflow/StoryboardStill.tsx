import styles from "../../index.module.less";
import type { ScriptShot } from "../ScriptNode/scriptNodeState";

export function StoryboardStill({ shot }: { shot: ScriptShot }) {
  return (
    <div
      className={`${styles.storyboardStill} ${
        styles[`storyboardStill${((shot.no - 1) % 8) + 1}`] ?? ""
      }`}
    >
      <span>{shot.character === "-" ? shot.scene : shot.character}</span>
    </div>
  );
}
