from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def wait_and_click(wait, by, selector):
    elem = wait.until(EC.element_to_be_clickable((by, selector)))
    elem.click()
    return elem


def wait_and_send_keys(wait, by, selector, keys):
    elem = wait.until(EC.visibility_of_element_located((by, selector)))
    elem.clear()
    elem.send_keys(keys)
    return elem


class TestNexent():
    @classmethod
    def setup_class(cls):
        options = Options()
        # use headless mode
        options.add_argument('--headless')
        cls.driver = webdriver.Firefox(options=options)
        cls.wait = WebDriverWait(cls.driver, 30)

    @classmethod
    def teardown_class(cls):
        cls.driver.quit()

    def test_login(self):
        self.driver.get("http://120.26.61.157:3000/zh")
        # Wait for and click the user icon
        wait_and_click(self.wait, By.CSS_SELECTOR, ".anticon-user > svg")
        # Wait for and click the login menu
        wait_and_click(self.wait, By.XPATH, "//li[3]/span[2]")
        # Wait for email input to be visible and enter email
        wait_and_send_keys(self.wait, By.XPATH, "(//input[@id='email'])[2]", "test@qq.com")
        # Wait for and click the area before the password input (if any)
        wait_and_click(self.wait, By.XPATH, "//div[4]/div[2]/div/div/div")
        # Wait for password input to be visible and enter password
        wait_and_send_keys(self.wait, By.XPATH, "(//input[@id='password'])[2]", "x")
        # Wait for and click the login button
        wait_and_click(self.wait, By.XPATH,
                       "/html/body/div[4]/div[2]/div/div[1]/div/div[2]/form/div[3]/div/div/div/div/button")

        # Check if login was successful by verifying the presence of the email indicator
        try:
            success_elem = self.wait.until(
                EC.visibility_of_element_located((By.XPATH, "/html/body/div[1]/header/div[2]/span[1]")))
            assert success_elem is not None, "Login failed: Email indicator not found."
        except Exception as e:
            assert False, f"Login failed: {str(e)}"

    def test_chat(self):
        # Wait for modal overlay to disappear
        self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".ant-modal-wrap")))
        # Wait for the 'Start Q&A' button to be clickable
        wait_and_click(self.wait, By.XPATH, "//button[contains(.,'开始问答')]")
        # Wait for textarea to be visible and enter question
        wait_and_send_keys(self.wait, By.XPATH, "//textarea", "北京今天天气怎么样？")
        # Wait for the output to appear (replace sleep with explicit wait for output)
        output_xpath = "/html/body/div[2]/div[1]/div[2]/div/div[1]/div[1]/div[1]/div/div"
        try:
            elem = WebDriverWait(self.driver, 40).until(
                lambda d: (lambda e: e if e.text.strip() != '' else None)(d.find_element(By.XPATH, output_xpath))
            )
        except Exception:
            elem = None

        if elem is None:
            assert False, "Test failed: No output received within 40 seconds."
        else:
            output_text = elem.text
            assert 'error' not in output_text.lower(), f"Test failed: Output contains 'error'. Actual output: {output_text}"
