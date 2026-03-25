import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'app.db')

def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if age column exists to prevent duplicate column errors
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "age" not in columns:
        print("Adding age column...")
        cursor.execute("ALTER TABLE users ADD COLUMN age INTEGER")
        
    if "gender" not in columns:
        print("Adding gender column...")
        cursor.execute("ALTER TABLE users ADD COLUMN gender TEXT")
        
    conn.commit()
    conn.close()
    print("Migration finished!")

if __name__ == "__main__":
    migrate_db()
