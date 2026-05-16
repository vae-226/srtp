import asyncio, traceback, sys
sys.path.insert(0, ".")

async def test():
    try:
        print("Step 1", flush=True)
        from playwright.async_api import async_playwright
        print("Step 2", flush=True)
        async with async_playwright() as p:
            print("Step 3", flush=True)
            # Try using msedge or chrome channel
            browser = await p.chromium.launch(headless=True, channel="msedge")
            print("Step 4: browser launched", flush=True)
            page = await browser.new_page()
            print("Step 5: page created", flush=True)
            try:
                await page.goto("https://www.douyin.com", timeout=15000, wait_until="domcontentloaded")
                print("Step 6: goto succeeded", flush=True)
            except Exception as e:
                print(f"goto error: {type(e).__name__}: {e}", flush=True)
            await browser.close()
            print("Step 7", flush=True)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()

asyncio.run(test())
print("Done", flush=True)