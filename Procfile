web: daphne -b 0.0.0.0 -p $PORT itrix.asgi:application
worker: celery -A tasks.celery worker --loglevel=info
beat: celery -A tasks.celery beat --loglevel=info
