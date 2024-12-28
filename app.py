from flask import Flask, flash, render_template, request, redirect, url_for, session, jsonify
from itsdangerous import URLSafeTimedSerializer
import random
import psycopg2
import psycopg2.extras
import keyring
import os
import re
import bcrypt
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from psycopg2 import sql, errors
from math import ceil
from werkzeug.utils import secure_filename




# Fetching credentials from keyring
db_username = keyring.get_password('nne_shop', 'db_username')
db_password = keyring.get_password('nne_shop', 'db_password')

# Initializing Flask app
app = Flask(__name__, static_url_path='/static')

# Fetching the secret key from keyring
app.config['SECRET_KEY'] = keyring.get_password('nne_shop', 'secret_key')

# For local development, you can fall back on environment variables for other settings.
# For production, Heroku will provide these as config vars.
app.config['DB_HOST'] = os.getenv('DB_HOST', 'localhost')  # Use 'localhost' for local, configurable in Heroku
app.config['DB_PORT'] = os.getenv('DB_PORT', '5432')  # Default port for PostgreSQL

# Build the database connection string dynamically using credentials from keyring and environment variables
app.config['DB_CONN_STRING'] = f"dbname='nne_shop' user='{db_username}' password='{db_password}' host='{app.config['DB_HOST']}' port='{app.config['DB_PORT']}'"



# Function to get database connection
def get_db_connection():
    conn = psycopg2.connect(app.config['DB_CONN_STRING'])
    
    return conn






# Password validation function
def validate_password(password):
    # Regex to ensure password is 6 characters long, contains at least one number and one special character
    pattern = r'^(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{6,}$'  # Minimum 6 characters

    return re.match(pattern, password)



#Retrieve smtp configuration
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = os.environ.get('SMTP_PORT', '587')
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', 'shopwithsharpyglam@gmail.com')
SMTP_PASSWORD=keyring.get_password('smtp.gmail.com', SMTP_USERNAME)








@app.route('/')
def home():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT image_url, overlay_title, overlay_caption FROM slides")
    slides = cursor.fetchall()
   
    # Fetch trending products
    cursor.execute("SELECT id, name, description, image_url FROM products WHERE is_trending = TRUE")
    trending_products = cursor.fetchall()

    # Fetch deals of the day
    cursor.execute("""
        SELECT p.name, p.description, p.image_url, d.discount, d.expiry_time
        FROM deals d
        JOIN products p ON d.product_id = p.id
        WHERE d.expiry_time > NOW()
    """)
    deals = cursor.fetchall()

    # Fetch categories
    cursor.execute("SELECT id, name FROM categories")
    categories = cursor.fetchall()

    # Fetch testimonials
    cursor.execute("SELECT customer_name, comment FROM testimonials WHERE status = 'approved' ORDER BY created_at DESC LIMIT 5")
    testimonials = cursor.fetchall()


    conn.close()

    return render_template('index.html', slides=slides, trending_products=trending_products, deals=deals, categories=categories,
        testimonials=testimonials
    )




    
@app.route('/search')
def search():
    query = request.args.get('query', '').strip()
    if not query:
        return render_template('search.html', products=[])

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM products WHERE name ILIKE %s OR description ILIKE %s', (f'%{query}%', f'%{query}%'))
        results = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        flash(f'Database Error: (str{e})')
        results = []
    return render_template('search.html', products=results, query=query)



# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and bcrypt.checkpw(password.encode('utf-8'), user[3].encode('utf-8')):  # Assuming password is in the 4th column
            session['user_id'] = user[1]  # Store user ID in session
            
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')



# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))




# Utility function to send an email
def send_verification_email(email, code):
    message = MIMEText(f'Your verification code is: {code}')
    message['Subject'] = 'Verify Your Registration'
    message['From'] = SMTP_USERNAME
    message['To'] = email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, email, message.as_string())
        logging.info(f"Verification email sent to {email}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")





logging.basicConfig(level=logging.DEBUG)

