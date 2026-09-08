# DClaw OEM 桌面客户端与强制更新机制设计草案

> 状态：讨论稿，记录截至 2026-09-08 已确认的方案。本文用于后续继续讨论，不代表已经完成开发。

## 1. 背景与目标

DClaw 服务端继续维护一套代码，但允许为不同客户独立部署服务端，并为每个客户构建独立 OEM 桌面客户端。每个 OEM 客户端拥有自己的品牌、版本、服务端地址和更新通道。

需要达到以下目标：

1. DClaw 与 OEM 客户端可以同时安装在同一台电脑上，应用、安装目录和用户数据互不覆盖。
2. 客户端能够明确识别自身品牌、版本、系统和架构。
3. OEM 客户端只能升级到自己的 OEM 包，升级后不能变成 DClaw 或其他 OEM 品牌。
4. 每个品牌独立管理版本号和发布时间。
5. 每个品牌在构建时固化对应的 API Base URL，最终用户无感且不能修改。
6. 客户端发现新版本时必须强制升级；更新检查或安装未完成时不能进入工作台。
7. 每个 OEM 部署在自己的业务域名根路径提供 `/latest.json`，安装包位于同域名的 `/desktop/<version>/`。
8. Windows 默认发布 x64 安装包；macOS 默认发布 Universal 通用包，同时兼容 Apple Silicon 和 Intel Mac。
9. 尽量不修改前端业务页面，通过应用入口和全局网络基础设施完成版本治理。
10. 主界面左上角以 Logo 表达品牌，Logo 右侧只常驻显示安装包自身的客户端版本，例如 `v2.0.0`，不重复显示品牌文字。

## 2. 已确认的核心决策

### 2.1 品牌和版本独立

每个品牌独立维护：

- `brandId`
- 产品名称和品牌资源
- 应用标识符
- 版本号
- API Base URL
- 更新清单 URL
- 更新签名密钥
- 安装包和更新文件目录
- 发布说明和发布时间

示例：

| 品牌 | 客户端版本 | API Base URL | 更新清单 |
| --- | --- | --- | --- |
| DClaw | `2.1.0` | `https://dclaw.deepmega.cn` | `https://dclaw.deepmega.cn/latest.json` |
| OEM A | `1.3.2` | `https://api.customer-a.com` | `https://api.customer-a.com/latest.json` |

不同品牌的版本不要求同步。

第一期每个品牌只设一个正式发布通道，不提供 beta、灰度发布、测试用户分组或多通道。新安装包先在测试服务器人工验证，确认后再替换正式部署的 `/latest.json`。

### 2.2 服务端代码共用，部署配置独立

服务端仍是一套源码。DClaw 和各 OEM 可以部署到不同服务器，使用不同域名和数据环境。客户端在构建时将该品牌的 API Base URL 固化进安装包；客户端界面不展示服务器设置，也不允许用户切换。

### 2.3 严格强制更新

采用简单、严格的更新策略：

- 客户端启动时必须成功读取该品牌的更新清单。
- 当前版本为最新版本时才允许进入工作台。
- 发现新版本时自动下载、验证、安装并重启。
- 更新服务器不可访问、下载失败或签名失败时，不能进入系统，只能重试或退出。
- 不提供“稍后更新”“跳过版本”或离线使用。

### 2.4 每个部署使用自己的更新根路径

每个 DClaw/OEM 独立部署都在自己的业务域名根路径提供 `/latest.json`。客户端从构建时固化的 `apiBaseUrl` 自动推导更新地址，不需要第二个服务器配置。第一版只需由 Nginx 或现有 Web 服务提供静态文件，不开发版本管理后台。

## 3. 品牌配置驱动构建

建议在客户端源码中建立品牌目录：

```text
console/brands/
├── dclaw/
│   ├── brand.json
│   ├── VERSION
│   ├── updater.pub
│   └── icons/
└── customer-a/
    ├── brand.json
    ├── VERSION
    ├── updater.pub
    └── icons/
```

品牌配置示例：

```json
{
  "brandId": "customer-a",
  "productName": "客户品牌",
  "identifier": "com.customer-a.desktop",
  "apiBaseUrl": "https://api.customer-a.com",
  "updateEndpoint": "https://api.customer-a.com/latest.json",
  "windowTitle": "客户品牌 - AI 智能工作台",
  "artifactPrefix": "CustomerA",
  "updateChannel": "stable"
}
```

