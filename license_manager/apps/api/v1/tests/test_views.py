# pylint: disable=redefined-outer-name
"""
Tests for the Subscription and License V1 API view sets.
"""
from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from django_dynamic_fixture import get as get_model_fixture
from rest_framework import status
from rest_framework.test import APIClient

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions.constants import ASSIGNED
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)


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


def _subscriptions_list_request(api_client, user, enterprise_customer_uuid=None):
    """
    Helper method that requests a list of subscriptions entities for a given enterprise_customer_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:subscriptions-list')
    if enterprise_customer_uuid is not None:
        url += '?enterprise_customer_uuid={uuid}'.format(uuid=enterprise_customer_uuid)
    return api_client.get(url)


def _subscriptions_detail_request(api_client, user, subscription_uuid):
    """
    Helper method that requests details for a specific subscription_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:subscriptions-detail', kwargs={'subscription_uuid': subscription_uuid})
    return api_client.get(url)


def _licenses_list_request(api_client, user, subscription_uuid):
    """
    Helper method that requests a list of licenses for a given subscription_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:licenses-list', kwargs={'subscription_uuid': subscription_uuid})
    return api_client.get(url)


def _licenses_detail_request(api_client, user, subscription_uuid, license_uuid):
    """
    Helper method that requests details for a specific license_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:licenses-detail', kwargs={
        'subscription_uuid': subscription_uuid,
        'license_uuid': license_uuid
    })
    return api_client.get(url)


def _get_date_string(date):
    """
    Helper to get the string associated with a date, or None if it doesn't exist.

    Returns:
        string or None: The string representation of the date if it exists.
    """
    if not date:
        return None
    return str(date)


def _assert_subscription_response_correct(response, subscription):
    """
    Helper for asserting that the response for a subscription matches the object's values.
    """
    assert response['enterprise_customer_uuid'] == str(subscription.enterprise_customer_uuid)
    assert response['uuid'] == str(subscription.uuid)
    assert response['purchase_date'] == _get_date_string(subscription.purchase_date)
    assert response['start_date'] == _get_date_string(subscription.start_date)
    assert response['expiration_date'] == _get_date_string(subscription.expiration_date)
    assert response['enterprise_catalog_uuid'] == str(subscription.enterprise_catalog_uuid)
    assert response['licenses'] == {
        'total': subscription.num_licenses,
        'allocated': subscription.num_allocated_licenses,
    }


def _assert_license_response_correct(response, subscription_license):
    """
    Helper for asserting that the response for a subscription_license matches the object's values.
    """
    assert response['uuid'] == str(subscription_license.uuid)
    assert response['status'] == subscription_license.status
    assert response['user_email'] == subscription_license.user_email
    assert response['activation_date'] == _get_date_string(subscription_license.activation_date)
    assert response['last_remind_date'] == _get_date_string(subscription_license.last_remind_date)


@pytest.mark.django_db
def test_subscription_plan_list_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the subscription plan list endpoint.
    """
    response = _subscriptions_list_request(api_client, AnonymousUser(), enterprise_customer_uuid=uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_retrieve_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the subscription plan retrieve endpoint.
    """
    response = _subscriptions_detail_request(api_client, AnonymousUser(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_list_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the license list endpoint.
    """
    response = _licenses_list_request(api_client, AnonymousUser(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_retrieve_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the license retrieve endpoint.
    """
    response = _licenses_detail_request(api_client, AnonymousUser(), uuid4(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


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
    response = _licenses_list_request(api_client, non_staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_detail_non_staff_user_403(api_client, non_staff_user):
    response = _licenses_detail_request(api_client, non_staff_user, uuid4(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_200(api_client, staff_user):
    """
    Verify that the subscription list view for staff users gives the correct response.

    Additionally checks that the staff user only sees the subscription plans associated with the enterprise customer as
    specified by the query parameter.
    """
    enterprise_customer_uuid = uuid4()
    first_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Associate some unassigned and assigned licenses to the first subscription
    unassigned_licenses = LicenseFactory.create_batch(5)
    assigned_licenses = LicenseFactory.create_batch(2, status=ASSIGNED)
    first_subscription.licenses.set(unassigned_licenses + assigned_licenses)
    # Create one more subscription for the enterprise with no licenses
    second_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Create another subscription not associated with the enterprise that shouldn't show up
    SubscriptionPlanFactory.create()

    response = _subscriptions_list_request(api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 2
    _assert_subscription_response_correct(results[0], first_subscription)
    _assert_subscription_response_correct(results[1], second_subscription)


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
def test_subscription_plan_detail_staff_user_200(api_client, staff_user):
    """
    Verify that the subscription detail view for staff gives the correct result.
    """
    subscription = SubscriptionPlanFactory.create()
    # Associate some licenses with the subscription
    unassigned_licenses = LicenseFactory.create_batch(3)
    assigned_licenses = LicenseFactory.create_batch(5, status=ASSIGNED)
    subscription.licenses.set(unassigned_licenses + assigned_licenses)
    response = _subscriptions_detail_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_subscription_response_correct(response.data, subscription)


@pytest.mark.django_db
def test_license_list_staff_user_200(api_client, staff_user):
    subscription = SubscriptionPlanFactory.create()
    # Associate some licenses with the subscription
    unassigned_license = LicenseFactory.create()
    assigned_license = LicenseFactory.create(status=ASSIGNED, user_email='fake@fake.com')
    subscription.licenses.set([unassigned_license, assigned_license])
    response = _licenses_list_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 2
    _assert_license_response_correct(results[0], unassigned_license)
    _assert_license_response_correct(results[1], assigned_license)


@pytest.mark.django_db
def test_license_detail_staff_user_200(api_client, staff_user):
    subscription = SubscriptionPlanFactory.create()
    # Associate some licenses with the subscription
    subscription_license = LicenseFactory.create()
    subscription.licenses.set([subscription_license])
    response = _licenses_detail_request(api_client, staff_user, subscription.uuid, subscription_license.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_license_response_correct(response.data, subscription_license)
