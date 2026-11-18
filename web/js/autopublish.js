import { api } from "../../../scripts/api.js";
import { app } from "../../../scripts/app.js";


const extensionName = "ComfyUI.AutoPublish";
const storageKey = "ComfyUI.AutoPublish.collapsed";
const positionStorageKey = "ComfyUI.AutoPublish.position";
const sourceStorageKey = "ComfyUI.AutoPublish.sourceNode";
const maxCards = 20;
let refreshSourceOptions = () => {};

const style = document.createElement("style");
style.textContent = `
    .autopublish-tray {
        --ap-panel: rgba(24, 27, 33, 0.96);
        --ap-card: #20242c;
        --ap-card-hover: #252a34;
        --ap-line: rgba(255, 255, 255, 0.09);
        --ap-text: #f2f5f8;
        --ap-muted: #9aa4b2;
        --ap-oss: #51a8ff;
        --ap-accent: #77d4c7;
        --ap-good: #7fd59a;
        --ap-local: #e6bd72;
        position: fixed;
        z-index: 10020;
        top: 132px;
        left: calc(100vw - 386px);
        width: min(368px, calc(100vw - 28px));
        max-height: calc(100vh - 96px);
        overflow: hidden;
        color: var(--ap-text);
        background: var(--ap-panel);
        border: 1px solid var(--ap-line);
        border-radius: 14px;
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.34);
        backdrop-filter: blur(14px);
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    }

    .autopublish-tray.is-dragging {
        user-select: none;
        box-shadow: 0 22px 56px rgba(0, 0, 0, 0.46);
    }

    .autopublish-tray.is-collapsed {
        width: auto;
        border-radius: 999px;
    }

    .autopublish-header {
        min-height: 54px;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 12px 0 15px;
        border-bottom: 1px solid var(--ap-line);
        cursor: grab;
        touch-action: none;
    }

    .autopublish-tray.is-dragging .autopublish-header {
        cursor: grabbing;
    }

    .autopublish-tray.is-collapsed .autopublish-header {
        min-height: 42px;
        padding: 0 8px 0 13px;
        border-bottom: 0;
        cursor: pointer;
    }

    .autopublish-mark {
        width: 9px;
        height: 9px;
        flex: 0 0 auto;
        border-radius: 50%;
        background: var(--ap-accent);
        box-shadow: 0 0 0 4px rgba(119, 212, 199, 0.12);
    }

    .autopublish-heading {
        min-width: 0;
        flex: 1;
    }

    .autopublish-title {
        font-family: Bahnschrift, "Segoe UI", sans-serif;
        font-size: 14px;
        font-weight: 650;
        letter-spacing: 0.02em;
    }

    .autopublish-subtitle {
        margin-top: 2px;
        color: var(--ap-muted);
        font-size: 11px;
    }

    .autopublish-tray.is-collapsed .autopublish-subtitle,
    .autopublish-tray.is-collapsed .autopublish-toolbar,
    .autopublish-tray.is-collapsed .autopublish-body {
        display: none;
    }

    .autopublish-count {
        display: inline-flex;
        min-width: 20px;
        height: 20px;
        align-items: center;
        justify-content: center;
        padding: 0 6px;
        color: #101419;
        background: var(--ap-accent);
        border-radius: 999px;
        font: 700 11px/1 Consolas, monospace;
    }

    .autopublish-icon-button {
        width: 30px;
        height: 30px;
        display: inline-grid;
        place-items: center;
        padding: 0;
        color: var(--ap-muted);
        background: transparent;
        border: 0;
        border-radius: 8px;
        cursor: pointer;
    }

    .autopublish-icon-button:hover {
        color: var(--ap-text);
        background: rgba(255, 255, 255, 0.07);
    }

    .autopublish-icon-button.is-local {
        color: var(--ap-local);
    }

    .autopublish-icon-button:focus-visible,
    .autopublish-action:focus-visible {
        outline: 2px solid var(--ap-accent);
        outline-offset: 2px;
    }

    .autopublish-body {
        max-height: calc(100vh - 151px);
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: #4a5361 transparent;
    }

    .autopublish-toolbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 9px 12px;
        color: var(--ap-muted);
        font-size: 11px;
        border-bottom: 1px solid var(--ap-line);
    }

    .autopublish-toolbar > span {
        min-width: 0;
        flex: 1;
        line-height: 1.35;
    }

    .autopublish-filter {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 8px;
        align-items: center;
        padding: 9px 12px;
        border-bottom: 1px solid var(--ap-line);
    }

    .autopublish-filter label {
        color: var(--ap-muted);
        font-size: 11px;
    }

    .autopublish-filter select,
    .autopublish-field input,
    .autopublish-field textarea,
    .autopublish-composer textarea {
        width: 100%;
        min-width: 0;
        box-sizing: border-box;
        color: var(--ap-text);
        background: #171a20;
        border: 1px solid var(--ap-line);
        border-radius: 7px;
        outline: 0;
    }

    .autopublish-filter select {
        height: 30px;
        padding: 0 8px;
        font-size: 11px;
    }

    .autopublish-filter select:focus,
    .autopublish-field input:focus,
    .autopublish-field textarea:focus,
    .autopublish-composer textarea:focus {
        border-color: var(--ap-accent);
        box-shadow: 0 0 0 2px rgba(119, 212, 199, 0.1);
    }

    .autopublish-config {
        padding: 12px;
        background: rgba(12, 14, 18, 0.45);
        border-bottom: 1px solid var(--ap-line);
    }

    .autopublish-config[hidden] {
        display: none;
    }

    .autopublish-config-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 9px;
    }

    .autopublish-config-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 10px;
        font-family: Bahnschrift, "Segoe UI", sans-serif;
        font-size: 12px;
        font-weight: 650;
    }

    .autopublish-x-account {
        color: var(--ap-muted);
        font: 500 10px/1.3 "Segoe UI", sans-serif;
    }

    .autopublish-field {
        display: grid;
        gap: 5px;
        color: var(--ap-muted);
        font-size: 10px;
    }

    .autopublish-field.is-wide {
        grid-column: 1 / -1;
    }

    .autopublish-field input {
        height: 32px;
        padding: 0 9px;
        font-size: 11px;
    }

    .autopublish-field textarea {
        min-height: 76px;
        resize: vertical;
        padding: 8px 9px;
        font: 11px/1.45 "Segoe UI", "Microsoft YaHei UI", sans-serif;
    }

    .autopublish-config-note {
        margin: 9px 0;
        color: var(--ap-muted);
        font-size: 10px;
        line-height: 1.45;
    }

    .autopublish-save-config {
        width: 100%;
        min-height: 32px;
        color: #10211e;
        background: var(--ap-accent);
        border: 0;
        border-radius: 7px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 700;
    }

    .autopublish-config-actions {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 7px;
    }

    .autopublish-config-action {
        min-height: 32px;
        color: var(--ap-text);
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid var(--ap-line);
        border-radius: 7px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 650;
    }

    .autopublish-config-action.is-primary {
        color: #11151a;
        background: #f3f5f7;
        border-color: #f3f5f7;
    }

    .autopublish-config-action:hover:not(:disabled) {
        border-color: currentColor;
    }

    .autopublish-config-action:disabled {
        cursor: default;
        opacity: 0.45;
    }

    .autopublish-config-actions > :last-child:nth-child(3) {
        grid-column: 1 / -1;
    }

    .autopublish-composer {
        display: grid;
        gap: 9px;
        padding: 12px;
        background: #16191f;
        border-bottom: 1px solid var(--ap-line);
        box-shadow: inset 3px 0 #f3f5f7;
    }

    .autopublish-composer[hidden] {
        display: none;
    }

    .autopublish-composer-head,
    .autopublish-composer-meta {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
    }

    .autopublish-composer-head strong {
        font: 650 12px/1.3 Bahnschrift, "Segoe UI", sans-serif;
    }

    .autopublish-composer-file {
        max-width: 210px;
        overflow: hidden;
        color: var(--ap-muted);
        font: 10px/1.3 Consolas, monospace;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .autopublish-composer textarea {
        min-height: 92px;
        resize: vertical;
        padding: 9px;
        font: 12px/1.5 "Segoe UI", "Microsoft YaHei UI", sans-serif;
    }

    .autopublish-composer-meta {
        color: var(--ap-muted);
        font-size: 10px;
    }

    .autopublish-composer-actions {
        display: grid;
        grid-template-columns: 0.7fr 1.3fr;
        gap: 7px;
    }

    .autopublish-save-config:disabled {
        cursor: wait;
        opacity: 0.65;
    }

    .autopublish-clear {
        padding: 3px 0;
        color: var(--ap-muted);
        background: transparent;
        border: 0;
        cursor: pointer;
        font: inherit;
    }

    .autopublish-clear:hover {
        color: var(--ap-text);
    }

    .autopublish-empty {
        margin: 12px;
        padding: 32px 20px;
        text-align: center;
        border: 1px dashed rgba(255, 255, 255, 0.13);
        border-radius: 11px;
    }

    .autopublish-empty strong {
        display: block;
        margin-bottom: 7px;
        font-family: Bahnschrift, "Segoe UI", sans-serif;
        font-size: 14px;
        font-weight: 600;
    }

    .autopublish-empty span {
        color: var(--ap-muted);
        font-size: 12px;
        line-height: 1.55;
    }

    .autopublish-list {
        display: grid;
        gap: 8px;
        padding: 10px;
    }

    .autopublish-card {
        position: relative;
        display: grid;
        grid-template-columns: 112px minmax(0, 1fr);
        min-height: 112px;
        overflow: hidden;
        background: var(--ap-card);
        border: 1px solid var(--ap-line);
        border-radius: 11px;
    }

    .autopublish-card[hidden] {
        display: none;
    }

    .autopublish-card::before {
        content: "";
        position: absolute;
        z-index: 1;
        inset: 0 auto 0 0;
        width: 3px;
        background: #59616e;
    }

    .autopublish-card[data-state="working"]::before {
        background: linear-gradient(180deg, var(--ap-oss), var(--ap-accent));
    }

    .autopublish-card[data-state="done"]::before {
        background: var(--ap-good);
    }

    .autopublish-card:hover {
        background: var(--ap-card-hover);
    }

    .autopublish-thumb {
        width: 112px;
        height: 112px;
        object-fit: cover;
        background: #15181e;
        cursor: zoom-in;
    }

    .autopublish-card-content {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 10px;
    }

    .autopublish-filename {
        overflow: hidden;
        color: var(--ap-text);
        font: 600 12px/1.3 Consolas, "Microsoft YaHei UI", monospace;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .autopublish-source {
        overflow: hidden;
        color: var(--ap-muted);
        font-size: 10px;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .autopublish-status {
        min-height: 30px;
        color: var(--ap-muted);
        font-size: 11px;
        line-height: 1.4;
    }

    .autopublish-status a {
        color: var(--ap-good);
        text-decoration: none;
    }

    .autopublish-status a:hover {
        text-decoration: underline;
    }

    .autopublish-actions {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 6px;
        margin-top: auto;
    }

    .autopublish-action {
        min-height: 30px;
        padding: 5px 7px;
        border: 1px solid var(--ap-line);
        border-radius: 7px;
        cursor: pointer;
        font: 650 11px/1 "Segoe UI", "Microsoft YaHei UI", sans-serif;
    }

    .autopublish-action[data-destination="oss"] {
        color: #dceeff;
        background: rgba(81, 168, 255, 0.13);
    }

    .autopublish-action[data-destination="x"] {
        color: #f3f5f7;
        background: rgba(255, 255, 255, 0.075);
    }

    .autopublish-action[data-destination="local"] {
        color: #fff0cf;
        background: rgba(230, 189, 114, 0.12);
    }

    .autopublish-copy {
        color: #dcf7e4;
        background: rgba(127, 213, 154, 0.13);
    }

    .autopublish-action:hover:not(:disabled) {
        border-color: currentColor;
        filter: brightness(1.08);
    }

    .autopublish-action:disabled {
        cursor: default;
        opacity: 0.58;
    }

    @media (max-width: 620px) {
        .autopublish-tray {
            width: calc(100vw - 20px);
            max-height: min(70vh, 560px);
        }

        .autopublish-body {
            max-height: calc(min(70vh, 560px) - 55px);
        }
    }

    @media (prefers-reduced-motion: no-preference) {
        .autopublish-card:first-child {
            animation: autopublish-arrive 180ms ease-out;
        }
        @keyframes autopublish-arrive {
            from { opacity: 0; transform: translateY(-5px); }
            to { opacity: 1; transform: translateY(0); }
        }
    }
`;
document.head.appendChild(style);


