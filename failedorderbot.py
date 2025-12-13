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

reported_failed_orders = set()  # prevent duplicate alerts

bot = Bot(token=BOT_TOKEN)

# =====================================================
# TELEGRAM ALERT
# =====================================================

async def send_telegram_alert(order_id: str):
    message = f"❌ Failed order detected\nOrder ID: {order_id}"
    await bot.send_message(chat_id=CHAT_ID, text=message)

# =====================================================
# PLAYWRIGHT LOGIC
# =====================================================

async def run_once():
    global reported_failed_orders

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Login
            await page.goto("https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE")
            await page.fill("input[name='log']", WP_USER)
            await page.fill("input[name='pwd']", WP_PASS)
            await page.click("input#wp-submit")

            # Orders page
            await page.goto(
                "https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing",
                wait_until="networkidle",
                timeout=90000
            )

            await page.wait_for_selector("table", timeout=90000)

            rows = await page.query_selector_all("table tbody tr")
            failed_orders = []

            for row in rows:
                try:
                    status = await row.inner_text()
                    if "Behandlas" in status:
                        link = await row.query_selector("a")
                        if link:
                            href = await link.get_attribute("href")
                            match = re.search(r'(?:post=|\bid=)(\d+)', href)
                            if match:
                                order_id = match.group(1)

                                order_page = await context.new_page()
                                await order_page.goto(href, timeout=30000)
                                text = await order_page.evaluate(
                                    "document.body.innerText.toLowerCase()"
                                )

                                # Check if order failed
                                if "ditt foto är nu redigerat" not in text:
                                    failed_orders.append(order_id)

                                await order_page.close()
                except Exception:
                    continue

            # Send alerts only for NEW failed orders
            for order_id in failed_orders:
                if order_id not in reported_failed_orders:
                    reported_failed_orders.add(order_id)
                    await send_telegram_alert(order_id)

            await browser.close()

    except Exception as e:
        print("Scan error:", e)

# =====================================================
# BACKGROUND LOOP
# =====================================================

async def order_monitor_loop():
    while True:
        print("🔍 Scanning orders...")
        await run_once()
        await asyncio.sleep(CHECK_INTERVAL)

# =====================================================
# HEALTH CHECK (RENDER / RAILWAY)
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
    print(f"🌐 Health server running on {PORT}")

# =====================================================
# START BOT
# =====================================================

async def main():
    print("🤖 Bot starting (send-only mode)")

    # Start health server and background monitoring
    asyncio.create_task(start_web_app())
    asyncio.create_task(order_monitor_loop())

    # Keep the main task alive
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
