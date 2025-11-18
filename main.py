from flask import Flask, request, jsonify, render_template, redirect, url_for, session, make_response
from datetime import datetime, timedelta
import os
import json
from pymongo import MongoClient
from bson.objectid import ObjectId

app = Flask(__name__)
app.secret_key = '2321h3l1h3hl3n1'  # Change this in production

# === CORS CONFIG (updated for ALL stake mirrors) ===

def is_allowed_origin(origin):
    if not origin:
        return False

    origin = origin.lower()

    try:
        host = origin.split("://", 1)[1]
    except:
        return False

    if host.startswith("stake."):
        return True

    if host.startswith("stake-"):
        return True

    if host.startswith("stake"):
        return True

    return False


@app.before_request
def handle_options():
    if request.method == 'OPTIONS':
        resp = make_response()
        origin = request.headers.get('Origin')
        if is_allowed_origin(origin):
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        return resp


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin')
    if is_allowed_origin(origin):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    return response

# === End CORS CONFIG ===


# === MONGODB CONFIG ===
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb+srv://rj5706603:O95nvJYxapyDHfkw@cluster0.fzmckei.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
DB_NAME = 'user_auth_db'
COLLECTION_NAME = 'users'

try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[COLLECTION_NAME]
    users_collection.create_index("auth_expires", expireAfterSeconds=60)
    mongo_connected = True
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    mongo_connected = False
# === End MONGODB CONFIG ===


DATA_FILE = 'users.json'


def clean_expired_users(users):
    now = datetime.utcnow()
    expired_users = []

    for username, user_data in list(users.items()):
        auth_expires = user_data.get('auth_expires')
        if auth_expires and auth_expires <= now:
            expired_users.append(username)

    for username in expired_users:
        del users[username]

    return users


def load_users():
    users = {}

    if mongo_connected:
        try:
            mongo_users = users_collection.find({})
            for user_doc in mongo_users:
                username = user_doc.get('username')
                if username:
                    users[username] = {
                        'auth_expires': user_doc.get('auth_expires'),
                        'mongo_id': str(user_doc.get('_id'))
                    }
            return users
        except Exception as e:
            print(f"Error loading from MongoDB: {e}")

    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for username, user_data in data.items():
                if user_data.get('auth_expires'):
                    user_data['auth_expires'] = datetime.fromisoformat(user_data['auth_expires'])

            data = clean_expired_users(data)
            save_users(data)
            return data
    except (json.JSONDecodeError, ValueError):
        return {}


def save_users(users):
    if mongo_connected:
        try:
            for username, user_data in users.items():
                existing_user = users_collection.find_one({'username': username})

                if existing_user:
                    users_collection.update_one(
                        {'username': username},
                        {'$set': {'auth_expires': user_data['auth_expires']}}
                    )
                else:
                    users_collection.insert_one({
                        'username': username,
                        'auth_expires': user_data['auth_expires']
                    })
        except Exception as e:
            print(f"Error saving to MongoDB: {e}")

    users_to_save = {}
    for username, user_data in users.items():
        users_to_save[username] = user_data.copy()
        if users_to_save[username].get('auth_expires'):
            users_to_save[username]['auth_expires'] = users_to_save[username]['auth_expires'].isoformat()

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(users_to_save, f, indent=2)


class User:
    def __init__(self, username, auth_expires=None, mongo_id=None):
        self.username = username
        self.auth_expires = auth_expires
        self.mongo_id = mongo_id

    def is_active(self):
        if self.auth_expires is None:
            return False
        return datetime.utcnow() < self.auth_expires

    def time_left(self):
        if self.auth_expires is None:
            return "No subscription"
        delta = self.auth_expires - datetime.utcnow()
        if delta.total_seconds() <= 0:
            return "Expired"
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"


def check_admin_password(password):
    return password == "admin1234"


