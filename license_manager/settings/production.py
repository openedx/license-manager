from os import environ
import yaml

from license_manager.settings.base import *
from license_manager.settings.utils import get_env_setting, get_logger_config


DEBUG = False
TEMPLATE_DEBUG = DEBUG

ALLOWED_HOSTS = ['*']

LOGGING = get_logger_config()

# Keep track of the names of settings that represent dicts. Instead of overriding the values in base.py,
# the values read from disk should UPDATE the pre-configured dicts.
DICT_UPDATE_KEYS = ('JWT_AUTH',)

# This may be overridden by the YAML in license_manager_CFG,
# but it should be here as a default.
MEDIA_STORAGE_BACKEND = {}
FILE_STORAGE_BACKEND = {}

CONFIG_FILE = get_env_setting('LICENSE_MANAGER_CFG')
with open(CONFIG_FILE, encoding='utf-8') as f:
    config_from_yaml = yaml.load(f)

    # Remove the items that should be used to update dicts, and apply them separately rather
    # than pumping them into the local vars.
    dict_updates = {key: config_from_yaml.pop(key, None) for key in DICT_UPDATE_KEYS}

    for key, value in dict_updates.items():
        if value:
            vars()[key].update(value)

    vars().update(config_from_yaml)

    # Unpack the media and files storage backend settings for django storages.
    # These dicts are not Django settings themselves, but they contain a mapping
    # of Django settings.
    vars().update(FILE_STORAGE_BACKEND)
    vars().update(MEDIA_STORAGE_BACKEND)

DB_OVERRIDES = dict(
    PASSWORD=environ.get('DB_MIGRATION_PASS', DATABASES['default']['PASSWORD']),
    ENGINE=environ.get('DB_MIGRATION_ENGINE', DATABASES['default']['ENGINE']),
    USER=environ.get('DB_MIGRATION_USER', DATABASES['default']['USER']),
    NAME=environ.get('DB_MIGRATION_NAME', DATABASES['default']['NAME']),
    HOST=environ.get('DB_MIGRATION_HOST', DATABASES['default']['HOST']),
    PORT=environ.get('DB_MIGRATION_PORT', DATABASES['default']['PORT']),
)

# BEGIN CELERY
CELERYD_HIJACK_ROOT_LOGGER = False
BROKER_URL = "{0}://{1}:{2}@{3}/{4}".format(
    CELERY_BROKER_TRANSPORT,
    CELERY_BROKER_USER,
    CELERY_BROKER_PASSWORD,
    CELERY_BROKER_HOSTNAME,
    CELERY_BROKER_VHOST
)
# END CELERY

# Email configuration settings
EMAIL_BACKEND = 'django_ses.SESBackend'  # Using Amazon AWS SES as an email backend

for override, value in DB_OVERRIDES.items():
    DATABASES['default'][override] = value
