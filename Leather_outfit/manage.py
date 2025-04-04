from flask import Flask
from flask_migrate import Migrate
from your_flask_app import app, db  # замените на файл, где у вас инициализируется приложение и база данных
from flask_migrate import MigrateCommand
from flask.cli import with_appcontext
import click

migrate = Migrate(app, db)

@app.cli.command("db_init")
@with_appcontext
def db_init():
    """Инициализация базы данных."""
    db.create_all()
    print("Database initialized.")

# Использование Flask CLI
if __name__ == "__main__":
    app.run()
