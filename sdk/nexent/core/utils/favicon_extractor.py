import requests
from urllib.parse import urlparse

def get_favicon_url(page_url):
    """
    从给定网页URL提取favicon图标地址

    参数:
        page_url (str): 要分析的网页URL

    返回:
        str: favicon图标的完整URL，如果找不到则返回None
    """

    # 解析输入URL
    parsed_url = urlparse(page_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    default_favicon = f"{base_url}/favicon.ico"
    return default_favicon


def check_favicon_exists(url):
    """
    检查给定的favicon URL是否有效

    参数:
        url (str): 要检查的favicon URL

    返回:
        bool: 如果URL存在且返回200状态码则为True
    """
    try:
        response = requests.head(url, timeout=3, allow_redirects=True)
        return response.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    url = "https://www.travelking.com.tw/zh-cn/tourguide/scenery100577.html"
    # url = "https://apps.apple.com/cn/app/wemeeting/id1480497919"

    # 获取favicon URL
    import time
    start = time.time()
    favicon_url = get_favicon_url(url)

    if favicon_url:
        print(f"找到favicon: {favicon_url}")
    else:
        print("未找到favicon")
    end = time.time()
    print(str(end - start))

    print(check_favicon_exists(favicon_url))