# Register route (updated with password validation)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Check if passwords match
        if password != confirm_password:
            flash("Passwords do not match. Please try again.", "danger")
            return redirect(url_for('register'))

        # Validate password format
        if not validate_password(password):
            flash("Password must be at least 6 characters long, with at least one number and one special character.", "danger")
            return redirect(url_for('register'))

        # Hash the password and proceed with the rest of the registration logic
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        verification_code = str(random.randint(100000, 999999))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if username or email already exists
            cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", (username, email))
            if cursor.fetchone():
                flash("Username or email already exists. Please choose another one.", "danger")
                return redirect(url_for('register'))
            
            # Store pending verification data
            cursor.execute("""
                INSERT INTO user_verifications (username, email, hashed_password, verification_code)
                VALUES (%s, %s, %s, %s)
            """, (username, email, hashed_password.decode('utf-8'), verification_code))
            conn.commit()

            # Send verification email
            send_verification_email(email, verification_code)
            flash("A verification code has been sent to your email. Please verify to complete registration.", "info")
            return redirect(url_for('verify', email=email))
        except Exception as e:
            logging.error(f"Error during registration: {e}")
            flash(f"An error occurred: {str(e)}", "danger")
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')






# Route to verify the code
@app.route('/verify', methods=['GET', 'POST'])
def verify():
    email = request.args.get('email')
    if request.method == 'POST':
        code = request.form['code']

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM user_verifications WHERE email = %s AND verification_code = %s", (email, code))
            user_data = cursor.fetchone()
            if user_data and user_data[4] == code:
                
                
                # Move user to the main users table
                cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                (user_data[1], user_data[2], user_data[3]))
                cursor.execute("DELETE FROM user_verifications WHERE email = %s", (email,))
                
                conn.commit()
                
                # Send welcome email
                send_verification_email(user_data[1], "Welcome! Your account is now active. Do well to patronize us as we are poised to serve you even better.")
                
                flash("Account verified successfully! You can now log in.", "success")
                return redirect(url_for('login'))
            else:
                flash("Invalid verification code. Please try again.", "danger")
        except Exception as e:
            logging.error(f"Verification error: {e}")
            flash(f"An error occurred: {str(e)}", "danger")
        finally:
            cursor.close()
            conn.close()
    return render_template('verify.html', email=email)







@app.route('/shop')
def shop():
    # Retrieve query parameters
    category_filter = request.args.get('category')
    sort_by = request.args.get('sort_by', 'created_at')  # Default: sort by created_at
    sort_order = request.args.get('order', 'desc')       # Default: descending order
    page = int(request.args.get('page', 1))              # Default: first page
    per_page = 12                                        # Number of products per page

    # Build the SQL query
    query = "SELECT * FROM products"
    filters = []
    params = []

    # Filter by category
    if category_filter:
        filters.append("category = %s")
        params.append(category_filter)

    # Add filters to query
    if filters:
        query += " WHERE " + " AND ".join(filters)

    # Sort the results
    if sort_by in ['price', 'created_at'] and sort_order in ['asc', 'desc']:
        query += f" ORDER BY {sort_by} {sort_order}"

    # Pagination
    query += " LIMIT %s OFFSET %s"
    params.extend([per_page, (page - 1) * per_page])

    # Connect to database and execute query
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    products = cursor.fetchall()

    # Count total products for pagination
    count_query = "SELECT COUNT(*) FROM products"
    if filters:
        count_query += " WHERE " + " AND ".join(filters)
    cursor.execute(count_query, params[:len(filters)])
    total_products = cursor.fetchone()[0]

    # Close connection
    cursor.close()
    conn.close()

    # Calculate total pages
    total_pages = ceil(total_products / per_page)

    return render_template(
        'shop.html',
        products=products,
        categories=get_all_categories(),
        total_pages=total_pages,
        current_page=page,
        category_filter=category_filter,
        sort_by=sort_by,
        sort_order=sort_order
    )

# Helper function to fetch all categories for filtering
def get_all_categories():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM products")
    categories = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return categories

    




@app.route('/cart')
def cart():
    # Debug: Print the cart contents
    print("Cart contents at /cart:", session.get('cart', []))

    cart_items = session.get('cart', [])
    total_price = sum(item['price'] * item['quantity'] for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total_price=total_price)



