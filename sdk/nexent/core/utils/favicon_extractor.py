import requests
from urllib.parse import urlparse


def get_favicon_url(page_url: str) -> str:
    """Build the default favicon URL for a given page URL.

    Args:
        page_url: Target page URL.

    Returns:
        Default favicon URL.
    """
    parsed_url = urlparse(page_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    return f"{base_url}/favicon.ico"


def check_favicon_exists(url: str) -> bool:
    """Check whether a favicon URL exists.

    Args:
        url: Favicon URL to check.

    Returns:
        True if the favicon exists, otherwise False.
    """
    try:
        response = requests.head(url, timeout=3, allow_redirects=True)
        return response.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    url = "https://www.travelking.com.tw/zh-cn/tourguide/scenery100577.html"
    # url = "https://apps.apple.com/cn/app/wemeeting/id1480497919"

    # Manual smoke check for favicon existence.
    _ = check_favicon_exists(get_favicon_url(url))
