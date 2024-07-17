from license_manager.settings.local import *

# Generic OAuth2 variables irrespective of SSO/backend service key types.
OAUTH2_PROVIDER_URL = 'http://edx.devstack.lms:18000/oauth2'
ALLOWED_HOSTS = ['*']
# API GATEWAY Settings
API_GATEWAY_URL = 'api.gateway.url'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'license_manager',
        'USER': 'root',
        'PASSWORD': '',
        'HOST': 'license-manager.mysql',
        'PORT': '3306',
    }
}

# OAuth2 variables specific to social-auth/SSO login use case.
SOCIAL_AUTH_EDX_OAUTH2_KEY = os.environ.get('SOCIAL_AUTH_EDX_OAUTH2_KEY', 'license_manager-sso-key')
SOCIAL_AUTH_EDX_OAUTH2_SECRET = os.environ.get('SOCIAL_AUTH_EDX_OAUTH2_SECRET', 'license_manager-sso-secret')
SOCIAL_AUTH_EDX_OAUTH2_ISSUER = os.environ.get('SOCIAL_AUTH_EDX_OAUTH2_ISSUER', 'http://localhost:18000')
SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT = os.environ.get('SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT', 'http://edx.devstack.lms:18000')
SOCIAL_AUTH_EDX_OAUTH2_LOGOUT_URL = os.environ.get('SOCIAL_AUTH_EDX_OAUTH2_LOGOUT_URL', 'http://localhost:18000/logout')
SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT = os.environ.get(
    'SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT', 'http://localhost:18000',
)

# OAuth2 variables specific to backend service API calls.
BACKEND_SERVICE_EDX_OAUTH2_KEY = os.environ.get('BACKEND_SERVICE_EDX_OAUTH2_KEY', 'license_manager-backend-service-key')
BACKEND_SERVICE_EDX_OAUTH2_SECRET = os.environ.get('BACKEND_SERVICE_EDX_OAUTH2_SECRET', 'license_manager-backend-service-secret')

JWT_AUTH.update({
    'JWT_SECRET_KEY': 'lms-secret',
    'JWT_ISSUER': 'http://localhost:18000/oauth2',
    'JWT_AUDIENCE': None,
    'JWT_VERIFY_AUDIENCE': False,
    'JWT_PUBLIC_SIGNING_JWK_SET': (
        '{"keys": [{"kid": "devstack_key", "e": "AQAB", "kty": "RSA", "n": "smKFSYowG6nNUAdeqH1jQQnH1PmIHphzBmwJ5vRf1vu'
        '48BUI5VcVtUWIPqzRK_LDSlZYh9D0YFL0ZTxIrlb6Tn3Xz7pYvpIAeYuQv3_H5p8tbz7Fb8r63c1828wXPITVTv8f7oxx5W3lFFgpFAyYMmROC'
        '4Ee9qG5T38LFe8_oAuFCEntimWxN9F3P-FJQy43TL7wG54WodgiM0EgzkeLr5K6cDnyckWjTuZbWI-4ffcTgTZsL_Kq1owa_J2ngEfxMCObnzG'
        'y5ZLcTUomo4rZLjghVpq6KZxfS6I1Vz79ZsMVUWEdXOYePCKKsrQG20ogQEkmTf9FT_SouC6jPcHLXw"}]}'
    ),
    'JWT_ISSUERS': [{
        'AUDIENCE': 'lms-key',
        'ISSUER': 'http://localhost:18000/oauth2',
        'SECRET_KEY': 'lms-secret',
    }],
})


# BEGIN CELERY
CELERY_WORKER_HIJACK_ROOT_LOGGER = True
CELERY_TASK_ALWAYS_EAGER = (
    os.environ.get("CELERY_ALWAYS_EAGER", "false").lower() == "true"
)
# END CELERY

# CORS CONFIG
CORS_ORIGIN_WHITELIST = [
    'http://localhost:1991',  # frontend-admin-portal
    'http://localhost:8734',  # frontend-app-learner-portal-enterprise
    'http://localhost:18450',  # frontend-app-support-tools
]
# END CORS

# CSRF CONFIG
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:1991',  # frontend-app-admin-portal
    'http://localhost:8734',  # frontend-app-learner-portal-enterprise
    'http://localhost:18450',  # frontend-app-support-tools
]
# END CSRF CONFIG

ENTERPRISE_LEARNER_PORTAL_BASE_URL = 'http://localhost:8734'
ENTERPRISE_CATALOG_URL = 'http://enterprise.catalog.app:18160'
LMS_URL = 'http://edx.devstack.lms:18000'
SUPPORT_SITE_URL = 'https://support.edx.org'

# URLs used for email footers
MOBILE_STORE_URLS = {
    'apple': 'https://itunes.apple.com/us/app/edx/id945480667?mt=8',
    'google': 'https://play.google.com/store/apps/details?id=org.edx.mobile',
}
SOCIAL_MEDIA_FOOTER_URLS = {
    'facebook': 'http://www.facebook.com/EdxOnline',
    'instagram': 'https://www.instagram.com/edxonline/',
    'linkedin': 'http://www.linkedin.com/company/edx',
    'meetup': 'http://www.meetup.com/edX-Global-Community',
    'reddit': 'http://www.reddit.com/r/edx',
    'tumblr': 'http://edxstories.tumblr.com/',
    'twitter': 'https://twitter.com/edXOnline',
    'youtube': 'https://www.youtube.com/user/edxonline',
}

# Django Admin Settings
VALIDATE_FORM_EXTERNAL_FIELDS = False

# Feature Toggles

# Install django-extensions for improved dev experiences
# https://github.com/django-extensions/django-extensions#using-it
INSTALLED_APPS += ('django_extensions',)

# Make some loggers less noisy (useful during test failure)
import logging

for logger_to_silence in ['faker', 'jwkest', 'edx_rest_framework_extensions']:
    logging.getLogger(logger_to_silence).setLevel(logging.WARNING)
