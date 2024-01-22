"""
Tests for subscriptions app celery tasks
"""
from datetime import datetime, timedelta
from unittest import mock
from uuid import uuid4

import ddt
import freezegun
import pytest
from braze.exceptions import BrazeClientError
from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
from freezegun import freeze_time
from requests import models

from license_manager.apps.api.utils import (
    acquire_subscription_plan_lock,
    release_subscription_plan_lock,
)
from license_manager.apps.subscriptions import tasks
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)


# pylint: disable=unused-argument
@ddt.ddt
class ProvisionLicensesTaskTests(TestCase):
    """
    Tests for provision_licenses_task.
    """
    def setUp(self):
        super().setUp()
        self.subscription_plan = SubscriptionPlanFactory()

    def tearDown(self):
        super().tearDown()
        release_subscription_plan_lock(self.subscription_plan)

    # For all cases below, assume batch size of 5.
    @ddt.data(
        # Don't add licenses if none are desired.
        {
            'num_initial_licenses': 0,
            'desired_num_licenses': 0,
            'expected_num_licenses': 0,
        },
        # Create fewer licenses than one batch.
        {
            'num_initial_licenses': 0,
            'desired_num_licenses': 1,
            'expected_num_licenses': 1,
        },
        # Create licenses that span multiple batches.
        {
            'num_initial_licenses': 0,
            'desired_num_licenses': 6,
            'expected_num_licenses': 6,
        },
        # Don't add more licenses if the goal has already been reached.
        {
            'num_initial_licenses': 10,
            'desired_num_licenses': 10,
            'expected_num_licenses': 10,
        },
        # Create fewer licenses than one batch (starting with 10 initially).
        {
            'num_initial_licenses': 10,
            'desired_num_licenses': 11,
            'expected_num_licenses': 11,
        },
        # Create licenses that span multiple batches (starting with 10 initially).
        {
            'num_initial_licenses': 10,
            'desired_num_licenses': 16,
            'expected_num_licenses': 16,
        },
        # Don't remove licenses if the desired number of licenses is smaller than count of existing licenses.
        {
            'num_initial_licenses': 20,
            'desired_num_licenses': 10,
            'expected_num_licenses': 20,
        },
        # Don't add or remove licenses if the desired number of licenses is None.
        {
            'num_initial_licenses': 20,
            'desired_num_licenses': None,
            'expected_num_licenses': 20,
        },
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.subscriptions.tasks.PROVISION_LICENSES_BATCH_SIZE', 5)
    def test_provision_licenses_task(self, num_initial_licenses, desired_num_licenses, expected_num_licenses):
        """
        Test provision_licenses_task.
        """
        self.subscription_plan.desired_num_licenses = desired_num_licenses
        self.subscription_plan.save()
        self.subscription_plan.increase_num_licenses(num_initial_licenses)

        tasks.provision_licenses_task(subscription_plan_uuid=self.subscription_plan.uuid)

        assert self.subscription_plan.num_licenses == expected_num_licenses

    def test_provision_licenses_task_locked(self):
        """
        Test provision_licenses_task throws an exception if the subscription is locked.
        """
        self.subscription_plan.desired_num_licenses = 5
        self.subscription_plan.save()

        acquire_subscription_plan_lock(self.subscription_plan)

        with self.assertRaises(tasks.RequiredTaskUnreadyError):
            tasks.provision_licenses_task(subscription_plan_uuid=self.subscription_plan.uuid)

        assert self.subscription_plan.num_licenses == 0
