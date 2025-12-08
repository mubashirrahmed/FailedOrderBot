import os
import re
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from playwright.async_api import async_playwright

# =====================================================
# 🔐 CONFIG
# =====================================================
TOKEN = os.getenv("BOT_TOKEN", "8207015657:AAFN50YiVxgugKx2qPZquNK5dGFsDOn8t6g")
CHAT_ID = int(os.getenv("CHAT_ID", 7831605046))

bot = Bot(TOKEN)
dp = Dispatcher()

# =====================================================
# ENSURE PLAYWRIGHT BROWSERS ON RENDER
# =====================================================
async def install_playwright_browsers():
    if os.getenv("RENDER"):  # Only run on Render
        print("Installing Playwright browsers on Render...")
        os.system("playwright install --with-deps chromium")
        print("Playwright browsers installed.")
    else:
        print("Not on Render – skipping forced install.")


# =====================================================
# ORDER UPDATER – ONLY NOTIFIES ON FAILURE
# =====================================================
async def update_orders():
    await asyncio.sleep(10)  # Wait a bit for bot to start

    while True:
        failed_orders = []
        has_error = False
        error_msg = ""

        try:
            async with async_playwright() as p:
                # This will auto-download if missing (fallback safety)
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                # Login
                await page.goto("https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE")
                await page.fill("input[name='log']", os.getenv("WP_USER"))
                await page.fill("input[name='pwd']", os.getenv("WP_PASS"))
                await page.click("input#wp-submit")
                await page.wait_for_load_state("networkidle")

                # Go to processing orders
                await page.goto(
                    "https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing",
                    wait_until="networkidle",
                    timeout=90000
                )

                # Wait for table
                try:
                    await page.wait_for_selector("table.wp-list-table, table.widefat", timeout=30000)
                except:
                    await page.screenshot(path="/tmp/debug.png")
                    await bot.send_document(CHAT_ID, types.InputFile("/tmp/debug.png"),
                                           caption="Could not find orders table")
                    has_error = True

                # Find "Behandlas" orders
                rows = await page.query_selector_all("table.wp-list-table tbody tr, table.widefat tbody tr")
                behandlas_orders = []

                for row in rows:
                    status_el = await row.query_selector("td.column-order_status mark span, td.order_status")
                    if not status_el:
                        continue
                    status_text = await status_el.inner_text()
                    if "Behandlas" in status_text or "Processing" in status_text:
                        link_el = await row.query_selector("td.column-order_number a")
                        href = await link_el.get_attribute("href") if link_el else None
                        order_id = re.search(r'id=(\d+)|post=(\d+)', href or "").group(1) or \
                                   re.search(r'id=(\d+)|post=(\d+)', href or "").group(2)
                        if order_id:
                            behandlas_orders.append((order_id, href))

                # Process each order
                for order_id, url in behandlas_orders:
                    try:
                        order_page = await context.new_page()
                        await order_page.goto(url, wait_until="domcontentloaded", timeout=60000)

                        content = (await order_page.content()).lower()
                        if "ditt foto är nu redigerat" in content or "your photo has now been edited" in content:
                            # Click "Markera som klar" button
                            button = await order_page.query_selector(
                                "#woocommerce-order-actions button.woocommerce-order-actions__button-complete, "
                                "#order_status option[value='wc-completed']"
                            )
                            if button:
                                await button.click()
                                await asyncio.sleep(2)
                                await order_page.close()
                            else:
                                failed_orders.append(order_id)
                        else:
                            failed_orders.append(order_id)
                        await order_page.close()
                    except Exception as e:
                        failed_orders.append(order_id)
                        print(f"Error processing order {order_id}: {e}")

                await browser.close()

        except Exception as e:
            has_error = True
            error_msg = str(e)
            print(f"Critical error in updater: {e}")

        # NOTIFY ONLY IF SOMETHING WENT WRONG
        if failed_orders:
            await bot.send_message(
                CHAT_ID,
                f"Failed to complete {len(failed_orders)} order(s):\n"
                f"`#{', #'.join(failed_orders)}`",
                parse_mode="Markdown"
            )

        if has_error:
            await bot.send_message(CHAT_ID, f"Order updater crashed:\n`{error_msg}`", parse_mode="Markdown")

        # No message if everything worked perfectly

        await asyncio.sleep(60)  # Check every 60 seconds


# =====================================================
# BOT COMMANDS
# =====================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Bot is running!\n\n"
        "I will only message you if an order fails to update.\n"
        "No news = good news"
    )


# =====================================================
# DUMMY WEB SERVER FOR RENDER
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
    print(f"Web server running on port {os.getenv('PORT', 10000)}")


# =====================================================
# MAIN
# =====================================================
async def main():
    # Critical: Install browsers on Render
    await install_playwright_browsers()

    # Start background tasks
    asyncio.create_task(start_web_server())
    asyncio.create_task(update_orders())

    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
