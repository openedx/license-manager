# pylint: disable=redefined-outer-name,missing-function-docstring
"""
Tests for the Subscription and License V1 API view sets.
"""
import datetime
import random
import string
from math import ceil, sqrt
from unittest import mock
from uuid import uuid4

import ddt
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get as get_model_fixture
from edx_rest_framework_extensions.auth.jwt.cookies import jwt_cookie_name
from edx_rest_framework_extensions.auth.jwt.tests.utils import (
    generate_jwt_token,
    generate_unversioned_payload,
)
from rest_framework import status
from rest_framework.test import APIClient

from license_manager.apps.api.tests.factories import BulkEnrollmentJobFactory
from license_manager.apps.api.utils import (
    acquire_subscription_plan_lock,
    release_subscription_plan_lock,
)
from license_manager.apps.api.v1.tests.constants import (
    ADMIN_ROLES,
    LEARNER_ROLES,
    PROVISIONING_ADMINS_GROUP,
    SUBSCRIPTION_RENEWAL_DAYS_OFFSET,
)
from license_manager.apps.api.v1.views import (
    ESTIMATED_COUNT_PAGINATOR_THRESHOLD,
)
from license_manager.apps.core.models import User
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.exceptions import LicenseRevocationError
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionLicenseSource,
    SubscriptionsFeatureRole,
    SubscriptionsRoleAssignment,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    ProductFactory,
    SubscriptionLicenseSourceFactory,
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
    UserFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    assert_historical_pii_cleared,
    assert_license_fields_cleared,
    assert_pii_cleared,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


def generate_random_email():
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = ''.join(random.choices(string.ascii_lowercase, k=5))

    return f"{name}@{domain}.com"


def _jwt_payload_from_role_context_pairs(user, role_context_pairs):
    """
    Generates a new JWT payload with roles assigned from pairs of (role name, context).
    """
    roles = []
    for role, context in role_context_pairs:
        role_data = f'{role}'
        if context is not None:
            role_data += f':{context}'
        roles.append(role_data)

    payload = generate_unversioned_payload(user)
    payload.update({'user_id': user.id})
    payload.update({'roles': roles})

    return payload


def _set_encoded_jwt_in_cookies(client, payload):
    """
    JWT-encodes the given payload and sets it in the client's cookies.
    """
    client.cookies[jwt_cookie_name()] = generate_jwt_token(payload)


def init_jwt_cookie(client, user, role_context_pairs=None, jwt_payload_extra=None):
    """
    Initialize a JWT token in the given client's cookies.
    """
    jwt_payload = _jwt_payload_from_role_context_pairs(user, role_context_pairs or [])
    jwt_payload.update(jwt_payload_extra or {})
    _set_encoded_jwt_in_cookies(client, jwt_payload)


@pytest.fixture(params=[True, False])
def boolean_toggle(request):
    """
    Simple fixture that toggles between boolean states.
    Any test that uses this fixture will actually be two tests - one for each boolean value.
    """
    return request.param


@pytest.fixture
def api_client():
    """
    Fixture that provides a DRF test APIClient.
    """
    return APIClient()


@pytest.fixture
def non_staff_user():
    """
    Fixture that provides a plain 'ole authenticated User instance.
    Non-staff, non-admin.
    """
    return get_model_fixture(User)


@pytest.fixture
def licensed_non_staff_user():
    """
    Fixture that provides a plain 'ole authenticated User instance.
    Non-staff, non-admin.
    """
    return get_model_fixture(User)


@pytest.fixture
def staff_user():
    """
    Fixture that provides a User instance for whom staff=True.
    """
    return get_model_fixture(User, is_staff=True, is_superuser=False)


@pytest.fixture
def superuser():
    """
    Fixture that provides a superuser.
    """
    return get_model_fixture(User, is_staff=True, is_superuser=True)


@pytest.fixture(params=[ADMIN_ROLES, LEARNER_ROLES])
def user_role(request):
    """
    Simple fixture that toggles between various user roles.
    """
    return request.param


def _customer_agreement_detail_request(api_client, user, customer_agreement_uuid, viewname='customer-agreement-detail'):
    """
    Helper method that requests details for a specific customer agreement.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = reverse(f'api:v1:{viewname}', kwargs={
        'customer_agreement_uuid': customer_agreement_uuid,
    })

    return api_client.get(url)


def _customer_agreement_list_request(api_client, user, enterprise_customer_uuid):
    """
    Helper method that requests CustomerAgreement details for a specific enterprise customer uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:customer-agreement-list')
    if enterprise_customer_uuid is not None:
        url += f'?enterprise_customer_uuid={enterprise_customer_uuid}'

    return api_client.get(url)


def _customer_agreement_create_request(api_client, user, enterprise_customer_uuid):
    """
    Helper method that requests to create a new CustomerAgreement for a specific enterprise customer uuid.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = reverse('api:v1:provisioning-admins-customer-agreement-list')
    data = {
        'enterprise_customer_uuid': str(enterprise_customer_uuid),
        'default_enterprise_catalog_uuid': str(uuid4()),
        'disable_expiration_notifications': False,
        'disable_onboarding_notifications': True,
    }

    return api_client.post(url, data=data)


def _customer_agreement_partial_update_request(api_client, user, customer_agreement_uuid):
    """
    Helper method that requests to partially update a CustomerAgreement.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = reverse('api:v1:provisioning-admins-customer-agreement-detail', kwargs={
        'customer_agreement_uuid': customer_agreement_uuid,
    })

    data = {
        'disable_onboarding_notifications': False,
    }

    return api_client.patch(url, data=data)


def _subscriptions_list_request(api_client, user, enterprise_customer_uuid=None, current_plan=None):
    """
    Helper method that requests a list of subscriptions entities for a given enterprise_customer_uuid.
    """
    if user:
        api_client.force_authenticate(user=user)

    query_string = ''
    url = reverse('api:v1:subscriptions-list')
    if enterprise_customer_uuid is not None:
        query_string += f'?enterprise_customer_uuid={enterprise_customer_uuid}'

    # Add current=true query parameter if current_plan is provided
    if current_plan is not None:
        query_string += '&' if '?' in query_string else '?'
        query_string += 'current=true'

    url += query_string
    return api_client.get(url)


def _provision_license_create_request(api_client, user, params):
    """
    Helper method that creates a SubscriptionPlan.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = '/api/v1/provisioning-admins/subscriptions'
    return api_client.post(url, params)


def _provision_license_list_request(api_client, user, enterprise_customer_uuid=None):
    """
    Helper method that creates a SubscriptionPlan.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = '/api/v1/provisioning-admins/subscriptions'
    if enterprise_customer_uuid:
        url += f'?enterprise_customer_uuid={enterprise_customer_uuid}'
    return api_client.get(url)


def _subscription_get_request(api_client, user, subscription_uuid):
    """
    Helper method that creates a SubscriptionPlan.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = f'/api/v1/provisioning-admins/subscriptions/{subscription_uuid}'
    return api_client.get(url)


def _provision_license_patch_request(api_client, user, params, subscription_uuid):
    """
    Helper method that updates a SubscriptionPlan.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = f'/api/v1/provisioning-admins/subscriptions/{subscription_uuid}'
    return api_client.patch(url, params)


def _learner_subscriptions_list_request(api_client, enterprise_customer_uuid=None):
    """
    Helper method that requests a list of active subscriptions entities for a given enterprise_customer_uuid.
    """
    url = reverse('api:v1:learner-subscriptions-list')
    if enterprise_customer_uuid is not None:
        url += f'?enterprise_customer_uuid={enterprise_customer_uuid}'
    return api_client.get(url)


def _subscriptions_detail_request(api_client, user, subscription_uuid):
    """
    Helper method that requests details for a specific subscription_uuid.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = reverse('api:v1:subscriptions-detail', kwargs={'subscription_uuid': subscription_uuid})

    return api_client.get(url)


def _licenses_list_request(
        api_client, subscription_uuid, page_size=None, active_only=None,
        search=None, ignore_null_emails=None, status=None
):
    """
    Helper method that requests a list of licenses for a given subscription_uuid.
    """
    url = reverse('api:v1:licenses-list', kwargs={'subscription_uuid': subscription_uuid})

    query_params = QueryDict(mutable=True)
    if page_size:
        query_params['page_size'] = page_size
    if active_only:
        query_params['active_only'] = active_only
    if search:
        query_params['search'] = search
    if ignore_null_emails:
        query_params['ignore_null_emails'] = ignore_null_emails
    if status:
        query_params['status'] = status

    url = f'{url}?{query_params.urlencode()}'
    return api_client.get(url)


def _licenses_detail_request(api_client, user, subscription_uuid, license_uuid):
    """
    Helper method that requests details for a specific license_uuid.
    """
    if user:
        api_client.force_authenticate(user=user)

    url = reverse('api:v1:licenses-detail', kwargs={
        'subscription_uuid': subscription_uuid,
        'license_uuid': license_uuid
    })

    return api_client.get(url)


def _learner_license_detail_request(api_client, subscription_uuid):
    """
    Helper method that requests a list of active subscriptions entities for a given enterprise_customer_uuid.
    """
    url = reverse('api:v1:license-list', kwargs={
        'subscription_uuid': subscription_uuid,
    })
    return api_client.get(url)


def _iso_8601_format(datetime):
    """
    Helper to return an ISO8601-formatted datetime string, with a trailing 'Z'.
    """
    if not datetime:
        return None
    return datetime.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _prepare_subscription_plan_payload(customer_agreement):
    return {
        "title": "foo",
        "start_date": "2024-04-29T15:17:53.462Z",
        "expiration_date": "2024-05-10T15:17:53.462Z",
        "enterprise_catalog_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "is_active": True,
        "is_revocation_cap_enabled": False,
        "should_auto_apply_licenses": True,
        "can_freeze_unused_licenses": True,
        "customer_agreement": customer_agreement.uuid,
        "desired_num_licenses": 3,
        "expiration_processed": True,
        "for_internal_use_only": True,
        "last_freeze_timestamp": "2024-04-29T15:17:53.462Z",
        "num_revocations_applied": 10,
        "product": 1,
        "revoke_max_percentage": 5,
        "salesforce_opportunity_line_item": "00k2222asdfasdfasd",
        "change_reason": "new"
    }


def _assert_customer_agreement_response_correct(response, customer_agreement):
    """
    Helper for asserting that the response for a customer agreement matches the object's values.
    """
    assert response['uuid'] == str(customer_agreement.uuid)
    assert response['enterprise_customer_uuid'] == str(customer_agreement.enterprise_customer_uuid)
    assert response['enterprise_customer_slug'] == customer_agreement.enterprise_customer_slug
    assert response['default_enterprise_catalog_uuid'] == str(customer_agreement.default_enterprise_catalog_uuid)
    assert response['net_days_until_expiration'] == customer_agreement.net_days_until_expiration
    for response_subscription, agreement_subscription in zip(
        response['subscriptions'],
        customer_agreement.subscriptions.all()
    ):
        _assert_subscription_response_correct(response_subscription, agreement_subscription)


def _assert_subscription_response_correct(response, subscription, expected_days_until_renewal_expiration=None):
    """
    Helper for asserting that the response for a subscription matches the object's values.
    """
    assert response['enterprise_customer_uuid'] == subscription.enterprise_customer_uuid
    assert response['uuid'] == str(subscription.uuid)
    assert response['start_date'] == _iso_8601_format(subscription.start_date)
    assert response['expiration_date'] == _iso_8601_format(subscription.expiration_date)
    assert response['enterprise_catalog_uuid'] == str(subscription.enterprise_catalog_uuid)
    assert response['is_active'] == subscription.is_active
    assert response['licenses'] == {
        'total': subscription.num_licenses,
        'allocated': subscription.num_allocated_licenses,
        'assigned': subscription.assigned_licenses.count(),
        'activated': subscription.activated_licenses.count(),
        'revoked': subscription.revoked_licenses.count(),
        'unassigned': subscription.unassigned_licenses.count(),
    }
    days_until_expiration = (subscription.expiration_date - localized_utcnow()).days
    assert response['days_until_expiration'] == days_until_expiration

    # If `expected_days_until_renewal_expiration` is None, there is no renewal
    assert response['days_until_expiration_including_renewals'] == (
        expected_days_until_renewal_expiration or days_until_expiration)
    assert response['prior_renewals'] == subscription.prior_renewals
    assert response['is_locked_for_renewal_processing'] == subscription.is_locked_for_renewal_processing


def _assert_license_response_correct(response, subscription_license):
    """
    Helper for asserting that the response for a subscription_license matches the object's values.
    """
    expected_fields = {
        'uuid',
        'status',
        'user_email',
        'last_remind_date',
        'subscription_plan_uuid',
        'revoked_date',
        'activation_key',
        'activation_date',
    }
    assert set(response.keys()) == expected_fields
    assert response['uuid'] == str(subscription_license.uuid)
    assert response['subscription_plan_uuid'] == str(subscription_license.subscription_plan.uuid)
    assert response['status'] == subscription_license.status
    assert response['user_email'] == subscription_license.user_email
    assert response['activation_key'] == str(subscription_license.activation_key)
    assert response['activation_date'] == _iso_8601_format(subscription_license.activation_date)
    assert response['last_remind_date'] == _iso_8601_format(subscription_license.last_remind_date)


@pytest.mark.django_db
def test_customer_agreement_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the customer agreement detail endpoint.
    """
    response = _customer_agreement_detail_request(
        api_client=api_client,
        user=None,
        customer_agreement_uuid=uuid4(),
    )
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_customer_agreement_create_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the customer agreement create endpoint.
    """
    response = _customer_agreement_create_request(
        api_client=api_client,
        user=None,
        enterprise_customer_uuid=uuid4(),
    )
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_customer_agreement_partial_update_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the customer agreement partial update endpoint.
    """
    response = _customer_agreement_partial_update_request(
        api_client=api_client,
        user=None,
        customer_agreement_uuid=uuid4(),
    )
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_customer_agreement_create_staff_user_403(api_client, staff_user):
    """
    Verify that staff users which are not in provision-admin-group receive a 403.
    """
    response = _customer_agreement_create_request(
        api_client=api_client,
        user=staff_user,
        enterprise_customer_uuid=uuid4(),
    )
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_customer_agreement_non_staff_user_403(api_client, non_staff_user):
    """
    Verify that non-staff users without JWT roles receive a 403 from the customer agreement detail endpoint.
    """
    response = _customer_agreement_detail_request(api_client, non_staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_customer_agreement_partial_update_staff_user_403(api_client, staff_user):
    """
    Verify that staff users which are not in provision-admin-group receive a 403.
    """
    response = _customer_agreement_partial_update_request(api_client, staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_customer_agreement_detail_non_staff_user_200(api_client, non_staff_user, user_role, boolean_toggle):
    """
    Verify that non-staff users with JWT roles (admin + learners) receive a 200 from the
    customer agreement detail endpoint.
    """
    enterprise_customer_uuid = uuid4()
    _, _, customer_agreement = _create_subscription_plans(enterprise_customer_uuid)

    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        enterprise_customer_uuid,
        assign_via_jwt=boolean_toggle,
        system_role=user_role['system_role'],
        subscriptions_role=user_role['subscriptions_role'],
    )

    response = _customer_agreement_detail_request(api_client, non_staff_user, customer_agreement.uuid)
    assert status.HTTP_200_OK == response.status_code


@pytest.mark.django_db
def test_customer_agreement_detail_provisioning_admin_user_200(api_client, staff_user):
    """
    Verify that provisioning admins can access the customer agreement detail endpoint.
    """
    enterprise_customer_uuid = uuid4()
    _, _, customer_agreement = _create_subscription_plans(enterprise_customer_uuid)

    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, assign_via_jwt=True)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)

    response = _customer_agreement_detail_request(
        api_client,
        staff_user,
        customer_agreement.uuid,
        viewname='provisioning-admins-customer-agreement-detail',
    )
    assert status.HTTP_200_OK == response.status_code


