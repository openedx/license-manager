"""
Tests for the license-manager API utility functions
"""
import logging
from unittest import mock
from uuid import uuid4

import pytest
from django.test import TestCase

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
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


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
        missing_subscriptions, licensed_enrollment_info = utils.check_missing_licenses(
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
        missing_subscriptions, licensed_enrollment_info = utils.check_missing_licenses(
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


class FileUploadTests(TestCase):
    def test_get_short_file_name(self):
        file_name = "BulkEnroll-Results.csv"
        object_name = "pathA/pathB/BulkEnroll-Results.csv"
        full_path_file_name = "/pathA/pathB/BulkEnroll-Results.csv"

        assert utils._get_short_file_name(file_name) == file_name
        assert utils._get_short_file_name(object_name) == file_name
        assert utils._get_short_file_name(full_path_file_name) == file_name
