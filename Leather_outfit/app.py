import os
import time
from flask import Flask, send_from_directory, render_template, request, redirect, url_for, flash, session, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, UserMixin, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import logging
from downloader_parser_edition import YouTubeBackup
from sqlalchemy import text
from elasticsearch import Elasticsearch 
import jinja2
import humanize
import logging
import requests
import json
import psycopg2

# Конфигурация
CONFIG = {
    "storage_path": "/mnt/d/videos",
    "db_uri": "postgresql://impostorboy:0@localhost/youtube_backup"
}

# Инициализация Flask и базы данных
app = Flask(__name__)
app.add_url_rule('/videos/<path:filename>', endpoint='videos', view_func=lambda filename: send_from_directory(CONFIG['storage_path'], filename))

es = Elasticsearch([{'host': 'localhost', 'port': 9200, 'scheme': 'http'}])

app.config['SQLALCHEMY_DATABASE_URI'] = CONFIG['db_uri']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'suck_some_dick'

db = SQLAlchemy(app)
migrate = Migrate(app, db)

logging.basicConfig(
    level=logging.INFO,  # Уровень логирования
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),  # Лог в файл
        logging.StreamHandler()  # Лог в консоль
    ]
)
# Инициализация Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Инициализация YouTube Backup
backup = YouTubeBackup()



def update_interests(username, interests):
    conn = psycopg2.connect(
        dbname="youtube_backup",
        user="your_user", 
        password="your_password", 
        host="localhost", 
        port="5432"
    )
    cursor = conn.cursor()

    query = """
    UPDATE "user"
    SET interests = %s
    WHERE "user" = %s
    """
    
    interests_json = json.dumps({"interests": interests})
    
    cursor.execute(query, (interests_json, username))
    conn.commit()
    
    cursor.close()
    conn.close()







# Модель для видео
class Video(db.Model):
    __tablename__ = 'videos'

    id = db.Column(db.String(11), primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(5000), nullable=True)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    uploader = db.Column(db.String)

    def __repr__(self):
        return f'<Video {self.title}>'

# Модель для пользователя
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(200), nullable=True)
    user_data = db.Column(db.JSON, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_user_data(self):
        """Генерируем и возвращаем JSON данные пользователя"""
        user_data = {
            "username": self.username,
            "email": self.email,
            "avatar": self.avatar,
            "last_login": str(datetime.utcnow())
        }
        return user_data

    def save_user_data(self):
        """Сохраняем данные пользователя в формате JSON в базу данных"""
        self.user_data = self.generate_user_data()
        db.session.commit()
        
# Загружаем пользователя для Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Функция для получения пути к превьюшке
def get_thumbnail_path(video_id):
    try:
        thumbnail_name = f"{video_id}.webp"  # Например: "90.webp"
        full_path = os.path.join(CONFIG['storage_path'], thumbnail_name)
        
        print(f"🔍 Поиск превью: {full_path}")
        if os.path.exists(full_path):
            return url_for('stream_thumbnail', filename=thumbnail_name)
        return None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

def format_views(views):
    """Форматируем количество просмотров в читаемый вид."""
    try:
        if views is None:
            return "0"
        
        # Convert to int if it's a string
        views_int = int(views) if isinstance(views, str) else views
        
        if views_int >= 1_000_000:
            return f"{views_int / 1_000_000:.1f} млн"
        elif views_int >= 1_000:
            return f"{views_int / 1_000:.1f} тыс"
        return str(views_int)
    except (ValueError, TypeError) as e:
        logging.error(f"Error formatting views: {e}")
        return str(views) if views is not None else "0"

# Главная страница
@app.route('/')
def index():
    query = request.args.get('query', '')
    if query:
        result = db.session.execute(
            text("SELECT id, title, description, upload_date, views, uploader FROM videos WHERE title LIKE :query"),
            {"query": f"%{query}%"}
        ).fetchall()
    else:
        result = db.session.execute(
            text("SELECT id, title, description, upload_date, views, uploader FROM videos")
        ).fetchall()

    columns = ['id', 'title', 'description', 'upload_date', 'views', 'uploader']
    videos = [
        {
            'id': row[0],
            'title': row[1],
            'thumbnail_path': get_thumbnail_path(row[0]),  # Передаём только ID!
            'views': format_views(row[4])
        }
        for row in result
    ]
    return render_template('index.html', videos=videos)

# Страница регистрации
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            username = request.form['username']
            email = request.form['email']
            password = request.form['password']
            avatar = request.files.get('avatar')

            if User.query.filter_by(username=username).first():
                flash('Имя пользователя уже существует')
                return redirect(url_for('register'))
            
            if User.query.filter_by(email=email).first():
                flash('Email уже зарегистрирован')
                return redirect(url_for('register'))
            
            avatar_path = None
            if avatar and avatar.filename:
                avatar_dir = 'static/avatars'
                os.makedirs(avatar_dir, exist_ok=True)
                avatar_filename = f'{username}_{int(time.time())}.webp'
                avatar_path = os.path.join(avatar_dir, avatar_filename)
                avatar.save(avatar_path)

            new_user = User(username=username, email=email)
            new_user.set_password(password)
            new_user.avatar = avatar_path
            db.session.add(new_user)
            db.session.commit()

            flash('Регистрация успешна! Теперь вы можете войти.')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Registration error: {e}")
            flash('Произошла ошибка при регистрации')
            return redirect(url_for('register'))

    return render_template('register.html')

# Страница входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            username = request.form['username']
            password = request.form['password']

            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                login_user(user)
                user.save_user_data()
                return redirect(url_for('dashboard'))

            flash('Неверное имя пользователя или пароль.')
        except Exception as e:
            logging.error(f"Login error: {e}")
            flash('Произошла ошибка при входе')

    return render_template('login.html')

# Страница выхода
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.template_filter('format_number')
def format_number(value):
    try:
        return humanize.intcomma(value)
    except:
        return value

# Страница профиля
@app.route('/dashboard')
@login_required
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))  # Перенаправление на страницу логина, если пользователь не авторизован

    return render_template('dashboard.html', user=current_user)
