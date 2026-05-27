import re
import os
import base64
import mimetypes
from playwright.sync_api import sync_playwright


def process_markdown_for_csdn(md_file_path):
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    images = set(re.findall(r'!\[.*?\]\((?!http)(.*?)\)', content))
    if not images:
        print("文档中没有发现需要上传的本地图片。")
        return

    print(f"找到 {len(images)} 张本地图片，开始启动“模拟粘贴”极简上传...")
    md_dir = os.path.dirname(os.path.abspath(md_file_path))

    with sync_playwright() as p:
        user_data_dir = os.path.join(os.getcwd(), 'csdn_browser_data')
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={'width': 1400, 'height': 900}
        )

        page = browser.new_page()
        page.goto("https://editor.csdn.net/md/")
        print("等待 15 秒 (首次运行请确保已扫码登录并看到编辑器界面)...")
        page.wait_for_timeout(3000)

        for img_path in images:
            if os.path.isabs(img_path):
                abs_img_path = img_path
            else:
                abs_img_path = os.path.normpath(os.path.join(md_dir, img_path))

            if not os.path.exists(abs_img_path):
                print(f"⚠️ 找不到图片文件: {abs_img_path}，跳过。")
                continue

            print(f"\n🚀 准备粘贴图片: {abs_img_path}")

            try:
                # ====== 核心步骤 1：读取本地图片并转为 Base64 编码 ======
                with open(abs_img_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

                # 自动识别图片类型（如 image/png, image/jpeg）
                mime_type, _ = mimetypes.guess_type(abs_img_path)
                if not mime_type:
                    mime_type = "image/png"
                file_name = os.path.basename(abs_img_path)

                # ====== 核心步骤 2：确保光标激活在编辑器内 ======
                # 点击页面中心或编辑器区域，确保当前网页的焦点在输入框里
                page.locator('.editor, .markdown-editor, .cke_textarea, body').first.click()
                page.wait_for_timeout(500)

                # ====== 核心步骤 3：利用 JS 注入一个真实的粘贴事件 ======
                print("⏳ 正在向浏览器发射粘贴事件...")
                page.evaluate("""
                    ([b64Data, mimeType, fileName]) => {
                        // 1. 将 Base64 还原为二进制数据
                        const byteCharacters = atob(b64Data);
                        const byteNumbers = new Array(byteCharacters.length);
                        for (let i = 0; i < byteCharacters.length; i++) {
                            byteNumbers[i] = byteCharacters.charCodeAt(i);
                        }
                        const byteArray = new Uint8Array(byteNumbers);

                        // 2. 构造浏览器可识别的 File 对象
                        const blob = new Blob([byteArray], {type: mimeType});
                        const file = new File([blob], fileName, {type: mimeType});

                        // 3. 构造虚拟剪贴板
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(file);

                        // 4. 创建标准的 paste 事件
                        const event = new ClipboardEvent('paste', {
                            clipboardData: dataTransfer,
                            bubbles: true,
                            cancelable: true
                        });

                        // 5. 在当前光标所在的元素上触发粘贴
                        document.activeElement.dispatchEvent(event);
                    }
                """, [encoded_string, mime_type, file_name])

                print("⏳ 粘贴成功，等待 CSDN 自动上传并生成链接...")

                # ====== 核心步骤 4：暴力扫描全网页，捕获生成的 URL ======
                csdn_url = None
                for _ in range(40):  # 最多等待 20 秒
                    page.wait_for_timeout(500)

                    # 直接获取整个网页的纯文本，寻找 csdnimg.cn 链接
                    # 这样连特定的 class 都不需要找了，绝对不会因为 CSDN 改版而失效
                    page_text = page.evaluate("document.body.innerText")
                    urls = re.findall(r'(https://[^\s"\'\\]+csdnimg\.cn[^\s"\'\\]+)', page_text)

                    if urls:
                        csdn_url = urls[-1]
                        break

                if csdn_url:
                    print(f"✅ 成功捕获外链: {csdn_url}")
                    # 替换本地内容
                    content = content.replace(img_path, csdn_url)

                    # 清理现场：全选并删除，防止影响下一张图片的 URL 提取
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                else:
                    print("❌ 超过 20 秒未检测到链接生成。")

            except Exception as e:
                print(f"❌ 自动化处理失败: {e}")

        browser.close()

    out_file = md_file_path.replace('.md', '_csdn.md')
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\n🎉 全自动图文转换完成。新文件已生成: {out_file}")


# ================= 运行测试 =================
if __name__ == "__main__":
    target_md_file = r"F:\0000_CODE\CSDN_auto_upload\3588 Ubuntu TeamViewer 安装及使用\3588 Ubuntu Teamviewer 安装及使用.md"
    process_markdown_for_csdn(target_md_file)