@pytest.mark.django_db
def test_customer_agreement_detail_staff_user_403(api_client, staff_user):
    """
    Verify that staff users without any assigned roles receive a 403 from the customer agreement detail endpoint.
    """
    response = _customer_agreement_detail_request(api_client, staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_customer_agreement_detail_superuser_200(api_client, superuser):
    """
    Verify that the customer agreement detail endpoint gives the correct
    response for superusers.
    """
    enterprise_customer_uuid = uuid4()
    _, _, customer_agreement = _create_subscription_plans(enterprise_customer_uuid)
    response = _customer_agreement_detail_request(api_client, superuser, customer_agreement.uuid)

    assert status.HTTP_200_OK == response.status_code
    _assert_customer_agreement_response_correct(response.data, customer_agreement)


@pytest.mark.django_db
def test_customer_agreement_list_superuser_200(api_client, superuser):
    """
    Verify that the customer agreement list endpoint gives the correct
    response for superusers.
    """
    enterprise_customer_uuid = uuid4()
    _, _, customer_agreement = _create_subscription_plans(enterprise_customer_uuid)
    response = _customer_agreement_list_request(api_client, superuser, customer_agreement.enterprise_customer_uuid)

    assert status.HTTP_200_OK == response.status_code
    assert 1 == response.data['count']
    _assert_customer_agreement_response_correct(response.data['results'][0], customer_agreement)


@pytest.mark.django_db
def test_customer_agreement_create_provisioning_admin_201(api_client, staff_user):
    """
    Verify that provisioning admins can create a new customer agreement.
    """
    enterprise_customer_uuid = uuid4()

    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, assign_via_jwt=True)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)

    response = _customer_agreement_create_request(api_client, staff_user, enterprise_customer_uuid)
    customer_agreement = CustomerAgreementFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)

    assert status.HTTP_201_CREATED == response.status_code
    _assert_customer_agreement_response_correct(response.data, customer_agreement)
    assert CustomerAgreement.objects.filter(uuid=response.data['uuid']).exists()


@pytest.mark.django_db
def test_customer_agreement_partial_update_provisioning_admin_200(api_client, staff_user):
    """
    Verify that provisioning admins can partially update a customer agreement.
    """
    enterprise_customer_uuid = uuid4()

    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, assign_via_jwt=True)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)

    customer_agreement = CustomerAgreementFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    response = _customer_agreement_partial_update_request(api_client, staff_user, customer_agreement.uuid)

    assert status.HTTP_200_OK == response.status_code
    _assert_customer_agreement_response_correct(response.data, customer_agreement)


@pytest.mark.django_db
def test_customer_agreement_list_non_staff_user_200(api_client, non_staff_user, user_role, boolean_toggle):
    """
    Verify that non-staff users with JWT roles (admin + learners) receive a 200 from the
    customer agreement list endpoint.
    """
    enterprise_customer_uuid = uuid4()
    _, _, customer_agreement = _create_subscription_plans(enterprise_customer_uuid)

    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        enterprise_customer_uuid,
        assign_via_jwt=boolean_toggle,
        system_role=user_role['system_role'],
        subscriptions_role=user_role['subscriptions_role'],
    )

    response = _customer_agreement_list_request(api_client, non_staff_user, customer_agreement.enterprise_customer_uuid)
    assert status.HTTP_200_OK == response.status_code


@pytest.mark.django_db
def test_customer_agreement_list_non_staff_user_200_empty(api_client, non_staff_user, user_role, boolean_toggle):
    """
    Verify that non-staff users with JWT roles (admin + learners) receive a 200 from the
    customer agreement list endpoint, but only returns the CustomerAgreement for which the user
    has access to based on the user's role(s).
    """
    enterprise_customer_uuid = uuid4()
    other_enterprise_customer_uuid = uuid4()
    _, _, customer_agreement = _create_subscription_plans(enterprise_customer_uuid)

    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        other_enterprise_customer_uuid,
        assign_via_jwt=boolean_toggle,
        system_role=user_role['system_role'],
        subscriptions_role=user_role['subscriptions_role'],
    )

    response = _customer_agreement_list_request(api_client, non_staff_user, customer_agreement.enterprise_customer_uuid)
    assert status.HTTP_200_OK == response.status_code
    # verify response results includes no results as user doesn't have access to the requested enterprise context
    assert response.data.get('count') == 0
    assert response.data.get('results') == []


@pytest.mark.django_db
def test_subscription_plan_list_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the subscription plan list endpoint.
    """
    response = _subscriptions_list_request(
        api_client,
        user=None,
        enterprise_customer_uuid=uuid4(),
    )
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_subscription_plan_retrieve_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the subscription plan retrieve endpoint.
    """
    response = _subscriptions_detail_request(
        api_client=api_client,
        user=None,
        subscription_uuid=uuid4(),
    )
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_license_list_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the license list endpoint.
    """
    response = _licenses_list_request(api_client, uuid4())
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_license_retrieve_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the license retrieve endpoint.
    """
    response = _licenses_detail_request(
        api_client=api_client,
        user=None,
        subscription_uuid=uuid4(),
        license_uuid=uuid4(),
    )
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_non_staff_user_403(api_client, non_staff_user):
    response = _subscriptions_list_request(api_client, non_staff_user, enterprise_customer_uuid='foo')
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_detail_non_staff_user_403(api_client, non_staff_user):
    response = _subscriptions_detail_request(api_client, non_staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_licenses_list_non_staff_user_403(api_client, non_staff_user):
    # init a JWT cookie (so the user is authenticated) but don't provide any roles
    init_jwt_cookie(api_client, non_staff_user)
    response = _licenses_list_request(api_client, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_detail_non_staff_user_403(api_client, non_staff_user):
    response = _licenses_detail_request(api_client, non_staff_user, uuid4(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription list view for staff users gives the correct response
    when the staff user is granted implicit permission to access the enterprise customer.

    Additionally checks that the staff user only sees the subscription plans associated with the enterprise customer as
    specified by the query parameter.
    """
    enterprise_customer_uuid = uuid4()
    first_subscription, second_subscription, __ = _create_subscription_plans(enterprise_customer_uuid)
    third_subscription = _create_subscription_with_renewal(enterprise_customer_uuid)
    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_list_request(api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 3

    _assert_subscription_response_correct(results_by_uuid[str(first_subscription.uuid)], first_subscription)
    _assert_subscription_response_correct(results_by_uuid[str(second_subscription.uuid)], second_subscription)
    _assert_subscription_response_correct(
        results_by_uuid[str(third_subscription.uuid)],
        third_subscription,
        expected_days_until_renewal_expiration=SUBSCRIPTION_RENEWAL_DAYS_OFFSET,
    )


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_200_with_current_param(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription list view for staff users gives the correct response with current query_param
    when the staff user is granted implicit permission to access the enterprise customer.

    Additionally checks that the staff user only sees the latest subscription plan associated with the enterprise
    customer as specified by the query parameter.
    """
    enterprise_customer_uuid = uuid4()
    _, second_subscription, __ = _create_subscription_plans(enterprise_customer_uuid)
    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_list_request(api_client,
                                           staff_user,
                                           enterprise_customer_uuid=enterprise_customer_uuid,
                                           current_plan=True
                                           )

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 1
    assert response.data['results'][0]['uuid'] == str(second_subscription.uuid)
    _assert_subscription_response_correct(
        results_by_uuid[str(second_subscription.uuid)],
        second_subscription
    )


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_400_with_current_param_and_without_enterprise_param(
    api_client,
    staff_user,
    boolean_toggle
):
    """
    Verify that the subscription list view for staff users gives the 400 response with current query_param if
    enterprise_uuid is not available.
    """
    enterprise_customer_uuid = uuid4()
    _create_subscription_plans(enterprise_customer_uuid)
    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_list_request(api_client,
                                           staff_user,
                                           current_plan=True
                                           )

    assert status.HTTP_400_BAD_REQUEST == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_no_query_param(api_client, staff_user):
    """
    Verify that the subscription list view for staff gives no results if there is no query param.
    """
    SubscriptionPlanFactory.create()
    response = _subscriptions_list_request(api_client, staff_user)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 0


@pytest.mark.django_db
def test_subscription_plan_list_superuser_200(api_client, superuser):
    """
    Verify that the subscription list view for superusers returns all subscription plans.
    """
    SubscriptionPlanFactory.create_batch(10)
    response = _subscriptions_list_request(api_client, superuser)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 10


@pytest.mark.django_db
def test_subscription_plan_list_bad_enterprise_uuid_400(api_client, superuser):
    """
    Verify that the subscription list view returns a 400 error for malformed enterprise customer uuids.
    """
    response = _subscriptions_list_request(api_client, superuser, enterprise_customer_uuid='bad')
    assert status.HTTP_400_BAD_REQUEST == response.status_code
    assert 'bad is not a valid uuid' in str(response.content)


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription POST endpoint creates new record and response includes all expected fields
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)
    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    response = _provision_license_create_request(
        api_client, staff_user, params=params)

    assert status.HTTP_201_CREATED == response.status_code
    expected_fields = {
        "can_freeze_unused_licenses",
        "change_reason",
        "customer_agreement",
        "days_until_expiration_including_renewals",
        "days_until_expiration",
        "desired_num_licenses",
        "enterprise_catalog_uuid",
        "enterprise_customer_uuid",
        "expiration_date",
        "expiration_processed",
        "for_internal_use_only",
        "is_active",
        "is_locked_for_renewal_processing",
        "is_revocation_cap_enabled",
        "last_freeze_timestamp",
        "num_revocations_applied",
        "product",
        "revoke_max_percentage",
        "salesforce_opportunity_line_item",
        "should_auto_apply_licenses",
        "start_date",
        "title",
        "uuid",
        "is_current",
    }
    assert response.json().keys() == expected_fields


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_403(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription POST endpoint is accessible to authorised users only
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)
    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)

    response = _provision_license_create_request(
        api_client, staff_user, params=params)
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_403(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription POST endpoint is accessible to authorised users only
    """
    enterprise_customer_uuid = uuid4()
    ProductFactory.create_batch(1)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)

    response = _provision_license_list_request(
        api_client, staff_user)
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_provisioning_admins_list_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription POST endpoint is accessible to authorised users only
    and returns valid data
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)

    params = _prepare_subscription_plan_payload(customer_agreement)

    _provision_license_create_request(
        api_client, staff_user, params=params)

    response = _provision_license_list_request(
        api_client, staff_user)

    expected_keys = {'count', 'next', 'previous', 'results'}
    assert expected_keys.issubset(response.json().keys())
    expected_result_keys = {
        'title', 'uuid', 'start_date', 'expiration_date',
        'enterprise_customer_uuid', 'enterprise_catalog_uuid',
        'is_active', 'is_revocation_cap_enabled', 'days_until_expiration',
        'days_until_expiration_including_renewals',
        'is_locked_for_renewal_processing', 'should_auto_apply_licenses',
        'licenses', 'revocations', 'prior_renewals'
    }
    for result in response.json()['results']:
        assert expected_result_keys.issubset(result.keys())
    assert status.HTTP_200_OK == response.status_code


@pytest.mark.django_db
def test_subscription_plan_pa_list_staff_user_customer_uuid_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription POST endpoint applies enterprise_customer_uuid if passed
    in query params
    """
    # first create a subscription plan against a enterprise customer
    # then query it and test that customer uuid that's passed in query params
    # and the one received from `list` response are same.
    # We'll have to create two subscription plans to confirm it.

    enterprise_customer_uuid_one = uuid4()
    enterprise_customer_uuid_two = uuid4()
    customer_agreement_one = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid_one)
    customer_agreement_two = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid_two)
    ProductFactory.create_batch(1)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid_one, assign_via_jwt=boolean_toggle)

    params_one = _prepare_subscription_plan_payload(customer_agreement_one)
    params_two = _prepare_subscription_plan_payload(customer_agreement_two)

    _provision_license_create_request(
        api_client, staff_user, params=params_one)

    response_one = _provision_license_list_request(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid_one)
    assert status.HTTP_200_OK == response_one.status_code
    assert response_one.json()['results'][0]['enterprise_customer_uuid'] == str(
        enterprise_customer_uuid_one)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid_two, assign_via_jwt=boolean_toggle)

    _provision_license_create_request(
        api_client, staff_user, params=params_two)
    response_two = _provision_license_list_request(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid_two)

    assert status.HTTP_200_OK == response_two.status_code
    assert response_two.json()['results'][0]['enterprise_customer_uuid'] == str(
        enterprise_customer_uuid_two)


@pytest.mark.django_db
def test_subscription_plan_update_staff_user_403(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription update endpoint is accessible to authorised users only
    """
    enterprise_customer_uuid = uuid4()
    fake_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)
    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)

    response = _provision_license_patch_request(
        api_client, staff_user, params=params, subscription_uuid=fake_uuid)

    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_201(api_client, staff_user, boolean_toggle):
    """
    Verify that the subcription update endpoint is accessible to authorised users only
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)
    params = _prepare_subscription_plan_payload(customer_agreement)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)

    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    response = _provision_license_create_request(
        api_client, staff_user, params=params)
    assert status.HTTP_201_CREATED == response.status_code


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_customer_agreement_400(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid customer_agreement is given
    """
    enterprise_customer_uuid = uuid4()
    invalid_customer_agreement_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    params['customer_agreement'] = invalid_customer_agreement_uuid
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    response = _provision_license_create_request(
        api_client, staff_user, params=params)
    assert status.HTTP_400_BAD_REQUEST == response.status_code
    assert response.json() == {'error': "An error occurred: Provided customer_agreement doesn't exist."}


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_product_400(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid Product is given
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    params['product'] = 2  # passing an invalid PK
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    response = _provision_license_create_request(
        api_client, staff_user, params=params)

    assert status.HTTP_400_BAD_REQUEST == response.status_code
    assert response.json() == {'error': {'product': [
        'Invalid pk "2" - object does not exist.']}}


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_salesforce_lineitem_400(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid salesforce_lineitem is given
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    # passing a invalid string
    params['salesforce_opportunity_line_item'] = 'foo'
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    response = _provision_license_create_request(
        api_client, staff_user, params=params)

    assert status.HTTP_400_BAD_REQUEST == response.status_code
    assert response.json() == \
        {'error': "An error occurred: You must specify Salesforce ID for selected product. It must start with '00k'."}


@pytest.mark.django_db
def test_subscription_plan_update_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns 200 on patch request
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    create_response = _provision_license_create_request(
        api_client, staff_user, params=params)
    params['title'] = 'bar'
    patch_response = _provision_license_patch_request(
        api_client, staff_user, params=params, subscription_uuid=create_response.json()['uuid'])
    assert status.HTTP_201_CREATED == create_response.status_code
    assert status.HTTP_200_OK == patch_response.status_code
    expected_fields = {
        "can_freeze_unused_licenses",
        "change_reason",
        "customer_agreement",
        "days_until_expiration_including_renewals",
        "days_until_expiration",
        "desired_num_licenses",
        "enterprise_catalog_uuid",
        "enterprise_customer_uuid",
        "expiration_date",
        "expiration_processed",
        "for_internal_use_only",
        "is_active",
        "is_locked_for_renewal_processing",
        "is_revocation_cap_enabled",
        "last_freeze_timestamp",
        "num_revocations_applied",
        "product",
        "revoke_max_percentage",
        "salesforce_opportunity_line_item",
        "should_auto_apply_licenses",
        "start_date",
        "title",
        "uuid",
    }
    assert patch_response.json()['title'] == params['title']
    assert patch_response.json().keys() == expected_fields


@pytest.mark.django_db
def test_subscription_plan_update_staff_user_invalid_product_id(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns 200 on patch request
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    create_response = _provision_license_create_request(
        api_client, staff_user, params=params)
    params['product'] = 10  # set invalid ID
    patch_response = _provision_license_patch_request(
        api_client, staff_user, params=params, subscription_uuid=create_response.json()['uuid'])
    assert status.HTTP_201_CREATED == create_response.status_code
    assert status.HTTP_400_BAD_REQUEST == patch_response.status_code


@pytest.mark.django_db
def test_subscription_plan_update_staff_user_invalid_payload(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns 200 on patch request
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    create_response = _provision_license_create_request(
        api_client, staff_user, params=params)
    params['salesforce_opportunity_line_item'] = 'foo'  # set invalid ID

    patch_response = _provision_license_patch_request(
        api_client, staff_user, params=params, subscription_uuid=create_response.json()['uuid'])
    assert status.HTTP_201_CREATED == create_response.status_code
    assert status.HTTP_400_BAD_REQUEST == patch_response.status_code


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_cataog_uuid_missing(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint handles request gracefully if enterprise_catalog_uuid is missing
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    params['enterprise_catalog_uuid'] = None
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    create_response = _provision_license_create_request(
        api_client, staff_user, params=params)

    assert status.HTTP_201_CREATED == create_response.status_code

    assert create_response.json()['enterprise_catalog_uuid'] == str(
        customer_agreement.default_enterprise_catalog_uuid)


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_invalid_product_id(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid product id is provided
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    params['product'] = 12
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    create_response = _provision_license_create_request(
        api_client, staff_user, params=params)

    assert status.HTTP_400_BAD_REQUEST == create_response.status_code
    assert create_response.json(
    ) == {'error': {'product': ['Invalid pk "12" - object does not exist.']}}


@pytest.mark.django_db
def test_subscription_plan_create_staff_user_db_integrity_error(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid product id is provided
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    first_create_response = _provision_license_create_request(
        api_client, staff_user, params=params)

    second_create_response = _provision_license_create_request(
        api_client, staff_user, params=params)

    assert status.HTTP_201_CREATED == first_create_response.status_code
    assert status.HTTP_400_BAD_REQUEST == second_create_response.status_code
    assert second_create_response.json() == \
        {"error": {"non_field_errors": ["The fields title, customer_agreement must "
                                        "make a unique set."]}}


@pytest.mark.django_db
def test_subscription_plan_get_staff_user_success(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid product id is provided
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(
        enterprise_customer_uuid=enterprise_customer_uuid)
    ProductFactory.create_batch(1)

    params = _prepare_subscription_plan_payload(customer_agreement)
    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    create_response = _provision_license_create_request(
        api_client, staff_user, params)
    created_uuid = str(create_response.json()['uuid'])

    retrieved_subscription = _subscription_get_request(
        api_client, staff_user, created_uuid)

    assert retrieved_subscription.json()['uuid'] == created_uuid
    assert status.HTTP_201_CREATED == create_response.status_code


@pytest.mark.django_db
def test_subscription_plan_get_staff_user_failure(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription create endpoint returns error if invalid product id is provided
    """
    enterprise_customer_uuid = uuid4()
    invalid_subscription_id = uuid4()

    _assign_role_via_jwt_or_db(
        api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid, assign_via_jwt=boolean_toggle)
    allowed_group = Group.objects.create(name=PROVISIONING_ADMINS_GROUP)
    staff_user.groups.add(allowed_group)
    response = _subscription_get_request(
        api_client, staff_user, invalid_subscription_id)

    assert status.HTTP_404_NOT_FOUND == response.status_code


@pytest.mark.django_db
def test_non_staff_user_learner_subscriptions_endpoint(api_client, non_staff_user):
    """
    Verify that an enterprise learner can view the active subscriptions their enterprise has
    """
    enterprise_customer_uuid = uuid4()
    customer_agreement = CustomerAgreementFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    active_subscriptions = SubscriptionPlanFactory.create_batch(
        2,
        customer_agreement=customer_agreement,
        is_active=True
    )
    inactive_subscriptions = SubscriptionPlanFactory.create_batch(
        2,
        customer_agreement=customer_agreement,
        is_active=False
    )
    subscriptions = active_subscriptions + inactive_subscriptions

    # Associate some licenses with the subscription
    unassigned_licenses = LicenseFactory.create_batch(3)
    assigned_licenses = LicenseFactory.create_batch(5, status=constants.ASSIGNED)
    assigned_licenses[0].user_email = non_staff_user.email
    subscriptions[0].licenses.set(unassigned_licenses + assigned_licenses)

    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        enterprise_customer_uuid,
        assign_via_jwt=True
    )

    response = _learner_subscriptions_list_request(
        api_client,
        subscriptions[0].enterprise_customer_uuid
    )
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 2