@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    users_data = load_users()
    active_users = []

    for username, user_data in users_data.items():
        user = User(username, user_data.get('auth_expires'), user_data.get('mongo_id'))
        if user.is_active():
            active_users.append(user)

    return render_template('dashboard.html', users=active_users)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['password'] == 'admin1234':
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'Invalid password'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/check')
def check_user():
    username = request.args.get('user')
    if not username:
        return jsonify({"error": "Missing user parameter"}), 400

    if not username.startswith('@'):
        return jsonify({"error": "Username must start with @"}), 400

    users_data = load_users()
    return jsonify({"exists": username in users_data})


@app.route('/auth')
def auth_user():
    username = request.args.get('user')
    admin_password = request.args.get('admin')
    duration = request.args.get('duration')

    if not all([username, admin_password, duration]):
        return jsonify({"error": "Missing parameters"}), 400

    if not check_admin_password(admin_password):
        return jsonify({"error": "Invalid admin password"}), 401

    try:
        duration_hours = int(duration)
        if duration_hours <= 0:
            return jsonify({"error": "Duration must be a positive integer"}), 400
    except ValueError:
        return jsonify({"error": "Duration must be an integer"}), 400

    if not username.startswith('@'):
        return jsonify({"error": "Username must start with @"}), 400

    users_data = load_users()

    now = datetime.utcnow()
    if username in users_data and users_data[username].get('auth_expires'):
        current_expires = users_data[username]['auth_expires']
        if current_expires > now:
            new_expires = current_expires + timedelta(hours=duration_hours)
        else:
            new_expires = now + timedelta(hours=duration_hours)
    else:
        new_expires = now + timedelta(hours=duration_hours)

    users_data[username] = {
        'auth_expires': new_expires
    }

    save_users(users_data)
    return jsonify({"success": True, "username": username, "expires": new_expires.isoformat()})


@app.route('/add_user', methods=['POST'])
def add_user():
    if not session.get('logged_in'):
        return jsonify({"error": "Not authenticated"}), 401

    username = request.form.get('username')
    duration = request.form.get('duration')

    if not all([username, duration]):
        return jsonify({"error": "Missing parameters"}), 400

    try:
        duration_hours = int(duration)
        if duration_hours <= 0:
            return jsonify({"error": "Duration must be a positive integer"}), 400
    except ValueError:
        return jsonify({"error": "Duration must be an integer"}), 400

    if not username.startswith('@'):
        return jsonify({"error": "Username must start with @"}), 400

    users_data = load_users()

    now = datetime.utcnow()
    new_expires = now + timedelta(hours=duration_hours)

    users_data[username] = {
        'auth_expires': new_expires
    }

    save_users(users_data)
    return redirect(url_for('index'))


@app.route('/edit_user', methods=['POST'])
def edit_user():
    if not session.get('logged_in'):
        return jsonify({"error": "Not authenticated"}), 401

    username = request.form.get('username')
    duration = request.form.get('duration')

    if not all([username, duration]):
        return jsonify({"error": "Missing parameters"}), 400

    try:
        duration_hours = int(duration)
        if duration_hours <= 0:
            return jsonify({"error": "Duration must be a positive integer"}), 400
    except ValueError:
        return jsonify({"error": "Duration must be an integer"}), 400

    users_data = load_users()

    if username not in users_data:
        return jsonify({"error": "User not found"}), 404

    now = datetime.utcnow()
    new_expires = now + timedelta(hours=duration_hours)

    users_data[username]['auth_expires'] = new_expires

    save_users(users_data)
    return redirect(url_for('index'))


@app.route('/delete_user', methods=['POST'])
def delete_user():
    if not session.get('logged_in'):
        return jsonify({"error": "Not authenticated"}), 401

    username = request.form.get('username')

    if not username:
        return jsonify({"error": "Missing username parameter"}), 400

    users_data = load_users()

    if username not in users_data:
        return jsonify({"error": "User not found"}), 404

    if mongo_connected:
        try:
            users_collection.delete_one({'username': username})
        except Exception as e:
            print(f"Error deleting from MongoDB: {e}")

    del users_data[username]

    save_users(users_data)

    return redirect(url_for('index'))


if not os.path.exists('templates'):
    os.makedirs('templates')

