import urllib.request
import urllib.parse
import os
import sys

SAVE_DIR = r"c:\Users\qianshengjia\Code\AI\nexent\docs\a2ui_samples"

IMAGES = [
    {
        "filename": "info_card.png",
        "prompt": "A clean info card UI component in a chat interface, showing a notification icon with a green checkmark, title '操作成功', body text '您的订单已完成处理，商品将在 24 小时内发货', and a small '知道了' button at the bottom. White background with subtle shadow, rounded corners, modern flat design, professional enterprise software style, centered composition."
    },
    {
        "filename": "feedback_card.png",
        "prompt": "A feedback card UI component in a chat interface, showing a question '您觉得这次服务体验如何？' with 3 rating options as clickable buttons: '非常满意' (green), '一般' (gray), '不满意' (red), plus a text input field for additional comments with placeholder '请输入您的建议...'. White background with rounded corners, modern flat design."
    },
    {
        "filename": "confirmation_card.png",
        "prompt": "A confirmation dialog card UI component in a chat interface, showing a warning icon with orange exclamation mark, title '确认删除', body text '此操作将永久删除当前对话记录，删除后不可恢复', with two buttons: gray '取消' button and red '确认删除' button. White background with rounded corners, modern alert design."
    },
    {
        "filename": "form_card.png",
        "prompt": "A form card UI component in a chat interface with multiple input fields: name input field with label '姓名', email input field with label '邮箱', department dropdown with label '部门', and a blue '提交表单' submit button at the bottom. Each field has a clean label above it. White background with rounded corners, professional form design."
    },
    {
        "filename": "rating_card.png",
        "prompt": "A rating card UI component in a chat interface, showing 5 large gold stars for rating, with labels '非常差', '较差', '一般', '满意', '非常满意' below each star, and a text area for review with placeholder '写下您的评价...', plus a '提交评价' button. White background with rounded corners, modern rating design."
    }
]

def download_image(filename, prompt):
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt={encoded_prompt}&image_size=landscape_4_3"
    save_path = os.path.join(SAVE_DIR, filename)

    print(f"Downloading {filename}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
        with open(save_path, "wb") as f:
            f.write(data)
        print(f"  Saved: {save_path} ({len(data)} bytes)")
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return False
    return True

def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    success = 0
    for img in IMAGES:
        if download_image(img["filename"], img["prompt"]):
            success += 1
    print(f"\nDone: {success}/{len(IMAGES)} images downloaded successfully.")

if __name__ == "__main__":
    main()