构建时选择品牌，而不是直接维护多份客户端源码：

```bash
npm run desktop:build -- --brand dclaw
npm run desktop:build -- --brand customer-a
```

构建过程根据品牌生成或覆盖临时 Tauri 配置，至少包括：

- `productName`
- `identifier`
- `version`
- 窗口标题
- 托盘名称和提示
- 图标
- 应用描述
- 安装包名称
- API Base URL
- 更新清单 URL
- 更新签名公钥
- 独立构建输出目录

品牌配置是安装包身份的唯一来源。运行期间不能从业务服务端或更新清单反向覆盖品牌名称、Logo、应用 ID 或更新地址。

### 3.1 主界面版本展示

不新增“关于”页面或设置菜单。Logo 本身代表品牌，主界面左上角 Logo 右侧只显示版本号：

```text
[品牌 Logo] v2.0.0
```

品牌仍由安装包内置身份信息识别，但不在 Logo 旁重复显示名称。版本必须读取安装包自身的桌面身份信息，不能使用服务端 `/version`，因为它代表服务端版本，不是当前安装的桌面客户端版本。API Header、更新比较和页面展示共用同一个客户端版本来源。

## 4. 同机安装隔离

DClaw 与 OEM 客户端需要使用不同的应用标识符，例如：

```text
com.dclaw.desktop
com.customer-a.desktop
```

因此它们应拥有独立的：

- Windows 安装记录和安装目录
- macOS Bundle Identifier
- 应用数据目录
- Local Storage/WebView 数据
- 缓存和日志目录
- 自启动项
- 托盘实例
- 更新清单和更新签名公钥

构建校验必须拒绝重复 `brandId` 或重复应用标识符。

## 5. 客户端启动与强制更新流程

客户端启动后先进入更新门禁，不直接加载工作台：

```text
启动客户端
  ↓
读取安装包内置品牌、版本、平台和架构
  ↓
请求该品牌固化的 latest.json
  ├─ 请求失败 → 品牌化错误页 → 只能重试或退出
  ├─ 当前版本最新 → 进入工作台
  └─ 存在新版本
       ↓
     自动下载并显示进度
       ↓
     验证更新签名
       ├─ 失败 → 禁止进入 → 重试或退出
       └─ 成功 → 安装 → 重启
```

更新页面必须使用当前安装包内置的 OEM 名称、Logo 和主题，不能使用更新服务器返回的品牌信息。

Windows 安装更新时客户端会退出；macOS 安装完成后需要重新启动应用。重启后再次通过更新门禁，确认版本最新后进入工作台。

### 5.1 最小更新页面

第一期只实现四种全屏状态：

1. 检查中：显示 OEM Logo 和“正在检查更新”。
2. 下载中：显示当前版本、目标版本和进度条，不提供取消按钮。
3. 安装中：显示“正在安装，请勿关闭应用”。
4. 失败：显示简短错误原因，以及“重试”“退出”两个按钮。

品牌名、Logo 和主题色全部来自安装包内置品牌配置。`latest.json` 只提供版本、更新说明、下载地址和签名，不能控制页面品牌。第一期不做更新公告弹窗、稍后提醒、后台下载或复杂动画。

### 5.2 超时与重试

第一期使用简单、可预测的失败处理：

- 请求 `latest.json` 的超时时间为 10 秒。
- 超时或请求失败后进入不可关闭的错误页，不在后台无限自动重试。
- 错误页只提供“重试”和“退出”。
- 用户点击重试后重新请求更新清单。
- 更新包下载失败时删除未完成文件，下次从头下载。
- 第一阶段不实现断点续传。
- 签名失败时显示“更新包验证失败”，只能重新下载或退出。
- 错误页显示可复制或截图的简洁错误原因，便于售后排查。

## 6. 已打开客户端与服务端更新竞态

仅在启动时检查更新无法覆盖“客户端一直开着、服务端已经升级”的场景。为避免用户在旧客户端操作新服务端功能时看到普通业务错误，采用以下双保险。

### 6.1 客户端启动检查

客户端只在启动门禁中主动读取一次 `latest.json`。不设置固定时间轮询，也不在窗口恢复或电脑唤醒时额外请求更新清单。

