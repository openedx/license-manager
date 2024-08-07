import os
from os.path import abspath, dirname, join

from corsheaders.defaults import default_headers as corsheaders_default_headers

from license_manager.apps.subscriptions.constants import (
    PROVISIONING_SUBSCRIPTION_ADMIN_ROLE,
    PROVISIONING_CUSTOMER_AGREEMENT_ADMIN_ROLE,
    SUBSCRIPTIONS_ADMIN_ROLE,
    SUBSCRIPTIONS_LEARNER_ROLE,
    SYSTEM_ENTERPRISE_ADMIN_ROLE,
    SYSTEM_ENTERPRISE_LEARNER_ROLE,
    SYSTEM_ENTERPRISE_OPERATOR_ROLE,
    SYSTEM_ENTERPRISE_PROVISIONING_ADMIN_ROLE,
)
from license_manager.settings.utils import get_logger_config

# PATH vars
here = lambda *x: join(abspath(dirname(__file__)), *x)
PROJECT_ROOT = here("..")
root = lambda *x: join(abspath(PROJECT_ROOT), *x)


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('LICENSE_MANAGER_SECRET_KEY', 'insecure-secret-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = []

# Application definition

INSTALLED_APPS = (
    # These have to be installed before the core django admin app
    'dal',
    'dal_select2',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
)

THIRD_PARTY_APPS = (
    'corsheaders',
    'csrf.apps.CsrfAppConfig',  # Enables frontend apps to retrieve CSRF tokens
    'django_celery_results',
    'django_filters',
    'djangoql',
    'durationwidget',
    'rest_framework',
    'drf_spectacular',
    'rules.apps.AutodiscoverRulesConfig',
    'simple_history',
    'simplejson',
    'social_django',
    'waffle',
)

PROJECT_APPS = (
    'license_manager.apps.core',
    'license_manager.apps.api',
    'license_manager.apps.subscriptions.apps.SubscriptionsConfig',
)

INSTALLED_APPS += THIRD_PARTY_APPS
INSTALLED_APPS += PROJECT_APPS

MIDDLEWARE = (
    'log_request_id.middleware.RequestIDMiddleware',
    'edx_django_utils.monitoring.CookieMonitoringMiddleware',
    'edx_django_utils.monitoring.DeploymentMonitoringMiddleware',
    # Resets RequestCache utility for added safety.
    'edx_django_utils.cache.middleware.RequestCacheMiddleware',

    # Enables monitoring utility for writing custom metrics.
    'edx_django_utils.monitoring.CachedCustomMonitoringMiddleware',

    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'edx_rest_framework_extensions.auth.jwt.middleware.JwtAuthCookieMiddleware',
    'edx_rest_framework_extensions.auth.jwt.middleware.JwtRedirectToLoginIfUnauthenticatedMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'social_django.middleware.SocialAuthExceptionMiddleware',
    'waffle.middleware.WaffleMiddleware',

    # Enables force_django_cache_miss functionality for TieredCache.
    'edx_django_utils.cache.middleware.TieredCacheMiddleware',

    # Outputs monitoring metrics for a request.
    'edx_rest_framework_extensions.middleware.RequestCustomAttributesMiddleware',

    # Ensures proper DRF permissions in support of JWTs
    'edx_rest_framework_extensions.auth.jwt.middleware.EnsureJWTAuthSettingsMiddleware',

    # Lets simple history track which user made changes
    'simple_history.middleware.HistoryRequestMiddleware',
)

# https://github.com/dabapps/django-log-request-id
LOG_REQUEST_ID_HEADER = "HTTP_X_REQUEST_ID"
GENERATE_REQUEST_ID_IF_NOT_IN_HEADER = False
REQUEST_ID_RESPONSE_HEADER = "X-Request-ID"
NO_REQUEST_ID = "None"
LOG_REQUESTS = False

# Enable CORS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = corsheaders_default_headers + (
    'use-jwt-cookie',
)
CORS_ORIGIN_WHITELIST = []

ROOT_URLCONF = 'license_manager.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'license_manager.wsgi.application'

# Database
# https://docs.djangoproject.com/en/1.11/ref/settings/#databases
# Set this value in the environment-specific files (e.g. local.py, production.py, test.py)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.',
        'NAME': '',
        'USER': '',
        'PASSWORD': '',
        'HOST': '',  # Empty for localhost through domain sockets or '127.0.0.1' for localhost through TCP.
        'PORT': '',  # Set to empty string for default.
    }
}

