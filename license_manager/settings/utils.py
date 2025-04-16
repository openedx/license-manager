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

def get_logger_config(
    logging_env: str = "no_env",
    debug: bool = False,
    service_variant: str = 'enterprise-access',
    format_string: str = None,
):
    """
    Return the appropriate logging config dictionary, to be assigned to the LOGGING var in settings.

    Arguments:
        logging_env (str): Environment name.
        debug (bool): Debug logging enabled.
        service_variant (str): Name of the service.
        format_string (str): Override format string for your logfiles.

    Returns:
        dict(string): Returns a dictionary of config values
    """

    hostname = platform.node().split(".")[0]
    syslog_format = (
        "[service_variant={service_variant}]"
        "[%(name)s][env:{logging_env}] %(levelname)s "
        "[{hostname}  %(process)d] [%(filename)s:%(lineno)d] "
        "- %(message)s"
    ).format(
        service_variant=service_variant,
        logging_env=logging_env, hostname=hostname
    )

    handlers = ['console']

    standard_format = format_string or (
        '%(asctime)s %(levelname)s %(process)d [%(name)s] '
        '[request_id %(request_id)s] '
        '%(filename)s:%(lineno)d - %(message)s'
    )

    logger_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': standard_format,
            },
            'syslog_format': {'format': syslog_format},
            'raw': {'format': '%(message)s'},
        },
        'filters': {
            'request_id': {
                '()': 'log_request_id.filters.RequestIDFilter'
            },
        },
        'handlers': {
            'console': {
                'level': 'DEBUG' if debug else 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'filters': ['request_id'],
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
