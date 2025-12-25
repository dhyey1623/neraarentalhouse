from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import os
import uuid
from io import BytesIO
from reportlab.lib.pagesizes import inch
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'neraa-rental-house-secret-key-2025')

# Database Configuration - PostgreSQL for Production, SQLite for Local
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Fix for Render PostgreSQL URL (postgres:// -> postgresql://)
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    # Local development - SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rental_system.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='staff')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    rental_price = db.Column(db.Float, nullable=False)  # Per product price (not daily)
    deposit_amount = db.Column(db.Float, default=0)
    image_path = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    secondary_phone = db.Column(db.String(20))  # Secondary phone (optional)
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    delivery_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending')
    total_amount = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('Customer', backref='orders')
    staff = db.relationship('User', backref='orders')
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')
    accessories = db.relationship('OrderAccessory', backref='order', cascade='all, delete-orphan')
    extra_charges = db.relationship('OrderExtraCharge', backref='order', cascade='all, delete-orphan')

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)  # Per product price
    
    product = db.relationship('Product')

class OrderAccessory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    accessory_name = db.Column(db.String(100), nullable=False)
    remarks = db.Column(db.Text)

class OrderExtraCharge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.Text)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    order = db.relationship('Order', backref='invoice')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Admin access required', 'error')
            return redirect(url_for('staff_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def generate_invoice_number():
    count = Invoice.query.count() + 1
    return f"INV-{count:05d}"

def amount_in_words(amount):
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
            'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 
            'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
    
    if amount == 0:
        return 'Zero Rupees Only'
    
    amount = int(amount)
    
    def convert_less_than_thousand(n):
        if n == 0:
            return ''
        elif n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + (' ' + ones[n % 10] if n % 10 != 0 else '')
        else:
            return ones[n // 100] + ' Hundred' + (' ' + convert_less_than_thousand(n % 100) if n % 100 != 0 else '')
    
    def convert(n):
        if n < 1000:
            return convert_less_than_thousand(n)
        elif n < 100000:
            return convert_less_than_thousand(n // 1000) + ' Thousand' + (' ' + convert_less_than_thousand(n % 1000) if n % 1000 != 0 else '')
        elif n < 10000000:
            return convert_less_than_thousand(n // 100000) + ' Lakh' + (' ' + convert(n % 100000) if n % 100000 != 0 else '')
        else:
            return convert(n // 10000000) + ' Crore' + (' ' + convert(n % 10000000) if n % 10000000 != 0 else '')
    
    return convert(amount) + ' Rupees Only'

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('staff_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('Account deactivated. Contact admin.', 'error')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Admin Dashboard
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    approved_orders = Order.query.filter_by(status='approved').count()
    total_products = Product.query.filter_by(is_active=True).count()
    total_staff = User.query.filter_by(role='staff', is_active=True).count()
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    monthly_revenue = db.session.query(db.func.sum(Order.total_amount)).filter(
        db.extract('month', Order.created_at) == current_month,
        db.extract('year', Order.created_at) == current_year,
        Order.status.in_(['approved', 'completed'])
    ).scalar() or 0
    
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    
    return render_template('admin_dashboard.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         approved_orders=approved_orders,
                         total_products=total_products,
                         total_staff=total_staff,
                         monthly_revenue=monthly_revenue,
                         recent_orders=recent_orders)

# Staff Dashboard
@app.route('/staff/dashboard')
@login_required
def staff_dashboard():
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    if current_user.role == 'admin':
        monthly_orders = Order.query.filter(
            db.extract('month', Order.created_at) == current_month,
            db.extract('year', Order.created_at) == current_year
        ).count()
        
        monthly_revenue = db.session.query(db.func.sum(Order.total_amount)).filter(
            db.extract('month', Order.created_at) == current_month,
            db.extract('year', Order.created_at) == current_year,
            Order.status.in_(['approved', 'completed'])
        ).scalar() or 0
    else:
        monthly_orders = Order.query.filter(
            Order.staff_id == current_user.id,
            db.extract('month', Order.created_at) == current_month,
            db.extract('year', Order.created_at) == current_year
        ).count()
        
        monthly_revenue = db.session.query(db.func.sum(Order.total_amount)).filter(
            Order.staff_id == current_user.id,
            db.extract('month', Order.created_at) == current_month,
            db.extract('year', Order.created_at) == current_year,
            Order.status.in_(['approved', 'completed'])
        ).scalar() or 0
    
    return render_template('staff_dashboard.html',
                         monthly_orders=monthly_orders,
                         monthly_revenue=monthly_revenue)

# Staff Management
@app.route('/admin/staff')
@login_required
@admin_required
def manage_staff():
    staff_list = User.query.filter_by(role='staff').all()
    return render_template('manage_staff.html', staff_list=staff_list)

@app.route('/admin/staff/add', methods=['POST'])
@login_required
@admin_required
def add_staff():
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password')
    
    if User.query.filter_by(email=email).first():
        flash('Email already exists', 'error')
        return redirect(url_for('manage_staff'))
    
    new_staff = User(
        name=name,
        email=email,
        phone=phone,
        password_hash=generate_password_hash(password),
        role='staff'
    )
    db.session.add(new_staff)
    db.session.commit()
    flash('Staff added successfully', 'success')
    return redirect(url_for('manage_staff'))

@app.route('/admin/staff/toggle/<int:staff_id>')
@login_required
@admin_required
def toggle_staff(staff_id):
    staff = User.query.get_or_404(staff_id)
    staff.is_active = not staff.is_active
    db.session.commit()
    flash(f'Staff {"activated" if staff.is_active else "deactivated"} successfully', 'success')
    return redirect(url_for('manage_staff'))

# Product Management
@app.route('/admin/products')
@login_required
@admin_required
def manage_products():
    products = Product.query.all()
    return render_template('manage_products.html', products=products)

@app.route('/admin/products/add', methods=['POST'])
@login_required
@admin_required
def add_product():
    product_code = request.form.get('product_code')
    name = request.form.get('name')
    rental_price = float(request.form.get('rental_price', 0))
    deposit_amount = float(request.form.get('deposit_amount', 0))
    
    if Product.query.filter_by(product_code=product_code).first():
        flash('Product code already exists', 'error')
        return redirect(url_for('manage_products'))
    
    image_path = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{product_code}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = f"uploads/{filename}"
    
    new_product = Product(
        product_code=product_code,
        name=name,
        rental_price=rental_price,
        deposit_amount=deposit_amount,
        image_path=image_path
    )
    db.session.add(new_product)
    db.session.commit()
    flash('Product added successfully', 'success')
    return redirect(url_for('manage_products'))

@app.route('/admin/products/bulk-add', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_add_products():
    if request.method == 'POST':
        product_codes = request.form.getlist('product_code[]')
        names = request.form.getlist('name[]')
        rental_prices = request.form.getlist('rental_price[]')
        deposit_amounts = request.form.getlist('deposit_amount[]')
        images = request.files.getlist('image[]')
        
        added_count = 0
        skipped_count = 0
        
        for i in range(len(product_codes)):
            code = product_codes[i].strip() if product_codes[i] else ''
            name = names[i].strip() if names[i] else ''
            price = rental_prices[i].strip() if rental_prices[i] else ''
            
            # Skip empty rows
            if not code and not name and not price:
                continue
            
            # Skip if required fields are missing
            if not code or not name or not price:
                skipped_count += 1
                continue
            
            # Skip if product code already exists
            if Product.query.filter_by(product_code=code).first():
                skipped_count += 1
                continue
            
            # Handle image upload
            image_path = None
            if i < len(images) and images[i] and images[i].filename:
                if allowed_file(images[i].filename):
                    filename = secure_filename(f"{code}_{images[i].filename}")
                    images[i].save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_path = f"uploads/{filename}"
            
            # Get deposit amount
            deposit = 0
            if i < len(deposit_amounts) and deposit_amounts[i]:
                try:
                    deposit = float(deposit_amounts[i])
                except:
                    deposit = 0
            
            # Create product
            new_product = Product(
                product_code=code,
                name=name,
                rental_price=float(price),
                deposit_amount=deposit,
                image_path=image_path
            )
            db.session.add(new_product)
            added_count += 1
        
        if added_count > 0:
            db.session.commit()
            flash(f'{added_count} products added successfully!', 'success')
            if skipped_count > 0:
                flash(f'{skipped_count} products skipped (duplicate code or missing info)', 'warning')
        else:
            flash('No products were added. Please check your input.', 'error')
        
        return redirect(url_for('manage_products'))
    
    return render_template('bulk_add_products.html')

@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        product.product_code = request.form.get('product_code')
        product.name = request.form.get('name')
        product.rental_price = float(request.form.get('rental_price', 0))
        product.deposit_amount = float(request.form.get('deposit_amount', 0))
        
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{product.product_code}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                product.image_path = f"uploads/{filename}"
        
        db.session.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('manage_products'))
    
    return render_template('edit_product.html', product=product)

@app.route('/admin/products/toggle/<int:product_id>')
@login_required
@admin_required
def toggle_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    flash(f'Product {"activated" if product.is_active else "deactivated"} successfully', 'success')
    return redirect(url_for('manage_products'))

# Order Management
@app.route('/admin/orders')
@login_required
@admin_required
def manage_orders():
    search_query = request.args.get('search', '')
    date_filter = request.args.get('date', '')
    staff_filter = request.args.get('staff', '')
    
    query = Order.query
    
    if search_query:
        query = query.join(Order.items).join(OrderItem.product).filter(
            Product.product_code.ilike(f'%{search_query}%')
        )
    
    if date_filter:
        filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
        query = query.filter(
            db.or_(Order.delivery_date == filter_date, Order.return_date == filter_date)
        )
    
    if staff_filter:
        query = query.join(Order.staff).filter(User.name.ilike(f'%{staff_filter}%'))
    
    orders = query.order_by(Order.created_at.desc()).all()
    staff_list = User.query.filter_by(role='staff', is_active=True).all()
    
    return render_template('manage_orders.html', orders=orders, staff_list=staff_list)

@app.route('/admin/orders/status/<int:order_id>/<status>')
@login_required
@admin_required
def update_order_status(order_id, status):
    order = Order.query.get_or_404(order_id)
    order.status = status
    db.session.commit()
    flash(f'Order status updated to {status}', 'success')
    return redirect(url_for('manage_orders'))

@app.route('/admin/orders/edit/<int:order_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price': float(p.rental_price),
        'deposit_amount': float(p.deposit_amount),
        'image_path': p.image_path if p.image_path else ''
    } for p in products]
    
    if request.method == 'POST':
        # Update customer details
        order.customer.name = request.form.get('customer_name')
        order.customer.phone = request.form.get('customer_phone')
        order.customer.secondary_phone = request.form.get('secondary_phone')
        order.customer.email = request.form.get('customer_email')
        order.customer.address = request.form.get('customer_address')
        
        # Update order details
        order.delivery_date = datetime.strptime(request.form.get('delivery_date'), '%Y-%m-%d').date()
        order.return_date = datetime.strptime(request.form.get('return_date'), '%Y-%m-%d').date()
        order.notes = request.form.get('notes')
        
        # Update products
        OrderItem.query.filter_by(order_id=order.id).delete()
        product_ids = request.form.getlist('product_id[]')
        
        total = 0
        for pid in product_ids:
            if pid:
                product = Product.query.get(int(pid))
                if product:
                    item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        price=product.rental_price
                    )
                    db.session.add(item)
                    total += product.rental_price
        
        # Update accessories
        OrderAccessory.query.filter_by(order_id=order.id).delete()
        accessory_names = request.form.getlist('accessory_name[]')
        accessory_remarks = request.form.getlist('accessory_remarks[]')
        
        for i, name in enumerate(accessory_names):
            if name:
                accessory = OrderAccessory(
                    order_id=order.id,
                    accessory_name=name,
                    remarks=accessory_remarks[i] if i < len(accessory_remarks) else ''
                )
                db.session.add(accessory)
        
        # Update extra charges
        OrderExtraCharge.query.filter_by(order_id=order.id).delete()
        extra_desc = request.form.getlist('extra_description[]')
        extra_amounts = request.form.getlist('extra_amount[]')
        extra_remarks = request.form.getlist('extra_remarks[]')
        
        for i, desc in enumerate(extra_desc):
            if desc and extra_amounts[i]:
                extra = OrderExtraCharge(
                    order_id=order.id,
                    description=desc,
                    amount=float(extra_amounts[i]),
                    remarks=extra_remarks[i] if i < len(extra_remarks) else ''
                )
                db.session.add(extra)
                total += float(extra_amounts[i])
        
        order.total_amount = total
        db.session.commit()
        flash('Order updated successfully', 'success')
        return redirect(url_for('manage_orders'))
    
    return render_template('edit_order.html', order=order, products=products_data)

# Create Order
@app.route('/create-order', methods=['GET', 'POST'])
@login_required
def create_order():
    if request.method == 'POST':
        # Customer details
        customer_name = request.form.get('customer_name')
        customer_phone = request.form.get('customer_phone')
        secondary_phone = request.form.get('secondary_phone')
        customer_email = request.form.get('customer_email')
        customer_address = request.form.get('customer_address')
        
        delivery_date = datetime.strptime(request.form.get('delivery_date'), '%Y-%m-%d').date()
        return_date = datetime.strptime(request.form.get('return_date'), '%Y-%m-%d').date()
        notes = request.form.get('notes')
        
        product_ids = request.form.getlist('product_id[]')
        
        # Check for duplicate bookings
        for pid in product_ids:
            if pid:
                existing = db.session.query(OrderItem).join(Order).filter(
                    OrderItem.product_id == int(pid),
                    Order.status.in_(['pending', 'approved']),
                    db.or_(
                        db.and_(Order.delivery_date <= delivery_date, Order.return_date >= delivery_date),
                        db.and_(Order.delivery_date <= return_date, Order.return_date >= return_date),
                        db.and_(Order.delivery_date >= delivery_date, Order.return_date <= return_date)
                    )
                ).first()
                
                if existing:
                    product = Product.query.get(int(pid))
                    flash(f'Product {product.product_code} is already booked for these dates!', 'error')
                    return redirect(url_for('create_order'))
        
        # Create or get customer
        customer = Customer.query.filter_by(phone=customer_phone).first()
        if not customer:
            customer = Customer(
                name=customer_name,
                phone=customer_phone,
                secondary_phone=secondary_phone,
                email=customer_email,
                address=customer_address
            )
            db.session.add(customer)
            db.session.flush()
        else:
            customer.name = customer_name
            customer.secondary_phone = secondary_phone
            customer.email = customer_email
            customer.address = customer_address
        
        # Create order
        order = Order(
            transaction_id=str(uuid.uuid4())[:8].upper(),
            customer_id=customer.id,
            staff_id=current_user.id,
            delivery_date=delivery_date,
            return_date=return_date,
            notes=notes,
            status='pending'
        )
        db.session.add(order)
        db.session.flush()
        
        # Add products
        total = 0
        for pid in product_ids:
            if pid:
                product = Product.query.get(int(pid))
                if product:
                    item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        price=product.rental_price
                    )
                    db.session.add(item)
                    total += product.rental_price
        
        # Add accessories
        accessory_names = request.form.getlist('accessory_name[]')
        accessory_remarks = request.form.getlist('accessory_remarks[]')
        
        for i, name in enumerate(accessory_names):
            if name:
                accessory = OrderAccessory(
                    order_id=order.id,
                    accessory_name=name,
                    remarks=accessory_remarks[i] if i < len(accessory_remarks) else ''
                )
                db.session.add(accessory)
        
        # Add extra charges
        extra_desc = request.form.getlist('extra_description[]')
        extra_amounts = request.form.getlist('extra_amount[]')
        extra_remarks = request.form.getlist('extra_remarks[]')
        
        for i, desc in enumerate(extra_desc):
            if desc and extra_amounts[i]:
                extra = OrderExtraCharge(
                    order_id=order.id,
                    description=desc,
                    amount=float(extra_amounts[i]),
                    remarks=extra_remarks[i] if i < len(extra_remarks) else ''
                )
                db.session.add(extra)
                total += float(extra_amounts[i])
        
        order.total_amount = total
        
        # Create invoice
        invoice = Invoice(
            invoice_number=generate_invoice_number(),
            order_id=order.id
        )
        db.session.add(invoice)
        
        db.session.commit()
        flash('Order created successfully', 'success')
        return redirect(url_for('staff_dashboard') if current_user.role == 'staff' else url_for('manage_orders'))
    
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price': float(p.rental_price),
        'deposit_amount': float(p.deposit_amount),
        'image_path': p.image_path if p.image_path else ''
    } for p in products]
    
    return render_template('create_order.html', products=products_data)

# Add products to existing order (staff - only for pending orders they created)
@app.route('/order/<int:order_id>/add-products', methods=['GET', 'POST'])
@login_required
def add_products_to_order(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Check permissions - staff can only add to their own pending orders
    if current_user.role == 'staff':
        if order.staff_id != current_user.id:
            flash('You can only modify orders you created!', 'error')
            return redirect(url_for('staff_view_orders'))
        if order.staff.role == 'admin':
            flash('You cannot modify admin orders!', 'error')
            return redirect(url_for('staff_view_orders'))
    
    if order.status != 'pending':
        flash('Cannot modify approved orders', 'error')
        return redirect(url_for('staff_view_orders') if current_user.role == 'staff' else url_for('manage_orders'))
    
    if request.method == 'POST':
        product_ids = request.form.getlist('product_id[]')
        
        for pid in product_ids:
            if pid:
                existing = db.session.query(OrderItem).join(Order).filter(
                    OrderItem.product_id == int(pid),
                    Order.status.in_(['pending', 'approved']),
                    db.or_(
                        db.and_(Order.delivery_date <= order.delivery_date, Order.return_date >= order.delivery_date),
                        db.and_(Order.delivery_date <= order.return_date, Order.return_date >= order.return_date),
                        db.and_(Order.delivery_date >= order.delivery_date, Order.return_date <= order.return_date)
                    )
                ).first()
                
                if existing and existing.order_id != order.id:
                    product = Product.query.get(int(pid))
                    flash(f'Product {product.product_code} is already booked!', 'error')
                    continue
                
                if not OrderItem.query.filter_by(order_id=order.id, product_id=int(pid)).first():
                    product = Product.query.get(int(pid))
                    item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        price=product.rental_price
                    )
                    db.session.add(item)
                    order.total_amount += product.rental_price
        
        db.session.commit()
        flash('Products added successfully', 'success')
        return redirect(url_for('staff_view_orders'))
    
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price': float(p.rental_price),
        'deposit_amount': float(p.deposit_amount),
        'image_path': p.image_path if p.image_path else ''
    } for p in products]
    
    return render_template('add_products.html', order=order, products=products_data)

