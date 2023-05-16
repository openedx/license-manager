import platform
import sys
from os import environ

from django.core.exceptions import ImproperlyConfigured


def get_env_setting(setting):
    """ Get the environment setting or raise exception """
    try:
        return environ[setting]
    except KeyError:
        error_msg = "Set the [%s] env variable!" % setting
        raise ImproperlyConfigured(error_msg)


def get_logger_config(logging_env="no_env",
                      debug=False,
                      service_variant='license_manager'):
    """
    Return the appropriate logging config dictionary. You should assign the
    result of this to the LOGGING var in your settings.
    """
    hostname = platform.node().split(".")[0]
    syslog_format = (
        "[service_variant={service_variant}]"
        "[%(name)s][env:{logging_env}] %(levelname)s "
        "[{hostname}  %(process)d] [user %(userid)s] [ip %(remoteip)s] "
        "[request_id %(request_id)s] [%(filename)s:%(lineno)d] "
        "- %(message)s"
    ).format(
        service_variant=service_variant,
        logging_env=logging_env, hostname=hostname
    )

    handlers = ['console']

    logger_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s %(levelname)s %(process)d '
                          '[%(name)s] [user %(userid)s] [ip %(remoteip)s] '
                          '[request_id %(request_id)s] %(filename)s:%(lineno)d - %(message)s',
            },
            'syslog_format': {'format': syslog_format},
            'raw': {'format': '%(message)s'},
        },
        'filters': {
            'require_debug_false': {
                '()': 'django.utils.log.RequireDebugFalse',
            },
            'userid_context': {
                '()': 'edx_django_utils.logging.UserIdFilter',
            },
            'remoteip_context': {
                '()': 'edx_django_utils.logging.RemoteIpFilter',
            },
            'request_id': {
                '()': 'log_request_id.filters.RequestIDFilter'
            }
        },
        'handlers': {
            'console': {
                'level': 'DEBUG' if debug else 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'filters': ['userid_context', 'remoteip_context', 'request_id'],
                'stream': sys.stdout,
            },
        },
        'loggers': {
            'django': {
                'handlers': handlers,
                'propagate': True,
                'level': 'INFO'
            },
            'requests': {
                'handlers': handlers,
                'propagate': True,
                'level': 'WARNING'
            },
            'factory': {
                'handlers': handlers,
                'propagate': True,
                'level': 'WARNING'
            },
            'django.request': {
                'handlers': handlers,
                'propagate': True,
                'level': 'WARNING'
            },
            '': {
                'handlers': handlers,
                'level': 'DEBUG',
                'propagate': False
            },
        }
    }

    return logger_config
