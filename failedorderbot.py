import os
import re
import asyncio
from aiohttp import web
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher

# =====================================================
# CONFIG
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

WP_USER = os.getenv("WP_USER")
WP_PASS = os.getenv("WP_PASS")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", 120))
PORT = int(os.getenv("PORT", 10000))

reported_failed_orders = set()  # avoid duplicate alerts

bot = Bot(token=BOT_TOKEN)

# =====================================================
# TELEGRAM ALERT
# =====================================================

async def send_telegram_alert(order_id: str):
    message = f"❌ Failed order detected\nOrder ID: {order_id}"
    await bot.send_message(chat_id=CHAT_ID, text=message)
    print(f"📩 Telegram alert sent for failed order: {order_id}")

# =====================================================
# PLAYWRIGHT LOGIC
# =====================================================

async def run_once():
    global reported_failed_orders

    print("🔍 Starting order scan...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)  # headless for Render
            context = await browser.new_context()
            page = await context.new_page()

            # -------- LOGIN --------
            try:
                await page.goto("https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE")
                print("Login page loaded")
                await page.fill("input[name='log']", WP_USER)
                await page.fill("input[name='pwd']", WP_PASS)
                await page.click("input#wp-submit")
                await page.wait_for_load_state("networkidle")
                print("Login submitted")
            except Exception as e:
                print("❌ Login failed:", e)
                await browser.close()
                return

            # -------- ORDERS PAGE --------
            try:
                await page.goto(
                    "https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing",
                    wait_until="networkidle",
                    timeout=90000
                )
                await page.wait_for_selector("table", timeout=90000)
                print("Orders page loaded")
            except Exception as e:
                print("❌ Orders page load failed:", e)
                await browser.close()
                return

            rows = await page.query_selector_all("table tbody tr")
            print(f"Total orders found on page: {len(rows)}")

            failed_orders = []

            for i, row in enumerate(rows, start=1):
                try:
                    status_text = await row.inner_text()
                    print(f"Checking order row {i}: {status_text.strip()[:50]}...")

                    if "Behandlas" in status_text:
                        link = await row.query_selector("a")
                        if link:
                            href = await link.get_attribute("href")
                            match = re.search(r'(?:post=|\bid=)(\d+)', href)
                            if match:
                                order_id = match.group(1)

                                order_page = await context.new_page()
                                await order_page.goto(href, timeout=30000)
                                text = await order_page.evaluate("document.body.innerText.toLowerCase()")

                                # Failed condition: "ditt foto är nu redigerat" not present
                                if "ditt foto är nu redigerat" not in text:
                                    failed_orders.append(order_id)
                                    print(f"❌ Order {order_id} is failed / not updated")

                                await order_page.close()
                except Exception as e:
                    print(f"❌ Error checking row {i}: {e}")

            # Send Telegram alerts only for new failed orders
            for order_id in failed_orders:
                if order_id not in reported_failed_orders:
                    reported_failed_orders.add(order_id)
                    await send_telegram_alert(order_id)

            print(f"✅ Scan completed: {len(rows)} orders checked, {len(failed_orders)} failed orders")

            await browser.close()

    except Exception as e:
        print("❌ Scan error:", e)

# =====================================================
# BACKGROUND LOOP
# =====================================================

async def order_monitor_loop():
    while True:
        await run_once()
        print(f"⏳ Waiting {CHECK_INTERVAL} seconds before next scan...\n")
        await asyncio.sleep(CHECK_INTERVAL)

# =====================================================
# HEALTH CHECK (RENDER)
# =====================================================

async def health(request):
    return web.Response(text="OK")

async def start_web_app():
    app = web.Application()
    app.add_routes([web.get("/", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Health server running on port {PORT}")

# =====================================================
# START BOT
# =====================================================

async def main():
    print("🤖 Failed Order Bot starting...")
    asyncio.create_task(start_web_app())
    asyncio.create_task(order_monitor_loop())
    # Keep main alive
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
