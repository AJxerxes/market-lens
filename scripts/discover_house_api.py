"""
Discover House Financial Disclosure (PTR) API by navigating to the Financial
Disclosure section and capturing XHR/network calls. Run from worktree root:
  .\\venv\\Scripts\\python.exe scripts\\discover_house_api.py
"""
import asyncio
import json
from playwright.async_api import async_playwright


async def discover_house_financial_disclosure():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        all_xhr = []

        async def handle_request(request):
            if not any(x in request.url for x in ['.css', '.js', '.png', '.woff', '.svg', 'google', 'fonts']):
                entry = {'url': request.url, 'method': request.method, 'body': request.post_data}
                all_xhr.append(entry)

        async def handle_response(response):
            if not any(x in response.url for x in ['.css', '.js', '.png', '.woff', '.svg', 'google', 'fonts']):
                try:
                    ct = response.headers.get('content-type', '')
                    if 'json' in ct:
                        body = await response.json()
                        print(f"\n<<< JSON {response.status}: {response.url}")
                        if isinstance(body, dict):
                            print(f"    Keys: {list(body.keys())}")
                            hits = body.get('filteredHits', body.get('hits', body.get('data', body.get('results', []))))
                            if isinstance(hits, list) and hits:
                                print(f"    Records: {len(hits)}")
                                print(f"    First keys: {list(hits[0].keys()) if isinstance(hits[0], dict) else hits[0]}")
                                print(f"    First: {json.dumps(hits[0], default=str)[:400]}")
                        elif isinstance(body, list) and body:
                            print(f"    List records: {len(body)}")
                            print(f"    First: {json.dumps(body[0], default=str)[:400]}")
                except Exception:
                    pass

        page = await context.new_page()
        page.on('request', handle_request)
        page.on('response', handle_response)

        # Try direct URLs for the Financial Disclosure section specifically
        fd_urls = [
            'https://disclosures.house.gov/FinancialDisclosure',
            'https://disclosures.house.gov/FinancialDisclosure#Search',
            'https://disclosures.house.gov/FinancialDisclosure/ViewMemberSearchResult',
            'https://disclosures.house.gov/FinancialDisclosure/SearchResult',
        ]

        for url in fd_urls:
            print(f"\n{'='*50}")
            print(f"Trying: {url}")
            try:
                await page.goto(url, wait_until='networkidle', timeout=20000)
                await page.wait_for_timeout(3000)

                title = await page.title()
                current_url = page.url
                print(f"Title: {title}")
                print(f"Current URL: {current_url}")

                # Check if this is different from lobbying section
                if 'lobbying' in title.lower():
                    print("Still on lobbying section — trying to navigate within the app")

                    # Try clicking Financial Disclosure link in navigation
                    nav_links = await page.query_selector_all('a, button, [role="tab"], [role="menuitem"]')
                    for link in nav_links:
                        text = (await link.inner_text()).strip().lower()
                        href = await link.get_attribute('href') or ''
                        if 'financial' in text or 'financial' in href.lower():
                            print(f"Found financial link: '{text}' href='{href}'")
                            await link.click()
                            await page.wait_for_load_state('networkidle', timeout=10000)
                            await page.wait_for_timeout(2000)
                            print(f"After click URL: {page.url}")
                            print(f"After click title: {await page.title()}")
                            break

                # Screenshot current state
                screenshot_path = f'scripts/house_fd_{fd_urls.index(url)}.png'
                await page.screenshot(path=screenshot_path)
                print(f"Screenshot: {screenshot_path}")

                # Print all links on page to find navigation
                links = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a')).map(a => ({
                        text: a.textContent.trim().substring(0, 50),
                        href: a.href
                    })).filter(l => l.text)
                """)
                print(f"Links on page ({len(links)}):")
                for l in links[:20]:
                    print(f"  '{l['text']}' -> {l['href']}")

                # Try to trigger a search
                selects = await page.query_selector_all('select')
                for sel in selects:
                    name = await sel.get_attribute('name') or await sel.get_attribute('id') or ''
                    options = await sel.query_selector_all('option')
                    opts = [(await o.get_attribute('value') or '', await o.inner_text()) for o in options]
                    print(f"Select '{name}': {opts[:5]}")
                    if any('ptr' in v.lower() or 'periodic' in t.lower() for v, t in opts):
                        ptr_opts = [v for v, t in opts if 'ptr' in v.lower() or 'periodic' in t.lower()]
                        if ptr_opts:
                            await sel.select_option(value=ptr_opts[0])
                            print("Selected PTR option")
                            break

                # Click any search button
                for selector in ['button:has-text("Search")', 'input[type="submit"]', 'button[type="submit"]']:
                    btn = await page.query_selector(selector)
                    if btn:
                        print(f"Clicking search: {selector}")
                        await btn.click()
                        await page.wait_for_load_state('networkidle', timeout=15000)
                        await page.wait_for_timeout(3000)
                        break

            except Exception as e:
                print(f"Error: {e}")
                continue

        print(f"\n{'='*50}")
        print(f"All non-asset requests captured ({len(all_xhr)}):")
        for req in all_xhr:
            print(f"  {req['method']} {req['url']}")
            if req.get('body'):
                print(f"    Body: {req['body'][:200]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(discover_house_financial_disclosure())
