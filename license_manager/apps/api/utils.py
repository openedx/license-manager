""" Utility functions. """
from datetime import datetime

from django.shortcuts import get_object_or_404
from pytz import UTC

from license_manager.apps.subscriptions.models import SubscriptionPlan


def localized_utcnow():
    """Helper function to return localized utcnow()."""
    return UTC.localize(datetime.utcnow())  # pylint: disable=no-value-for-parameter


def get_subscription_plan_from_enterprise(request):
    """
    Helper function to return the active subscription from the `enterprise_customer_uuid` query param on a request.
    """
    enterprise_customer_uuid = request.query_params.get('enterprise_customer_uuid')
    return get_object_or_404(
        SubscriptionPlan,
        enterprise_customer_uuid=enterprise_customer_uuid,
        is_active=True,
    )
