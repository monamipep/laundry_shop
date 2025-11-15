from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask import redirect, url_for, session, flash
from datetime import datetime, date, timedelta
from flask import jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql
import os
import calendar
import random
from sqlalchemy import text

#========================================================================================= 
#Flask app 
#========================================================================================= 
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.secret_key = "mysecretkey"

#========================================================================================= 
# MySQL driver 
#========================================================================================= 
pymysql.install_as_MySQLdb()

#========================================================================================= 
# Database config
#========================================================================================= 
app.config['SQLALCHEMY_DATABASE_URI'] = "mysql+pymysql://root:@localhost/laundry_db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

#========================================================================================= 
# DATABASE MODELS
#========================================================================================= 
class User(db.Model):
    __tablename__ = 'user'
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(100), unique=True, nullable=False)
        password = db.Column(db.String(255), nullable=False)
        role = db.Column(db.String(20), default="customer")
        laundry_orders = db.relationship('LaundryOrder', backref='user', lazy=True, cascade="all, delete")


class LaundryOrder(db.Model):
    __tablename__ = 'laundry_order'
    id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
            laundry_type = db.Column(db.String(100))
            weight_kg = db.Column(db.Float)
            price = db.Column(db.Float)
            status = db.Column(db.String(50), default="Pending")
            pickup_requested = db.Column(db.Boolean, default=False)
            floor_number = db.Column(db.String(10))
            unit_number = db.Column(db.String(10))
            date_created = db.Column(db.DateTime, default=datetime.now)
            date_updated = db.Column(db.DateTime, onupdate=datetime.now)
            payment_status = db.Column(db.String(20), default="Pending")
            is_paid = db.Column(db.Boolean, default=False)

# New: persistent Income table — income entries are independent of users/orders
class Income(db.Model):
    __tablename__ = 'income'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)  # date-only
    total = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<Income {self.date} ₱{self.total}>"


# Helper 
def get_price_per_kg(laundry_type):
    mapping = {
        "Wash-Dry-Fold": 23,
        "Wash-Dry-Press": 60,
        "Press Only": 40,
        "Special Items": 70
    }
    return mapping.get(laundry_type, 23)


def order_to_dict(order):
    return {
        'id': order.id,
        'customer': order.user.username if order.user else 'Unknown',
        'laundry_type': order.laundry_type,
        'weight_kg': order.weight_kg,
        'price': float(order.price) if order.price else 0,
        'pickup_requested': order.pickup_requested,
        'floor_number': order.floor_number,
        'unit_number': order.unit_number,
        'status': order.status,
        'payment_status': order.payment_status,
        'is_paid': order.is_paid,
        'date_created': order.date_created.strftime('%Y-%m-%d %H:%M') if order.date_created else None,
        'date_updated': order.date_updated.strftime('%Y-%m-%d %H:%M') if getattr(order, 'date_updated', None) else None
    }



def add_income_entry(entry_date: date, amount: float):
    """
    Add amount to Income table for the given date.
    If an Income row for the date exists, increment it; otherwise create it.
    """
    if amount is None:
        return
    try:
        inc = Income.query.filter_by(date=entry_date).first()
        if inc:
            inc.total = (inc.total or 0.0) + float(amount)
        else:
            inc = Income(date=entry_date, total=float(amount))
            db.session.add(inc)
        db.session.commit()
    except Exception as e:
        print("🔥 add_income_entry error:", e)
        db.session.rollback()


# ROUTES 
@app.route('/')
def home():
    return redirect(url_for('login'))


#========================================================================================= 
# LOGIN 
#========================================================================================= 
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Case-sensitive username check
        user = User.query.filter(text("BINARY username = :username")).params(username=username).first()

        if user and check_password_hash(user.password, password):
            # Store user info in session
            session['user_id'] = user.id
            session['role'] = user.role  # assuming you have a 'role' column: 'admin' or 'user'

            flash("Login successful!", "success")

            # Redirect based on role
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash("Invalid username or password!", "error")
            return redirect(url_for('login'))

    return render_template('login.html')


#========================================================================================= 
#register
#========================================================================================= 
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    # POST via AJAX
    data = request.get_json(force=True)
    if not data:
        return jsonify({"success": False, "error": "No data received"})

    username = data.get('username')
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return jsonify({"success": False, "error": "Username already exists"})

    hashed_pw = generate_password_hash(data.get('password'))