@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    # Fetch product details
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()
    conn.close()

    if not product:
        flash("Product not found.", "error")
        return redirect(url_for('shop'))

    # Initialize cart if not exists
    if 'cart' not in session:
        session['cart'] = []

    # Debug: Print the cart before modification
    print("Cart before adding item:", session.get('cart', []))

    # Check if product already in cart
    for item in session['cart']:
        if item['id'] == product_id:
            flash("Product already in cart.", "info")
            return redirect(url_for('shop'))

    # Add product to cart
    session['cart'].append({
        'id': product[0],
        'name': product[1],
        'price': float(product[2]),
        'quantity': 1
    })

    # Debug: Print the cart after modification
    print("Cart after adding item:", session['cart'])

    session.modified = True
    flash("Product added to cart.", "success")
    return redirect(url_for('shop'))






@app.route('/update_cart/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    quantity = int(request.form['quantity'])
    if 'cart' in session:
        for item in session['cart']:
            if item['id'] == product_id:
                item['quantity'] = quantity
                session.modified = True
                flash("Cart updated.", "success")
                break
    return redirect(url_for('cart'))
@app.route('/remove_from_cart/<int:product_id>')



def remove_from_cart(product_id):
    if 'cart' in session:
        # Debug: Print cart before removal
        print("Cart before removing item:", session['cart'])

        session['cart'] = [item for item in session['cart'] if item['id'] != product_id]

        # Debug: Print cart after removal
        print("Cart after removing item:", session['cart'])

        session.modified = True
        flash("Item removed from cart.", "info")
    return redirect(url_for('cart'))



@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        # Capture customer details
        customer_name = request.form.get('customer_name')
        email = request.form.get('email')
        
        # Validate cart
        cart_items = session.get('cart', [])
        if not cart_items:
            flash("Your cart is empty. Add items before checkout.", "error")
            return redirect(url_for('cart'))

        # Calculate total price
        total_price = sum(item['price'] * item['quantity'] for item in cart_items)

        # Save order to database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO orders (customer_name, email, total_price) VALUES (%s, %s, %s) RETURNING id",
            (customer_name, email, total_price)
        )
        order_id = cursor.fetchone()[0]

        # Save order items
        for item in cart_items:
            cursor.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, item['id'], item['name'], item['quantity'], item['price'])
            )

            # Update product stock
            cursor.execute(
                "UPDATE products SET stock = stock - %s WHERE id = %s",
                (item['quantity'], item['id'])
            )

        conn.commit()
        conn.close()

        # Save order ID to session for payment processing
        session['order_id'] = order_id
        session.modified = True

        # Redirect to payment page
        return redirect(url_for('payment'))

    # If GET, display checkout page
    cart_items = session.get('cart', [])
    total_price = sum(item['price'] * item['quantity'] for item in cart_items)

    # Fetch email for the user from the session or database
    email = session.get('email')
    if not email and 'user_id' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE username = %s", (session['user_id'],))
        user = cursor.fetchone()
        email = user[0] if user else 'Email not available'
        conn.close()

    return render_template('checkout.html', cart_items=cart_items, total_price=total_price, email=email)



@app.route('/payment', methods=['GET', 'POST'])
def payment():
    order_id = session.get('order_id')

    # Ensure there's an order to pay for
    if not order_id:
        flash("No order found. Please complete the checkout process.", "error")
        return redirect(url_for('cart'))

    if request.method == 'POST':
        # Process payment (placeholder logic)
        payment_method = request.form.get('payment_method')

        # Simulate payment success
        flash("Payment successful! Thank you for your order.", "success")

        # Clear cart and session order ID
        session.pop('cart', None)
        session.pop('order_id', None)
        session.modified = True

        return redirect(url_for('order_confirmation'))

    # Fetch order details for display
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, total_price FROM orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    conn.close()

    return render_template('payment.html', order=order)


@app.route('/order_confirmation')
def order_confirmation():
    return render_template('order_confirmation.html')









