import asyncio
import random
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiosqlite
import aiohttp

API_TOKEN = '7687205801:AAFwYLqVIzdFgIcAu9YmIurqT-3wnolwBa4'
ADMIN_ID = 7505715359
DB_PATH = "db.sqlite3"

BTC_ADDRESS = "bc1pret37zjwelrtusq7le5urw9w9ns5lj2t5smwxmq60pxckg5cflss87jr3x"
COINMARKETCAP_API_KEY = "b2abba61-203f-4ff8-8c07-75ad4279955a"

pending_payments = {}

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---------------------- DATABASE SETUP AND HELPERS ----------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                orders INTEGER DEFAULT 0,
                discount REAL DEFAULT 0,
                rank TEXT DEFAULT 'buyer'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS cities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS districts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city_id INTEGER,
                name TEXT,
                UNIQUE(city_id, name),
                FOREIGN KEY(city_id) REFERENCES cities(id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city_id INTEGER,
                district_id INTEGER,
                name TEXT,
                description TEXT,
                photo_id TEXT,
                price REAL,
                product_text TEXT,
                FOREIGN KEY(city_id) REFERENCES cities(id),
                FOREIGN KEY(district_id) REFERENCES districts(id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS product_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                item_text TEXT,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        ''')
        await db.commit()

async def get_user(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT * FROM users WHERE tg_id = ?', (tg_id,))
        user = await cur.fetchone()
        await cur.close()
        return user

async def add_user(tg_id: int, rank='buyer'):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO users (tg_id, rank) VALUES (?, ?)', (tg_id, rank))
            await db.commit()
        except aiosqlite.IntegrityError:
            pass

async def update_rank(tg_id: int, rank: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET rank = ? WHERE tg_id = ?', (rank, tg_id))
        await db.commit()

async def update_user_orders_and_discount(tg_id: int, plus=1):
    async with aiosqlite.connect(DB_PATH) as db:
        # Обновить количество заказов
        await db.execute('UPDATE users SET orders = orders + ? WHERE tg_id = ?', (plus, tg_id))
        # Получить новое количество заказов
        cur = await db.execute('SELECT orders FROM users WHERE tg_id = ?', (tg_id,))
        orders = (await cur.fetchone())[0]
        # Высчитать скидку
        discount = 0
        if orders >= 200:
            discount = 15
        elif orders >= 50:
            discount = 10
        elif orders >= 20:
            discount = 5
        elif orders >= 10:
            discount = 2
        await db.execute('UPDATE users SET discount = ? WHERE tg_id = ?', (discount, tg_id))
        await db.commit()
        return orders, discount

async def get_staff():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT tg_id, rank FROM users WHERE rank != "buyer"')
        staff = await cur.fetchall()
        await cur.close()
        return staff

async def add_city(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO cities (name) VALUES (?)', (name,))
            await db.commit()
        except aiosqlite.IntegrityError:
            return False
        return True

async def delete_city(city_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # Удаляем product_items для товаров города
        await db.execute('DELETE FROM product_items WHERE product_id IN (SELECT id FROM products WHERE city_id=?)', (city_id,))
        # Удаляем товары города
        await db.execute('DELETE FROM products WHERE city_id=?', (city_id,))
        # Удаляем районы города
        await db.execute('DELETE FROM districts WHERE city_id=?', (city_id,))
        # Удаляем сам город
        await db.execute('DELETE FROM cities WHERE id=?', (city_id,))
        await db.commit()

async def get_cities():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT id, name FROM cities')
        data = await cur.fetchall()
        await cur.close()
        return data

async def add_district(city_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO districts (city_id, name) VALUES (?, ?)', (city_id, name))
            await db.commit()
        except aiosqlite.IntegrityError:
            return False
        return True

async def get_districts(city_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT id, name FROM districts WHERE city_id = ?', (city_id,))
        data = await cur.fetchall()
        await cur.close()
        return data

async def add_product(city_id, district_id, name, description, photo_id, price, product_text):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO products (city_id, district_id, name, description, photo_id, price, product_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (city_id, district_id, name, description, photo_id, price, product_text))
        await db.commit()

async def delete_product(product_id: int):
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM product_items WHERE product_id = ?', (product_id,))
        await db.execute('DELETE FROM products WHERE id = ?', (product_id,))
        await db.commit()
        
async def get_products(city_id, district_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('''
            SELECT id, name, price FROM products
            WHERE city_id = ? AND district_id = ?
        ''', (city_id, district_id))
        data = await cur.fetchall()
        await cur.close()
        return data

async def get_product_full(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('''
            SELECT p.id, p.name, p.description, p.photo_id, p.price, p.product_text, c.name, d.name
            FROM products p
            JOIN cities c ON p.city_id = c.id
            JOIN districts d ON p.district_id = d.id
            WHERE p.id = ?
        ''', (product_id,))
        data = await cur.fetchone()
        await cur.close()
        return data

# Экземпляры товара (item-коды)
async def add_product_items(product_id, items):
    async with aiosqlite.connect(DB_PATH) as db:
        for item in items:
            await db.execute("INSERT INTO product_items (product_id, item_text) VALUES (?, ?)", (product_id, item))
        await db.commit()

async def get_and_delete_product_item(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT id, item_text FROM product_items WHERE product_id=? LIMIT 1', (product_id,))
        row = await cur.fetchone()
        if not row:
            return None
        item_id, item_text = row
        await db.execute('DELETE FROM product_items WHERE id=?', (item_id,))
        await db.commit()
        return item_text

async def has_items(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT COUNT(*) FROM product_items WHERE product_id=?', (product_id,))
        count = (await cur.fetchone())[0]
        return count > 0

async def items_count(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT COUNT(*) FROM product_items WHERE product_id=?', (product_id,))
        count = (await cur.fetchone())[0]
        return count

# ---------------------- FSM STATES ----------------------

class AddCity(StatesGroup):
    waiting_for_city_name = State()

class AddDistrict(StatesGroup):
    waiting_for_city = State()
    waiting_for_district_name = State()

class AddProduct(StatesGroup):
    waiting_for_city = State()
    waiting_for_district = State()
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_photo = State()
    waiting_for_price = State()
    waiting_for_product_text = State()

class BuyProduct(StatesGroup):
    waiting_for_payment_method = State()
    waiting_for_payment = State()

class StaffManage(StatesGroup):
    waiting_for_action = State()
    waiting_for_id = State()

# ---------------------- KEYBOARDS ----------------------

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text='🛍️ Товары'), KeyboardButton(text='👤 Личный кабинет')],
        [KeyboardButton(text='⭐ Отзывы'), KeyboardButton(text='📜 Правила')],
        [KeyboardButton(text='💬 Поддержка'), KeyboardButton(text='🌍 Язык')]
    ],
    resize_keyboard=True
)

def admin_panel():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='➕ Добавить товар'), KeyboardButton(text='➖ Удалить товар')],
            [KeyboardButton(text='🏙️ Добавить город'), KeyboardButton(text='🌆 Добавить район')],
            [KeyboardButton(text='🗑️ Удалить город'), KeyboardButton(text='🧑‍💼 Управление персоналом')],
            [KeyboardButton(text='⬅️ Назад')]
        ],
        resize_keyboard=True
    )

def worker_panel():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='➕ Добавить товар')],
            [KeyboardButton(text='⬅️ Назад')]
        ],
        resize_keyboard=True
    )

def staff_manage_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Назначить администратора", callback_data="staff_set_admin")],
        [InlineKeyboardButton(text="👷 Назначить работника", callback_data="staff_set_worker")],
        [InlineKeyboardButton(text="⬇️ Понизить до покупателя", callback_data="staff_set_buyer")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="staff_show_users")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="staff_back")]
    ])

# ---------------------- START AND PROFILE ----------------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    user = await get_user(tg_id)
    if not user:
        if tg_id == ADMIN_ID:
            await add_user(tg_id, "admin")
        else:
            await add_user(tg_id)
    await message.answer(
        "👋 Добро пожаловать!\nВыберите действие из меню ниже:",
        reply_markup=main_menu
    )

@dp.message(F.text == "👤 Личный кабинет")
async def profile(message: types.Message):
    tg_id = message.from_user.id
    user = await get_user(tg_id)
    if not user:
        await message.answer("⛔ Пользователь не найден. Напишите /start.")
        return

    uid, _, orders, discount, rank = user
    rank_ru = {"admin": "Администратор 👑", "worker": "Работник 👷", "buyer": "Покупатель 🛒"}.get(rank, rank)
    markup = None
    if rank == "admin":
        markup = admin_panel()
    elif rank == "worker":
        markup = worker_panel()
    else:
        markup = main_menu

    text = (
        f"🆔 Ваш айди: <code>{tg_id}</code>\n"
        f"📦 Ваше количество заказов: <b>{orders}</b>\n"
        f"💸 Ваша персональная скидка: <b>{discount}%</b>\n"
        f"🎖️ Ваш ранг: <b>{rank_ru}</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=markup)

# ---------------------- STAFF MANAGEMENT INLINE FSM ----------------------

@dp.message(F.text == "🧑‍💼 Управление персоналом")
async def staff_manage(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user[4] != "admin":
        await message.answer("⛔ Недостаточно прав.")
        return
    await message.answer("🧑‍💼 Управление персоналом:", reply_markup=staff_manage_inline())
    await state.set_state(StaffManage.waiting_for_action)

@dp.callback_query(F.data.in_(["staff_set_admin", "staff_set_worker", "staff_set_buyer"]))
async def staff_manage_choose_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data
    action_map = {
        "staff_set_admin": "администратором",
        "staff_set_worker": "работником",
        "staff_set_buyer": "покупателем"
    }
    await state.update_data(staff_action=action)
    await callback.message.answer(f"Введите TG ID пользователя, которого хотите назначить {action_map[action]}:")
    await state.set_state(StaffManage.waiting_for_id)
    await callback.answer()

@dp.callback_query(F.data == "staff_back")
async def staff_manage_back(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⬅️ Назад в админ-панель.", reply_markup=admin_panel())
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "staff_show_users")
async def staff_show_users(callback: types.CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    user = await get_user(tg_id)
    if not user or user[4] != "admin":
        await callback.message.answer("⛔ Недостаточно прав.")
        await callback.answer()
        return
    staff = await get_staff()
    if not staff:
        await callback.message.answer("Нет пользователей с рангом выше покупателя.")
        await callback.answer()
        return
    lines = ["<b>Список пользователей с рангом выше покупателя:</b>"]
    for uid, rank in staff:
        rank_ru = {"admin": "Администратор 👑", "worker": "Работник 👷"}.get(rank, rank)
        lines.append(f"ID: <code>{uid}</code> | Ранг: <b>{rank_ru}</b>")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()

@dp.message(StaffManage.waiting_for_id)
async def staff_manage_set_id(message: types.Message, state: FSMContext):
    data = await state.get_data()
    action = data.get("staff_action")
    target_rank = {
        "staff_set_admin": "admin",
        "staff_set_worker": "worker",
        "staff_set_buyer": "buyer"
    }[action]
    try:
        target_id = int(message.text.strip())
    except Exception:
        await message.answer("Некорректный формат TG ID. Попробуйте ещё раз.")
        return
    user = await get_user(message.from_user.id)
    if not user or user[4] != "admin":
        await message.answer("⛔ Недостаточно прав.")
        return
    if target_id == message.from_user.id and target_rank == "buyer":
        await message.answer("⛔ Нельзя понизить самого себя!")
        return
    target_user = await get_user(target_id)
    if not target_user:
        await message.answer("Пользователь с таким ID не найден.")
        return
    await update_rank(target_id, target_rank)
    rank_ru = {"admin": "Администратор 👑", "worker": "Работник 👷", "buyer": "Покупатель 🛒"}[target_rank]
    await message.answer(f"✅ Пользователь <code>{target_id}</code> теперь {rank_ru}.", parse_mode="HTML", reply_markup=admin_panel())
    await state.clear()

# ---------------------- ADD CITY / DISTRICT / PRODUCT FSM ----------------------

@dp.message(F.text == "🏙️ Добавить город")
async def add_city_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user[4] != "admin":
        await message.answer("⛔ Недостаточно прав.")
        return
    await message.answer("🏙️ Введите название города:")
    await state.set_state(AddCity.waiting_for_city_name)

@dp.message(AddCity.waiting_for_city_name)
async def add_city_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("⛔ Название не должно быть пустым.")
        return
    ok = await add_city(name)
    if ok:
        await message.answer("🏙️ Город добавлен!", reply_markup=admin_panel())
    else:
        await message.answer("⛔ Такой город уже есть.", reply_markup=admin_panel())
    await state.clear()

@dp.message(F.text == "🌆 Добавить район")
async def add_district_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user[4] != "admin":
        await message.answer("⛔ Недостаточно прав.")
        return
    cities = await get_cities()
    if not cities:
        await message.answer("Сначала добавьте город.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"adddistrict_city_{cid}")] for cid, name in cities]
    )
    await message.answer("🏙️ Выберите город для района:", reply_markup=kb)

@dp.callback_query(F.data.startswith("adddistrict_city_"))
async def add_district_choose_city(callback: types.CallbackQuery, state: FSMContext):
    city_id = int(callback.data.split("_")[-1])
    await state.update_data(city_id=city_id)
    await callback.message.answer("🌆 Введите название района:")
    await state.set_state(AddDistrict.waiting_for_district_name)
    await callback.answer()

@dp.message(AddDistrict.waiting_for_district_name)
async def add_district_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    city_id = data.get("city_id")
    name = message.text.strip()
    if not name:
        await message.answer("⛔ Название не должно быть пустым.")
        return
    ok = await add_district(city_id, name)
    if ok:
        await message.answer("🌆 Район добавлен!", reply_markup=admin_panel())
    else:
        await message.answer("⛔ Такой район уже есть.", reply_markup=admin_panel())
    await state.clear()

@dp.message(F.text.in_(["➕ Добавить товар", "Добавить товар"]))
async def add_product_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user[4] not in ("admin", "worker"):
        await message.answer("⛔ Недостаточно прав.")
        return
    cities = await get_cities()
    if not cities:
        await message.answer("Сначала добавьте город.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"addprod_city_{cid}")] for cid, name in cities]
    )
    await message.answer("🏙️ Выберите город для товара:", reply_markup=kb)

@dp.callback_query(F.data.startswith("addprod_city_"))
async def add_product_choose_city(callback: types.CallbackQuery, state: FSMContext):
    city_id = int(callback.data.split("_")[-1])
    await state.update_data(city_id=city_id)
    districts = await get_districts(city_id)
    if not districts:
        await callback.message.answer("В этом городе нет районов. Добавьте район.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"addprod_district_{did}")] for did, name in districts]
    )
    await callback.message.answer("🌆 Выберите район для товара:", reply_markup=kb)
    await callback.answer()

@dp.message(F.text == "🗑️ Удалить город")
async def delete_city_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user[4] != "admin":
        await message.answer("⛔ Недостаточно прав.")
        return
    cities = await get_cities()
    if not cities:
        await message.answer("Нет доступных городов для удаления.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"delete_city_{cid}")] for cid, name in cities]
    )
    await message.answer("Выберите город для удаления:", reply_markup=kb)

@dp.callback_query(F.data.startswith("addprod_district_"))
async def add_product_choose_district(callback: types.CallbackQuery, state: FSMContext):
    district_id = int(callback.data.split("_")[-1])
    await state.update_data(district_id=district_id)
    await callback.message.answer("🛒 Введите название товара:")
    await state.set_state(AddProduct.waiting_for_name)
    await callback.answer()

@dp.message(AddProduct.waiting_for_name)
async def add_product_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📝 Введите описание товара:")
    await state.set_state(AddProduct.waiting_for_description)

@dp.message(AddProduct.waiting_for_description)
async def add_product_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("📸 Отправьте фото товара (как фото):")
    await state.set_state(AddProduct.waiting_for_photo)

@dp.message(AddProduct.waiting_for_photo, F.photo)
async def add_product_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer("💵 Введите цену товара (только число, $USD):")
    await state.set_state(AddProduct.waiting_for_price)

@dp.message(AddProduct.waiting_for_photo)
async def add_product_photo_fail(message: types.Message, state: FSMContext):
    await message.answer("⛔ Пожалуйста, отправьте изображение как фото.")

@dp.message(AddProduct.waiting_for_price)
async def add_product_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except Exception:
        await message.answer("⛔ Введите корректную цену.")
        return
    await state.update_data(price=price)
    await message.answer("💼 Введите список экземпляров товара (каждый с новой строки):")
    await state.set_state(AddProduct.waiting_for_product_text)

@dp.message(AddProduct.waiting_for_product_text)
async def add_product_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await add_product(
        data["city_id"],
        data["district_id"],
        data["name"],
        data["description"],
        data["photo_id"],
        data["price"],
        ""  # product_text больше не нужен для продажи
    )
    # Получаем только что созданный product_id
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM products WHERE name = ? ORDER BY id DESC LIMIT 1",
            (data["name"],)
        )
        product_row = await cur.fetchone()
        product_id = product_row[0]
        # Сохраняем экземпляры
        items = [line.strip() for line in message.text.split("\n") if line.strip()]
        for item in items:
            await db.execute("INSERT INTO product_items (product_id, item_text) VALUES (?, ?)", (product_id, item))
        await db.commit()
    await message.answer(f"✅ Товар добавлен!\nЗагружено {len(items)} экземпляров.")
    await state.clear()

@dp.message(F.text == "➖ Удалить товар")
async def start_delete_product(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user or user[4] != "admin":
        await message.answer("⛔ Недостаточно прав.")
        return
    cities = await get_cities()
    if not cities:
        await message.answer("Нет городов.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"delprod_city_{cid}")] for cid, name in cities]
    )
    await message.answer("Выберите город:", reply_markup=kb)

# ---------------------- ТОВАРЫ И ПОКУПКА ----------------------

@dp.message(F.text == "🛍️ Товары")
async def show_cities(message: types.Message):
    cities = await get_cities()
    if not cities:
        await message.answer("🔔Нет доступных кладов в данный момент! Следите за пополнениями!🔔")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"🏙️ {name}", callback_data=f"show_city_{cid}")] for cid, name in cities]
    )
    await message.answer("🏙️ Выберите город:", reply_markup=kb)

@dp.callback_query(F.data.startswith("show_city_"))
async def show_city(callback: types.CallbackQuery):
    city_id = int(callback.data.split("_")[-1])
    districts = await get_districts(city_id)
    if not districts:
        await callback.message.answer("🌆 В этом городе нет районов.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"🌆 {name}", callback_data=f"show_district_{city_id}_{did}")] for did, name in districts]
    )
    await callback.message.answer("🌆 Выберите район:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("show_district_"))
async def show_district(callback: types.CallbackQuery):
    _, _, city_id, district_id = callback.data.split("_")
    city_id, district_id = int(city_id), int(district_id)
    products = await get_products(city_id, district_id)
    if not products:
        await callback.message.answer("❌ В этом районе кладов нет.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text=f"{name} (${price}) [{await items_count(pid)} шт.]", 
            callback_data=f"show_product_{pid}")] for pid, name, price in products]
    )
    await callback.message.answer("📦 Выберите клад:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("show_product_"))
async def show_product(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[-1])
    product = await get_product_full(product_id)
    if not product:
        await callback.message.answer("❌ Клад не найден.")
        return
    pid, name, description, photo_id, price, product_text, city, district = product
    count = await items_count(product_id)
    text = (
        f"🛒 <b>{name}</b>\n"
        f"🏙️ <b>Город:</b> {city}\n"
        f"🌆 <b>Район:</b> {district}\n"
        f"💰 <b>Цена:</b> {price} $USD\n"
        f"{description}"
    )
    user = await get_user(callback.from_user.id)
    buy_buttons = []
    if count > 0:
        buy_buttons.append([InlineKeyboardButton(text="💸 Купить", callback_data=f"buy_{pid}")])
    if user and user[4] == "admin":
        buy_buttons.append([InlineKeyboardButton(text="🧪 Подделать покупку (админ)", callback_data=f"emulate_buy_{pid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buy_buttons)
    await callback.message.answer_photo(photo_id, caption=text, parse_mode="HTML", reply_markup=kb)
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data.startswith("emulate_buy_"))
async def emulate_buy(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if not user or user[4] != "admin":
        await callback.message.answer("⛔ Недостаточно прав для подделки покупки.")
        await callback.answer()
        return

    product_id = int(callback.data.split("_")[-1])
    item = await get_and_delete_product_item(product_id)
    if not item:
        await callback.message.answer("❌ Нет доступных экземпляров товара!")
        await callback.answer()
        return

    product = await get_product_full(product_id)
    if not product:
        await callback.message.answer("❌ Клад не найден.")
        await callback.answer()
        return

    pid, name, description, photo_id, price, product_text, city, district = product
    # Эмулируем заказ
    await update_user_orders_and_discount(callback.from_user.id, plus=1)
    await callback.message.answer(
        f"🧪 <b>Подделка покупки</b>\n\n"
        f"🛒 <b>{name}</b>\n"
        f"🏙️ <b>Город:</b> {city}\n"
        f"🌆 <b>Район:</b> {district}\n"
        f"💰 <b>Цена:</b> {price} $USD\n\n"
        f"✅ Благодарим за Ваше доверие! Мы - лучшие в своем деле, не забудьте оставить положительный отзыв, удачного трипа! Вот ваш товар:\n\n"
        f"{item}\n\n"
        f"Спасибо за покупку! 🎉",
        parse_mode="HTML"
    )
    await callback.answer("Покупка подделана!")

@dp.callback_query(F.data.startswith("delete_city_"))
async def delete_city_confirm(callback: types.CallbackQuery):
    city_id = int(callback.data.split("_")[-1])
    await delete_city(city_id)
    await callback.message.answer("Город успешно удалён!", reply_markup=admin_panel())
    await callback.answer("Город удалён")

@dp.callback_query(F.data == "product_delete")
async def product_delete_inline(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if not user or user[4] != "admin":
        await callback.message.answer("⛔ Недостаточно прав.")
        await callback.answer()
        return
    cities = await get_cities()
    if not cities:
        await callback.message.answer("Нет городов.")
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"delprod_city_{cid}")] for cid, name in cities]
    )
    await callback.message.answer("Выберите город:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("delprod_city_"))
async def delprod_choose_city(callback: CallbackQuery, state: FSMContext):
    city_id = int(callback.data.split("_")[-1])
    districts = await get_districts(city_id)
    if not districts:
        await callback.message.answer("В этом городе нет районов.")
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=name, callback_data=f"delprod_district_{city_id}_{did}")] for did, name in districts]
    )
    await callback.message.answer("Выберите район:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("delprod_district_"))
async def delprod_choose_district(callback: CallbackQuery, state: FSMContext):
    _, _, city_id, district_id = callback.data.split("_")
    city_id, district_id = int(city_id), int(district_id)
    products = await get_products(city_id, district_id)
    if not products:
        await callback.message.answer("В этом районе товаров нет.")
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"{name} (${price})", callback_data=f"delprod_product_{pid}")] for pid, name, price in products]
    )
    await callback.message.answer("Выберите товар для удаления:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("delprod_product_"))
async def delprod_delete(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[-1])
    await delete_product(product_id)
    await callback.message.answer("✅ Товар удалён.", reply_markup=admin_panel())
    await callback.answer()

# ---------------------- BTC PAYMENT FSM ----------------------

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product_choose_method(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[-1])
    await state.update_data(product_id=product_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ BTC", callback_data="pay_btc")],
        [InlineKeyboardButton(text="🪙 USDT (скоро)", callback_data="pay_usdt")],
        [InlineKeyboardButton(text="🕵️ Monero (скоро)", callback_data="pay_xmr")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_product")]
    ])
    await callback.message.answer("💳 Выберите способ оплаты:", reply_markup=kb)
    await state.set_state(BuyProduct.waiting_for_payment_method)
    await callback.answer()

@dp.callback_query(F.data == "pay_usdt")
async def pay_usdt_soon(callback: types.CallbackQuery):
    await callback.message.answer("🪙 Оплата через USDT скоро будет готова 😉")
    await callback.answer()

@dp.callback_query(F.data == "pay_xmr")
async def pay_xmr_soon(callback: types.CallbackQuery):
    await callback.message.answer("🕵️ Оплата через Monero скоро будет готова 😉")
    await callback.answer()

@dp.callback_query(F.data == "back_to_product")
async def back_to_product(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("product_id"):
        await callback.answer()
        return
    product = await get_product_full(data["product_id"])
    if not product:
        await callback.message.answer("❌ Товар не найден.")
        return
    pid, name, description, photo_id, price, product_text, city, district = product
    count = await items_count(pid)
    text = (
        f"🛒 <b>{name}</b>\n"
        f"🏙️ <b>Город:</b> {city}\n"
        f"🌆 <b>Район:</b> {district}\n"
        f"💰 <b>Цена:</b> {price} $USD\n"
        f"📦 <b>В наличии:</b> {count} шт.\n\n"
        f"{description}"
    )
    user = await get_user(callback.from_user.id)
    buy_buttons = []
    if count > 0:
        buy_buttons.append([InlineKeyboardButton(text="💸 Купить", callback_data=f"buy_{pid}")])
    if user and user[4] == "admin":
        buy_buttons.append([InlineKeyboardButton(text="🧪 Эмулировать покупку (админ)", callback_data=f"emulate_buy_{pid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buy_buttons)
    await callback.message.answer_photo(photo_id, caption=text, parse_mode="HTML", reply_markup=kb)
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "pay_btc")
async def pay_btc(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    data = await state.get_data()
    product_id = data.get("product_id")
    product = await get_product_full(product_id)
    if not product:
        await callback.message.answer("❌ Товар не найден.")
        return
    pid, name, description, photo_id, price_usd, product_text, city, district = product

    # Скидка
    discount = user[3] if user else 0
    price_usd_discounted = round(price_usd - (price_usd * discount / 100), 2)

    async with aiohttp.ClientSession() as session:
        headers = {"X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}
        async with session.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol=BTC", headers=headers) as resp:
            data_resp = await resp.json()
            btc_price = float(data_resp["data"]["BTC"]["quote"]["USD"]["price"])

    unique_usd = price_usd_discounted + round(random.uniform(0.01, 2.00), 2)
    unique_btc = round(unique_usd / btc_price, 8)
    unique_btc_str = f"{unique_btc:.8f}"

    payment_id = f"{user_id}:{product_id}"
    pending_payments[payment_id] = {
        "btc": unique_btc,
        "btc_str": unique_btc_str,
        "expire": time.time() + 20 * 60,
        "product_text": product_text,
        "usd": unique_usd
    }

    payment_info = (
        f"🛒 <b>{name}</b>\n"
        f"🏙️ Город: {city}\n"
        f"🌆 Район: {district}\n"
        f"💵 Цена: {price_usd} $USD\n"
        f"💸 Ваша цена со скидкой: <b>{price_usd_discounted} USD</b> (скидка {discount}%)\n\n"
        f"⚡ <b>Для оплаты отправьте точно <code>{unique_btc_str} BTC</code> на адрес:</b>\n"
        f"<code>{BTC_ADDRESS}</code>\n\n"
        f"❗ Сумма уникальна, платеж будет засчитан только при поступлении <b>ровно такой суммы</b> в течение 20 минут.\n"
        f"⏰ После оплаты нажмите кнопку ниже для проверки."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Проверить оплату", callback_data="check_btc_payment")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_product")]
    ])
    await callback.message.answer(payment_info, parse_mode="HTML", reply_markup=kb)
    await state.set_state(BuyProduct.waiting_for_payment)
    await callback.answer()

@dp.callback_query(F.data == "check_btc_payment")
async def check_btc_payment(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    product_id = data.get("product_id")
    payment_id = f"{user_id}:{product_id}"

    payment = pending_payments.get(payment_id)
    if not payment:
        await callback.message.answer("⌛ Сессия оплаты истекла или не найдена.")
        await state.clear()
        await callback.answer()
        return

    if time.time() > payment["expire"]:
        await callback.message.answer("⏰ Время ожидания оплаты истекло. Попробуйте совершить покупку снова.")
        pending_payments.pop(payment_id, None)
        await state.clear()
        await callback.answer()
        return

    btc_addr = BTC_ADDRESS
    btc_amount = payment["btc"]
    btc_amount_str = payment["btc_str"]

    # --- Проверка оплаты через Blockchain.com API ---
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://blockchain.info/rawaddr/{btc_addr}?limit=50") as resp:
            if resp.status != 200:
                await callback.message.answer("❗ Ошибка при проверке оплаты, попробуйте позже.")
                await callback.answer()
                return
            data_resp = await resp.json()
    txs = data_resp.get("txs", [])
    found = False
    for tx in txs:
        for out in tx.get("out", []):
            if out.get("addr", "") == btc_addr:
                value_btc = round(out.get("value", 0) / 1e8, 8)
                if abs(value_btc - btc_amount) < 1e-8:
                    found = True
                    break
        if found:
            break

    if found:
        # Выдаём экземпляр
        item = await get_and_delete_product_item(product_id)
        if not item:
            await callback.message.answer("❌ Увы, товар закончился!")
            await state.clear()
            return
        await update_user_orders_and_discount(user_id, plus=1)
        await callback.message.answer(
        f"🧪 <b>Подделка покупки</b>\n\n"
        f"🛒 <b>{name}</b>\n"
        f"🏙️ <b>Город:</b> {city}\n"
        f"🌆 <b>Район:</b> {district}\n"
        f"💰 <b>Цена:</b> {price} $USD\n\n"
        f"✅ Благодарим за Ваше доверие! Мы - лучшие в своем деле, не забудьте оставить положительный отзыв, удачного трипа! Вот ваш товар:\n\n"
        f"{item}\n\n"
        f"Спасибо за покупку! 🎉",
        parse_mode="HTML"
    )
        pending_payments.pop(payment_id, None)
        await state.clear()
    else:
        await callback.message.answer("❌ Платеж не найден!\nУбедитесь, что вы отправили <b>ровно</b> указанную сумму и попробуйте ещё раз.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Проверить оплату", callback_data="check_btc_payment")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_product")]
        ]))
    await callback.answer()

# ---------------------- МЕЛКИЕ ХЕНДЛЕРЫ ----------------------

@dp.message(F.text == "⭐ Отзывы")
async def otzyvy_handler(message: types.Message):
    await message.answer(
        "В данном телеграмм-канале Вы можете ознакомиться с пользователями, которые оставили отзыв :)\n"
        "Вы можете быть одним из них!\n"
        "t.me/otzyvy_zdes"
    )

@dp.message(F.text == "💬 Поддержка")
async def support_handler(message: types.Message):
    await message.answer(
        "В случае возникновения проблем с заказом, либо проблем с оплатой Вы всегда можете обратиться к нашему оператору!\n"
        "@ImMathewBTW"
    )

@dp.message(F.text == "📜 Правила")
async def rules_handler(message: types.Message):
    await message.answer(
        "*Здесь будут расписаны правила магазина*"
    )

@dp.message(F.text == "⬅️ Назад")
async def back_to_menu(message: types.Message):
    await message.answer("🔙 Вы вернулись в главное меню.", reply_markup=main_menu)

# ---------------------- MAIN ----------------------

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
