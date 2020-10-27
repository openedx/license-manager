# pylint: disable=redefined-outer-name
"""
Tests for the Subscription and License V1 API view sets.
"""
import datetime
from unittest import mock
from uuid import uuid4

import ddt
import factory
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ObjectDoesNotExist
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get as get_model_fixture
from edx_rest_framework_extensions.auth.jwt.cookies import jwt_cookie_name
from edx_rest_framework_extensions.auth.jwt.tests.utils import (
    generate_jwt_token,
    generate_unversioned_payload,
)
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionsFeatureRole,
    SubscriptionsRoleAssignment,
)
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
    UserFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    assert_date_fields_correct,
    assert_historical_pii_cleared,
    assert_license_fields_cleared,
    assert_pii_cleared,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


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


def _subscriptions_list_request(api_client, user, enterprise_customer_uuid=None):
    """
    Helper method that requests a list of subscriptions entities for a given enterprise_customer_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:subscriptions-list')
    if enterprise_customer_uuid is not None:
        url += f'?enterprise_customer_uuid={enterprise_customer_uuid}'
    return api_client.get(url)


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
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:subscriptions-detail', kwargs={'subscription_uuid': subscription_uuid})
    return api_client.get(url)


def _licenses_list_request(api_client, subscription_uuid, page_size=None):
    """
    Helper method that requests a list of licenses for a given subscription_uuid.
    """
    url = reverse('api:v1:licenses-list', kwargs={'subscription_uuid': subscription_uuid})
    if page_size:
        url += f'?page_size={page_size}'
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


def _learner_license_detail_request(api_client, subscription_uuid):
    """
    Helper method that requests a list of active subscriptions entities for a given enterprise_customer_uuid.
    """
    url = reverse('api:v1:license-list', kwargs={
        'subscription_uuid': subscription_uuid,
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
    assert response['start_date'] == _get_date_string(subscription.start_date)
    assert response['expiration_date'] == _get_date_string(subscription.expiration_date)
    assert response['enterprise_catalog_uuid'] == str(subscription.enterprise_catalog_uuid)
    assert response['is_active'] == subscription.is_active
    assert response['licenses'] == {
        'total': subscription.num_licenses,
        'allocated': subscription.num_allocated_licenses,
    }
    assert response['days_until_expiration'] == (subscription.expiration_date - datetime.date.today()).days


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
def test_license_list_unauthenticated_user_401(api_client):
    """
    Verify that unauthenticated users receive a 401 from the license list endpoint.
    """
    response = _licenses_list_request(api_client, uuid4())
    assert status.HTTP_401_UNAUTHORIZED == response.status_code


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
    first_subscription, second_subscription = _create_subscription_plans(enterprise_customer_uuid)
    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_list_request(api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 2

    _assert_subscription_response_correct(results_by_uuid[str(first_subscription.uuid)], first_subscription)
    _assert_subscription_response_correct(results_by_uuid[str(second_subscription.uuid)], second_subscription)


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
def test_non_staff_user_learner_subscriptions_endpoint(api_client, non_staff_user):
    """
    Verify that an enterprise learner can view the active subscriptions their enterprise has
    """
    enterprise_customer_uuid = uuid4()
    active_subscriptions = SubscriptionPlanFactory.create_batch(
        2,
        enterprise_customer_uuid=enterprise_customer_uuid,
        is_active=True
    )
    inactive_subscriptions = SubscriptionPlanFactory.create_batch(
        2,
        enterprise_customer_uuid=enterprise_customer_uuid,
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
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    unassigned_licenses = LicenseFactory.create_batch(3)
    assigned_licenses = LicenseFactory.create_batch(5, status=constants.ASSIGNED)
    subscription.licenses.set(unassigned_licenses + assigned_licenses)

    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_detail_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_subscription_response_correct(response.data, subscription)


@pytest.mark.django_db
def test_license_list_staff_user_200(api_client, staff_user, boolean_toggle):
    subscription, assigned_license, unassigned_license = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, boolean_toggle)

    response = _licenses_list_request(api_client, subscription.uuid)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 2
    _assert_license_response_correct(results_by_uuid[str(unassigned_license.uuid)], unassigned_license)
    _assert_license_response_correct(results_by_uuid[str(assigned_license.uuid)], assigned_license)


@pytest.mark.django_db
def test_license_list_staff_user_200_custom_page_size(api_client, staff_user):
    subscription, _, _ = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, True)

    response = _licenses_list_request(api_client, subscription.uuid, page_size=1)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    # We test for content in the test above, we're just worried about the number of pages here
    assert len(results_by_uuid) == 1
    assert 2 == response.data['count']
    assert response.data['next'] is not None


@pytest.mark.django_db
def test_license_detail_staff_user_200(api_client, staff_user, boolean_toggle):
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    subscription_license = LicenseFactory.create()
    subscription.licenses.set([subscription_license])

    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, boolean_toggle)

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
    Helper method to return a SubscriptionPlan, an unassigned license, and an assigned license.
    """
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    unassigned_license = LicenseFactory.create()
    assigned_license = LicenseFactory.create(status=constants.ASSIGNED, user_email='fake@fake.com')
    subscription.licenses.set([unassigned_license, assigned_license])

    return subscription, assigned_license, unassigned_license


