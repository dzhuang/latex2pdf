#!/usr/bin/env bash

# This will be availabel on Django 3.0
#if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ] ; then
#    (python manage.py createsuperuser --no-input)
#fi

USER_REQUIREMENTS=/opt/latex2pdf/local_settings/requirements.txt
if test -f "$USER_REQUIREMENTS"; then
    pip install -r $USER_REQUIREMENTS
fi

python manage.py makemigrations
python manage.py migrate --noinput

(gunicorn latex2pdf.wsgi --user www-data --bind 0.0.0.0:8010 --workers 3) &
nginx -g "daemon off;"
