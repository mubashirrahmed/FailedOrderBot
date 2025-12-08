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
# PLAYWRIGHT ORDER UPDATER
# =====================================================
async def update_orders():
    while True:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                # Login
                await page.goto("https://korkortsfoton.se/wp-login.php?loggedout=true&wp_lang=sv_SE")
                await page.fill("input[name='log']", os.getenv("WP_USER", "prijnen6@gmail.com"))
                await page.fill("input[name='pwd']", os.getenv("WP_PASS", "prijnen6@gmail.com"))
                await page.click("input#wp-submit")

                # Navigate to orders page
                await page.goto("https://korkortsfoton.se/wp-admin/admin.php?page=wc-orders&status=wc-processing", wait_until="networkidle", timeout=90000)
                
                try:
                    await page.wait_for_selector("table.wp-list-table", timeout=90000)
                except:
                    try:
                        await page.wait_for_selector("table.widefat", timeout=30000)
                    except:
                        await page.screenshot(path="debug_orders_page.png")
                        await bot.send_message(CHAT_ID, "⚠️ Could not load orders page")
                        return

                # Collect orders with "Behandlas" status
                all_rows = await page.query_selector_all("table.wp-list-table tbody tr") or \
                           await page.query_selector_all("table.widefat tbody tr")
                behandlas_orders = []

                for row in all_rows:
                    status_cell = await row.query_selector("td.column-order_status mark span")
                    status_text = await status_cell.inner_text() if status_cell else ""
                    if "Behandlas" in status_text:
                        link = await row.query_selector("td.column-order_number a")
                        href = await link.get_attribute("href") if link else None
                        order_id = re.search(r'(?:post=|\bid=)([\d]+)', href).group(1) if href else None
                        if order_id:
                            behandlas_orders.append((order_id, href))

                # Process each order
                failed_orders = []

                for oid, href in behandlas_orders:
                    new_page = await context.new_page()
                    await new_page.goto(href, wait_until="domcontentloaded")
                    content = await new_page.inner_text("body")
                    if "ditt foto är nu redigerat" in content.lower():
                        button = await new_page.query_selector("#woocommerce-order-actions div.inside ul li:nth-child(2) button")
                        if button:
                            await button.click()
                            await asyncio.sleep(1)
                        else:
                            failed_orders.append(oid)
                    else:
                        failed_orders.append(oid)
                    await new_page.close()

                if failed_orders:
                    await bot.send_message(CHAT_ID, f"⚠️ Failed orders: {', '.join(failed_orders)}")
                else:
                    await bot.send_message(CHAT_ID, "✅ All processing orders updated successfully.")

                await browser.close()

        except Exception as e:
            await bot.send_message(CHAT_ID, f"❌ Order updater error: {e}")

        await asyncio.sleep(60)  # repeat every 60 seconds

# =====================================================
# TELEGRAM BOT HANDLERS (example start)
# =====================================================
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("👋 Bot is running. Playwright order updater is active in background.")

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
# MAIN
# =====================================================
async def main():
    asyncio.create_task(start_web_app())
    asyncio.create_task(update_orders())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
