release: python manage.py check --deploy && python manage.py migrate --noinput
web: python manage.py check --deploy && exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 4
worker: python manage.py check --deploy && exec python manage.py run_worker --duration 3600
