"""
Unit tests for SubscriptionPlanRenewalProvisioningAdminViewset.
"""
from datetime import timedelta
from uuid import UUID, uuid4

import ddt
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from license_manager.apps.api.v1.tests.test_views import (
    _assign_role_via_jwt_or_db,
)
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
    UserFactory,
)


@ddt.ddt
class SubscriptionPlanRenewalProvisioningAdminViewsetTests(APITestCase):
    """
    Tests for SubscriptionPlanRenewalProvisioningAdminViewset.
    """
    prior_plan_uuid = uuid4()
    renewed_plan_uuid = uuid4()
    unrelated_plan_uuid = uuid4()

    def setUp(self):
        """
        Set up test data.
        """
        super().setUp()
        self.user = UserFactory()
        self.staff_user = UserFactory(is_staff=True)
        self.enterprise_customer_uuid = uuid4()
        self.customer_agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=self.enterprise_customer_uuid
        )
        self.prior_plan = SubscriptionPlanFactory.create(
            uuid=self.prior_plan_uuid,
            customer_agreement=self.customer_agreement
        )
        self.renewed_plan = SubscriptionPlanFactory.create(
            uuid=self.renewed_plan_uuid,
            customer_agreement=self.customer_agreement
        )
        self.unrelated_plan = SubscriptionPlanFactory.create(
            uuid=self.unrelated_plan_uuid,
            customer_agreement=self.customer_agreement
        )

    def _setup_request_jwt(self, user=None):
        """
        Helper to set up JWT authentication for provisioning admin role.
        """
        if user is None:
            user = self.user
        _assign_role_via_jwt_or_db(
            self.client,
            user,
            enterprise_customer_uuid='*',
            assign_via_jwt=True,
            system_role=constants.SYSTEM_ENTERPRISE_PROVISIONING_ADMIN_ROLE,
        )

    def _get_list_url(self):
        """
        Helper to get the list URL.
        """
        return reverse('api:v1:provisioning-admins-subscription-plan-renewals-list')

    def _get_detail_url(self, renewal_id):
        """
        Helper to get the detail URL.
        """
        return reverse(
            'api:v1:provisioning-admins-subscription-plan-renewals-detail',
            kwargs={'pk': renewal_id}
        )

    def _prepare_renewal_payload(self, prior_plan=None, renewed_plan=None):
        """
        Helper to prepare a valid renewal payload.
        """
        if prior_plan is None:
            prior_plan = self.prior_plan

        now = timezone.now()
        effective_date = now + timedelta(days=30)
        renewed_expiration = effective_date + timedelta(days=365)

        payload = {
            'prior_subscription_plan': str(prior_plan.uuid),
            'salesforce_opportunity_id': '0061234567890ABCDE',
            'number_of_licenses': 100,
            'effective_date': effective_date.isoformat(),
            'renewed_expiration_date': renewed_expiration.isoformat(),
            'license_types_to_copy': constants.LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED,
        }

        if renewed_plan:
            payload['renewed_subscription_plan'] = str(renewed_plan.uuid)

        return payload

    ################
    # Create Tests #
    ################

    def test_create_renewal_success(self):
        """
        Verify that creating a renewal returns 201 and includes all expected fields.
        """
        self._setup_request_jwt()
        payload = self._prepare_renewal_payload()

        response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expected_fields = {
            'id',
            'created',
            'modified',
            'prior_subscription_plan',
            'prior_subscription_plan_title',
            'renewed_subscription_plan',
            'renewed_subscription_plan_title',
            'salesforce_opportunity_id',
            'number_of_licenses',
            'effective_date',
            'renewed_expiration_date',
            'processed',
            'processed_datetime',
            'renewed_plan_title',
            'license_types_to_copy',
            'disable_auto_apply_licenses',
            'exempt_from_batch_processing',
            'enterprise_customer_uuid',
        }
        self.assertEqual(set(response.data.keys()), expected_fields)

    def test_create_renewal_exact_match_returns_200(self):
        """
        Verify that creating a renewal with exact matching fields returns 200 and the existing record.
        """
        self._setup_request_jwt()

        # Create an existing renewal
        existing_renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            renewed_subscription_plan=self.renewed_plan,
            salesforce_opportunity_id='0061234567890ABCDE',
        )

        # Try to create the same renewal
        payload = {
            'prior_subscription_plan': str(self.prior_plan.uuid),
            'renewed_subscription_plan': str(self.renewed_plan.uuid),
            'salesforce_opportunity_id': '0061234567890ABCDE',
            'number_of_licenses': 100,
            'effective_date': (timezone.now() + timedelta(days=30)).isoformat(),
            'renewed_expiration_date': (timezone.now() + timedelta(days=395)).isoformat(),
        }

        response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], existing_renewal.id)

    @ddt.data(
        # Only the prior plan matches, but not the renewed plan. x1
        {
            'existing_renewal_prior_plan': prior_plan_uuid,
            'existing_renewal_renewed_plan': renewed_plan_uuid,
            'request_renewal_prior_plan': prior_plan_uuid,
            'request_renewal_renewed_plan': None,
        },
        # Only the prior plan matches, but not the renewed plan. x2
        {
            'existing_renewal_prior_plan': prior_plan_uuid,
            'existing_renewal_renewed_plan': None,
            'request_renewal_prior_plan': prior_plan_uuid,
            'request_renewal_renewed_plan': renewed_plan_uuid,
        },
        # Only the prior plan matches, but not the renewed plan. x3
        {
            'existing_renewal_prior_plan': prior_plan_uuid,
            'existing_renewal_renewed_plan': unrelated_plan_uuid,
            'request_renewal_prior_plan': prior_plan_uuid,
            'request_renewal_renewed_plan': renewed_plan_uuid,
        },
        # Only the renewed plan matches, but not the prior plan.
        {
            'existing_renewal_prior_plan': unrelated_plan_uuid,
            'existing_renewal_renewed_plan': renewed_plan_uuid,
            'request_renewal_prior_plan': prior_plan_uuid,
            'request_renewal_renewed_plan': renewed_plan_uuid,
        },
    )
    @ddt.unpack
    def test_create_renewal_conflict_returns_422(
        self,
        existing_renewal_prior_plan: UUID,
        existing_renewal_renewed_plan: UUID | None,
        request_renewal_prior_plan: UUID,
        request_renewal_renewed_plan: UUID | None,
    ):
        """
        Verify that creating a renewal with partial matching fields returns 422.
        """
        self._setup_request_jwt()

        # Create an existing renewal according to the test case.
        existing_renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=SubscriptionPlan.objects.get(
                uuid=existing_renewal_prior_plan,
            ) if existing_renewal_prior_plan else None,
            renewed_subscription_plan=SubscriptionPlan.objects.get(
                uuid=existing_renewal_renewed_plan,
            ) if existing_renewal_renewed_plan else None,
        )

        # Try to create a renewal with partially matching fields.
        payload = {
            'prior_subscription_plan': str(request_renewal_prior_plan),
            'renewed_subscription_plan': str(request_renewal_renewed_plan) if request_renewal_renewed_plan else None,
            'salesforce_opportunity_id': None,
            'number_of_licenses': 100,
            'effective_date': (timezone.now() + timedelta(days=30)).isoformat(),
            'renewed_expiration_date': (timezone.now() + timedelta(days=395)).isoformat(),
        }

        with self.assertLogs(level='INFO') as log_capture:
            response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        assert any('Conflicting renewal encountered' in log_line for log_line in log_capture.output)
        assert response.data['id'] == existing_renewal.id

    def test_create_renewal_without_permission_returns_403(self):
        """
        Verify that staff users without provisioning admin role cannot create renewals.
        """
        _assign_role_via_jwt_or_db(
            self.client,
            self.staff_user,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            assign_via_jwt=False,
        )

        payload = self._prepare_renewal_payload()
        response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_renewal_different_customer_agreements_fails(self):
        """
        Verify that creating a renewal with plans from different customer agreements fails.
        """
        self._setup_request_jwt()

        other_customer_agreement = CustomerAgreementFactory.create()
        other_plan = SubscriptionPlanFactory.create(
            customer_agreement=other_customer_agreement
        )

        payload = self._prepare_renewal_payload(
            prior_plan=self.prior_plan,
            renewed_plan=other_plan
        )

        response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('same customer agreement', str(response.data).lower())

    def test_create_renewal_effective_date_before_prior_start_fails(self):
        """
        Verify that effective_date before prior plan's start_date fails validation.
        """
        self._setup_request_jwt()

        future_plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            start_date=timezone.now() + timedelta(days=100),
        )

        payload = self._prepare_renewal_payload(prior_plan=future_plan)
        payload['effective_date'] = (timezone.now() + timedelta(days=50)).isoformat()

        response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('effective date', str(response.data).lower())

    def test_create_renewal_expiration_before_effective_fails(self):
        """
        Verify that renewed_expiration_date before effective_date fails validation.
        """
        self._setup_request_jwt()

        payload = self._prepare_renewal_payload()
        effective_date = timezone.now() + timedelta(days=30)
        payload['effective_date'] = effective_date.isoformat()
        payload['renewed_expiration_date'] = (effective_date - timedelta(days=1)).isoformat()

        response = self.client.post(self._get_list_url(), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expiration date', str(response.data).lower())

    def test_create_renewal_with_null_salesforce_opportunity_id(self):
        """
        Verify that creating a renewal with null salesforce_opportunity_id is allowed.
        """
        self._setup_request_jwt()

        payload = self._prepare_renewal_payload(renewed_plan=self.renewed_plan)
        payload['salesforce_opportunity_id'] = None  # This is what we are testing is allowed.

        response = self.client.post(self._get_list_url(), payload, format='json')

        # This is the main thing we are testing: we are allowed to create a renewal with a null opp id.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['salesforce_opportunity_id'])

        # Basic DB-level verification just to make sure it went through.
        renewal_id = response.data['id']
        created_renewal = SubscriptionPlanRenewal.objects.get(id=renewal_id)
        self.assertIsNone(created_renewal.salesforce_opportunity_id)
        self.assertEqual(created_renewal.prior_subscription_plan, self.prior_plan)
        self.assertEqual(created_renewal.renewed_subscription_plan, self.renewed_plan)

    ##############
    # List Tests #
    ##############

    def test_list_renewals_success(self):
        """
        Verify that listing renewals returns correct structure.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        response = self.client.get(self._get_list_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_keys = {'count', 'next', 'previous', 'results'}
        self.assertTrue(expected_keys.issubset(response.data.keys()))
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], renewal.id)

    def test_list_renewals_without_permission_returns_403(self):
        """
        Verify that staff users without provisioning admin role cannot list renewals.
        """
        _assign_role_via_jwt_or_db(
            self.client,
            self.staff_user,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            assign_via_jwt=False,
        )

        response = self.client.get(self._get_list_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_renewals_with_filter(self):
        """
        Verify that list endpoint supports filtering by prior_subscription_plan.
        """
        self._setup_request_jwt()

        other_plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement
        )
        renewal_1 = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )
        # Create a 2nd renewal which should not be included in response.
        SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=other_plan
        )

        url = f'{self._get_list_url()}?prior_subscription_plan={self.prior_plan.uuid}'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], renewal_1.id)

    ##################
    # Retrieve Tests #
    ##################

    def test_retrieve_renewal_success(self):
        """
        Verify that retrieving a single renewal returns the correct record.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        response = self.client.get(self._get_detail_url(renewal.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], renewal.id)

    def test_retrieve_renewal_not_found_returns_404(self):
        """
        Verify that retrieving a non-existent renewal returns 404.
        """
        self._setup_request_jwt()

        response = self.client.get(self._get_detail_url(99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_renewal_without_permission_returns_403(self):
        """
        Verify that staff users without provisioning admin role cannot retrieve renewals.
        """
        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        _assign_role_via_jwt_or_db(
            self.client,
            self.staff_user,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            assign_via_jwt=False,
        )

        response = self.client.get(self._get_detail_url(renewal.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    ################
    # Update Tests #
    ################

    def test_update_renewal_success(self):
        """
        Verify that updating a renewal (PUT) succeeds.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            number_of_licenses=100,
        )

        update_data = {'number_of_licenses': 200}
        response = self.client.put(
            self._get_detail_url(renewal.id),
            update_data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['number_of_licenses'], 200)

    def test_partial_update_renewal_success(self):
        """
        Verify that partially updating a renewal (PATCH) succeeds.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            disable_auto_apply_licenses=False,
        )

        update_data = {'disable_auto_apply_licenses': True}
        response = self.client.patch(
            self._get_detail_url(renewal.id),
            update_data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['disable_auto_apply_licenses'], True)

    def test_update_renewal_without_permission_returns_403(self):
        """
        Verify that staff users without provisioning admin role cannot update renewals.
        """
        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        _assign_role_via_jwt_or_db(
            self.client,
            self.staff_user,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            assign_via_jwt=False,
        )

        update_data = {'number_of_licenses': 200}
        response = self.client.put(
            self._get_detail_url(renewal.id),
            update_data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_non_updatable_field_returns_400(self):
        """
        Verify that attempting to update non-updatable fields returns 400.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        another_plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement
        )

        # Try to update prior_subscription_plan, which is not updatable
        update_data = {'prior_subscription_plan': str(another_plan.uuid)}
        response = self.client.patch(
            self._get_detail_url(renewal.id),
            update_data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not updatable', str(response.data).lower())

    def test_update_renewed_plan_different_customer_fails(self):
        """
        Verify that updating renewed_subscription_plan to a different customer fails.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        other_customer_agreement = CustomerAgreementFactory.create()
        other_plan = SubscriptionPlanFactory.create(
            customer_agreement=other_customer_agreement
        )

        update_data = {'renewed_subscription_plan': str(other_plan.uuid)}
        response = self.client.patch(
            self._get_detail_url(renewal.id),
            update_data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('same customer agreement', str(response.data).lower())

    ################
    # Delete Tests #
    ################

    def test_delete_renewal_success(self):
        """
        Verify that deleting a renewal succeeds.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        response = self.client.delete(self._get_detail_url(renewal.id))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            SubscriptionPlanRenewal.objects.filter(id=renewal.id).exists()
        )

    def test_delete_renewal_without_permission_returns_403(self):
        """
        Verify that staff users without provisioning admin role cannot delete renewals.
        """
        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan
        )

        _assign_role_via_jwt_or_db(
            self.client,
            self.staff_user,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            assign_via_jwt=False,
        )

        response = self.client.delete(self._get_detail_url(renewal.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_non_existent_renewal_returns_404(self):
        """
        Verify that deleting a non-existent renewal returns 404.
        """
        self._setup_request_jwt()

        response = self.client.delete(self._get_detail_url(99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    ##################
    # Process Tests #
    ##################

    def test_process_renewal_success(self):
        """
        Verify that processing a renewal succeeds and marks it as processed.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            number_of_licenses=50,
            processed=False,
        )

        # Create some licenses in the prior plan to be copied
        LicenseFactory.create_batch(
            3,
            subscription_plan=self.prior_plan,
            status=constants.ACTIVATED
        )

        response = self.client.post(
            self._get_process_url(renewal.id),
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify renewal is now processed
        renewal.refresh_from_db()
        self.assertTrue(renewal.processed)
        self.assertIsNotNone(renewal.processed_datetime)

        # Verify renewed subscription plan was created
        self.assertIsNotNone(renewal.renewed_subscription_plan)

    def test_process_already_processed_renewal_returns_200(self):
        """
        Verify that processing an already processed renewal returns 200.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            processed=True,
        )

        response = self.client.post(
            self._get_process_url(renewal.id),
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(renewal.processed)

    def test_process_renewal_without_permission_returns_403(self):
        """
        Verify that staff users without provisioning admin role cannot process renewals.
        """
        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            processed=False,
        )

        _assign_role_via_jwt_or_db(
            self.client,
            self.staff_user,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            assign_via_jwt=False,
        )

        response = self.client.post(
            self._get_process_url(renewal.id),
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_process_non_existent_renewal_returns_404(self):
        """
        Verify that processing a non-existent renewal returns 404.
        """
        self._setup_request_jwt()

        response = self.client.post(
            self._get_process_url(99999),
            format='json'
        )

        self.assertIn('No SubscriptionPlanRenewal matches the given query.', str(response.data['detail']))

    def test_process_renewal_processing_error_returns_500(self):
        """
        Verify that RenewalProcessingError returns 500.
        """
        self._setup_request_jwt()

        renewal = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.prior_plan,
            number_of_licenses=0,  # This will cause a processing error
            processed=False,
        )

        LicenseFactory.create_batch(
            5,
            subscription_plan=self.prior_plan,
            status=constants.ACTIVATED
        )

        response = self.client.post(
            self._get_process_url(renewal.id),
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('Cannot renew for fewer than the number of original activated licenses', response.data['error'])

    def _get_process_url(self, renewal_id):
        """
        Helper method to get the process URL for a renewal.
        """
        return reverse(
            'api:v1:provisioning-admins-subscription-plan-renewals-process',
            kwargs={'pk': renewal_id}
        )