# Django Rest Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'edx_rest_framework_extensions.auth.jwt.authentication.JwtAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        'rest_framework.permissions.IsAdminUser',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'PAGE_SIZE': 100,
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'license_manager.apps.core.throttles.UserBurstRateThrottle',
        'license_manager.apps.core.throttles.UserSustainedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user_burst': '18/second',
        'user_sustained': '360/minute',
    }
}

# Internationalization
# https://docs.djangoproject.com/en/dev/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Django 4.0+ uses zoneinfo if this is not set. We can remove this and
# migrate to zoneinfo after Django 4.2 upgrade. See more on following url
# https://docs.djangoproject.com/en/4.2/releases/4.0/#zoneinfo-default-timezone-implementation
USE_DEPRECATED_PYTZ = True

LOCALE_PATHS = (
    root('conf', 'locale'),
)


# MEDIA CONFIGURATION
# See: https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = root('media')

# See: https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = '/media/'
# END MEDIA CONFIGURATION


# STATIC FILE CONFIGURATION
# See: https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = root('assets')

# See: https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = '/static/'

# See: https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = (
    root('static'),
)

# TEMPLATE CONFIGURATION
# See: https://docs.djangoproject.com/en/1.11/ref/settings/#templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'DIRS': (
            root('templates'),
        ),
        'OPTIONS': {
            'context_processors': (
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.request',
                'django.template.context_processors.debug',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.contrib.messages.context_processors.messages',
                'license_manager.apps.core.context_processors.core',
            ),
            'debug': True,  # Django will only display debug pages if the global DEBUG setting is set to True.
        }
    },
]
# END TEMPLATE CONFIGURATION


# COOKIE CONFIGURATION
# The purpose of customizing the cookie names is to avoid conflicts when
# multiple Django services are running behind the same hostname.
# Detailed information at: https://docs.djangoproject.com/en/dev/ref/settings/
SESSION_COOKIE_NAME = 'license_manager_sessionid'
CSRF_COOKIE_NAME = 'license_manager_csrftoken'
LANGUAGE_COOKIE_NAME = 'license_manager_language'
# END COOKIE CONFIGURATION

CSRF_COOKIE_SECURE = False
CSRF_TRUSTED_ORIGINS = []

# AUTHENTICATION CONFIGURATION
LOGIN_URL = '/login/'
LOGOUT_URL = '/logout/'

AUTH_USER_MODEL = 'core.User'

AUTHENTICATION_BACKENDS = (
    'auth_backends.backends.EdXOAuth2',
    'rules.permissions.ObjectPermissionBackend',
    'django.contrib.auth.backends.ModelBackend',
)

ENABLE_AUTO_AUTH = False
AUTO_AUTH_USERNAME_PREFIX = 'auto_auth_'

SOCIAL_AUTH_STRATEGY = 'auth_backends.strategies.EdxDjangoStrategy'

# Set these to the correct values for your OAuth2 provider (e.g., LMS)
SOCIAL_AUTH_EDX_OAUTH2_KEY = 'license-manager-sso-key'
SOCIAL_AUTH_EDX_OAUTH2_SECRET = 'license-manager-sso-secret'
SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT = 'http://127.0.0.1:8000'
SOCIAL_AUTH_EDX_OAUTH2_LOGOUT_URL = 'http://127.0.0.1:8000/logout'
BACKEND_SERVICE_EDX_OAUTH2_KEY = 'license-manager-backend-service-key'
BACKEND_SERVICE_EDX_OAUTH2_SECRET = 'license-manager-service-secret'

JWT_AUTH = {
    'JWT_AUTH_HEADER_PREFIX': 'JWT',
    'JWT_ISSUER': 'http://127.0.0.1:18000/oauth2',
    'JWT_ALGORITHM': 'HS256',
    'JWT_VERIFY_EXPIRATION': True,
    'JWT_PAYLOAD_GET_USERNAME_HANDLER': lambda d: d.get('preferred_username'),
    'JWT_LEEWAY': 1,
    'JWT_DECODE_HANDLER': 'edx_rest_framework_extensions.auth.jwt.decoder.jwt_decode_handler',
    'JWT_PUBLIC_SIGNING_JWK_SET': None,
    'JWT_AUTH_COOKIE': 'edx-jwt-cookie',
    'JWT_AUTH_COOKIE_HEADER_PAYLOAD': 'edx-jwt-cookie-header-payload',
    'JWT_AUTH_COOKIE_SIGNATURE': 'edx-jwt-cookie-signature',
    'JWT_SECRET_KEY': 'SET-ME-PLEASE',
    # JWT_ISSUERS enables token decoding for multiple issuers (Note: This is not a native DRF-JWT field)
    # We use it to allow different values for the 'ISSUER' field, but keep the same SECRET_KEY and
    # AUDIENCE values across all issuers.
    'JWT_ISSUERS': [
        {
            'AUDIENCE': 'SET-ME-PLEASE',
            'ISSUER': 'http://localhost:18000/oauth2',
            'SECRET_KEY': 'SET-ME-PLEASE'
        },
    ],
}