客户端保持打开期间，由每次内部 HTTP 业务请求携带的版本信息和服务端 `426` 门禁发现更新，避免重复机制和无意义请求。

### 6.2 服务端请求门禁

桌面客户端访问内部 API 时携带：

```http
X-Desktop-Brand: customer-a
X-Desktop-Version: 1.3.0
X-Desktop-Platform: windows
X-Desktop-Arch: x86_64
```

服务端以本部署的 `latest.json.version` 作为唯一版本依据，不再额外维护最低版本环境变量。服务端在执行业务逻辑前比较桌面客户端版本：

- 客户端版本低于 `latest.json.version`：返回 `426` 并强制更新。
- 客户端版本等于 `latest.json.version`：正常处理。
- 客户端版本高于 `latest.json.version`：允许使用，同时记录服务端警告日志。
- 不支持自动降级。

客户端版本低于最新版本时返回：

```http
HTTP/1.1 426 Upgrade Required
Content-Type: application/json
```

```json
{
  "code": "DESKTOP_UPDATE_REQUIRED",
  "brandId": "customer-a",
  "currentVersion": "1.3.0",
  "requiredVersion": "1.4.0",
  "message": "客户端版本过低，请升级后继续使用"
}
```

客户端捕获任意内部 API 的 `426` 后：

1. 停止后续业务请求。
2. 中止当前操作。
3. 显示不可关闭的品牌化升级页面。
4. 只从安装包内置的品牌更新地址获取更新。
5. 自动下载、验证、安装和重启。

服务端响应不能指定客户端的下载地址，避免错误或恶意配置将 OEM 引导到 DClaw 或其他 OEM 更新包。

## 7. 尽量不修改前端业务代码的网络接管方案

本章机制只适用于 Tauri 桌面客户端，不适用于 Web 版。普通浏览器不会注入桌面品牌、版本、平台和架构请求头；服务端在这些桌面请求头全部缺失时必须直接放行，不读取 `latest.json`、不返回桌面升级专用的 `426`，也不向 Web 页面展示下载、安装或重启界面。只有四个桌面请求头完整且品牌与当前部署一致时才执行版本比较。

### 7.1 当前代码现状

客户端已有公共 `request()` 封装，但并非所有请求都经过它。登录、上传、流式聊天、插件和部分工作区接口仍直接调用 `fetch()`；WebSocket 也有独立连接。因此只修改当前 `request.ts` 不能覆盖全部请求。

### 7.2 全局 HTTP 接管

为避免逐个修改业务页面，可以在应用启动入口安装一次全局 `fetch` 包装器：

```ts
const originalFetch = window.fetch;

window.fetch = async (input, init = {}) => {
  // 仅识别并处理发往当前 OEM API Base URL 的内部请求。
  // 自动添加品牌、版本、平台和架构 Header。
  // 全局捕获 426 并触发唯一一次强制更新。
  // 外部 URL 原样交给 originalFetch。
};
```

全局层负责：

- 判断请求是否属于当前品牌的内部 API
- 自动添加桌面客户端身份 Header
- 捕获所有内部 HTTP 请求的 `426`
- 防止多个并发请求重复触发升级
- 进入全局强制更新状态并阻止后续内部请求
- 保持 OSS/S3 等外部预签名上传地址不变

外部预签名 URL 不能添加 DClaw Header，否则可能破坏签名。

现有 `request()` 可以继续保留，并自然经过全局 `fetch` 包装器。第一阶段无需逐个改动业务页面。

### 7.3 WebSocket 例外

浏览器 WebSocket API 不能自由添加普通 HTTP Header。第一期已确定不对 WebSocket 增加版本门禁，依赖启动检查和普通 HTTP `426` 门禁，以减少改动。

后续如果确有需要，可以选择：

1. 在 WebSocket URL 查询参数中传递品牌和版本。
2. 使用 WebSocket 子协议传递有限身份信息。
3. 在连接建立后的第一条认证消息中携带身份。

WebSocket 版本门禁属于后续增强，不阻塞第一期。

## 8. 每个部署的更新目录

这里的“根目录”指业务域名的 URL 根路径，而不是公开 Git 源码目录。推荐把更新文件放在宿主机持久目录，并由 Nginx 映射：