#========================================================================================= 
    # Create a new user in the database
#========================================================================================= 
    new_user = User(
        username=username,
        password=hashed_pw,
        role='customer'  # default role
    )
    db.session.add(new_user)
    db.session.commit()

    # Store additional info in session for OTP verification
    session['new_user_id'] = new_user.id
    otp = generate_otp()
    session['otp'] = otp

    # send OTP via email/SMS
    print(f"OTP for {username}: {otp}")

    return jsonify({"success": True, "otp": otp})

#========================================================================================= 
#        OTP verification 
#========================================================================================= 
@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    user_id = session.get('new_user_id')
    sent_otp = session.get('otp')
    data = request.get_json()
    if not user_id or not sent_otp or not data:
        return jsonify({"success": False, "error": "OTP verification failed"})

    user_otp = data.get('otp')
    if user_otp == sent_otp:
        
#========================================================================================= 
        # OTP correct → remove session and allow login
#========================================================================================= 
        session.pop('otp', None)
        session.pop('new_user_id', None)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Incorrect OTP"})


#========================================================================================= 
#                 USER DASHBOARD 
#========================================================================================= 
@app.route('/user', methods=['GET', 'POST'])
def user_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    
    

    if request.method == 'POST':
        
#========================================================================================= 
        # Validate laundry type
#=========================================================================================
        laundry_type = request.form.get('laundry_type')
        if not laundry_type:
            flash("Please select a laundry type.", "danger")
            return redirect(url_for('user_dashboard'))

#========================================================================================= 
        # Validate weight
#========================================================================================= 
        try:
            weight = float(request.form.get('weight', 0))
            if weight <= 0:
                flash("Please enter a valid weight.", "danger")
                return redirect(url_for('user_dashboard'))
        except ValueError:
            flash("Please enter a valid weight.", "danger")
            return redirect(url_for('user_dashboard'))

#========================================================================================= 
        #delivery
#========================================================================================= 
        pickup_requested = 'pickup_requested' in request.form
        floor = request.form.get('floor_number') if pickup_requested else None
        unit = request.form.get('unit_number') if pickup_requested else None

#========================================================================================= 
        # Base price calculation
#========================================================================================= 
        price = get_price_per_kg(laundry_type) * weight
        if pickup_requested:
            price += 70 

       
#========================================================================================= 
        # Create new order
#========================================================================================= 
        new_order = LaundryOrder(
            user_id=user.id,
            laundry_type=laundry_type,
            weight_kg=weight,
            price=price,
            pickup_requested=pickup_requested,
            floor_number=floor,
            unit_number=unit,
            status="Pending"
        )
        db.session.add(new_order)
        db.session.commit()

        # Persist income at creation time
        order_date = new_order.date_created.date() if new_order.date_created else datetime.now().date()
        add_income_entry(order_date, price)

        flash("Order submitted successfully!", "success")
        return redirect(url_for('user_dashboard'))

#========================================================================================= 
    # Fetch user orders
#========================================================================================= 
    orders = LaundryOrder.query.filter_by(user_id=user.id).order_by(LaundryOrder.date_created.desc()).all()
    return render_template('user_dashboard.html', user=user, orders=orders)


#========================================================================================= 
#order
#========================================================================================= 
@app.route("/add_order", methods=["POST"])
def add_order():
    data = request.get_json()
    if not data:
        return jsonify({"message": "No data received"}), 400
    if 'user_id' not in session:
        return jsonify({"message": "User not logged in"}), 401

    try:
        user_id = session['user_id']
        laundry_type = data.get('laundry_type')
        weight = float(data.get('weight', 0))
        price = float(data.get('price', 0))
        pickup_requested = bool(data.get('pickup_requested', False))
        floor = data.get('floor_number')
        unit = data.get('unit_number')

#========================================================================================= 
        # Create new order using SQLAlchemy
#========================================================================================= 
        new_order = LaundryOrder(
            user_id=user_id,
            laundry_type=laundry_type,
            weight_kg=weight,
            price=price,
            pickup_requested=pickup_requested,
            floor_number=floor,
            unit_number=unit,
            status="Pending",
            payment_status="Pending"
        )

        db.session.add(new_order)
        db.session.commit()

