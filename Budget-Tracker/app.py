from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import database
import os
import uuid
import sqlite3
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']

# Check for Gemini Key
gemini_key = os.getenv('GEMINI_API_KEY')
if gemini_key:
    genai.configure(api_key=gemini_key)
    
# Initialize the model once
ai_model = genai.GenerativeModel('gemini-2.5-flash')

# System Instructions injected on every chat
SYSTEM_PROMPT = """You are the AI assistant built directly into the TrackFlow personal finance dashboard. 
You help users understand their budgets, explain how the app's math works, and provide financial advice based on their queries. 

CRITICAL TRACKFLOW SYSTEM MECHANICS YOU MUST KNOW:
1. Income Calculation: The "Remaining Budget" and "Target Savings" widgets do NOT use projected monthly income. They calculate 'Received Income' dynamically based on the current calendar day versus the user's specific input frequency (Daily, Weekly, Monthly etc) and their requested "Next Date". If an income has not reached its 'Next Date' on the calendar yet, it is completely ignored by the active budget.
2. Savings Wallet: Users can fund their savings in two ways. "From Balance" deducts money from their active Remaining Budget. "External Source" (external funds) expands their savings completely independently without affecting their primary budget.
3. Goals: Users can fund tracking Goals from either their main balance_wallet or their external_savings. Both are logged distinctly.
4. Activity Feed: The 'Comprehensive Ledger' on the Activity page uses a SQL UNION ALL to merge incomes, expenses, and external funds into a single chronological timeline.

Be concise, friendly, and act as a built-in guide for the platform."""

# Initialize database on startup
database.init_db()

# Helper to inject user into all templates for navbar avatar
@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        conn = database.get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
    return dict(current_user=user, g_user=user)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = database.get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and user['password_hash'] and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))
            
        conn = database.get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user:
            conn.close()
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
            
        hashed_password = generate_password_hash(password)
        cursor = conn.execute('INSERT INTO users (username, password_hash, currency) VALUES (?, ?, ?)', 
                              (username, hashed_password, '₹'))
        conn.commit()
        
        session['user_id'] = cursor.lastrowid
        session['username'] = username
        conn.close()
        
        flash('Registration successful! Please complete your profile.', 'success')
        return redirect(url_for('onboarding'))
        
    return render_template('register.html')


