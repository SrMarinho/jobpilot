import os
import time
import argparse
import src.config.settings as setting
import undetected_chromedriver as uc
from src.automation.tasks.connection_manager import ConnectionManager
from src.automation.tasks.job_application_manager import JobApplicationManager
from src.config.settings import logger
from dotenv import load_dotenv


BOT_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "bot_profile")


def get_config() -> dict:
    env_headless = str(os.getenv("HEADLESS")).upper()
    headless = False if env_headless == "FALSE" else True
    return {"headless": headless}


def setup() -> uc.Chrome:
    config = get_config()
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    driver = uc.Chrome(options=options, headless=config["headless"], version_main=146)
    return driver


LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "glassdoor": "https://www.glassdoor.com/profile/login_input.htm",
    "indeed": "https://secure.indeed.com/auth",
}


def parse_args():
    parser = argparse.ArgumentParser(description="JobPilot")
    subparsers = parser.add_subparsers(dest="task", required=True)

    login_parser = subparsers.add_parser("login", help="Open browser to log in to a job site")
    login_parser.add_argument(
        "site",
        choices=list(LOGIN_URLS.keys()),
        help="Site to log in to: linkedin, glassdoor, indeed",
    )

    connect_parser = subparsers.add_parser("connect", help="Send connection requests")
    connect_parser.add_argument("--url", type=str, required=True, help="LinkedIn people search URL")
    connect_parser.add_argument("--max-pages", type=int, default=100, help="Max pages to process (default: 100)")

    apply_parser = subparsers.add_parser("apply", help="Apply to jobs via Easy Apply")
    apply_parser.add_argument("--url", type=str, required=True, help="Job search URL")
    apply_parser.add_argument("--resume", type=str, default="resume.txt", help="Path to resume file (default: resume.txt)")
    apply_parser.add_argument("--preferences", type=str, default="", help="Job preferences to guide evaluation")
    apply_parser.add_argument("--level", type=str, nargs="+", default=[], help="Accepted seniority levels (e.g. --level junior pleno)")
    apply_parser.add_argument("--max-pages", type=int, default=100, help="Max pages to process (default: 100)")

    return parser.parse_args()


def run_login(site: str):
    url = LOGIN_URLS[site]
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    driver = uc.Chrome(options=options, headless=False, version_main=146)
    driver.get(url)
    print(f"Browser opened at {url}")
    print("Log in and close the browser window when done.")
    while True:
        try:
            _ = driver.window_handles
            time.sleep(1)
        except Exception:
            break
    print("Browser closed. Login session saved.")


def main():
    args = parse_args()

    if args.task == "login":
        run_login(args.site)
        return

    driver = setup()
    try:
        if args.task == "connect":
            ConnectionManager(driver, url=args.url, max_pages=args.max_pages).run()
        elif args.task == "apply":
            JobApplicationManager(driver, url=args.url, resume_path=args.resume, preferences=args.preferences, level=args.level, max_pages=args.max_pages).run()
        try:
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception:
            pass
    except Exception as e:
        logger.critical(f"{str(e)}")
        try:
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception:
            pass
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    load_dotenv()
    main()
