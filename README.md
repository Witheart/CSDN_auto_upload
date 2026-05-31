# CSDN Markdown 全自动图文发布助手 🚀

- **作者**：吴思含（Witheart）
- **更新时间**：2026-05-31

---

基于 Python 和 Playwright 构建的自动化脚本，解决 CSDN 无法直接读取和上传 Markdown 本地图片的问题。

只需配置一次，即可实现**操作系统级的一键发布**：右键点击本地文档 $\rightarrow$ 图片自动转存图床 $\rightarrow$ 提取文章标题 $\rightarrow$ 填入正文排版 $\rightarrow$ 保存至草稿箱 $\rightarrow$ 本地日志记账。

## ✨ 核心特性

- **🖱️ 操作系统级集成**：完美绑定 Windows 右键菜单。无需打开终端，在任意目录下右键点击 `.md` 文件即可触发全自动上传流程。
- **🛡️ 绕过反爬机制**：通过注入底层虚拟剪贴板事件 (Paste Event) 模拟真实用户的粘贴行为，稳定绕过 CSDN 动态渲染 UI 与接口加密。
- **🔐 智能持久化登录**：首次运行提供 60 秒扫码/账号登录时间，自动于脚本目录生成 `csdn_browser_data` 保存 Cookie，后续免登录秒进编辑器。
- **📝 无损排版还原**：通过纯文本模拟粘贴 (`text/plain`)，100% 保留本地 Markdown 的段落、换行及代码块排版。
- **💡 全域路径解析**：引入动态“寻根”算法自动定位笔记根目录。支持解析本地相对与绝对路径图片，精准转换为 Base64 数据流上传。
- **📊 自动化记账协同**：上传成功后，自动计算相对路径并追加到笔记根目录的 `.upload_status` 文件中，完美兼容 Bash 追踪脚本。

---

## 🛠️ 环境依赖

确保已安装 Python 3.7 及以上版本。

**1. 安装 Playwright 库**

```bash
pip install playwright

```

**2. 下载 Chromium 浏览器内核**

```bash
playwright install chromium

```

---

## 🚀 部署指南 (右键菜单极速配置)

只需三步，将脚本变成你的 Windows 系统原生功能。

### 1. 准备核心脚本

确保 `csdn_auto_upload.py` 已放置在你的工具目录中（例如 `F:\0000_TOOL\CSDN_auto_upload\`），并且代码底部已配置为接收命令行参数 `sys.argv[1]`。

### 2. 创建批处理桥梁 (.bat)

在脚本同级目录下新建一个文件 `upload_csdn.bat`，填入以下代码。**注意替换为你自己的实际路径**：

```bat
@echo off
:: 设置控制台为 UTF-8 编码，防止中文乱码
chcp 65001 >nul

echo =========================================
echo       CSDN 自动图文发布工具启动中...
echo =========================================

:: 请将下面的路径替换为你自己的 Python 解释器和 py 脚本的绝对路径
"F:\0000_TOOL\CSDN_auto_upload\.venv\Scripts\python.exe" "F:\0000_TOOL\CSDN_auto_upload\csdn_auto_upload.py" "%~1"

echo.
echo =========================================
echo       执行完毕，请检查上面的日志输出
echo =========================================
pause

```

### 3. 写入注册表 (.reg)

在桌面新建一个文本文件，命名为 `Add_CSDN_Menu.reg`，填入以下内容。**注意：注册表中的路径必须使用双反斜杠 `\\**`：

```registry
Windows Registry Editor Version 5.00

; 为 .md 文件添加右键菜单
[HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.md\shell\UploadToCSDN]
@="🚀 上传到 CSDN 草稿箱"
"Icon"="\"F:\\0000_TOOL\\CSDN_auto_upload\\.venv\\Scripts\\python.exe\""

; 配置点击后执行的 bat 脚本
[HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.md\shell\UploadToCSDN\command]
@="\"F:\\0000_TOOL\\CSDN_auto_upload\\upload_csdn.bat\" \"%1\""

```

保存后，**双击运行该 `.reg` 文件**并确认添加到注册表。

---

## 🖱️ 如何使用

配置完成后，使用体验将极其简单：

1. 打开资源管理器，找到你写好的任意 `.md` 笔记。
2. **鼠标右键**点击该文件。
3. 在弹出的菜单中选择 **“🚀 上传到 CSDN 草稿箱”**。
4. 喝口水，看着弹出的终端和浏览器全自动完成所有工作，并在 `.upload_status` 中自动记账。

---

## ⚠️ 注意事项

- **首次运行与授权**：第一次使用右键菜单时，弹出的控制台会提示等待，请在 **60秒** 内在自动弹出的浏览器中完成 CSDN 扫码登录。
- **防盗链限制**：脚本提取的 CSDN 图床链接受 HTTP Referer 保护，**仅限 CSDN 站内有效**。直接发布至外站会导致图片无法显示。
- **图片路径规范**：请确保 Markdown 中的图片使用有效的本地相对路径或完整绝对路径。不支持二次转存以 `http` 开头的网络图片。
- **保持窗口可视**：脚本运行期间（尤其是粘贴和保存阶段），切勿最小化 Chromium 浏览器窗口，以免中断 UI 事件触发和焦点捕获。
