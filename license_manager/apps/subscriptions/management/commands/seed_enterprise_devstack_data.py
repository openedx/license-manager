"""
Management command for seeding devstack with licenses and subscriptions for development.
"""


import logging
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    PlanType,
    Product,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Management command for populating License Manager with enterprise customer agreement, subscriptions, and licenses.

    Example usage:
        $ ./manage.py seed_enterprise_devstack_data --enterprise-customer-slug "CUSTOMER-SLUG-HERE"
    """

    help = 'Seeds an enterprise customer agreement, subscription and licenses for an existing enterprise customer.'

    def add_arguments(self, parser):
        """ Adds argument(s) to the the command """
        parser.add_argument(
            '--enterprise-customer-slug',
            action='store',
            dest='enterprise_customer_slug',
            required=True,
            help='Enterprise slug of an existing enterprise customer (e.g. "test-enterprise").',
            type=str,
        )
        parser.add_argument(
            '--num-licenses',
            action='store',
            dest='num_licenses',
            default=10,
            help='Specify the number of licenses you want on this subscription. Defaults to 10.',
            type=int,
        )

    def get_enterprise_customer(self, enterprise_customer_slug):
        """ Returns an enterprise customer """
        logger.info('\nFetching an enterprise customer {} name ...'.format(enterprise_customer_slug))
        try:
            enterprise_api_client = EnterpriseApiClient()

            # Query endpoint by slug for easy dev CLI experience
            endpoint = '{}?slug={}'.format(enterprise_api_client.enterprise_customer_endpoint,
                                           str(enterprise_customer_slug))
            response = enterprise_api_client.client.get(endpoint).json()
            if response.get('count'):
                return response.get('results')[0]

            return None

        except IndexError:
            logger.error('No enterprise customer found.')
            return None

    def get_or_create_customer_agreement(self, enterprise_customer):
        """
        Gets or creates a CustomerAgreement for a customer.
        """
        logger.info('\nFetching/Creating enterprise CustomerAgreement ...')

        customer_agreement, _ = CustomerAgreement.objects.get_or_create(
            enterprise_customer_slug=enterprise_customer.get('slug'),
            defaults={
                'enterprise_customer_uuid': enterprise_customer.get('uuid'),
                'enterprise_customer_slug': enterprise_customer.get('slug'),
                'default_enterprise_catalog_uuid': enterprise_customer.get('enterprise_customer_catalogs')[0]

            }
        )

        # Data sync for running command multiple times:
        # update the uuid with the latest that matches the slug:
        customer_agreement.enterprise_customer_uuid = enterprise_customer.get('uuid')
        customer_agreement.default_enterprise_catalog_uuid = enterprise_customer.get('enterprise_customer_catalogs')[0]
        customer_agreement.save()
        return customer_agreement

    def create_subscription_plan(self, customer_agreement, num_licenses=1):
        """
        Creates a SubscriptionPlan for a customer.
        """
        timestamp = localized_utcnow()
        new_plan = SubscriptionPlan(
            title='Seed Generated Plan from {} {}'.format(customer_agreement, timestamp),
            customer_agreement=customer_agreement,
            enterprise_catalog_uuid=customer_agreement.default_enterprise_catalog_uuid,
            start_date=timestamp,
            expiration_date=timestamp + timedelta(days=365),
            is_active=True,
            for_internal_use_only=True,
            salesforce_opportunity_id=123456789123456789,
            product=Product.objects.get(name="B2B Paid")
        )
        with transaction.atomic():
            new_plan.save()
            new_plan.increase_num_licenses(
                num_licenses
            )
        return new_plan

    def handle(self, *args, **options):
        """
        Entry point for managment command execution.
        """
        enterprise_customer = None

        enterprise_customer_slug = options['enterprise_customer_slug']

        # Fetch enterprise customer
        enterprise_customer = self.get_enterprise_customer(
            enterprise_customer_slug,
        )
        if not enterprise_customer:
            logger.error('\nNo EnterpriseCustomer found with slug "{}".'.format(enterprise_customer_slug))
            return

        logger.info('\nEnterpriseCustomer found to apply new licenses for: {} {}.'
                    .format(enterprise_customer['name'], enterprise_customer['uuid']))
        customer_agreement = self.get_or_create_customer_agreement(enterprise_customer)

        # populate products first
        call_command('seed_development_data')
        new_plan = self.create_subscription_plan(customer_agreement, num_licenses=options['num_licenses'])
        logger.info('\nCustomerAgreement created on {} used for this subscription plan: {}'.
                    format(customer_agreement.created, customer_agreement.uuid))
        logger.info(new_plan)
        logger.info('Licenses created: {}'.format(License.objects.filter(subscription_plan=new_plan)))
