"""
Tests for the license-manager API utility functions
"""
import logging
from unittest import mock
from uuid import uuid4

from django.test import TestCase
from edx_django_utils.cache.utils import TieredCache

from license_manager.apps.api import utils
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    UserFactory,
)


logger = logging.getLogger(__name__)


# pylint: disable=unused-argument
class CheckMissingLicenseTests(TestCase):
    """
    Tests for check_missing_licenses
    """
    def setUp(self):
        super().setUp()
        self.activated_user = UserFactory()
        self.assigned_user = UserFactory()
        self.unlicensed_user = UserFactory()
        self.enterprise_customer_uuid = uuid4()
        self.enterprise_catalog_uuid = uuid4()
        self.course_key = 'testX'

        self.customer_agreement = CustomerAgreementFactory(
            enterprise_customer_uuid=self.enterprise_customer_uuid,
        )
        self.active_subscription_for_customer = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
        )
        self.activated_license = LicenseFactory.create(
            status=constants.ACTIVATED,
            user_email=self.activated_user.email,
            subscription_plan=self.active_subscription_for_customer,
        )
        self.assigned_license = LicenseFactory.create(
            status=constants.ASSIGNED,
            user_email=self.assigned_user.email,
            subscription_plan=self.active_subscription_for_customer,
        )

    def tearDown(self):
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()
        CustomerAgreement.objects.all().delete()

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    def test_assigned(self, mock_contains_content):
        _, licensed_enrollment_info = utils.check_missing_licenses(
            self.customer_agreement,
            [self.assigned_user.email],
            [self.course_key],
            self.active_subscription_for_customer.uuid
        )
        assert licensed_enrollment_info[0]['license_uuid'] == str(self.assigned_license.uuid)
        assert licensed_enrollment_info[0]['email'] == self.assigned_license.user_email
        assert licensed_enrollment_info[0]['activation_link'] is not None
        assert str(self.assigned_license.activation_key) in licensed_enrollment_info[0]['activation_link']

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    def test_active(self, mock_contains_content):
        _, licensed_enrollment_info = utils.check_missing_licenses(
            self.customer_agreement,
            [self.activated_user.email],
            [self.course_key],
            self.active_subscription_for_customer.uuid
        )
        assert licensed_enrollment_info[0]['license_uuid'] == str(self.activated_license.uuid)
        assert licensed_enrollment_info[0]['email'] == self.activated_license.user_email
        assert licensed_enrollment_info[0].get('activation_link') is None

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    def test_missing(self, mock_contains_content):
        missing_subscriptions, licensed_enrollment_info = utils.check_missing_licenses(
            self.customer_agreement,
            [self.unlicensed_user.email],
            [self.course_key],
            self.active_subscription_for_customer.uuid
        )
        assert len(licensed_enrollment_info) == 0
        assert missing_subscriptions.get(self.unlicensed_user.email) is not None


# pylint: disable=protected-access
class FileUploadTests(TestCase):
    def test_get_short_file_name(self):
        file_name = "BulkEnroll-Results.csv"
        object_name = "pathA/pathB/BulkEnroll-Results.csv"
        full_path_file_name = "/pathA/pathB/BulkEnroll-Results.csv"

        assert utils._get_short_file_name(file_name) == file_name
        assert utils._get_short_file_name(object_name) == file_name
        assert utils._get_short_file_name(full_path_file_name) == file_name


class PlanLockTests(TestCase):
    """
    Tests for acquiring and releasing plan-level locks.
    """
    def setUp(self):
        super().setUp()
        self.enterprise_customer_uuid = uuid4()
        self.enterprise_catalog_uuid = uuid4()
        self.customer_agreement = CustomerAgreementFactory(
            enterprise_customer_uuid=self.enterprise_customer_uuid,
        )
        self.plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
        )

    def tearDown(self):
        """
        Ensures there are no unexpected locks sitting in the cache
        between sequential test runs.
        """
        super().tearDown()
        TieredCache.dangerous_clear_all_tiers()

    def test_lock_available(self):
        lock_acquired = utils.acquire_subscription_plan_lock(self.plan)
        assert lock_acquired

    def test_lock_unavailable(self):
        first_lock_acquired = utils.acquire_subscription_plan_lock(self.plan)
        assert first_lock_acquired
        second_lock_acquired = utils.acquire_subscription_plan_lock(self.plan)
        assert second_lock_acquired is False

    def test_release_acquired_lock(self):
        utils.acquire_subscription_plan_lock(self.plan)
        released = utils.release_subscription_plan_lock(self.plan)
        assert released

    def test_release_unacquired_lock(self):
        utils.acquire_subscription_plan_lock(self.plan, other_stuff='yes')
        released = utils.release_subscription_plan_lock(self.plan)
        assert released


class TestUtils(TestCase):
    """
    Tests for license-manager utils
    """

    def test_make_swagger_var_param_optional(self):
        # Sample data structure
        result_case1 = {
            "paths": {
                "/example/path/{var}/": {
                    "get": {
                        "parameters": [
                            {
                                "name": "var",
                                "in": "path",
                                "type": "string",
                                "required": True,
                            }
                        ]
                    }
                }
            }
        }

        # Verify that the modification is as expected
        expected_result_case1 = {
            "paths": {
                "/example/path/{var}/": {
                    "get": {
                        "parameters": [
                            {
                                "name": "var",
                                "in": "path",
                                "type": "string",
                                "required": True,
                                "allowEmptyValue": True,  # This field should be added
                            }
                        ]
                    }
                }
            }
        }

        updated_result_case1 = utils.make_swagger_var_param_optional(result_case1)
        self.assertEqual(updated_result_case1, expected_result_case1)

        # Case 2: Var param exists and allowEmptyValue is already present

        updated_result_case2 = utils.make_swagger_var_param_optional(
            expected_result_case1
        )
        self.assertEqual(updated_result_case2, expected_result_case1)

        # Case 3: Var param does not exist
        result_case3 = {
            "paths": {
                "/example/path/{param}/": {
                    "get": {
                        "parameters": [
                            {
                                "name": "param",
                                "in": "path",
                                "type": "string",
                                "required": True,
                            }
                        ]
                    }
                }
            }
        }

        updated_result_case3 = utils.make_swagger_var_param_optional(result_case3)
        self.assertEqual(updated_result_case3, result_case3)  # No change expected
