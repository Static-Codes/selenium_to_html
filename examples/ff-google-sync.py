"""The following example navigates to google.com using firefox and asynchronously captures the rendered page source."""

import logging
from selenium_to_html import FetchConfig, capture_page

from selenium.webdriver import Firefox


async def main():
    driver = Firefox()
    driver.get("https://google.com")

    # All failures are logged under "selenium_to_html.*"
    logging.basicConfig(level=logging.INFO)   
    result = await capture_page(driver, FetchConfig(include_media=True, embed_media=True))
    
    # the raw page source can be found at result.page_source
    with open("ff-google.sync.html", "w") as output:
        output.write(result.embedded_source)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())