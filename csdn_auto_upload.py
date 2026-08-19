import re
import os
import time
import base64
import mimetypes
import datetime
import sys
from playwright.sync_api import sync_playwright

# ==========================================================
# ====== 配置区（参照 githubio_sync.js 的风格集中管理） ======
# ==========================================================
# 每张图片上传完成后的缓冲间隔（秒）。CSDN 对连续上传有频控，
# 间隔太短会触发"操作过于频繁"，适当调大更稳。
IMAGE_PASTE_INTERVAL = 1.5

# 正文粘贴完成后、点击保存前的缓冲时间（秒），让编辑器完成渲染
SETTLE_BEFORE_SAVE = 2.0

# 保存草稿的最大尝试次数
SAVE_MAX_ATTEMPTS = 8

# 触发"操作过于频繁"后的基础等待（秒），每次重试按 2 的幂递增，封顶 60 秒
SAVE_RATE_LIMIT_BASE_WAIT = 5

# 点击保存后轮询结果的超时（秒）
SAVE_POLL_TIMEOUT = 12

# 保存成功的提示文字（toast / 按钮状态 / 页面文字）
SAVE_SUCCESS_MARKERS = [
    "已成功保存至草稿箱",  # CSDN 实际 toast 文案
    "保存成功", "草稿保存成功", "已保存", "保存成功！",
]

# 触发频控或保存失败的提示文字
SAVE_RATE_LIMIT_MARKERS = [
    "操作过于频繁", "过于频繁", "太频繁", "请稍后再试", "请稍后重试",
    "保存失败", "网络异常", "请求失败",
]

# 保存按钮的候选选择器（按优先级排列）
SAVE_BTN_SELECTORS = [
    'button:has-text("保存草稿")',
    '.btn-save',
    'button:has-text("保存")',
    'a:has-text("保存草稿")',
    '.article-bar__save',
    '[class*="save"]',
]


# ==========================================
# ====== 新增：动态定位根目录机制 ======
# ==========================================
def get_notes_root(md_file_path):
    """
    以目标 md 文件为起点，逐级向上寻找 .upload_status 所在的目录，
    将其认定为"笔记根目录"。（顺带兼容寻找 .git 作为兜底）
    """
    current_dir = os.path.abspath(os.path.dirname(md_file_path))
    while True:
        # 如果当前层级存在 .upload_status 或 .git，说明到达了笔记仓库的根目录
        if os.path.exists(os.path.join(current_dir, ".upload_status")) or \
           os.path.exists(os.path.join(current_dir, ".git")):
            return current_dir

        parent = os.path.dirname(current_dir)
        if parent == current_dir:  # 已经退到了系统的根目录 (如 C:\)
            raise Exception("❌ 无法在父目录中找到 .upload_status 或 .git！请确保它放置在笔记根目录下。")
        current_dir = parent


