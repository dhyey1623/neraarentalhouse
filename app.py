from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import os
import uuid
import io

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rental_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload folder if not exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ==================== DATABASE MODELS ====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin' or 'staff'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    rental_price_daily = db.Column(db.Float, nullable=False)
    deposit_amount = db.Column(db.Float, default=0)
    image_path = db.Column(db.String(200))
    sizes_available = db.Column(db.JSON)  # {'S': 3, 'M': 5, 'L': 2}
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OrderProduct(db.Model):
    __tablename__ = 'order_products'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product_size = db.Column(db.String(10))
    quantity = db.Column(db.Integer, default=1)
    price = db.Column(db.Float)
    
    product = db.relationship('Product', backref='order_items')


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(36), unique=True, nullable=False)
    
    # Customer details
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(120))
    customer_phone = db.Column(db.String(20), nullable=False)
    customer_address = db.Column(db.Text)
    
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    delivery_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, delivered, returned, completed, canceled
    rental_days = db.Column(db.Integer)
    total_amount = db.Column(db.Float)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    products = db.relationship('OrderProduct', backref='order', lazy=True, cascade='all, delete-orphan')
    staff = db.relationship('User', backref='orders')


class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    invoice_number = db.Column(db.String(20), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='pending')
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    order = db.relationship('Order', backref='invoices')


# ==================== LOGIN MANAGER ====================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ==================== DECORATORS ====================

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role != role and current_user.role != 'admin':
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== HELPER FUNCTIONS ====================

