# ComfyUI AutoPublish

在 ComfyUI 持续生成图片的同时，直接挑选满意的结果并上传到阿里云 OSS，或发布到自己的 X 账号。上传和发帖任务在后台执行，不会阻塞下一次工作流运行。

> [!NOTE]
> 这是一个 ComfyUI 前端扩展和后端服务，不会向工作流中增加新节点，也不会改变现有节点的执行结果。

## 功能概览

- 监听 ComfyUI 图片输出事件，并在悬浮发布托盘中展示最近 20 张结果。
- 支持 `Save Image`、`Preview Image`、`ImageCompressor` 及其他图片输出节点。
- 可指定只显示某一个节点的结果，适合包含多个预览、保存和压缩节点的工作流。
- 托盘可拖拽、收起，位置和节点筛选保存在当前浏览器中。
- 每张图片可独立执行 `上传 OSS`、`发布 X`，无需等待生成任务全部结束。
- OSS 上传成功后生成 HTTPS URL，并提供 `复制 URL`。
- X 发布前可编辑正文，也可以只发布图片；成功后可直接打开帖子。
- OSS 与 X 均使用后台任务和状态轮询，失败时在对应图片卡片显示原因并允许重试。
- 只允许读取 ComfyUI `input`、`output`、`temp` 目录内的图片。
- “清空卡片”只清理浏览器中的卡片，不会删除任何本地图片。

## 环境要求

- 可正常运行的 ComfyUI。
- Python 3.10 或更高版本。
- 阿里云 OSS 功能需要 [`oss2`](https://pypi.org/project/oss2/)。
- X Token 加密目前使用 Windows DPAPI，需要 `pywin32`；ComfyUI Aki 整合包通常已经包含。
- 使用 X 功能需要 X Developer Project/App 和可用的 X API credits。

## 安装

将插件目录放入：

```text
ComfyUI/custom_nodes/ComfyUI-AutoPublish
```

安装依赖：

```powershell
<ComfyUI使用的Python> -m pip install -r ComfyUI/custom_nodes/ComfyUI-AutoPublish/requirements.txt
```

如果 X 授权时提示缺少 Windows DPAPI 支持，再安装：

```powershell
<ComfyUI使用的Python> -m pip install pywin32
```

完成后重启 ComfyUI，并使用 `Ctrl+F5` 强制刷新浏览器页面。

## 基本使用方法

1. 打开包含图片输出节点的工作流。
2. 运行工作流并等待图片生成。
3. 页面右侧会出现“发布托盘”，新图片会自动加入托盘。
4. 在“显示节点”中选择最终图片节点；留在“所有图片输出节点”则接收全部结果。
5. 对满意的图片点击 `上传 OSS` 或 `发布 X`。
6. 可以继续运行工作流，后台发布不会阻塞生成。

### 发布托盘操作

| 操作 | 说明 |
| --- | --- |
| 拖拽标题栏 | 移动托盘；位置保存在浏览器 `localStorage` |
| `—` / `+` | 收起或展开托盘 |
| 齿轮按钮 | 打开 OSS 配置 |
| `𝕏` | 打开 X 配置和账号状态 |
| 显示节点 | 只显示指定图片输出节点产生的结果 |
| 清空卡片 | 清空当前页面的卡片，不删除图片文件 |
| 点击缩略图 | 在新窗口打开 ComfyUI 原图 |

## 阿里云 OSS 设置

### 1. 创建 Bucket

1. 打开[阿里云 OSS 控制台](https://oss.console.aliyun.com/)。
2. 创建或选择一个 Bucket。
3. 记下 Bucket 名称和所在地域，例如：

   ```text
   Bucket：akizukipic
   地域：华北 2（北京）
   Endpoint：oss-cn-beijing.aliyuncs.com
   ```

> [!IMPORTANT]
> 私有 Bucket 可以正常上传，但复制出的普通 URL 无法直接公开访问。本插件当前不会生成临时签名 URL。如果图片需要公开展示，请配置合适的 Bucket 读权限、CDN 或公开访问域名，并自行评估公开访问风险。

### 2. 创建 RAM 用户和 AccessKey

不要使用阿里云主账号 AccessKey。推荐在[RAM 控制台](https://ram.console.aliyun.com/)创建专用用户，并只授予目标 Bucket 的上传权限。

最小权限策略示例，请将 `your-bucket-name` 替换成真实 Bucket 名称：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "oss:PutObject"
      ],
      "Resource": [
        "acs:oss:*:*:your-bucket-name/*"
      ]
    }
  ]
}
```

为该 RAM 用户创建 AccessKey，并妥善保存：

```text
AccessKey ID
AccessKey Secret
```

AccessKey Secret 通常只在创建时完整显示一次。

### 3. 填写插件 OSS 配置

点击发布托盘右上角的齿轮：

| 字段 | 是否必填 | 示例 | 说明 |
| --- | --- | --- | --- |
| Endpoint | 是 | `https://oss-cn-beijing.aliyuncs.com` | 填地域 Endpoint，不要填写对象 URL |
| Bucket | 是 | `akizukipic` | Bucket 名称，不包含域名 |
| 路径前缀 | 否 | `comfyui/%Y/%m/%d` | 支持日期格式；留空则上传到 Bucket 根目录 |
| AccessKey ID | 是 | `LTAI...` | 专用 RAM 用户的 AccessKey ID |
| AccessKey Secret | 是 | `...` | 保存后再次打开时留空表示不修改 |
| 公开访问域名 | 否 | `https://img.example.com` | CDN、自定义域名或 Bucket 公开域名 |

