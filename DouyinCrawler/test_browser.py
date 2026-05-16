import asyncio, traceback
from playwright.async_api import async_playwright

async def test():
    try:
        async with async_playwright() as p:
            print("Playwright context created")
            chromium = p.chromium
            print(f"Chromium: {chromium}")
            browser = await chromium.launch(headless=True)
            print("Browser launched")
            page = await browser.new_page()
            print("Page created")
            await page.goto("https://www.douyin.com")
            print("Page loaded")
            await browser.close()
            print("Browser closed")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

asyncio.run(test())