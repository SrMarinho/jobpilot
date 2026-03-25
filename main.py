import os
import argparse
import src.config.settings as setting
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from src.automation.tasks.connection_manager import ConnectionManager
from src.config.settings import logger
from dotenv import load_dotenv


def setup_chrome_options(headless: bool = False):
    user_profile = os.environ["USERPROFILE"]
    chrome_user_data = f"{user_profile}\\AppData\\Local\\Google\\Chrome\\User Data"

    options = Options()
    options.add_argument(f"user-data-dir={chrome_user_data}")
    options.add_argument("profile-directory=Default")
    options.add_argument("--start-maximized")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    return options


def get_config() -> dict:
    env_headless = str(os.getenv("HEADLESS")).upper()
    headless = False if env_headless == "FALSE" else True

    return {"headless": headless}


def setup():
    config = get_config()
    options = setup_chrome_options(**config)
    driver = webdriver.Chrome(options=options)
    return driver


def parse_args():
    parser = argparse.ArgumentParser(description="LinkedIn connection automation")
    parser.add_argument("--url", type=str, required=True, help="URL da página de busca do LinkedIn")
    parser.add_argument("--max-pages", type=int, default=100, help="Número máximo de páginas (padrão: 100)")
    return parser.parse_args()


def main():
    args = parse_args()
    with setup() as driver:
        try:
            ConnectionManager(driver, url=args.url, max_pages=args.max_pages).run()
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception as e:
            logger.critical(f"{str(e)}")
            driver.save_screenshot(f"{setting.screenshots_path}.png")
            raise


if __name__ == "__main__":
    load_dotenv()
    main()
