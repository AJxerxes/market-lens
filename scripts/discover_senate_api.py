"""
Senate eFD (efdsearch.senate.gov) discovery: accept consent and capture PTR/search API.
Consent page: single checkbox "I understand the prohibitions on obtaining and use
of financial disclosure reports" then submit. Run with: python scripts/discover_senate_api.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Install playwright: pip install playwright && playwright install chromium")
        return

    url = "https://efdsearch.senate.gov/search/home/"
    print(f"Opening {url} ...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Optional: capture API requests for discovery
        captured_requests = []

        async def on_request(req):
            if req.resource_type in ("xhr", "fetch") and req.url:
                captured_requests.append({"url": req.url, "method": req.method})

        async def pass_through(route):
            await route.continue_()

        await page.route("**/*", pass_through)
        page.on("request", on_request)

        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        # Wait for the checkbox to be present
        await page.wait_for_selector('input[type="checkbox"]', timeout=10000)
        await page.wait_for_timeout(1000)

        # Use JS to check it and dispatch React-compatible change event
        await page.evaluate("""
            () => {
                const cb = document.querySelector('input[type="checkbox"]');
                if (cb && !cb.checked) {
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'checked'
                    ).set;
                    nativeInputValueSetter.call(cb, true);
                    cb.dispatchEvent(new Event('change', { bubbles: true }));
                    cb.dispatchEvent(new Event('click', { bubbles: true }));
                }
                return cb ? cb.checked : false;
            }
        """)
        await page.wait_for_timeout(1000)

        # Now find and click the submit button
        await page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
                const btn = btns.find(b =>
                    (b.textContent || b.value || '').toLowerCase().includes('agree') ||
                    (b.textContent || b.value || '').toLowerCase().includes('submit') ||
                    (b.textContent || b.value || '').toLowerCase().includes('search')
                );
                if (btn) btn.click();
            }
        """)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)

        print(f"After consent URL: {page.url}")

        if captured_requests:
            print("Captured XHR/fetch requests:")
            for r in captured_requests[-20:]:
                print(f"  {r['method']} {r['url'][:120]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