def amount_in_words(amount):
    """Convert amount to words (Indian format)"""
    try:
        # Simple conversion - you can enhance this
        units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
        teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        
        amount = int(amount)
        if amount == 0:
            return "Zero Rupees"
        
        def convert_hundreds(n):
            if n == 0:
                return ""
            elif n < 10:
                return units[n]
            elif n < 20:
                return teens[n - 10]
            elif n < 100:
                return tens[n // 10] + (" " + units[n % 10] if n % 10 != 0 else "")
            else:
                return units[n // 100] + " Hundred" + (" " + convert_hundreds(n % 100) if n % 100 != 0 else "")
        
        if amount < 1000:
            return convert_hundreds(amount) + " Rupees"
        elif amount < 100000:
            thousands = amount // 1000
            hundreds = amount % 1000
            result = convert_hundreds(thousands) + " Thousand"
            if hundreds > 0:
                result += " " + convert_hundreds(hundreds)
            return result + " Rupees"
        elif amount < 10000000:
            lakhs = amount // 100000
            remainder = amount % 100000
            result = convert_hundreds(lakhs) + " Lakh"
            if remainder >= 1000:
                result += " " + convert_hundreds(remainder // 1000) + " Thousand"
            if remainder % 1000 > 0:
                result += " " + convert_hundreds(remainder % 1000)
            return result + " Rupees"
        else:
            return "Amount too large"
    except:
        return "Amount conversion error"


def check_product_availability(product_id, delivery_date, return_date, exclude_order_id=None):
    """Check if product is available for given date range"""
    query = Order.query.filter(
        Order.status.in_(['pending', 'approved', 'delivered'])
    ).join(OrderProduct).filter(
        OrderProduct.product_id == product_id,
        Order.return_date >= delivery_date,
        Order.delivery_date <= return_date
    )
    
    if exclude_order_id:
        query = query.filter(Order.id != exclude_order_id)
    
    return query.first() is None


def generate_invoice_pdf(order):
    """Generate PDF invoice matching web design"""
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Draw outer border
    p.setLineWidth(2)
    p.rect(0.5*inch, 0.5*inch, width-1*inch, height-1*inch)
    
    # Header Section with border
    p.setLineWidth(1.5)
    p.rect(0.5*inch, height-2*inch, width-1*inch, 1.5*inch)
    
    # Company Name - Large and Bold
    p.setFont("Helvetica-Bold", 22)
    p.drawCentredString(width/2, height-0.9*inch, "NERAA RENTAL HOUSE")
    
    # Contact Details
    p.setFont("Helvetica", 9)
    p.drawCentredString(width/2, height-1.1*inch, "Contact: +91 95588 25555, +91 94294 29228")
    p.setFont("Helvetica", 8)
    p.drawCentredString(width/2, height-1.25*inch, "First Floor, Shivalay Complex, Near Vrajbhusan School")
    p.drawCentredString(width/2, height-1.4*inch, "Ranjitsagar Road, Jamnagar-361005, Gujarat")
    
    # INVOICE title - top right
    p.setFont("Helvetica-Bold", 16)
    p.drawRightString(width-0.7*inch, height-0.9*inch, "INVOICE")
    
    # Invoice details - top right
    p.setFont("Helvetica", 9)
    p.drawRightString(width-0.7*inch, height-1.15*inch, f"Invoice #: INV-{order.id:05d}")
    p.drawRightString(width-0.7*inch, height-1.3*inch, f"Date: {order.created_at.strftime('%d-%m-%Y')}")
    
    # Customer Details Box
    y_start = height - 2.3*inch
    box_height = 1.1*inch
    
    # Left box - Customer Details
    p.setLineWidth(1)
    p.rect(0.6*inch, y_start-box_height, 3.3*inch, box_height)
    
    p.setFont("Helvetica-Bold", 11)
    p.drawString(0.75*inch, y_start-0.25*inch, "CUSTOMER DETAILS")
    
    p.setFont("Helvetica", 9)
    y_pos = y_start - 0.45*inch
    p.drawString(0.75*inch, y_pos, f"Name: {order.customer_name}")
    y_pos -= 0.18*inch
    p.drawString(0.75*inch, y_pos, f"Phone: {order.customer_phone}")
    if order.customer_email:
        y_pos -= 0.18*inch
        p.drawString(0.75*inch, y_pos, f"Email: {order.customer_email}")
    if order.customer_address and len(order.customer_address) < 50:
        y_pos -= 0.18*inch
        p.drawString(0.75*inch, y_pos, f"Address: {order.customer_address[:45]}")
    
    # Right box - Order Details
    p.rect(4.1*inch, y_start-box_height, 3.4*inch, box_height)
    
    p.setFont("Helvetica-Bold", 11)
    p.drawString(4.25*inch, y_start-0.25*inch, "ORDER DETAILS")
    
    p.setFont("Helvetica", 9)
    y_pos = y_start - 0.45*inch
    p.drawString(4.25*inch, y_pos, f"Order ID: #{order.id}")
    y_pos -= 0.18*inch
    p.drawString(4.25*inch, y_pos, f"Delivery: {order.delivery_date.strftime('%d-%m-%Y')}")
    y_pos -= 0.18*inch
    p.drawString(4.25*inch, y_pos, f"Return: {order.return_date.strftime('%d-%m-%Y')}")
    y_pos -= 0.18*inch
    p.drawString(4.25*inch, y_pos, f"Rental Days: {order.rental_days} days")
    
    # Products Table
    table_top = y_start - box_height - 0.4*inch
    row_height = 0.35*inch
    
    # Table border
    table_rows = len(order.products) + 1  # +1 for header
    table_height = row_height * table_rows
    p.setLineWidth(1.5)
    p.rect(0.6*inch, table_top - table_height, width-1.2*inch, table_height)
    
    # Table Header (Black background)
    p.setFillColorRGB(0, 0, 0)
    p.rect(0.6*inch, table_top - row_height, width-1.2*inch, row_height, fill=1)
    
    # Header text (White)
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 10)
    header_y = table_top - 0.23*inch
    p.drawString(0.75*inch, header_y, "Sr.")
    p.drawString(1.2*inch, header_y, "Product Details")
    p.drawString(3.8*inch, header_y, "Size")
    p.drawString(4.5*inch, header_y, "Days")
    p.drawString(5.3*inch, header_y, "Rate/Day")
    p.drawString(6.5*inch, header_y, "Amount")
    
    # Reset to black for table content
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 9)
    
    # Draw horizontal lines and product rows
    current_y = table_top - row_height
    for idx, item in enumerate(order.products, 1):
        # Draw horizontal line
        p.setLineWidth(0.5)
        p.line(0.6*inch, current_y, width-0.6*inch, current_y)
        
        # Product row
        row_y = current_y - 0.23*inch
        p.drawString(0.75*inch, row_y, str(idx))
        
        # Product name and code
        product_name = item.product.name[:30] + "..." if len(item.product.name) > 30 else item.product.name
        p.setFont("Helvetica-Bold", 9)
        p.drawString(1.2*inch, row_y + 0.05*inch, product_name)
        p.setFont("Helvetica", 8)
        p.drawString(1.2*inch, row_y - 0.08*inch, f"Code: {item.product.product_code}")
        
        p.setFont("Helvetica", 9)
        p.drawString(3.9*inch, row_y, item.product_size)
        p.drawString(4.6*inch, row_y, str(order.rental_days))
        p.drawRightString(6.2*inch, row_y, f"Rs.{item.product.rental_price_daily:.2f}")
        p.setFont("Helvetica-Bold", 9)
        p.drawRightString(7.3*inch, row_y, f"Rs.{item.price:.2f}")
        
        current_y -= row_height
    
    # Total Section (Grey background box)
    total_box_y = current_y - 0.5*inch
    p.setFillColorRGB(0.95, 0.95, 0.95)
    p.rect(0.6*inch, total_box_y - 0.5*inch, width-1.2*inch, 0.5*inch, fill=1)
    
    # Total Amount
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(4.2*inch, total_box_y - 0.3*inch, "TOTAL AMOUNT:")
    p.setFont("Helvetica-Bold", 16)
    p.drawRightString(7.3*inch, total_box_y - 0.3*inch, f"Rs.{order.total_amount:.2f}")
    
    # Amount in words
    amount_words_y = total_box_y - 0.8*inch
    p.setFont("Helvetica", 8)
    amount_words = amount_in_words(order.total_amount)
    p.drawRightString(7.3*inch, amount_words_y, f"Amount in words: {amount_words}")
    
    # Terms & Conditions
    terms_y = amount_words_y - 0.4*inch
    p.setFont("Helvetica-Bold", 10)
    p.drawString(0.75*inch, terms_y, "Terms & Conditions:")
    p.setFont("Helvetica", 8)
    terms_y -= 0.18*inch
    p.drawString(0.75*inch, terms_y, "")
    terms_y -= 0.15*inch
    p.drawString(0.75*inch, terms_y, "• Any damage to the rented items will be charged separately")
    terms_y -= 0.15*inch
    p.drawString(0.75*inch, terms_y, "• Items must be returned on or before the return date")
    terms_y -= 0.15*inch
    p.drawString(0.75*inch, terms_y, "• Late returns will incur additional charges")
    
    # Signature Section
    sig_y = 1.8*inch
    p.setFont("Helvetica", 10)
    p.drawString(1*inch, sig_y, "Customer Signature")
    p.drawString(5.5*inch, sig_y, "Authorized Signature")
    
    # Signature lines
    p.setLineWidth(1)
    p.line(1*inch, sig_y - 0.7*inch, 2.5*inch, sig_y - 0.7*inch)
    p.line(5.5*inch, sig_y - 0.7*inch, 7*inch, sig_y - 0.7*inch)
    
    # Company name under authorized signature
    p.setFont("Helvetica-Bold", 10)
    p.drawString(5.5*inch, sig_y - 0.95*inch, "NERAA RENTAL HOUSE")
    
    # Footer
    p.setFont("Helvetica", 10)
    p.drawCentredString(width/2, 0.9*inch, "Thank you for your business!")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


# ==================== AUTHENTICATION ROUTES ====================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password, or account is inactive.', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ==================== DASHBOARD ====================

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status='pending').count()
        total_staff = User.query.filter_by(role='staff').count()
        total_products = Product.query.filter_by(is_active=True).count()
        recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
        
        return render_template('admin_dashboard.html', 
                             total_orders=total_orders,
                             pending_orders=pending_orders,
                             total_staff=total_staff,
                             total_products=total_products,
                             recent_orders=recent_orders)
    else:
        # Staff dashboard - show monthly stats
        today = datetime.now()
        first_day = today.replace(day=1)
        
        monthly_orders = Order.query.filter(
            Order.staff_id == current_user.id,
            Order.created_at >= first_day
        ).count()
        
        monthly_revenue = db.session.query(db.func.sum(Order.total_amount)).filter(
            Order.staff_id == current_user.id,
            Order.created_at >= first_day,
            Order.status.in_(['approved', 'delivered', 'completed'])
        ).scalar() or 0
        
        my_orders = Order.query.filter_by(staff_id=current_user.id).order_by(Order.created_at.desc()).limit(10).all()
        
        return render_template('staff_dashboard.html', 
                             monthly_orders=monthly_orders,
                             monthly_revenue=monthly_revenue,
                             my_orders=my_orders)


