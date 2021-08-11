"""
Management command for assigning enterprise roles to existing enterprise users.
"""


import logging

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from license_manager.apps.api_client.enterprise import EnterpriseApiClient


from license_manager.apps.subscriptions.models import License, SubscriptionPlan, CustomerAgreement
from license_manager.apps.subscriptions.utils import chunks

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Management command for populating License Manager with an enterprise customer agreement, subscriptions, and licenses.

    Example usage:
        $ ./manage.py seed_enterprise_devstack_data --enterprise-customer "CUSTOMER-UUID-HERE"
    """

    enterprise_customer = None
    enterprise_catalog = None
    help = 'Seeds an enterprise customer agreement, subscription and licenses for an existing enterprise customer.'

    def add_arguments(self, parser):
        """ Adds argument(s) to the the command """
        parser.add_argument(
            '--enterprise-customer-name',
            action='store',
            dest='enterprise_customer_name',
            required=True,
            help='Friendly name of an existing enterprise customer.',
            type=str,
        )

    def get_enterprise_customer(self, enterprise_customer_name):
        """ Returns an enterprise customer """
        logger.info('\nFetching an enterprise customer {} name ...'.format(enterprise_customer_name))
        try:
            enterprise_api_client = EnterpriseApiClient()

            # Query endpoint by name instead of UUID:
            endpoint = '{}?name={}'.format(enterprise_api_client.enterprise_customer_endpoint, str(enterprise_customer_name))
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
        if customer_agreement:
            logger.info('\nCustomerAgreement created on {} found: {}'.format(customer_agreement.created, customer_agreement.uuid))

        return customer_agreement

    def create_subscription_plan(self, enterprise_uuid):
        """ 
        Creates a SubscriptionPlan for a customer.
        """
        pass

    def create_licenses(self, subscription_plan_id, num_licenses=100):
        pass

    def handle(self, *args, **options):
        """
        Entry point for managment command execution.
        """
        enterprise_customer_name = options['enterprise_customer_name']

        # Fetch enterprise customer
        self.enterprise_customer = self.get_enterprise_customer(
            enterprise_customer_name,
        )
        if (self.enterprise_customer):
            logger.info(self.enterprise_customer)
            self.get_or_create_customer_agreement(self.enterprise_customer)
