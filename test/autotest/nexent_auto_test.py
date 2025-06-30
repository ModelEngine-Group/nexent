from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import time
import json
import os


def load_json(config_file="config.json"):
    # 获取配置文件所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, config_file)

    # 读取配置文件
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        return config

def contains_any_char(s, char_list):
    return any(char in s for char in char_list)

def connect_nexent(config):
    # 设置Firefox选项
    firefox_options = Options()
    # 无头模式，在进行测试时，不打开浏览器
    # firefox_options.add_argument('--headless')

    # 设置GeckoDriver路径
    gecko_path = config.get('gecko_path')
    # 创建GeckoDriver服务
    service = Service(executable_path=gecko_path)

    # 设置WebDriver路径（如果已添加到PATH则可以省略）
    browser = webdriver.Firefox(options=firefox_options, service=service)

    # 打开Nexent主页
    browser.get(config.get("env_url"))

    # sleep 3s，因为上述窗口打开过程中有延迟，避免下述操作在窗口还未打开时执行，执行会出错
    # todo 应该有更精确的等待机制
    time.sleep(3)

    # 登录用户账号
    browser.find_element(By.XPATH, config.get("auth_button_xpath")).send_keys(
        Keys.ENTER)
    browser.find_element(By.ID, config.get("user_id")).send_keys(config.get('username'))
    browser.find_element(By.ID, config.get("password_id")).send_keys(config.get('password'))
    # todo 应该有更精确的等待机制
    time.sleep(3)
    browser.find_element(By.XPATH, config.get("confirm_button_xpath")).send_keys(Keys.ENTER)
    browser.find_element(By.XPATH, config.get("input_xpath")).send_keys("最近7天上海的天气情况")
    browser.find_element(By.XPATH, config.get("input_confirm_button_xpath")).send_keys(Keys.ENTER)

    # 等待输出结束
    time.sleep(40)
    output = browser.find_element(By.XPATH, config.get("output_xpath"))
    # print("output:", output)
    error_list = ["Error"]
    if not contains_any_char(output.text, error_list):
        print("test successfully!")
    else:
        print("test failed!")


    # 等待页面加载（例如，等待10秒）
    # 注意：在实际测试中，应使用更精确的等待机制，如WebDriverWait。
    # todo 应该有更精确的等待机制
    time.sleep(10)

    # 关闭浏览器
    browser.quit()


if __name__ == "__main__":
    config = load_json()
    connect_nexent(config)