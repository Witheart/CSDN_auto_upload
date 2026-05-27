import re
import os
import json
from playwright.sync_api import sync_playwright


def process_markdown_for_csdn(md_file_path):
    # 1. 读取 Markdown 文件内容
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 2. 正则匹配所有本地图片路径 (排除以 http/https 开头的网络图片)
    # 匹配格式: ![xxx](本地路径)
    images = set(re.findall(r'!\[.*?\]\((?!http)(.*?)\)', content))

    if not images:
        print("文档中没有发现需要上传的本地图片，或者图片已经是网络链接。")
        return

    print(f"找到 {len(images)} 张本地图片，开始启动自动化上传...")

    with sync_playwright() as p:
        # 3. 启动浏览器（保持登录状态）
        # 这里指定一个本地文件夹专门用来存 CSDN 的 Cookie，这样你只需要扫码登录一次
        user_data_dir = os.path.join(os.getcwd(), 'csdn_browser_data')

        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,  # 必须关闭无头模式，我们需要看到界面并在首次手动登录
            viewport={'width': 1280, 'height': 800}
        )

        page = browser.new_page()
        print("正在打开 CSDN Markdown 编辑器...")
        page.goto("https://editor.csdn.net/md/")

        # 留出时间让页面加载，如果是第一次运行，你需要在这个时间内扫码登录
        print("等待 15 秒 (如果是首次运行，请在弹出的浏览器中扫码/账号登录)...")
        page.wait_for_timeout(15000)

        # 4. 遍历并上传图片
        md_dir = os.path.dirname(os.path.abspath(md_file_path))

        # 4. 遍历并上传图片
        for img_path in images:
            # ====== 修改：智能处理绝对路径和相对路径 ======
            # 如果已经是绝对路径（例如 F:\... 或 /...），则保持不变
            if os.path.isabs(img_path):
                abs_img_path = img_path
            else:
                # 如果是相对路径，将其与 .md 文件所在的目录进行拼接
                abs_img_path = os.path.join(md_dir, img_path)

            # 规范化路径分隔符（自动处理 \ 和 / 的跨平台问题）
            abs_img_path = os.path.normpath(abs_img_path)

            if not os.path.exists(abs_img_path):
                print(f"⚠️ 找不到图片文件: {abs_img_path}，跳过该图。")
                continue

            print(f"✅ 成功定位图片，准备上传: {abs_img_path}")

            try:
                # 核心逻辑：监听 CSDN 上传图片的网络响应
                # CSDN 的图片上传接口通常是 POST 请求，且 URL 包含 upload 关键字
                with page.expect_response(
                        lambda response: "upload" in response.url and response.request.method == "POST",
                        timeout=15000
                ) as response_info:

                    # 强行给网页中的隐藏文件输入框塞入本地图片，模拟人为点击上传
                    # CSDN 编辑器里必然存在 <input type="file"> 用于接收图片
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(abs_img_path)

                # 5. 解析上传成功后返回的数据
                response = response_info.value
                resp_text = response.text()

                # 简单粗暴：直接通过正则从返回的 JSON 字符串中提取出 CSDN 的图床 URL
                # CSDN 的图床链接一般包含 csdnimg.cn
                url_match = re.search(r'(https://[^\s"\'\\]+csdnimg\.cn[^\s"\'\\]+)', resp_text)

                if url_match:
                    csdn_url = url_match.group(1)
                    print(f"✅ 上传成功，获得链接: {csdn_url}")
                    # 在 Markdown 内容中进行替换
                    content = content.replace(img_path, csdn_url)
                else:
                    print(f"❌ 上传请求成功，但未能在响应中找到图床 URL。返回体: {resp_text[:100]}...")

            except Exception as e:
                print(f"❌ 上传 {img_path} 时发生错误: {e}")

            # 稍微停顿一下，防止并发过高被 CSDN 封 IP
            page.wait_for_timeout(2000)

        browser.close()

    # 6. 将替换后的内容写出为新的 Markdown 文件
    out_file = md_file_path.replace('.md', '_csdn.md')
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\n🎉 处理完毕！已生成适合直接复制到 CSDN 的文件: {out_file}")


# ================= 运行测试 =================
if __name__ == "__main__":
    # 将这里替换为你本地想要处理的 md 文件路径
    target_md_file = r"F:\0000_CODE\CSDN_auto_upload\3588 Ubuntu TeamViewer 安装及使用\3588 Ubuntu Teamviewer 安装及使用.md"
    process_markdown_for_csdn(target_md_file)