@app.route('/guest_login', methods=['GET', 'POST'])
def guest_login():
    # Create a unique guest user
    guest_username = f"guest_{uuid.uuid4().hex[:8]}"
    
    conn = database.get_db_connection()
    cursor = conn.execute('INSERT INTO users (username, is_guest, currency) VALUES (?, 1, ?)', 
                          (guest_username, '₹'))
    conn.commit()
    
    session['user_id'] = cursor.lastrowid
    session['username'] = 'Guest'
    conn.close()
    
    flash('Logged in as Guest. Your session is temporary unless you link an account later.', 'success')
    return redirect(url_for('onboarding'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

# Temporary placeholders for next steps
import datetime
import calendar

def get_user_budget_stats(user_id, conn):
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user: return None
    
    current_date = datetime.date.today()
    days_in_month = calendar.monthrange(current_date.year, current_date.month)[1]
    weeks_in_month = days_in_month / 7.0
    
    incomes = conn.execute('SELECT * FROM incomes WHERE user_id = ?', (user_id,)).fetchall()
    total_monthly_income = 0
    received_monthly_income = 0
    
    for inc in incomes:
        amt = inc['amount']
        if inc['frequency'] == 'One-time' and not inc['income_date']:
            continue
            
        inc_date = datetime.datetime.strptime(inc['income_date'], '%Y-%m-%d').date()
        
        # 1. Projected Total Monthly Income Calculation
        if inc['frequency'] == 'Monthly':
            total_monthly_income += amt
        elif inc['frequency'] == 'Weekly':
            total_monthly_income += amt * weeks_in_month
        elif inc['frequency'] == 'Daily':
            total_monthly_income += amt * days_in_month
        elif inc['frequency'] == 'Yearly':
            total_monthly_income += amt / 12
        elif inc['frequency'] == 'One-time':
            if inc_date.year == current_date.year and inc_date.month == current_date.month:
                total_monthly_income += amt
                
        # 2. Actual Received Income (Up to Current Date)
        if inc['frequency'] == 'Monthly':
            pay_day = min(inc_date.day, days_in_month)
            if current_date.day >= pay_day:
                received_monthly_income += amt
        elif inc['frequency'] == 'Weekly':
            target_weekday = inc_date.weekday()
            for day in range(1, current_date.day + 1):
                if datetime.date(current_date.year, current_date.month, day).weekday() == target_weekday:
                    received_monthly_income += amt
        elif inc['frequency'] == 'Daily':
            if inc_date.year < current_date.year or (inc_date.year == current_date.year and inc_date.month < current_date.month):
                # Started in a previous month, so received every day this month up to today
                received_monthly_income += amt * current_date.day
            elif inc_date.year == current_date.year and inc_date.month == current_date.month:
                # Started this month
                if current_date.day >= inc_date.day:
                    received_monthly_income += amt * (current_date.day - inc_date.day + 1)
        elif inc['frequency'] == 'Yearly':
            if current_date.month == inc_date.month:
                pay_day = min(inc_date.day, days_in_month)
                if current_date.day >= pay_day:
                    received_monthly_income += amt
        elif inc['frequency'] == 'One-time':
            if inc_date.year == current_date.year and inc_date.month == current_date.month:
                if current_date.day >= inc_date.day:
                    received_monthly_income += amt
                
    current_month = current_date.strftime('%Y-%m')
    expenses = conn.execute('''
        SELECT SUM(amount) as total FROM expenses 
        WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
        AND category NOT IN ('External Funds', 'Savings Transfer', 'Savings Withdrawal')
    ''', (user_id, current_month)).fetchone()
    total_monthly_expenses = expenses['total'] if expenses and expenses['total'] else 0
    
    target_savings = received_monthly_income * (user['savings_percentage'] / 100.0) if user['savings_percentage'] else 0
    external_savings = user['external_savings'] or 0
    total_savings_wallet = target_savings + user['balance_wallet'] + external_savings
    remaining_budget = received_monthly_income - total_monthly_expenses - target_savings - user['balance_wallet']
    
    return {
        'total_monthly_income': total_monthly_income,
        'total_monthly_expenses': total_monthly_expenses,
        'target_savings': target_savings,
        'total_savings_wallet': total_savings_wallet,
        'remaining_budget': remaining_budget,
        'current_month': current_month
    }

def get_expanded_transactions(user_id, conn, filter_type='all', limit=None):
    # Fetch base rows
    expenses_db = conn.execute("SELECT id, category, sub_category, amount, expense_date as date, 'expense' as type, notes FROM expenses WHERE user_id = ?", (user_id,)).fetchall()
    expenses = [dict(e) for e in expenses_db]
    
    incomes_db = conn.execute("SELECT id, source_name as category, frequency as sub_category, amount, income_date as date, 'income' as type, '' as notes FROM incomes WHERE user_id = ?", (user_id,)).fetchall()
    
    import datetime
    import calendar
    today = datetime.date.today()
    
    def add_months(d, x):
        new_month = d.month - 1 + x
        year = d.year + new_month // 12
        month = new_month % 12 + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        return datetime.date(year, month, day)

    incomes = []
    for inc in incomes_db:
        start_date = datetime.datetime.strptime(inc['date'], '%Y-%m-%d').date()
        freq = inc['sub_category']
        current_date = start_date
        
        # One-time or isolated external funds don't repeat
        if freq == 'One-time' or inc['category'] == 'External Funds':
            if current_date <= today:
                incomes.append(dict(inc))
            continue
            
        # Expend repeating intervals up to today
        while current_date <= today:
            inc_copy = dict(inc)
            inc_copy['date'] = current_date.strftime('%Y-%m-%d')
            incomes.append(inc_copy)
            
            if freq == 'Daily':
                current_date += datetime.timedelta(days=1)
            elif freq == 'Weekly':
                current_date += datetime.timedelta(days=7)
            elif freq == 'Monthly':
                current_date = add_months(current_date, 1)
            elif freq == 'Yearly':
                current_date = add_months(current_date, 12)
            else:
                break
                
    transactions = expenses + incomes
    
    # Filter constraints
    if filter_type == 'income':
        transactions = [t for t in transactions if t['type'] == 'income' and t['category'] not in ('External Funds', 'Savings Withdrawal')]
    elif filter_type == 'expense':
        transactions = [t for t in transactions if t['type'] == 'expense' and t['category'] not in ('External Funds', 'Savings Transfer')]
    elif filter_type == 'external':
        transactions = [t for t in transactions if t['category'] in ('External Funds', 'Goal Funding', 'Savings Transfer', 'Savings Withdrawal')]
        
    # Global sort descending by date
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    if limit is not None:
        transactions = transactions[:limit]
        
    return transactions
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    user_id = session['user_id']
    
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    # Provide a default user dict if somehow missing
    if not user:
        session.clear()
        return redirect(url_for('login'))
        
    stats = get_user_budget_stats(user_id, conn)
    total_monthly_income = stats['total_monthly_income']
    total_monthly_expenses = stats['total_monthly_expenses']
    target_savings = stats['target_savings']
    total_savings_wallet = stats['total_savings_wallet']
    remaining_budget = stats['remaining_budget']
    
    current_month = stats['current_month']
    expenses = conn.execute('''
        SELECT * FROM expenses 
        WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
    ''', (user_id, current_month)).fetchall()
    
    recent_transactions = get_expanded_transactions(user_id, conn, filter_type='all', limit=5)
    
    categories = {}
    for exp in expenses:
        categories[exp['category']] = categories.get(exp['category'], 0) + exp['amount']
    
    # Check if budget is exceeded > 80%
    budget_alert = False
    if total_monthly_income > 0 and (total_monthly_expenses / total_monthly_income) > 0.8:
        budget_alert = True
        
    conn.close()
    
    return render_template('dashboard.html', 
                           user=user, 
                           total_income=total_monthly_income,
                           total_expenses=total_monthly_expenses,
                           recent_transactions=recent_transactions,
                           categories=categories,
                           target_savings=target_savings,
                           total_savings_wallet=total_savings_wallet,
                           remaining_budget=remaining_budget,
                           budget_alert=budget_alert)

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not current_password or not new_password or not confirm_password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('reset_password'))
            
        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('reset_password'))
            
        conn = database.get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        
        if not user or not check_password_hash(user['password_hash'], current_password):
            conn.close()
            flash('Incorrect current password.', 'danger')
            return redirect(url_for('reset_password'))
            
        hashed_pw = generate_password_hash(new_password)
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hashed_pw, session['user_id']))
        conn.commit()
        conn.close()
        
        flash('Password successfully updated!', 'success')
        return redirect(url_for('profile'))
        
    return render_template('reset_password.html')