# Request the user's permissions in the ID token
EXTRA_SCOPE = ['permissions']

LOGIN_REDIRECT_URL = '/admin/'
# END AUTHENTICATION CONFIGURATION


# OPENEDX-SPECIFIC CONFIGURATION
PLATFORM_NAME = 'Your Platform Name Here'
# END OPENEDX-SPECIFIC CONFIGURATION

# Set up logging for development use (logging to stdout)
LOGGING = get_logger_config(debug=DEBUG, dev_env=True)

"""############################# BEGIN CELERY CONFIG ##################################"""

# Message configuration
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_COMPRESSION = 'gzip'
CELERY_RESULT_COMPRESSION = 'gzip'

# Results configuration
CELERY_TASK_IGNORE_RESULT = False
CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED = True

# Events configuration
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True

# Celery task routing configuration.
# Only the license_manager worker should receive license_manager tasks.
# Explicitly define these to avoid name collisions with other services
# using the same broker and the standard default queue name of "celery".
CELERY_TASK_DEFAULT_EXCHANGE = os.environ.get('CELERY_DEFAULT_EXCHANGE', 'license_manager')
CELERY_TASK_DEFAULT_ROUTING_KEY = os.environ.get('CELERY_DEFAULT_ROUTING_KEY', 'license_manager')
CELERY_TASK_DEFAULT_QUEUE = os.environ.get('CELERY_DEFAULT_QUEUE', 'license_manager.default')

# Celery Broker
# These settings need not be set if CELERY_TASK_ALWAYS_EAGER == True, like in Standalone.
# Devstack overrides these in its docker-compose.yml.
# Production environments can override these to be whatever they want.
CELERY_BROKER_TRANSPORT = os.environ.get('CELERY_BROKER_TRANSPORT', '')
CELERY_BROKER_HOSTNAME = os.environ.get('CELERY_BROKER_HOSTNAME', '')
CELERY_BROKER_VHOST = os.environ.get('CELERY_BROKER_VHOST', '')
CELERY_BROKER_USER = os.environ.get('CELERY_BROKER_USER', '')
CELERY_BROKER_PASSWORD = os.environ.get('CELERY_BROKER_PASSWORD', '')
CELERY_BROKER_URL = '{}://{}:{}@{}/{}'.format(
    CELERY_BROKER_TRANSPORT,
    CELERY_BROKER_USER,
    CELERY_BROKER_PASSWORD,
    CELERY_BROKER_HOSTNAME,
    CELERY_BROKER_VHOST
)
CELERY_RESULT_BACKEND = 'django-db'

# see https://github.com/celery/django-celery-results/issues/326
# on CELERY_RESULT_EXTENDED
CELERY_RESULT_EXTENDED = True

# Celery task time limits.
# Tasks will be asked to quit after four minutes, and un-gracefully killed
# after five.
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_TIME_LIMIT = 300

CELERY_BROKER_TRANSPORT_OPTIONS = {
    'fanout_patterns': True,
    'fanout_prefix': True,
}

# Route licensed bulk enrollment tasks to a dedicated queue
CELERY_TASK_ROUTES = {
    'license_manager.apps.api.tasks.enterprise_enrollment_license_subsidy_task': {
        'queue': 'license_manager.bulk_enrollment',
    },
}
"""############################# END CELERY CONFIG ##################################"""

# Email configuration settings
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'  # Prints 'sent' emails to the console for development
# Alternative email backend enables the output of emails to a given filepath (useful for HTML template debugging)
"""
EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
EMAIL_FILE_PATH = './emails'
"""
EMAIL_UNSUBSCRIBE_LINK = 'https://www.edx.org'  # Dummy unsubscribe link for development use
SUBSCRIPTIONS_FROM_EMAIL = 'from@example.com'  # Dummy from email address for development use
CUSTOMER_SUCCESS_EMAIL_ADDRESS = 'ecs@example.com'  # Dummy ECS email address for development use
# End email configuration