def _create_subscription_plans(enterprise_customer_uuid):
    """
    Helper method to create several plans.  Returns the plans.
    """
    first_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Associate some unassigned and assigned licenses to the first subscription
    unassigned_licenses = LicenseFactory.create_batch(5)
    assigned_licenses = LicenseFactory.create_batch(2, status=constants.ASSIGNED)
    first_subscription.licenses.set(unassigned_licenses + assigned_licenses)
    # Create one more subscription for the enterprise with no licenses
    second_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Create another subscription not associated with the enterprise that shouldn't show up
    SubscriptionPlanFactory.create()
    return first_subscription, second_subscription


@ddt.ddt
class LicenseViewSetActionTests(TestCase):
    """
    Tests for special actions on the LicenseViewSet.
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
        cls.test_email = 'test@example.com'
        cls.greeting = 'Hello'
        cls.closing = 'Goodbye'

        # Routes setup
        cls.subscription_plan = SubscriptionPlanFactory()
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

        cls.revoke_license_url = reverse(
            'api:v1:licenses-revoke',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )

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

    def _assert_licenses_assigned(self, user_emails):
        """
        Helper that verifies that there is an assigned license associated with each email in `user_emails`.
        """
        for email in user_emails:
            user_license = self.subscription_plan.licenses.get(user_email=email)
            assert user_license.status == constants.ASSIGNED

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

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_no_emails(self, mock_activation_task):
        """
        Verify the assign endpoint returns a 400 if no user emails are provided.
        """
        response = self.api_client.post(self.assign_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_activation_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    @ddt.data(True, False)
    def test_assign_non_admin_user(self, user_is_staff, mock_activation_task):
        """
        Verify the assign endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self._test_and_assert_forbidden_user(self.assign_url, user_is_staff, mock_activation_task)

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_empty_emails(self, mock_activation_task):
        """
        Verify the assign endpoint returns a 400 if the list of emails provided is empty.
        """
        response = self.api_client.post(self.assign_url, {'user_emails': []})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_activation_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_invalid_emails(self, mock_activation_task):
        """
        Verify the assign endpoint returns a 400 if the list contains an invalid email.
        """
        response = self.api_client.post(self.assign_url, {'user_emails': ['lkajsdf']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_activation_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_insufficient_licenses(self, mock_activation_task):
        """
        Verify the assign endpoint returns a 400 if there are not enough unassigned licenses to assign to.
        """
        # Create some assigned licenses which will not factor into the count
        assigned_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set(assigned_licenses)
        response = self.api_client.post(self.assign_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_activation_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_insufficient_licenses_revoked(self, mock_activation_task):
        """
        Verify the endpoint returns a 400 if there are not enough licenses to assign to considering revoked licenses
        """
        # Create a revoked license that is not being assigned to
        revoked_license = LicenseFactory.create(status=constants.REVOKED, user_email='revoked@example.com')
        self.subscription_plan.licenses.set([revoked_license])
        response = self.api_client.post(self.assign_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_activation_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_already_associated_email(self, mock_activation_task):
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
        mock_activation_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            ['unassigned@example.com'],
            str(self.subscription_plan.uuid),
        )

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    @ddt.data(True, False)
    def test_assign(self, use_superuser, mock_activation_task):
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
        task_args, _ = mock_activation_task.call_args
        actual_template_text, actual_emails, actual_subscription_uuid = task_args
        assert ['bb8@mit.edu', self.test_email] == sorted(actual_emails)
        assert str(self.subscription_plan.uuid) == actual_subscription_uuid
        assert self.greeting == actual_template_text['greeting']
        assert self.closing == actual_template_text['closing']

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_dedupe_input(self, mock_activation_task):
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
        mock_activation_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            [self.test_email],
            str(self.subscription_plan.uuid),
        )

    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_to_revoked_user(self, mock_activation_task):
        """
        Verify that the assign endpoint allows assigning a license to a user who previously had a license revoked.
        """
        revoked_license = LicenseFactory.create(
            user_email=self.test_email,
            status=constants.REVOKED,
            lms_user_id=1,
            last_remind_date=localized_utcnow(),
            activation_date=localized_utcnow(),
            assigned_date=localized_utcnow(),
            revoked_date=localized_utcnow(),
        )
        original_activation_key = revoked_license.activation_key
        self.subscription_plan.licenses.set([revoked_license])

        response = self.api_client.post(self.assign_url, {'user_emails': [self.test_email]})
        assert response.status_code == status.HTTP_200_OK

        # Verify all the attributes on the formerly revoked license are correct
        revoked_license.refresh_from_db()
        self._assert_licenses_assigned([self.test_email])
        assert_license_fields_cleared(revoked_license)
        # Verify the activation key has been switched
        assert revoked_license.activation_key is not original_activation_key
        mock_activation_task.assert_called_with(
            {'greeting': '', 'closing': ''},
            [self.test_email],
            str(self.subscription_plan.uuid),
        )

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if no email is provided.
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
    def test_remind_invalid_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if an invalid email is provided.
        """
        response = self.api_client.post(self.remind_url, {'user_email': 'lkajsf'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_blank_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if an empty string is submitted for an email.
        """
        response = self.api_client.post(self.remind_url, {'user_email': ''})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_license_for_user(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 404 if there is no license associated with the given email.
        """
        response = self.api_client.post(self.remind_url, {'user_email': 'nolicense@example.com'})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_pending_license_for_user(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 404 if there is no pending license associated with the given email.
        """
        activated_license = LicenseFactory.create(user_email=self.test_email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([activated_license])

        response = self.api_client.post(self.remind_url, {'user_email': self.test_email})
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
        self.subscription_plan.licenses.set([pending_license])

        response = self.api_client.post(
            self.remind_url,
            {'user_email': self.test_email, 'greeting': self.greeting, 'closing': self.closing},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_send_reminder_emails_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            [self.test_email],
            str(self.subscription_plan.uuid),
        )

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

        response = self.api_client.post(self.remind_all_url, {'greeting': self.greeting, 'closing': self.closing})
        assert response.status_code == status.HTTP_200_OK

        # Verify emails sent to only the pending licenses
        mock_send_reminder_emails_task.assert_called_with(
            {'greeting': self.greeting, 'closing': self.closing},
            [license.user_email for license in pending_licenses],
            str(self.subscription_plan.uuid),
        )

    def test_license_overview(self):
        """
        Verify that the overview endpoint for the state of all licenses in the subscription returns correctly
        """
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        pending_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        revoked_licenses = LicenseFactory.create_batch(1, status=constants.REVOKED)
        self.subscription_plan.licenses.set(unassigned_licenses + pending_licenses + revoked_licenses)

        response = self.api_client.get(self.license_overview_url)
        assert response.status_code == status.HTTP_200_OK

        expected_response = [
            {'status': constants.UNASSIGNED, 'count': len(unassigned_licenses)},
            {'status': constants.ASSIGNED, 'count': len(pending_licenses)},
            {'status': constants.REVOKED, 'count': len(revoked_licenses)},
        ]
        actual_response = response.data
        assert expected_response == actual_response

    @ddt.data(
        {
            'license_state': constants.ACTIVATED,
            'expected_status': status.HTTP_204_NO_CONTENT,
            'use_superuser': True,
            'revoked_date_should_update': True,
            'should_reach_revocation_cap': True,
        },
        {
            'license_state': constants.ACTIVATED,
            'expected_status': status.HTTP_204_NO_CONTENT,
            'use_superuser': False,
            'revoked_date_should_update': True,
            'should_reach_revocation_cap': False,
        },
        {
            'license_state': constants.ASSIGNED,
            'expected_status': status.HTTP_204_NO_CONTENT,
            'use_superuser': True,
            'revoked_date_should_update': True,
            'should_reach_revocation_cap': False,
        },
        {
            'license_state': constants.ASSIGNED,
            'expected_status': status.HTTP_204_NO_CONTENT,
            'use_superuser': False,
            'revoked_date_should_update': True,
            'should_reach_revocation_cap': False,
        },
        {
            'license_state': constants.REVOKED,
            'expected_status': status.HTTP_404_NOT_FOUND,
            'use_superuser': True,
            'revoked_date_should_update': False,
            'should_reach_revocation_cap': False,
        },
        {
            'license_state': constants.REVOKED,
            'expected_status': status.HTTP_404_NOT_FOUND,
            'use_superuser': False,
            'revoked_date_should_update': False,
            'should_reach_revocation_cap': False,
        },
        {
            'license_state': constants.ACTIVATED,
            'expected_status': status.HTTP_400_BAD_REQUEST,
            'use_superuser': False,
            'revoked_date_should_update': False,
            'should_reach_revocation_cap': False,
        },
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.subscriptions.api.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.subscriptions.api.send_revocation_cap_notification_email_task.delay')
    def test_revoke_license_states(
        self,
        mock_send_revocation_cap_notification_email_task,
        mock_revoke_course_enrollments_for_user_task,
        license_state,
        expected_status,
        use_superuser,
        revoked_date_should_update,
        should_reach_revocation_cap,
    ):
        """
        Test that revoking a license behaves correctly for different initial license states
        """
        self._setup_request_jwt(user=self.super_user if use_superuser else self.user)
        original_license = LicenseFactory.create(user_email=self.test_email, status=license_state)
        self.subscription_plan.licenses.set([original_license])

        # Force a license revocation limit reached error
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.subscription_plan.revoke_max_percentage = 0
            self.subscription_plan.save()
        elif not should_reach_revocation_cap:
            # Only one revoke is allowed by default on self.subscription_plan, so
            # if we don't want to reach the revocation cap, more licenses must be added.
            LicenseFactory.create_batch(
                15,
                user_email=factory.Faker('email'),
                status=license_state,
                subscription_plan=self.subscription_plan,
            )
            self.subscription_plan.revoke_max_percentage = 50
            self.subscription_plan.save()

        response = self.api_client.post(self.revoke_license_url, {'user_email': self.test_email})
        assert response.status_code == expected_status
        revoked_license = self.subscription_plan.licenses.get(uuid=original_license.uuid)
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert revoked_license.status == constants.ACTIVATED
        else:
            assert revoked_license.status == constants.REVOKED

        if license_state == constants.ACTIVATED and expected_status != status.HTTP_400_BAD_REQUEST:
            mock_revoke_course_enrollments_for_user_task.assert_called()

            if should_reach_revocation_cap:
                mock_send_revocation_cap_notification_email_task.assert_called_with(
                    subscription_uuid=self.subscription_plan.uuid,
                )
            else:
                mock_send_revocation_cap_notification_email_task.assert_not_called()
        else:
            mock_revoke_course_enrollments_for_user_task.assert_not_called()
            mock_send_revocation_cap_notification_email_task.assert_not_called()

        # Verify the revoked date is updated if the license was revoked
        assert_date_fields_correct([revoked_license], ['revoked_date'], revoked_date_should_update)

    def test_revoke_no_license(self):
        """
        Tests revoking a license when the user doesn't have a license
        """
        response = self.api_client.post(self.revoke_license_url, {'user_email': self.test_email})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @ddt.data(True, False)
    def test_revoke_non_admin_user(self, user_is_staff):
        """
        Verify the revoke endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self.user.is_staff = user_is_staff
        completely_different_customer_uuid = uuid4()
        self._setup_request_jwt(enterprise_customer_uuid=completely_different_customer_uuid)
        response = self.api_client.post(self.revoke_license_url, {'user_email': 'foo@bar.com'})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @mock.patch('license_manager.apps.subscriptions.api.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.subscriptions.api.send_revocation_cap_notification_email_task.delay')
    @mock.patch('license_manager.apps.api.v1.views.activation_task.delay')
    def test_assign_after_license_revoke(
        self,
        mock_activation_task,
        mock_send_revocation_cap_notification_email_task,
        mock_revoke_course_enrollments_for_user_task,
    ):
        """
        Verifies that assigning a license after revoking one works
        """
        original_license = LicenseFactory.create(user_email=self.test_email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([original_license])
        response = self.api_client.post(self.revoke_license_url, {'user_email': self.test_email})
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_revoke_course_enrollments_for_user_task.assert_called()
        mock_send_revocation_cap_notification_email_task.assert_called_with(
            subscription_uuid=self.subscription_plan.uuid,
        )

        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', self.test_email]
        response = self.api_client.post(
            self.assign_url,
            {'greeting': self.greeting, 'closing': self.closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned(user_emails)

        # Verify the activation email task was called with the correct args
        task_args, _ = mock_activation_task.call_args
        actual_template_text, actual_emails, actual_subscription_uuid = task_args
        assert ['bb8@mit.edu', self.test_email] == sorted(actual_emails)
        assert str(self.subscription_plan.uuid) == actual_subscription_uuid
        assert self.greeting == actual_template_text['greeting']
        assert self.closing == actual_template_text['closing']

    @mock.patch('license_manager.apps.subscriptions.api.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.subscriptions.api.send_revocation_cap_notification_email_task.delay')
    def test_revoke_total_and_allocated_count(
        self,
        mock_send_revocation_cap_notification_email_task,
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
        }

        # Revoke the activated license and verify the counts change appropriately
        revoke_response = self.api_client.post(self.revoke_license_url, {'user_email': self.test_email})
        assert revoke_response.status_code == status.HTTP_204_NO_CONTENT
        mock_revoke_course_enrollments_for_user_task.assert_called()
        mock_send_revocation_cap_notification_email_task.assert_called_with(
            subscription_uuid=self.subscription_plan.uuid,
        )
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
        cls.enterprise_customer_uuid = uuid4()
        cls.enterprise_catalog_uuid = uuid4()
        cls.course_key = 'testX'
        cls.lms_user_id = 1

        cls.active_subscription_for_customer = SubscriptionPlanFactory.create(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
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
        SubscriptionPlanFactory.create(enterprise_customer_uuid=other_enterprise_uuid, is_active=True)
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
    def test_get_subsidy_no_jwt(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 400 if the user_id could not be found in the JWT.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = {}
        url = self._get_url_with_params()
        response = self.api_client.get(url)

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert '`user_id` is required and could not be found in your jwt' in str(response.content)

    def test_get_subsidy_no_subscription_for_customer(self):
        """
        Verify the view returns a 404 if there is no subscription plan for the customer.
        """
        self._assign_learner_roles()
        # Pass in some random enterprise_customer_uuid that doesn't have a subscripttion
        url = self._get_url_with_params(enterprise_customer_override=uuid4())
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy_no_active_subscription_for_customer(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 404 if there is no active subscription plan for the customer.
        """
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        other_enterprise_uuid = uuid4()
        SubscriptionPlanFactory.create(enterprise_customer_uuid=other_enterprise_uuid, is_active=False)
        self._assign_learner_roles(alternate_customer=other_enterprise_uuid)
        url = self._get_url_with_params(enterprise_customer_override=other_enterprise_uuid)
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy_no_license_for_user(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 404 if the subscription has no license for the user.
        """
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

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy_course_not_in_catalog(self, mock_get_decoded_jwt, mock_subscription_contains_content):
        """
        Verify the view returns a 404 if the subscription's catalog does not contain the given course.
        """
        self._assign_learner_roles()
        # Mock that the content was not found in the subscription's catalog
        mock_subscription_contains_content.return_value = False
        mock_get_decoded_jwt.return_value = self._decoded_jwt

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_subscription_contains_content.assert_called_with([self.course_key])

    def _assert_correct_subsidy_response(self, response):
        """
        Verifies the license subsidy endpoint returns the correct response.
        """
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            'discount_type': constants.PERCENTAGE_DISCOUNT_TYPE,
            'discount_value': constants.LICENSE_DISCOUNT_VALUE,
            'status': constants.ACTIVATED,
            'subsidy_id': str(self.activated_license.uuid),
            'start_date': str(self.active_subscription_for_customer.start_date),
            'expiration_date': str(self.active_subscription_for_customer.expiration_date),
        }

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_get_subsidy(self, mock_get_decoded_jwt, mock_subscription_contains_content):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        self._assign_learner_roles()
        # Mock that the content was found in the subscription's catalog
        mock_subscription_contains_content.return_value = True
        mock_get_decoded_jwt.return_value = self._decoded_jwt

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        self._assert_correct_subsidy_response(response)
        mock_subscription_contains_content.assert_called_with([self.course_key])


class LicenseActivationViewTests(LicenseViewTestMixin, TestCase):
    """
    Tests for the license activation view.
    """
    NOW = localized_utcnow()
    ACTIVATION_KEY = uuid4()

    def tearDown(self):
        """
        Deletes all licenses after each test method is run.
        """
        super().tearDown()

        License.objects.all().delete()

    def _post_request(self, activation_key):
        """
        Helper to make the POST request to the license activation endpoint.

        Will update the test client's cookies to contain an lms_user_id and email,
        which can be overridden from those defined in the class ``setUpTestData()``
        method with the optional params provided here.
        """
        query_params = QueryDict(mutable=True)
        query_params['activation_key'] = str(activation_key)
        url = reverse('api:v1:license-activation') + '/?' + query_params.urlencode()
        return self.api_client.post(url)

    def _create_license(self, status=constants.ASSIGNED, activation_date=None):
        """
        Helper method to create a license.
        """
        return LicenseFactory.create(
            status=status,
            lms_user_id=self.lms_user_id,
            user_email=self.user.email,
            subscription_plan=self.active_subscription_for_customer,
            activation_key=self.ACTIVATION_KEY,
            activation_date=activation_date,
        )

    def test_activation_no_auth(self):
        """
        Unauthenticated requests should result in a 401.
        """
        # Create a new client with no authentication present.
        self.api_client = APIClient()

        response = self._post_request(uuid4())

        assert status.HTTP_401_UNAUTHORIZED == response.status_code

    def test_activation_no_jwt_roles(self):
        """
        JWT Authenticated requests without the appropriate learner role should result in a 403.
        """
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            self.enterprise_customer_uuid,
            assign_via_jwt=True,
            system_role=None,
        )
        self._create_license()

        response = self._post_request(self.ACTIVATION_KEY)

        assert status.HTTP_403_FORBIDDEN == response.status_code

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_activation_no_jwt(self, mock_get_decoded_jwt):
        """
        Verify that license activation returns a 400 if the user's email could not be found in the JWT.
        """
        mock_get_decoded_jwt.return_value = {}
        response = self._post_request(str(self.ACTIVATION_KEY))

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert '`email` is required and could not be found in your jwt' in str(response.content)

    def test_activation_key_is_malformed(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
            }
        )

        response = self._post_request('deadbeef')

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert 'deadbeef is not a valid activation key' in str(response.content)

    def test_activation_key_does_not_exist(self):
        """
        When the user is authenticated and has the appropriate role,
        but no corresponding license exists for the given ``activation_key``,
        we should return a 404.
        """
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
            }
        )

        response = self._post_request(uuid4())

        assert status.HTTP_404_NOT_FOUND == response.status_code

    def test_activate_an_assigned_license(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
            }
        )
        license_to_be_activated = self._create_license()

        with freeze_time(self.NOW):
            response = self._post_request(str(self.ACTIVATION_KEY))

        assert status.HTTP_204_NO_CONTENT == response.status_code
        license_to_be_activated.refresh_from_db()
        assert constants.ACTIVATED == license_to_be_activated.status
        assert self.lms_user_id == license_to_be_activated.lms_user_id
        assert self.NOW == license_to_be_activated.activation_date

    def test_license_already_activated_returns_204(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
            }
        )
        already_activated_license = self._create_license(
            status=constants.ACTIVATED,
            activation_date=self.NOW,
        )

        response = self._post_request(str(self.ACTIVATION_KEY))

        assert status.HTTP_204_NO_CONTENT == response.status_code
        already_activated_license.refresh_from_db()
        assert constants.ACTIVATED == already_activated_license.status
        assert self.lms_user_id == already_activated_license.lms_user_id
        assert self.NOW == already_activated_license.activation_date

    def test_activating_revoked_license_returns_422(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
            }
        )
        revoked_license = self._create_license(
            status=constants.REVOKED,
            activation_date=self.NOW,
        )

        response = self._post_request(str(self.ACTIVATION_KEY))

        assert status.HTTP_422_UNPROCESSABLE_ENTITY == response.status_code
        revoked_license.refresh_from_db()
        assert constants.REVOKED == revoked_license.status
        assert self.lms_user_id == revoked_license.lms_user_id
        assert self.NOW == revoked_license.activation_date


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
        return LicenseFactory.create(
            status=status,
            lms_user_id=cls.lms_user_id,
            user_email=cls.user_email,
        )

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
        # Verify the request succeeds with the correct status and logs the appropriate messages
        with self.assertLogs(level='INFO') as log:
            response = self._post_request(self.lms_user_id, self.original_username)
            assert response.status_code == status.HTTP_204_NO_CONTENT

            license_message = 'Retired 3 licenses with uuids: {} for user with lms_user_id {}'.format(
                sorted([self.revoked_license.uuid, self.assigned_license.uuid, self.activated_license.uuid]),
                self.lms_user_id,
            )
            assert license_message in log.output[0]

            user_retirement_message = 'Retiring user with id {} and lms_user_id {}'.format(
                self.user_to_retire.id,
                self.lms_user_id,
            )
            assert user_retirement_message in log.output[1]

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