# Staff view all orders
@app.route('/staff/orders')
@login_required
def staff_view_orders():
    search_query = request.args.get('search', '')
    customer_query = request.args.get('customer', '')
    date_filter = request.args.get('date', '')
    
    query = Order.query
    
    if search_query:
        query = query.join(Order.items).join(OrderItem.product).filter(
            Product.product_code.ilike(f'%{search_query}%')
        )
    
    if customer_query:
        query = query.join(Order.customer).filter(
            db.or_(
                Customer.name.ilike(f'%{customer_query}%'),
                Customer.phone.ilike(f'%{customer_query}%')
            )
        )
    
    if date_filter:
        filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
        query = query.filter(
            db.or_(Order.delivery_date == filter_date, Order.return_date == filter_date)
        )
    
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('staff_view_orders.html', orders=orders)

# Staff edit their own order
@app.route('/staff/orders/edit/<int:order_id>', methods=['GET', 'POST'])
@login_required
def staff_edit_order(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Check if staff can edit this order
    # Staff can only edit their OWN orders that are PENDING
    if order.staff_id != current_user.id:
        flash('You can only edit orders you created!', 'error')
        return redirect(url_for('staff_view_orders'))
    
    if order.staff.role == 'admin':
        flash('You cannot edit admin orders!', 'error')
        return redirect(url_for('staff_view_orders'))
    
    if order.status != 'pending':
        flash('You can only edit pending orders!', 'error')
        return redirect(url_for('staff_view_orders'))
    
    if request.method == 'POST':
        # Update customer
        order.customer.name = request.form.get('customer_name')
        order.customer.phone = request.form.get('customer_phone')
        order.customer.secondary_phone = request.form.get('secondary_phone')
        order.customer.email = request.form.get('customer_email')
        order.customer.address = request.form.get('customer_address')
        
        # Update dates
        order.delivery_date = datetime.strptime(request.form.get('delivery_date'), '%Y-%m-%d')
        order.return_date = datetime.strptime(request.form.get('return_date'), '%Y-%m-%d')
        order.notes = request.form.get('notes')
        
        # Update products
        OrderItem.query.filter_by(order_id=order.id).delete()
        OrderAccessory.query.filter_by(order_id=order.id).delete()
        OrderExtraCharge.query.filter_by(order_id=order.id).delete()
        
        total = 0
        product_ids = request.form.getlist('product_id[]')
        for pid in product_ids:
            if pid:
                product = Product.query.get(int(pid))
                if product:
                    item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        price=product.rental_price
                    )
                    db.session.add(item)
                    total += product.rental_price
        
        # Update accessories
        acc_names = request.form.getlist('accessory_name[]')
        acc_remarks = request.form.getlist('accessory_remarks[]')
        for i, name in enumerate(acc_names):
            if name:
                acc = OrderAccessory(
                    order_id=order.id,
                    accessory_name=name,
                    remarks=acc_remarks[i] if i < len(acc_remarks) else ''
                )
                db.session.add(acc)
        
        # Update extra charges
        extra_desc = request.form.getlist('extra_description[]')
        extra_amounts = request.form.getlist('extra_amount[]')
        extra_remarks = request.form.getlist('extra_remarks[]')
        
        for i, desc in enumerate(extra_desc):
            if desc and extra_amounts[i]:
                extra = OrderExtraCharge(
                    order_id=order.id,
                    description=desc,
                    amount=float(extra_amounts[i]),
                    remarks=extra_remarks[i] if i < len(extra_remarks) else ''
                )
                db.session.add(extra)
                total += float(extra_amounts[i])
        
        order.total_amount = total
        db.session.commit()
        flash('Order updated successfully!', 'success')
        return redirect(url_for('staff_view_orders'))
    
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price': float(p.rental_price),
        'deposit_amount': float(p.deposit_amount),
        'image_path': p.image_path if p.image_path else ''
    } for p in products]
    
    return render_template('staff_edit_order.html', order=order, products=products_data)