@app.route('/activity')
def activity():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    user_id = session['user_id']
    import datetime
    
    today = datetime.date.today()
    months_data = []
    
    for i in range(5, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
            
        month_str = f"{year}-{month:02d}"
        
        spent = conn.execute('''
            SELECT SUM(amount) as total FROM expenses
            WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
        ''', (user_id, month_str)).fetchone()['total'] or 0
        
        month_name = datetime.date(year, month, 1).strftime('%b %Y')
        months_data.append({
            'label': month_name,
            'total': spent
        })
        
    all_expenses = conn.execute('SELECT amount, expense_date, category FROM expenses WHERE user_id = ?', (user_id,)).fetchall()
    
    top_category = "N/A"
    top_category_amount = 0
    
    if all_expenses:
        total_ever = sum(e['amount'] for e in all_expenses)
        first_date_str = min(e['expense_date'] for e in all_expenses)
        first_date = datetime.datetime.strptime(first_date_str, '%Y-%m-%d').date()
        
        days_diff = (today - first_date).days
        if days_diff == 0: days_diff = 1
        weeks_passed = max(1, days_diff / 7.0)
        months_passed = max(1, days_diff / 30.44)
        
        avg_weekly = total_ever / weeks_passed
        avg_monthly = total_ever / months_passed
        
        cat_totals = {}
        for e in all_expenses:
            cat = e['category']
            if cat != 'External Funds':
                cat_totals[cat] = cat_totals.get(cat, 0) + e['amount']
                
        if cat_totals:
            top_category = max(cat_totals, key=cat_totals.get)
            top_category_amount = cat_totals[top_category]
    else:
        avg_weekly = 0
        avg_monthly = 0
        
    current_month_total = months_data[-1]['total']
    prev_month_total = months_data[-2]['total'] if len(months_data) >= 2 else 0
    percent_change = 0
    
    if prev_month_total > 0:
        percent_change = ((current_month_total - prev_month_total) / prev_month_total) * 100
        
    categories = {}
    current_month_expenses = conn.execute('''
        SELECT category, amount FROM expenses 
        WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
        AND category NOT IN ('External Funds', 'Savings Transfer', 'Savings Withdrawal')
    ''', (user_id, today.strftime('%Y-%m'))).fetchall()
    
    for exp in current_month_expenses:
        categories[exp['category']] = categories.get(exp['category'], 0) + exp['amount']
        
    # Build Unified Transaction History Logic
    filter_type = request.args.get('type', 'all')
    transactions = get_expanded_transactions(user_id, conn, filter_type=filter_type)

    conn.close()
    
    return render_template('activity.html', 
                           months_data=months_data,
                           avg_weekly=avg_weekly,
                           avg_monthly=avg_monthly,
                           current_month_total=current_month_total,
                           prev_month_total=prev_month_total,
                           percent_change=percent_change,
                           categories=categories,
                           transactions=transactions,
                           current_filter=filter_type,
                           top_category=top_category,
                           top_category_amount=top_category_amount)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    user_id = session['user_id']
    
    if request.method == 'POST':
        # Form submission for updating profile
        new_username = request.form.get('username')
        age = request.form.get('age', type=int)
        gender = request.form.get('gender')
        currency = request.form.get('currency', '$')
        
        try:
            conn.execute('''
                UPDATE users 
                SET username = ?, age = ?, gender = ?, currency = ?
                WHERE id = ?
            ''', (new_username, age, gender, currency, user_id))
                
            conn.commit()
            
            # Update session if username changed
            if new_username:
                session['username'] = new_username
                
            flash('Profile successfully updated!', 'success')
        except sqlite3.IntegrityError:
            flash('Username is already taken. Please choose another.', 'danger')
            
        return redirect(url_for('profile'))
        
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    incomes = conn.execute('SELECT * FROM incomes WHERE user_id = ? ORDER BY income_date DESC', (user_id,)).fetchall()
    
    # Calculate historical savings by month
    savings_percentage = user['savings_percentage'] or 0
    historical_transactions = get_expanded_transactions(user_id, conn, filter_type='income')
    
    monthly_savings_map = {}
    for tx in historical_transactions:
        # tx['date'] is 'YYYY-MM-DD'
        month_key = tx['date'][:7]  # 'YYYY-MM'
        monthly_savings_map[month_key] = monthly_savings_map.get(month_key, 0) + tx['amount']
        
    historical_savings = []
    for month_key in sorted(monthly_savings_map.keys(), reverse=True):
        income_sum = monthly_savings_map[month_key]
        saved_sum = income_sum * (savings_percentage / 100.0)
        historical_savings.append({
            'month': month_key,
            'income': income_sum,
            'saved': saved_sum
        })
    
    conn.close()
    
    return render_template('profile.html', user=user, incomes=incomes, historical_savings=historical_savings)

@app.route('/delete_income/<int:income_id>', methods=['POST'])
def delete_income(income_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    conn.execute('DELETE FROM incomes WHERE id = ? AND user_id = ?', (income_id, session['user_id']))
    conn.commit()
    conn.close()
    
    flash('Income source successfully removed.', 'success')
    return redirect(url_for('profile'))

@app.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    if 'user_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        role = request.form.get('role')
        savings_percentage = request.form.get('savings_percentage', 0, type=float)
        
        income_sources = request.form.getlist('income_source[]')
        income_amounts = request.form.getlist('income_amount[]')
        income_frequencies = request.form.getlist('income_frequency[]')
        income_dates = request.form.getlist('income_date[]')
        
        conn = database.get_db_connection()
        
        # Update user profile
        conn.execute('''
            UPDATE users 
            SET role = ?, savings_percentage = ?
            WHERE id = ?
        ''', (role, savings_percentage, session['user_id']))
        
        # Insert income sources
        # First clear out existing ones (in case they navigated back and submitted again)
        conn.execute('DELETE FROM incomes WHERE user_id = ?', (session['user_id'],))
        
        for i in range(len(income_sources)):
            if income_sources[i].strip() and income_amounts[i]:
                conn.execute('''
                    INSERT INTO incomes (user_id, source_name, amount, frequency, income_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session['user_id'], income_sources[i], float(income_amounts[i]), 
                      income_frequencies[i], income_dates[i]))
                
        conn.commit()
        conn.close()
        
        flash('Profile setup complete! Welcome to your dashboard.', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('onboarding.html')

@app.route('/add_income', methods=['GET', 'POST'])
def add_income():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        income_sources = request.form.getlist('income_source[]')
        income_amounts = request.form.getlist('income_amount[]')
        income_frequencies = request.form.getlist('income_frequency[]')
        income_dates = request.form.getlist('income_date[]')
        
        conn = database.get_db_connection()
        
        added_count = 0
        for i in range(len(income_sources)):
            if income_sources[i].strip() and income_amounts[i]:
                conn.execute('''
                    INSERT INTO incomes (user_id, source_name, amount, frequency, income_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session['user_id'], income_sources[i], float(income_amounts[i]), 
                      income_frequencies[i], income_dates[i]))
                added_count += 1
                
        conn.commit()
        conn.close()
        
        if added_count > 0:
            flash(f'Successfully added {added_count} new income stream(s)!', 'success')
        
        return redirect(url_for('profile'))
        
    return render_template('add_income.html')

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    user_id = session['user_id']
    
    if request.method == 'POST':
        category = request.form.get('category')
        sub_category = request.form.get('sub_category', '')
        amount = request.form.get('amount', type=float)
        expense_date = request.form.get('expense_date')
        frequency = request.form.get('frequency', 'One-time')
        notes = request.form.get('notes', '')
        
        conn.execute('''
            INSERT INTO expenses (user_id, category, sub_category, amount, expense_date, frequency, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, category, sub_category, amount, expense_date, frequency, notes))
        
        conn.commit()
        
        flash('Expense added successfully!', 'success')
        return redirect(url_for('expenses'))
        
    # GET request - fetch history
    # Simple search/filter implementation
    date_filter = request.args.get('date', '')
    cat_filter = request.args.get('category', '')
    
    query = 'SELECT * FROM expenses WHERE user_id = ?'
    params = [user_id]
    
    if dict(request.args).get('clear'):
        date_filter = ''
        cat_filter = ''
        
    if date_filter:
        query += ' AND expense_date = ?'
        params.append(date_filter)
        
    if cat_filter:
        query += ' AND category = ?'
        params.append(cat_filter)
        
    query += ' ORDER BY expense_date DESC'
    
    expense_records = [dict(row) for row in conn.execute(query, params).fetchall()]
    
    # Get total spent for these filtered records
    total_filtered = sum(e['amount'] for e in expense_records)
    
    # Predefined popular categories based on requirements
    categories_list = ['Food & Dining', 'Rent/Housing', 'Transport', 'Grocery', 'EMI/Loans', 'Medicine/Health', 'Insurance/Policy', 'Entertainment', 'Shopping', 'Utilities', 'Other']
    
    # Calculate balance & category budgets for JavaScript warnings
    stats = get_user_budget_stats(user_id, conn)
    current_balance = stats['remaining_budget'] if stats else 0
    current_month = stats['current_month'] if stats else datetime.date.today().strftime('%Y-%m')
    
    budgets = conn.execute('SELECT category, monthly_limit FROM budgets WHERE user_id = ?', (user_id,)).fetchall()
    budget_dict = {b['category']: b['monthly_limit'] for b in budgets}
    
    monthly_expenses = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses 
        WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
        GROUP BY category
    ''', (user_id, current_month)).fetchall()
    spent_dict = {e['category']: e['total'] for e in monthly_expenses}
    
    category_remaining = {}
    for cat in categories_list:
        limit = budget_dict.get(cat, 0)
        spent = spent_dict.get(cat, 0)
        if limit > 0:
            category_remaining[cat] = limit - spent
        else:
            category_remaining[cat] = None
            
    conn.close()
    
    return render_template('expenses.html', 
                           expenses=expense_records, 
                           categories=categories_list,
                           total=total_filtered,
                           filters={'date': date_filter, 'category': cat_filter},
                           balance=current_balance,
                           category_remaining=category_remaining)

@app.route('/expense/delete/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    conn.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?', (expense_id, session['user_id']))
    conn.commit()
    conn.close()
    
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))