# Default URLS for external services
ENTERPRISE_CATALOG_URL = os.environ.get('ENTERPRISE_CATALOG_URL', '')
ENTERPRISE_LEARNER_PORTAL_BASE_URL = os.environ.get('ENTERPRISE_LEARNER_PORTAL_BASE_URL', '')
ENTERPRISE_ADMIN_PORTAL_BASE_URL = os.environ.get('ENTERPRISE_ADMIN_PORTAL_BASE_URL', 'localhost:1991')
LMS_URL = os.environ.get('LMS_URL', '')
SUPPORT_SITE_URL = os.environ.get('SUPPORT_SITE_URL', '')

# Bulk enroll specific
BULK_ENROLL_REQUEST_TIMEOUT_SECONDS = os.environ.get('BULK_ENROLL_REQUEST_TIMEOUT_SECONDS', 180)
BULK_ENROLL_REQUEST_LIMIT = os.environ.get('BULK_ENROLL_REQUEST_LIMIT', 500)
BULK_ENROLL_JOB_AWS_BUCKET = os.environ.get('BULK_ENROLL_JOB_AWS_BUCKET', '')
BULK_ENROLL_RESULT_CAMPAIGN = os.environ.get('BULK_ENROLL_RESULT_CAMPAIGN', '')

# Set up system-to-feature roles mapping for edx-rbac
SYSTEM_TO_FEATURE_ROLE_MAPPING = {
    SYSTEM_ENTERPRISE_OPERATOR_ROLE: [SUBSCRIPTIONS_ADMIN_ROLE],
    SYSTEM_ENTERPRISE_ADMIN_ROLE: [SUBSCRIPTIONS_ADMIN_ROLE],
    SYSTEM_ENTERPRISE_LEARNER_ROLE: [SUBSCRIPTIONS_LEARNER_ROLE],
    SYSTEM_ENTERPRISE_PROVISIONING_ADMIN_ROLE: [
        PROVISIONING_SUBSCRIPTION_ADMIN_ROLE,
        PROVISIONING_CUSTOMER_AGREEMENT_ADMIN_ROLE,
    ]
}

SOCIAL_MEDIA_FOOTER_URLS = os.environ.get('SOCIAL_MEDIA_FOOTER_URLS', '')
MOBILE_STORE_URLS = os.environ.get('MOBILE_STORE_URLS', '')

# User retirement settings
RETIREMENT_SERVICE_WORKER_USERNAME = "replace with valid username"

# Feature Toggles
FEATURES = {}


DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

DEFAULT_DAYS_BEFORE_LICENSE_PURGE = 90

ENTERPRISE_SUBSIDY_CHECKSUM_ALGORITHM = 'sha256'
ENTERPRISE_SUBSIDY_CHECKSUM_SECRET_KEY = 'please-set-me'
ENTERPRISE_SUBSIDY_CHECKSUM_MESSAGE_FORMAT = '{lms_user_id}:{course_key}:{license_uuid}'

SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS = 12

# Braze
AUTOAPPLY_WITH_LEARNER_PORTAL_CAMPAIGN = ''
AUTOAPPLY_NO_LEARNER_PORTAL_CAMPAIGN = ''
INITIAL_LICENSE_UTILIZATION_CAMPAIGN = ''
NO_ALLOCATIONS_REMAINING_CAMPAIGN = ''
LIMITED_ALLOCATIONS_REMAINING_CAMPAIGN = ''
BRAZE_ASSIGNMENT_EMAIL_CAMPAIGN = ''
BRAZE_ACTIVATION_EMAIL_CAMPAIGN = ''
BRAZE_REMIND_EMAIL_CAMPAIGN = ''
BRAZE_REVOKE_CAP_EMAIL_CAMPAIGN = ''

BRAZE_API_URL = ''
BRAZE_API_KEY = os.environ.get('BRAZE_API_KEY', '')
BRAZE_APP_ID = os.environ.get('BRAZE_APP_ID', '')

# Set a datetime that a django action can reset license state to
# Use year-month-day hour:minute:second format
LICENSE_REVERT_SNAPSHOT_TIMESTAMP = '9999-12-31 23:59:59'

# Django Admin Settings
VALIDATE_FORM_EXTERNAL_FIELDS = True

# disable indexing on history_date
SIMPLE_HISTORY_DATE_INDEX = False

# DRF Spectacular settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'License Manager API',
    'DESCRIPTION': 'API for querying and commanding about license manager records.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'POSTPROCESSING_HOOKS': [
        'license_manager.apps.api.utils.make_swagger_var_param_optional',
    ],
}

# An allow list of enterprise catalog uuids that excused from  violations
# in the ``validate_num_catalog_queries`` management command
CUSTOM_CATALOG_PRODUCTS_ALLOW_LIST = [

]

CUSTOMERS_WITH_CUSTOM_LICENSE_EVENTS = ['00000000-1111-2222-3333-444444444444']
