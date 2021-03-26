""" Utility functions. """
import uuid

from django.shortcuts import get_object_or_404
from edx_rbac.utils import get_decoded_jwt
from rest_framework.exceptions import ParseError

from license_manager.apps.subscriptions.models import CustomerAgreement, License


def get_customer_agreement_from_request_enterprise_uuid(request):
    """
    Helper function to return the CustomerAgreement, if any, associated with the specified ``enterprise_customer_uuid``.
    """
    enterprise_customer_uuid = request.query_params.get('enterprise_customer_uuid')
    return get_object_or_404(
        CustomerAgreement,
        enterprise_customer_uuid=enterprise_customer_uuid,
    )


def get_context_for_customer_agreement_from_request(request):
    """
    Helper function to return the permission context (i.e., EnterpriseCustomer uuid) for the
    CustomerAgreement associated with the specified ``enterprise_customer_uuid`` query param.
    """
    customer_agreement = get_customer_agreement_from_request_enterprise_uuid(request)
    return customer_agreement.enterprise_customer_uuid


def get_activation_key_from_request(request):
    """
    Helper function to get an ``activation_key``, in the form of a UUID4, from a
    request's query params.

    Params:
        ``request`` - A DRF Request object.

    Returns: An activation_key UUID.
    """
    try:
        return uuid.UUID(request.query_params['activation_key'])
    except KeyError as exc:
        raise ParseError('activation_key is a required parameter') from exc
    except ValueError as exc:
        raise ParseError('{} is not a valid activation key.'.format(request.query_params['activation_key'])) from exc


def get_key_from_jwt(decoded_jwt, key):
    """
    Helper to get the provided ``key`` out of a decoded JWT or raise a validation error if not found in the JWT.
    """
    value = decoded_jwt.get(key)
    if not value:
        raise ParseError(f'`{key}` is required and could not be found in your jwt')

    return value


def get_email_from_request(request):
    """
    Helper to get the ``email`` value provided in a request's JWT.
    """
    decoded_jwt = get_decoded_jwt(request)
    return get_key_from_jwt(decoded_jwt, 'email')


def get_context_from_subscription_plan_by_activation_key(request):
    """
    Helper function to return the permission context (i.e., enterprise customer uuid) from active
    subscription plan associated with the license identified by the ``activation_key`` query param
    on a request and the ``email`` provided in the request's JWT.

    Params:
        ``request`` - A DRF Request object.

    Returns: The ``enterprise_customer_uuid`` associated with the user's license.
    """
    user_license = get_object_or_404(
        License,
        activation_key=get_activation_key_from_request(request),
        user_email=get_email_from_request(request),
        subscription_plan__is_active=True,
    )
    return user_license.subscription_plan.customer_agreement.enterprise_customer_uuid