@app.route('/budgets', methods=['GET', 'POST'])
def budgets():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    user_id = session['user_id']
    
    if request.method == 'POST':
        category = request.form.get('category')
        limit = request.form.get('monthly_limit', type=float)
        
        # Check if exists
        existing = conn.execute('SELECT id FROM budgets WHERE user_id = ? AND category = ?', (user_id, category)).fetchone()
        if existing:
            conn.execute('UPDATE budgets SET monthly_limit = ? WHERE id = ?', (limit, existing['id']))
        else:
            conn.execute('INSERT INTO budgets (user_id, category, monthly_limit) VALUES (?, ?, ?)', (user_id, category, limit))
        conn.commit()
        flash(f'Budget for {category} updated to ${limit:.2f}!', 'success')
        return redirect(url_for('budgets'))
        
    # GET: fetch budgets and current month spending
    budgets_data = conn.execute('SELECT * FROM budgets WHERE user_id = ?', (user_id,)).fetchall()
    
    # current month spending
    current_month = datetime.date.today().strftime('%Y-%m')
    expenses = conn.execute('''
        SELECT category, SUM(amount) as total_spent 
        FROM expenses 
        WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
        GROUP BY category
    ''', (user_id, current_month)).fetchall()
    
    conn.close()
    
    # Merge data
    budget_dict = {b['category']: b['monthly_limit'] for b in budgets_data}
    spent_dict = {e['category']: e['total_spent'] for e in expenses}
    
    categories_list = ['Food & Dining', 'Rent/Housing', 'Transport', 'Grocery', 'EMI/Loans', 'Medicine/Health', 'Insurance/Policy', 'Entertainment', 'Shopping', 'Utilities', 'Other']
    
    # Build view model
    budgets_view = []
    for cat in categories_list:
        limit = budget_dict.get(cat, 0)
        spent = spent_dict.get(cat, 0)
        if limit > 0 or spent > 0:
            percentage = (spent / limit * 100) if limit > 0 else 100 if spent > 0 else 0
            budgets_view.append({
                'category': cat,
                'limit': limit,
                'spent': spent,
                'percentage': min(percentage, 100),
                'alert': percentage >= 90
            })
            
    return render_template('budgets.html', budgets=budgets_view, categories=categories_list)

