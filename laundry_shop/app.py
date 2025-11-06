from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import os
import pymysql

# --- Load Environment Variables ---
load_dotenv()

# --- MySQL driver ---
pymysql.install_as_MySQLdb()

# --- Flask Config ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "defaultsecret")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    "DB_URI", "mysql+pymysql://root:ryan123@localhost/laundry_db"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# --- Database Models ---
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="customer")

    laundry_orders = db.relationship(
        'LaundryOrder', backref='user', lazy=True, cascade="all, delete"
    )


class LaundryOrder(db.Model):
    __tablename__ = 'laundry_order'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    laundry_type = db.Column(db.String(100))
    weight_kg = db.Column(db.Float)
    price = db.Column(db.Float)
    status = db.Column(db.String(50), default="Pending")

    # Pickup and dropoff
    pickup_requested = db.Column(db.Boolean, default=False)
    dropoff_requested = db.Column(db.Boolean, default=False)
    floor_number = db.Column(db.String(10))
    unit_number = db.Column(db.String(10))

    date_created = db.Column(db.DateTime, default=datetime.now)
    date_updated = db.Column(db.DateTime, onupdate=datetime.now)


# --- Helpers ---
def parse_bool_from_form(value):
    """Convert checkbox or string value to boolean"""
    if value is None:
        return False
    val = str(value).strip().lower()
    return val in ("on", "1", "true", "yes")


def get_price_per_kg(laundry_type):
    """
    Price mapping for each laundry type (matches your front-end).
    Defaults to Wash-Dry-Fold price if unknown.
    """
    mapping = {
        "Wash-Dry-Fold": 23,
        "Wash-Dry-Press": 60,
        "Press Only": 40,
        "Special Items": 70
    }
    return mapping.get(laundry_type, 23)


# --- Routes ---
@app.route('/')
def home():
    return redirect(url_for('login'))


# --- LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role
            return redirect(url_for('admin_dashboard' if user.role == 'admin' else 'user_dashboard'))
        else:
            flash("Invalid username or password!", "danger")
    return render_template('login.html')


# --- REGISTER ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash("Username already exists!", "danger")
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, password=hashed_pw, role='customer')
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')


# --- ADMIN DASHBOARD ---
@app.route('/admin')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    orders = LaundryOrder.query.order_by(LaundryOrder.date_created.desc()).all()
    users = User.query.filter(User.role != 'admin').all()
    total_income = db.session.query(db.func.sum(LaundryOrder.price)).scalar() or 0
    total_orders = LaundryOrder.query.count()

    return render_template(
        'admin_dashboard.html',
        orders=orders,
        users=users,
        total_income=total_income,
        total_orders=total_orders,
    )


# --- ADD ORDER (Admin) ---
@app.route('/add_order', methods=['POST'])
def add_order():
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    user_id = request.form.get('user_id')
    laundry_type = request.form.get('laundry_type')
    try:
        weight = float(request.form.get('weight', 0))
    except ValueError:
        weight = 0.0

    pickup_requested = parse_bool_from_form(request.form.get('pickup_requested'))
    floor_number = request.form.get('floor_number') if pickup_requested else None
    unit_number = request.form.get('unit_number') if pickup_requested else None

    # price per kg by type
    price_per_kg = get_price_per_kg(laundry_type)
    price = weight * price_per_kg
    if pickup_requested:
        price += 20  # single flat fee for pickup+dropoff

    new_order = LaundryOrder(
        user_id=user_id,
        laundry_type=laundry_type,
        weight_kg=weight,
        price=price,
        pickup_requested=pickup_requested,
        floor_number=floor_number,
        unit_number=unit_number,
    )
    db.session.add(new_order)
    db.session.commit()
    flash("Laundry order added successfully!", "success")
    return redirect(url_for('admin_dashboard'))


# --- UPDATE STATUS ---
@app.route('/update_status/<int:order_id>', methods=['POST'])
def update_status(order_id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    order = LaundryOrder.query.get(order_id)
    if order:
        new_status = request.form['status']
        order.status = new_status

        # When laundry is marked as Ready → mark dropoff to True (no additional fee)
        if new_status.lower() == "ready" and not order.dropoff_requested:
            order.dropoff_requested = True
            # DO NOT add price here — pickup/dropoff fee is added earlier if requested.

        db.session.commit()
        flash("Order status updated!", "success")

    return redirect(url_for('admin_dashboard'))


# --- DELETE ORDER ---
@app.route('/delete_order/<int:order_id>')
def delete_order(order_id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    order = LaundryOrder.query.get(order_id)
    if order:
        db.session.delete(order)
        db.session.commit()
        flash("Order deleted successfully!", "info")
    return redirect(url_for('admin_dashboard'))


# --- DELETE USER ---
@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash("User and all their orders deleted!", "info")
    return redirect(url_for('admin_dashboard'))


# --- USER DASHBOARD ---
@app.route('/user')
def user_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    orders = LaundryOrder.query.filter_by(user_id=session['user_id']).order_by(LaundryOrder.date_created.desc()).all()
    return render_template('user_dashboard.html', orders=orders, user=user)


# --- USER PLACE ORDER ---
@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    laundry_type = request.form.get('laundry_type')
    try:
        weight = float(request.form.get('weight', 0))
    except ValueError:
        weight = 0.0

    pickup_requested = parse_bool_from_form(request.form.get('pickup_requested'))
    floor_number = request.form.get('floor_number') if pickup_requested else None
    unit_number = request.form.get('unit_number') if pickup_requested else None

    # price per kg by type
    price_per_kg = get_price_per_kg(laundry_type)
    price = weight * price_per_kg
    if pickup_requested:
        price += 20  # single flat pickup+dropoff fee

    new_order = LaundryOrder(
        user_id=session['user_id'],
        laundry_type=laundry_type,
        weight_kg=weight,
        price=price,
        pickup_requested=pickup_requested,
        floor_number=floor_number,
        unit_number=unit_number,
    )
    db.session.add(new_order)
    db.session.commit()
    flash("Laundry order placed successfully!", "success")
    return redirect(url_for('user_dashboard'))


# --- LOGOUT ---
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))


# --- Initialize Database ---
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password=generate_password_hash('admin123'), role='admin')
        db.session.add(admin)
        db.session.commit()
        print("✅ Default admin created: admin / admin123")


if __name__ == '__main__':
    app.run(debug=True)
