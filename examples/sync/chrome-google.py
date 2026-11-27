"""The following example navigates to google.com using Chrome and synchronously captures the rendered page source."""

import logging
from selenium_to_html import FetchConfig, capture_page_sync

from selenium.webdriver import Chrome


def main():
    driver: Chrome = Chrome()
    driver.get("https://google.com")

    # All failures are logged under "selenium_to_html.*"
    logging.basicConfig(level=logging.INFO)   
    result = capture_page_sync(driver, FetchConfig(include_media=True, embed_media=True))
    
    if not result.embedded_source:
        raise Exception("The capture failed retrieve the embedded source.") 
        
    # the raw page source can be found at result.page_source
    with open("chrome-google-sync.html", "w") as output:
        output.write(result.embedded_source)  # pyright: ignore[reportUnusedCallResult]

if __name__ == "__main__":
    main()