""" Utility functions. """
import uuid
from datetime import datetime

from django.shortcuts import get_object_or_404
from edx_rbac.utils import get_decoded_jwt
from pytz import UTC
from rest_framework.exceptions import ParseError

from license_manager.apps.subscriptions.models import License, SubscriptionPlan


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


def get_activation_key_from_request(request, email_from_jwt=None):
    """
    Helper function to get an ``activation_key``, in the form of a UUID4, from a
    request's query params.

    Params:
        ``request`` - A DRF Request object.
        ``email_from_jwt`` (optional, str) - An email that has already been found in the request's JWT.
    Returns: An activation_key UUID.
    """
    if not email_from_jwt:
        email_from_jwt = get_email_from_jwt(get_decoded_jwt(request))

    try:
        return uuid.UUID(request.query_params['activation_key'])
    except KeyError:
        raise ParseError('activation_key is a required parameter')
    except ValueError:
        raise ParseError('{} is not a valid activation key.'.format(request.query_params['activation_key']))


def get_user_id_from_jwt(decoded_jwt):
    """
    Helper function to get the ``user_id`` key out of a decoded JWT.
    """
    return decoded_jwt.get('user_id')


def get_email_from_jwt(decoded_jwt):
    """
    Helper function to get the ``email`` key out of a decoded JWT.
    """
    return decoded_jwt.get('email')


def get_subscription_plan_by_activation_key(request):
    """
    Helper function to return the active subscription plan associated
    with the license identified by the `activation_key` query param on a request
    and the ``email`` provided in the renquest's JWT.

    Params:
        ``request`` - A DRF Request object.
    Returns: A ``SubscriptionPlan`` object.
    """
    activation_key = get_activation_key_from_request(request)

    email_from_jwt = get_email_from_jwt(get_decoded_jwt(request))

    user_license = get_object_or_404(
        License,
        activation_key=activation_key,
        user_email=email_from_jwt,
        subscription_plan__is_active=True,
    )
    return user_license.subscription_plan
