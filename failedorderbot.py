import asyncio
import re
import aiohttp
from playwright.async_api import async_playwright

# === TELEGRAM CONFIG ===
TELEGRAM_BOT_TOKEN = "8207015657:AAFN50YiVxgugKx2qPZquNK5dGFsDOn8t6g"
CHAT_ID = "7831605046"

async def send_telegram(message: str):
    """Send Telegram notification."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}

    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, data=data)
        except Exception as e:
            print("Telegram error:", e)


async def check_orders():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # LOGIN
        await page.goto("https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE")
        await page.fill("input[name='log']", "prijnen6@gmail.com")
        await page.fill("input[name='pwd']", "prijnen6@gmail.com")
        await page.click("input#wp-submit")

        await asyncio.sleep(3)

        # GO TO PROCESSING ORDERS
        await page.goto("https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing", wait_until="networkidle")
        await asyncio.sleep(3)

        # FETCH ROWS
        all_rows = await page.query_selector_all("table.wp-list-table tbody tr")
        if not all_rows:
            all_rows = await page.query_selector_all("table.widefat tbody tr")

        behandlas_orders = []

        async def check_status(row):
            try:
                status_text = ""
                selectors = [
                    "td.column-order_status mark.status span",
                    "td.column-order_status mark span",
                    "td.order_status mark > span",
                    "td.column-order_status mark"
                ]
                for s in selectors:
                    el = await row.query_selector(s)
                    if el:
                        status_text = await el.inner_text()
                        break

                if "Behandlas" not in status_text:
                    return

                link = await row.query_selector("td.column-order_number a")
                if not link:
                    return

                href = await link.get_attribute("href")
                if not href:
                    return

                match = re.search(r'(?:post=|\bid=)(\d+)', href)
                if match:
                    behandlas_orders.append((match.group(1), href))
            except:
                pass

        await asyncio.gather(*(check_status(row) for row in all_rows))

        print("Orders in Processing:", behandlas_orders)

        pages = []
        order_urls = []

        async def open_tab(order_id, href):
            try:
                new_page = await context.new_page()
                await new_page.goto(href, wait_until="domcontentloaded", timeout=30000)
                pages.append(new_page)
                order_urls.append((order_id, href))
            except:
                pass

        await asyncio.gather(*(open_tab(oid, href) for oid, href in behandlas_orders))

        failed = []
        updated = []

        async def process_order(pg, order_id, url):
            try:
                await pg.wait_for_selector("#order_data", timeout=10000)

                text = await pg.eval_on_selector_all("*", "els => els.map(el => el.textContent).join(' ').toLowerCase()")

                if "ditt foto är nu redigerat" not in text:
                    failed.append(order_id)
                    return

                btn = await pg.query_selector("#woocommerce-order-actions div.inside ul li:nth-child(2) button")
                if btn:
                    await btn.click()
                    await asyncio.sleep(1)
                    updated.append(order_id)
                else:
                    failed.append(order_id)

            except:
                failed.append(order_id)
            finally:
                await pg.close()

        await asyncio.gather(*(process_order(pg, oid, url) for pg, (oid, url) in zip(pages, order_urls)))

        await browser.close()

        return updated, failed


async def main():
    while True:
        print("🔄 Checking orders...")
        updated, failed = await check_orders()

        print("Updated:", updated)
        print("Failed:", failed)

        if failed:
            msg = "⚠️ FAILED ORDERS DETECTED:\n" + "\n".join(failed)
            await send_telegram(msg)

        print("⏳ Waiting 60 seconds...")
        await asyncio.sleep(60)  # repeat every 60 seconds


asyncio.run(main())