def mark_as_uploaded(md_file_path):
    # 1. 动态获取绝对的笔记根目录
    notes_root = get_notes_root(md_file_path)
    upload_log_path = os.path.join(notes_root, ".upload_status")

    # 2. 以根目录为基准，计算纯正的相对路径
    rel_path = os.path.relpath(md_file_path, notes_root)
    rel_path = rel_path.replace('\\', '/')  # 转换为 Linux 风格，兼容 bash 脚本

    # 3. 确保文件存在（强制使用 Linux 换行符 \n）
    if not os.path.exists(upload_log_path):
        with open(upload_log_path, 'w', encoding='utf-8', newline='\n') as f:
            pass

    # 4. 检查是否已经标记过
    with open(upload_log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        if line.startswith(f"{rel_path}:"):
            date_marked = line.strip().split(':')[-1]
            print(f"📌 记录提示: 文件之前已在 {date_marked} 标记过上传，跳过重复写入。")
            return

    # 5. 追加新记录（强制使用 Linux 换行符 \n）
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(upload_log_path, 'a', encoding='utf-8', newline='\n') as f:
        f.write(f"{rel_path}:{today}\n")
    print(f"📝 记账成功: 已将 {rel_path} 写入根目录的 .upload_status (日期: {today})")


# ==========================================================
# ====== 新增：保存草稿的智能重试（解决"操作过于频繁"） ======
# ==========================================================
def wait_for_save_result(page, before_text, timeout_ms=SAVE_POLL_TIMEOUT * 1000):
    """
    点击保存后轮询页面，判断保存结果。
    返回 (result, page_text)：
      result = "success" | "rate_limited" | "unknown"
    只识别"点击后新出现"的提示文字，避免把页面本来就有的"已保存"误判。
    """
    deadline = time.time() + timeout_ms / 1000.0
    last_text = before_text
    while time.time() < deadline:
        try:
            page_text = page.evaluate("document.body.innerText")
        except Exception:
            page_text = last_text

        # 只关注"点击后新出现"的提示
        new_text = page_text
        # 成功标记
        for m in SAVE_SUCCESS_MARKERS:
            if m in new_text and m not in before_text:
                return "success", page_text
        # 频控/失败标记
        for m in SAVE_RATE_LIMIT_MARKERS:
            if m in new_text and m not in before_text:
                return "rate_limited", page_text

        last_text = page_text
        page.wait_for_timeout(500)
    return "unknown", last_text


def save_draft_with_retry(page, max_attempts=SAVE_MAX_ATTEMPTS):
    """
    点击"保存草稿"并验证结果。
    CSDN 偶尔会提示"操作过于频繁"导致保存失败，此函数会自动等待并重试，
    直到确认保存成功或达到最大次数。
    返回 True 表示已确认保存成功；False 表示未能确认。
    """
    print(f"⏳ 开始保存草稿（最多尝试 {max_attempts} 次，自动处理'操作过于频繁'）...")

    for attempt in range(1, max_attempts + 1):
        print(f"  ── 第 {attempt}/{max_attempts} 次尝试 ──")

        # 1) 找到保存按钮
        save_btn = None
        for sel in SAVE_BTN_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    save_btn = loc
                    break
            except Exception:
                continue
        if save_btn is None:
            print("  ❌ 未找到保存按钮，等待 3 秒后重试...")
            page.wait_for_timeout(3000)
            continue

        # 2) 记录点击前的页面文字，用于判断"新出现"的提示
        try:
            before_text = page.evaluate("document.body.innerText")
        except Exception:
            before_text = ""

        # 3) 点击保存
        try:
            save_btn.click()
            print("  👆 已点击保存草稿")
        except Exception as e:
            print(f"  ⚠️ 点击保存按钮异常: {e}")

        # 4) 轮询页面，判断结果
        result, page_text = wait_for_save_result(page, before_text)

        if result == "success":
            print("  ✅ 草稿保存成功！")
            return True
        elif result == "rate_limited":
            wait_s = min(SAVE_RATE_LIMIT_BASE_WAIT * (2 ** (attempt - 1)), 60)
            print(f"  ⚠️ 触发'操作过于频繁'，等待 {wait_s} 秒后自动重试...")
            page.wait_for_timeout(int(wait_s * 1000))
        else:
            # 未知结果：可能静默成功，也可能静默失败。
            # 再保存一次已保存的草稿是无害的，稍等后重试。
            print("  ⚠️ 未检测到明确的保存结果，稍等后自动重试...")
            page.wait_for_timeout(4000)

    print("  ❌ 多次尝试后仍未确认草稿保存成功，请手动检查浏览器中的草稿箱。")
    return False


def process_markdown_for_csdn(md_file_path):
    # 确保传入的是绝对路径，防止路径解析歧义
    md_file_path = os.path.abspath(md_file_path)

    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # ====== 提取文章标题 ======
    article_title = "无标题文章"
    for line in content.split('\n'):
        if line.strip().startswith('# '):
            article_title = line.replace('#', '').strip()
            break
    print(f"📑 提取到文章标题: {article_title}")

    images = set(re.findall(r'!\[.*?\]\((?!http)(.*?)\)', content))
    md_dir = os.path.dirname(md_file_path)

    with sync_playwright() as p:
        # 🚩 核心修改：让浏览器数据文件夹永远跟 Python 脚本保存在一起
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = os.path.join(script_dir, 'csdn_browser_data')

        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={'width': 1400, 'height': 900}
        )

        page = browser.new_page()
        page.goto("https://editor.csdn.net/md/")

        # ====== 智能判断登录状态 ======
        print("🔍 正在检查登录状态...")
        try:
            page.wait_for_selector('.editor, .markdown-editor, div.article-bar__title-display', timeout=3000)
            print("✅ 已处于登录状态，直接开始处理...")
            page.wait_for_timeout(1000)
        except:
            print("⚠️ 未检测到编辑器界面，可能需要登录。")
            print("👉 请在弹出的浏览器窗口中扫码或登录 (程序将静默等待，最长 60 秒)...")
            try:
                page.wait_for_selector('.editor, .markdown-editor, div.article-bar__title-display', timeout=60000)
                print("✅ 登录成功，开始执行后续流程！")
                page.wait_for_timeout(2000)
            except Exception:
                print("❌ 超过 60 秒未检测到登录成功状态，脚本终止。")
                browser.close()
                return

        # ====== 处理图片上传 ======
        if images:
            print(f"找到 {len(images)} 张本地图片，开始处理...")
            for idx, img_path in enumerate(images):
                if os.path.isabs(img_path):
                    abs_img_path = img_path
                else:
                    abs_img_path = os.path.normpath(os.path.join(md_dir, img_path))

                if not os.path.exists(abs_img_path):
                    print(f"⚠️ 找不到图片文件: {abs_img_path}，跳过。")
                    continue

                # 每张图片之间留出缓冲，降低触发频控的概率
                if idx > 0:
                    print(f"  💤 图片间隔 {IMAGE_PASTE_INTERVAL}s（防频控）...")
                    page.wait_for_timeout(int(IMAGE_PASTE_INTERVAL * 1000))

                print(f"\n🚀 准备粘贴图片: {abs_img_path}")

                try:
                    with open(abs_img_path, "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

                    mime_type, _ = mimetypes.guess_type(abs_img_path)
                    if not mime_type:
                        mime_type = "image/png"
                    file_name = os.path.basename(abs_img_path)

                    page.locator('.editor, .markdown-editor, .cke_textarea, body').first.click()
                    page.wait_for_timeout(500)

                    page.evaluate("""
                        ([b64Data, mimeType, fileName]) => {
                            const byteCharacters = atob(b64Data);
                            const byteNumbers = new Array(byteCharacters.length);
                            for (let i = 0; i < byteCharacters.length; i++) {
                                byteNumbers[i] = byteCharacters.charCodeAt(i);
                            }
                            const byteArray = new Uint8Array(byteNumbers);
                            const blob = new Blob([byteArray], {type: mimeType});
                            const file = new File([blob], fileName, {type: mimeType});
                            const dataTransfer = new DataTransfer();
                            dataTransfer.items.add(file);
                            const event = new ClipboardEvent('paste', {
                                clipboardData: dataTransfer,
                                bubbles: true,
                                cancelable: true
                            });
                            document.activeElement.dispatchEvent(event);
                        }
                    """, [encoded_string, mime_type, file_name])

                    csdn_url = None
                    for _ in range(40):
                        page.wait_for_timeout(500)
                        page_text = page.evaluate("document.body.innerText")
                        urls = re.findall(r'(https://[^\s"\'\\()]+csdnimg\.cn[^\s"\'\\()]+)', page_text)
                        if urls:
                            csdn_url = urls[-1]
                            break

                    if csdn_url:
                        print(f"✅ 成功捕获外链: {csdn_url}")
                        content = content.replace(img_path, csdn_url)
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                    else:
                        print("❌ 超过 20 秒未检测到链接生成。")

                except Exception as e:
                    print(f"❌ 图片处理失败: {e}")

        # ====== 自动填写标题和最终正文内容 ======
        print("\n🚀 图片处理完毕，开始排版文章...")

        try:
            # 1. 填写标题
            title_locator = page.locator(
                'div.article-bar__title-display, input[placeholder*="标题"], .article-bar__title').first
            title_locator.click()
            page.wait_for_timeout(500)

            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(article_title)
            print("✅ 标题已自动填入")

            # 2. 填写正文
            editor_area = page.locator('.editor, .markdown-editor, body').first
            editor_area.click()
            page.wait_for_timeout(500)

            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")

            page.evaluate("""
                ([text]) => {
                    const dataTransfer = new DataTransfer();
                    dataTransfer.setData('text/plain', text);
                    const event = new ClipboardEvent('paste', {
                        clipboardData: dataTransfer,
                        bubbles: true,
                        cancelable: true
                    });
                    document.activeElement.dispatchEvent(event);
                }
            """, [content])

            print("✅ 文章内容已通过模拟粘贴填入，完美保留排版！")

            # 3. 等待编辑器完成渲染后再保存（降低失败概率）
            print(f"⏳ 等待编辑器渲染 {SETTLE_BEFORE_SAVE}s 后保存草稿...")
            page.wait_for_timeout(int(SETTLE_BEFORE_SAVE * 1000))

            # 4. 保存草稿（自动重试，处理"操作过于频繁"）
            saved = save_draft_with_retry(page)

            if saved:
                mark_as_uploaded(md_file_path)
            else:
                print("⚠️ 草稿保存未能确认成功，本次**不记账**，请手动检查浏览器后自行补充记录。")

        except Exception as e:
            print(f"❌ 填入正文或保存草稿时发生错误: {e}")

        page.wait_for_timeout(3000)
        browser.close()

    # 🚩 删除了在本地保存 _csdn.md 文件的代码
    print(f"\n🎉 全部自动化流程执行完毕！请前往浏览器查看草稿箱或直接发布。")


# ================= 运行测试 =================
if __name__ == "__main__":
    # 判断是否接收到了右键传进来的文件路径
    if len(sys.argv) > 1:
        target_md_file = sys.argv[1]
        print(f"🚀 接收到目标文件: {target_md_file}")
        process_markdown_for_csdn(target_md_file)
    else:
        print("❌ 错误：请提供一个 Markdown 文件路径！")
        print("💡 提示：你可以直接把 .md 文件拖拽到这个脚本上，或者通过右键菜单使用。")
        input("按任意键退出...")
