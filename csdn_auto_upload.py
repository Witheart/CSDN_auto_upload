import re
import os
import base64
import mimetypes
from playwright.sync_api import sync_playwright


def process_markdown_for_csdn(md_file_path):
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # ====== 新增功能 1：提取文章标题 ======
    article_title = "无标题文章"
    for line in content.split('\n'):
        # 寻找第一个一级标题作为文章标题
        if line.strip().startswith('# '):
            article_title = line.replace('#', '').strip()
            break
    print(f"📑 提取到文章标题: {article_title}")

    images = set(re.findall(r'!\[.*?\]\((?!http)(.*?)\)', content))

    # 获取 .md 文件所在的目录
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
        page.wait_for_timeout(15000)

        # ====== 处理图片上传 (核心保持不变) ======
        if images:
            print(f"找到 {len(images)} 张本地图片，开始处理...")
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
                    with open(abs_img_path, "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

                    mime_type, _ = mimetypes.guess_type(abs_img_path)
                    if not mime_type:
                        mime_type = "image/png"
                    file_name = os.path.basename(abs_img_path)

                    # 点击编辑器区域，确保焦点
                    page.locator('.editor, .markdown-editor, .cke_textarea, body').first.click()
                    page.wait_for_timeout(500)

                    # 注入粘贴事件
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

                    # 捕获生成的 URL
                    csdn_url = None
                    for _ in range(40):
                        page.wait_for_timeout(500)
                        page_text = page.evaluate("document.body.innerText")
                        urls = re.findall(r'(https://[^\s"\'\\]+csdnimg\.cn[^\s"\'\\]+)', page_text)
                        if urls:
                            csdn_url = urls[-1]
                            break

                    if csdn_url:
                        print(f"✅ 成功捕获外链: {csdn_url}")
                        content = content.replace(img_path, csdn_url)
                        # 清理编辑器，为下一张图做准备
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                    else:
                        print("❌ 超过 20 秒未检测到链接生成。")

                except Exception as e:
                    print(f"❌ 图片处理失败: {e}")

        # =======================================================
        # ====== 新增功能 2：自动填写标题和最终正文内容 ======
        # =======================================================
        print("\n🚀 图片处理完毕，开始排版文章...")

        try:
            # 1. 填写标题
            # 宽泛地选中带有 title 相关 class 或 placeholder 的元素
            title_locator = page.locator(
                'div.article-bar__title-display, input[placeholder*="标题"], .article-bar__title').first
            title_locator.click()  # 这会触发 CSDN 将 div 变成 input 或者直接获取焦点
            page.wait_for_timeout(500)

            # 全选清空默认的“【无标题】”，然后打字输入我们提取到的标题
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(article_title)
            print("✅ 标题已自动填入")

            # 2. 填写正文
            # 重新点击下方的编辑器主区域
            editor_area = page.locator('.editor, .markdown-editor, body').first
            editor_area.click()
            page.wait_for_timeout(500)

            # 确保编辑器是空的，然后将带有外链 URL 的最终内容插入
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")

            # insert_text 是底层直接塞入字符，比模拟打字快得多且不会乱码
            page.keyboard.insert_text(content)
            print("✅ 文章内容已自动填入，排版完成！")

        except Exception as e:
            print(f"❌ 填入标题或正文时发生错误: {e}")

        # 给浏览器一点缓冲时间让你看清效果
        page.wait_for_timeout(3000)
        browser.close()

    # 依然在本地保留一份 _csdn.md 作为备份，防范网页意外崩溃
    out_file = md_file_path.replace('.md', '_csdn.md')
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\n🎉 全部自动化流程执行完毕！请前往浏览器查看草稿箱或直接发布。")


# ================= 运行测试 =================
if __name__ == "__main__":
    target_md_file = r"F:\0000_CODE\CSDN_auto_upload\3588 Ubuntu TeamViewer 安装及使用\3588 Ubuntu Teamviewer 安装及使用.md"
    process_markdown_for_csdn(target_md_file)