from os import environ
import yaml

from license_manager.settings.base import *
from license_manager.settings.utils import get_env_setting, get_logger_config


DEBUG = False
TEMPLATE_DEBUG = DEBUG

# IMPORTANT: With this enabled, the server must always be behind a proxy that
# strips the header HTTP_X_FORWARDED_PROTO from client requests. Otherwise,
# a user can fool our server into thinking it was an https connection.
# See
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
# for other warnings.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

ALLOWED_HOSTS = ['*']

# Keep track of the names of settings that represent dicts. Instead of overriding the values in base.py,
# the values read from disk should UPDATE the pre-configured dicts.
DICT_UPDATE_KEYS = ('JWT_AUTH', 'REST_FRAMEWORK')

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# This may be overridden by the YAML in license_manager_CFG,
# but it should be here as a default.
MEDIA_STORAGE_BACKEND = {}
FILE_STORAGE_BACKEND = {}

# Allow extra headers for your specicfic production environment.
# Set this variable in the config yaml, and the values will be appended to CORS_ALLOW_HEADERS.
CORS_ALLOW_HEADERS_EXTRA = ()

CONFIG_FILE = get_env_setting('LICENSE_MANAGER_CFG')
with open(CONFIG_FILE, encoding='utf-8') as f:
    config_from_yaml = yaml.safe_load(f)

    # Remove the items that should be used to update dicts, and apply them separately rather
    # than pumping them into the local vars.
    dict_updates = {key: config_from_yaml.pop(key, None) for key in DICT_UPDATE_KEYS}

    for key, value in dict_updates.items():
        if value:
            vars()[key].update(value)

    vars().update(config_from_yaml)

    # Fallback for DEFAULT_FILE_STORAGE and STATICFILES_STORAGE settings.
    # If these keys are present in the YAML config, use them to override the default storage backends.
    media_default_backend = MEDIA_STORAGE_BACKEND.pop("DEFAULT_FILE_STORAGE", None)
    file_default_backend = FILE_STORAGE_BACKEND.pop("DEFAULT_FILE_STORAGE", None)
    media_static_backend = MEDIA_STORAGE_BACKEND.pop("STATICFILES_STORAGE", None)
    file_static_backend = FILE_STORAGE_BACKEND.pop("STATICFILES_STORAGE", None)

    default_backend = media_default_backend or file_default_backend
    static_backend = media_static_backend or file_static_backend

    if default_backend:
        STORAGES['default']['BACKEND'] = default_backend
    if static_backend:
        STORAGES['staticfiles']['BACKEND'] = static_backend

    # Unpack the media and files storage backend settings for django storages.
    # These dicts are not Django settings themselves, but they contain a mapping
    # of Django settings.
    vars().update(FILE_STORAGE_BACKEND)
    vars().update(MEDIA_STORAGE_BACKEND)

# Must be generated after loading config YAML because LOGGING_FORMAT_STRING might be overridden.
LOGGING = get_logger_config(format_string=LOGGING_FORMAT_STRING)

DB_OVERRIDES = dict(
    PASSWORD=environ.get('DB_MIGRATION_PASS', DATABASES['default']['PASSWORD']),
    ENGINE=environ.get('DB_MIGRATION_ENGINE', DATABASES['default']['ENGINE']),
    USER=environ.get('DB_MIGRATION_USER', DATABASES['default']['USER']),
    NAME=environ.get('DB_MIGRATION_NAME', DATABASES['default']['NAME']),
    HOST=environ.get('DB_MIGRATION_HOST', DATABASES['default']['HOST']),
    PORT=environ.get('DB_MIGRATION_PORT', DATABASES['default']['PORT']),
)

# BEGIN CELERY
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_BROKER_URL = "{}://{}:{}@{}/{}".format(
    CELERY_BROKER_TRANSPORT,
    CELERY_BROKER_USER,
    CELERY_BROKER_PASSWORD,
    CELERY_BROKER_HOSTNAME,
    CELERY_BROKER_VHOST
)
# END CELERY

# BEGIN CORS
# Inject extra allowed headers specific to a production environment.
CORS_ALLOW_HEADERS = (
    *CORS_ALLOW_HEADERS,
    *CORS_ALLOW_HEADERS_EXTRA,
)
# END CORS

# Email configuration settings
EMAIL_BACKEND = 'django_ses.SESBackend'  # Using Amazon AWS SES as an email backend

for override, value in DB_OVERRIDES.items():
    DATABASES['default'][override] = value
