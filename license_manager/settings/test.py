import os

from license_manager.settings.base import *


# IN-MEMORY TEST DATABASE
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    },
}
# END IN-MEMORY TEST DATABASE

# BEGIN CELERY
CELERY_ALWAYS_EAGER = True
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://:password@redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://:password@redis:6379/0')
CELERY_IGNORE_RESULT = True
# END CELERY

# Make some loggers less noisy (useful during test failure)
import logging

for logger_to_silence in ['faker', 'jwkest', 'edx_rest_framework_extensions']:
    logging.getLogger(logger_to_silence).setLevel(logging.WARNING)