# Check product availability
@app.route('/api/check-availability', methods=['POST'])
@login_required
def check_availability():
    data = request.get_json()
    product_code = data.get('product_code')
    
    product = Product.query.filter_by(product_code=product_code).first()
    if not product:
        return jsonify({'found': False, 'message': 'Product not found'})
    
    bookings = db.session.query(Order).join(OrderItem).filter(
        OrderItem.product_id == product.id,
        Order.status.in_(['pending', 'approved'])
    ).all()
    
    booking_info = [{
        'order_id': b.id,
        'delivery_date': b.delivery_date.strftime('%Y-%m-%d'),
        'return_date': b.return_date.strftime('%Y-%m-%d'),
        'status': b.status,
        'customer': b.customer.name
    } for b in bookings]
    
    return jsonify({
        'found': True,
        'product': {
            'code': product.product_code,
            'name': product.name,
            'price': product.rental_price
        },
        'bookings': booking_info,
        'is_available': len(booking_info) == 0
    })

# Get order details API
@app.route('/api/order-details/<int:order_id>')
@login_required
def get_order_details(order_id):
    order = Order.query.get_or_404(order_id)
    
    return jsonify({
        'id': order.id,
        'transaction_id': order.transaction_id,
        'customer': {
            'name': order.customer.name,
            'phone': order.customer.phone,
            'secondary_phone': order.customer.secondary_phone or '',
            'email': order.customer.email or '',
            'address': order.customer.address or ''
        },
        'staff': order.staff.name,
        'delivery_date': order.delivery_date.strftime('%d-%m-%Y'),
        'return_date': order.return_date.strftime('%d-%m-%Y'),
        'status': order.status,
        'total_amount': order.total_amount,
        'notes': order.notes or '',
        'items': [{
            'product_code': item.product.product_code,
            'product_name': item.product.name,
            'price': item.price,
            'image_path': item.product.image_path or ''
        } for item in order.items],
        'accessories': [{
            'name': acc.accessory_name,
            'remarks': acc.remarks or ''
        } for acc in order.accessories],
        'extra_charges': [{
            'description': extra.description,
            'amount': extra.amount,
            'remarks': extra.remarks or ''
        } for extra in order.extra_charges]
    })