# ==================== ADMIN ROUTES ====================

@app.route('/admin/staff', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_staff():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('User with this email already exists.', 'danger')
        else:
            new_user = User(name=name, email=email, phone=phone, role='staff')
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Staff member {name} created successfully!', 'success')
            return redirect(url_for('manage_staff'))
    
    staff_members = User.query.filter_by(role='staff').all()
    return render_template('manage_staff.html', staff_members=staff_members)


@app.route('/admin/staff/toggle/<int:user_id>')
@login_required
@role_required('admin')
def toggle_staff(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot deactivate admin accounts.', 'danger')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        status = 'activated' if user.is_active else 'deactivated'
        flash(f'Staff member {user.name} has been {status}.', 'success')
    return redirect(url_for('manage_staff'))


@app.route('/admin/products', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_products():
    if request.method == 'POST':
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_path = f"uploads/{filename}"
        
        product = Product(
            product_code=request.form.get('product_code'),
            name=request.form.get('name'),
            rental_price_daily=float(request.form.get('rental_price_daily')),
            deposit_amount=float(request.form.get('deposit_amount', 0)),
            image_path=image_path,
            sizes_available={'S': 0, 'M': 0, 'L': 0, 'XL': 0}
        )
        db.session.add(product)
        db.session.commit()
        flash(f'Product {product.name} added successfully!', 'success')
        return redirect(url_for('manage_products'))
    
    products = Product.query.filter_by(is_active=True).all()
    return render_template('manage_products.html', products=products)


@app.route('/admin/products/bulk', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def bulk_add_products():
    if request.method == 'POST':
        product_count = int(request.form.get('product_count', 1))
        added_count = 0
        
        for i in range(product_count):
            product_code = request.form.get(f'product_code_{i}')
            name = request.form.get(f'name_{i}')
            price = request.form.get(f'rental_price_daily_{i}')
            deposit = request.form.get(f'deposit_amount_{i}', 0)
            
            if product_code and name and price:
                # Check if product code already exists
                if Product.query.filter_by(product_code=product_code).first():
                    flash(f'Product code {product_code} already exists. Skipped.', 'warning')
                    continue
                
                image_path = None
                if f'image_{i}' in request.files:
                    file = request.files[f'image_{i}']
                    if file and file.filename:
                        filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        image_path = f"uploads/{filename}"
                
                product = Product(
                    product_code=product_code,
                    name=name,
                    rental_price_daily=float(price),
                    deposit_amount=float(deposit),
                    image_path=image_path,
                    sizes_available={'S': 0, 'M': 0, 'L': 0, 'XL': 0}
                )
                db.session.add(product)
                added_count += 1
        
        db.session.commit()
        flash(f'{added_count} products added successfully!', 'success')
        return redirect(url_for('manage_products'))
    
    return render_template('bulk_add_products.html')


@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        product.product_code = request.form.get('product_code')
        product.name = request.form.get('name')
        product.rental_price_daily = float(request.form.get('rental_price_daily'))
        product.deposit_amount = float(request.form.get('deposit_amount', 0))
        
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                product.image_path = f"uploads/{filename}"
        
        db.session.commit()
        flash(f'Product {product.name} updated successfully!', 'success')
        return redirect(url_for('manage_products'))
    
    return render_template('edit_product.html', product=product)


@app.route('/admin/orders')
@login_required
@role_required('admin')
def manage_orders():
    status_filter = request.args.get('status', 'all')
    search = request.args.get('search', '')
    search_type = request.args.get('search_type', 'product')
    
    query = Order.query
    
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    if search:
        if search_type == 'product':
            query = query.join(OrderProduct).join(Product).filter(Product.product_code.contains(search))
        elif search_type == 'staff':
            query = query.join(User).filter(User.name.contains(search))
        elif search_type == 'date':
            try:
                search_date = datetime.strptime(search, '%Y-%m-%d').date()
                query = query.filter(
                    (Order.delivery_date == search_date) | (Order.return_date == search_date)
                )
            except:
                pass
    
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('manage_orders.html', orders=orders, status_filter=status_filter)


@app.route('/staff/orders')
@login_required
def staff_view_orders():
    """Staff can view all orders (read-only)"""
    status_filter = request.args.get('status', 'all')
    
    if status_filter == 'all':
        orders = Order.query.order_by(Order.created_at.desc()).all()
    else:
        orders = Order.query.filter_by(status=status_filter).order_by(Order.created_at.desc()).all()
    
    return render_template('staff_view_orders.html', orders=orders, status_filter=status_filter)


@app.route('/admin/orders/edit/<int:order_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)
    
    if request.method == 'POST':
        try:
            # Update customer details
            order.customer_name = request.form.get('customer_name')
            order.customer_phone = request.form.get('customer_phone')
            order.customer_email = request.form.get('customer_email')
            order.customer_address = request.form.get('customer_address')
            
            # Update dates
            order.delivery_date = datetime.strptime(request.form.get('delivery_date'), '%Y-%m-%d').date()
            order.return_date = datetime.strptime(request.form.get('return_date'), '%Y-%m-%d').date()
            order.rental_days = (order.return_date - order.delivery_date).days
            order.notes = request.form.get('notes')
            
            # Delete existing products
            OrderProduct.query.filter_by(order_id=order.id).delete()
            
            # Add updated products
            product_ids = request.form.getlist('product_id[]')
            product_sizes = request.form.getlist('product_size[]')
            
            total_amount = 0
            for i, product_id in enumerate(product_ids):
                product = Product.query.get(product_id)
                price = order.rental_days * product.rental_price_daily
                
                order_product = OrderProduct(
                    order_id=order.id,
                    product_id=product_id,
                    product_size=product_sizes[i],
                    price=price
                )
                db.session.add(order_product)
                total_amount += price
            
            order.total_amount = total_amount
            
            db.session.commit()
            flash(f'Order #{order.id} updated successfully!', 'success')
            return redirect(url_for('manage_orders'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating order: {str(e)}', 'danger')
    
    # Convert products to JSON-serializable format
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price_daily': float(p.rental_price_daily),
        'deposit_amount': float(p.deposit_amount)
    } for p in products]
    
    staff_members = User.query.filter_by(role='staff').all()
    return render_template('edit_order.html', order=order, products=products_data, staff_members=staff_members)


@app.route('/admin/orders/update/<int:order_id>', methods=['POST'])
@login_required
@role_required('admin')
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    order.status = new_status
    db.session.commit()
    flash(f'Order #{order.id} status updated to {new_status}.', 'success')
    return redirect(url_for('manage_orders'))


@app.route('/orders/view-invoice/<int:order_id>')
@login_required
def view_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    logo_exists = os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'logo.png'))
    return render_template('view_invoice.html', order=order, logo_exists=logo_exists, amount_in_words=amount_in_words)


@app.route('/orders/download-invoice/<int:order_id>')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    pdf_buffer = generate_invoice_pdf(order)
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'invoice_{order.id}.pdf'
    )


# ==================== STAFF & ADMIN ORDER ROUTES ====================

@app.route('/orders/create', methods=['GET', 'POST'])
@login_required
def create_order():
    if request.method == 'POST':
        try:
            # Get customer details
            customer_name = request.form.get('customer_name')
            customer_phone = request.form.get('customer_phone')
            customer_email = request.form.get('customer_email')
            customer_address = request.form.get('customer_address')
            
            delivery_date = datetime.strptime(request.form.get('delivery_date'), '%Y-%m-%d').date()
            return_date = datetime.strptime(request.form.get('return_date'), '%Y-%m-%d').date()
            rental_days = (return_date - delivery_date).days
            
            # Get products
            product_ids = request.form.getlist('product_id[]')
            product_sizes = request.form.getlist('product_size[]')
            
            if not product_ids:
                flash('Please add at least one product to the order.', 'danger')
                return redirect(url_for('create_order'))
            
            # Check product availability for all products
            for product_id in product_ids:
                if not check_product_availability(product_id, delivery_date, return_date):
                    product = Product.query.get(product_id)
                    flash(f'Product "{product.name}" is already booked for these dates. Please select different dates.', 'danger')
                    return redirect(url_for('create_order'))
            
            # Calculate total - deposit is NOT added to rental cost
            total_amount = 0
            for i, product_id in enumerate(product_ids):
                product = Product.query.get(product_id)
                # Only rental cost: days × daily_price
                total_amount += (rental_days * product.rental_price_daily)
            
            # Create order
            new_order = Order(
                transaction_id=str(uuid.uuid4()),
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                customer_address=customer_address,
                staff_id=current_user.id,
                delivery_date=delivery_date,
                return_date=return_date,
                rental_days=rental_days,
                total_amount=total_amount,
                status='pending'
            )
            
            db.session.add(new_order)
            db.session.flush()
            
            # Add products
            for i, product_id in enumerate(product_ids):
                product = Product.query.get(product_id)
                order_product = OrderProduct(
                    order_id=new_order.id,
                    product_id=product_id,
                    product_size=product_sizes[i],
                    price=(rental_days * product.rental_price_daily)  # Only rental cost
                )
                db.session.add(order_product)
            
            db.session.commit()
            
            flash(f'Order created successfully! Order ID: #{new_order.id}', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating order: {str(e)}', 'danger')
    
    # Convert products to JSON-serializable format
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price_daily': float(p.rental_price_daily),
        'deposit_amount': float(p.deposit_amount),
        'image_path': p.image_path if p.image_path else ''
    } for p in products]
    
    return render_template('create_order.html', products=products_data)


@app.route('/orders/add-products/<int:order_id>', methods=['GET', 'POST'])
@login_required
def add_products_to_order(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Only allow adding products to pending orders
    if order.status not in ['pending']:
        flash('Cannot add products to approved orders.', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        try:
            product_ids = request.form.getlist('product_id[]')
            product_sizes = request.form.getlist('product_size[]')
            
            # Check availability
            for product_id in product_ids:
                if not check_product_availability(product_id, order.delivery_date, order.return_date, order.id):
                    product = Product.query.get(product_id)
                    flash(f'Product "{product.name}" is already booked for these dates.', 'danger')
                    return redirect(url_for('add_products_to_order', order_id=order_id))
            
            # Add products
            for i, product_id in enumerate(product_ids):
                product = Product.query.get(product_id)
                order_product = OrderProduct(
                    order_id=order.id,
                    product_id=product_id,
                    product_size=product_sizes[i],
                    price=(order.rental_days * product.rental_price_daily) + product.deposit_amount
                )
                db.session.add(order_product)
                order.total_amount += order_product.price
            
            db.session.commit()
            flash(f'Products added to order #{order.id} successfully!', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding products: {str(e)}', 'danger')
    
    # Convert products to JSON-serializable format
    products = Product.query.filter_by(is_active=True).all()
    products_data = [{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'rental_price_daily': float(p.rental_price_daily),
        'deposit_amount': float(p.deposit_amount),
        'image_path': p.image_path if p.image_path else ''
    } for p in products]
    
    return render_template('add_products.html', order=order, products=products_data)


# ==================== API ENDPOINTS ====================

@app.route('/api/products/search', methods=['GET'])
@login_required
def search_products():
    search = request.args.get('search', '')
    products = Product.query.filter(
        Product.is_active == True,
        (Product.product_code.contains(search) | Product.name.contains(search))
    ).limit(20).all()
    
    return jsonify([{
        'id': p.id,
        'product_code': p.product_code,
        'name': p.name,
        'price': p.rental_price_daily,
        'deposit': p.deposit_amount,
        'image': p.image_path
    } for p in products])


@app.route('/api/check-availability', methods=['POST'])
@login_required
def check_availability():
    data = request.get_json()
    product_id = data.get('product_id')
    start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
    end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
    
    available = check_product_availability(product_id, start_date, end_date)
    
    return jsonify({
        'available': available,
        'message': 'Product is available' if available else 'Product already booked for these dates'
    })


# ==================== INITIALIZE DATABASE ====================

@app.before_request
def create_tables():
    db.create_all()
    
    # Create default admin if not exists
    if not User.query.filter_by(email='admin@rental.com').first():
        admin = User(
            name='System Admin',
            email='admin@rental.com',
            phone='1234567890',
            role='admin'
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Default admin created: admin@rental.com / admin123")


if __name__ == '__main__':
    app.run(debug=True, port=5000)