""" Utility functions for the subscriptions app. """
from datetime import date, datetime

from django.conf import settings
from pytz import UTC

from license_manager.apps.subscriptions.constants import (
    DEFAULT_EMAIL_SENDER_ALIAS,
)


def localized_utcnow():
    """Helper function to return localized utcnow()."""
    return UTC.localize(datetime.utcnow())  # pylint: disable=no-value-for-parameter


def localized_datetime(*args, **kwargs):
    """
    Helper to return a UTC-localized datetime.
    """
    return UTC.localize(datetime(*args, **kwargs))


def days_until(end_date):
    """
    Helper to return the number of days until the end date.
    """
    diff = end_date - date.today()
    return diff.days


def chunks(a_list, chunk_size):
    """
    Helper to break a list up into chunks. Returns a list of lists
    """
    for i in range(0, len(a_list), chunk_size):
        yield a_list[i:i + chunk_size]


def get_learner_portal_url(enterprise_slug):
    """
    Returns the link to the learner portal, given an enterprise slug.
    Does not contain a trailing slash.
    """
    return '{}/{}'.format(settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL, enterprise_slug)


def get_license_activation_link(enterprise_slug, activation_key):
    """
    Returns the activation link displayed in the activation email sent to a learner
    """
    return '/'.join((
        get_learner_portal_url(enterprise_slug),
        'licenses',
        str(activation_key),
        'activate'
    ))


def get_enterprise_sender_alias(enterprise_customer):
    """
    Returns the configured sender alias for an enterprise, if configured; otherwise
    returns the default sender alias.
    """
    return enterprise_customer.get('sender_alias') or DEFAULT_EMAIL_SENDER_ALIAS


def get_enterprise_reply_to_email(enterprise_customer):
    """
    Returns the configured reply_to email for an enterprise, if configured.
    """
    return enterprise_customer.get('reply_to') or ''
