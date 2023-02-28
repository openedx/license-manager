import os

from license_manager.settings.base import *
import tempfile


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
CELERY_TASK_ALWAYS_EAGER = True
results_dir = tempfile.TemporaryDirectory()
CELERY_RESULT_BACKEND = f'file://{results_dir.name}'
# END CELERY

# Increase throttle thresholds for tests
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': '2400/minute',
    'user_burst': '120/second',
    'user_sustained': '2400/minute',
}

# Make some loggers less noisy (useful during test failure)
import logging

for logger_to_silence in ['faker', 'jwkest', 'edx_rest_framework_extensions']:
    logging.getLogger(logger_to_silence).setLevel(logging.WARNING)
# Specifically silence license manager event_utils warnings
logging.getLogger('event_utils').setLevel(logging.ERROR)

# Django Admin Settings
VALIDATE_FORM_EXTERNAL_FIELDS = False
DEBUG = False
