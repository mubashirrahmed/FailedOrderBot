import os
import re
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from playwright.async_api import async_playwright
import logging
# =====================================================
# 🔐 CONFIG
# =====================================================
TOKEN = os.getenv("BOT_TOKEN", "8207015657:AAFN50YiVxgugKx2qPZquNK5dGFsDOn8t6g")
CHAT_ID = int(os.getenv("CHAT_ID", 7831605046))

bot = Bot(TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =====================================================
# INSTALL PLAYWRIGHT BROWSERS ON RENDER (ONE-TIME)
# =====================================================
async def install_playwright_browsers():
    if os.getenv("RENDER"):
        logger.info("Render detected — installing Playwright browsers...")
        os.system("playwright install --with-deps chromium")
        logger.info("Playwright browsers installed successfully.")
    else:
        logger.info("Not on Render — skipping browser install.")

# =====================================================
# MAIN ORDER UPDATER — ONLY NOTIFIES ON FAILURE
# =====================================================
async def update_orders():
    await asyncio.sleep(15)  # give everything time to start

    while True:
        failed_orders = []
        critical_error = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                # Login
                await page.goto("https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE")
                await page.fill("input[name='log']", os.getenv("WP_USER"))
                await page.fill("input[name='pwd']", os.getenv("WP_PASS"))
                await page.click("input#wp-submit")
                await page.wait_for_load_state("networkidle")

                # Go to Processing orders
                await page.goto(
                    "https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing",
                    wait_until="networkidle",
                    timeout=120000
                )

                await page.wait_for_selector("table.wp-list-table, table.widefat", timeout=30000)

                rows = await page.query_selector_all("tbody tr")
                behandlas_orders = []

                for row in rows:
                    status = await row.query_selector("td.column-order_status mark span, td.order_status span")
                    if status:
                        text = await status.inner_text()
                        if "Behandl" in text.lower() or "processing" in text.lower():
                            link = await row.query_selector("td.column-order_number a")
                            href = await link.get_attribute("href") if link else None
                            order_id = re.search(r'id=(\d+)|post=(\d+)', href or "", re.I)
                            if order_id:
                                oid = order_id.group(1) or order_id.group(2)
                                behandlas_orders.append((oid, href))

                # Process each order
                for order_id, url in behandlas_orders:
                    try:
                        order_page = await context.new_page()
                        await order_page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        content = (await order_page.content()).lower()

                        if "ditt foto är nu redigerat" in content or "your photo has now been edited" in content:
                            # Click Complete order button
                            complete_btn = await order_page.query_selector(
                                "button.woocommerce-order-actions__button-complete, "
                                "button[value='complete'], "
                                "input[name='wc_order_action'][value='complete']"
                            )
                            if complete_btn:
                                await complete_btn.click()
                                await asyncio.sleep(2)
                            else:
                                failed_orders.append(order_id)
                        else:
                            failed_orders.append(order_id)

                        await order_page.close()
                    except Exception as e:
                        failed_orders.append(order_id)
                        logger.error(f"Error processing order #{order_id}: {e}")

                await browser.close()

        except Exception as e:
            critical_error = str(e)
            logger.exception("Critical error in order updater")

        # ONLY SEND MESSAGE IF SOMETHING FAILED
        if failed_orders:
            await bot.send_message(
                CHAT_ID,
                f"Failed to auto-complete {len(failed_orders)} order(s):\n"
                f"`#{', #'.join(failed_orders)}`",
                parse_mode="Markdown"
            )

        if critical_error:
            await bot.send_message(CHAT_ID, f"Updater crashed:\n`{critical_error}`", parse_mode="Markdown")

        # No message = everything worked perfectly

        await asyncio.sleep(60)

# =====================================================
# BOT COMMANDS
# =====================================================
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "Auto-updater is running!\n\n"
        "You will ONLY receive a message when an order fails to complete.\n"
        "Silence = all good"
    )

# =====================================================
# DUMMY WEB SERVER (required by Render)
# =====================================================
from aiohttp import web

async def health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000)))
    await site.start()
    logger.info(f"Web server started on port {os.getenv('PORT', 10000)}")

# =====================================================
# MAIN
# =====================================================
async def main():
    # 1. Install browsers on Render
    await install_playwright_browsers()

    # 2. Start background tasks
    asyncio.create_task(start_web_server())
    asyncio.create_task(update_orders())

    # 3. Start polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