配置示例：

```text
Endpoint: https://oss-cn-beijing.aliyuncs.com
Bucket: akizukipic
路径前缀: comfyui/%Y/%m/%d
公开访问域名: https://akizukipic.oss-cn-beijing.aliyuncs.com
```

默认路径前缀会根据上传时间展开：

```text
comfyui/2026/08/04/compressed_20260804_120000_0000_1234.jpeg
```

路径前缀不能包含 `..`。如果未配置公开访问域名，插件会根据 Bucket 和 Endpoint 自动生成标准 HTTPS URL：

```text
https://akizukipic.oss-cn-beijing.aliyuncs.com/ComfyUI_00070_.png
```

### 4. 上传与复制 URL

1. 点击图片卡片的 `上传 OSS`。
2. 卡片依次显示排队、上传和完成状态。
3. 上传完成后点击 `复制 URL`。
4. URL 始终带有 `https://` 前缀。

### OSS 配置安全

OSS 配置保存在：

```text
ComfyUI/user/__autopublish/oss.json
```

> [!WARNING]
> AccessKey Secret 会以明文形式保存在本机配置文件中，但不会通过配置查询接口返回浏览器。请使用最小权限 RAM 用户，不要提交 `oss.json`，也不要将带有本插件的 ComfyUI 服务直接暴露到公网。

## X 设置