@app.route('/manage_products', methods=['GET'])
def manage_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch filters
    category_filter = request.args.get('category', '')
    search_query = request.args.get('search', '')
    
    # Base query
    query = "SELECT id, name, category, price, stock, created_at FROM products WHERE 1=1"
    params = []
    
    # Apply category filter
    if category_filter:
        query += " AND category = %s"
        params.append(category_filter)
    
    # Apply search filter
    if search_query:
        query += " AND name ILIKE %s"
        params.append(f'%{search_query}%')
    
    query += " ORDER BY created_at DESC"
    
    cursor.execute(query, params)
    products = cursor.fetchall()
    
    # Fetch distinct categories
    cursor.execute("SELECT DISTINCT category FROM products")
    categories = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        'manage_products.html',
        products=products,
        categories=categories,
        category_filter=category_filter,
        search_query=search_query
    )
    
    
UPLOAD_FOLDER = 'static/uploads'  # Directory for uploaded images
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}  # Allowed image extensions

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    
    conn = get_db_connection()
    cursor = conn.cursor()
                
    # Fetch categories for the dropdown
    cursor.execute("SELECT id, name FROM categories")
    categories = cursor.fetchall()
    
    if request.method == 'POST':
        
        try:
            
            name = request.form['name']
            description = request.form['description']
            price = request.form['price']
            category_id = request.form['category']
            stock = request.form['stock']
            image = request.files['image']
            is_trending = request.form['is_trending']

            if image and allowed_file(image.filename):
                filename = secure_filename(image.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.save(image_path)  # Save image to the server
                
                # Save the relative path to the database (e.g., "static/uploads/filename.jpg")
                relative_path = os.path.join('static/uploads', filename)
                
                
                
                cursor.execute("""
                    INSERT INTO products (name, description, price, image_url, category, stock)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (name, description, price, relative_path, category_id, stock, is_trending))
                
                conn.commit()
            

            conn.close()
            flash('Product added successfully!', 'success')
            return redirect(url_for('manage_products'))
        except Exception as e:
            flash('Invalid file format. Please upload an image.', 'danger')
            return redirect(request.url)
    else:
        return render_template('add_product.html', categories=categories)



@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'GET':
        # Fetch the product details to pre-fill the form
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()

        if not product:
            flash("Product not found.", "error")
            return redirect(url_for('manage_products'))

        # Map database fields to a dictionary for easier usage in the template
        product_data = {
            'id': product[0],
            'name': product[1],
            'description': product[2],
            'price': product[3],
            'image_url': product[4],
            'category': product[5],
            'stock': product[6],
        }

        return render_template('edit_product.html', product=product_data)

    elif request.method == 'POST':
        # Get form data
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        category = request.form['category']
        stock = request.form['stock']

        # Handle image upload
        file = request.files['image']
        image_url = request.form.get('image_url', '')  # Default to existing image URL

        if file and allowed_file(file.filename):
            # Save the uploaded file
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Update product details in the database
        try:
            cursor.execute("""
                UPDATE products
                SET name = %s, description = %s, price = %s, image_url = %s, category = %s, stock = %s
                WHERE id = %s
            """, (name, description, price, image_url, category, stock, product_id))

            conn.commit()
            flash("Product updated successfully.", "success")
        except Exception as e:
            flash(f"Error updating product: {e}", "error")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('manage_products'))




@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    try:
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        conn.close()
    
        flash('Product deleted successfully!', 'success')
    except Exception as e:
        flash(f"Error: (str{e})", 'danger')
        return redirect(url_for('manage_products'))
    
    
    
@app.route('/submit-testimonial', methods=['GET', 'POST'])
def submit_testimonial():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name')
        comment = request.form.get('comment')

        if not customer_name or not comment:
            flash("All fields are required.", "error")
            return redirect(url_for('submit_testimonial'))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO testimonials (customer_name, comment, status) VALUES (%s, %s, %s)",
            (customer_name, comment, 'pending')
        )
        conn.commit()
        conn.close()

        flash("Thank you! Your testimonial has been submitted for review.", "success")
        return redirect(url_for('home'))

    return render_template('submit_testimonial.html')


@app.route('/manage-testimonials', methods=['GET', 'POST'])
def manage_testimonials():

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        testimonial_id = request.form.get('testimonial_id')
        action = request.form.get('action')

        if action == 'approve':
            cursor.execute("UPDATE testimonials SET status = 'approved' WHERE id = %s", (testimonial_id,))
        elif action == 'reject':
            cursor.execute("UPDATE testimonials SET status = 'rejected' WHERE id = %s", (testimonial_id,))
        
        conn.commit()
        flash("Testimonial updated successfully!", "success")

    cursor.execute("SELECT id, customer_name, comment, status FROM testimonials WHERE status = 'pending'")
    pending_testimonials = cursor.fetchall()
    conn.close()

    return render_template('manage_testimonials.html', pending_testimonials=pending_testimonials)


@app.route('/manage-categories', methods=['GET', 'POST'])
def manage_categories():
    # Restrict to admins

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name')

        # Check if the category already exists
        cursor.execute("SELECT id FROM categories WHERE name = %s", (name,))
        if cursor.fetchone():
            flash("Category already exists!", "error")
        else:
            # Insert category into the database
            cursor.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
            conn.commit()
            flash("Category added successfully!", "success")

    # Fetch all categories
    cursor.execute("SELECT * FROM categories ORDER BY name ASC")
    categories = cursor.fetchall()
    conn.close()

    return render_template('manage_categories.html', categories=categories)

    



#Clear Database table entries

@app.route('/clear_table', methods=['GET', 'POST'])
def clear_table():
    if request.method == 'POST':
        table_name = request.form['table_name']

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Clear all entries from the specified table
            query = sql.SQL("DELETE FROM {}").format(sql.Identifier(table_name))
            cursor.execute(query)
            conn.commit()
            
            flash(f"All entries from '{table_name}' have been deleted successfully.", "success")
        except psycopg2.Error as e:
            conn.rollback()
            flash(f"Error: {str(e)}", "danger")
        finally:
            if conn:
                cursor.close()
                conn.close()
        
        return redirect(url_for('clear_table'))
    
    return render_template('clear_table.html')






@app.route('/admin-dashboard')
def admin_dashboard():
    
    if not session.get('is_admin'):
        flash("Unauthorized access. Admins only.", "error")
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html')



@app.route('/create-admin', methods=['GET', 'POST'])
def create_admin():

    if request.method == 'POST':
        # Get admin details
        username = request.form['username']
        password = request.form['password']

        # Hash the password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        email = ''

        # Insert into the database with is_admin=True
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password, email, is_admin) VALUES (%s, %s, %s, %s)",
                (username, hashed_password, email, True)
            )
            conn.commit()
            flash("Admin account created successfully.", "success")
        except Exception as e:
            conn.rollback()
            flash("Error creating admin account: {}".format(str(e)), "error")
        finally:
            conn.close()
        return redirect(url_for('admin_dashboard'))  # Redirect to admin dashboard after creation

    # Render admin creation form
    return render_template('create_admin.html')


@app.route('/manage-slides', methods=['GET', 'POST'])
def manage_slides():

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if 'image' in request.files:  # Adding a new slide
            file = request.files.get('image')
            title = request.form.get('overlay_title')
            caption = request.form.get('overlay_caption')
            
            if file:
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)  # Save the uploaded image
                
                # Insert slide details into the database
                cursor.execute(
                    "INSERT INTO slides (image_url, overlay_title, overlay_caption) VALUES (%s, %s, %s)",
                    (f'/static/images/{filename}', title, caption)
                )
                conn.commit()
                flash("Slide added successfully!", "success")

        elif 'slide_id' in request.form:  # Removing a slide
            slide_id = request.form.get('slide_id')
            
            # Remove slide from database
            cursor.execute("DELETE FROM slides WHERE id = %s", (slide_id,))
            conn.commit()
            flash("Slide removed successfully!", "success")

    # Retrieve all slides for display
    cursor.execute("SELECT id, image_url, overlay_title, overlay_caption FROM slides")
    slides = cursor.fetchall()
    conn.close()

    return render_template('manage_slides.html', slides=slides)



if __name__ == '__main__':
    app.run(debug=True)