#========================================================================================= 
        # Persist income
#========================================================================================= 
        order_date = new_order.date_created.date() if new_order.date_created else datetime.now().date()
        add_income_entry(order_date, price)

        return jsonify({
            "id": new_order.id,
            "laundry_type": laundry_type,
            "weight": weight,
            "price": price,
            "pickup_requested": pickup_requested,
            "floor_number": floor,
            "unit_number": unit,
            "date_created": new_order.date_created.strftime("%Y-%m-%d %H:%M")
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": str(e)}), 500






#========================================================================================= 
# ADMIN DASHBOARD
#========================================================================================= 
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return redirect(url_for('user_dashboard'))

    try:
        pending_orders = LaundryOrder.query.filter_by(status="Pending").order_by(LaundryOrder.date_created.desc()).all()
   # to avoid crashes if some orders point to deleted users
        all_orders = db.session.query(LaundryOrder).outerjoin(User).order_by(LaundryOrder.date_created.desc()).all()
        users = User.query.all()

#========================================================================================= 
        # total_income now comes from Income table 
#========================================================================================= 
        total_income_row = db.session.query(db.func.sum(Income.total)).scalar()
        total_income = float(total_income_row or 0.0)

#========================================================================================= 
        # monthly_income used by server-side 
#========================================================================================= 
        from sqlalchemy import func
        monthly_income = db.session.query(
            func.date_format(Income.date, '%Y-%m').label('month'),
            func.sum(Income.total).label('total')
        ).group_by(func.date_format(Income.date, '%Y-%m')).all()

 
        total_orders = db.session.query(db.func.count(LaundryOrder.id)).scalar() or 0

        return render_template(
            'admin_dashboard.html',
            user=user,
            users=users,
            pending_orders=pending_orders,
            all_orders=all_orders,
            total_income=total_income,
            monthly_income=monthly_income,
            total_orders=total_orders,
            orders=all_orders  
        )
    except Exception as e:
        print("🔥 ADMIN DASHBOARD ERROR:", e)
        flash("Admin dashboard error — check console.", "danger")
        return redirect(url_for('login'))


#========================================================================================= 
## Update order status (Admin: Ready, Completed, 
#========================================================================================= 
@app.route('/api/update_status/<int:order_id>', methods=['POST'])
def api_update_status(order_id):
    order = LaundryOrder.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    try:
        data = request.get_json(force=True)
        if not data or 'status' not in data:
            return jsonify({'success': False, 'error': 'No status provided'}), 400

        order.status = data['status']
        order.date_updated = datetime.now()
        db.session.commit()
        return jsonify({'success': True, 'order': order_to_dict(order)})
    except Exception as e:
        print("🔥 Update Status Error:", e)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500

#========================================================================================= 
#  Mark order as Paid (AJAX) 
#========================================================================================= 
@app.route('/api/mark_payment/<int:order_id>', methods=['POST'])
def api_mark_payment(order_id):
    order = LaundryOrder.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    try:
        #========================================================================================= 
        # Update payment info
        #========================================================================================= 
        order.payment_status = "Paid"
        order.is_paid = True
        order.date_updated = datetime.now()

        db.session.commit()

        return jsonify({'success': True, 'order': order_to_dict(order)})
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
#========================================================================================= 
#  Delete order (Admin) 
#========================================================================================= 
@app.route('/api/delete_order/<int:order_id>', methods=['POST', 'DELETE'])
def api_delete_order(order_id):
    order = LaundryOrder.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    try:
        db.session.delete(order)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Order {order_id} deleted'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
 #========================================================================================= 
# ACCEPT ORDER (AJAX) 
 #========================================================================================= 
@app.route('/api/accept_order/<int:order_id>', methods=['POST'])
def api_accept_order(order_id):
    order = LaundryOrder.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'error': 'Order not found'}), 404

    try:
        order.status = "Accepted"
        order.date_updated = datetime.now()
        db.session.commit()
        return jsonify({'success': True, 'order': order_to_dict(order)})
    except Exception as e:
        print("🔥 Accept Order Error:", e)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500
 #========================================================================================= 
#  INCOME BY MONTH & DAY 
 #========================================================================================= 