# Запрос на поставку
@app.route('/zapros-na-postavku', methods=['GET', 'POST'])
def zapros_na_postavku():
    if request.method == 'POST':
        try:
            # Извлекаем данные из формы
            action = request.form.get('action')
            query = request.form.get('query')
            count = int(request.form.get('count', 10))
            min_views = int(request.form.get('min_views', 0))
            min_duration = int(request.form.get('min_duration', 0))
            max_duration = int(request.form.get('max_duration', 0)) or float('inf')

            # Логируем полученные параметры
            logging.info(f"Получены данные: action={action}, query={query}, count={count}, "
                         f"min_views={min_views}, min_duration={min_duration}, max_duration={max_duration}")

            if action == 'search_and_download':
                # Логируем начало действия
                logging.info("Начинается поиск и загрузка видео...")
                backup.search_and_download(query, count, min_views, min_duration, max_duration)

                # Извлечение и форматирование данных о видео
                videos = db.session.execute(text("SELECT * FROM videos")).fetchall()
                columns = db.session.execute(text("SELECT * FROM videos LIMIT 1")).keys()

                formatted_videos = [
                    {**dict(zip(columns, row)), 'thumbnail_path': get_thumbnail_path(row[0])}
                    for row in videos
                ]

                # Логируем завершение операции
                logging.info(f"Загрузка и поиск завершены, найдено видео: {len(formatted_videos)}")

                flash('Поиск и загрузка видео завершены!')
                return redirect(url_for('index'))

        except Exception as e:
            # Логируем ошибку
            logging.error(f"Ошибка при обработке запроса: {e}")
            flash('Произошла ошибка при загрузке видео')

    return render_template('zapros_na_postavku.html')
# Стриминг превью
@app.route('/thumbnails/<path:filename>')
def stream_thumbnail(filename):
    try:
        full_path = os.path.join(CONFIG['storage_path'], filename)
        print(f"📤 Отправляю превью: {full_path}")  # ← Для отладки
        return send_from_directory(CONFIG['storage_path'], filename)
    except Exception as e:
        print(f"❌ Ошибка при загрузке превью: {e}")
        return "Not Found", 404








@app.route('/video/<video_id>')
def video_detail(video_id):
    try:
        print(f"🔍 Поиск видео с ID: {video_id}")
        result = db.session.execute(
            text("SELECT * FROM videos WHERE id = :id"), 
            {"id": video_id}
        ).fetchone()

        if not result:
            print(f"❌ Видео с ID {video_id} не найдено.")
            return "Video not found", 404

        video_dict = dict(result._mapping)
        video_dict['thumbnail_path'] = f"/thumbnails/{video_id}.webp"
        
        # Ищем реальные файлы в директории
        video_dir = CONFIG['storage_path']
        for file in os.listdir(video_dir):
            if file.startswith(video_id):
                ext = file.split('.')[-1]
                if ext in ['webm', 'mp4', 'f616']:
                    video_dict[f'file_path_{ext}'] = file
                    print(f"✅ Найден файл: {file}")

        return render_template('video.html', video=video_dict)
    except Exception as e:
        logging.error(f"Video detail error: {e}")
        flash("Произошла ошибка при загрузке видео")
        return redirect(url_for('index'))

@app.route('/stream/<filename>')
def stream_video(filename):
    video_dir = CONFIG['storage_path']
    video_path = os.path.join(video_dir, filename)
    
    print(f"🔍 Проверка пути к видео: {video_path}")

    if os.path.exists(video_path):
        print(f"📤 Стримим видео: {video_path}")
        return send_from_directory(video_dir, filename, as_attachment=False)

    print(f"❌ Видео {filename} не найдено.")
    abort(404)
    
if __name__ == '__main__':
    app.run(debug=True)
