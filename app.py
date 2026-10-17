import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from database import get_db_connection, init_db
from functools import wraps
import csv
from io import StringIO, BytesIO
try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import json

# ReportLab for PDF Generation
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'medalert-secure-secret-key-2026')

# Initialize DB migrations on startup
try:
    init_db()
except Exception as e:
    print(f"Warning: init_db execution deferred: {e}")

# -----------------------------
# AUTH & ROLE DECORATORS
# -----------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in first.', 'warning')
                return redirect(url_for('login'))
            user_role = session.get('user_role', 'pharmacist')
            if user_role not in allowed_roles:
                flash(f'Access denied. Your role ({user_role.capitalize()}) does not have permission for this action.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    return role_required('admin')(f)

# -----------------------------
# EMAIL ALERTS
def send_alert_email_async(user_email, expired_list, expiring_soon_list, low_stock_list):
    sender_email = os.getenv("SMTP_USERNAME")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    
    if not sender_email or not sender_password:
        print("[MedAlert Email] SMTP credentials not set in .env. Skipping automated email.")
        return
        
    subject = "🚨 MedAlert: Action Required - Expired & Low Stock Medicines Report"
    
    # Build HTML email with tables
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
        .container {{ max-width: 650px; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; margin: auto; }}
        .header {{ background-color: #0f172a; color: #ffffff; padding: 20px; text-align: center; }}
        .content {{ padding: 24px; }}
        h3 {{ margin-top: 0; color: #0f172a; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px; }}
        th {{ background-color: #f1f5f9; color: #475569; text-align: left; padding: 8px 10px; border-bottom: 2px solid #cbd5e1; }}
        td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; }}
        .badge-danger {{ background-color: #fee2e2; color: #991b1b; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
        .badge-warning {{ background-color: #fef3c7; color: #92400e; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
        .badge-info {{ background-color: #e0f2fe; color: #0369a1; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
        .footer {{ background-color: #f8fafc; padding: 15px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; }}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">MedAlert Pharmacy System</h2>
            <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 13px;">Clinical Stock & Expiry Priority Dispatch</p>
        </div>
        <div class="content">
            <p>Hello,</p>
            <p>This is an automated priority dispatch from your pharmacy management system. The following pharmaceuticals require immediate rotation, quarantine, or restocking.</p>
    """
    
    # Expired Table
    if expired_list:
        html_content += f"""
            <h4 style="color: #dc2626; margin-bottom: 8px;">🔴 Already Expired Medicines ({len(expired_list)} items) - Mandatory Quarantine</h4>
            <table>
                <thead><tr><th>Medicine Name</th><th>Batch</th><th>In Stock</th><th>Expiry Date</th></tr></thead>
                <tbody>
        """
        for m in expired_list:
            exp_date_str = m['expiry_date'].strftime('%Y-%m-%d') if hasattr(m['expiry_date'], 'strftime') else str(m['expiry_date'])
            html_content += f"<tr><td><strong>{m['name']}</strong></td><td><code>{m['batch_number']}</code></td><td>{m['quantity']} units</td><td><span class=\"badge-danger\">{exp_date_str}</span></td></tr>"
        html_content += "</tbody></table>"
        
    # Expiring Soon Table
    if expiring_soon_list:
        html_content += f"""
            <h4 style="color: #d97706; margin-bottom: 8px;">🟡 Medicines Expiring Soon ({len(expiring_soon_list)} items) - Prioritize Dispensing</h4>
            <table>
                <thead><tr><th>Medicine Name</th><th>Batch</th><th>In Stock</th><th>Expiry Date</th><th>Days Left</th></tr></thead>
                <tbody>
        """
        for m in expiring_soon_list:
            exp_date_str = m['expiry_date'].strftime('%Y-%m-%d') if hasattr(m['expiry_date'], 'strftime') else str(m['expiry_date'])
            html_content += f"<tr><td><strong>{m['name']}</strong></td><td><code>{m['batch_number']}</code></td><td>{m['quantity']} units</td><td>{exp_date_str}</td><td><span class=\"badge-warning\">{m.get('days_remaining', 0)} days</span></td></tr>"
        html_content += "</tbody></table>"
        
    # Low Stock Table
    if low_stock_list:
        html_content += f"""
            <h4 style="color: #0284c7; margin-bottom: 8px;">🔵 Shortage of Stock / Low Stock ({len(low_stock_list)} items) - Reorder Required</h4>
            <table>
                <thead><tr><th>Medicine Name</th><th>Batch</th><th>Available Units</th><th>Min Threshold</th></tr></thead>
                <tbody>
        """
        for m in low_stock_list:
            html_content += f"<tr><td><strong>{m['name']}</strong></td><td><code>{m['batch_number']}</code></td><td><span class=\"badge-danger\">{m['quantity']} units</span></td><td>{m.get('minimum_stock', 10)} units</td></tr>"
        html_content += "</tbody></table>"
        
    html_content += """
            <p style="margin-top: 25px;">Please access the MedAlert Clinical Dashboard to quarantine expired stock or log FEFO dispenses.</p>
        </div>
        <div class="footer">
            MedAlert Regulatory System • Automated Clinical Dispatch • Generated on """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """
        </div>
    </div>
    </body>
    </html>
    """
    
    msg = MIMEMultipart('alternative')
    msg['From'] = sender_email
    msg['To'] = user_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=12)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"[MedAlert Email] Detailed HTML alert successfully delivered to {user_email}.")
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected) as e:
        print(f"[MedAlert Email Error] Gmail rejected the login. Google does not allow your normal account password. You MUST use a 16-character Google App Password from https://myaccount.google.com/apppasswords. Details: {e}")
    except Exception as e:
        print(f"[MedAlert Email Error] Failed to send email alert to {user_email}: {e}")

@app.route('/api/send_inventory_email', methods=['POST'])
@login_required
def send_inventory_email():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    user_email = session.get('user_email')
    
    if not user_email:
        return jsonify({'success': False, 'error': 'No registered email found for current session.'})
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if user_role == 'admin':
        cursor.execute('SELECT * FROM medicines ORDER BY expiry_date ASC')
    else:
        cursor.execute('SELECT * FROM medicines WHERE user_id = %s ORDER BY expiry_date ASC', (user_id,))
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    today = date.today()
    expired_list = []
    expiring_soon_list = []
    low_stock_list = []
    
    for med in medicines:
        ed = med['expiry_date']
        status = get_expiry_status(ed)
        days_rem = (ed - today).days
        med['days_remaining'] = days_rem
        
        if status == 'Expired':
            expired_list.append(med)
        elif status == 'Expiring Soon':
            expiring_soon_list.append(med)
            
        if med['quantity'] <= med['minimum_stock']:
            low_stock_list.append(med)
            
    sender_email = os.getenv("SMTP_USERNAME")
    sender_password = os.getenv("SMTP_PASSWORD")
    if not sender_email or not sender_password:
        return jsonify({
            'success': False,
            'error': 'SMTP credentials are not configured! Please click "Setup Email" on the dashboard to configure your sender email.'
        })
        
    try:
        send_alert_email_async(user_email, expired_list, expiring_soon_list, low_stock_list)
        return jsonify({
            'success': True,
            'message': f'Detailed list of expired ({len(expired_list)}), expiring soon ({len(expiring_soon_list)}), and shortage ({len(low_stock_list)}) medicines sent to {user_email}!'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/test_email', methods=['POST'])
@login_required
def test_email():
    sender_email = os.getenv("SMTP_USERNAME", "").strip()
    sender_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    target_email = request.form.get('target_email', '').strip() or session.get('user_email')
    
    if not sender_email or not sender_password:
        return jsonify({
            'success': False,
            'error': 'SMTP credentials are not configured! Please open your .env file or use the settings form below to enter your Gmail/SMTP email and App Password.'
        })
        
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = target_email
        msg['Subject'] = "MedAlert: SMTP Verification & Test Alert"
        body = (
            f"Hello,\n\n"
            f"This is a verified test email from your MedAlert Pharmacy System.\n\n"
            f"Your automated email notification system is fully configured and operational!\n\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Recipient: {target_email}\n\n"
            f"Best regards,\nMedAlert System"
        )
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=12)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return jsonify({'success': True, 'message': f'Test email successfully sent to {target_email}!'})
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected) as e:
        return jsonify({
            'success': False,
            'error': 'Gmail Authentication Rejected: Google does NOT allow standard account passwords in apps. You MUST generate a 16-character Google "App Password" at https://myaccount.google.com/apppasswords and enter it here.'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'SMTP Connection Failed: {str(e)}'})

@app.route('/api/save_smtp', methods=['POST'])
@login_required
def save_smtp():
    user_role = session.get('user_role')
    if user_role not in ['admin', 'pharmacist']:
        return jsonify({'success': False, 'error': 'Only Administrators and Pharmacists can configure SMTP.'}), 403
        
    email_user = request.form.get('smtp_username', '').strip()
    email_pass = request.form.get('smtp_password', '').strip()
    
    if not email_user or not email_pass:
        return jsonify({'success': False, 'error': 'Both Email and App Password are required.'})
        
    os.environ['SMTP_USERNAME'] = email_user
    os.environ['SMTP_PASSWORD'] = email_pass
    
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    try:
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
        
        new_lines = []
        user_set, pass_set = False, False
        for line in lines:
            if line.startswith('SMTP_USERNAME='):
                new_lines.append(f"SMTP_USERNAME={email_user}\n")
                user_set = True
            elif line.startswith('SMTP_PASSWORD='):
                new_lines.append(f"SMTP_PASSWORD={email_pass}\n")
                pass_set = True
            else:
                new_lines.append(line)
        if not user_set:
            new_lines.append(f"SMTP_USERNAME={email_user}\n")
        if not pass_set:
            new_lines.append(f"SMTP_PASSWORD={email_pass}\n")
            
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
            
        return jsonify({'success': True, 'message': 'SMTP credentials successfully updated and saved to .env!'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to write to .env: {str(e)}'})

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def get_expiry_status(expiry_date):
    today = date.today()
    if expiry_date < today:
        return 'Expired'
    elif expiry_date <= today + timedelta(days=30):
        return 'Expiring Soon'
    else:
        return 'Safe'

# -----------------------------
# ROUTES: AUTHENTICATION
# -----------------------------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'pharmacist').strip().lower()
        
        valid_roles = ['admin', 'pharmacist', 'staff', 'viewer']
        if role not in valid_roles:
            role = 'pharmacist'

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        if not conn:
            flash('Database connection failed. Please ensure MySQL server is running.', 'danger')
            return redirect(url_for('register'))
            
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)',
                (name, email, hashed_password, role)
            )
            conn.commit()
            flash(f'Account created successfully as {role.capitalize()}! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Email already registered or registration failed.', 'danger')
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        conn = get_db_connection()
        if not conn:
            flash('Database connection failed. Check your MySQL setup.', 'danger')
            return redirect(url_for('login'))
            
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['user_role'] = user.get('role', 'pharmacist') or 'pharmacist'
            session.pop('alert_sent', None)
            
            flash(f'Welcome back, {user["name"]}! Logged in as {session["user_role"].capitalize()}.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password. Please verify your credentials.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been securely logged out.', 'info')
    return redirect(url_for('login'))

# -----------------------------
# ADVANCED DASHBOARD
# -----------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    
    scope = request.args.get('scope', 'all' if user_role == 'admin' else 'mine')
    if user_role != 'admin':
        scope = 'mine'

    conn = get_db_connection()
    if not conn:
        flash('Could not connect to database.', 'danger')
        return render_template('dashboard.html', 
                               total_medicines=0, expired=0, expiring_soon=0, expiring_7=0,
                               low_stock=0, health_score=100, total_quantity=0,
                               recent_medicines=[], categories_json='{}', timeline_json='{}',
                               scope=scope, total_users_count=0)
        
    cursor = conn.cursor(dictionary=True)
    
    if scope == 'all':
        cursor.execute('''
            SELECT m.*, u.name as owner_name, u.role as owner_role 
            FROM medicines m 
            LEFT JOIN users u ON m.user_id = u.id 
            ORDER BY m.expiry_date ASC
        ''')
    else:
        cursor.execute('''
            SELECT m.*, u.name as owner_name 
            FROM medicines m 
            LEFT JOIN users u ON m.user_id = u.id 
            WHERE m.user_id = %s 
            ORDER BY m.expiry_date ASC
        ''', (user_id,))
        
    medicines = cursor.fetchall()
    
    cursor.execute('SELECT COUNT(*) as total_users FROM users')
    user_count_row = cursor.fetchone()
    total_users_count = user_count_row['total_users'] if user_count_row else 1
    
    today = date.today()
    total_medicines = len(medicines)
    total_quantity = 0
    expired = 0
    expiring_soon = 0
    expiring_7 = 0
    low_stock = 0
    safe_count = 0
    
    category_counts = {}
    timeline = {
        'expired': 0,
        'days_7': 0,
        'days_30': 0,
        'days_60': 0,
        'safe': 0
    }
    
    expired_list = []
    expiring_soon_list = []
    low_stock_list = []
    
    for med in medicines:
        ed = med['expiry_date']
        status = get_expiry_status(ed)
        med['status'] = status
        days_rem = (ed - today).days
        med['days_remaining'] = days_rem
        
        qty = med.get('quantity', 0)
        total_quantity += qty
        
        cat = med.get('category', 'General') or 'General'
        category_counts[cat] = category_counts.get(cat, 0) + 1
        
        if status == 'Expired':
            expired += 1
            timeline['expired'] += 1
            expired_list.append(med)
        elif status == 'Expiring Soon':
            expiring_soon += 1
            expiring_soon_list.append(med)
            if days_rem <= 7:
                expiring_7 += 1
                timeline['days_7'] += 1
            else:
                timeline['days_30'] += 1
        else:
            safe_count += 1
            if days_rem <= 60:
                timeline['days_60'] += 1
            else:
                timeline['safe'] += 1
            
        if qty <= med.get('minimum_stock', 10):
            low_stock += 1
            med['low_stock'] = True
            low_stock_list.append(med)
        else:
            med['low_stock'] = False
            
    if total_medicines > 0:
        health_penalty = (expired * 25 + expiring_7 * 15 + (expiring_soon - expiring_7) * 5 + low_stock * 10) / total_medicines
        health_score = max(0, min(100, round(100 - health_penalty)))
    else:
        health_score = 100

    if scope == 'all':
        cursor.execute('''
            SELECT m.*, u.name as owner_name 
            FROM medicines m 
            LEFT JOIN users u ON m.user_id = u.id 
            ORDER BY m.created_at DESC LIMIT 8
        ''')
    else:
        cursor.execute('''
            SELECT m.*, u.name as owner_name 
            FROM medicines m 
            LEFT JOIN users u ON m.user_id = u.id 
            WHERE m.user_id = %s 
            ORDER BY m.created_at DESC LIMIT 8
        ''', (user_id,))
    recent_medicines = cursor.fetchall()
    
    for med in recent_medicines:
        ed = med['expiry_date']
        med['status'] = get_expiry_status(ed)
        med['days_remaining'] = (ed - today).days
        med['low_stock'] = (med['quantity'] <= med['minimum_stock'])
        
    cursor.close()
    conn.close()
    
    # Detailed speech alert data
    speech_details = {
        'expired_names': [f"{m['name']} batch {m['batch_number']}" for m in expired_list[:4]],
        'expiring_names': [f"{m['name']} in {m['days_remaining']} days" for m in expiring_soon_list[:4]],
        'low_stock_names': [f"{m['name']} with {m['quantity']} units left" for m in low_stock_list[:4]]
    }
    
    if (expired > 0 or low_stock > 0 or expiring_soon > 0) and not session.get('alert_sent'):
        user_email = session.get('user_email')
        if user_email:
            threading.Thread(
                target=send_alert_email_async,
                args=(user_email, expired_list, expiring_soon_list, low_stock_list)
            ).start()
            session['alert_sent'] = True
    
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_configured = bool(smtp_username and os.getenv("SMTP_PASSWORD", "").strip())

    return render_template('dashboard.html', 
                           total_medicines=total_medicines,
                           total_quantity=total_quantity,
                           expired=expired,
                           expiring_soon=expiring_soon,
                           expiring_7=expiring_7,
                           safe_count=safe_count,
                           low_stock=low_stock,
                           health_score=health_score,
                           recent_medicines=recent_medicines,
                           categories_json=json.dumps(category_counts),
                           timeline_json=json.dumps(timeline),
                           speech_details_json=json.dumps(speech_details),
                           scope=scope,
                           total_users_count=total_users_count,
                           smtp_configured=smtp_configured,
                           smtp_username=smtp_username)

# -----------------------------
# API: BARCODE SEARCH & ALERTS
# -----------------------------
@app.route('/api/search_barcode')
@login_required
def search_barcode():
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({'found': False, 'message': 'No code provided.'})
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Search by barcode or batch_number
    cursor.execute('''
        SELECT * FROM medicines 
        WHERE barcode = %s OR batch_number = %s 
        ORDER BY expiry_date ASC
    ''', (code, code))
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if medicines:
        today = date.today()
        for m in medicines:
            m['status'] = get_expiry_status(m['expiry_date'])
            m['days_remaining'] = (m['expiry_date'] - today).days
            m['expiry_date'] = m['expiry_date'].strftime('%Y-%m-%d')
        return jsonify({'found': True, 'count': len(medicines), 'medicines': medicines})
    
    return jsonify({'found': False, 'message': f"No medicine found matching barcode/batch '{code}'."})

@app.route('/api/alert_counts')
@login_required
def api_alert_counts():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if user_role == 'admin':
        cursor.execute('SELECT * FROM medicines')
    else:
        cursor.execute('SELECT * FROM medicines WHERE user_id = %s', (user_id,))
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    today = date.today()
    expired = 0
    expiring_7 = 0
    low_stock = 0
    
    for med in medicines:
        ed = med['expiry_date']
        status = get_expiry_status(ed)
        days_rem = (ed - today).days
        if status == 'Expired':
            expired += 1
        elif status == 'Expiring Soon' and days_rem <= 7:
            expiring_7 += 1
        if med['quantity'] <= med['minimum_stock']:
            low_stock += 1
            
    return jsonify({
        'expired': expired,
        'expiring_7': expiring_7,
        'low_stock': low_stock,
        'total': len(medicines)
    })

# -----------------------------
# FEFO (FIRST-EXPIRED, FIRST-OUT) DISPENSING
# -----------------------------
@app.route('/fefo')
@login_required
def fefo_workspace():
    selected_name = request.args.get('drug_name', '').strip()
    barcode_code = request.args.get('barcode', '').strip()
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get list of unique drug names with quantities > 0
    cursor.execute('SELECT DISTINCT name FROM medicines WHERE quantity > 0 ORDER BY name ASC')
    all_drugs = [row['name'] for row in cursor.fetchall()]
    
    batches = []
    recommended_batch = None
    warning_message = None
    
    if barcode_code and not selected_name:
        cursor.execute('SELECT name FROM medicines WHERE barcode = %s OR batch_number = %s LIMIT 1', (barcode_code, barcode_code))
        found = cursor.fetchone()
        if found:
            selected_name = found['name']
            
    if selected_name:
        cursor.execute('''
            SELECT * FROM medicines 
            WHERE name = %s AND quantity > 0 
            ORDER BY expiry_date ASC
        ''', (selected_name,))
        batches = cursor.fetchall()
        
        today = date.today()
        for b in batches:
            b['status'] = get_expiry_status(b['expiry_date'])
            b['days_remaining'] = (b['expiry_date'] - today).days
            
        if batches:
            recommended_batch = batches[0]
            if recommended_batch['status'] == 'Expired':
                warning_message = (
                    f"CRITICAL FEFO ALERT: The earliest batch ({recommended_batch['batch_number']}) "
                    f"of '{selected_name}' is EXPIRED. You MUST quarantine it before dispensing subsequent batches!"
                )
                
    cursor.close()
    conn.close()
    
    return render_template('fefo_dispense.html', 
                           all_drugs=all_drugs,
                           selected_name=selected_name,
                           batches=batches,
                           recommended_batch=recommended_batch,
                           warning_message=warning_message)

@app.route('/fefo/dispense', methods=['POST'])
@login_required
def fefo_dispense_action():
    user_role = session.get('user_role', 'pharmacist')
    if user_role == 'viewer':
        flash('Doctors/Viewers cannot dispense medicines.', 'danger')
        return redirect(url_for('fefo_workspace'))
        
    medicine_id = request.form.get('medicine_id', type=int)
    dispense_qty = request.form.get('quantity', type=int)
    patient_or_dest = request.form.get('patient_or_dest', 'General Dispensing').strip()
    override_reason = request.form.get('override_reason', '').strip()
    user_id = session['user_id']
    
    if not medicine_id or not dispense_qty or dispense_qty <= 0:
        flash('Invalid medicine or quantity.', 'danger')
        return redirect(url_for('fefo_workspace'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM medicines WHERE id = %s', (medicine_id,))
    med = cursor.fetchone()
    
    if not med:
        flash('Medicine batch not found.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('fefo_workspace'))
        
    # Check if expired
    today = date.today()
    if med['expiry_date'] < today and not override_reason:
        flash('Cannot dispense expired medicine! Must be quarantined.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('fefo_workspace', drug_name=med['name']))

    if dispense_qty > med['quantity']:
        flash(f"Insufficient stock in batch {med['batch_number']}. Available: {med['quantity']} units.", 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('fefo_workspace', drug_name=med['name']))
        
    new_quantity = med['quantity'] - dispense_qty
    cursor.execute('UPDATE medicines SET quantity = %s WHERE id = %s', (new_quantity, medicine_id))
    
    # Record dispense transaction
    cursor.execute('''
        INSERT INTO dispenses (medicine_id, medicine_name, batch_number, quantity, patient_or_dest, dispensed_by)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (medicine_id, med['name'], med['batch_number'], dispense_qty, patient_or_dest, user_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash(f"Successfully dispensed {dispense_qty} unit(s) of '{med['name']}' from Batch {med['batch_number']} (FEFO compliant)!", 'success')
    return redirect(url_for('fefo_workspace', drug_name=med['name']))

@app.route('/dispense_history')
@login_required
def dispense_history():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT d.*, u.name as staff_name, u.role as staff_role 
        FROM dispenses d 
        LEFT JOIN users u ON d.dispensed_by = u.id 
        ORDER BY d.dispensed_at DESC LIMIT 100
    ''')
    dispenses = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('dispense_history.html', dispenses=dispenses)

# -----------------------------
# QUARANTINE & DISPOSAL AUDIT LOG
# -----------------------------
@app.route('/quarantine/<int:medicine_id>', methods=['GET', 'POST'])
@login_required
def quarantine_medicine(medicine_id):
    user_role = session.get('user_role', 'pharmacist')
    if user_role in ['viewer', 'staff']:
        flash('Only Pharmacists or Administrators can execute quarantine and disposal.', 'danger')
        return redirect(url_for('inventory'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM medicines WHERE id = %s', (medicine_id,))
    med = cursor.fetchone()
    
    if not med:
        flash('Medicine not found.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('inventory'))
        
    if request.method == 'POST':
        dispose_qty = request.form.get('quantity', type=int)
        reason = request.form.get('reason', 'Expired').strip()
        disposal_method = request.form.get('disposal_method', 'High-Temp Incineration').strip()
        witness_name = request.form.get('witness_name', '').strip()
        notes = request.form.get('notes', '').strip()
        user_id = session['user_id']
        
        if not dispose_qty or dispose_qty <= 0 or dispose_qty > med['quantity']:
            flash(f'Invalid disposal quantity. Maximum available: {med["quantity"]}.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('quarantine_medicine', medicine_id=medicine_id))
            
        # 1. Insert into disposals
        cursor.execute('''
            INSERT INTO disposals (user_id, medicine_name, category, batch_number, quantity, expiry_date, reason, disposal_method, witness_name, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, med['name'], med['category'], med['batch_number'], dispose_qty, med['expiry_date'], reason, disposal_method, witness_name, notes))
        
        # 2. Update or remove from medicines
        remaining_qty = med['quantity'] - dispose_qty
        if remaining_qty <= 0:
            cursor.execute('DELETE FROM medicines WHERE id = %s', (medicine_id,))
        else:
            cursor.execute('UPDATE medicines SET quantity = %s WHERE id = %s', (remaining_qty, medicine_id))
            
        conn.commit()
        cursor.close()
        conn.close()
        
        flash(f"Compliance Logged: {dispose_qty} units of '{med['name']}' quarantined and scheduled for {disposal_method}.", 'success')
        return redirect(url_for('disposals_log'))
        
    cursor.close()
    conn.close()
    return render_template('quarantine_modal.html', med=med)

@app.route('/disposals')
@login_required
def disposals_log():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT d.*, u.name as authorized_by_name, u.role as authorized_by_role 
        FROM disposals d 
        LEFT JOIN users u ON d.user_id = u.id 
        ORDER BY d.disposed_at DESC
    ''')
    disposals = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('disposals_log.html', disposals=disposals)

@app.route('/disposal_certificate/<int:id>')
@login_required
def disposal_certificate(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT d.*, u.name as authorized_by_name, u.role as authorized_by_role 
        FROM disposals d 
        LEFT JOIN users u ON d.user_id = u.id 
        WHERE d.id = %s
    ''', (id,))
    disposal = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not disposal:
        flash('Disposal record not found.', 'danger')
        return redirect(url_for('disposals_log'))
        
    return render_template('disposal_certificate.html', disposal=disposal)

# -----------------------------
# PDF INSPECTION REPORT GENERATOR
# -----------------------------
@app.route('/export_pdf')
@login_required
def export_pdf():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    scope = request.args.get('scope', 'all' if user_role == 'admin' else 'mine')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if scope == 'all':
        cursor.execute('SELECT m.*, u.name as owner_name FROM medicines m LEFT JOIN users u ON m.user_id = u.id ORDER BY m.expiry_date ASC')
    else:
        cursor.execute('SELECT m.*, u.name as owner_name FROM medicines m LEFT JOIN users u ON m.user_id = u.id WHERE m.user_id = %s ORDER BY m.expiry_date ASC', (user_id,))
        
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    today = date.today()
    expired = []
    expiring_7 = []
    expiring_30 = []
    low_stock = []
    safe = []
    
    for med in medicines:
        ed = med['expiry_date']
        days_rem = (ed - today).days
        med['days_remaining'] = days_rem
        med['status'] = get_expiry_status(ed)
        
        if ed < today:
            expired.append(med)
        elif today <= ed <= today + timedelta(days=7):
            expiring_7.append(med)
        elif today <= ed <= today + timedelta(days=30):
            expiring_30.append(med)
        else:
            safe.append(med)
            
        if med['quantity'] <= med['minimum_stock']:
            low_stock.append(med)
            
    if not HAS_REPORTLAB:
        flash('PDF report generation requires the "reportlab" library. Please install reportlab or run inside your virtual environment.', 'warning')
        return redirect(url_for('reports'))

    # Build PDF with ReportLab
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0f172a')
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748b')
    )
    section_title = ParagraphStyle(
        'SectionHeading',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1e293b')
    )
    
    elements.append(Paragraph("MEDALERT PHARMACEUTICAL AUDIT REPORT", title_style))
    elements.append(Paragraph(f"Official Regulatory Inspection & Compliance Sheet • Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
    elements.append(Paragraph(f"Audited by: {session.get('user_name')} ({user_role.upper()}) | Scope: {scope.upper()}", subtitle_style))
    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0f172a'), spaceBefore=4, spaceAfter=14))
    
    # KPI Summary Table
    total_count = len(medicines)
    health_score = round(max(0, 100 - ((len(expired) * 30 + len(expiring_7) * 15 + len(low_stock) * 10) / (total_count or 1))))
    
    kpi_data = [
        ['Total SKUs', 'Expired Items', 'Expiring < 7 Days', 'Low Stock Breaches', 'Safety Rating'],
        [str(total_count), str(len(expired)), str(len(expiring_7)), str(len(low_stock)), f"{health_score}%"]
    ]
    kpi_table = Table(kpi_data, colWidths=[108, 108, 108, 108, 108])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f1f5f9')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#334155')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 14),
        ('TEXTCOLOR', (1,1), (1,1), colors.HexColor('#ef4444')),
        ('TEXTCOLOR', (2,1), (2,1), colors.HexColor('#f59e0b')),
        ('TEXTCOLOR', (3,1), (3,1), colors.HexColor('#0ea5e9')),
        ('TEXTCOLOR', (4,1), (4,1), colors.HexColor('#10b981') if health_score > 75 else colors.HexColor('#ef4444')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1'))
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 16))
    
    # Expired Medicines Table
    elements.append(Paragraph("1. CRITICAL: EXPIRED MEDICINES (MANDATORY QUARANTINE)", section_title))
    elements.append(Spacer(1, 6))
    if expired:
        exp_table_data = [['Medicine Name', 'Category', 'Batch #', 'Qty', 'Expiry Date', 'Expired Ago']]
        for m in expired:
            exp_table_data.append([
                m['name'][:22],
                m['category'][:15],
                m['batch_number'][:14],
                str(m['quantity']),
                m['expiry_date'].strftime('%Y-%m-%d'),
                f"{abs(m['days_remaining'])} days"
            ])
        exp_table = Table(exp_table_data, colWidths=[140, 95, 95, 50, 80, 80])
        exp_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#fee2e2')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#991b1b')),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (3,0), (5,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#fca5a5')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#fef2f2')])
        ]))
        elements.append(exp_table)
    else:
        elements.append(Paragraph("No expired medicines found. Stock complies with zero-expired standards.", subtitle_style))
        
    elements.append(Spacer(1, 14))
    
    # Urgent Expiring (< 7 Days)
    elements.append(Paragraph("2. HIGH PRIORITY: EXPIRING WITHIN 7 DAYS", section_title))
    elements.append(Spacer(1, 6))
    if expiring_7:
        soon_table_data = [['Medicine Name', 'Category', 'Batch #', 'Qty', 'Expiry Date', 'Days Left']]
        for m in expiring_7:
            soon_table_data.append([
                m['name'][:22],
                m['category'][:15],
                m['batch_number'][:14],
                str(m['quantity']),
                m['expiry_date'].strftime('%Y-%m-%d'),
                f"{m['days_remaining']} days"
            ])
        soon_table = Table(soon_table_data, colWidths=[140, 95, 95, 50, 80, 80])
        soon_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#fef3c7')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#92400e')),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (3,0), (5,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#fde68a')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#fffbeb')])
        ]))
        elements.append(soon_table)
    else:
        elements.append(Paragraph("No medicines expiring within the next 7 days.", subtitle_style))
        
    elements.append(Spacer(1, 24))
    
    # Auditor Sign-off box
    sign_data = [
        ['Chief Pharmacist Signature', 'Hospital Regulatory Inspector', 'Date of Sign-off'],
        ['\n\n___________________________', '\n\n___________________________', f'\n\n{date.today().strftime("%d %B %Y")}']
    ]
    sign_table = Table(sign_data, colWidths=[180, 180, 180])
    sign_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER')
    ]))
    elements.append(sign_table)
    
    doc.build(elements)
    pdf_buffer.seek(0)
    
    return Response(
        pdf_buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=medalert_audit_report_{date.today().strftime('%Y%m%d')}.pdf"}
    )

# -----------------------------
# QUICK RESTOCK
# -----------------------------
@app.route('/quick_update_stock/<int:id>', methods=['POST'])
@login_required
def quick_update_stock(id):
    user_role = session.get('user_role', 'pharmacist')
    if user_role == 'viewer':
        return jsonify({'success': False, 'error': 'Viewers cannot modify stock.'}), 403
        
    user_id = session['user_id']
    add_qty = request.form.get('additional_quantity', type=int)
    new_qty = request.form.get('new_quantity', type=int)
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error'}), 500
        
    cursor = conn.cursor(dictionary=True)
    if user_role == 'admin':
        cursor.execute('SELECT * FROM medicines WHERE id = %s', (id,))
    else:
        cursor.execute('SELECT * FROM medicines WHERE id = %s AND user_id = %s', (id, user_id))
    med = cursor.fetchone()
    
    if not med:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'error': 'Medicine not found'}), 404
        
    if new_qty is not None:
        final_qty = max(0, new_qty)
    elif add_qty is not None:
        final_qty = max(0, med['quantity'] + add_qty)
    else:
        final_qty = med['quantity']
        
    cursor.execute('UPDATE medicines SET quantity = %s WHERE id = %s', (final_qty, id))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash(f"Stock for '{med['name']}' updated to {final_qty} units.", 'success')
    return redirect(request.referrer or url_for('dashboard'))

# -----------------------------
# ADD MEDICINE & OCR
# -----------------------------
@app.route('/add_medicine', methods=['GET', 'POST'])
@login_required
def add_medicine():
    user_role = session.get('user_role', 'pharmacist')
    if user_role == 'viewer':
        flash('Doctors/Viewers have read-only permissions and cannot add medicines.', 'warning')
        return redirect(url_for('inventory'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        batch_number = request.form.get('batch_number', '').strip()
        barcode = request.form.get('barcode', '').strip() or batch_number
        manufacturer = request.form.get('manufacturer', '').strip()
        quantity = int(request.form.get('quantity', 0))
        manufacturing_date = request.form.get('manufacturing_date') or None
        expiry_date = request.form.get('expiry_date')
        purchase_date = request.form.get('purchase_date') or None
        supplier_name = request.form.get('supplier_name', '').strip()
        minimum_stock = int(request.form.get('minimum_stock', 10))
        user_id = session['user_id']
        
        if quantity < 0 or minimum_stock < 0:
            flash('Quantity and Minimum Stock must be positive numbers.', 'danger')
            return redirect(url_for('add_medicine'))
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO medicines (user_id, name, category, batch_number, barcode, manufacturer, 
                quantity, manufacturing_date, expiry_date, purchase_date, supplier_name, minimum_stock)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (user_id, name, category, batch_number, barcode, manufacturer, quantity, 
                  manufacturing_date, expiry_date, purchase_date, supplier_name, minimum_stock))
            conn.commit()
            flash(f"Medicine '{name}' successfully registered to inventory!", 'success')
            return redirect(url_for('inventory'))
        except Exception as e:
            flash(f'Error adding medicine: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
            
    return render_template('add_medicine.html')

@app.route('/extract_info', methods=['POST'])
@login_required
def extract_info():
    if not HAS_OCR:
        return jsonify({'error': 'OCR module (pytesseract/Pillow) is not installed in the currently active Python interpreter. Please run using your virtual environment (venv) or install pytesseract.'})

    if 'medicine_image' not in request.files:
        return jsonify({'error': 'No image file uploaded.'})
    
    file = request.files['medicine_image']
    if file.filename == '':
        return jsonify({'error': 'No file selected.'})
        
    try:
        image = Image.open(file.stream)
        
        tesseract_cmd = os.getenv('TESSERACT_CMD')
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            
        text = pytesseract.image_to_string(image)
        
        data = {
            'name': '',
            'batch_number': '',
            'expiry_date': '',
            'manufacturing_date': ''
        }
        
        batch_match = re.search(r'(?i)(?:batch|lot|b\.?no|b\.?n)[\s\.\-\:]*([a-zA-Z0-9]+)', text)
        if batch_match:
            data['batch_number'] = batch_match.group(1)
            
        date_pattern = r'\b(\d{2}[/.-]\d{2}[/.-]\d{2,4}|\d{2}[/.-]\d{4})\b'
        dates = re.findall(date_pattern, text)
        
        if len(dates) >= 2:
            data['manufacturing_date'] = dates[0]
            data['expiry_date'] = dates[1]
        elif len(dates) == 1:
            data['expiry_date'] = dates[0]

        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if line and len(line) > 3 and not re.search(r'(?i)(batch|mfg|exp|date|price|rs|mrp|tab|cap)', line):
                data['name'] = line
                break
                
        return jsonify({'success': True, 'data': data, 'raw_text': text})
    except Exception as e:
        return jsonify({'error': str(e)})

# -----------------------------
# INVENTORY
# -----------------------------
@app.route('/inventory')
@login_required
def inventory():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'all')
    scope = request.args.get('scope', 'all' if user_role == 'admin' else 'mine')
    
    if user_role != 'admin':
        scope = 'mine'

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    params = []
    if scope == 'all':
        query = 'SELECT m.*, u.name as owner_name FROM medicines m LEFT JOIN users u ON m.user_id = u.id WHERE 1=1'
    else:
        query = 'SELECT m.*, u.name as owner_name FROM medicines m LEFT JOIN users u ON m.user_id = u.id WHERE m.user_id = %s'
        params.append(user_id)
        
    if search:
        query += ' AND (m.name LIKE %s OR m.batch_number LIKE %s OR m.category LIKE %s OR m.barcode LIKE %s)'
        search_param = f'%{search}%'
        params.extend([search_param, search_param, search_param, search_param])
        
    query += ' ORDER BY m.expiry_date ASC'
    
    cursor.execute(query, tuple(params))
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    filtered_medicines = []
    today = date.today()
    for med in medicines:
        ed = med['expiry_date']
        status = get_expiry_status(ed)
        med['status'] = status
        med['is_low_stock'] = (med['quantity'] <= med['minimum_stock'])
        med['days_remaining'] = (ed - today).days
        
        if status_filter == 'all':
            filtered_medicines.append(med)
        elif status_filter == 'expired' and status == 'Expired':
            filtered_medicines.append(med)
        elif status_filter == 'soon' and status == 'Expiring Soon':
            filtered_medicines.append(med)
        elif status_filter == 'safe' and status == 'Safe':
            filtered_medicines.append(med)
        elif status_filter == 'low' and med['is_low_stock']:
            filtered_medicines.append(med)
            
    return render_template('inventory.html', 
                           medicines=filtered_medicines, 
                           search=search, 
                           status_filter=status_filter,
                           scope=scope)

# -----------------------------
# EDIT & DELETE MEDICINE
# -----------------------------
@app.route('/edit_medicine/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_medicine(id):
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    
    if user_role == 'viewer':
        flash('Viewers do not have edit permissions.', 'warning')
        return redirect(url_for('inventory'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        batch_number = request.form['batch_number']
        barcode = request.form.get('barcode', '').strip() or batch_number
        manufacturer = request.form['manufacturer']
        quantity = int(request.form['quantity'])
        manufacturing_date = request.form['manufacturing_date'] or None
        expiry_date = request.form['expiry_date']
        purchase_date = request.form['purchase_date'] or None
        supplier_name = request.form['supplier_name']
        minimum_stock = int(request.form['minimum_stock'])
        
        try:
            if user_role == 'admin':
                cursor.execute('''
                    UPDATE medicines SET name=%s, category=%s, batch_number=%s, barcode=%s, manufacturer=%s, 
                    quantity=%s, manufacturing_date=%s, expiry_date=%s, purchase_date=%s, supplier_name=%s, minimum_stock=%s
                    WHERE id=%s
                ''', (name, category, batch_number, barcode, manufacturer, quantity, manufacturing_date, expiry_date, purchase_date, supplier_name, minimum_stock, id))
            else:
                cursor.execute('''
                    UPDATE medicines SET name=%s, category=%s, batch_number=%s, barcode=%s, manufacturer=%s, 
                    quantity=%s, manufacturing_date=%s, expiry_date=%s, purchase_date=%s, supplier_name=%s, minimum_stock=%s
                    WHERE id=%s AND user_id=%s
                ''', (name, category, batch_number, barcode, manufacturer, quantity, manufacturing_date, expiry_date, purchase_date, supplier_name, minimum_stock, id, user_id))
            conn.commit()
            flash('Medicine record updated successfully!', 'success')
            return redirect(url_for('inventory'))
        except Exception as e:
            flash(f'Error updating medicine: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
            
    if user_role == 'admin':
        cursor.execute('SELECT * FROM medicines WHERE id = %s', (id,))
    else:
        cursor.execute('SELECT * FROM medicines WHERE id = %s AND user_id = %s', (id, user_id))
    medicine = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not medicine:
        flash('Medicine record not found or access denied.', 'danger')
        return redirect(url_for('inventory'))
        
    return render_template('edit_medicine.html', medicine=medicine)

@app.route('/delete_medicine/<int:id>', methods=['POST'])
@login_required
def delete_medicine(id):
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    
    if user_role in ['viewer', 'staff']:
        flash(f'{user_role.capitalize()}s cannot delete medicine records. Contact Administrator or Pharmacist.', 'danger')
        return redirect(url_for('inventory'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if user_role == 'admin':
            cursor.execute('DELETE FROM medicines WHERE id = %s', (id,))
        else:
            cursor.execute('DELETE FROM medicines WHERE id = %s AND user_id = %s', (id, user_id))
        conn.commit()
        flash('Medicine deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting medicine: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('inventory'))

# -----------------------------
# ADMIN CONSOLE: USER MANAGEMENT
# -----------------------------
@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT u.id, u.name, u.email, u.role, u.created_at, 
               COUNT(m.id) as total_medicines,
               COALESCE(SUM(m.quantity), 0) as total_quantity
        FROM users u 
        LEFT JOIN medicines m ON u.id = m.user_id 
        GROUP BY u.id 
        ORDER BY u.id ASC
    ''')
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/update_role/<int:user_id>', methods=['POST'])
@admin_required
def update_user_role(user_id):
    new_role = request.form.get('role', 'pharmacist').strip().lower()
    if new_role not in ['admin', 'pharmacist', 'staff', 'viewer']:
        flash('Invalid role specified.', 'danger')
        return redirect(url_for('admin_users'))
        
    if user_id == session['user_id'] and new_role != 'admin':
        flash('You cannot remove the administrator role from yourself.', 'warning')
        return redirect(url_for('admin_users'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE users SET role = %s WHERE id = %s', (new_role, user_id))
        conn.commit()
        flash(f'User role updated to {new_role.capitalize()}.', 'success')
    except Exception as e:
        flash(f'Error updating role: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == session['user_id']:
        flash('You cannot delete your own account while logged in.', 'danger')
        return redirect(url_for('admin_users'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
        conn.commit()
        flash('User account and associated medicines removed.', 'success')
    except Exception as e:
        flash(f'Error deleting user: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin_users'))

# -----------------------------
# REPORTS & CSV EXPORT
# -----------------------------
@app.route('/reports')
@login_required
def reports():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    scope = request.args.get('scope', 'all' if user_role == 'admin' else 'mine')
    if user_role != 'admin':
        scope = 'mine'

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if scope == 'all':
        cursor.execute('''
            SELECT m.*, u.name as owner_name 
            FROM medicines m 
            LEFT JOIN users u ON m.user_id = u.id 
            ORDER BY m.expiry_date ASC
        ''')
    else:
        cursor.execute('''
            SELECT m.*, u.name as owner_name 
            FROM medicines m 
            LEFT JOIN users u ON m.user_id = u.id 
            WHERE m.user_id = %s 
            ORDER BY m.expiry_date ASC
        ''', (user_id,))
        
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    expired = []
    expiring_7 = []
    expiring_30 = []
    low_stock = []
    
    today = date.today()
    for med in medicines:
        ed = med['expiry_date']
        med['status'] = get_expiry_status(ed)
        med['days_remaining'] = (ed - today).days
        
        if ed < today:
            expired.append(med)
        elif today <= ed <= today + timedelta(days=7):
            expiring_7.append(med)
        elif today <= ed <= today + timedelta(days=30):
            expiring_30.append(med)
            
        if med['quantity'] <= med['minimum_stock']:
            low_stock.append(med)
            
    return render_template('reports.html', 
                           expired=expired, 
                           expiring_7=expiring_7, 
                           expiring_30=expiring_30, 
                           low_stock=low_stock, 
                           medicines=medicines,
                           scope=scope)

@app.route('/export_csv')
@login_required
def export_csv():
    user_id = session['user_id']
    user_role = session.get('user_role', 'pharmacist')
    scope = request.args.get('scope', 'all' if user_role == 'admin' else 'mine')
    if user_role != 'admin':
        scope = 'mine'

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if scope == 'all':
        cursor.execute('SELECT m.*, u.name as owner_name FROM medicines m LEFT JOIN users u ON m.user_id = u.id ORDER BY m.expiry_date ASC')
    else:
        cursor.execute('SELECT m.*, u.name as owner_name FROM medicines m LEFT JOIN users u ON m.user_id = u.id WHERE m.user_id = %s ORDER BY m.expiry_date ASC', (user_id,))
        
    medicines = cursor.fetchall()
    cursor.close()
    conn.close()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Medicine Name', 'Category', 'Batch Number', 'Barcode', 'Manufacturer', 'Quantity', 'Min Stock', 'Expiry Date', 'Status', 'Days Remaining', 'Owner'])
    
    today = date.today()
    for med in medicines:
        status = get_expiry_status(med['expiry_date'])
        days_rem = (med['expiry_date'] - today).days
        cw.writerow([
            med['id'],
            med['name'],
            med['category'],
            med['batch_number'],
            med.get('barcode', ''),
            med.get('manufacturer', ''),
            med['quantity'],
            med['minimum_stock'],
            med['expiry_date'],
            status,
            days_rem,
            med.get('owner_name', 'Self')
        ])
        
    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=medalert_inventory_report.csv"}
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)
