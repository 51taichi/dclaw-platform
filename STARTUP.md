# QwenPaw 项目启动指南

本文档记录了 QwenPaw 项目前端与后端服务的常规本地启动命令，方便开发与调试。

## 1. 启动后端服务

后端服务基于 Python 环境运行。在启动前，请确保已经激活了项目自带的虚拟环境。

打开终端，在项目根目录 `/Users/zu/Documents/workes/qwenpaw` 下执行：

```bash
# 激活 Python 虚拟环境
source venv/bin/activate

# 启动后端应用
qwenpaw app
```

> **注意：** 
> 后端服务启动后，默认会加载本地的工作空间与历史聊天记录。请确保虚拟环境（`venv`）正常配置并且安装了所有必要的依赖。如果需要重新安装依赖，可以执行 `pip install -e .`。

---

## 2. 启动前端控制台

前端服务（Console）基于 Vite + React 构建。

打开一个**新的终端窗口**，进入 `console` 目录并启动开发服务器：

```bash
# 进入前端目录
cd console

# 启动前端开发服务器
npm run dev
```

启动成功后，终端会提示本地的访问地址（通常为 `http://localhost:5173/`）。
直接在浏览器中打开该地址即可使用控制台。
