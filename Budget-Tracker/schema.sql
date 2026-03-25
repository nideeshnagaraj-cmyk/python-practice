CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    role TEXT, -- e.g., Businessman, Student, Employee
    is_guest BOOLEAN DEFAULT 0,
    savings_percentage REAL DEFAULT 0,
    balance_wallet REAL DEFAULT 0,
    age INTEGER,
    gender TEXT,
    recovery_email TEXT,
    recovery_mobile TEXT,
    currency TEXT DEFAULT '₹',
    external_savings REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS incomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    amount REAL NOT NULL,
    frequency TEXT NOT NULL, -- e.g., Monthly, Weekly, Yearly
    income_date DATE NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    monthly_limit REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    sub_category TEXT,
    amount REAL NOT NULL,
    expense_date DATE NOT NULL,
    frequency TEXT DEFAULT 'One-time', -- e.g., One-time, Monthly (EMI)
    notes TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    saved_amount REAL DEFAULT 0,
    target_date DATE NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