# Invoice
@app.route('/order/<int:order_id>/invoice')
@login_required
def view_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    invoice = Invoice.query.filter_by(order_id=order_id).first()
    
    if not invoice:
        invoice = Invoice(
            invoice_number=generate_invoice_number(),
            order_id=order.id
        )
        db.session.add(invoice)
        db.session.commit()
    
    logo_exists = os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'logo.png'))
    
    return render_template('view_invoice.html', 
                         order=order, 
                         invoice=invoice,
                         logo_exists=logo_exists,
                         amount_in_words=amount_in_words(order.total_amount))

@app.route('/order/<int:order_id>/invoice/download')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    invoice = Invoice.query.filter_by(order_id=order_id).first()
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=(8.5*inch, 11*inch))
    width = 8.5 * inch
    
    # Header
    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width/2, 10.2*inch, "NERAA RENTAL HOUSE")
    
    p.setFont("Helvetica", 9)
    p.drawCentredString(width/2, 10*inch, "Contact: +91 95588 25555, +91 94294 29228")
    p.drawCentredString(width/2, 9.85*inch, "First Floor, Shivalay Complex, Near Vrajbhusan School,")
    p.drawCentredString(width/2, 9.7*inch, "Ranjitsagar Road, Jamnagar-361005, Gujarat")
    p.setFont("Helvetica-Bold", 9)
    p.drawCentredString(width/2, 9.55*inch, "GSTIN: 24PYIPS8703R1Z6")
    
    # Invoice details
    p.setFont("Helvetica-Bold", 12)
    p.drawString(0.5*inch, 9.2*inch, f"Invoice: {invoice.invoice_number}")
    p.drawRightString(8*inch, 9.2*inch, f"Date: {invoice.generated_at.strftime('%d-%m-%Y')}")
    
    # Customer details
    p.setFont("Helvetica-Bold", 10)
    p.drawString(0.5*inch, 8.9*inch, "Customer Details:")
    p.setFont("Helvetica", 10)
    p.drawString(0.5*inch, 8.7*inch, f"Name: {order.customer.name}")
    p.drawString(0.5*inch, 8.55*inch, f"Phone: {order.customer.phone}")
    if order.customer.secondary_phone:
        p.drawString(0.5*inch, 8.4*inch, f"Alt Phone: {order.customer.secondary_phone}")
    
    # Order details
    p.setFont("Helvetica-Bold", 10)
    p.drawString(4.5*inch, 8.9*inch, "Order Details:")
    p.setFont("Helvetica", 10)
    p.drawString(4.5*inch, 8.7*inch, f"Order ID: #{order.id}")
    p.drawString(4.5*inch, 8.55*inch, f"Delivery: {order.delivery_date.strftime('%d-%m-%Y')}")
    p.drawString(4.5*inch, 8.4*inch, f"Return: {order.return_date.strftime('%d-%m-%Y')}")
    
    # Products table - Only Product Code (No Name)
    y = 8.0*inch
    p.setFont("Helvetica-Bold", 10)
    p.drawString(0.5*inch, y, "Sr.")
    p.drawString(1.2*inch, y, "Product Code")
    p.drawRightString(7.5*inch, y, "Amount")
    
    p.line(0.5*inch, y-0.1*inch, 8*inch, y-0.1*inch)
    
    y -= 0.3*inch
    p.setFont("Helvetica", 10)
    for i, item in enumerate(order.items, 1):
        p.drawString(0.5*inch, y, str(i))
        p.drawString(1.2*inch, y, item.product.product_code)
        p.drawRightString(7.5*inch, y, f"Rs. {item.price:,.2f}")
        y -= 0.25*inch
    
    # Extra charges
    if order.extra_charges:
        y -= 0.1*inch
        p.setFont("Helvetica-Bold", 10)
        p.drawString(0.5*inch, y, "Extra Charges:")
        y -= 0.25*inch
        p.setFont("Helvetica", 10)
        for extra in order.extra_charges:
            p.drawString(1*inch, y, extra.description)
            p.drawRightString(7.5*inch, y, f"Rs. {extra.amount:,.2f}")
            y -= 0.25*inch
    
    # Accessories
    if order.accessories:
        y -= 0.1*inch
        p.setFont("Helvetica-Bold", 10)
        p.drawString(0.5*inch, y, "Accessories:")
        y -= 0.25*inch
        p.setFont("Helvetica", 10)
        for acc in order.accessories:
            p.drawString(1*inch, y, f"{acc.accessory_name}")
            if acc.remarks:
                p.drawString(4*inch, y, f"({acc.remarks})")
            y -= 0.25*inch
    
    # Total
    y -= 0.2*inch
    p.line(0.5*inch, y, 8*inch, y)
    y -= 0.3*inch
    p.setFont("Helvetica-Bold", 12)
    p.drawString(5*inch, y, "TOTAL AMOUNT:")
    p.drawRightString(7.5*inch, y, f"Rs. {order.total_amount:,.2f}")
    
    y -= 0.3*inch
    p.setFont("Helvetica", 9)
    p.drawString(0.5*inch, y, f"({amount_in_words(order.total_amount)})")
    
    # Footer
    p.setFont("Helvetica", 8)
    p.drawCentredString(width/2, 0.5*inch, "Thank you for choosing NERAA RENTAL HOUSE!")
    
    p.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Invoice_{invoice.invoice_number}.pdf",
        mimetype='application/pdf'
    )