# login.html
with open('templates/login.html', 'w', encoding='utf-8') as f:
    f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Admin Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            background-color: #f5f7fa;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }
        .login-container {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            padding: 2rem;
            width: 100%;
            max-width: 400px;
        }
        .login-header {
            text-align: center;
            margin-bottom: 1.5rem;
        }
        .login-header h1 {
            color: #333;
            font-size: 1.8rem;
            margin-bottom: 0.5rem;
        }
        .login-header p {
            color: #666;
            font-size: 0.9rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: #555;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #4a90e2;
        }
        .btn {
            display: block;
            width: 100%;
            padding: 0.75rem;
            background-color: #4a90e2;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 1rem;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .btn:hover {
            background-color: #3a7bc8;
        }
        .error-message {
            color: #e74c3c;
            margin-top: 1rem;
            text-align: center;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1>Admin Login</h1>
            <p>Enter your password to access the dashboard</p>
        </div>
        <form method="post">
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="btn">Login</button>
            {% if error %}
            <div class="error-message">{{ error }}</div>
            {% endif %}
        </form>
    </div>
</body>
</html>""")


# dashboard.html
with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
    f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>User Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            background-color: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background-color: #4a90e2;
            color: white;
            padding: 1rem 0;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        h1 {
            font-size: 1.8rem;
        }
        .logout-btn {
            background-color: rgba(255, 255, 255, 0.2);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.3);
            padding: 0.5rem 1rem;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            transition: background-color 0.3s;
        }
        .logout-btn:hover {
            background-color: rgba(255, 255, 255, 0.3);
        }
        .stats-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        .stat-card {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            padding: 20px;
            text-align: center;
        }
        .stat-value {
            font-size: 2rem;
            font-weight: bold;
            color: #4a90e2;
            margin-bottom: 5px;
        }
        .stat-label {
            color: #666;
            font-size: 0.9rem;
        }
        .users-section {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            padding: 20px;
            margin-top: 30px;
        }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        h2 {
            font-size: 1.5rem;
            color: #333;
        }
        .refresh-btn {
            background-color: #4a90e2;
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .refresh-btn:hover {
            background-color: #3a7bc8;
        }
        .users-table {
            width: 100%;
            border-collapse: collapse;
        }
        .users-table th, .users-table td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        .users-table th {
            background-color: #f9f9f9;
            font-weight: 600;
            color: #555;
        }
        .users-table tr:hover {
            background-color: #f9f9f9;
        }
        .username {
            font-weight: 500;
            color: #4a90e2;
        }
        .time-left {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .time-left.active {
            background-color: #e8f5e9;
            color: #2e7d32;
        }
        .time-left.expiring {
            background-color: #fff8e1;
            color: #f57f17;
        }
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #666;
        }
        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 15px;
            opacity: 0.5;
        }
        .api-info {
            background-color: #f0f7ff;
            border-left: 4px solid #4a90e2;
            padding: 15px;
            margin-top: 30px;
            border-radius: 0 4px 4px 0;
        }
        .api-info h3 {
            margin-bottom: 10px;
            color: #4a90e2;
        }
        .api-endpoint {
            font-family: monospace;
            background-color: #f5f5f5;
            padding: 8px 12px;
            border-radius: 4px;
            margin: 5px 0;
            overflow-x: auto;
        }
        .action-btn {
            padding: 0.3rem 0.6rem;
            margin-right: 0.3rem;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8rem;
            transition: background-color 0.3s;
        }
        .edit-btn {
            background-color: #2196F3;
            color: white;
        }
        .edit-btn:hover {
            background-color: #0b7dda;
        }
        .delete-btn {
            background-color: #f44336;
            color: white;
        }
        .delete-btn:hover {
            background-color: #d32f2f;
        }
        .add-user-section {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            padding: 20px;
            margin-top: 30px;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: #555;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #4a90e2;
        }
        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            background-color: #4a90e2;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 1rem;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .btn:hover {
            background-color: #3a7bc8;
        }
        .modal {
            display: none;
            position: fixed;
            z-index: 1;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto;
            background-color: rgba(0,0,0,0.4);
        }
        .modal-content {
            background-color: #fefefe;
            margin: 15% auto;
            padding: 20px;
            border: 1px solid #888;
            width: 80%;
            max-width: 500px;
            border-radius: 8px;
        }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
        }
        .close:hover,
        .close:focus {
            color: black;
            text-decoration: none;
            cursor: pointer;
        }
        @media (max-width: 768px) {
            .header-content {
                flex-direction: column;
                gap: 15px;
            }
            .users-table {
                font-size: 0.9rem;
            }
            .users-table th, .users-table td {
                padding: 8px 10px;
            }
            .section-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="header-content">
            <h1>User Dashboard</h1>
            <a href="/logout" class="logout-btn">Logout</a>
        </div>
    </header>

    <div class="container">
        <div class="stats-container">
            <div class="stat-card">
                <div class="stat-value">{{ users|length }}</div>
                <div class="stat-label">Active Users</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ users|length }}</div>
                <div class="stat-label">Total Subscriptions</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">0</div>
                <div class="stat-label">Expired Subscriptions</div>
            </div>
        </div>

        <div class="add-user-section">
            <div class="section-header">
                <h2>Add New User</h2>
            </div>
            <form action="/add_user" method="post">
                <div class="form-group">
                    <label for="username">Username (must start with @)</label>
                    <input type="text" id="username" name="username" placeholder="@username" required>
                </div>
                <div class="form-group">
                    <label for="duration">Duration (hours)</label>
                    <input type="number" id="duration" name="duration" min="1" required>
                </div>
                <button type="submit" class="btn">Add User</button>
            </form>
        </div>

        <div class="users-section">
            <div class="section-header">
                <h2>Active Users</h2>
                <button class="refresh-btn" onclick="location.reload()">Refresh</button>
            </div>

            {% if users %}
            <table class="users-table">
                <thead>
                    <tr>
                        <th>Username</th>
                        <th>Time Left</th>
                        <th>Expires At</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td class="username">{{ user.username }}</td>
                        <td>
                            {% set time_left = user.time_left() %}
                            {% if 'Expired' in time_left %}
                            <span class="time-left expiring">{{ time_left }}</span>
                            {% else %}
                            <span class="time-left active">{{ time_left }}</span>
                            {% endif %}
                        </td>
                        <td>{{ user.auth_expires.strftime('%Y-%m-%d %H:%M:%S') if user.auth_expires else 'N/A' }}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="openEditModal('{{ user.username }}')">Edit</button>
                            <form action="/delete_user" method="post" style="display: inline;">
                                <input type="hidden" name="username" value="{{ user.username }}">
                                <button type="submit" class="action-btn delete-btn" onclick="return confirm('Are you sure you want to delete this user?')">Delete</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty-state">
                <div class="empty-state-icon">📭</div>
                <h3>No active users</h3>
                <p>There are no users with active subscriptions at the moment.</p>
            </div>
            {% endif %}
        </div>

        <div class="api-info">
            <h3>API Endpoints</h3>
            <div class="api-endpoint">GET /check?user=@username</div>
            <p>Check if a user exists in the database</p>

            <div class="api-endpoint">GET /auth?user=@username&admin=adminpassword&duration=hours</div>
            <p>Authorize a user for a specific duration (in hours)</p>
        </div>
    </div>

    <div id="editModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeEditModal()">&times;</span>
            <h2>Edit User</h2>
            <form action="/edit_user" method="post">
                <div class="form-group">
                    <label for="edit_username">Username</label>
                    <input type="text" id="edit_username" name="username" readonly>
                </div>
                <div class="form-group">
                    <label for="edit_duration">New Duration (hours)</label>
                    <input type="number" id="edit_duration" name="duration" min="1" required>
                </div>
                <button type="submit" class="btn">Update User</button>
            </form>
        </div>
    </div>

    <script>
        setTimeout(function() {
            location.reload();
        }, 300000);

        function openEditModal(username) {
            document.getElementById('edit_username').value = username;
            document.getElementById('editModal').style.display = 'block';
        }

        function closeEditModal() {
            document.getElementById('editModal').style.display = 'none';
        }

        window.onclick = function(event) {
            const modal = document.getElementById('editModal');
            if (event.target == modal) {
                modal.style.display = 'none';
            }
        }
    </script>
</body>
</html>""")


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
