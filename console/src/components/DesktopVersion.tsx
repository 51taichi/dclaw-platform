import { useEffect, useState } from "react";
import { getDesktopRuntime } from "@/desktop/runtime";
import styles from "../layouts/index.module.less";

export function DesktopVersion() {
  const [version, setVersion] = useState("");
  useEffect(() => {
    void getDesktopRuntime().then((runtime) =>
      setVersion(runtime?.version ?? ""),
    );
  }, []);
  return version ? (
    <span className={styles.desktopVersion}>v{version}</span>
  ) : null;
}