@app.route('/goals', methods=['GET', 'POST'])
def goals():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = database.get_db_connection()
    user_id = session['user_id']
    
    if request.method == 'POST':
        name = request.form.get('name')
        target_amount = request.form.get('target_amount', type=float)
        saved_amount = request.form.get('saved_amount', type=float)
        target_date = request.form.get('target_date')
        
        conn.execute('''
            INSERT INTO goals (user_id, name, target_amount, saved_amount, target_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, name, target_amount, saved_amount, target_date))
        conn.commit()
        
        flash('New goal created successfully!', 'success')
        return redirect(url_for('goals'))
        
    goals_data = conn.execute('SELECT * FROM goals WHERE user_id = ? ORDER BY target_date ASC', (user_id,)).fetchall()
    conn.close()
    
    # Calculate planning metrics for each goal
    goals_view = []
    today = datetime.date.today()
    for g in goals_data:
        target_dt = datetime.datetime.strptime(g['target_date'], '%Y-%m-%d').date()
        
        # Calculate rough months difference
        months_left = (target_dt.year - today.year) * 12 + (target_dt.month - today.month)
        if target_dt <= today or months_left <= 0:
            months_left = 0
            
        remaining = max(g['target_amount'] - g['saved_amount'], 0)
        
        # Avoid division by zero
        required_monthly = (remaining / months_left) if months_left > 0 else remaining
        
        percentage = (g['saved_amount'] / g['target_amount'] * 100) if g['target_amount'] > 0 else 0
        
        goals_view.append({
            'id': g['id'],
            'name': g['name'],
            'target_amount': g['target_amount'],
            'saved_amount': g['saved_amount'],
            'target_date': g['target_date'],
            'months_left': months_left,
            'remaining': remaining,
            'required_monthly': required_monthly,
            'percentage': min(percentage, 100),
            'achieved': g['saved_amount'] >= g['target_amount']
        })
        
    return render_template('goals.html', goals=goals_view)

@app.route('/goal/update/<int:goal_id>', methods=['POST'])
def update_goal(goal_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    added_amount = request.form.get('added_amount', type=float)
    fund_source = request.form.get('fund_source', 'other')
    
    if not added_amount or added_amount <= 0:
        flash('Please enter a valid amount.', 'danger')
        return redirect(url_for('goals'))
        
    conn = database.get_db_connection()
    goal = conn.execute('SELECT name FROM goals WHERE id = ?', (goal_id,)).fetchone()
    
    if fund_source == 'savings':
        # Deduct from user balance_wallet or external_savings safely
        user = conn.execute('SELECT balance_wallet FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        bw = user['balance_wallet'] or 0
        if added_amount <= bw:
            conn.execute('UPDATE users SET balance_wallet = balance_wallet - ? WHERE id = ?', (added_amount, session['user_id']))
        else:
            conn.execute('UPDATE users SET balance_wallet = 0, external_savings = external_savings - ? WHERE id = ?', (added_amount - bw, session['user_id']))
            import datetime
            today = datetime.date.today().strftime('%Y-%m-%d')
            conn.execute('''
                INSERT INTO expenses (user_id, category, amount, expense_date, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], 'External Funds', added_amount - bw, today, f'Funded Goal from External Savings: {goal["name"]}'))
    elif fund_source == 'balance':
        # Deduct from general balance by logging it as a tracking expense
        import datetime
        today = datetime.date.today().strftime('%Y-%m-%d')
        conn.execute('''
            INSERT INTO expenses (user_id, category, amount, expense_date, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (session['user_id'], 'Goal Funding', added_amount, today, f'Funded Goal: {goal["name"]}'))
        
    conn.execute('''
        UPDATE goals 
        SET saved_amount = saved_amount + ? 
        WHERE id = ? AND user_id = ?
    ''', (added_amount, goal_id, session['user_id']))
    
    conn.commit()
    conn.close()
    
    flash('Goal progress successfully updated!', 'success')
    return redirect(url_for('goals'))

@app.route('/wallet/transfer', methods=['POST'])
def wallet_transfer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    amount = request.form.get('amount', type=float)
    action = request.form.get('action')
    
    if not amount or amount <= 0:
        flash('Please enter a valid amount.', 'danger')
        return redirect(url_for('dashboard'))
        
    conn = database.get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Calculate current total savings wallet
    stats = get_user_budget_stats(session['user_id'], conn)
    total_savings_wallet = stats['total_savings_wallet'] if stats else 0
    
    if action == 'deposit':
        fund_source = request.form.get('fund_source', 'balance')
        if fund_source == 'external':
            conn.execute('UPDATE users SET external_savings = external_savings + ? WHERE id = ?', (amount, session['user_id']))
            import datetime
            today = datetime.date.today().strftime('%Y-%m-%d')
            conn.execute('''
                INSERT INTO incomes (user_id, source_name, amount, frequency, income_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], 'External Funds', amount, 'One-time', today))
            flash(f'{user["currency"]}{amount:.2f} securely added to your Savings Wallet from an external source.', 'success')
        else:
            conn.execute('UPDATE users SET balance_wallet = balance_wallet + ? WHERE id = ?', (amount, session['user_id']))
            import datetime
            today = datetime.date.today().strftime('%Y-%m-%d')
            conn.execute('''
                INSERT INTO expenses (user_id, category, amount, expense_date, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], 'Savings Transfer', amount, today, 'Transferred from Balance to Savings'))
            flash(f'{user["currency"]}{amount:.2f} securely added to your Savings Wallet from your balance.', 'success')
    elif action == 'withdraw':
        if amount > total_savings_wallet:
            flash('Insufficient funds in your Savings Wallet!', 'danger')
        else:
            bw = user['balance_wallet'] or 0
            if amount <= bw:
                conn.execute('UPDATE users SET balance_wallet = balance_wallet - ? WHERE id = ?', (amount, session['user_id']))
            else:
                conn.execute('UPDATE users SET balance_wallet = 0, external_savings = external_savings - ? WHERE id = ?', (amount - bw, session['user_id']))
                
            import datetime
            today = datetime.date.today().strftime('%Y-%m-%d')
            conn.execute('''
                INSERT INTO incomes (user_id, source_name, amount, frequency, income_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], 'Savings Withdrawal', amount, 'One-time', today))
            flash(f'{user["currency"]}{amount:.2f} withdrawn from Savings Wallet.', 'success')
            
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.get_json()
    user_message = data.get('message')
    
    if not user_message:
        return jsonify({'error': 'Message is required'}), 400
        
    # We need access to the global model initialized at the top
    global ai_model, gemini_key
    
    if not gemini_key:
        return jsonify({'response': "I haven't been properly configured yet! I need a valid Gemini API Key placed into the environment `.env` file to wake up."})
        
    try:
        # Retrieve existing chat history from Flask session
        history = session.get('chat_history', [])
        
        if not history:
            # Inject system prompt invisibly into the very first message
            current_message = f"SYSTEM INSTRUCTIONS: {SYSTEM_PROMPT}\n\nUSER TRIGGER: {user_message}"
        else:
            current_message = user_message
            
        # Start a chat session pre-loaded with the conversation memory
        chat = ai_model.start_chat(history=history)
        response = chat.send_message(current_message)
        
        # Append the new interaction as flat dictionaries for session serialization
        history.append({"role": "user", "parts": [current_message]})
        history.append({"role": "model", "parts": [response.text]})
        
        session['chat_history'] = history
        session.modified = True
        
        return jsonify({
            'response': response.text
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Gemini API Error: {error_msg}")
        print(traceback.format_exc())
        
        if '429' in error_msg or 'quota' in error_msg.lower():
            return jsonify({'error': 'You have exceeded your free tier AI usage quota. Please wait a minute and try again.'}), 429
            
        return jsonify({'error': 'Failed to communicate with AI provider.'}), 500

@app.route('/api/chat/reset', methods=['POST'])
def reset_chat():
    session.pop('chat_history', None)
    return jsonify({"status": "cleared"})

@app.route('/api/expense_insights', methods=['GET'])
def expense_insights():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = database.get_db_connection()
    user_id = session['user_id']

    # Get user profile stats
    stats = get_user_budget_stats(user_id, conn)
    user = conn.execute('SELECT savings_percentage, currency FROM users WHERE id = ?', (user_id,)).fetchone()
    
    import datetime
    current_month = datetime.date.today().strftime('%Y-%m')

    # Get expenses grouped by category
    expenses = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses
        WHERE user_id = ? AND strftime('%Y-%m', expense_date) = ?
        GROUP BY category
    ''', (user_id, current_month)).fetchall()

    conn.close()

    if not expenses and (not stats or stats['total_monthly_income'] == 0):
        return jsonify({"insight": "Welcome! Start adding some incomes and expenses to your ledger so I can analyze your financial habits."})

    expense_data = {row['category']: row['total'] for row in expenses}
    
    currency = user['currency'] if user else '$'
    savings_pct = user['savings_percentage'] if user else 0
    total_income = stats['total_monthly_income'] if stats else 0
    target_savings = stats['target_savings'] if stats else 0

    prompt = f"""
You are a financial analysis assistant built into TrackFlow.

Analyze the user's finances for this current month and provide:
1. Biggest spending category
2. Potential monthly savings opportunities based on their data
3. Any unusual spending patterns
4. One short, practical budgeting tip

User Financial Data (Current Month):
- Recognized Income: {currency}{total_income}
- Target Savings Rate: {savings_pct}% ({currency}{target_savings})
- Expenses Breakdown: {expense_data}

Respond in a clear, concise bullet-point financial report using their currency symbol. Make it encouraging but analytical. Do not use markdown headers, just bolded text and bullet points. Keep it under 150 words.
"""

    global ai_model, gemini_key
    if not gemini_key:
        return jsonify({"insight": "AI Intelligence is disabled. Please configure your API key."})

    try:
        response = ai_model.generate_content(prompt)
        return jsonify({
            "insight": response.text
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Gemini API Error: {error_msg}")
        print(traceback.format_exc())
        
        if '429' in error_msg or 'quota' in error_msg.lower():
            return jsonify({'error': 'AI usage quota temporarily exceeded. Please wait a minute and refresh.'}), 429
            
        return jsonify({"error": "Failed to generate insights."}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
