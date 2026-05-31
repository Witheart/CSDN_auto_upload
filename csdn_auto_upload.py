import re
import os
import base64
import mimetypes
import datetime
from playwright.sync_api import sync_playwright

# ==========================================
# ====== 新增：动态定位根目录机制 ======
# ==========================================
def get_notes_root(md_file_path):
    """
    以目标 md 文件为起点，逐级向上寻找 .upload_status 所在的目录，
    将其认定为“笔记根目录”。（顺带兼容寻找 .git 作为兜底）
    """
    current_dir = os.path.abspath(os.path.dirname(md_file_path))
    while True:
        # 如果当前层级存在 .upload_status 或 .git，说明到达了笔记仓库的根目录
        if os.path.exists(os.path.join(current_dir, ".upload_status")) or \
           os.path.exists(os.path.join(current_dir, ".git")):
            return current_dir
            
        parent = os.path.dirname(current_dir)
        if parent == current_dir: # 已经退到了系统的根目录 (如 C:\)
            raise Exception("❌ 无法在父目录中找到 .upload_status 或 .git！请确保它放置在笔记根目录下。")
        current_dir = parent


def mark_as_uploaded(md_file_path):
    # 1. 动态获取绝对的笔记根目录
    notes_root = get_notes_root(md_file_path)
    upload_log_path = os.path.join(notes_root, ".upload_status")
    
    # 2. 以根目录为基准，计算纯正的相对路径
    rel_path = os.path.relpath(md_file_path, notes_root)
    rel_path = rel_path.replace('\\', '/') # 转换为 Linux 风格，兼容 bash 脚本
    
    # 3. 确保文件存在
    if not os.path.exists(upload_log_path):
        with open(upload_log_path, 'w', encoding='utf-8') as f:
            pass 
            
    # 4. 检查是否已经标记过
    with open(upload_log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        if line.startswith(f"{rel_path}:"):
            date_marked = line.strip().split(':')[-1]
            print(f"📌 记录提示: 文件之前已在 {date_marked} 标记过上传，跳过重复写入。")
            return
            
    # 5. 追加新记录
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(upload_log_path, 'a', encoding='utf-8') as f:
        f.write(f"{rel_path}:{today}\n")
    print(f"📝 记账成功: 已将 {rel_path} 写入根目录的 .upload_status (日期: {today})")


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

            # 3. 保存草稿
            print("⏳ 正在保存草稿...")
            save_btn = page.locator('.btn-save, button:has-text("保存草稿")').first
            save_btn.click()

            page.wait_for_timeout(3000)
            print("✅ 草稿保存成功！")
            
            # ==========================================
            # ====== 触发标记动作，智能写入日志 ========
            # ==========================================
            mark_as_uploaded(md_file_path)

        except Exception as e:
            print(f"❌ 填入正文或保存草稿时发生错误: {e}")

        page.wait_for_timeout(3000)
        browser.close()

    out_file = md_file_path.replace('.md', '_csdn.md')
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\n🎉 全部自动化流程执行完毕！请前往浏览器查看草稿箱或直接发布。")


# ================= 运行测试 =================
if __name__ == "__main__":
    # 现在你可以在任何路径下执行这个脚本了！
    # 比如: python F:\tools\csdn_auto_upload.py F:\0000_CODE\CSDN_auto_upload\笔记分类\文章.md
    target_md_file = r"F:\notes\06. 其他工具使用技巧\CH7511B配置工具使用补充\CH7511B配置工具使用补充.md"
    process_markdown_for_csdn(target_md_file)