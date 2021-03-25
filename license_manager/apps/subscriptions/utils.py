""" Utility functions for the subscriptions app. """
from datetime import date, datetime

from django.conf import settings
from pytz import UTC


def localized_utcnow():
    """Helper function to return localized utcnow()."""
    return UTC.localize(datetime.utcnow())  # pylint: disable=no-value-for-parameter


def days_until(end_date):
    """
    Helper to return the number of days until the end date.
    """
    diff = end_date - date.today()
    return diff.days


def chunks(list, chunk_size):
    """
    Helper to break a list up into chunks. Returns a list of lists
    """
    for i in range(0, len(list), chunk_size):
        yield list[i:i + chunk_size]


def get_learner_portal_url(enterprise_slug):
    """
    Returns the link to the learner portal, given an enterprise slug.
    Does not contain a trailing slash.
    """
    return settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL + '/' + enterprise_slug


def get_license_activation_link(enterprise_slug, activation_key):
    """
    Returns the activation link displayed in the activation email sent to a learner
    """
    return '/'.join((
        get_learner_portal_url(enterprise_slug),
        'licenses',
        activation_key,
        'activate'
    ))
