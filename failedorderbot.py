import asyncio
import os
import re
import httpx
from aiohttp import web
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# =====================================================
# CONFIGURATION
# =====================================================
WP_URL = "https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE"
WP_EMAIL = os.getenv("WP_EMAIL")
WP_PASSWORD = os.getenv("WP_PASSWORD")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 120))  # seconds
PORT = int(os.getenv("PORT", 10000))

# =====================================================
# TELEGRAM FUNCTION
# =====================================================
async def send_telegram_message(message):
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                TELEGRAM_API,
                json={"chat_id": CHAT_ID, "text": message}
            )
        except Exception as e:
            print("Telegram error:", e)

# =====================================================
# BOT LOGIC
# =====================================================
async def run_once():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
    headless=True,

)
            context = await browser.new_context()
            page = await context.new_page()

            # ---------- LOGIN ----------
            await page.goto(WP_URL)
            await page.fill("input[name='log']", WP_EMAIL)
            await page.fill("input[name='pwd']", WP_PASSWORD)
            await page.click("input#wp-submit")
            await page.wait_for_timeout(5000)

            # ---------- ORDERS ----------
            await page.goto(
                "https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing",
                wait_until="networkidle",
                timeout=60000
            )

            rows = await page.query_selector_all("table tbody tr")
            behandlas_orders = []

            for row in rows:
                text = await row.inner_text()
                if "Behandlas" in text:
                    link = await row.query_selector("a")
                    if link:
                        href = await link.get_attribute("href")
                        match = re.search(r'post=(\d+)', href)
                        if match:
                            behandlas_orders.append((match.group(1), href))

            if not behandlas_orders:
                await send_telegram_message("ℹ️ No Behandlas orders found.")
                await browser.close()
                return

            updated = []

            for order_id, url in behandlas_orders:
                p2 = await context.new_page()
                await p2.goto(url)
                content = await p2.content()

                if "ditt foto är nu redigerat" in content.lower():
                    btn = await p2.query_selector(
                        "#woocommerce-order-actions button"
                    )
                    if btn:
                        await btn.click()
                        updated.append(order_id)

                await p2.close()

            if updated:
                await send_telegram_message(f"✅ Updated orders: {updated}")

            await browser.close()
    except Exception as e:
        await send_telegram_message(f"❌ Bot error: {e}")
        print("Error in run_once:", e)

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
