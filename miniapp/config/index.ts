import { defineConfig, type UserConfigExport } from "@tarojs/cli";
import { resolveMiniappApiBase } from "./apiBase";
import devConfig from "./dev";
import prodConfig from "./prod";

export default defineConfig<"webpack5">(async (merge, { command }) => {
  const baseConfig: UserConfigExport<"webpack5"> = {
    projectName: "dclaw-miniapp",
    date: "2026-06-17",
    designWidth: 375,
    deviceRatio: {
      375: 2,
      640: 2.34 / 2,
      750: 1,
      828: 1.81 / 2,
    },
    sourceRoot: "src",
    outputRoot: "dist",
    plugins: [],
    defineConstants: {
      __DCLAW_API_BASE__: JSON.stringify(resolveMiniappApiBase(process.env)),
    },
    copy: {
      patterns: [
        {
          from: "src/assets",
          to: "dist/assets",
          ignore: [
            "**/README.md",
            "**/*.test.*",
            "**/mascot-confirm.png",
            "**/mascot-empty.png",
            "**/mascot-error.png",
            "**/mascot-hero.png",
            "**/mascot-knowledge.png",
            "**/mascot-login.png",
            "**/mascot-result.png",
            "**/mascot-tab.png",
            "**/mascot-task.png",
          ],
        },
      ],
      options: {},
    },
    framework: "react",
    compiler: "webpack5",
    mini: {
      postcss: {
        pxtransform: {
          enable: true,
          config: {},
        },
      },
    },
    h5: {},
  };

  if (command === "build") {
    return merge({}, baseConfig, prodConfig);
  }
  return merge({}, baseConfig, devConfig);
});
