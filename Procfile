web: gunicorn itrix.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
release: python manage.py migrate --noinput
worker: celery -A tasks.celery worker --loglevel=info
beat: celery -A tasks.celery beat --loglevel=info