# Packing Slip (3x2 inches)
@app.route('/order/<int:order_id>/packing-slip')
@login_required
@admin_required
def packing_slip(order_id):
    order = Order.query.get_or_404(order_id)
    invoice = Invoice.query.filter_by(order_id=order_id).first()
    return render_template('packing_slip.html', order=order, invoice=invoice)

@app.route('/order/<int:order_id>/packing-slip/download')
@login_required
@admin_required
def download_packing_slip(order_id):
    order = Order.query.get_or_404(order_id)
    invoice = Invoice.query.filter_by(order_id=order_id).first()
    
    # 3x2 inches
    slip_width = 3 * inch
    slip_height = 2 * inch
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=(slip_width, slip_height))
    
    # Header
    p.setFont("Helvetica-Bold", 8)
    p.drawCentredString(slip_width/2, 1.85*inch, "NERAA RENTAL HOUSE")
    
    p.setFont("Helvetica", 6)
    y = 1.7*inch
    
    # Bill number
    p.drawString(0.1*inch, y, f"Bill: {invoice.invoice_number if invoice else 'N/A'}")
    y -= 0.15*inch
    
    # Customer name
    p.drawString(0.1*inch, y, f"Customer: {order.customer.name[:20]}")
    y -= 0.15*inch
    
    # Dates
    p.drawString(0.1*inch, y, f"Delivery: {order.delivery_date.strftime('%d-%m-%Y')}")
    y -= 0.12*inch
    p.drawString(0.1*inch, y, f"Return: {order.return_date.strftime('%d-%m-%Y')}")
    y -= 0.15*inch
    
    # Products
    p.setFont("Helvetica-Bold", 6)
    p.drawString(0.1*inch, y, "Products:")
    y -= 0.12*inch
    p.setFont("Helvetica", 5)
    
    for item in order.items[:5]:  # Limit to 5 products for space
        p.drawString(0.1*inch, y, f"- {item.product.product_code}")
        y -= 0.1*inch
    
    # Accessories
    if order.accessories:
        y -= 0.05*inch
        p.setFont("Helvetica-Bold", 5)
        p.drawString(0.1*inch, y, "Accessories:")
        y -= 0.1*inch
        p.setFont("Helvetica", 5)
        for acc in order.accessories[:3]:
            p.drawString(0.1*inch, y, f"- {acc.accessory_name[:15]}")
            y -= 0.1*inch
    
    p.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"PackingSlip_{order.id}.pdf",
        mimetype='application/pdf'
    )

# Initialize database
def init_db():
    with app.app_context():
        db.create_all()
        
        # Create admin if not exists
        if not User.query.filter_by(email='admin@rental.com').first():
            admin = User(
                name='Admin',
                email='admin@rental.com',
                phone='0000000000',
                password_hash=generate_password_hash('admin123'),
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin account created: admin@rental.com / admin123")

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