@app.route('/api/income_by_month')
def api_income_by_month():
    try:
        from collections import defaultdict
        from datetime import datetime
        import calendar

        incomes = Income.query.order_by(Income.date.desc()).all()
        monthly = defaultdict(float)
        daily = defaultdict(float)
        overall_total = 0.0

        for inc in incomes:
            if not inc.date:
                continue
            total = float(inc.total or 0.0)
            overall_total += total
            month_label = f"{calendar.month_name[inc.date.month]} {inc.date.year}"
            monthly[month_label] += total
            day_label = inc.date.strftime("%B %d, %Y")
            daily[day_label] += total

        def month_sort_key(m):
            parts = m.split()
            try:
                mon = list(calendar.month_name).index(parts[0])
                yr = int(parts[1])
            except:
                mon, yr = 0, 0
            return (yr, mon)

        month_items = sorted(monthly.items(), key=lambda kv: month_sort_key(kv[0]), reverse=True)
        day_items = sorted(daily.items(), key=lambda kv: datetime.strptime(kv[0], "%B %d, %Y"), reverse=True)

        months_list = [{"month": k, "total": v} for k, v in month_items]
        days_list = [{"day": k, "total": v} for k, v in day_items]

        return jsonify({
            "success": True,
            "months": months_list,
            "days": days_list,
            "overall_total": overall_total
        })

    except Exception as e:
        print("🔥 Income Error:", e)
        return jsonify({"success": False, "error": "Server error"}), 500

 #========================================================================================= 
# INCOME BY WEEK (Mon → Sun)
 #========================================================================================= 
@app.route('/api/income_by_week')
def api_income_by_week():
    try:
        from datetime import timedelta, datetime

        incomes = Income.query.order_by(Income.date).all()
        daily_map = {inc.date: float(inc.total or 0.0) for inc in incomes}

        if not daily_map:
            return jsonify({"success": True, "weeks": []})

        min_date = min(daily_map.keys())
        max_date = max(daily_map.keys())

        min_monday = min_date - timedelta(days=min_date.weekday())
        max_sunday = max_date + timedelta(days=(6 - max_date.weekday()))

        weeks = []
        current = min_monday
        while current <= max_sunday:
            week = []
            for i in range(7):
                day = current + timedelta(days=i)
                week.append({
                    "date": day.strftime("%A %b %d, %Y"),
                    "total": daily_map.get(day, 0.0)
                })
            weeks.append(week)
            current += timedelta(days=7)

        return jsonify({"success": True, "weeks": weeks})

    except Exception as e:
        print("🔥 Weekly Income Error:", e)
        return jsonify({"success": False, "error": "Server error"}), 500

 #========================================================================================= 
#  DELETE MONTHLY INCOME 
 #========================================================================================= 
@app.route('/api/delete_income_month', methods=['POST'])
def delete_income_month():
    try:
        payload = request.get_json(force=True)
        month_str = payload.get('month')  # expected format: "YYYY-MM"
        if not month_str:
            return jsonify(success=False, error="No month provided"), 400

        from datetime import datetime, date
        year, month = map(int, month_str.split('-'))
 #========================================================================================= 
        # Compute start and end of month
 #========================================================================================= 
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
 #========================================================================================= 
        # Query incomes in that month
 #========================================================================================= 
        rows = Income.query.filter(Income.date >= start_date, Income.date < end_date).all()
        deleted = 0
        for r in rows:
            db.session.delete(r)
            deleted += 1
        db.session.commit()
 #========================================================================================= 
        # Update total income
 #========================================================================================= 
        total_income = db.session.query(db.func.sum(Income.total)).scalar() or 0

        return jsonify(success=True, deleted=deleted, total_income=total_income)

    except Exception as e:
        print("🔥 Delete month income error:", e)
        db.session.rollback()
        return jsonify(success=False, error="Server error"), 500



 #=========================================================================================   
# Initialize DB 
#==============================================================================================
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password=generate_password_hash('admin123'), role='admin')
        db.session.add(admin)
        db.session.commit()
        print("✅ Default admin created: admin / admin123")


from flask import redirect, url_for, session, flash

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()  # clear all session data
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))  # redirect to login page


# --- Run the app ---
if __name__ == '__main__':
    app.run(debug=True)