> [!CAUTION]
> **X API 需要付费 credits。** 当前 X API 采用按量付费，不是免费的发帖接口。余额为 0 时会返回 `credits depleted`，插件无法绕过。根据 X 官方在 2026 年 8 月公布的价格，普通 `Post: Create` 为 **$0.015/次**，正文包含 URL 的 `Post: Create (with URL)` 为 **$0.200/次**，授权后读取账号资料 `User: Read` 为 **$0.010/次**。媒体及其他端点可能产生额外费用，价格可能随时调整，请始终以 [X API Pricing](https://docs.x.com/x-api/getting-started/pricing) 和 [Developer Console](https://console.x.com) 为准。
>
> 建议首次只购买少量 credits，关闭自动充值并设置 Spending Limit。普通图片帖正文尽量不要包含 OSS URL；图片已经通过媒体接口上传，无需再次附加链接。

### 费用估算

以下仅按普通发帖 `$0.015`，并预留少量媒体端点费用进行粗略估算，不包含汇率和税费：

| 发布数量 | 预计 API 消耗 |
| ---: | ---: |
| 10 张 | 约 `$0.15～$0.20` |
| 100 张 | 约 `$1.50～$2.00` |
| 1,000 张 | 约 `$15～$20` |

如果正文包含 URL，仅创建帖子本身就是 `$0.200/次`，100 条约为 `$20`，还未计算其他端点费用。

### 1. 创建 X Developer Project 和 App

1. 登录 [X Developer Portal](https://developer.x.com/en/portal/dashboard)。
2. 创建 Project 和 App。
3. 根据页面要求填写 API 使用场景。建议如实说明：仅把本机 ComfyUI 生成的图片手动发布到用户自己的 X 账号，不抓取时间线、不自动互动、不出售数据。
4. 进入 App 的 User authentication settings。

### 2. 配置 OAuth 2.0

在 User authentication settings 中填写：

| 项目 | 设置 |
| --- | --- |
| App permissions | `Read and write` |
| Request email from users | 关闭 |
| Type of App | `Native App` / Public client |
| Callback URI / Redirect URL | `http://127.0.0.1:17863/x/callback` |
| Website URL | 有效的 HTTPS 页面，例如个人主页或项目主页 |
| Organization / Terms / Privacy | 未启用邮箱权限时通常可按控制台要求填写或留空 |

> [!IMPORTANT]
> Callback URI 必须逐字符一致，包括 `http`、`127.0.0.1`、端口和路径。不要使用旧地址 `http://127.0.0.1:8188/api/autopublish/x/oauth/callback`，它会被 ComfyUI 的跨站安全中间件返回 403。

保存后复制 **OAuth 2.0 Client ID**。本插件使用 PKCE 公开客户端流程，不需要 Client Secret，也不要把 API Key、API Secret 或 Bearer Token 填进插件。

插件申请以下 OAuth 范围：

```text
tweet.read tweet.write users.read media.write offline.access
```

### 3. 购买 API credits

1. 打开 [X Developer Console](https://console.x.com)。
2. 进入 Billing、Credits 或 Usage 页面。
3. 购买少量 credits。
4. 建议关闭 Auto-recharge，或设置较低的 Recharge amount 和 Spending Limit。
5. credits 实时扣除，余额耗尽后 X API 会停止服务。

### 4. 填写插件 X 配置

点击发布托盘右上角的 `𝕏`：

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| Client ID | 是 | X App 的 OAuth 2.0 Client ID |
| Callback URI | 是 | 默认 `http://127.0.0.1:17863/x/callback`，必须与 X 后台一致 |
| HTTP 代理 | 否 | 无法直连 X 时填写，例如 `http://127.0.0.1:7890` |
| 默认帖子正文 | 否 | 每次发布前仍可单独修改 |

点击 `保存配置`，然后点击 `连接 X`。在弹出的 X 页面确认授权，成功后托盘顶部会显示：

```text
X @你的用户名
```

### 5. 为什么使用 17863 回调端口

X 授权页面属于外部站点，直接回跳到 ComfyUI `/api` 会触发 ComfyUI 的跨站保护并返回 403。插件会在开始授权时临时监听：

```text
127.0.0.1:17863
```

授权结束后自动关闭监听。服务只绑定本机回环地址，不对局域网或公网开放。如果端口被其他程序占用，可以在 X 后台和插件中同时改成另一个未占用的本机端口，两处必须一致。

### 6. 中国大陆网络与代理

浏览器能打开 X，不代表 ComfyUI 的 Python 进程也能访问 `api.x.com`。如果授权结果显示“连接 X API 超时”，填写代理软件提供的 HTTP 或 Mixed 代理地址：

```text
http://127.0.0.1:7890
```

`7890` 只是常见示例，必须以代理软件实际显示的端口为准。插件还会自动读取：

```text
HTTP_PROXY
HTTPS_PROXY
```

当前不支持需要用户名或密码的代理 URL。仅浏览器扩展内部使用的代理通常不能直接提供给 ComfyUI，需要代理软件开放本机 HTTP/Mixed 端口。

### 7. 发布到 X

1. 点击图片卡片的 `发布 X`。
2. 在确认面板中编辑正文；正文可以留空。
3. 点击 `确认发布`。
4. 后台依次刷新授权、上传媒体和创建帖子。
5. 成功后按钮变为 `打开 X`。

当前限制：

- 每次发布 1 张图片。
- 支持 JPG、PNG、GIF、WEBP。
- 单张图片最大 5 MB。
- X 会根据账号权限校验正文长度。
- 含 URL 的正文可能按更高的 X API 单价计费。

### X Token 安全

X 配置保存在：

```text
ComfyUI/user/__autopublish/x.json
```

Access Token 和 Refresh Token 使用 Windows DPAPI 加密，通常只有当前 Windows 用户能够解密。配置查询接口不会返回 Token。Client ID、Callback URI、代理地址和默认正文不是秘密，会以普通配置保存。

点击“断开账号”只会移除本机保存的授权。如果需要在 X 侧彻底撤销授权，请同时前往 X 账号的已连接应用设置中撤销该 App。

## 配置和本地数据

| 数据 | 保存位置 | 说明 |
| --- | --- | --- |
| OSS 配置 | `ComfyUI/user/__autopublish/oss.json` | AccessKey Secret 本机明文保存 |
| X 配置 | `ComfyUI/user/__autopublish/x.json` | Token 使用 Windows DPAPI 加密 |
| 托盘位置 | 浏览器 `localStorage` | 每个浏览器独立保存 |
| 节点筛选 | 浏览器 `localStorage` | 保存节点 ID |
| 图片卡片 | 当前页面内存 | 刷新页面后清空 |

本插件不会自动删除、移动或修改本地图片。只有明确点击发布按钮时，选中的图片才会发送到 OSS 或 X。

## 常见问题

### 托盘没有出现图片

- 确认节点的执行结果包含 ComfyUI 标准 `images` 输出。
- 检查“显示节点”是否选中了其他节点。
- 先运行一次工作流，让插件发现图片输出节点。
- 使用 `Ctrl+F5` 刷新前端扩展。

### ImageCompressor 图片没有显示或找不到文件

插件支持 ComfyUI `input`、`output`、`temp` 目录内的相对和绝对子目录。确认压缩插件最终返回了图片信息，并且文件仍位于上述目录中。

### OSS 上传成功，但复制的 URL 无法打开

这通常是 Bucket 为私有读权限。请配置公开读策略、CDN/自定义域名，或在其他系统中生成签名 URL。本插件当前只返回普通 HTTPS 对象 URL。

### OSS 返回 AccessDenied

检查 RAM 用户是否具有目标 Bucket 和对象路径的 `oss:PutObject` 权限，并确认 Endpoint 与 Bucket 地域一致。

### X 授权回调显示 HTTP 403

确认 X 后台和插件都使用：

```text
http://127.0.0.1:17863/x/callback
```

不要使用旧的 ComfyUI `/api/autopublish/x/oauth/callback` 地址。

### X 授权显示“连接 X API 超时”

ComfyUI Python 无法直连 `api.x.com`。在 X 配置中填写可用的 HTTP/Mixed 代理地址后，重新发起授权。授权 code 只能使用一次，超时后必须重新点击 `连接 X`。

### X 发布显示 `credits depleted`

OAuth、回调和网络通常已经成功，但 X Developer Project 没有可用 credits。前往 Developer Console 充值后直接重试，无需重新创建 Client ID。

### X 返回 401 或授权过期

插件会使用 `offline.access` 自动刷新 Token。如果 Refresh Token 被撤销或失效，请点击 `𝕏` 后重新连接账号。

### X 图片格式或大小错误

确保图片是 JPG、PNG、GIF 或 WEBP，并且不超过 5 MB。可以先通过 ImageCompressor 压缩后再发布。

## 安全建议

- 不要把 `ComfyUI/user/__autopublish/` 提交到 Git。
- 不要截图或分享 AccessKey Secret、OAuth Token、授权 code。
- OSS 使用专用 RAM 用户和最小权限策略。
- X 设置较低的 Spending Limit，谨慎开启自动充值。
- 不要将没有额外认证保护的 ComfyUI 直接暴露到公网。
- 分发插件时优先让每位用户填写自己的 Client ID，由各自的 X Project 承担 credits 和合规责任。

## 外部文档

- [阿里云 OSS 控制台](https://oss.console.aliyun.com/)
- [阿里云 RAM 控制台](https://ram.console.aliyun.com/)
- [X Developer Portal](https://developer.x.com/en/portal/dashboard)
- [X Developer Console](https://console.x.com)
- [X OAuth 2.0 Authorization Code with PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)
- [X API Pricing](https://docs.x.com/x-api/getting-started/pricing)
- [X Media Upload](https://docs.x.com/x-api/media/upload-media)
- [X Create Post](https://docs.x.com/x-api/posts/create-or-edit-post)
