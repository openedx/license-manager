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
CELERY_RESULT_BACKEND = 'file://{}'.format(results_dir.name)
# END CELERY

# Make some loggers less noisy (useful during test failure)
import logging

for logger_to_silence in ['faker', 'jwkest', 'edx_rest_framework_extensions']:
    logging.getLogger(logger_to_silence).setLevel(logging.WARNING)
