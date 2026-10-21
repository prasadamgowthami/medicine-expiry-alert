import os
import re
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

# Check if MySQL connector is installed
try:
    import mysql.connector
    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False

import sqlite3

SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), 'medicine_db.sqlite')

def _parse_sqlite_value(val):
    if isinstance(val, str):
        if re.match(r'^\d{4}-\d{2}-\d{2}$', val):
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except Exception:
                return val
        if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', val):
            try:
                return datetime.strptime(val.split('.')[0], '%Y-%m-%d %H:%M:%S')
            except Exception:
                return val
    return val

class SQLiteCursorAdapter:
    def __init__(self, cursor, dictionary=False):
        self._cursor = cursor
        self._dictionary = dictionary
        
    def execute(self, query, params=None):
        # Convert %s placeholders to SQLite ? placeholders
        query = query.replace('%s', '?')
        if params is not None:
            # Convert date/datetime objects to strings for SQLite storage
            clean_params = []
            for p in params:
                if isinstance(p, (datetime, date)):
                    clean_params.append(p.strftime('%Y-%m-%d'))
                else:
                    clean_params.append(p)
            return self._cursor.execute(query, tuple(clean_params))
        return self._cursor.execute(query)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._dictionary:
            return {k: _parse_sqlite_value(row[k]) for k in row.keys()}
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if self._dictionary:
            return [{k: _parse_sqlite_value(r[k]) for k in r.keys()} for r in rows]
        return rows

    def close(self):
        self._cursor.close()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

class SQLiteConnectionAdapter:
    def __init__(self, conn):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def cursor(self, dictionary=False):
        return SQLiteCursorAdapter(self._conn.cursor(), dictionary=dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

def get_db_connection():
    # 1. Try MySQL if configured
    if HAS_MYSQL and os.getenv("DB_HOST"):
        try:
            connection = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                user=os.getenv("DB_USER", "root"),
                password=os.getenv("DB_PASSWORD", ""),
                database=os.getenv("DB_NAME", "medicine_db"),
                connection_timeout=3
            )
            return connection
        except Exception:
            pass # Fall back to SQLite
            
    # 2. SQLite Fallback (Runs automatically on cloud platforms like Render)
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH, timeout=10)
        return SQLiteConnectionAdapter(conn)
    except Exception as err:
        print(f"Error connecting to SQLite fallback: {err}")
        return None

def init_db():
    """Ensure database schema is up-to-date across MySQL and SQLite."""
    conn = get_db_connection()
    if not conn:
        print("Database connection failed during init_db.")
        return False
        
    try:
        cursor = conn.cursor()
        
        # Check if this is an SQLite connection
        is_sqlite = isinstance(conn, SQLiteConnectionAdapter)
        
        if is_sqlite:
            # Initialize SQLite schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'pharmacist',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS medicines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    batch_number TEXT NOT NULL,
                    barcode TEXT,
                    manufacturer TEXT,
                    quantity INTEGER NOT NULL,
                    manufacturing_date DATE,
                    expiry_date DATE NOT NULL,
                    purchase_date DATE,
                    supplier_name TEXT,
                    minimum_stock INTEGER DEFAULT 10,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS disposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    medicine_name TEXT NOT NULL,
                    category TEXT,
                    batch_number TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    expiry_date DATE,
                    reason TEXT NOT NULL,
                    disposal_method TEXT NOT NULL,
                    witness_name TEXT,
                    notes TEXT,
                    disposed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dispenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    medicine_id INTEGER,
                    medicine_name TEXT NOT NULL,
                    batch_number TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    patient_or_dest TEXT,
                    dispensed_by INTEGER NOT NULL,
                    dispensed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dispensed_by) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            conn.commit()
        else:
            # MySQL Migrations
            cursor.execute("SHOW TABLES LIKE 'users'")
            if cursor.fetchone():
                cursor.execute("SHOW COLUMNS FROM users LIKE 'role'")
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'pharmacist'")
                    cursor.execute("UPDATE users SET role = 'admin' ORDER BY id ASC LIMIT 1")
                    conn.commit()

            cursor.execute("SHOW TABLES LIKE 'medicines'")
            if cursor.fetchone():
                cursor.execute("SHOW COLUMNS FROM medicines LIKE 'barcode'")
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE medicines ADD COLUMN barcode VARCHAR(100) AFTER batch_number")
                    conn.commit()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS disposals (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    medicine_name VARCHAR(150) NOT NULL,
                    category VARCHAR(100),
                    batch_number VARCHAR(100) NOT NULL,
                    quantity INT NOT NULL,
                    expiry_date DATE,
                    reason VARCHAR(100) NOT NULL,
                    disposal_method VARCHAR(100) NOT NULL,
                    witness_name VARCHAR(150),
                    notes TEXT,
                    disposed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dispenses (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    medicine_id INT,
                    medicine_name VARCHAR(150) NOT NULL,
                    batch_number VARCHAR(100) NOT NULL,
                    quantity INT NOT NULL,
                    patient_or_dest VARCHAR(150),
                    dispensed_by INT NOT NULL,
                    dispensed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dispensed_by) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            conn.commit()
            
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error during init_db: {e}")
        if conn:
            conn.close()
        return False