function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}


function imageKey(image, nodeId) {
    return JSON.stringify([nodeId, image.filename, image.subfolder || "", image.type || "output"]);
}


function imageUrl(image) {
    const params = new URLSearchParams({
        filename: image.filename,
        subfolder: image.subfolder || "",
        type: image.type || "output",
        t: Date.now().toString(),
    });
    return api.apiURL(`/view?${params.toString()}`);
}


async function copyText(text) {
    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (_error) {
            // Fall back for non-secure contexts or denied clipboard permission.
        }
    }
    const input = document.createElement("textarea");
    input.value = text;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("浏览器拒绝访问剪贴板");
}


app.registerExtension({
    name: extensionName,
    async setup() {
        const tray = element("aside", "autopublish-tray");
        const header = element("div", "autopublish-header");
        const mark = element("span", "autopublish-mark");
        const heading = element("div", "autopublish-heading");
        const title = element("div", "autopublish-title", "发布托盘");
        const subtitle = element("div", "autopublish-subtitle", "生成不停，挑中就发");
        const count = element("span", "autopublish-count", "0");
        const configToggle = element("button", "autopublish-icon-button", "⚙");
        configToggle.type = "button";
        configToggle.title = "配置 OSS";
        configToggle.setAttribute("aria-label", "配置 OSS");
        const xConfigToggle = element("button", "autopublish-icon-button", "𝕏");
        xConfigToggle.type = "button";
        xConfigToggle.title = "配置 X";
        xConfigToggle.setAttribute("aria-label", "配置 X");
        const localConfigToggle = element("button", "autopublish-icon-button is-local", "★");
        localConfigToggle.type = "button";
        localConfigToggle.title = "配置本地精选目录";
        localConfigToggle.setAttribute("aria-label", "配置本地精选目录");
        const collapse = element("button", "autopublish-icon-button", "—");
        collapse.type = "button";
        collapse.title = "收起发布托盘";
        collapse.setAttribute("aria-label", "收起发布托盘");

        heading.append(title, subtitle);
        header.append(mark, heading, count, configToggle, xConfigToggle, localConfigToggle, collapse);

        const toolbar = element("div", "autopublish-toolbar");
        const connectionStatus = element("span", "", "正在读取 OSS 配置…");
        toolbar.append(connectionStatus);
        const clear = element("button", "autopublish-clear", "清空卡片");
        clear.type = "button";
        clear.title = "只清空托盘卡片，不删除图片文件";
        toolbar.append(clear);

        const filter = element("div", "autopublish-filter");
        const filterLabel = element("label", "", "显示节点");
        const sourceSelect = element("select");
        filterLabel.htmlFor = "autopublish-source-select";
        sourceSelect.id = "autopublish-source-select";
        filter.append(filterLabel, sourceSelect);

        const configPanel = element("section", "autopublish-config");
        configPanel.hidden = true;
        const configGrid = element("div", "autopublish-config-grid");
        const configInputs = {};
        const addConfigField = (labelText, name, placeholder, wide = false, type = "text") => {
            const field = element("label", `autopublish-field${wide ? " is-wide" : ""}`, labelText);
            const input = element("input");
            input.type = type;
            input.name = name;
            input.placeholder = placeholder;
            input.autocomplete = type === "password" ? "new-password" : "off";
            field.appendChild(input);
            configGrid.appendChild(field);
            configInputs[name] = input;
        };
        addConfigField("Endpoint", "endpoint", "https://oss-cn-shanghai.aliyuncs.com", true);
        addConfigField("Bucket", "bucket", "my-image-bucket");
        addConfigField("路径前缀", "prefix", "comfyui/%Y/%m/%d");
        addConfigField("AccessKey ID", "access_key_id", "LTAI…", true);
        addConfigField("AccessKey Secret", "access_key_secret", "留空表示不修改", true, "password");
        addConfigField("公开访问域名（可选）", "public_base_url", "https://img.example.com", true);
        const configNote = element("div", "autopublish-config-note", "密钥只保存在本机 ComfyUI/user/__autopublish/oss.json，不会返回到前端。请勿将 ComfyUI 暴露到公网。");
        const saveConfig = element("button", "autopublish-save-config", "保存 OSS 配置");
        saveConfig.type = "button";
        configPanel.append(configGrid, configNote, saveConfig);

        const xConfigPanel = element("section", "autopublish-config");
        xConfigPanel.hidden = true;
        const xConfigTitle = element("div", "autopublish-config-title");
        xConfigTitle.append(
            element("span", "", "X 官方 API"),
            element("span", "autopublish-x-account", "尚未连接"),
        );
        const xAccount = xConfigTitle.lastElementChild;
        const xConfigGrid = element("div", "autopublish-config-grid");
        const xInputs = {};
        const addXField = (labelText, name, placeholder, multiline = false) => {
            const field = element("label", "autopublish-field is-wide", labelText);
            const input = element(multiline ? "textarea" : "input");
            input.name = name;
            input.placeholder = placeholder;
            input.autocomplete = "off";
            field.appendChild(input);
            xConfigGrid.appendChild(field);
            xInputs[name] = input;
        };
        addXField("Client ID", "client_id", "X Developer Portal 中 OAuth 2.0 Client ID");
        addXField("Callback URI", "redirect_uri", "http://127.0.0.1:17863/x/callback");
        addXField("HTTP 代理（无法直连 X 时填写）", "proxy_url", "例如 http://127.0.0.1:7890");
        addXField("默认帖子正文（可选）", "default_text", "每次发布前仍可修改", true);
        const xConfigNote = element(
            "div",
            "autopublish-config-note",
            "请把 Callback URI 原样填入 X Developer Portal。若浏览器能打开 X、授权却提示 API 超时，请填写代理软件提供的 HTTP/Mixed 代理地址；插件也会自动读取 HTTPS_PROXY 环境变量。",
        );
        const xConfigActions = element("div", "autopublish-config-actions");
        const saveXConfig = element("button", "autopublish-config-action", "保存配置");
        saveXConfig.type = "button";
        const connectX = element("button", "autopublish-config-action is-primary", "连接 X");
        connectX.type = "button";
        const disconnectX = element("button", "autopublish-config-action", "断开账号");
        disconnectX.type = "button";
        disconnectX.hidden = true;
        xConfigActions.append(saveXConfig, connectX, disconnectX);
        xConfigPanel.append(xConfigTitle, xConfigGrid, xConfigNote, xConfigActions);

        const localConfigPanel = element("section", "autopublish-config");
        localConfigPanel.hidden = true;
        const localConfigTitle = element("div", "autopublish-config-title");
        localConfigTitle.append(
            element("span", "", "本地精选目录"),
            element("span", "autopublish-x-account", "尚未设置"),
        );
        const localAccount = localConfigTitle.lastElementChild;
        const localConfigGrid = element("div", "autopublish-config-grid");
        const localField = element("label", "autopublish-field is-wide", "精选结果文件夹");
        const localDirectoryInput = element("input");
        localDirectoryInput.type = "text";
        localDirectoryInput.name = "output_directory";
        localDirectoryInput.placeholder = "例如 D:\\Pictures\\ComfyUI-Selected";
        localDirectoryInput.autocomplete = "off";
        localField.appendChild(localDirectoryInput);
        localConfigGrid.appendChild(localField);
        const localConfigNote = element(
            "div",
            "autopublish-config-note",
            "点击图片卡片的“输出本地”后，插件会复制原图并保留文件时间等信息。同名时自动添加 _1、_2，不会覆盖已有文件。",
        );
        const saveLocalConfig = element("button", "autopublish-save-config", "保存本地目录");
        saveLocalConfig.type = "button";
        localConfigPanel.append(localConfigTitle, localConfigGrid, localConfigNote, saveLocalConfig);

        const composer = element("section", "autopublish-composer");
        composer.hidden = true;
        const composerHead = element("div", "autopublish-composer-head");
        composerHead.append(
            element("strong", "", "发布到 X"),
            element("span", "autopublish-composer-file", ""),
        );
        const composerFile = composerHead.lastElementChild;
        const composerText = element("textarea");
        composerText.placeholder = "添加帖子正文（可留空，仅发布图片）";
        const composerMeta = element("div", "autopublish-composer-meta");
        const composerCount = element("span", "", "0 字符");
        composerMeta.append(composerCount, element("span", "", "发布前最后确认"));
        const composerActions = element("div", "autopublish-composer-actions");
        const cancelComposer = element("button", "autopublish-config-action", "取消");
        cancelComposer.type = "button";
        const confirmComposer = element("button", "autopublish-config-action is-primary", "确认发布");
        confirmComposer.type = "button";
        composerActions.append(cancelComposer, confirmComposer);
        composer.append(composerHead, composerText, composerMeta, composerActions);

        const body = element("div", "autopublish-body");
        const empty = element("div", "autopublish-empty");
        const emptyTitle = element("strong", "", "等待下一张成图");
        const emptyText = element("span", "", "选择一个图片输出节点，托盘只接收它之后产生的图片。");
        empty.append(emptyTitle, emptyText);
        const list = element("div", "autopublish-list");
        body.append(toolbar, filter, configPanel, xConfigPanel, localConfigPanel, composer, empty, list);
        tray.append(header, body);
        document.body.appendChild(tray);

        const cards = new Map();
        const activeJobs = new Map();
        const activeXJobs = new Map();
        const activeLocalJobs = new Map();
        const observedSources = new Map();
        let pollTimer = null;
        let xPollTimer = null;
        let localPollTimer = null;
        let xAuthPollTimer = null;
        let configReady = false;
        let xReady = false;
        let localReady = false;
        let xDefaultText = "";
        let ossStatusText = "正在读取 OSS 配置…";
        let xStatusText = "正在读取 X 配置…";
        let localStatusText = "正在读取本地目录…";
        let composerTarget = null;
        let ignoreHeaderClick = false;

        const nodeLabel = (nodeId) => {
            const node = app.graph?.getNodeById?.(nodeId);
            return node?.title || node?.type || observedSources.get(String(nodeId)) || `节点 #${nodeId}`;
        };

        const isImageOutputNode = (node) => {
            const data = node?.constructor?.nodeData;
            const name = `${node?.type || ""} ${node?.title || ""}`;
            return Boolean(data?.output_node) || /(save|preview|compressor|image output)/i.test(name);
        };

        const applySourceFilter = () => {
            const selected = sourceSelect.value;
            let visible = 0;
            for (const card of cards.values()) {
                const show = !selected || card.dataset.nodeId === selected;
                card.hidden = !show;
                if (show) visible += 1;
            }
            count.textContent = String(visible);
            empty.hidden = visible > 0;
            emptyTitle.textContent = selected ? "等待所选节点出图" : "等待下一张成图";
            emptyText.textContent = selected
                ? `当前只显示 #${selected} · ${nodeLabel(selected)} 的结果。`
                : "选择一个图片输出节点，托盘只接收它之后产生的图片。";
        };

        refreshSourceOptions = () => {
            for (const node of app.graph?._nodes || []) {
                if (isImageOutputNode(node)) observedSources.set(String(node.id), nodeLabel(node.id));
            }

            const wanted = sourceSelect.value || localStorage.getItem(sourceStorageKey) || "";
            sourceSelect.replaceChildren();
            const allOption = element("option", "", "所有图片输出节点");
            allOption.value = "";
            sourceSelect.appendChild(allOption);

            const sources = [...observedSources.entries()].sort((a, b) => Number(a[0]) - Number(b[0]));
            for (const [nodeId, label] of sources) {
                const option = element("option", "", `#${nodeId} · ${label}`);
                option.value = nodeId;
                sourceSelect.appendChild(option);
            }
            if (wanted && !observedSources.has(wanted)) {
                const missing = element("option", "", `#${wanted} · 当前工作流未找到`);
                missing.value = wanted;
                sourceSelect.appendChild(missing);
            }
            sourceSelect.value = wanted;
            applySourceFilter();
        };

        const clampTrayPosition = (left, top, save = false) => {
            const maxLeft = Math.max(8, window.innerWidth - tray.offsetWidth - 8);
            const maxTop = Math.max(8, window.innerHeight - 50);
            const position = {
                left: Math.min(Math.max(8, left), maxLeft),
                top: Math.min(Math.max(8, top), maxTop),
            };
            tray.style.left = `${position.left}px`;
            tray.style.top = `${position.top}px`;
            if (save) localStorage.setItem(positionStorageKey, JSON.stringify(position));
        };

        const restoreTrayPosition = () => {
            let position;
            try {
                position = JSON.parse(localStorage.getItem(positionStorageKey));
            } catch (_error) {
                position = null;
            }
            const left = Number.isFinite(position?.left) ? position.left : window.innerWidth - tray.offsetWidth - 18;
            const top = Number.isFinite(position?.top) ? position.top : 132;
            clampTrayPosition(left, top);
        };

        const setCollapsed = (collapsed) => {
            tray.classList.toggle("is-collapsed", collapsed);
            collapse.textContent = collapsed ? "+" : "—";
            collapse.title = collapsed ? "展开发布托盘" : "收起发布托盘";
            collapse.setAttribute("aria-label", collapse.title);
            localStorage.setItem(storageKey, collapsed ? "1" : "0");
            window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop, true));
        };

        const renderConnectionStatus = () => {
            connectionStatus.textContent = `${ossStatusText} · ${xStatusText} · ${localStatusText}`;
            mark.style.background = (configReady || xReady || localReady) ? "var(--ap-good)" : "var(--ap-accent)";
        };

        const setConfigStatus = (config, error = "") => {
            configReady = Boolean(config?.configured);
            ossStatusText = error || (configReady ? `OSS ${config.bucket}` : "OSS 未配置");
            renderConnectionStatus();
        };

        const setXConfigStatus = (config, error = "") => {
            xReady = Boolean(config?.connected);
            xDefaultText = config?.default_text ?? "";
            const account = config?.username ? `@${config.username}` : "X 账号";
            xStatusText = error || (xReady ? `X ${account}` : "X 未连接");
            xAccount.textContent = error || (xReady ? `已连接 ${account}` : "尚未连接");
            connectX.textContent = xReady ? "重新授权" : "连接 X";
            disconnectX.hidden = !xReady;
            renderConnectionStatus();
        };

        const setLocalConfigStatus = (config, error = "") => {
            localReady = Boolean(config?.configured);
            const directory = config?.output_directory || "";
            localStatusText = error || (localReady ? "本地精选 ✓" : "本地未设置");
            localAccount.textContent = error || (localReady ? "已设置" : "尚未设置");
            localAccount.title = directory;
            localConfigToggle.title = localReady
                ? `本地精选目录：${directory}`
                : "配置本地精选目录";
            renderConnectionStatus();
        };

        const loadConfig = async () => {
            try {
                const response = await api.fetchApi("/autopublish/oss/config", { cache: "no-store" });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                const config = payload.config;
                for (const name of ["endpoint", "bucket", "prefix", "public_base_url", "access_key_id"]) {
                    configInputs[name].value = config[name] || "";
                }
                configInputs.access_key_secret.value = "";
                setConfigStatus(config);
            } catch (error) {
                setConfigStatus(null, `配置读取失败：${error.message}`);
            }
        };

        const loadLocalConfig = async () => {
            try {
                const response = await api.fetchApi("/autopublish/local/config", { cache: "no-store" });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                const config = payload.config;
                localDirectoryInput.value = config.output_directory || "";
                setLocalConfigStatus(config);
                return config;
            } catch (error) {
                setLocalConfigStatus(null, `本地配置读取失败：${error.message}`);
                return null;
            }
        };

        const defaultRedirectUri = () => "http://127.0.0.1:17863/x/callback";

        const isLegacyRedirectUri = (value) => {
            try {
                const url = new URL(value);
                return ["127.0.0.1", "localhost"].includes(url.hostname)
                    && /\/api\/autopublish\/x\/oauth\/callback$/.test(url.pathname);
            } catch (_error) {
                return false;
            }
        };

        const loadXConfig = async () => {
            try {
                const response = await api.fetchApi("/autopublish/x/config", { cache: "no-store" });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                const config = payload.config;
                xInputs.client_id.value = config.client_id || "";
                const needsMigration = isLegacyRedirectUri(config.redirect_uri || "");
                xInputs.redirect_uri.value = needsMigration ? defaultRedirectUri() : (config.redirect_uri || defaultRedirectUri());
                xInputs.proxy_url.value = config.proxy_url || "";
                xInputs.default_text.value = config.default_text || "";
                setXConfigStatus(config);
                if (needsMigration) {
                    xAccount.textContent = "请更新 X 后台 Callback URI";
                    xStatusText = "X 回调待更新";
                    renderConnectionStatus();
                }
                return config;
            } catch (error) {
                if (!xInputs.redirect_uri.value) xInputs.redirect_uri.value = defaultRedirectUri();
                setXConfigStatus(null, `X 配置读取失败：${error.message}`);
                return null;
            }
        };

        const saveXSettings = async () => {
            const requestBody = {};
            for (const [name, input] of Object.entries(xInputs)) requestBody[name] = input.value;
            const response = await api.fetchApi("/autopublish/x/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(requestBody),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            setXConfigStatus(payload.config);
            return payload.config;
        };

        const updateJob = (job) => {
            const tracked = activeJobs.get(job.id);
            if (!tracked) return;
            const { card, button } = tracked;
            card.dataset.state = job.status === "done" ? "done" : (job.status === "failed" ? "idle" : "working");
            const status = card.querySelector(".autopublish-status");
            status.replaceChildren();
            if (job.status === "done" && job.result_url) {
                const link = element("a", "", job.message);
                link.href = job.result_url;
                link.target = "_blank";
                link.rel = "noopener";
                status.appendChild(link);
            } else {
                status.textContent = job.message;
            }
            if (job.status === "done" || job.status === "failed") {
                button.textContent = job.status === "done" ? "OSS 已上传" : "重试";
                button.disabled = job.status === "done";
                if (job.status === "done" && job.result_url) {
                    const actions = card.querySelector(".autopublish-actions");
                    const copyButton = card.querySelector(".autopublish-copy");
                    copyButton.dataset.url = job.result_url;
                    copyButton.hidden = false;
                    actions.classList.add("has-copy");
                }
                activeJobs.delete(job.id);
            }
        };

        const stopPollingIfIdle = () => {
            if (activeJobs.size === 0 && pollTimer !== null) {
                window.clearInterval(pollTimer);
                pollTimer = null;
            }
        };

        const pollJobs = async () => {
            try {
                const response = await api.fetchApi("/autopublish/oss/jobs", { cache: "no-store" });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const payload = await response.json();
                for (const job of payload.jobs || []) updateJob(job);
            } catch (error) {
                for (const { card } of activeJobs.values()) {
                    card.querySelector(".autopublish-status").textContent = `无法读取发布状态：${error.message}`;
                }
            } finally {
                stopPollingIfIdle();
            }
        };

        const startPolling = () => {
            if (pollTimer === null) pollTimer = window.setInterval(pollJobs, 550);
        };

        const publish = async (image, card, button) => {
            if (!configReady) {
                configPanel.hidden = false;
                xConfigPanel.hidden = true;
                localConfigPanel.hidden = true;
                composer.hidden = true;
                card.querySelector(".autopublish-status").textContent = "请先点击右上角齿轮完成 OSS 配置";
                window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
                return;
            }
            button.disabled = true;
            button.textContent = "提交中…";
            card.dataset.state = "working";
            card.querySelector(".autopublish-status").textContent = "正在交给后台发布队列…";
            try {
                const response = await api.fetchApi("/autopublish/oss/publish", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ image }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                activeJobs.set(payload.job.id, { card, button });
                updateJob(payload.job);
                startPolling();
            } catch (error) {
                card.dataset.state = "idle";
                card.querySelector(".autopublish-status").textContent = `提交失败：${error.message}`;
                button.disabled = false;
                button.textContent = "重试 OSS";
            }
        };

        const updateLocalJob = (job) => {
            const tracked = activeLocalJobs.get(job.id);
            if (!tracked) return;
            const { card, button } = tracked;
            card.dataset.state = job.status === "done" ? "done" : (job.status === "failed" ? "idle" : "working");
            const status = card.querySelector(".autopublish-status");
            status.textContent = job.message;
            status.title = job.result_path || "";
            if (job.status === "done" || job.status === "failed") {
                button.textContent = job.status === "done" ? "已输出" : "重试本地";
                button.disabled = job.status === "done";
                activeLocalJobs.delete(job.id);
            }
        };

        const stopLocalPollingIfIdle = () => {
            if (activeLocalJobs.size === 0 && localPollTimer !== null) {
                window.clearInterval(localPollTimer);
                localPollTimer = null;
            }
        };

        const pollLocalJobs = async () => {
            try {
                const response = await api.fetchApi("/autopublish/local/jobs", { cache: "no-store" });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const payload = await response.json();
                for (const job of payload.jobs || []) updateLocalJob(job);
            } catch (error) {
                for (const { card } of activeLocalJobs.values()) {
                    card.querySelector(".autopublish-status").textContent = `无法读取本地复制状态：${error.message}`;
                }
            } finally {
                stopLocalPollingIfIdle();
            }
        };

        const startLocalPolling = () => {
            if (localPollTimer === null) localPollTimer = window.setInterval(pollLocalJobs, 450);
        };

        const publishLocal = async (image, card, button) => {
            if (!localReady) {
                localConfigPanel.hidden = false;
                configPanel.hidden = true;
                xConfigPanel.hidden = true;
                composer.hidden = true;
                card.querySelector(".autopublish-status").textContent = "请先点击右上角 ★ 设置精选结果文件夹";
                window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
                return;
            }
            button.disabled = true;
            button.textContent = "复制中…";
            card.dataset.state = "working";
            card.querySelector(".autopublish-status").textContent = "正在交给本地复制队列…";
            try {
                const response = await api.fetchApi("/autopublish/local/publish", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ image }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                activeLocalJobs.set(payload.job.id, { card, button });
                updateLocalJob(payload.job);
                startLocalPolling();
            } catch (error) {
                card.dataset.state = "idle";
                card.querySelector(".autopublish-status").textContent = `本地输出失败：${error.message}`;
                button.disabled = false;
                button.textContent = "重试本地";
            }
        };

        const updateXJob = (job) => {
            const tracked = activeXJobs.get(job.id);
            if (!tracked) return;
            const { card, button } = tracked;
            card.dataset.state = job.status === "done" ? "done" : (job.status === "failed" ? "idle" : "working");
            const status = card.querySelector(".autopublish-status");
            status.replaceChildren();
            if (job.status === "done" && job.post_url) {
                const link = element("a", "", job.message);
                link.href = job.post_url;
                link.target = "_blank";
                link.rel = "noopener";
                status.appendChild(link);
            } else {
                status.textContent = job.message;
            }
            if (job.status === "done" || job.status === "failed") {
                if (job.status === "done" && job.post_url) {
                    button.textContent = "打开 X";
                    button.dataset.postUrl = job.post_url;
                } else {
                    button.textContent = "重试 X";
                }
                button.disabled = false;
                activeXJobs.delete(job.id);
            }
        };

        const stopXPollingIfIdle = () => {
            if (activeXJobs.size === 0 && xPollTimer !== null) {
                window.clearInterval(xPollTimer);
                xPollTimer = null;
            }
        };

        const pollXJobs = async () => {
            try {
                const response = await api.fetchApi("/autopublish/x/jobs", { cache: "no-store" });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const payload = await response.json();
                for (const job of payload.jobs || []) updateXJob(job);
            } catch (error) {
                for (const { card } of activeXJobs.values()) {
                    card.querySelector(".autopublish-status").textContent = `无法读取 X 发布状态：${error.message}`;
                }
            } finally {
                stopXPollingIfIdle();
            }
        };

        const startXPolling = () => {
            if (xPollTimer === null) xPollTimer = window.setInterval(pollXJobs, 650);
        };

        const closeComposer = () => {
            composer.hidden = true;
            composerTarget = null;
            confirmComposer.disabled = false;
            confirmComposer.textContent = "确认发布";
        };

        const openComposer = (image, card, button) => {
            if (button.dataset.postUrl) {
                window.open(button.dataset.postUrl, "_blank", "noopener");
                return;
            }
            if (!xReady) {
                xConfigPanel.hidden = false;
                configPanel.hidden = true;
                localConfigPanel.hidden = true;
                card.querySelector(".autopublish-status").textContent = "请先点击右上角 𝕏 并连接 X 账号";
                window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
                return;
            }
            composerTarget = { image, card, button };
            composerFile.textContent = image.filename;
            composerFile.title = image.filename;
            composerText.value = xDefaultText;
            composerCount.textContent = `${composerText.value.length} 字符`;
            composer.hidden = false;
            configPanel.hidden = true;
            xConfigPanel.hidden = true;
            localConfigPanel.hidden = true;
            composerText.focus();
            composer.scrollIntoView({ block: "nearest" });
            window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
        };

        const publishX = async () => {
            if (!composerTarget) return;
            const { image, card, button } = composerTarget;
            const text = composerText.value;
            confirmComposer.disabled = true;
            confirmComposer.textContent = "提交中…";
            button.disabled = true;
            button.textContent = "X 提交中…";
            card.dataset.state = "working";
            card.querySelector(".autopublish-status").textContent = "正在交给 X 后台发布队列…";
            try {
                const response = await api.fetchApi("/autopublish/x/publish", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ image, text }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                activeXJobs.set(payload.job.id, { card, button });
                updateXJob(payload.job);
                closeComposer();
                startXPolling();
            } catch (error) {
                card.dataset.state = "idle";
                card.querySelector(".autopublish-status").textContent = `X 提交失败：${error.message}`;
                button.disabled = false;
                button.textContent = "重试 X";
                confirmComposer.disabled = false;
                confirmComposer.textContent = "重新提交";
            }
        };

        const createCard = (image, nodeId) => {
            const selected = sourceSelect.value;
            if (selected && selected !== nodeId) return;
            const key = imageKey(image, nodeId);
            if (cards.has(key)) {
                list.prepend(cards.get(key));
                return;
            }

            const card = element("article", "autopublish-card");
            card.dataset.state = "idle";
            const thumb = element("img", "autopublish-thumb");
            thumb.src = imageUrl(image);
            thumb.alt = image.filename;
            thumb.title = "打开原图";
            thumb.addEventListener("click", () => window.open(imageUrl(image), "_blank", "noopener"));

            const content = element("div", "autopublish-card-content");
            const filename = element("div", "autopublish-filename", image.filename);
            filename.title = image.filename;
            const source = element("div", "autopublish-source", `#${nodeId} · ${nodeLabel(nodeId)}`);
            source.title = source.textContent;
            const status = element("div", "autopublish-status", "未发布 · 可以继续生成");
            const actions = element("div", "autopublish-actions");

            const button = element("button", "autopublish-action", "上传 OSS");
            button.type = "button";
            button.dataset.destination = "oss";
            button.addEventListener("click", () => publish(image, card, button));
            const copyButton = element("button", "autopublish-action autopublish-copy", "复制 URL");
            copyButton.type = "button";
            copyButton.hidden = true;
            copyButton.addEventListener("click", async () => {
                const url = copyButton.dataset.url;
                if (!url) return;
                try {
                    await copyText(url);
                    copyButton.textContent = "已复制";
                    window.setTimeout(() => { copyButton.textContent = "复制 URL"; }, 1200);
                } catch (error) {
                    copyButton.textContent = "复制失败";
                    status.textContent = `复制失败：${error.message}`;
                    window.setTimeout(() => { copyButton.textContent = "复制 URL"; }, 1600);
                }
            });
            const xButton = element("button", "autopublish-action", "发布 X");
            xButton.type = "button";
            xButton.dataset.destination = "x";
            xButton.addEventListener("click", () => openComposer(image, card, xButton));
            const localButton = element("button", "autopublish-action", "输出本地");
            localButton.type = "button";
            localButton.dataset.destination = "local";
            localButton.addEventListener("click", () => publishLocal(image, card, localButton));
            actions.append(button, xButton, localButton, copyButton);

            content.append(filename, source, status, actions);
            card.append(thumb, content);
            card.dataset.nodeId = nodeId;
            list.prepend(card);
            cards.set(key, card);

            while (cards.size > maxCards) {
                const oldestKey = cards.keys().next().value;
                const oldestCard = cards.get(oldestKey);
                oldestCard.remove();
                cards.delete(oldestKey);
            }
            applySourceFilter();
        };

        sourceSelect.addEventListener("pointerdown", refreshSourceOptions);
        sourceSelect.addEventListener("change", () => {
            localStorage.setItem(sourceStorageKey, sourceSelect.value);
            applySourceFilter();
        });

        configToggle.addEventListener("click", (event) => {
            event.stopPropagation();
            configPanel.hidden = !configPanel.hidden;
            if (!configPanel.hidden) {
                xConfigPanel.hidden = true;
                localConfigPanel.hidden = true;
                composer.hidden = true;
                loadConfig();
            }
            window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
        });

        xConfigToggle.addEventListener("click", (event) => {
            event.stopPropagation();
            xConfigPanel.hidden = !xConfigPanel.hidden;
            if (!xConfigPanel.hidden) {
                configPanel.hidden = true;
                localConfigPanel.hidden = true;
                composer.hidden = true;
                loadXConfig();
            }
            window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
        });

        localConfigToggle.addEventListener("click", (event) => {
            event.stopPropagation();
            localConfigPanel.hidden = !localConfigPanel.hidden;
            if (!localConfigPanel.hidden) {
                configPanel.hidden = true;
                xConfigPanel.hidden = true;
                composer.hidden = true;
                loadLocalConfig();
            }
            window.requestAnimationFrame(() => clampTrayPosition(tray.offsetLeft, tray.offsetTop));
        });

        saveConfig.addEventListener("click", async () => {
            saveConfig.disabled = true;
            saveConfig.textContent = "正在保存…";
            const body = {};
            for (const [name, input] of Object.entries(configInputs)) body[name] = input.value;
            try {
                const response = await api.fetchApi("/autopublish/oss/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                setConfigStatus(payload.config);
                configInputs.access_key_secret.value = "";
                saveConfig.textContent = "配置已保存";
                window.setTimeout(() => { saveConfig.textContent = "保存 OSS 配置"; }, 1200);
            } catch (error) {
                setConfigStatus(null, `保存失败：${error.message}`);
                saveConfig.textContent = "重新保存";
            } finally {
                saveConfig.disabled = false;
            }
        });

        saveLocalConfig.addEventListener("click", async () => {
            saveLocalConfig.disabled = true;
            saveLocalConfig.textContent = "正在保存…";
            try {
                const response = await api.fetchApi("/autopublish/local/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ output_directory: localDirectoryInput.value }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                localDirectoryInput.value = payload.config.output_directory || "";
                setLocalConfigStatus(payload.config);
                saveLocalConfig.textContent = "目录已保存";
                window.setTimeout(() => { saveLocalConfig.textContent = "保存本地目录"; }, 1200);
            } catch (error) {
                setLocalConfigStatus(null, `本地保存失败：${error.message}`);
                saveLocalConfig.textContent = "重新保存";
            } finally {
                saveLocalConfig.disabled = false;
            }
        });

        saveXConfig.addEventListener("click", async () => {
            saveXConfig.disabled = true;
            saveXConfig.textContent = "正在保存…";
            try {
                await saveXSettings();
                saveXConfig.textContent = "配置已保存";
                window.setTimeout(() => { saveXConfig.textContent = "保存配置"; }, 1200);
            } catch (error) {
                setXConfigStatus(null, `X 保存失败：${error.message}`);
                saveXConfig.textContent = "重新保存";
            } finally {
                saveXConfig.disabled = false;
            }
        });

        connectX.addEventListener("click", async () => {
            const popup = window.open("about:blank", "autopublish-x-oauth", "width=620,height=760,noopener=no");
            connectX.disabled = true;
            connectX.textContent = "准备授权…";
            try {
                await saveXSettings();
                const response = await api.fetchApi("/autopublish/x/oauth/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: "{}",
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                if (!popup) throw new Error("浏览器阻止了授权窗口，请允许此站点打开弹窗");
                popup.location.href = payload.authorization_url;
                connectX.textContent = "等待授权…";
                if (xAuthPollTimer !== null) window.clearInterval(xAuthPollTimer);
                let attempts = 0;
                xAuthPollTimer = window.setInterval(async () => {
                    attempts += 1;
                    const config = await loadXConfig();
                    if (config?.connected || attempts >= 120 || popup.closed) {
                        window.clearInterval(xAuthPollTimer);
                        xAuthPollTimer = null;
                        connectX.disabled = false;
                        connectX.textContent = config?.connected ? "重新授权" : "连接 X";
                    }
                }, 1000);
            } catch (error) {
                if (popup && !popup.closed) popup.close();
                setXConfigStatus(null, `X 授权启动失败：${error.message}`);
                connectX.disabled = false;
                connectX.textContent = "重新连接";
            }
        });

        disconnectX.addEventListener("click", async () => {
            if (!window.confirm("只移除本机保存的 X 授权，确定断开吗？")) return;
            disconnectX.disabled = true;
            try {
                const response = await api.fetchApi("/autopublish/x/disconnect", { method: "POST" });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
                setXConfigStatus(payload.config);
            } catch (error) {
                setXConfigStatus(null, `X 断开失败：${error.message}`);
            } finally {
                disconnectX.disabled = false;
            }
        });

        composerText.addEventListener("input", () => {
            composerCount.textContent = `${composerText.value.length} 字符`;
        });
        cancelComposer.addEventListener("click", closeComposer);
        confirmComposer.addEventListener("click", publishX);

        collapse.addEventListener("click", (event) => {
            event.stopPropagation();
            setCollapsed(!tray.classList.contains("is-collapsed"));
        });
        header.addEventListener("click", () => {
            if (!ignoreHeaderClick && tray.classList.contains("is-collapsed")) setCollapsed(false);
        });
        clear.addEventListener("click", () => {
            list.replaceChildren();
            cards.clear();
            applySourceFilter();
        });

        let drag = null;
        header.addEventListener("pointerdown", (event) => {
            if (event.button !== 0 || event.target.closest("button, input, select")) return;
            event.preventDefault();
            drag = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                left: tray.offsetLeft,
                top: tray.offsetTop,
                moved: false,
            };
            tray.classList.add("is-dragging");
            header.setPointerCapture(event.pointerId);
        });
        header.addEventListener("pointermove", (event) => {
            if (!drag || event.pointerId !== drag.pointerId) return;
            const deltaX = event.clientX - drag.startX;
            const deltaY = event.clientY - drag.startY;
            if (Math.abs(deltaX) + Math.abs(deltaY) > 3) drag.moved = true;
            clampTrayPosition(drag.left + deltaX, drag.top + deltaY);
        });
        const finishDrag = (event) => {
            if (!drag || event.pointerId !== drag.pointerId) return;
            ignoreHeaderClick = drag.moved;
            tray.classList.remove("is-dragging");
            clampTrayPosition(tray.offsetLeft, tray.offsetTop, true);
            drag = null;
            window.setTimeout(() => { ignoreHeaderClick = false; }, 0);
        };
        header.addEventListener("pointerup", finishDrag);
        header.addEventListener("pointercancel", finishDrag);
        window.addEventListener("resize", () => clampTrayPosition(tray.offsetLeft, tray.offsetTop, true));

        restoreTrayPosition();
        setCollapsed(localStorage.getItem(storageKey) === "1");
        window.setTimeout(refreshSourceOptions, 0);
        loadConfig();
        loadXConfig();
        loadLocalConfig();

        api.addEventListener("executed", ({ detail }) => {
            const images = detail?.output?.images;
            if (!Array.isArray(images)) return;
            const nodeId = String(detail.node || "").split(":")[0];
            if (!nodeId) return;
            observedSources.set(nodeId, nodeLabel(nodeId));
            refreshSourceOptions();
            for (const image of images) {
                if (image?.filename) createCard(image, nodeId);
            }
        });
    },
    afterConfigureGraph() {
        window.setTimeout(refreshSourceOptions, 0);
    },
    nodeCreated() {
        window.setTimeout(refreshSourceOptions, 0);
    },
});