```text
/opt/dclaw-updates/
├── latest.json
└── desktop/
    └── 1.3.0/
        ├── CustomerA_1.3.0_x64-setup.exe
        ├── CustomerA_1.3.0_x64-setup.exe.sig
        ├── CustomerA_1.3.0_universal.dmg
        ├── CustomerA.app.tar.gz
        ├── CustomerA.app.tar.gz.sig
        └── checksums.txt
```

映射结果：

```text
/opt/dclaw-updates/latest.json → https://api.customer-a.com/latest.json
/opt/dclaw-updates/desktop/*   → https://api.customer-a.com/desktop/*
```

更新目录不放入 Docker 镜像，避免容器替换时丢失历史版本或反复传输安装包。

普通 DMG 用于首次安装，`.app.tar.gz` 用于 macOS 在线更新。Windows 安装程序既用于首次安装，也可作为 updater 产物；最终形式以 Tauri 2 实际构建输出为准。

`latest.json` 示例：

```json
{
  "version": "1.3.0",
  "notes": "功能升级和问题修复",
  "pub_date": "2026-09-08T12:00:00+08:00",
  "platforms": {
    "windows-x86_64": {
      "url": "https://api.customer-a.com/desktop/1.3.0/CustomerA_1.3.0_x64-setup.exe",
      "signature": "签名文件的实际内容"
    },
    "darwin-universal": {
      "url": "https://api.customer-a.com/desktop/1.3.0/CustomerA.app.tar.gz",
      "signature": "签名文件的实际内容"
    }
  }
}
```

## 9. 签名和品牌安全

Tauri updater 要求更新包签名校验，不能关闭。每个品牌建议使用独立 updater 密钥：

- 公钥进入对应品牌配置并固化到客户端。
- 私钥只保存在发布机器或 CI Secret 中。
- 私钥不能提交到 Git，也不能上传到静态更新目录。
- 私钥需要可靠备份；丢失后已安装客户端将无法验证后续更新。

第一期私钥由当前专用 Mac 在 Git 仓库外保管：

```text
~/.dclaw-release/keys/
├── dclaw.key
├── customer-a.key
└── customer-b.key
```

- 每个品牌使用独立、带密码的私钥。
- 目录权限仅允许当前 macOS 用户访问。
- 另存一份加密备份。
- 打包脚本按品牌选择密钥，不打印私钥内容。
- 第一阶段不接入 GitHub Actions 或其他 CI Secret。

独立密钥是防止跨品牌更新的重要保障。即使 `latest.json` 地址配置错误，OEM A 也不能安装由 DClaw 或 OEM B 密钥签名的更新包。

Tauri updater 签名与 Windows/macOS 操作系统代码签名是两套机制。第一期只实现必需且免费的 Tauri updater 签名，不申请或接入 Apple Developer、Windows Authenticode 或 Azure Artifact Signing。

第一期未做系统代码签名的已知影响：

- Windows 首次安装或更新时可能显示“未知发布者”或 SmartScreen 提示。
- macOS 首次安装时可能需要用户在系统设置中手动允许打开。
- 这些提示不影响 Tauri 对在线更新包执行签名完整性验证。
- 系统代码签名作为后续可选增强，不阻塞 OEM 和强制更新机制上线。

## 10. macOS Universal

macOS 默认生成 Universal 包，将 `aarch64` 与 `x86_64` 架构合并，覆盖 Apple Silicon 和 Intel Mac。

影响主要在构建流程：

- 同时编译两种架构
- 合并原生二进制
- 构建时间和安装包体积增加
- 需要验证所有原生依赖均支持 Intel
- 第一阶段不做 Apple 代码签名和公证；后续接入时对合并后的最终应用执行
- 构建使用 Tauri 的 `universal-apple-darwin` target；静态更新清单同时提供 `darwin-aarch64` 与 `darwin-x86_64` 两个键，并让它们指向同一个 Universal 更新包和签名

业务代码不需要维护两份。构建系统仍保留单架构选项，便于排查依赖问题。

## 11. 发布顺序与原子性

每次发布某个品牌时必须遵循：

