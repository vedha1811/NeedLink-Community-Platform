from werkzeug.utils import secure_filename
import os
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
import re
import firebase_admin
from firebase_admin import credentials, firestore
import smtplib
from email.mime.text import MIMEText
import random
import time
from datetime import datetime
from math import radians, cos, sin, asin, sqrt
from email.mime.multipart import MIMEMultipart


def send_otp_email(receiver_email, otp):
    sender_email = "needlink8@gmail.com"
    app_password = "sbslocjotzrxyzoi"

    msg = MIMEText(f"Your OTP is: {otp}")
    msg['Subject'] = "NeedLink OTP"
    msg['From'] = sender_email
    msg['To'] = receiver_email

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
# -------------------------------
# Generic Email Sender
# -------------------------------
def send_email(receiver, subject, body):

    sender_email = "needlink8@gmail.com"

    sender_password = "sbslocjotzrxyzoi"

    msg = MIMEMultipart()

    msg['From'] = sender_email
    msg['To'] = receiver
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:

        server = smtplib.SMTP('smtp.gmail.com', 587)

        server.starttls()

        server.login(sender_email, sender_password)

        server.send_message(msg)

        server.quit()

        print("Email sent")

    except Exception as e:

        print("Email error:", e)


# -------------------------------
# Firebase Setup
# -------------------------------
cred = credentials.Certificate("firebase_key.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -------------------------------
# Flask Setup
# -------------------------------
app = Flask(__name__)
app.secret_key = "secret123"

@app.context_processor
def inject_notification_count():

    if 'user' not in session:
        return dict(notif_count=0)

    notif_ref = db.collection("notifications") \
        .where("user", "==", session['user']) \
        .where("is_read", "==", False) \
        .stream()

    return dict(notif_count=len(list(notif_ref)))

# -------------------------------
# Upload Configuration
# -------------------------------
UPLOAD_FOLDER = 'static/uploads'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create folder if not exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -------------------------------
# Helper: Create Notification
# -------------------------------
def create_notification(user, message, need_id):
    db.collection("notifications").add({
        "user": user,
        "message": message,
        "need_id": need_id,
        "is_read": False,
        "timestamp": datetime.utcnow()
    })

# -------------------------------
# Helper: Calculate Distance (KM)
# -------------------------------
def calculate_distance(lat1, lon1, lat2, lon2):

    lat1 = float(lat1)
    lon1 = float(lon1)

    lat2 = float(lat2)
    lon2 = float(lon2)

    # Earth radius in KM
    R = 6371

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * asin(sqrt(a))

    return round(R * c, 2)

# -------------------------------
# Helper: Set full session after login
# -------------------------------
def set_user_session(user_doc_id, user_data):
    session['user'] = user_data['email']
    session['uid'] = user_doc_id
    session['role'] = user_data.get('role', 'user')
    session['is_ngo'] = user_data.get('is_ngo', False)
    session['ngo_verified'] = user_data.get('ngo_verified', False)
    session['ngo_id'] = user_data.get('ngo_id', None)
    session['is_volunteer'] = user_data.get('is_volunteer', False)


# -------------------------------
# Home
# -------------------------------
@app.route('/')
def home():
    return redirect('/login')


# -------------------------------
# Register
# -------------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'

        if not re.match(pattern, email):
            return render_template('register.html', error="Invalid Email Format")

        users_ref = db.collection("users").stream()
        for user in users_ref:
            if user.to_dict()['email'] == email:
                return render_template('register.html', error="Email already exists")

        session['reg_user'] = {
            "name": request.form['name'],
            "email": email,
            "password": generate_password_hash(request.form['password']),
            "phone": request.form['phone'],
            "role": "user",
            "is_blocked": False,
            "is_ngo": False,
            "ngo_verified": False,
            "is_volunteer": False,
            "ngo_id": None
        }

        otp = str(random.randint(100000, 999999))
        session['reg_otp'] = otp
        session['reg_time'] = time.time()

        send_otp_email(email, otp)
        return redirect('/verify_register_otp')

    return render_template('register.html')


# -------------------------------
# Verify Register OTP
# -------------------------------
@app.route('/verify_register_otp', methods=['GET', 'POST'])
def verify_register_otp():
    if request.method == 'POST':
        user_otp = request.form['otp']

        if time.time() - session.get('reg_time', 0) > 120:
            return render_template('otp.html', error="OTP expired")

        if user_otp == session.get('reg_otp'):
            db.collection("users").add(session['reg_user'])
            session.pop('reg_user', None)
            session.pop('reg_otp', None)
            session.pop('reg_time', None)
            return redirect('/login')

        return render_template('otp.html', error="Invalid OTP")

    return render_template('otp.html')


# -------------------------------
# Resend OTP
# -------------------------------
@app.route('/resend_otp')
def resend_otp():
    reg_user = session.get('reg_user')
    if not reg_user:
        return redirect('/register')

    otp = str(random.randint(100000, 999999))
    session['reg_otp'] = otp
    session['reg_time'] = time.time()

    send_otp_email(reg_user['email'], otp)
    return redirect('/verify_register_otp')


# -------------------------------
# Login
# -------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        users = db.collection("users").stream()

        for user in users:
            u = user.to_dict()
            if u['email'] == email and check_password_hash(u['password'], password):
                if u.get('is_blocked'):
                    return render_template('login.html', error="Your account has been blocked.")
                # FIX: set full session including uid and NGO flags
                set_user_session(user.id, u)
                return redirect('/dashboard')

        return render_template('login.html', error="Invalid Credentials")

    return render_template('login.html')


# -------------------------------
# Dashboard
# -------------------------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')

    needs_docs = db.collection("needs").stream()

    total_needs = 0
    ongoing = 0

    for doc in needs_docs:
        need = doc.to_dict()
        total_needs += 1
        if need.get('status') == "In Progress":
            ongoing += 1

    notif_ref = db.collection("notifications")\
        .where("user", "==", session['user'])\
        .where("is_read", "==", False)\
        .stream()

    notif_count = len(list(notif_ref))

    return render_template(
        'dashboard.html',
        total_needs=total_needs,
        ongoing=ongoing,
        notif_count=notif_count
    )


# -------------------------------
# Post Need
# -------------------------------
@app.route('/post_need', methods=['GET', 'POST'])
def post_need():
    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':

       description = request.form['description'].strip()

       if not description:
            return render_template(
                'post_need.html',
                error="Description cannot be empty"
            )

       need = {
            "category": request.form['category'],
            "description": description,
            "location": request.form['location'],
            "lat": request.form.get('lat', ''),
            "lng": request.form.get('lng', ''),
            "status": "Open",
            "created_by": session['user'],
            "priority": request.form.get('priority', 'Normal'),
            "timestamp": datetime.utcnow()
        }
       db.collection("needs").add(need)
       return redirect('/view_needs')

    return render_template('post_need.html')


# -------------------------------
# Edit Need
# -------------------------------
@app.route('/edit_need/<need_id>', methods=['GET', 'POST'])
def edit_need(need_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("needs").document(need_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Need not found"

    need = doc.to_dict()

    if need.get('created_by') != session['user']:
        return "Not allowed"

    if need.get('status') != "Open":
        return "Cannot edit a need that is already In Progress or Completed"

    if request.method == 'POST':
        doc_ref.update({
            "category": request.form['category'],
            "description": request.form['description'],
            "location": request.form['location'],
            "priority": request.form.get('priority', 'Normal'),
        })
        return redirect('/view_needs')

    need['id'] = need_id
    return render_template('edit_need.html', need=need)


# -------------------------------
# Delete Need
# -------------------------------
@app.route('/delete_need/<need_id>')
def delete_need_user(need_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("needs").document(need_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Need not found"

    need = doc.to_dict()

    if need.get('created_by') != session['user']:
        return "Not allowed"

    if need.get('status') != "Open":
        return "Cannot delete a need that is already In Progress or Completed"

    doc_ref.delete()
    return redirect('/view_needs')


# -------------------------------
# View Needs
# -------------------------------
@app.route('/view_needs')
def view_needs():

    if 'user' not in session:
        return redirect('/login')

    # User filter inputs
    radius = request.args.get('radius', type=float)
    user_lat = request.args.get('user_lat')
    user_lng = request.args.get('user_lng')

    needs_ref = db.collection("needs").stream()

    open_needs = []
    progress_needs = []
    completed_needs = []

    for need in needs_ref:

        data = need.to_dict()
        data['id'] = need.id

        # -------------------------------
        # DISTANCE FILTERING
        # -------------------------------
        if radius and user_lat and user_lng:

            # Skip needs without coordinates
           if not data.get('lat') or not data.get('lng'):
               continue
           try:

              distance = calculate_distance(
               user_lat,
               user_lng,
               data['lat'],
               data['lng']
            )

              data['distance'] = distance

        # Outside radius
              if distance > radius:
                continue

           except:
             continue

        # -------------------------------
        # STATUS GROUPING
        # -------------------------------
        if data.get("status") == "Open":
            open_needs.append(data)

        elif data.get("status") == "In Progress":
            progress_needs.append(data)

        else:
            completed_needs.append(data)

    # -------------------------------
    # SORTING
    # SOS -> Urgent -> Nearest
    # -------------------------------
    open_needs.sort(
        key=lambda x: (
            x.get('priority') != 'SOS',
            x.get('priority') != 'Urgent',
            x.get('distance', 9999)
        )
    )

    return render_template(
        'view_needs.html',
        open_needs=open_needs,
        progress_needs=progress_needs,
        completed_needs=completed_needs
    )


# -------------------------------
# Respond to Need
# -------------------------------
@app.route('/respond/<need_id>')
def respond(need_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("needs").document(need_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Need not found"

    need = doc.to_dict()

    if need.get("created_by") == session['user']:
        return "Cannot respond to your own request"

    if need.get("helper"):
        return "Already taken"

    doc_ref.update({
        "status": "In Progress",
        "helper": session['user']
    })

    create_notification(
        need['created_by'],
        f"{session['user']} accepted your request",
        need_id
    )
    # -------------------------------
    # Email Alert
    # -------------------------------
    send_email(
        need['created_by'],
        "Need Accepted - NeedLink",
        f"""
Hello,

Your request has been accepted.

Category: {need['category']}

Helper: {session['user']}

Please login to NeedLink for updates.

- NeedLink
"""
    )
    return redirect('/view_needs')


# -------------------------------
# Cancel Response (helper withdraws)
# -------------------------------
@app.route('/cancel_response/<need_id>')
def cancel_response(need_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("needs").document(need_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Need not found"

    need = doc.to_dict()

    if need.get("helper") != session['user']:
        return "Not allowed"

    doc_ref.update({
        "status": "Open",
        "helper": None
    })

    create_notification(
        need['created_by'],
        f"{session['user']} cancelled their response to your request",
        need_id
    )

    return redirect('/view_needs')

# -------------------------------
# Report User / Complaint System
# -------------------------------
@app.route('/report_user/<need_id>', methods=['GET', 'POST'])
def report_user(need_id):

    if 'user' not in session:
        return redirect('/login')

    need_doc = db.collection("needs").document(need_id).get()

    if not need_doc.exists:
        return "Need not found"

    need = need_doc.to_dict()

    # Determine whom to report
    reported_user = None

    if session['user'] == need.get('created_by'):
        reported_user = need.get('helper')

    elif session['user'] == need.get('helper'):
        reported_user = need.get('created_by')

    else:
        return "Unauthorized"

    if not reported_user:
        return "No user available to report"

    # -------------------------------
    # SUBMIT REPORT
    # -------------------------------
    if request.method == 'POST':

        reason = request.form['reason']
        details = request.form.get('details', '')

        db.collection("reports").add({
            "need_id": need_id,
            "reported_user": reported_user,
            "reported_by": session['user'],
            "reason": reason,
            "details": details,
            "status": "Pending",
            "timestamp": datetime.utcnow()
        })

        return redirect('/dashboard')

    return render_template(
        'report_user.html',
        need=need,
        reported_user=reported_user
    )

# -------------------------------
# Chat Module
# -------------------------------
@app.route('/chat/<need_id>')
def chat(need_id):
    if 'user' not in session:
        return redirect('/login')

    need_doc = db.collection("needs").document(need_id).get()

    if not need_doc.exists:
        return "Need not found"

    need = need_doc.to_dict()

    if session['user'] != need.get('created_by') and session['user'] != need.get('helper'):
        return "Unauthorized access"

    messages_ref = db.collection("needs").document(need_id)\
        .collection("chats").order_by("timestamp")

    messages = [msg.to_dict() for msg in messages_ref.stream()]

    return render_template("chat.html", need=need, messages=messages, need_id=need_id)


# -------------------------------
# Send Message
# -------------------------------
@app.route('/send_message/<need_id>', methods=['POST'])
def send_message(need_id):
    if 'user' not in session:
        return redirect('/login')

    need_doc = db.collection("needs").document(need_id).get()

    if not need_doc.exists:
        return "Need not found"

    need = need_doc.to_dict()

    if session['user'] != need.get('created_by') and session['user'] != need.get('helper'):
        return "Unauthorized"

    if need.get('status') != "In Progress":
        return "Chat closed after completion"

    text = request.form['message']

    db.collection("needs").document(need_id).collection("chats").add({
        "sender": session['user'],
        "text": text,
        "timestamp": datetime.utcnow()
    })
    # -------------------------------
    # Create message notification
    # -------------------------------
    receiver = None

    if session['user'] == need.get('created_by'):
        receiver = need.get('helper')

    else:
        receiver = need.get('created_by')

    if receiver:

        create_notification(
            receiver,
            f"💬 New message from {session['user']}",
            need_id
        )
    return redirect(f'/chat/{need_id}')


# -------------------------------
# Complete Need
# -------------------------------
@app.route('/complete/<need_id>')
def complete(need_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("needs").document(need_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Need not found"

    need = doc.to_dict()

    if need.get("created_by") != session['user']:
        return "Not allowed"

    doc_ref.update({"status": "Completed"})

    create_notification(
        need['helper'],
        "Your task was marked as completed",
        need_id
    )
    # -------------------------------
    # Completion Email
    # -------------------------------
    receiver = None

    if session['user'] == need['created_by']:
        receiver = need.get('helper')

    else:
        receiver = need['created_by']

    if receiver:

        send_email(
            receiver,
            "Need Completed - NeedLink",
            f"""
Hello,

A request has been marked as completed.

Category: {need['category']}

Completed By: {session['user']}

Thank you for using NeedLink.

- NeedLink
"""
        )
    return redirect('/view_needs')


# -------------------------------
# Rate Helper
# -------------------------------
@app.route('/rate/<need_id>', methods=['GET', 'POST'])
def rate(need_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("needs").document(need_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Need not found"

    need = doc.to_dict()

    if need.get("created_by") != session['user']:
        return "Only the requester can rate the helper"

    if need.get("helper") == session['user']:
        return "Helper cannot rate their own work"

    if request.method == 'POST':
        existing = db.collection("ratings")\
            .where("need_id", "==", need_id)\
            .where("rated_by", "==", session['user'])\
            .stream()

        if list(existing):
            return "You already rated this task"

        rating = int(request.form['rating'])
        feedback = request.form['feedback']

        db.collection("ratings").add({
            "need_id": need_id,
            "helper": need.get("helper"),
            "rated_by": session['user'],
            "rating": rating,
            "feedback": feedback,
            "timestamp": datetime.utcnow()
        })
        doc_ref.update({
           "rated": True
        })

        return redirect('/dashboard')

    return render_template('rate.html', need=need)


# -------------------------------
# Notifications
# -------------------------------
@app.route('/notifications')
def notifications():
    if 'user' not in session:
        return redirect('/login')

    notif_ref = db.collection("notifications")\
        .where("user", "==", session['user'])\
        .order_by("timestamp", direction="DESCENDING")

    notifications_list = []

    for n in notif_ref.stream():
        data = n.to_dict()
        data['id'] = n.id
        notifications_list.append(data)

    return render_template("notifications.html", notifications=notifications_list)


# -------------------------------
# Mark Notification Read
# -------------------------------
@app.route('/mark_read/<notif_id>')
def mark_read(notif_id):
    db.collection("notifications").document(notif_id).update({
        "is_read": True
    })
    return redirect('/notifications')

#--------------------------------
#mark as read
#----------------------------
@app.route('/mark_all_read')
def mark_all_read():

    if 'user' not in session:
        return redirect('/login')

    notifs = db.collection("notifications") \
        .where("user", "==", session['user']) \
        .where("is_read", "==", False) \
        .stream()

    for n in notifs:
        db.collection("notifications").document(n.id).update({
            "is_read": True
        })

    return redirect('/notifications')


# -------------------------------
# Profile
# -------------------------------
@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect('/login')

    users_ref = db.collection("users").stream()

    for user in users_ref:
        data = user.to_dict()
        if data['email'] == session['user']:
            # Calculate average rating
            ratings_ref = db.collection("ratings")\
                .where("helper", "==", session['user'])\
                .stream()
            ratings = [r.to_dict()['rating'] for r in ratings_ref]
            avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
            data['avg_rating'] = avg_rating
            data['total_ratings'] = len(ratings)

            # Count needs posted and helped
            needs_posted = len(list(db.collection("needs").where("created_by", "==", session['user']).stream()))
            needs_helped = len(list(db.collection("needs").where("helper", "==", session['user']).stream()))
            data['needs_posted'] = needs_posted
            data['needs_helped'] = needs_helped

            return render_template('profile.html', user=data)

    return "User not found"


# -------------------------------
# Edit Profile
# -------------------------------
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():

    if 'user' not in session:
        return redirect('/login')

    email = session['user']

    users = db.collection("users").stream()

    user_id = None
    user_data = None

    for user in users:

        u = user.to_dict()

        if u['email'] == email:
            user_id = user.id
            user_data = u
            break

    if not user_id:
        return "User not found"

    # -------------------------------
    # UPDATE PROFILE
    # -------------------------------
    if request.method == 'POST':

        name = request.form['name']
        phone = request.form['phone']
        location = request.form.get('location', '')

        update_data = {
            "name": name,
            "phone": phone,
            "location": location
        }

        # -------------------------------
        # PROFILE PHOTO
        # -------------------------------
        photo = request.files.get('photo')

        if photo and photo.filename:

            filename = f"{int(time.time())}_{secure_filename(photo.filename)}"

            photo_path = os.path.join(
                app.config['UPLOAD_FOLDER'],
                filename
            )

            photo.save(photo_path)

            update_data['photo'] = photo_path

        # -------------------------------
        # ID PROOF
        # -------------------------------
        id_proof = request.files.get('id_proof')

        if id_proof and id_proof.filename:

            filename = f"{int(time.time())}_{secure_filename(id_proof.filename)}"

            proof_path = os.path.join(
                app.config['UPLOAD_FOLDER'],
                filename
            )

            id_proof.save(proof_path)

            update_data['id_proof'] = proof_path

            # Verification pending
            update_data['verification_status'] = "Pending"

        # -------------------------------
        # UPDATE FIRESTORE
        # -------------------------------
        db.collection("users").document(user_id).update(update_data)

        return redirect('/profile')

    return render_template(
        'edit_profile.html',
        user=user_data
    )
# -------------------------------
# Forgot Password
# -------------------------------
@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        email = request.form['email']

        users = db.collection("users").stream()
        for user in users:
            u = user.to_dict()
            if u['email'] == email:
                otp = str(random.randint(100000, 999999))
                session['reset_email'] = email
                session['reset_otp'] = otp
                session['reset_time'] = time.time()

                send_otp_email(email, otp)
                return redirect('/verify_reset_otp')

        return render_template('forgot.html', error="Email not found")

    return render_template('forgot.html')


# -------------------------------
# Verify Reset OTP
# -------------------------------
@app.route('/verify_reset_otp', methods=['GET', 'POST'])
def verify_reset_otp():
    if request.method == 'POST':
        user_otp = request.form['otp']

        if time.time() - session.get('reset_time', 0) > 120:
            return render_template('verify_reset_otp.html', error="OTP expired")

        if user_otp == session.get('reset_otp'):
            session['reset_verified'] = True
            return redirect('/reset_password')

        return render_template('verify_reset_otp.html', error="Invalid OTP")

    return render_template('verify_reset_otp.html')


# -------------------------------
# Reset Password
# -------------------------------
@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('reset_verified'):
       return redirect('/forgot')
    if request.method == 'POST':
        new_password = request.form['password']
        email = session.get('reset_email')

        users = db.collection("users").stream()

        for user in users:
            u = user.to_dict()
            if u['email'] == email:
                db.collection("users").document(user.id).update({
                    "password": generate_password_hash(new_password)
                })
                session.pop('reset_email', None)
                session.pop('reset_otp', None)
                session.pop('reset_verified', None)
                return redirect('/login')

        return "Error updating password"

    return render_template('reset_password.html')


# ================================
# SPRINT 2 - NEW FEATURES
# ================================

# -------------------------------
# Emergency SOS
# -------------------------------
@app.route('/sos', methods=['GET', 'POST'])
def sos():

    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':

        lat = request.form.get('lat', '')
        lng = request.form.get('lng', '')

        description = request.form.get(
            'description',
            '🆘 Emergency! I need immediate help.'
        )

        # Use readable location if available
        location = request.form.get('location', '').strip()

        if not location:
            location = f"{lat}, {lng}"

        # Create SOS need
        db.collection("needs").add({

            "category": "Emergency",

            "description": description,

            "location": location,

            "lat": lat,

            "lng": lng,

            "status": "Open",

            "created_by": session['user'],

            "priority": "SOS",

            "timestamp": datetime.utcnow()

        })

        # Get all users
        users = db.collection("users").stream()

        for user in users:

            u = user.to_dict()

            if u.get('email') != session['user']:

                subject = "🆘 SOS Emergency Alert - NeedLink"

                body = f"""
Emergency SOS Request Posted

Posted By:
{session['user']}

Description:
{description}

Location:
{location}

Please login to NeedLink if you can help.

- NeedLink
"""

                send_email(
                    u.get('email'),
                    subject,
                    body
                )

        return render_template(
            'sos.html',
            success=True
        )

    return render_template(
        'sos.html',
        success=False
    )
# -------------------------------
# Pickup & Drop Module
# -------------------------------
@app.route('/pickup', methods=['GET', 'POST'])
def pickup():
    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':
        pickup_req = {
            "requester": session['user'],
            "item": request.form['item'],
            "pickup_location": request.form['pickup_location'],
            "drop_location": request.form['drop_location'],
            "notes": request.form.get('notes', ''),
            "status": "Pending",
            "helper": None,
            "timestamp": datetime.utcnow()
        }

        db.collection("pickups").add(pickup_req)
        return redirect('/my_pickups')

    return render_template('pickup.html')


@app.route('/my_pickups')
def my_pickups():
    if 'user' not in session:
        return redirect('/login')

    my_requests = []
    req_ref = db.collection("pickups").where("requester", "==", session['user']).stream()
    for p in req_ref:
        d = p.to_dict()
        d['id'] = p.id
        my_requests.append(d)

    available = []
    all_ref = db.collection("pickups").where("status", "==", "Pending").stream()
    for p in all_ref:
        d = p.to_dict()
        d['id'] = p.id
        if d['requester'] != session['user']:
            available.append(d)

    my_deliveries = []
    del_ref = db.collection("pickups").where("helper", "==", session['user']).stream()
    for p in del_ref:
        d = p.to_dict()
        d['id'] = p.id
        my_deliveries.append(d)

    return render_template('my_pickups.html',
                           my_requests=my_requests,
                           available=available,
                           my_deliveries=my_deliveries)


@app.route('/accept_pickup/<pickup_id>')
def accept_pickup(pickup_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("pickups").document(pickup_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Not found"

    data = doc.to_dict()

    if data['requester'] == session['user']:
        return "Cannot accept your own request"

    if data['status'] != "Pending":
        return "Already taken"

    doc_ref.update({
        "status": "In Transit",
        "helper": session['user']
    })

    create_notification(
        data['requester'],
        f"{session['user']} is delivering your pickup request",
        pickup_id
    )

    return redirect('/my_pickups')


@app.route('/complete_pickup/<pickup_id>')
def complete_pickup(pickup_id):
    if 'user' not in session:
        return redirect('/login')

    doc_ref = db.collection("pickups").document(pickup_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Not found"

    data = doc.to_dict()

    if data.get('helper') != session['user']:
        return "Not allowed"

    doc_ref.update({"status": "Delivered"})

    create_notification(
        data['requester'],
        "Your pickup request has been delivered!",
        pickup_id
    )

    return redirect('/my_pickups')


# -------------------------------
# NGO Registration
# -------------------------------
@app.route('/ngo_register', methods=['GET', 'POST'])
def ngo_register():

    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':

        ngo_name = request.form['ngo_name']

        ngo_desc = request.form.get('ngo_desc', '')

        contact = request.form.get('contact', '')
        
        existing = db.collection("ngo_requests") \
             .where("email", "==", session['user']) \
             .stream()

        if list(existing):

           return render_template(
                'register_ngo.html',
               success="NGO request already submitted"
            )

        db.collection("ngo_requests").add({
            "email": session['user'],
            "ngo_name": ngo_name,
            "ngo_desc": ngo_desc,
            "contact": contact,
            "status": "Pending",
            "timestamp": datetime.utcnow()
        })

        return render_template(
            'register_ngo.html',
            success="NGO registration submitted successfully"
        )

    return render_template('register_ngo.html')


# -------------------------------
# List NGOs
# -------------------------------
@app.route('/ngos')
def list_ngos():
    if 'user' not in session:
        return redirect('/login')

    ngos = []

    for u in db.collection("users").where("is_ngo", "==", True).stream():
        d = u.to_dict()

        if d.get('ngo_verified'):
            # Count volunteers
            volunteers_count = len(list(
                db.collection("users").where("ngo_id", "==", u.id).stream()
            ))
            ngos.append({
                "id": u.id,
                "name": d.get('ngo_name'),
                "desc": d.get('ngo_desc', d.get('description', '')),
                "contact": d.get('contact', ''),
                "volunteers": volunteers_count
            })

    # Check if current user is already a volunteer
    current_user_ngo_id = session.get('ngo_id')

    return render_template('ngos.html', ngos=ngos, current_ngo_id=current_user_ngo_id)


# -------------------------------
# Join NGO as Volunteer
# -------------------------------
@app.route('/join_ngo/<ngo_id>')
def join_ngo(ngo_id):
    if 'user' not in session:
        return redirect('/login')

    uid = session.get('uid')
    if not uid:
        return redirect('/login')

    # Prevent NGOs/admins from joining as volunteer
    if session.get('is_ngo') or session.get('role') == 'admin':
        return redirect('/dashboard')

    db.collection("users").document(uid).update({
        "ngo_id": ngo_id,
        "is_volunteer": True
    })

    session['ngo_id'] = ngo_id
    session['is_volunteer'] = True

    return redirect('/dashboard')


# -------------------------------
# Leave NGO
# -------------------------------
@app.route('/leave_ngo')
def leave_ngo():
    if 'user' not in session:
        return redirect('/login')

    uid = session.get('uid')
    if not uid:
        return redirect('/login')

    db.collection("users").document(uid).update({
        "ngo_id": None,
        "is_volunteer": False
    })

    session['ngo_id'] = None
    session['is_volunteer'] = False

    return redirect('/dashboard')

#--------------------------------
#Volunteers
#---------------------------------
@app.route('/volunteers')
def volunteers():

    if 'user' not in session:
        return redirect('/login')

    uid = session.get('uid')

    if not uid:
        return redirect('/dashboard')

    volunteer_docs = db.collection("users") \
        .where("ngo_id", "==", uid) \
        .stream()

    volunteers = []

    for v in volunteer_docs:
        data = v.to_dict()
        volunteers.append(data)

    return render_template(
        'volunteers.html',
        volunteers=volunteers
    )


# -------------------------------
# Admin Panel
# -------------------------------
@app.route('/admin')
def admin():
    if 'user' not in session:
        return redirect('/login')

    if session.get('role') != 'admin':
        return "Access Denied"

    users_list = []
    for u in db.collection("users").stream():
        d = u.to_dict()
        d['id'] = u.id
        ratings_ref = db.collection("ratings").where("helper", "==", d['email']).stream()
        ratings = [r.to_dict()['rating'] for r in ratings_ref]
        d['avg_rating'] = round(sum(ratings) / len(ratings), 1) if ratings else None
        users_list.append(d)

    needs_list = []
    for n in db.collection("needs").stream():
        d = n.to_dict()
        d['id'] = n.id
        needs_list.append(d)

    ngo_requests = []
    for n in db.collection("ngo_requests").where("status", "==", "Pending").stream():
        d = n.to_dict()
        d['id'] = n.id
        ngo_requests.append(d)


    # -------------------------------
    # Analytics
    # -------------------------------

    total_users = len(users_list)

    total_needs = len(needs_list)

    completed_needs = len([
        n for n in needs_list
        if n.get('status') == 'Completed'
    ])

    ongoing_needs = len([
        n for n in needs_list
        if n.get('status') == 'In Progress'
    ])

    open_needs_count = len([
        n for n in needs_list
        if n.get('status') == 'Open'
    ])

    sos_count = len([
        n for n in needs_list
        if n.get('priority') == 'SOS'
    ])

    urgent_count = len([
        n for n in needs_list
        if n.get('priority') == 'Urgent'
    ])

    completion_rate = 0

    if total_needs > 0:

        completion_rate = round(
            (completed_needs / total_needs) * 100,
            1
        )

    # -------------------------------
    # Top Helpers
    # -------------------------------
    helper_scores = {}

    for n in needs_list:

        helper = n.get('helper')

        if helper:

            helper_scores[helper] = helper_scores.get(helper, 0) + 1

    top_helpers = sorted(
        helper_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]

    # Pending reports
    reports = []

    for r in db.collection("reports") \
              .order_by("timestamp", direction="DESCENDING") \
              .stream():

        d = r.to_dict()
        d['id'] = r.id

        reports.append(d)
    
    return render_template(
        'admin.html',
        users=users_list,
        needs=needs_list,
        ngo_requests=ngo_requests,
        reports=reports,

        total_users=total_users,
        total_needs=total_needs,
        completed_needs=completed_needs,
        ongoing_needs=ongoing_needs,
        open_needs_count=open_needs_count,

        sos_count=sos_count,
        urgent_count=urgent_count,

        completion_rate=completion_rate,

        top_helpers=top_helpers
    )
    
                           


@app.route('/admin/block/<user_id>')
def block_user(user_id):
    if session.get('role') != 'admin':
        return "Access Denied"

    db.collection("users").document(user_id).update({"is_blocked": True})
    return redirect('/admin')


@app.route('/admin/unblock/<user_id>')
def unblock_user(user_id):
    if session.get('role') != 'admin':
        return "Access Denied"

    db.collection("users").document(user_id).update({"is_blocked": False})
    return redirect('/admin')


@app.route('/admin/delete_need/<need_id>')
def delete_need(need_id):
    if session.get('role') != 'admin':
        return "Access Denied"

    db.collection("needs").document(need_id).delete()
    return redirect('/admin')


@app.route('/admin/approve_ngo/<ngo_id>')
def approve_ngo(ngo_id):
    if session.get('role') != 'admin':
        return "Access Denied"

    ngo_doc = db.collection("ngo_requests").document(ngo_id).get()
    if not ngo_doc.exists:
        return "Not found"

    ngo_data = ngo_doc.to_dict()

    db.collection("ngo_requests").document(ngo_id).update({"status": "Approved"})

    users = db.collection("users").stream()
    for u in users:
        if u.to_dict()['email'] == ngo_data['email']:
            db.collection("users").document(u.id).update({
                "is_ngo": True,
                "ngo_verified": True,
                "ngo_name": ngo_data['ngo_name'],
                "ngo_desc": ngo_data.get('description', '')
            })
            break

    create_notification(
        ngo_data['email'],
        "Congratulations! Your NGO registration has been approved.",
        ngo_id
    )

    return redirect('/admin')


@app.route('/admin/reject_ngo/<ngo_id>')
def reject_ngo(ngo_id):
    if session.get('role') != 'admin':
        return "Access Denied"

    ngo_doc = db.collection("ngo_requests").document(ngo_id).get()
    if not ngo_doc.exists:
        return "Not found"

    ngo_data = ngo_doc.to_dict()

    db.collection("ngo_requests").document(ngo_id).update({"status": "Rejected"})

    create_notification(
        ngo_data['email'],
        "Your NGO registration was not approved.",
        ngo_id
    )

    return redirect('/admin')


# -------------------------------
# Logout
# -------------------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# -------------------------------
# Run App
# -------------------------------
if __name__ == '__main__':
    app.run(debug=True)