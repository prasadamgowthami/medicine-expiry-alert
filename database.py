import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "medicine_db")
        )
        return connection
    except mysql.connector.Error as err:
        print(f"Error connecting to database: {err}")
        return None

def init_db():
    """Ensure database schema is up-to-date with roles, barcodes, disposals, and dispenses tables."""
    conn = get_db_connection()
    if not conn:
        print("Database connection failed during init_db.")
        return False
        
    try:
        cursor = conn.cursor()
        
        # 1. Check role in users
        cursor.execute("SHOW TABLES LIKE 'users'")
        if cursor.fetchone():
            cursor.execute("SHOW COLUMNS FROM users LIKE 'role'")
            if not cursor.fetchone():
                print("Adding 'role' column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'pharmacist'")
                cursor.execute("UPDATE users SET role = 'admin' ORDER BY id ASC LIMIT 1")
                conn.commit()

        # 2. Check barcode in medicines
        cursor.execute("SHOW TABLES LIKE 'medicines'")
        if cursor.fetchone():
            cursor.execute("SHOW COLUMNS FROM medicines LIKE 'barcode'")
            if not cursor.fetchone():
                print("Adding 'barcode' column to medicines table...")
                cursor.execute("ALTER TABLE medicines ADD COLUMN barcode VARCHAR(100) AFTER batch_number")
                conn.commit()

        # 3. Create disposals table if not exists
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

        # 4. Create dispenses table if not exists
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