1. 选择该品牌并确定独立版本号。
2. 构建 Windows x64 安装包。
3. 构建 macOS Universal DMG 和 updater 包。
4. 生成 updater 签名和 SHA-256。
5. 校验产物内部的品牌、版本、应用 ID、API Base URL 和更新地址。
6. 上传到该部署的全新 `/desktop/<version>/` 目录。
7. 从公网重新下载并校验文件。
8. 最后原子替换该部署域名根路径的 `latest.json`。
9. 服务端随后直接以新 `latest.json.version` 对旧桌面客户端返回 `426`。

客户端产物必须先于不兼容的服务端发布。只要 `latest.json` 尚未切换，线上客户端就不会看到未上传完整的新版本。

### 11.1 前进式回滚

线上版本只允许递增，不允许 updater 自动安装低版本：

- 新版本尚未切换 `latest.json`：直接废弃新版本目录，线上不受影响。
- 新版本已经发布并发现严重问题：从上一个稳定版本恢复代码或立即修复，并发布更高的补丁版本。
- 例如 `1.4.0` 故障时发布 `1.4.1`，不把 `latest.json` 改回 `1.3.0`。

这样避免安装器降级、客户端数据格式倒退以及 Tauri 版本比较异常。

## 12. 构建与发布校验

构建脚本至少应拒绝以下情况：

- `brandId` 重复
- 应用标识符重复
- 品牌名称、版本或 URL 为空
- API Base URL 或更新 URL 不是生产 HTTPS 地址
- OEM 仍使用 DClaw 应用 ID、更新地址或默认品牌资源
- OEM updater 公钥与预期不一致
- 输出目录可能覆盖其他品牌
- Tauri、Cargo 与品牌 `VERSION` 不一致
- Windows 和 macOS 产物版本不一致
- `latest.json` 引用了不存在或未验证的产物

第一期采用严格 OEM 资料门禁。每个 OEM 至少必须提供品牌 Logo 原图、唯一 `brandId`、唯一应用 ID、独立版本、固定 HTTPS API Base URL、主题色以及成对的 updater 公钥和私钥。构建脚本从 Logo 原图生成各平台所需图标。任意必填项缺失时直接失败，绝不回退使用 DClaw 的名称、Logo、应用 ID、API 地址或更新密钥。后续可根据实际 OEM 交付流程调整必填字段。

## 13. 过渡版本

当前已安装的旧客户端尚未内置 updater、品牌身份和全局 `426` 拦截逻辑，服务器无法凭空让这些旧版本自动升级。

需要发布一个一次性的过渡版本，包含：

1. 固化品牌身份和更新配置。
2. Tauri updater。
3. 启动更新门禁。
4. 全局内部 HTTP 请求身份 Header。
5. 全局 `426` 强制更新处理。

现有客户需要手动安装这一次。从过渡版本开始，后续版本才具备完整在线强制更新能力。

## 14. 客户端预计改动范围

业务页面不需要逐页修改。主要改动集中在：

1. 品牌配置目录和品牌配置加载器。
2. 构建时 Tauri 配置生成与品牌校验。
3. 原生应用身份查询接口。
4. Tauri updater 插件初始化。
5. 更新状态管理模块。
6. 品牌化强制更新页面。
7. 应用启动更新门禁。
8. 全局内部 HTTP `fetch` 包装器和 `426` 拦截。
9. 双品牌、双平台构建和发布脚本。
10. 更新服务器目录及 `latest.json` 生成、签名、上传和原子切换。
11. 服务端桌面客户端版本门禁中间件。

整体属于中等规模改造，不需要重写客户端。

## 15. 尚待继续讨论和确认

以下事项尚未最终确定：

1. 宿主机更新目录与 Nginx 静态文件映射的最终配置。
2. OEM 品牌配置的具体维护人和资料交付流程；第一期必填字段和严格门禁已经确定。
3. Windows 与 macOS 系统代码签名已确定不属于第一期，后续有精力时再评估。

## 16. 后续讨论建议顺序

建议后续按以下顺序继续：

1. 明确服务端版本门禁规则和部署时序。
2. 确定品牌配置字段和 OEM 交付物清单。
3. 确定更新服务器域名与存储方式。
4. 确定各品牌 Tauri updater 私钥的保管方式；系统代码签名留到后续阶段。
5. 设计客户端强制更新状态机和页面。
6. 设计构建、上传、验证和发布命令。
7. 拆分实施阶段、测试范围和上线迁移方案。
