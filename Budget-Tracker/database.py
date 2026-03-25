import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'app.db')
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DB_PATH):
        conn = get_db_connection()
        with open(SCHEMA_PATH, 'r') as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        print("Database initialized successfully.")
    else:
        print("Database already exists.")

if __name__ == '__main__':
    init_db()
