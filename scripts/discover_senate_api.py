import asyncio
from playwright.async_api import async_playwright
import json
from datetime import datetime, timedelta


async def discover_senate_ptr():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        all_requests = []
        all_responses = []

        async def handle_request(request):
            # Capture everything except static assets
            if not any(x in request.url for x in ['.css', '.js', '.png', '.woff', 'google-analytics', 'fonts.googleapis']):
                all_requests.append({
                    'url': request.url,
                    'method': request.method,
                    'post_data': request.post_data
                })

        async def handle_response(response):
            if not any(x in response.url for x in ['.css', '.js', '.png', '.woff', 'google-analytics', 'fonts.googleapis']):
                try:
                    ct = response.headers.get('content-type', '')
                    if 'json' in ct:
                        body = await response.json()
                        all_responses.append({
                            'url': response.url,
                            'status': response.status,
                            'body': body
                        })
                        print(f"\n<<< JSON {response.status}: {response.url}")
                        if isinstance(body, dict):
                            print(f"    Keys: {list(body.keys())}")
                            # Look for results
                            for key in ['results', 'data', 'filings', 'reports', 'hits', 'items']:
                                if key in body:
                                    items = body[key]
                                    print(f"    '{key}': {len(items)} records")
                                    if items:
                                        first = items[0]
                                        print(f"    First record keys: {list(first.keys()) if isinstance(first, dict) else first}")
                                        print(f"    First record: {json.dumps(first, default=str)[:400]}")
                                    break
                        elif isinstance(body, list):
                            print(f"    List: {len(body)} records")
                            if body:
                                first = body[0]
                                print(f"    First keys: {list(first.keys()) if isinstance(first, dict) else ''}")
                                print(f"    First: {json.dumps(first, default=str)[:400]}")
                except Exception:
                    pass

        page = await context.new_page()
        page.on('request', handle_request)
        page.on('response', handle_response)

        # Step 1: consent
        print("Step 1: Consent...")
        await page.goto('https://efdsearch.senate.gov/search/home/', timeout=30000)
        await page.wait_for_timeout(3000)

        await page.evaluate("""
            () => {
                const cb = document.querySelector('input[type="checkbox"]');
                if (cb) {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'checked'
                    ).set;
                    setter.call(cb, true);
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                    cb.dispatchEvent(new Event('click', {bubbles: true}));
                }
            }
        """)
        await page.wait_for_timeout(1000)

        await page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
                const btn = btns.find(b =>
                    (b.textContent || b.value || '').toLowerCase().includes('agree') ||
                    (b.textContent || b.value || '').toLowerCase().includes('submit')
                );
                if (btn) btn.click();
            }
        """)
        await page.wait_for_load_state('networkidle', timeout=15000)
        await page.wait_for_timeout(2000)
        print(f"After consent: {page.url}")

        # Step 2: print all report_type inputs with their labels
        print("\nStep 2: Report type inputs with labels...")
        report_types = await page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('input[name="report_type"]').forEach(inp => {
                    // Get associated label
                    let label = '';
                    const id = inp.id;
                    if (id) {
                        const lbl = document.querySelector('label[for="' + id + '"]');
                        if (lbl) label = lbl.textContent.trim();
                    }
                    // Try parent label
                    if (!label) {
                        const parentLabel = inp.closest('label');
                        if (parentLabel) label = parentLabel.textContent.trim();
                    }
                    result.push({value: inp.value, type: inp.type, label: label, id: inp.id});
                });
                return result;
            }
        """)
        print("Report type options:")
        for rt in report_types:
            print(f"  value={rt['value']} type={rt['type']} label='{rt['label']}' id='{rt['id']}'")

        # Step 3: select all report types and set date range
        print("\nStep 3: Selecting report types and searching...")
        await page.evaluate("""
            () => {
                // Uncheck all report_type inputs first
                document.querySelectorAll('input[name="report_type"]').forEach(cb => {
                    cb.checked = false;
                });

                // For discovery, check all report types so any search hits
                document.querySelectorAll('input[name="report_type"]').forEach(cb => {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                });
            }
        """)
        await page.wait_for_timeout(500)

        # Set date range to last 90 days
        end_date = datetime.utcnow().strftime('%m/%d/%Y')
        start_date = (datetime.utcnow() - timedelta(days=90)).strftime('%m/%d/%Y')

        await page.evaluate(f"""
            () => {{
                const startInput = document.querySelector('input[name="submitted_start_date"]');
                const endInput = document.querySelector('input[name="submitted_end_date"]');
                if (startInput) {{
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(startInput, '{start_date}');
                    startInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                    startInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
                if (endInput) {{
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(endInput, '{end_date}');
                    endInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                    endInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
        """)
        await page.wait_for_timeout(500)

        # Click Search Reports
        await page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button'));
                const btn = btns.find(b => b.textContent.trim().includes('Search Reports'));
                if (btn) {
                    btn.click();
                    console.log('Clicked Search Reports');
                }
            }
        """)
        await page.wait_for_load_state('networkidle', timeout=20000)
        await page.wait_for_timeout(5000)

        print(f"\nResults URL: {page.url}")

        # Print all non-asset requests made
        print(f"\nAll requests made ({len(all_requests)}):")
        for req in all_requests:
            print(f"  {req['method']} {req['url']}")
            if req['post_data']:
                body_preview = req['post_data'][:300].replace('\n', ' ')
                print(f"    Body: {body_preview}")

        if not all_responses:
            print("\nNo JSON responses captured.")
            content = await page.content()
            print(f"Page content preview: {content[:1000]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(discover_senate_ptr())
