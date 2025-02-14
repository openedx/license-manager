from datetime import timedelta
from unittest import mock

import ddt
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
)


@ddt.ddt
class ProcessAutoScalingCommandTests(TestCase):
    command_name = 'process_auto_scalable_plans'
    now = timezone.now()

    def tearDown(self):
        """
        Deletes all renewals, licenses, and subscription after each test method is run.
        """
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

    def setUp(self):
        """
        Sets up an auto-scaling agreement and subscription.
        """
        self.agreement = CustomerAgreementFactory.create(
            enable_auto_scaling_of_current_plan=True,
            auto_scaling_max_licenses=100,
            auto_scaling_threshold_percentage=30,
            auto_scaling_increment_percentage=50,
        )
        self.plan = SubscriptionPlanFactory.create(
            customer_agreement=self.agreement,
            start_date=self.now - timedelta(days=7),
            expiration_date=self.now + timedelta(days=7),
            is_active=True,
        )
        self.older_plan = SubscriptionPlanFactory.create(
            customer_agreement=self.agreement,
            start_date=self.now - timedelta(days=70),
            expiration_date=self.now + timedelta(days=7),
            is_active=True,
        )

    @ddt.data(False, True)
    def test_auto_scale_happy_path(self, is_dry_run):
        """
        Tests that auto-scaling is actually executed for an agreement's most recent active plan.
        """
        # Allocate licenses in the older plan; later, we'll
        # assert that we did *not* auto-scale this plan, b/c it's older.
        LicenseFactory.create_batch(
            10,
            subscription_plan=self.older_plan,
            status=constants.ASSIGNED,
        )

        # Add some unallocated licenses to the newer plan
        LicenseFactory.create_batch(
            6,
            subscription_plan=self.plan,
            status=constants.UNASSIGNED,
        )
        # Allocate 4/10 licenses, which means we're at 40% allocated, which
        # is over the threshold at which we've configured auto-scaling.
        LicenseFactory.create_batch(
            4,
            subscription_plan=self.plan,
            status=constants.ASSIGNED,
        )

        self.assertEqual(10, self.plan.num_licenses)

        for _ in range(2):
            # Given the auto-scaling parameters, the second time
            # we execute call_command(), nothing should have changed.
            args = ['--dry-run'] if is_dry_run else []
            call_command(self.command_name, *args)

            # Since we set `auto_scaling_increment_percentage` to 50%, we should have now added
            # 5 more license to the plan.
            self.assertEqual(10 if is_dry_run else 15, self.plan.num_licenses)

            # The older plan should not have had licenses added to it.
            self.assertEqual(10, self.older_plan.num_licenses)

    def test_auto_scale_hard_cap(self):
        """
        Tests that auto-scaling is actually executed for an agreement's most recent active plan,
        and that we only scale up to the hard cap allowed.
        """
        # Allocate licenses in the older plan; later, we'll
        # assert that we did *not* auto-scale this plan, b/c it's older.
        LicenseFactory.create_batch(
            10,
            subscription_plan=self.older_plan,
            status=constants.ASSIGNED,
        )

        # Add some unallocated licenses to the newer plan
        LicenseFactory.create_batch(
            5,
            subscription_plan=self.plan,
            status=constants.UNASSIGNED,
        )
        # Allocate 90 licenses, which means we're 90/95 allocated.
        LicenseFactory.create_batch(
            90,
            subscription_plan=self.plan,
            status=constants.ASSIGNED,
        )

        self.assertEqual(95, self.plan.num_licenses)

        call_command(self.command_name)

        # Since we set `auto_scaling_increment_percentage` to 50%, without a hard cap,
        # we'd allocate (95 * 0.50) ~= 42 licenses. But the hard cap is 100, so we should
        # only have created 5 more licenses to put us at 100 total.
        self.assertEqual(100, self.plan.num_licenses)

        # The older plan should not have had licenses added to it.
        self.assertEqual(10, self.older_plan.num_licenses)

    def test_plan_with_no_licenses(self):
        """
        Auto-scaling should not execute on a plan with no licenses.
        """
        self.assertEqual(0, self.plan.num_licenses)

        call_command(self.command_name)

        self.assertEqual(0, self.plan.num_licenses)
