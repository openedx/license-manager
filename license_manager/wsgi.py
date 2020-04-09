"""
WSGI config for license_manager.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/howto/deployment/wsgi/
"""
import os
from os.path import abspath, dirname
from sys import path

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application


SITE_ROOT = dirname(dirname(abspath(__file__)))
path.append(SITE_ROOT)

application = get_wsgi_application()  # pylint: disable=invalid-name

# Allows the gunicorn app to serve static files in development environment.
# Without this, css in django admin will not be served locally.
if settings.DEBUG:
    application = StaticFilesHandler(get_wsgi_application())
else:
    application = get_wsgi_application()