@pytest.mark.django_db
def test_non_staff_user_learner_subscriptions_no_enterprise_customer_uuid(api_client, non_staff_user):
    """
    Verify that the learner-subscriptions endpoint returns no subscriptions
    when an enterprise_customer_uuid isn't specified
    """
    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        uuid4(),
        assign_via_jwt=True
    )
    response = _learner_subscriptions_list_request(api_client)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 0


@pytest.mark.django_db
def test_subscription_plan_detail_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription detail view for staff gives the correct result.
    """
    enterprise_customer_uuid = uuid4()
    subscription = _create_subscription_with_renewal(enterprise_customer_uuid)

    # Associate some licenses with the subscription
    unassigned_licenses = LicenseFactory.create_batch(3)
    assigned_licenses = LicenseFactory.create_batch(5, status=constants.ASSIGNED)
    subscription.licenses.set(unassigned_licenses + assigned_licenses)

    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        enterprise_customer_uuid,
        boolean_toggle,
    )

    response = _subscriptions_detail_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_subscription_response_correct(
        response.data,
        subscription,
        expected_days_until_renewal_expiration=SUBSCRIPTION_RENEWAL_DAYS_OFFSET,
    )


@pytest.mark.django_db
def test_license_list_staff_user_200(api_client, staff_user, boolean_toggle):
    (subscription,
     assigned_license,
     unassigned_license,
     activated_license,
     revoked_license) = _subscription_and_licenses()

    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        boolean_toggle,
    )

    response = _licenses_list_request(api_client, subscription.uuid)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 4
    _assert_license_response_correct(results_by_uuid[str(unassigned_license.uuid)], unassigned_license)
    _assert_license_response_correct(results_by_uuid[str(assigned_license.uuid)], assigned_license)
    _assert_license_response_correct(results_by_uuid[str(activated_license.uuid)], activated_license)
    _assert_license_response_correct(results_by_uuid[str(revoked_license.uuid)], revoked_license)


@pytest.mark.django_db
def test_license_list_active_licenses(api_client, staff_user, boolean_toggle):
    subscription, assigned_license, unassigned_license, activated_license, revoked_license \
        = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        boolean_toggle,
    )

    response = _licenses_list_request(api_client, subscription.uuid, active_only='1')

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}

    assert len(results_by_uuid) == 2
    _assert_license_response_correct(results_by_uuid[str(assigned_license.uuid)], assigned_license)
    _assert_license_response_correct(results_by_uuid[str(activated_license.uuid)], activated_license)
    assert not hasattr(results_by_uuid, str(unassigned_license.uuid))
    assert not hasattr(results_by_uuid, str(revoked_license.uuid))


@pytest.mark.django_db
def test_license_list_search_by_email(api_client, staff_user, boolean_toggle):
    subscription, _, unassigned_license, _, _ = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        boolean_toggle,
    )

    response = _licenses_list_request(api_client, subscription.uuid, search='unas')

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}

    assert len(results_by_uuid) == 1
    _assert_license_response_correct(results_by_uuid[str(unassigned_license.uuid)], unassigned_license)


@pytest.mark.django_db
def test_license_list_staff_user_200_custom_page_size(api_client, staff_user):
    subscription, _, _, _, _ = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        True,
    )

    response = _licenses_list_request(api_client, subscription.uuid, page_size=1)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    # We test for content in the test above, we're just worried about the number of pages here
    assert len(results_by_uuid) == 1
    assert response.data['count'] == 4
    assert response.data['next'] is not None


@pytest.mark.django_db
def test_license_list_staff_user_200_estimated_license_count(api_client, staff_user):
    subscription, _, _, _, _ = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        True,
    )
    subscription.desired_num_licenses = ESTIMATED_COUNT_PAGINATOR_THRESHOLD + 1
    subscription.save()

    response = _licenses_list_request(
        api_client, subscription.uuid, page_size=1,
        status=','.join([constants.UNASSIGNED, constants.ASSIGNED, constants.ACTIVATED]),
    )

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    # We test for content in the test above,
    # we're only worried about the response count matching `desired_num_licenses` here.
    assert len(results_by_uuid) == 1
    assert response.data['count'] == ESTIMATED_COUNT_PAGINATOR_THRESHOLD + 1
    assert response.data['next'] is not None


@pytest.mark.django_db
def test_license_list_ignore_null_emails_query_param(api_client, staff_user, boolean_toggle):
    """
    Assert the endpoint respects the ``ignore_null_emails`` query parameter.
    """
    subscription, assigned_license, unassigned_license, active_license, revoked_license = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        assign_via_jwt=True,
    )
    revoked_license.user_email = None
    revoked_license.save()

    response = _licenses_list_request(
        api_client,
        subscription.uuid,
        ignore_null_emails=boolean_toggle
    )
    expected_license_uuids = [
        str(assigned_license.uuid),
        str(unassigned_license.uuid),
        str(active_license.uuid)
    ] if boolean_toggle else [
        str(assigned_license.uuid),
        str(unassigned_license.uuid),
        str(active_license.uuid),
        str(revoked_license.uuid)
    ]
    actual_license_uuids = [user_license['uuid'] for user_license in response.json()['results']]
    assert sorted(actual_license_uuids) == sorted(expected_license_uuids)


@pytest.mark.django_db
def test_license_detail_staff_user_200(api_client, staff_user, boolean_toggle):
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    subscription_license = LicenseFactory.create()
    subscription.licenses.set([subscription_license])

    _assign_role_via_jwt_or_db(
        api_client,
        staff_user,
        subscription.enterprise_customer_uuid,
        boolean_toggle,
    )

    response = _licenses_detail_request(api_client, staff_user, subscription.uuid, subscription_license.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_license_response_correct(response.data, subscription_license)


@pytest.mark.django_db
def test_license_detail_non_staff_user_with_assigned_license_200(api_client, non_staff_user):
    """
    Verify that a learner is able to view their own license
    """
    subscription = SubscriptionPlanFactory.create()

    # Assign the non_staff user a license associated with the subscription
    subscription_license = LicenseFactory.create(status=constants.ASSIGNED, user_email=non_staff_user.email)
    subscription.licenses.set([subscription_license])
    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        subscription.enterprise_customer_uuid,
        assign_via_jwt=True
    )

    # Verify non_staff user can view their own license
    response = _learner_license_detail_request(api_client, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 1
    _assert_license_response_correct(results[0], subscription_license)


@pytest.mark.django_db
def test_license_detail_non_staff_user_with_no_assigned_license_200(api_client, non_staff_user):
    """
    Verify that a learner does not see any licenses when none are assigned to them
    """
    subscription = SubscriptionPlanFactory.create()
    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        subscription.enterprise_customer_uuid,
        assign_via_jwt=True
    )

    # Verify non_staff user can view their own license
    response = _learner_license_detail_request(api_client, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 0


@pytest.mark.django_db
def test_license_detail_non_staff_user_with_revoked_license_200(api_client, non_staff_user):
    """
    Verify that a learner can not view their revoked license
    """
    subscription = SubscriptionPlanFactory.create()
    # Assign the non_staff user a revoked license associated with the subscription
    subscription_license = LicenseFactory.create(status=constants.REVOKED, user_email=non_staff_user.email)
    subscription.licenses.set([subscription_license])
    _assign_role_via_jwt_or_db(
        api_client,
        non_staff_user,
        subscription.enterprise_customer_uuid,
        assign_via_jwt=True
    )

    # Verify non_staff user can view their own license
    response = _learner_license_detail_request(api_client, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 0


def _assign_role_via_jwt_or_db(
    client,
    user,
    enterprise_customer_uuid,
    assign_via_jwt,
    system_role=constants.SYSTEM_ENTERPRISE_ADMIN_ROLE,
    subscriptions_role=constants.SUBSCRIPTIONS_ADMIN_ROLE,
    jwt_payload_extra=None,
):
    """
    Helper method to assign the given role (defaulting to enterprise/subscriptions admin role)
    via a request JWT or DB role assignment class.
    """
    if assign_via_jwt:
        # In the request's JWT, grant the given role for this enterprise customer.
        init_jwt_cookie(
            client,
            user,
            [(system_role, str(enterprise_customer_uuid))] if system_role else [],
            jwt_payload_extra,
        )
    else:
        # We still provide a JWT cookie, with no roles, so the user is authenticated
        init_jwt_cookie(client, user)

        # Assign a feature role to the user via database record.
        SubscriptionsRoleAssignment.objects.create(
            enterprise_customer_uuid=enterprise_customer_uuid,
            user=user,
            role=SubscriptionsFeatureRole.objects.get(name=subscriptions_role),
        )


def _subscription_and_licenses():
    """
    Helper method to return a SubscriptionPlan, an unassigned license, active license, revoked license and an assigned
    license.
    """
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    unassigned_license = LicenseFactory.create(user_email='unassigned@edx.org')
    assigned_license = LicenseFactory.create(status=constants.ASSIGNED, user_email='assigned@fake.com')
    active_license = LicenseFactory.create(status=constants.ACTIVATED, user_email='activated@edx.org')
    revoked_license = LicenseFactory.create(status=constants.REVOKED)
    subscription.licenses.set([unassigned_license, assigned_license, active_license, revoked_license])

    return subscription, assigned_license, unassigned_license, active_license, revoked_license


def _create_subscription_plans(enterprise_customer_uuid):
    """
    Helper method to create several plans.  Returns the plans.
    """
    customer_agreement = CustomerAgreementFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    first_subscription = SubscriptionPlanFactory.create(customer_agreement=customer_agreement)
    # Associate some unassigned and assigned licenses to the first subscription
    unassigned_licenses = LicenseFactory.create_batch(5)
    assigned_licenses = LicenseFactory.create_batch(2, status=constants.ASSIGNED)
    first_subscription.licenses.set(unassigned_licenses + assigned_licenses)
    # Create one more subscription for the enterprise with no licenses
    second_subscription = SubscriptionPlanFactory.create(customer_agreement=customer_agreement)
    # Create another subscription not associated with the enterprise that shouldn't show up
    SubscriptionPlanFactory.create(customer_agreement=CustomerAgreementFactory())
    return first_subscription, second_subscription, customer_agreement


def _create_subscription_with_renewal(enterprise_customer_uuid):
    """
    Helper method to create a subscription with a renewal associated with it.
    """
    today = localized_utcnow()
    customer_agreement = CustomerAgreementFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    subscription = SubscriptionPlanFactory.create(customer_agreement=customer_agreement, expiration_date=today)
    SubscriptionPlanRenewalFactory.create(
        prior_subscription_plan=subscription,
        renewed_expiration_date=today + datetime.timedelta(days=SUBSCRIPTION_RENEWAL_DAYS_OFFSET + 1),
    )
    return subscription


class LicenseViewSetActionMixin:
    """
    Mixin of common functionality for LicenseViewSet action tests.
    """

    def setUp(self):
        super().setUp()

        # API client setup
        self.api_client = APIClient()
        self._setup_request_jwt()

        # Try to start every test with the regular user not being staff
        self.user.is_staff = False

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Set up a couple of users
        cls.user = UserFactory()
        cls.super_user = UserFactory(is_staff=True, is_superuser=True)
        cls.subscription_plan = SubscriptionPlanFactory()

        cls.test_email = 'test@example.com'
        cls.greeting = 'Hello'
        cls.closing = 'Goodbye'

    def _setup_request_jwt(self, user=None, enterprise_customer_uuid=None):
        """
        Helper method to assign role to the requesting user (via self.client) with a JWT.
        """
        _assign_role_via_jwt_or_db(
            self.api_client,
            user or self.user,
            enterprise_customer_uuid or self.subscription_plan.enterprise_customer_uuid,
            assign_via_jwt=True
        )

    def _create_available_licenses(self, num_licenses=5):
        """
        Helper that creates `num_licenses` licenses that can be assigned, associated with the subscription.
        """
        unassigned_licenses = LicenseFactory.create_batch(num_licenses)
        self.subscription_plan.licenses.set(unassigned_licenses)
        return unassigned_licenses

    def _assert_licenses_assigned(self, user_emails):
        """
        Helper that verifies that there is an assigned license associated with each email in `user_emails`.
        """
        for email in user_emails:
            assigned_licenses = self.subscription_plan.licenses.filter(user_email=email, status=constants.ASSIGNED)
            assert assigned_licenses.count() == 1

    def _test_and_assert_forbidden_user(self, url, user_is_staff, mock_task):
        """
        Helper to login an unauthorized user, request an action URL, and assert that 403 response is returned.
        """
        self.user.is_staff = user_is_staff
        completely_different_customer_uuid = uuid4()
        self._setup_request_jwt(enterprise_customer_uuid=completely_different_customer_uuid)
        response = self.api_client.post(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_task.assert_not_called()


@ddt.ddt
class CustomerAgreementViewSetTests(LicenseViewSetActionMixin, TestCase):
    """
    Tests for the CustomerAgreementViewSet.
    """

    def setUp(self):
        super().setUp()

        # API client setup
        self.api_client = APIClient()
        self._setup_request_jwt()

        # Try to start every test with the regular user not being staff
        self.user.is_staff = False

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Set up a couple of users
        cls.user = UserFactory()
        cls.super_user = UserFactory(is_staff=True, is_superuser=True)
        cls.subscription_plan = SubscriptionPlanFactory()

        cls.enterprise_catalog_uuid = uuid4()

        cls.customer_agreement = CustomerAgreementFactory(
            enterprise_customer_uuid=uuid4(),
        )
        cls.active_subscription_for_customer = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            enterprise_catalog_uuid=cls.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=False,
        )
        cls.inactive_subscription_for_customer = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            enterprise_catalog_uuid=cls.enterprise_catalog_uuid,
            is_active=False,
        )

        # Routes setup
        cls.auto_apply_url = reverse(
            'api:v1:customer-agreement-auto-apply',
            kwargs={'customer_agreement_uuid': cls.customer_agreement.uuid}
        )
        cls.list_url = reverse(
            'api:v1:customer-agreement-list'
        )

    @ddt.data(None, True, False)
    def test_active_plans_only_query_param(self, active_plans_only):
        """
        Tests that only active plans are serialized if the query param active_plans_only = True (default),
        else all plans should be serialized in the CustomerAgreement.
        """

        query_params = '' if active_plans_only is None else f'active_plans_only={active_plans_only}'
        url = self.list_url + f'?{query_params}'
        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data['results']
        result = [result for result in results if result['uuid'] == str(self.customer_agreement.uuid)][0]

        only_active_plans = all(plan['is_active'] for plan in result['subscriptions'])

        self.assertEqual(active_plans_only is None or active_plans_only, only_active_plans)

    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    def test_auto_apply_422_if_no_applicable_subscriptions(self, mock_send_assignment_email_task):
        """
        Endpoint should return 422 if no auto-applicable subscriptions are found.
        """
        SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=False,
        )

        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.post(self.auto_apply_url)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    def test_auto_apply_422_if_no_licenses_on_applicable_plan(self, mock_send_assignment_email_task):
        """
        Endpoint should return 422 if applicable subscriptions found, but not
        enough licenses.
        """
        SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=True,
        )

        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.post(self.auto_apply_url)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    def test_auto_apply_422_if_revoked_license_on_plan(self, mock_send_assignment_email_task):
        """
        Endpoint should return 422 if applicable subscriptions found, license
        with revoked status for user found.
        """
        user_email = self.super_user.email

        plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=True,
        )
        LicenseFactory.create(subscription_plan=plan)
        LicenseFactory.create(
            subscription_plan=plan,
            user_email=user_email,
            status=constants.REVOKED
        )

        assert License.objects.filter(user_email=user_email).count() == 1

        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.post(self.auto_apply_url)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert License.objects.filter(user_email=user_email).count() == 1

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    def test_auto_apply_200_if_active_or_assigned_license_on_plan(self, mock_send_assignment_email_task):
        """
        Endpoint should return 200 if the plan in question already has an
        activated or assigned license associated with the user.
        """
        user_email = self.super_user.email
        plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=True,
        )
        LicenseFactory.create(subscription_plan=plan)
        LicenseFactory.create(
            subscription_plan=plan,
            user_email=user_email,
            status=constants.ACTIVATED
        )

        assert License.objects.filter(user_email=user_email).count() == 1

        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.post(self.auto_apply_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['user_email'] == user_email
        assert response.json()['status'] == 'activated'
        assert License.objects.filter(user_email=user_email).count() == 1

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.send_utilization_threshold_reached_email_task.delay')
    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    def test_auto_apply_endpoint_idempotent(
            self, mock_send_assignment_email_task, mock_send_utilization_threshold_reached_email_task
    ):
        """
        Endpoint should only associate user with license on auto-applicable
        subscription once, even if you hit the end point a bunch of times.
        """
        user_email = self.super_user.email

        plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=True,
        )
        # Unassigned License
        for _ in range(10):
            LicenseFactory.create(subscription_plan=plan)

        assert License.objects.filter(user_email=user_email).count() == 0
        self._setup_request_jwt(user=self.super_user)
        for _ in range(7):
            self.api_client.post(self.auto_apply_url)
        assert License.objects.filter(user_email=user_email).count() == 1

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_called_once_with(
            (self.customer_agreement.enterprise_customer_uuid, user_email),
            {}
        )

        mock_send_utilization_threshold_reached_email_task.assert_called_once_with(
            plan.uuid
        )

    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    @mock.patch('license_manager.apps.api.v1.views.CustomerAgreementViewSet._auto_apply_new_license')
    def test_auto_apply_422_if_DB_error(self, mock_auto_apply_new_licenses, mock_send_assignment_email_task):
        """
        Endpoint should return 422 if database error occurs.
        """
        plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=True,
        )
        for _ in range(3):
            LicenseFactory.create(subscription_plan=plan)

        # Make sure no licenses have auto_applied True
        assert License.objects.filter(auto_applied=True).count() == 0

        self._setup_request_jwt(user=self.super_user)

        mock_auto_apply_new_licenses.side_effect = DatabaseError('fail')
        response = self.api_client.post(self.auto_apply_url)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Make sure no licenses still don't have auto_applied True
        assert License.objects.filter(auto_applied=True).count() == 0

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.send_utilization_threshold_reached_email_task.delay')
    @mock.patch('license_manager.apps.api.v1.views.send_auto_applied_license_email_task.apply_async')
    def test_auto_apply_200_if_successful(
        self,
        mock_send_assignment_email_task,
        mock_send_utilization_threshold_reached_email_task,
    ):
        """
        Endpoint should return 200 if applicable subscriptions found, and
        License successfully auto applied.
        """
        plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            should_auto_apply_licenses=True,
        )
        for _ in range(3):
            LicenseFactory.create(subscription_plan=plan)

        # Make sure no licenses have auto_applied True
        assert License.objects.filter(auto_applied=True).count() == 0

        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.post(self.auto_apply_url)
        assert response.status_code == status.HTTP_200_OK

        response_json = response.json()
        response_subscription_plan = response_json['subscription_plan']
        response_customer_agreement = response_json['customer_agreement']
        assert response_json['user_email'] == self.super_user.email
        assert response_json['status'] == 'activated'
        assert response_json['subscription_plan']['uuid'] == str(plan.uuid)
        assert response_subscription_plan['title'] == plan.title
        assert response_subscription_plan['enterprise_catalog_uuid'] == str(plan.enterprise_catalog_uuid)
        assert response_subscription_plan['is_active'] == plan.is_active
        assert response_customer_agreement['uuid'] == str(self.customer_agreement.uuid)
        expected_customer_agreement_customer_uuid = str(self.customer_agreement.enterprise_customer_uuid)
        assert response_customer_agreement['enterprise_customer_uuid'] == expected_customer_agreement_customer_uuid

        # Check if 1 License has become auto_applied
        assert plan.licenses.filter(auto_applied=True).count() == 1

        # Check whether tasks were run
        mock_send_assignment_email_task.assert_called_once_with(
            (self.customer_agreement.enterprise_customer_uuid, self.super_user.email),
            {}
        )

        mock_send_utilization_threshold_reached_email_task.assert_called_once_with(
            plan.uuid
        )


@ddt.ddt
class LicenseViewSetActionTests(LicenseViewSetActionMixin, TestCase):
    """
    Tests for special actions on the LicenseViewSet.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Routes setup
        cls.assign_url = reverse('api:v1:licenses-assign', kwargs={'subscription_uuid': cls.subscription_plan.uuid})
        cls.remind_url = reverse('api:v1:licenses-remind', kwargs={'subscription_uuid': cls.subscription_plan.uuid})
        cls.remind_all_url = reverse(
            'api:v1:licenses-remind-all',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )
        cls.license_overview_url = reverse(
            'api:v1:licenses-overview',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )
        cls.licenses_csv_url = reverse(
            'api:v1:licenses-csv',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )

    def setUp(self):
        super().setUp()
        self.mock_track_test_mocker = mock.patch('license_manager.apps.api.v1.views.track_license_changes_task')
        self.mock_track_test_mocker.start()

    def tearDown(self):
        super().tearDown()
        self.mock_track_test_mocker.stop()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_no_emails(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint returns a 400 if no user emails are provided.
        """
        response = self.api_client.post(self.assign_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_assignment_email_task.assert_not_called()
        mock_link_learners_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    @ddt.data(True, False)
    def test_assign_non_admin_user(self, user_is_staff, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self._test_and_assert_forbidden_user(self.assign_url, user_is_staff, mock_send_assignment_email_task)
        mock_link_learners_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_empty_emails(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint returns a 400 if the list of emails provided is empty.
        """
        response = self.api_client.post(self.assign_url, {'user_emails': []})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_assignment_email_task.assert_not_called()
        mock_link_learners_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_invalid_emails(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint returns a 400 if the list contains an invalid email.
        """
        response = self.api_client.post(self.assign_url, {'user_emails': ['lkajsdf']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_assignment_email_task.assert_not_called()
        mock_link_learners_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_insufficient_licenses(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint returns a 400 if there are not enough unassigned licenses to assign to.
        """
        # Create some assigned licenses which will not factor into the count
        assigned_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set(assigned_licenses)
        response = self.api_client.post(self.assign_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_assignment_email_task.assert_not_called()
        mock_link_learners_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_insufficient_licenses_revoked(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the endpoint returns a 400 if there are not enough licenses to assign to considering revoked licenses
        """
        # Create a revoked license that is not being assigned to
        revoked_license = LicenseFactory.create(status=constants.REVOKED, user_email='revoked@example.com')
        self.subscription_plan.licenses.set([revoked_license])
        response = self.api_client.post(self.assign_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_assignment_email_task.assert_not_called()
        mock_link_learners_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_already_associated_email(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint returns a 200 if there is already a license associated with a provided email.

        Verify the activation data returned in the response is correct and the new email is successfully assigned.
        """
        self._create_available_licenses()
        assigned_license = LicenseFactory.create(user_email=self.test_email, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set([assigned_license])
        user_emails = [self.test_email, 'unassigned@example.com']
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['num_successful_assignments'] == 1
        assert response.data['num_already_associated'] == 1
        mock_send_assignment_email_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            ['unassigned@example.com'],
            str(self.subscription_plan.uuid),
        )

        mock_link_learners_task.assert_called_with(
            ['unassigned@example.com'],
            self.subscription_plan.customer_agreement.enterprise_customer_uuid
        )

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    @ddt.data(True, False)
    def test_assign(self, use_superuser, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint assigns licenses to the provided emails and sends activation emails.

        Also verifies that a greeting and closing can be sent.
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', self.test_email]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned(user_emails)

        # Verify the activation email task was called with the correct args
        task_args, _ = mock_send_assignment_email_task.call_args
        actual_template_text, actual_emails, actual_subscription_uuid = task_args
        assert ['bb8@mit.edu', self.test_email] == sorted(actual_emails)
        assert str(self.subscription_plan.uuid) == actual_subscription_uuid
        assert self.greeting == actual_template_text['greeting']
        assert self.closing == actual_template_text['closing']

        mock_link_learners_task.assert_called_with(
            actual_emails,
            self.subscription_plan.customer_agreement.enterprise_customer_uuid
        )

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    @mock.patch('license_manager.apps.api.utils.set_datadog_tags')
    @ddt.data(True, False)
    def test_assign_set_custom_tags(
            self,
            use_superuser,
            mock_set_tags_util,
            mock_send_assignment_email_task, # pylint: disable=unused-argument
            mock_link_learners_task # pylint: disable=unused-argument
    ):
        """
        Verify the assign endpoint sets tags 'enterprise_customer_uuid' and 'external_request' on the request.
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', self.test_email]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )
        tags_dict = {
            'enterprise_customer_uuid': self.subscription_plan.customer_agreement.enterprise_customer_uuid,
        }
        # Verify that set_tags util was called with right arguments
        mock_set_tags_util.assert_called_with(tags_dict)
        assert response.status_code == status.HTTP_200_OK

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    @ddt.data(True, False)
    def test_assign_with_salesforce_ids(self, use_superuser, *arge, **kwargs):  # pylint: disable=unused-argument
        """
        Verify the assign endpoint assigns licenses and correct lincese sources are created.
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', self.test_email, 'ama@example.com', 'aaa@example.com']
        user_sfids = ['0000qse56709sdfd08', '0000abc34MS67a8907', '', None]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails, 'user_sfids': user_sfids},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned(user_emails)

        # verify that correct salesforce ids are assigned
        emails_and_sfids = dict(zip(user_emails, user_sfids))
        for email, salesforce_id in emails_and_sfids.items():
            assigned_license = self.subscription_plan.licenses.get(user_email=email, status=constants.ASSIGNED)

            if salesforce_id:
                assert assigned_license.source.source_id == salesforce_id
            else:
                with self.assertRaises(ObjectDoesNotExist):
                    SubscriptionLicenseSource.objects.get(license=assigned_license)

    @ddt.data(True, False)
    def test_assign_with_less_salesforce_ids(self, use_superuser):
        """
        Verify the assign endpoint raises correct error when user_sfids list has less items then user_emails.
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        user_emails = ['bb8@mit.edu', 'aaa@mit.edu']
        user_sfids = ['0010abc34MS67a8907']
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails, 'user_sfids': user_sfids},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            'non_field_errors': [
                'Number of Salesforce IDs did not match number of provided user emails.'
            ]
        }
        assert SubscriptionLicenseSource.objects.count() == 0

    @ddt.data(True, False)
    def test_assign_with_empty_salesforce_ids(self, use_superuser):
        """
        Verify the assign endpoint raises correct error when user_sfids is present but empty.
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        user_emails = ['bb8@mit.edu']
        user_sfids = []
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails, 'user_sfids': user_sfids},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {'user_sfids': ['No Salesforce Ids provided.']}
        assert SubscriptionLicenseSource.objects.count() == 0

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    @ddt.data(True, False)
    def test_assign_is_locked(self, use_superuser, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint respects any existing locks for the requested plan.
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', self.test_email]

        # lock the subscription plan, as if another concurrent request
        # is also trying to assign licenses.
        try:
            acquire_subscription_plan_lock(
                self.subscription_plan,
                django_cache_timeout=10,
            )
            response = self.api_client.post(
                self.assign_url,
                {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
            )
        finally:
            release_subscription_plan_lock(self.subscription_plan)

        assert response.status_code == status.HTTP_423_LOCKED
        assert self.subscription_plan.licenses.filter(status=constants.ASSIGNED).count() == 0
        self.assertFalse(mock_send_assignment_email_task.called)
        self.assertFalse(mock_link_learners_task.called)

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    @mock.patch('license_manager.apps.api.v1.views.License.bulk_update')
    def test_assign_is_atomic(self, mock_bulk_update, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify that license assignment is atomic and no updates
        are made if an error occurs.
        """
        self._setup_request_jwt(user=self.user)
        self._create_available_licenses()

        mock_bulk_update.side_effect = DatabaseError('fail')

        user_emails = ['bb8@mit.edu', self.test_email]

        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        self.assertEqual(
            'Database error occurred while assigning licenses, no assignments were completed',
            response.json(),
        )
        self.assertFalse(mock_send_assignment_email_task.called)
        self.assertFalse(mock_link_learners_task.called)
        for _license in self.subscription_plan.licenses.all():
            self.assertEqual(constants.UNASSIGNED, _license.status)

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_dedupe_input(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint deduplicates submitted emails.
        """
        self._create_available_licenses()
        user_emails = [self.test_email, self.test_email]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned([self.test_email])
        mock_send_assignment_email_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            [self.test_email],
            str(self.subscription_plan.uuid),
        )
        mock_link_learners_task.assert_called_with(
            [self.test_email],
            self.subscription_plan.customer_agreement.enterprise_customer_uuid
        )

    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_dedupe_casing_input(self, mock_send_assignment_email_task, mock_link_learners_task):
        """
        Verify the assign endpoint deduplicates submitted emails with different casing.
        """
        self._create_available_licenses()
        user_emails = [self.test_email, self.test_email.upper()]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned([self.test_email])
        mock_send_assignment_email_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            [self.test_email.lower()],
            str(self.subscription_plan.uuid),
        )
        mock_link_learners_task.assert_called_with(
            [self.test_email.lower()],
            self.subscription_plan.customer_agreement.enterprise_customer_uuid
        )

    @ddt.data(
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, False),
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.v1.views.create_braze_aliases_task.si')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_notify_users(
        self,
        notify_users,
        disable_onboarding_notifications,
        should_send_assignment_email,
        mock_send_assignment_email_task,
        _,
        __,
    ):
        """
        Verify that users are not sent a license assignment email if notify_users=False
        or disable_onboarding_notifications=True.
        """

        customer_agreement = self.subscription_plan.customer_agreement
        customer_agreement.disable_onboarding_notifications = disable_onboarding_notifications
        customer_agreement.save()

        self._create_available_licenses()
        user_emails = [self.test_email, self.test_email.upper()]
        response = self.api_client.post(
            self.assign_url,
            {'user_emails': user_emails, 'notify_users': notify_users},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned([self.test_email])

        assert mock_send_assignment_email_task.called == should_send_assignment_email

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_emails(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if no emails are provided.
        """
        response = self.api_client.post(self.remind_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    @ddt.data(True, False)
    def test_remind_non_admin_user(self, user_is_staff, mock_send_reminder_email_task):
        """
        Verify the remind endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self._test_and_assert_forbidden_user(self.remind_url, user_is_staff, mock_send_reminder_email_task)

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_invalid_emails(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if an invalid email is provided.
        """
        response = self.api_client.post(self.remind_url, {'user_emails': ['lkajsf']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_blank_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if an empty string is submitted for an email.
        """
        response = self.api_client.post(self.remind_url, {'user_emails': ['']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_valid_subscription_plan(self, mock_send_reminder_emails_task):
        """
        Test that calls to remind fail with a 403 if no valid subscription plan uuid
        is provided, for requests made by a regular user.  A 403 is expected because our
        test user has an admin role assigned for a specific, existing enterprise, but (obviously)
        there is no role assignment for an enterprise/subscription plan that does not exist.
        """
        response = self.api_client.post(
            reverse('api:v1:licenses-remind', kwargs={'subscription_uuid': uuid4()}),
            {'user_emails': ['edx@example.com']}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_remind_no_valid_subscription_plan_superuser(self, mock_revoke_license):
        """
        Test that calls to bulk_revoke fail with a 404 if no valid subscription plan uuid
        is provided, for requests made by a superuser.
        """
        self._setup_request_jwt(user=self.super_user)

        response = self.api_client.post(
            reverse('api:v1:licenses-remind', kwargs={'subscription_uuid': uuid4()}),
            {'user_emails': ['edx@example.com']}
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        self.assertFalse(mock_revoke_license.called)

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_license_for_user(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 404 if there is no license associated with the given email.
        """
        response = self.api_client.post(self.remind_url, {'user_emails': ['nolicense@example.com']})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_pending_license_for_user(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 404 if there is no pending license associated with the given email.
        """
        activated_license = LicenseFactory.create(user_email=self.test_email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([activated_license])

        response = self.api_client.post(self.remind_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    @ddt.data(True, False)
    def test_remind(self, use_superuser, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint sends an email to the specified user with a pending license.
        Also verifies that a custom greeting and closing can be sent to the endpoint
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        pending_license = LicenseFactory.create(user_email=self.test_email, status=constants.ASSIGNED)
        pending_license_b = LicenseFactory.create(user_email='other@example.com', status=constants.ASSIGNED)
        self.subscription_plan.licenses.set([pending_license, pending_license_b])

        with mock.patch('license_manager.apps.subscriptions.constants.REMINDER_EMAIL_BATCH_SIZE', new=1):
            response = self.api_client.post(
                self.remind_url,
                {
                    'user_emails': [self.test_email, 'other@example.com'],
                    'greeting': self.greeting,
                    'closing': self.closing,
                },
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_send_reminder_emails_task.assert_has_calls([
            mock.call(
                {'greeting': self.greeting, 'closing': self.closing},
                [self.test_email],
                str(self.subscription_plan.uuid),
            ),
            mock.call(
                {'greeting': self.greeting, 'closing': self.closing},
                ['other@example.com'],
                str(self.subscription_plan.uuid),
            ),
        ])

    @ddt.data(
        ([{'name': 'user_email', 'filter_value': 'al'}], ['alice@example.com']),
        ([{'name': 'status_in', 'filter_value': [constants.ACTIVATED]}], []),
        (
            [{'name': 'status_in', 'filter_value': [constants.ASSIGNED, constants.ACTIVATED]}],
            ['alice@example.com', 'bob@example.com']
        ),
        ([{'name': 'user_email', 'filter_value': 'al'},
          {'name': 'status_in', 'filter_value': [constants.ACTIVATED]}], []),
        ([{'name': 'user_email', 'filter_value': 'al'},
          {'name': 'status_in', 'filter_value': [constants.ASSIGNED]}], ['alice@example.com'])
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_with_filters(self, filters, expected_reminded_emails, mock_send_reminder_emails_task):
        """
        Test that remind endpoint works with filters.
        """
        self._setup_request_jwt(user=self.user)
        alice_license = LicenseFactory.create(user_email='alice@example.com', status=constants.ASSIGNED)
        bob_license = LicenseFactory.create(user_email='bob@example.com', status=constants.ASSIGNED)
        activated_license = LicenseFactory.create(user_email='sam@example.com', status=constants.ACTIVATED)
        revoked_license = LicenseFactory.create(user_email='eve@example.com', status=constants.REVOKED)
        self.subscription_plan.licenses.set([alice_license, bob_license, activated_license, revoked_license])

        request_payload = {
            'filters': filters
        }

        response = self.api_client.post(self.remind_url, request_payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        if expected_reminded_emails:
            reminded_emails = mock_send_reminder_emails_task.call_args_list[0][0][1]
            assert sorted(reminded_emails) == expected_reminded_emails
        else:
            self.assertFalse(mock_send_reminder_emails_task.called)

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_all_no_pending_licenses(self, mock_send_reminder_emails_task):
        """
        Verify that the remind all endpoint returns a 404 if there are no pending licenses.
        """
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        self.subscription_plan.licenses.set(unassigned_licenses)

        response = self.api_client.post(self.remind_all_url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_all(self, mock_send_reminder_emails_task):
        """
        Verify that the remind all endpoint sends an email to each user with a pending license.
        Also verifies that a custom greeting and closing can be sent to the endpoint.
        """
        # Create some pending and non-pending licenses for the subscription
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        pending_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set(unassigned_licenses + pending_licenses)

        with mock.patch('license_manager.apps.subscriptions.constants.REMINDER_EMAIL_BATCH_SIZE', new=2):
            response = self.api_client.post(self.remind_all_url, {'greeting': self.greeting, 'closing': self.closing})

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify emails sent to only the pending licenses
        mock_send_reminder_emails_task.assert_has_calls([
            mock.call(
                {'greeting': self.greeting, 'closing': self.closing},
                mock.ANY,
                str(self.subscription_plan.uuid),
            ),
            mock.call(
                {'greeting': self.greeting, 'closing': self.closing},
                mock.ANY,
                str(self.subscription_plan.uuid),
            ),
        ])
        pending_emails = [license.user_email for license in pending_licenses]
        actually_called_emails = []
        for call in mock_send_reminder_emails_task.call_args_list:
            actually_called_emails.extend(call.args[1])

        assert set(pending_emails) == set(actually_called_emails)

    @ddt.data(True, False)
    def test_license_overview(self, ignore_null_emails):
        """
        Verify that the overview endpoint for the state of all licenses in the subscription returns correctly
        """
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        pending_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        revoked_licenses = LicenseFactory.create_batch(2, status=constants.REVOKED)
        self.subscription_plan.licenses.set(unassigned_licenses + pending_licenses + revoked_licenses)

        revoked_licenses[0].user_email = None
        revoked_licenses[0].save()

        api_url = self.license_overview_url
        if ignore_null_emails:
            api_url += '?ignore_null_emails=1'

        response = self.api_client.get(api_url)
        assert response.status_code == status.HTTP_200_OK

        expected_response = [
            {'status': constants.UNASSIGNED, 'count': len(unassigned_licenses)},
            {'status': constants.ASSIGNED, 'count': len(pending_licenses)},
            {
                'status': constants.REVOKED,
                'count': len(revoked_licenses) - 1 if ignore_null_emails else len(revoked_licenses)
            },
        ]
        actual_response = response.data
        assert expected_response == actual_response

    @staticmethod
    def _get_csv_data_rows(response):
        """
        Helper method to create list of str for each row in the CSV data
        returned from the licenses CSV endpoint. As is expected, each
        column in a given row is comma separated.
        """
        return str(response.data)[2:].split('\\r\\n')[:-1]

    def test_csv_action_license_fields(self):
        """
        Tests that the CSV action only returns the expected license fields
        in the data, as detailed by the expected_fields list below.
        """
        expected_fields = [
            'status',
            'user_email',
            'activation_date',
            'last_remind_date',
            'activation_link',
        ]
        assigned_license = LicenseFactory.create(status=constants.ASSIGNED)
        self.subscription_plan.licenses.set([assigned_license])
        response = self.api_client.get(self.licenses_csv_url)
        rows = self._get_csv_data_rows(response)
        response_license_fields = rows[0].split(',')
        assert set(expected_fields) == set(response_license_fields)

    def test_csv_action_license_statuses(self):
        """
        Tests that the CSV action only returns data for licenses with status of:
         - Assigned
         - Activated
         - Revoked
        """
        assigned_license = LicenseFactory.create(status=constants.ASSIGNED)
        activated_license = LicenseFactory.create(status=constants.ACTIVATED)
        unassigned_license = LicenseFactory.create(status=constants.UNASSIGNED)
        revoked_license = LicenseFactory.create(status=constants.REVOKED)
        self.subscription_plan.licenses.set([
            assigned_license,
            activated_license,
            unassigned_license,
            revoked_license,
        ])
        response = self.api_client.get(self.licenses_csv_url)
        rows = self._get_csv_data_rows(response)

        # Ensure that licenses with status of UNASSIGNED aren't
        # included in the CSV data returned in the response.
        for row in rows[1:]:
            cols = row.split(',')
            assert cols[3] != constants.UNASSIGNED

        # Ensure that the correct number of licenses is returned
        # in the CSV data returned in the response.
        num_allocated_licenses = self.subscription_plan.licenses.filter(
            status__in=[
                constants.ASSIGNED,
                constants.ACTIVATED,
                constants.REVOKED,
            ],
        ).count()
        assert num_allocated_licenses == len(rows) - 1


@ddt.ddt
class LicenseViewSetRevokeActionTests(LicenseViewSetActionMixin, TestCase):
    """
    Tests for the license revoke action.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.bulk_revoke_license_url = reverse(
            'api:v1:licenses-bulk-revoke',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )
        cls.revoke_all_licenses_url = reverse(
            'api:v1:licenses-revoke-all',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )
        cls.assign_url = reverse(
            'api:v1:licenses-assign',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )

    def setUp(self):
        super().setUp()
        self.mock_track_test_mocker = mock.patch('license_manager.apps.api.v1.views.track_license_changes_task')
        self.mock_track_test_mocker.start()

    def tearDown(self):
        super().tearDown()
        self.mock_track_test_mocker.stop()

    @mock.patch('license_manager.apps.api.v1.views.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_happy_path(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Test that we can revoke multiple licenses from the bulk_revoke action.
        """
        self._setup_request_jwt(user=self.user)
        alice_license = LicenseFactory.create(user_email='alice@example.com', status=constants.ACTIVATED)
        alice_assigned_license = LicenseFactory.create(user_email='alice@example.com', status=constants.ASSIGNED)
        bob_license = LicenseFactory.create(user_email='bob@example.com', status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([alice_license, bob_license, alice_assigned_license])

        request_payload = {
            'user_emails': [
                'alice@example.com',
                'bob@example.com',
            ],
        }

        revoke_alice_license_result = {
            'revoked_license': alice_assigned_license, 'original_status': alice_assigned_license.status,
        }
        revoke_bob_license_result = {'revoked_license': bob_license, 'original_status': bob_license.status}
        mock_revoke_license.side_effect = [revoke_alice_license_result, revoke_bob_license_result]

        response = self.api_client.post(self.bulk_revoke_license_url, request_payload)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        # Since alice has multiple licenses, we should only revoke her assigned one.
        mock_revoke_license.assert_has_calls([
            mock.call(alice_assigned_license),
            mock.call(bob_license),
        ])

        mock_execute_post_revocation_tasks.assert_has_calls([
            mock.call(**revoke_alice_license_result),
            mock.call(**revoke_bob_license_result),
        ])

    @mock.patch('license_manager.apps.api.v1.views.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    @mock.patch('license_manager.apps.api.utils.set_datadog_tags')
    def test_bulk_revoke_set_custom_tags(
        self,
        mock_set_tags_util,
        mock_revoke_license,
        mock_execute_post_revocation_tasks # pylint: disable=unused-argument
    ):
        """
        Verify the bulk-revoke endpoint sets tags 'enterprise_customer_uuid' and 'external_request' on the request.
        """
        self._setup_request_jwt(user=self.user)
        alice_license = LicenseFactory.create(user_email='alice@example.com', status=constants.ACTIVATED)
        alice_assigned_license = LicenseFactory.create(user_email='alice@example.com', status=constants.ASSIGNED)
        bob_license = LicenseFactory.create(user_email='bob@example.com', status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([alice_license, bob_license, alice_assigned_license])

        request_payload = {
            'user_emails': [
                'alice@example.com',
                'bob@example.com',
            ],
        }

        revoke_alice_license_result = {
            'revoked_license': alice_assigned_license, 'original_status': alice_assigned_license.status,
        }
        revoke_bob_license_result = {'revoked_license': bob_license, 'original_status': bob_license.status}
        mock_revoke_license.side_effect = [revoke_alice_license_result, revoke_bob_license_result]

        response = self.api_client.post(self.bulk_revoke_license_url, request_payload)
        tags_dict = {
            'enterprise_customer_uuid': self.subscription_plan.customer_agreement.enterprise_customer_uuid,
        }
        # Verify that set_tags util was called with right arguments
        mock_set_tags_util.assert_called_with(tags_dict)
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @mock.patch('license_manager.apps.api.v1.views.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_multiple_activated_same_email(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Test the edge condition where one email in a single plan has multiple activated licenses.
        """
        self._setup_request_jwt(user=self.user)
        alice_license_1 = LicenseFactory.create(
            uuid='00000000-0000-0000-0000-000000000000',
            user_email='alice@example.com', status=constants.ACTIVATED,
        )
        alice_license_2 = alice_license_1 = LicenseFactory.create(
            uuid='00000000-0000-0000-0000-000000000001',
            user_email='alice@example.com', status=constants.ACTIVATED,
        )
        self.subscription_plan.licenses.set([alice_license_1, alice_license_2])

        request_payload = {
            'user_emails': [
                'alice@example.com',
            ],
        }

        revoke_alice_license_result = {
            'revoked_license': alice_license_1, 'original_status': alice_license_1.status,
        }
        mock_revoke_license.side_effect = [revoke_alice_license_result]

        response = self.api_client.post(self.bulk_revoke_license_url, request_payload)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        # Since alice has multiple licenses, we should only revoke the first one (which is arbitrarily
        # the one with the smallest uuid).
        mock_revoke_license.assert_has_calls([
            mock.call(alice_license_1),
        ])

        mock_execute_post_revocation_tasks.assert_has_calls([
            mock.call(**revoke_alice_license_result),
        ])

    @ddt.data(
        ([{'name': 'user_email', 'filter_value': 'al'}], ['alice@example.com']),
        ([{'name': 'status_in', 'filter_value': [constants.ACTIVATED]}], ['alice@example.com']),
        ([{'name': 'status_in', 'filter_value': [constants.REVOKED]}], []),
        (
            [{'name': 'status_in', 'filter_value': [constants.ASSIGNED, constants.ACTIVATED]}],
            ['alice@example.com', 'bob@example.com']
        ),
        ([{'name': 'user_email', 'filter_value': 'al'},
          {'name': 'status_in', 'filter_value': [constants.ACTIVATED]}], ['alice@example.com']),
        ([{'name': 'user_email', 'filter_value': 'al'},
          {'name': 'status_in', 'filter_value': [constants.ASSIGNED]}], [])
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.v1.views.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_with_filters_happy_path(
            self, filters, expected_revoked_emails, mock_revoke_license, mock_execute_post_revocation_tasks
    ):
        """
        Test that we can revoke multiple licenses from the bulk_revoke action using filters.
        """
        self._setup_request_jwt(user=self.user)
        alice_license = LicenseFactory.create(user_email='alice@example.com', status=constants.ACTIVATED)
        bob_license = LicenseFactory.create(user_email='bob@example.com', status=constants.ASSIGNED)
        revoked_license = LicenseFactory.create(user_email='sam@example.com', status=constants.REVOKED)
        self.subscription_plan.licenses.set([alice_license, bob_license, revoked_license])

        request_payload = {
            'filters': filters
        }

        response = self.api_client.post(self.bulk_revoke_license_url, request_payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        revoked_emails = [call_arg[0][0].user_email for call_arg in mock_revoke_license.call_args_list]
        assert sorted(revoked_emails) == expected_revoked_emails

        assert mock_execute_post_revocation_tasks.call_count == len(expected_revoked_emails)

    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_no_valid_subscription_plan(self, mock_revoke_license):
        """
        Test that calls to bulk_revoke fail with a 403 if no valid subscription plan uuid
        is provided, for requests made by a regular user.  A 403 is expected because our
        test user has an admin role assigned for a specific, existing enterprise, but (obviously)
        there is no role assignment for an enterprise/subscription plan that does not exist.
        """
        self._setup_request_jwt(user=self.user)

        request_payload = {
            'user_emails': [
                'alice@example.com',
                'bob@example.com',
            ],
        }
        non_existent_uuid = uuid4()
        request_url = reverse(
            'api:v1:licenses-bulk-revoke',
            kwargs={'subscription_uuid': non_existent_uuid},
        )
        response = self.api_client.post(request_url, request_payload)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        self.assertFalse(mock_revoke_license.called)

    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_no_valid_subscription_plan_superuser(self, mock_revoke_license):
        """
        Test that calls to bulk_revoke fail with a 404 if no valid subscription plan uuid
        is provided, for requests made by a superuser.
        """
        self._setup_request_jwt(user=self.super_user)

        request_payload = {
            'user_emails': [
                'alice@example.com',
                'bob@example.com',
            ],
        }
        non_existent_uuid = uuid4()
        request_url = reverse(
            'api:v1:licenses-bulk-revoke',
            kwargs={'subscription_uuid': non_existent_uuid},
        )
        response = self.api_client.post(request_url, request_payload)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        expected_response_message = 'No SubscriptionPlan identified by {} exists'.format(non_existent_uuid)
        self.assertEqual(expected_response_message, response.json())
        self.assertFalse(mock_revoke_license.called)

    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_not_enough_revocations_remaining(self, mock_revoke_license):
        """
        Test that calls to bulk_revoke fail with a 400 if the plan does not have enough
        revocations remaining.
        """
        plan = SubscriptionPlanFactory.create(
            is_revocation_cap_enabled=True,
            revoke_max_percentage=0,
        )
        _ = LicenseFactory.create(
            subscription_plan=plan,
            user_email='alice@example.com',
            status=constants.ACTIVATED,
        )

        self._setup_request_jwt(self.user, plan.enterprise_customer_uuid)
        request_payload = {
            'user_emails': ['alice@example.com'],
        }
        request_url = reverse(
            'api:v1:licenses-bulk-revoke',
            kwargs={'subscription_uuid': plan.uuid},
        )
        response = self.api_client.post(request_url, request_payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        expected_response_message = 'Plan does not have enough revocations remaining.'
        self.assertEqual(expected_response_message, response.json())
        self.assertFalse(mock_revoke_license.called)

    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_license_not_found(self, mock_revoke_license):
        """
        Test that calls to bulk_revoke fail with a 404 if the plan does not have enough
        revocations remaining.
        """
        self._setup_request_jwt(self.user)

        alice_license = LicenseFactory.create(
            subscription_plan=self.subscription_plan,
            user_email='alice@example.com',
            status=constants.ACTIVATED,
        )

        request_payload = {
            'user_emails': [
                'alice@example.com',
                'bob@example.com',  # There's no license for bob
            ],
        }
        response = self.api_client.post(self.bulk_revoke_license_url, request_payload)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        expected_error_msg = (
            "No license for email bob@example.com exists in plan "
            "{} with a status in ['activated', 'assigned']".format(self.subscription_plan.uuid)
        )
        self.assertEqual(expected_error_msg, response.json())
        mock_revoke_license.assert_called_once_with(alice_license)

    @mock.patch('license_manager.apps.api.v1.views.revoke_license')
    def test_bulk_revoke_license_revocation_error(self, mock_revoke_license):
        """
        Test that calls to bulk_revoke fail with a 400 if some error occurred during
        the actual revocation process.
        """
        self._setup_request_jwt(self.user)

        alice_license = LicenseFactory.create(
            subscription_plan=self.subscription_plan,
            user_email='alice@example.com',
            status=constants.ACTIVATED,
        )

        mock_revoke_license.side_effect = LicenseRevocationError(alice_license.uuid, 'floor is lava')

        request_payload = {
            'user_emails': [
                'alice@example.com',
            ],
        }
        response = self.api_client.post(self.bulk_revoke_license_url, request_payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        expected_error_msg = "Action: license revocation failed for license: {} because: {}".format(
            alice_license.uuid,
            'floor is lava',
        )
        self.assertEqual(expected_error_msg, response.json())
        mock_revoke_license.assert_called_once_with(alice_license)

    def test_revoke_all_no_valid_subscription_plan_superuser(self):
        """
        Test that calls to revoke-all fail with a 404 if no valid subscription plan uuid
        is provided, for requests made by a superuser.
        """
        self._setup_request_jwt(user=self.super_user)

        non_existent_uuid = uuid4()
        request_url = reverse(
            'api:v1:licenses-revoke-all',
            kwargs={'subscription_uuid': non_existent_uuid},
        )
        response = self.api_client.post(request_url, {})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        expected_response_message = 'No SubscriptionPlan identified by {} exists'.format(non_existent_uuid)
        self.assertEqual(expected_response_message, response.json())

    def test_revoke_all_revocation_cap_enabled(self):
        """
        Test that calls to revoke-all fail with a 422 if revocation cap is enabled
        """
        self._setup_request_jwt(user=self.super_user)

        subscription_plan = SubscriptionPlanFactory.create(is_revocation_cap_enabled=True)
        request_url = reverse(
            'api:v1:licenses-revoke-all',
            kwargs={'subscription_uuid': subscription_plan.uuid},
        )
        response = self.api_client.post(request_url, {})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        expected_response_message = (
            'Cannot revoke all licenses when revocation cap is enabled for the subscription plan'
        )
        self.assertEqual(expected_response_message, response.json())

    @mock.patch('license_manager.apps.api.tasks.revoke_all_licenses_task.delay')
    def test_revoke_all_happy_path(self, mock_revoke_all_licenses_task):
        """
        Test that calls to revoke-all calls the revoke_all_licenses task
        """
        self._setup_request_jwt(user=self.super_user)
        response = self.api_client.post(self.revoke_all_licenses_url, {})
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_revoke_all_licenses_task.assert_called()

    @ddt.data(
        {'is_revocation_cap_enabled': True},
        {'is_revocation_cap_enabled': False},
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.v1.views.link_learners_to_enterprise_task.si')
    @mock.patch('license_manager.apps.api.tasks.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.api.tasks.send_revocation_cap_notification_email_task.delay')
    @mock.patch('license_manager.apps.api.v1.views.send_assignment_email_task.si')
    def test_assign_after_license_revoke_end_to_end(
        self,
        mock_send_assignment_email_task,
        mock_send_revocation_cap_notification_email_task,
        mock_revoke_course_enrollments_for_user_task,
        mock_link_learners_task,
        is_revocation_cap_enabled,
    ):
        """
        Verifies that assigning a license after revoking one works
        """
        original_license = LicenseFactory.create(user_email=self.test_email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([original_license])
        self.subscription_plan.is_revocation_cap_enabled = is_revocation_cap_enabled
        self.subscription_plan.save()

        response = self.api_client.post(self.bulk_revoke_license_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_revoke_course_enrollments_for_user_task.assert_called()
        if is_revocation_cap_enabled:
            mock_send_revocation_cap_notification_email_task.assert_called_with(
                subscription_uuid=self.subscription_plan.uuid,
            )
        else:
            mock_send_revocation_cap_notification_email_task.assert_not_called()

        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', self.test_email]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned(user_emails)

        # Verify the activation email task was called with the correct args
        task_args, _ = mock_send_assignment_email_task.call_args
        actual_template_text, actual_emails, actual_subscription_uuid = task_args
        assert ['bb8@mit.edu', self.test_email] == sorted(actual_emails)
        assert str(self.subscription_plan.uuid) == actual_subscription_uuid
        assert self.greeting == actual_template_text['greeting']
        assert self.closing == actual_template_text['closing']

        mock_link_learners_task.assert_called_with(
            actual_emails,
            self.subscription_plan.customer_agreement.enterprise_customer_uuid
        )

    @mock.patch('license_manager.apps.api.tasks.revoke_course_enrollments_for_user_task.delay')
    def test_revoke_total_and_allocated_count_end_to_end(
        self,
        mock_revoke_course_enrollments_for_user_task,
    ):
        """
        Verifies revoking a license keeps the `total` license count the same, and the `allocated` count decreases by 1.
        """
        # Create some allocated licenses
        assigned_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        activated_license = LicenseFactory.create(user_email=self.test_email, status=constants.ACTIVATED)
        allocated_licenses = assigned_licenses + [activated_license]
        # Create one non allocated license
        unassigned_license = LicenseFactory.create(status=constants.UNASSIGNED)
        self.subscription_plan.licenses.set([unassigned_license] + allocated_licenses)

        # Verify the original `total` and `allocated` counts are correct
        response = _subscriptions_detail_request(self.api_client, self.super_user, self.subscription_plan.uuid)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['licenses'] == {
            'total': len(allocated_licenses) + 1,
            'allocated': len(allocated_licenses),
            'revoked': 0,
            'activated': 1,
            'assigned': len(assigned_licenses),
            'unassigned': 1,
        }

        # Revoke the activated license and verify the counts change appropriately
        revoke_response = self.api_client.post(self.bulk_revoke_license_url, {'user_emails': [self.test_email]})
        assert revoke_response.status_code == status.HTTP_204_NO_CONTENT
        mock_revoke_course_enrollments_for_user_task.assert_called()

        second_detail_response = _subscriptions_detail_request(
            self.api_client,
            self.super_user,
            self.subscription_plan.uuid,
        )
        assert second_detail_response.status_code == status.HTTP_200_OK
        assert second_detail_response.json()['licenses'] == {
            'total': len(allocated_licenses) + 1,
            # There should be 1 fewer allocated license now that we revoked the activated license
            'allocated': len(allocated_licenses) - 1,
            # ...and we create a new, unassigned license on revocation, so there should
            # now be 2 unassigned licenses in this plan
            'unassigned': 2,
            'revoked': 1,
            'activated': 0,
            'assigned': len(assigned_licenses),
        }


class LicenseViewTestMixin:
    def setUp(self):
        super().setUp()

        # API client setup
        self.api_client = APIClient()
        self.api_client.force_authenticate(user=self.user)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = UserFactory()
        cls.user2 = UserFactory()
        cls.users = [cls.user, cls.user2]
        cls.enterprise_customer_uuid = uuid4()
        cls.enterprise_catalog_uuid = uuid4()
        cls.course_key = 'testX'
        cls.lms_user_id = 1
        cls.now = localized_utcnow()
        cls.activation_key = uuid4()

        cls.customer_agreement = CustomerAgreementFactory(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
        )
        cls.active_subscription_for_customer = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            enterprise_catalog_uuid=cls.enterprise_catalog_uuid,
            is_active=True,
        )

    @property
    def _decoded_jwt(self):
        return {'user_id': self.lms_user_id}

    def _assign_learner_roles(self, alternate_customer=None, jwt_payload_extra=None):
        """
        Helper that assigns the correct learner role via JWT to the user.
        """
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            alternate_customer or self.enterprise_customer_uuid,
            assign_via_jwt=True,
            system_role=constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            subscriptions_role=constants.SUBSCRIPTIONS_LEARNER_ROLE,
            jwt_payload_extra=jwt_payload_extra,
        )

    def _assign_multi_learner_roles(self, alternate_customer=None, jwt_payload_extra=None):
        """
        Helper that assigns the correct learner role via JWT to the user.
        """
        for user in self.users:
            _assign_role_via_jwt_or_db(
                self.api_client,
                user,
                alternate_customer or self.enterprise_customer_uuid,
                assign_via_jwt=True,
                system_role=constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
                subscriptions_role=constants.SUBSCRIPTIONS_LEARNER_ROLE,
                jwt_payload_extra=jwt_payload_extra,
            )

    def _create_license(
        self,
        subscription_plan=None,
        **kwargs,
    ):
        """
        Helper method to create a license.
        """
        if not subscription_plan:
            subscription_plan = self.active_subscription_for_customer
        return LicenseFactory.create(
            status=kwargs.pop('status', constants.ASSIGNED),
            lms_user_id=self.lms_user_id,
            user_email=self.user.email,
            subscription_plan=subscription_plan,
            activation_key=kwargs.pop('activation_key', self.activation_key),
            activation_date=kwargs.pop('activation_date', None),
            **kwargs,
        )


@ddt.ddt
class LearnerLicensesViewsetTests(LicenseViewTestMixin, TestCase):
    """
    Tests for the LearnerLicensesViewset
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.base_url = reverse('api:v1:learner-licenses-list')

    def _get_url_with_customer_uuid(
        self,
        enterprise_customer_uuid,
        active_plans_only=True,
        current_plans_only=True,
        include_revoked=False
    ):
        """
        Private helper method to make a get request to the base URL
        using the enterprise_customer_uuid query parameter.
        """
        query_params = QueryDict(mutable=True)
        query_params['enterprise_customer_uuid'] = enterprise_customer_uuid
        query_params['active_plans_only'] = active_plans_only
        query_params['current_plans_only'] = current_plans_only
        query_params['include_revoked'] = include_revoked

        url = self.base_url + '?' + query_params.urlencode()
        return self.api_client.get(url)

    def test_endpoint_permissions_missing_role(self):
        """
        Verify the endpoint returns a 403 for users without the learner or admin role.
        """
        response = self._get_url_with_customer_uuid(self.enterprise_customer_uuid)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @ddt.data(
        {
            'system_role': constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            'subs_role': constants.SUBSCRIPTIONS_LEARNER_ROLE,
            'customer_match': True,
        },
        {
            'system_role': constants.SYSTEM_ENTERPRISE_ADMIN_ROLE,
            'subs_role': constants.SUBSCRIPTIONS_ADMIN_ROLE,
            'customer_match': True,
        },
        {
            'system_role': constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            'subs_role': constants.SUBSCRIPTIONS_LEARNER_ROLE,
            'customer_match': False,
        },
        {
            'system_role': constants.SYSTEM_ENTERPRISE_ADMIN_ROLE,
            'subs_role': constants.SUBSCRIPTIONS_ADMIN_ROLE,
            'customer_match': False,
        },
    )
    @ddt.unpack
    def test_endpoint_permissions_with_customer_uuid(self, system_role, subs_role, customer_match):
        """
        Data-driven test to ensure permissions are correctly enforced when the user
        does/doesn't have subs access to the specified customer as learner/admin.
        """
        customer_uuid = self.enterprise_customer_uuid if customer_match else uuid4()
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            customer_uuid,
            assign_via_jwt=True,
            system_role=system_role,
            subscriptions_role=subs_role,
        )

        response = self._get_url_with_customer_uuid(customer_uuid)

        assert response.status_code == status.HTTP_200_OK
        if not customer_match:
            content = response.json()  # pylint: disable=no-member
            assert content['results'] == []

    @ddt.data(
        {
            'system_role': constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            'subs_role': constants.SUBSCRIPTIONS_LEARNER_ROLE,
        },
        {
            'system_role': constants.SYSTEM_ENTERPRISE_ADMIN_ROLE,
            'subs_role': constants.SUBSCRIPTIONS_ADMIN_ROLE,
        },
    )
    @ddt.unpack
    def test_endpoint_request_missing_customer_uuid(self, system_role, subs_role):
        """
        Test that the appropriate response is returned when the enterprise_customer_uuid
        query param isn't included in the request with existing learner/admin roles.

        Note: role assignment is needed because 403 would be returned otherwise.
        """
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            self.enterprise_customer_uuid,
            assign_via_jwt=True,
            system_role=system_role,
            subscriptions_role=subs_role,
        )
        response = self.api_client.get(self.base_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'missing enterprise_customer_uuid query param' in str(response.content)

    def test_endpoint_results_contains_customer_agreement(self):
        """
        Tests if the learner-licenses endpoint contains the customer agreement object
        on the paginator.

        Checks if the serialized customer agreement from the response matches the mocked
        customer agreement.
        """
        self._assign_learner_roles()

        response = self._get_url_with_customer_uuid(self.enterprise_customer_uuid)

        assert response.status_code == status.HTTP_200_OK

        customer_agreement_response = response.json().get('customer_agreement')
        expected_days_until_expiration = self.customer_agreement.net_days_until_expiration
        expected_disable_expire_notifications = self.customer_agreement.disable_expiration_notifications
        assert customer_agreement_response['uuid'] == str(self.customer_agreement.uuid)
        assert customer_agreement_response['net_days_until_expiration'] == expected_days_until_expiration
        assert customer_agreement_response['disable_expiration_notifications'] == expected_disable_expire_notifications
        assert customer_agreement_response['subscription_for_auto_applied_licenses'] is None

        expected_available_catalog_uuids = [
            str(self.customer_agreement.subscriptions.first().enterprise_catalog_uuid)
        ]
        assert customer_agreement_response['available_subscription_catalogs'] == expected_available_catalog_uuids

    def test_endpoint_results_correctly_ordered(self):
        """
        Test the ordering of responses from the endpoint matches the following:
            ORDER BY License.status ASC, License.SubscriptionPlan.expiration_date DESC

        Licenses are created as follows:
         - Activated, expires in future
         - Activated, expires before ^
         - Assigned, expires in future
         - Assigned, expires before ^
        """
        self._assign_learner_roles()

        # Using SubscriptionPlan from LicenseViewTestMixin for first License
        self.active_subscription_for_customer.expiration_date = self.now + datetime.timedelta(weeks=52)
        first_license = self._create_license(
            activation_date=self.now,
            status=constants.ACTIVATED,
            subscription_plan=self.active_subscription_for_customer,
        )

        # Create second SubscriptionPlan and License
        second_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            expiration_date=self.now + datetime.timedelta(weeks=26),
            is_active=True,
        )
        second_license = self._create_license(
            activation_date=self.now,
            status=constants.ACTIVATED,
            subscription_plan=second_sub,
        )

        # Create third SubscriptionPlan and License
        third_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            expiration_date=self.now + datetime.timedelta(weeks=52),
            is_active=True,
        )
        third_license = self._create_license(
            activation_date=self.now,
            subscription_plan=third_sub,
        )

        # Create fourth SubscriptionPlan and License
        fourth_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            expiration_date=self.now + datetime.timedelta(weeks=26),
            is_active=True,
        )
        fourth_license = self._create_license(
            activation_date=self.now,
            subscription_plan=fourth_sub,
        )

        expected_response = [
            first_license,
            second_license,
            third_license,
            fourth_license,
        ]
        response = self._get_url_with_customer_uuid(self.enterprise_customer_uuid)
        for expected, actual in zip(expected_response, response.json()['results']):  # pylint: disable=no-member
            # Ensure UUIDs are in expected order
            assert str(expected.uuid) == actual['uuid']

            # Assert that nested subscription plan and customer agreement are
            # serialized in the response for each license.
            plan = expected.subscription_plan
            agreement = plan.customer_agreement
            assert actual['customer_agreement']['uuid'] == str(agreement.uuid)
            assert actual['subscription_plan']['uuid'] == str(plan.uuid)

    def test_endpoint_respects_active_only_query_parameter(self):
        self._assign_learner_roles()

        # The license in this subscription should be listed first in the
        # response results, because it's plan's expiration date is the furthest away.
        active_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            expiration_date=self.now + datetime.timedelta(weeks=20),
            is_active=True,
        )
        active_sub_license = self._create_license(
            activation_date=self.now,
            status=constants.ACTIVATED,
            subscription_plan=active_sub,
        )
        # Create a plan that starts in the future - we'll
        # later make our request with current_plans_only=false,
        # and we want to ensure that we will get this non-current
        # plan in the response results.
        inactive_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            start_date=self.now + datetime.timedelta(weeks=1),
            expiration_date=self.now + datetime.timedelta(weeks=10),
            is_active=False,
        )
        inactive_sub_license = self._create_license(
            activation_date=self.now,
            subscription_plan=inactive_sub,
            status=constants.ACTIVATED,
        )

        # We should get licenses from both the active and inactive plan if active_plans_only is false.
        response = self._get_url_with_customer_uuid(
            self.enterprise_customer_uuid, active_plans_only=False, current_plans_only=False,
        )
        expected_license_uuids = [
            str(active_sub_license.uuid),
            str(inactive_sub_license.uuid),
        ]
        actual_license_uuids = [
            user_license['uuid'] for user_license in response.json()['results']  # pylint: disable=no-member
        ]
        self.assertEqual(actual_license_uuids, expected_license_uuids)

        # We should get licenses from only the active plan if active_plans_only is true.
        response = self._get_url_with_customer_uuid(
            self.enterprise_customer_uuid, active_plans_only=True, current_plans_only=False,
        )
        expected_license_uuids = [
            str(active_sub_license.uuid),
        ]
        actual_license_uuids = [
            user_license['uuid'] for user_license in response.json()['results']  # pylint: disable=no-member
        ]
        self.assertEqual(actual_license_uuids, expected_license_uuids)

    def test_endpoint_respects_current_only_query_parameter(self):
        self._assign_learner_roles()

        # The license in this subscription should be listed first in the
        # response results, because it's plan's expiration date is the furthest away.
        current_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            start_date=self.now - datetime.timedelta(weeks=1),
            expiration_date=self.now + datetime.timedelta(weeks=20),
            is_active=True,
        )
        current_sub_license = self._create_license(
            activation_date=self.now,
            status=constants.ACTIVATED,
            subscription_plan=current_sub,
        )
        non_current_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            start_date=self.now + datetime.timedelta(weeks=1),
            expiration_date=self.now + datetime.timedelta(weeks=10),
            is_active=False,
        )
        non_current_sub_license = self._create_license(
            activation_date=self.now,
            subscription_plan=non_current_sub,
            status=constants.ACTIVATED,
        )

        # We should get licenses from both the current and non-current plan if current_plans_only is false.
        response = self._get_url_with_customer_uuid(
            self.enterprise_customer_uuid, current_plans_only=False, active_plans_only=False,
        )
        expected_license_uuids = [
            str(current_sub_license.uuid),
            str(non_current_sub_license.uuid),
        ]
        actual_license_uuids = [
            user_license['uuid'] for user_license in response.json()['results']  # pylint: disable=no-member
        ]
        self.assertEqual(actual_license_uuids, expected_license_uuids)

        # We should get licenses from only the current plan if current_plans_only and active_plans_only are true
        response = self._get_url_with_customer_uuid(
            self.enterprise_customer_uuid, current_plans_only=True, active_plans_only=True,
        )
        expected_license_uuids = [
            str(current_sub_license.uuid),
        ]
        actual_license_uuids = [
            user_license['uuid'] for user_license in response.json()['results']  # pylint: disable=no-member
        ]
        self.assertEqual(actual_license_uuids, expected_license_uuids)

    def test_endpoint_respects_include_revoked(self):
        self._assign_learner_roles()

        # The license in this subscription should be listed first in the
        # response results, because its plan's expiration date is the furthest away.
        current_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            start_date=self.now - datetime.timedelta(weeks=1),
            expiration_date=self.now + datetime.timedelta(weeks=20),
            is_active=True,
        )
        current_sub_license = self._create_license(
            activation_date=self.now,
            status=constants.ACTIVATED,
            subscription_plan=current_sub,
        )

        revoked_sub_license = self._create_license(
            activation_date=self.now,
            subscription_plan=current_sub,
            status=constants.REVOKED,
        )

        # We should get both current and revoked licenses if include_revoked is true.
        response = self._get_url_with_customer_uuid(
            self.enterprise_customer_uuid, current_plans_only=False, active_plans_only=False, include_revoked=True
        )
        expected_license_uuids = [
            str(current_sub_license.uuid),
            str(revoked_sub_license.uuid),
        ]
        actual_license_uuids = [
            user_license['uuid'] for user_license in response.json()['results']  # pylint: disable=no-member
        ]
        self.assertEqual(actual_license_uuids, expected_license_uuids)

    def test_user_changed_email(self):
        """
        Test that if a user changes their email, they would still be able to fetch their licenses
        and the licenses will be updated with the new email.
        """
        active_sub = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            expiration_date=self.now + datetime.timedelta(weeks=20),
            is_active=True,
        )
        # License with old email in current sub
        current_sub_license = LicenseFactory(
            lms_user_id=self.user.id,
            user_email=self.user.email,
            subscription_plan=active_sub,
        )

        new_email = 'new_email@testing.edx.org'
        self.user.email = new_email

        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            self.enterprise_customer_uuid,
            assign_via_jwt=True,
            system_role=constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            subscriptions_role=constants.SUBSCRIPTIONS_LEARNER_ROLE
        )

        # We should get still get the license
        response = self._get_url_with_customer_uuid(self.enterprise_customer_uuid)

        expected_license_uuids = [
            str(current_sub_license.uuid),
        ]

        results = response.json()['results']  # pylint: disable=no-member
        actual_license_uuids = [
            user_license['uuid'] for user_license in results
        ]
        self.assertEqual(actual_license_uuids, expected_license_uuids)
        current_sub_license.refresh_from_db()
        self.assertEqual(results[0]['user_email'], new_email)
        self.assertEqual(current_sub_license.user_email, new_email)


class EnterpriseEnrollmentWithLicenseSubsidyViewTests(LicenseViewTestMixin, TestCase):
    """
    Tests for the EnterpriseEnrollmentWithLicenseSubsidyView.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.base_url = reverse('api:v1:bulk-license-enrollment')
        cls.activated_license = LicenseFactory.create(
            status=constants.ACTIVATED,
            user_email=cls.user.email,
            subscription_plan=cls.active_subscription_for_customer,
        )
        cls.bulk_enrollment_job = BulkEnrollmentJobFactory.create(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
        )

    def _get_url_with_params(
        self,
        use_enterprise_customer=True,
        subscription_uuid=None,
        bulk_enrollment_job_uuid=None,
        enroll_all=None
    ):
        """
        Helper to add the appropriate query parameters to the base url if specified.
        """
        url = reverse('api:v1:bulk-license-enrollment')
        query_params = QueryDict(mutable=True)
        if use_enterprise_customer:
            # Use the override uuid if it's given
            query_params['enterprise_customer_uuid'] = self.enterprise_customer_uuid
        if subscription_uuid:
            query_params['subscription_uuid'] = subscription_uuid
        if bulk_enrollment_job_uuid:
            query_params['bulk_enrollment_job_uuid'] = bulk_enrollment_job_uuid
        if enroll_all:
            query_params['enroll_all'] = enroll_all
        return url + '/?' + query_params.urlencode()

    def test_bulk_enroll_with_missing_role(self):
        """
        Verify the view returns a 403 for users without the learner role.
        """
        url = self._get_url_with_params()
        response = self.api_client.post(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_bulk_enroll_with_missing_course_key_param(self):
        """
        Verify the view returns a 400 if the `course_run_keys` query param is not provided.
        """
        self._assign_learner_roles()
        url = self._get_url_with_params()
        response = self.api_client.post(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_enroll_with_missing_enterprise_customer(self):
        """
        Verify the view returns a 404 if the `enterprise_customer_uuid` query param is not provided.
        """
        self._assign_learner_roles()
        url = self._get_url_with_params(use_enterprise_customer=False)
        response = self.api_client.post(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.models.current_app.send_task')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_bulk_enroll(self, mock_get_decoded_jwt, mock_send_task):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        data = {
            'emails': [self.user.email],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params()
        response = self.api_client.post(url, data)

        mock_send_task.assert_called()
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json().get('job_id')

    @mock.patch('license_manager.apps.api.models.current_app.send_task')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    @mock.patch('license_manager.apps.api.utils.set_datadog_tags')
    def test_bulk_enroll_set_custom_tags(self, mock_set_tags_util, mock_get_decoded_jwt, mock_send_task):
        """
        Verify the view assigns tags to the request correctly.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        data = {
            'emails': [self.user.email],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params()
        response = self.api_client.post(url, data)

        # Verify that set_tags util was called with right arguments
        tags_dict = {
            'enterprise_customer_uuid': str(self.enterprise_customer_uuid),
        }
        mock_set_tags_util.assert_called_with(tags_dict)

        mock_send_task.assert_called()
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json().get('job_id')

    @mock.patch('license_manager.apps.api.models.current_app.send_task')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_bulk_enroll_all(self, mock_get_decoded_jwt, mock_send_task):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        data = {
            'emails': [self.user.email],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params(subscription_uuid=self.active_subscription_for_customer.uuid, enroll_all=True)
        response = self.api_client.post(url, data)

        mock_send_task.assert_called()
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json().get('job_id')

    @mock.patch('license_manager.apps.api.models.uuid4')
    @mock.patch('license_manager.apps.api.models.current_app.send_task')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_bulk_enroll_all_ignores_revoked_licenses(
        self,
        mock_get_decoded_jwt,
        mock_send_task,
        mock_enrollment_job_uuid
    ):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        job_uuid = uuid4()
        mock_enrollment_job_uuid.return_value = job_uuid
        inactive_user = UserFactory()
        LicenseFactory.create(
            status=constants.REVOKED,
            user_email=inactive_user.email,
            subscription_plan=self.active_subscription_for_customer,
        )
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        data = {
            'emails': [self.user.email],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params(subscription_uuid=self.active_subscription_for_customer.uuid, enroll_all=True)
        response = self.api_client.post(url, data)
        mock_send_task.assert_called_once_with(
            'license_manager.apps.api.tasks.enterprise_enrollment_license_subsidy_task',
            (
                str(job_uuid),
                str(self.enterprise_customer_uuid),
                [self.user.email],
                [self.course_key],
                True,
                str(self.active_subscription_for_customer.uuid),
            ),
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json().get('job_id')

    @mock.patch('license_manager.apps.api.models.uuid4')
    @mock.patch('license_manager.apps.api.models.current_app.send_task')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_bulk_enroll_all_uses_assigned_and_active_licenses(
        self,
        mock_get_decoded_jwt,
        mock_send_task,
        mock_enrollment_job_uuid
    ):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        job_uuid = uuid4()
        mock_enrollment_job_uuid.return_value = job_uuid
        assigned_user = UserFactory()
        LicenseFactory.create(
            status=constants.ASSIGNED,
            user_email=assigned_user.email,
            subscription_plan=self.active_subscription_for_customer,
        )
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        data = {
            'emails': [self.user.email],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params(subscription_uuid=self.active_subscription_for_customer.uuid, enroll_all=True)
        response = self.api_client.post(url, data)
        assert mock_send_task.call_count == 1
        actual_task_name, actual_task_args = mock_send_task.call_args_list[0][0]
        assert actual_task_name == 'license_manager.apps.api.tasks.enterprise_enrollment_license_subsidy_task'
        assert actual_task_args[0] == str(job_uuid)
        assert actual_task_args[1] == str(self.enterprise_customer_uuid)
        assert sorted(actual_task_args[2]) == sorted([self.user.email, assigned_user.email])
        assert actual_task_args[3] == [self.course_key]
        assert actual_task_args[4] is True
        assert actual_task_args[5] == str(self.active_subscription_for_customer.uuid)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json().get('job_id')

    def test_bulk_licensed_enrollment_with_enroll_all_no_sub_uuid(self):
        """
        Test that we properly handle requests with enroll_all params and no sub uuid
        """
        self._assign_learner_roles()
        data = {
            'emails': ['ayylmao@foobar.com'],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params(enroll_all=True)
        response = self.api_client.post(url, data)
        assert response.status_code == 400
        expected_json = {'subscription_id': ['This field is required when enroll_all is provided']}
        assert response.json() == expected_json

    def test_bulk_licensed_enrollment_with_missing_emails(self):
        """
        Test that we properly handle the odd empty string in the list of emails
        """
        self._assign_learner_roles()

        empty_email_data = {
            'emails': [],
            'course_run_keys': [self.course_key],
            'notify': True,
        }
        url = self._get_url_with_params()
        response = self.api_client.post(url, empty_email_data)
        assert response.status_code == 400
        expected_json = {'emails': ['This list may not be empty.']}
        assert response.json() == expected_json

    def test_bulk_enroll_too_many_enrollments(self):
        # Unnecessary math time!
        enrollment_split = ceil(sqrt(settings.BULK_ENROLL_REQUEST_LIMIT)) + 1

        self._assign_multi_learner_roles()

        payload = {
            'emails': [generate_random_email() for _ in range(enrollment_split)],
            'course_run_keys': random.sample(range(1, 100), enrollment_split),
            'notify': True,
        }
        url = self._get_url_with_params()
        response = self.api_client.post(url, payload)
        assert response.status_code == 400
        assert response.json() == constants.BULK_ENROLL_TOO_MANY_ENROLLMENTS

    @mock.patch(
        'license_manager.apps.api.v1.views.BulkEnrollmentJob.generate_download_url',
        return_value="https://example.com/download"
    )
    def test_bulk_enroll_status(self, mock_generate_download_url):
        self._assign_learner_roles()
        url = self._get_url_with_params(bulk_enrollment_job_uuid=self.bulk_enrollment_job.uuid)
        response = self.api_client.get(url)
        assert response.status_code == 200
        mock_generate_download_url.assert_called()
        assert response.json().get('job_id') == str(self.bulk_enrollment_job.uuid)
        assert response.json().get('download_url') == 'https://example.com/download'


@ddt.ddt
class LicenseSubsidyViewTests(LicenseViewTestMixin, TestCase):
    """
    Tests for the LicenseSubsidyView.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.base_url = reverse('api:v1:license-subsidy')
        cls.activated_license = LicenseFactory.create(
            status=constants.ACTIVATED,
            lms_user_id=cls.lms_user_id,
            subscription_plan=cls.active_subscription_for_customer,
        )

    def _get_url_with_params(
        self,
        use_enterprise_customer=True,
        use_course_key=True,
        enterprise_customer_override=None,
    ):
        """
        Helper to add the appropriate query parameters to the base url if specified.
        """
        url = reverse('api:v1:license-subsidy')
        query_params = QueryDict(mutable=True)
        if use_enterprise_customer:
            # Use the override uuid if it's given
            query_params['enterprise_customer_uuid'] = enterprise_customer_override or self.enterprise_customer_uuid
        if use_course_key:
            query_params['course_key'] = self.course_key
        return url + '/?' + query_params.urlencode()

    def test_get_subsidy_missing_role(self):
        """
        Verify the view returns a 403 for users without the learner role.
        """
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_subsidy_wrong_enterprise_customer(self):
        """
        Verify the view returns a 403 for users associated with a different enterprise than they are requesting.
        """
        # Create another enterprise and subscription the user has access to
        other_enterprise_uuid = uuid4()
        customer_agreement = CustomerAgreementFactory.create(enterprise_customer_uuid=other_enterprise_uuid)
        SubscriptionPlanFactory.create(customer_agreement=customer_agreement, is_active=True)
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            other_enterprise_uuid,
            assign_via_jwt=True,
            system_role=constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            subscriptions_role=constants.SUBSCRIPTIONS_LEARNER_ROLE,
        )

        # Request the subsidy view for an enterprise the user does not have access to
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_subsidy_missing_enterprise_customer(self):
        """
        Verify the view returns a 404 if the enterprise customer query param is not provided.
        """
        self._assign_learner_roles()
        url = self._get_url_with_params(use_enterprise_customer=False)
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_subsidy_missing_course_key(self):
        """
        Verify the view returns a 400 if the course key query param is not provided.
        """
        self._assign_learner_roles()
        url = self._get_url_with_params(use_course_key=False)
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    @mock.patch('license_manager.apps.api.mixins.LMSApiClient')
    def test_get_subsidy_no_jwt(self, MockLMSApiClient, mock_get_decoded_jwt):
        """
        Verify the view makes an API call to fetch lmsUserId if user_id could not be found in the JWT.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = {}
        url = self._get_url_with_params()

        # Mock the behavior of LMSApiClient to return a sample user ID
        mock_lms_client = MockLMSApiClient.return_value
        mock_lms_client.fetch_lms_user_id.return_value = 443
        response = self.api_client.get(url)
        assert status.HTTP_404_NOT_FOUND == response.status_code

        # Assert that the LMSApiClient.fetch_lms_user_id method was called once with the correct argument
        mock_lms_client.fetch_lms_user_id.assert_called_once_with(self.user.email)

    def test_get_subsidy_no_subscription_for_enterprise_customer(self):
        """
        Verify the view returns a 404 if there is no subscription plan for the enterprise customer.
        """
        self._assign_learner_roles()
        # Pass in some random enterprise_customer_uuid that doesn't have a subscripttion
        url = self._get_url_with_params(enterprise_customer_override=uuid4())
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy_no_active_subscription_for_customer(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 404 if there is no active license for the user.
        """
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        customer_agreement = CustomerAgreementFactory.create()
        subscription_plan = SubscriptionPlanFactory.create(customer_agreement=customer_agreement)
        LicenseFactory.create(subscription_plan=subscription_plan, status=constants.ASSIGNED)
        self._assign_learner_roles()
        # Mock the lms_user_id to be one not associated with any licenses
        mock_get_decoded_jwt.return_value = {'user_id': 500}
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy_no_activated_license_for_user(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 404 if the subscription has no activated license for the user.
        """
        self._assign_learner_roles()

        # Mock the lms_user_id to be one not associated with any activated license
        unactivated_user_id = 500
        mock_get_decoded_jwt.return_value = {'user_id': unactivated_user_id}
        LicenseFactory.create(
            subscription_plan=self.active_subscription_for_customer,
            status=constants.UNASSIGNED,
            lms_user_id=unactivated_user_id,
        )

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.subscriptions.models.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy_course_not_in_catalog(self, mock_get_decoded_jwt, mock_contains_content):
        """
        Verify the view returns a 404 if the subscription's catalog does not contain the given course.
        """
        self._assign_learner_roles()
        # Mock that the content was not found in the subscription's catalog
        mock_contains_content.return_value = False
        mock_get_decoded_jwt.return_value = self._decoded_jwt

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_contains_content.assert_called_with([self.course_key])

    def _assert_correct_subsidy_response(self, response, expected_checksum):
        """
        Verifies the license subsidy endpoint returns the correct response.
        """
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            'discount_type': constants.PERCENTAGE_DISCOUNT_TYPE,
            'discount_value': constants.LICENSE_DISCOUNT_VALUE,
            'status': constants.ACTIVATED,
            'subsidy_id': str(self.activated_license.uuid),
            'start_date': _iso_8601_format(self.active_subscription_for_customer.start_date),
            'expiration_date': _iso_8601_format(self.active_subscription_for_customer.expiration_date),
            'subsidy_checksum': expected_checksum,
        }

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    @mock.patch('license_manager.apps.api.v1.views.get_subsidy_checksum', return_value='some-hash', autospec=True)
    def test_get_subsidy(self, mock_get_subsidy_checksum, mock_get_decoded_jwt, mock_contains_content):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        self._assign_learner_roles()
        # Mock that the content was found in the subscription's catalog
        mock_contains_content.return_value = True
        mock_get_decoded_jwt.return_value = self._decoded_jwt

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        self._assert_correct_subsidy_response(response, mock_get_subsidy_checksum.return_value)
        mock_contains_content.assert_called_with([self.course_key])
        mock_get_subsidy_checksum.assert_called_once_with(
            self.activated_license.lms_user_id,
            self.course_key,
            self.activated_license.uuid,
        )


@ddt.ddt
class UserRetirementViewTests(TestCase):
    """
    Tests for the user retirement view.
    """

    def setUp(self):
        super().setUp()

        self.api_client = APIClient()
        self.retirement_user = UserFactory(username=settings.RETIREMENT_SERVICE_WORKER_USERNAME)
        self.api_client.force_authenticate(user=self.retirement_user)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.lms_user_id = 1
        cls.original_username = 'edxBob'
        cls.user_email = 'edxBob@example.com'
        cls.user_to_retire = UserFactory(username=cls.original_username)

        # Create some licenses associated with the user being retired
        cls.revoked_license = cls._create_associated_license(constants.REVOKED)
        cls.assigned_license = cls._create_associated_license(constants.ASSIGNED)
        cls.activated_license = cls._create_associated_license(constants.ACTIVATED)

    @classmethod
    def _create_associated_license(cls, status):
        """
        Helper to create a license of the given status associated with the user being retired.
        """
        _license = LicenseFactory.create(
            status=status,
            lms_user_id=cls.lms_user_id,
            user_email=cls.user_email,
        )
        SubscriptionLicenseSourceFactory.create(license=_license)
        return _license

    def _post_request(self, lms_user_id, original_username):
        """
        Helper to make the POST request to the license activation endpoint.

        Will update the test client's cookies to contain an lms_user_id and email,
        which can be overridden from those defined in the class ``setUpTestData()``
        method with the optional params provided here.
        """
        data = {
            'lms_user_id': lms_user_id,
            'original_username': original_username,
        }
        url = reverse('api:v1:user-retirement')
        return self.api_client.post(url, data)

    def test_retirement_no_auth(self):
        """
        Unauthenticated requests should result in a 401.
        """
        # Create a new client with no authentication present.
        self.api_client = APIClient()

        response = self._post_request(self.lms_user_id, self.original_username)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_retirement_missing_permission(self):
        """
        Requests from non-superusers that aren't the retirement worker should result in a 403.
        """
        user = UserFactory()
        self.api_client = APIClient()
        self.api_client.force_authenticate(user=user)

        response = self._post_request(self.lms_user_id, self.original_username)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @ddt.data(
        {'lms_user_id': None, 'original_username': None},
        {'lms_user_id': 1, 'original_username': None},
        {'lms_user_id': None, 'original_username': 'edxBob'},
    )
    @ddt.unpack
    def test_retirement_missing_data(self, lms_user_id, original_username):
        """
        Requests that don't provide the lms_user_id or original_username should result in a 400.
        """
        response = self._post_request(lms_user_id, original_username)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retirement_missing_user(self):
        """
        The endpoint should 404 if we attempt to retire a user who doesn't exist in license-manager.
        """
        response = self._post_request(1000, 'fake-username')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.get_user_model')
    def test_retirement_500_error(self, mock_get_user_model):
        """
        The endpoint should log an error message if we get an unexpected error retiring the user.
        """
        exception_message = 'blah'
        mock_get_user_model.side_effect = Exception(exception_message)
        with self.assertLogs(level='ERROR') as log:
            response = self._post_request(self.lms_user_id, self.original_username)
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            message = '500 error retiring user with lms_user_id {}. Error: {}'.format(
                self.lms_user_id,
                exception_message,
            )
            assert message in log.output[0]

    def test_retirement(self):
        """
        All licenses associated with the user being retired should have pii scrubbed, and the user should be deleted.
        """
        for _license in (self.revoked_license, self.assigned_license, self.activated_license):
            assert _license.source

        # Verify the request succeeds with the correct status and logs the appropriate messages
        with self.assertLogs(level='INFO') as log:
            response = self._post_request(self.lms_user_id, self.original_username)
            assert response.status_code == status.HTTP_204_NO_CONTENT

            license_message = 'Retired 3 licenses with uuids: {} for user with lms_user_id {}'.format(
                sorted([self.revoked_license.uuid, self.assigned_license.uuid, self.activated_license.uuid]),
                self.lms_user_id,
            )
            assert license_message in ' '.join(log.output)

            user_retirement_message = 'Retiring user with id {} and lms_user_id {}'.format(
                self.user_to_retire.id,
                self.lms_user_id,
            )
            assert user_retirement_message in ' '.join(log.output)

        # Verify the revoked license was cleared correctly
        self.revoked_license.refresh_from_db()
        assert_pii_cleared(self.revoked_license)
        assert_historical_pii_cleared(self.revoked_license)
        assert self.revoked_license.status == constants.REVOKED

        # Verify the assigned & activated licenses were cleared correctly
        self.assigned_license.refresh_from_db()
        assert_pii_cleared(self.assigned_license)
        assert_historical_pii_cleared(self.assigned_license)
        assert_license_fields_cleared(self.assigned_license)
        assert self.assigned_license.status == constants.UNASSIGNED

        self.activated_license.refresh_from_db()
        assert_pii_cleared(self.activated_license)
        assert_historical_pii_cleared(self.activated_license)
        assert_license_fields_cleared(self.activated_license)
        assert self.activated_license.status == constants.UNASSIGNED

        # Verify the user for retirement has been deleted
        User = get_user_model()
        with self.assertRaises(ObjectDoesNotExist):
            User.objects.get(username=self.original_username)

        # Verify license source records are deleted
        for _license in (self.revoked_license, self.assigned_license, self.activated_license):
            with self.assertRaises(SubscriptionLicenseSource.DoesNotExist):
                _license.source  # pylint: disable=pointless-statement


class StaffLicenseLookupViewTests(LicenseViewTestMixin, TestCase):
    """
    Tests for the ``StaffLicenseLookupView``.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.admin_user = UserFactory(is_staff=True)

        cls.other_subscription = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            enterprise_catalog_uuid=cls.enterprise_catalog_uuid,
            is_active=True,
            title='Other Subscription Plan',
        )

    def _post_request(self, user_email):
        """
        Helper to make the POST request to the admin license lookup endpoint.
        """
        data = {
            'user_email': user_email,
        }
        url = reverse('api:v1:staff-lookup-licenses')
        return self.api_client.post(url, data)

    def test_lookup_no_auth(self):
        """
        Unauthenticated requests should result in a 401.
        """
        # Create a new client with no authentication present.
        self.api_client = APIClient()

        response = self._post_request(self.user.email)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_lookup_missing_permission(self):
        """
        Requests from non-admin users should result in a 403.
        """
        self.api_client.force_authenticate(user=self.user)
        # Give the user an enterprise admin JWT role for good measure
        _assign_role_via_jwt_or_db(self.api_client, self.user, self.enterprise_customer_uuid, True)

        response = self._post_request(self.user.email)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_lookup_email_with_no_licenses(self):
        """
        Requests from admin users should 404 if no license for the given email exists.
        """
        self.api_client.force_authenticate(user=self.admin_user)

        response = self._post_request('NO-SUCH-EMAIL')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_lookup_post_data_missing_email_key(self):
        """
        Requests from admin users should 400 if the payload contains no ``user_email`` key.
        """
        self.api_client.force_authenticate(user=self.admin_user)

        url = reverse('api:v1:staff-lookup-licenses')
        response = self.api_client.post(url, data={'something-else': 'whatever'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_where_licenses_for_email_exist(self):
        """
        Requests from admin users should return 200/OK and some data if licenses
        for the given email exist.
        """
        self.api_client.force_authenticate(user=self.admin_user)

        first_license = self._create_license(
            assigned_date=localized_utcnow() - datetime.timedelta(days=100),
            activation_date=localized_utcnow() - datetime.timedelta(days=90),
            status=constants.ACTIVATED,
        )
        second_license = self._create_license(
            subscription_plan=self.other_subscription,
            assigned_date=localized_utcnow() - datetime.timedelta(days=120),
            activation_date=localized_utcnow() - datetime.timedelta(days=110),
            status=constants.REVOKED,
            revoked_date=localized_utcnow() - datetime.timedelta(days=105),
        )

        response = self._post_request(self.user.email)
        assert response.status_code == status.HTTP_200_OK
        self.assertCountEqual([
            {
                'activation_date': _iso_8601_format(second_license.activation_date),
                'activation_link': second_license.activation_link,
                'assigned_date': _iso_8601_format(second_license.assigned_date),
                'last_remind_date': None,
                'revoked_date': _iso_8601_format(second_license.revoked_date),
                'status': constants.REVOKED,
                'subscription_plan_expiration_date': _iso_8601_format(self.other_subscription.expiration_date),
                'subscription_plan_title': self.other_subscription.title,
            },
            {
                'activation_date': _iso_8601_format(first_license.activation_date),
                'activation_link': first_license.activation_link,
                'assigned_date': _iso_8601_format(first_license.assigned_date),
                'last_remind_date': None,
                'revoked_date': None,
                'status': constants.ACTIVATED,
                'subscription_plan_expiration_date': _iso_8601_format(
                    self.active_subscription_for_customer.expiration_date
                ),
                'subscription_plan_title': self.active_subscription_for_customer.title,
            },
        ], response.json())  # pylint: disable=no-member
