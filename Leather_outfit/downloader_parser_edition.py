import os
import json
import requests
import isodate
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from datetime import datetime
import youtube_dl

# Конфигурация
CONFIG = {
    "storage_path": "/mnt/d/videos",
    "db_uri": "postgresql://impostorboy:0@localhost/youtube_backup",
    "service_account_file": "/home/impostorboy/downlader/service_account.json"
}

# Подключение к базе данных
engine = create_engine(CONFIG['db_uri'])
db = scoped_session(sessionmaker(bind=engine))

class YouTubeBackup:
    def __init__(self):
        self.youtube_service = self.get_youtube_service()
        
    def get_youtube_service(self):
        credentials = service_account.Credentials.from_service_account_file(
            CONFIG['service_account_file'],
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
        )
        return build('youtube', 'v3', credentials=credentials)

    def parse_duration(self, duration):
        try:
            return int(isodate.parse_duration(duration).total_seconds())
        except:
            return 0

    def save_video_to_db(self, video_id, title, description, uploader, views, duration, upload_date):
        try:
            db.execute(text(""" 
                INSERT INTO videos (id, title, description, uploader, views, duration, upload_date) 
                VALUES (:id, :title, :description, :uploader, :views, :duration, :upload_date) 
                ON CONFLICT (id) DO NOTHING;
            """), {
                "id": video_id,
                "title": title,
                "description": description,
                "uploader": uploader,
                "views": views,
                "duration": duration,
                "upload_date": datetime.strptime(upload_date, '%Y-%m-%dT%H:%M:%SZ')
            })
            db.commit()
            print(f"✅ Видео '{title}' добавлено в базу данных.")
        except Exception as e:
            print(f"❌ Ошибка при добавлении видео в базу данных: {e}")

    def download_thumbnail(self, video_id, format="jpg"):
        try:
            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.{format}"
            thumbnail_path = f"{CONFIG['storage_path']}/{video_id}.{format}"
            
            response = requests.get(thumbnail_url)
            if response.status_code == 200:
                with open(thumbnail_path, 'wb') as f:
                    f.write(response.content)
                print(f"✅ Превью загружено: {thumbnail_path}")
            else:
                print("❌ Не удалось скачать превью.")
        except Exception as e:
            print(f"❌ Ошибка при загрузке превью: {e}")

    def get_video_info(self, video_id):
        try:
            video_request = self.youtube_service.videos().list(
                part='snippet,contentDetails,statistics',
                id=video_id
            )
            video_response = video_request.execute()

            if not video_response['items']:
                return None

            video_data = video_response['items'][0]
            return {
                'title': video_data['snippet']['title'],
                'description': video_data['snippet']['description'],
                'uploader': video_data['snippet']['channelTitle'],
                'views': int(video_data['statistics'].get('viewCount', 0)),
                'duration': self.parse_duration(video_data['contentDetails']['duration']),
                'upload_date': video_data['snippet']['publishedAt']
            }
        except HttpError as e:
            print(f"❌ Ошибка API: {e}")
            return None

    def check_video_exists(self, video_id):
        result = db.execute(text("SELECT 1 FROM videos WHERE id = :id"), {"id": video_id})
        return result.fetchone() is not None

    def download_video(self, video_id, video_format="best"):
        output_template = f"{CONFIG['storage_path']}/%(id)s.%(ext)s"
        ydl_opts = {
            'format': video_format,
            'outtmpl': output_template,
            'noplaylist': True,
            'quiet': False,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',  # Добавьте файл с кукисами, если нужно
            'geo_bypass': True,  # Обход гео-ограничений
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }

        try:
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f'https://youtube.com/watch?v={video_id}'])
            print(f"✅ Видео {video_id} успешно загружено.")
        except Exception as e:
            print(f"❌ Ошибка при загрузке видео {video_id}: {e}")

    def process_video(self, video_id, thumbnail_format="jpg", video_format="best"):
        if self.check_video_exists(video_id):
            print(f"⚠️ Видео {video_id} уже существует в базе. Пропускаем.")
            return

        video_info = self.get_video_info(video_id)
        if not video_info:
            return

        self.download_thumbnail(video_id, thumbnail_format)
        self.save_video_to_db(
            video_id,
            video_info['title'],
            video_info['description'],
            video_info['uploader'],
            video_info['views'],
            video_info['duration'],
            video_info['upload_date']
        )
        self.download_video(video_id, video_format)

    def search_and_download(self, query, max_results=300, min_views=0, min_duration=0, max_duration=float('inf')):
        try:
            search_request = self.youtube_service.search().list(
                q=query,
                part='id,snippet',
                maxResults=max_results,
                type='video'
            )
            search_response = search_request.execute()

            for item in search_response['items']:
                video_id = item['id']['videoId']
                video_info = self.get_video_info(video_id)
                if not video_info:
                    continue

                # Фильтр по просмотрам
                if video_info['views'] < min_views:
                    print(f"⚠️ Пропущено видео '{video_info['title']}' из-за недостаточного количества просмотров ({video_info['views']})")
                    continue

                # Фильтр по длительности
                if video_info['duration'] < min_duration or video_info['duration'] > max_duration:
                    print(f"⚠️ Пропущено видео '{video_info['title']}' из-за неподходящей длины ({video_info['duration']} секунд)")
                    continue

                print(f"✅ Найдено видео: {video_info['title']} ({video_info['duration']} сек) с {video_info['views']} просмотрами")
                self.process_video(video_id)
                
        except HttpError as e:
            print(f"❌ Ошибка при поиске: {e}")

    def mass_download(self, file_path):
        with open(file_path, 'r') as file:
            video_urls = file.readlines()

        for url in video_urls:
            video_id = url.strip().split('v=')[1].split('&')[0]
            self.process_video(video_id)


def main():
    backup = YouTubeBackup()
    
    print("Выберите режим работы:")
    print("1 - Загрузить одно видео")
    print("2 - Массовая загрузка из файла")
    print("3 - Поиск и загрузка по запросу")
    
    choice = input("Ваш выбор: ")
    
    if choice == '1':
        url = input("Введите URL видео: ")
        if 'v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
            thumbnail_format = input("Введите формат превью (например, jpg, png): ")
            video_format = input("Введите формат видео (например, best, mp4): ")
            backup.process_video(video_id, thumbnail_format, video_format)
    elif choice == '2':
        file_path = input("Введите путь к файлу с URL: ")
        backup.mass_download(file_path)
    elif choice == '3':
        query = input("Введите поисковый запрос: ")
        count = int(input("Количество видео для загрузки: "))
        min_views = int(input("Введите минимальное количество просмотров: "))
        min_duration = int(input("Введите минимальную длительность видео (в секундах): "))
        max_duration = int(input("Введите максимальную длительность видео (в секундах): "))
        backup.search_and_download(query, count, min_views, min_duration, max_duration)
    else:
        print("❌ Неверный выбор")

if __name__ == "__main__":
    main()