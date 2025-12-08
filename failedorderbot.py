import os
import asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiohttp import web

# =====================================================
# LOAD ENV VARIABLES
# =====================================================

load_dotenv()

WP_LOGIN_URL = os.getenv("WP_LOGIN_URL")
WP_ORDERS_URL = os.getenv("WP_ORDERS_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_PASSWORD = os.getenv("WP_PASSWORD")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", 60))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =====================================================
# GET FAILED ORDERS
# =====================================================

async def get_failed_orders():
    print("🔍 Checking WordPress orders...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        page = await context.new_page()

        # Login to WordPress
        await page.goto(WP_LOGIN_URL)
        await page.fill("#user_login", WP_USERNAME)
        await page.fill("#user_pass", WP_PASSWORD)
        await page.click("#wp-submit")
        await page.wait_for_load_state("domcontentloaded")

        # Navigate to processing orders
        await page.goto(WP_ORDERS_URL)
        await page.wait_for_selector("table.wp-list-table")

        rows = await page.query_selector_all("tbody tr")

        failed_orders = []

        for row in rows:
            status_el = await row.query_selector("mark.order-status > span")
            status = await status_el.inner_text()

            if "Failed" in status or "failed" in status:
                order_id_el = await row.query_selector("td.order_title a")
                order_id = await order_id_el.inner_text()

                failed_orders.append(order_id)

        await browser.close()

        return failed_orders

# =====================================================
# PERIODIC CHECKER
# =====================================================

async def periodic_check():
    while True:
        failed = await get_failed_orders()

        if failed:
            msg = "❌ *FAILED ORDERS FOUND:*\n" + "\n".join([f"• Order #{o}" for o in failed])
            await bot.send_message(CHAT_ID, msg, parse_mode=ParseMode.MARKDOWN)
        else:
            print("✅ No failed orders.")

        await asyncio.sleep(CHECK_INTERVAL)

# =====================================================
# COMMAND HANDLER
# =====================================================

@dp.message(commands=["start"])
async def start_cmd(message: types.Message):
    await message.reply("👋 Bot is running and monitoring orders!")

# =====================================================
# DUMMY HTTP SERVER FOR RENDER
# =====================================================

async def health(request):
    return web.Response(text="OK")

async def start_web_app():
    app = web.Application()
    app.add_routes([web.get("/", health)])

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🌐 Dummy HTTP server running on port {port}")

# =====================================================
# START BOT
# =====================================================

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🧹 Webhook deleted. Polling starts...")

    asyncio.create_task(start_web_app())
    asyncio.create_task(periodic_check())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
