import time
from selenium.common.exceptions import ElementClickInterceptedException
from src.automation.pages.linkedin_search_page import PeopleSearchPage
from src.config.settings import logger


class ConnectionHandler:
    def __init__(self, page: PeopleSearchPage):
        self.page = page
        self.invite_sended = 0
        self.limit_reached = False

    def run(self):
        while btn_connect := self.page.get_connect_btn():
            try:
                btn_connect.click()
            except ElementClickInterceptedException:
                if self.page.is_invite_limit_reached():
                    logger.warning("Limite de convites do LinkedIn atingido. Encerrando.")
                    self.limit_reached = True
                    return
                self.page.close_modal()
                continue

            btn_confirm = self.page.get_confirm_invitation_btn()
            if not btn_confirm:
                if self.page.is_invite_limit_reached():
                    logger.warning("Limite de convites do LinkedIn atingido. Encerrando.")
                    self.limit_reached = True
                    return
                self.page.close_modal()
                continue

            btn_confirm.click()
            self.invite_sended += 1
            time.sleep(1)
