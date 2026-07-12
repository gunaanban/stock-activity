import sqlite3
import uuid
from datetime import datetime

DB_FILE = "stocks.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create stocks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT,
            buy_amt REAL NOT NULL,
            sell_amt REAL NOT NULL,
            updated_at TEXT NOT NULL,
            last_price REAL,
            last_fetched_at TEXT,
            last_error TEXT
        )
    """)
    
    # Create settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

def dict_from_row(row):
    if row is None:
        return None
    return dict(row)

def get_stocks():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stocks ORDER BY symbol ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]

def get_stock(stock_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stocks WHERE id = ?", (stock_id,))
    row = cursor.fetchone()
    conn.close()
    return dict_from_row(row)

def add_stock(symbol, name, buy_amt, sell_amt, stock_id=None):
    if not stock_id:
        stock_id = str(uuid.uuid4())
    
    now_str = datetime.utcnow().isoformat() + "Z"
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO stocks (id, symbol, name, buy_amt, sell_amt, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (stock_id, symbol.upper().strip(), name, buy_amt, sell_amt, now_str))
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise e
    conn.close()
    return get_stock(stock_id)

def update_stock(stock_id, symbol, name, buy_amt, sell_amt):
    now_str = datetime.utcnow().isoformat() + "Z"
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE stocks
            SET symbol = ?, name = ?, buy_amt = ?, sell_amt = ?, updated_at = ?
            WHERE id = ?
        """, (symbol.upper().strip(), name, buy_amt, sell_amt, now_str, stock_id))
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise e
    conn.close()
    return get_stock(stock_id)

def delete_stock(stock_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stocks WHERE id = ?", (stock_id,))
    conn.commit()
    conn.close()
    return True

def update_stock_price(stock_id, price, fetched_at=None, error=None):
    if fetched_at is None:
        fetched_at = datetime.utcnow().isoformat() + "Z"
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE stocks
        SET last_price = ?, last_fetched_at = ?, last_error = ?
        WHERE id = ?
    """, (price, fetched_at, error, stock_id))
    conn.commit()
    conn.close()
    return get_stock(stock_id)

def get_setting(key, default=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['value']
    return default

def set_setting(key, value):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO settings (key, value)
        VALUES (?, ?)
    """, (key, str(value)))
    conn.commit()
    conn.close()
    return value

