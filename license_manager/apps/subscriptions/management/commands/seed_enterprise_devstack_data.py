"""
Management command for assigning enterprise roles to existing enterprise users.
"""


import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now
from datetime import timedelta
from license_manager.apps.api_client.enterprise import EnterpriseApiClient


from license_manager.apps.subscriptions.models import License, SubscriptionPlan, CustomerAgreement, PlanType
from license_manager.apps.subscriptions.utils import chunks

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Management command for populating License Manager with enterprise customer agreement, subscriptions, and licenses.

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
        parser.add_argument(
            '--num-licenses',
            action='store',
            dest='num_licenses',
            default=10,
            help='Specify the number of licenses you want on this subscription. Defaults to 10.',
            type=int,
        )

    def get_enterprise_customer(self, enterprise_customer_name):
        """ Returns an enterprise customer """
        logger.info('\nFetching an enterprise customer {} name ...'.format(enterprise_customer_name))
        try:
            enterprise_api_client = EnterpriseApiClient()

            # Query endpoint by name instead of UUID:
            endpoint = '{}?name={}'.format(enterprise_api_client.enterprise_customer_endpoint,
                                           str(enterprise_customer_name))
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
            # Data sync for running command multiple times:
            # update the uuid with the latest that matches the slug:
            customer_agreement.enterprise_customer_uuid = enterprise_customer.get('uuid')
            customer_agreement.default_enterprise_catalog_uuid = enterprise_customer.get('enterprise_customer_catalogs')[0]
            customer_agreement.save()

            logger.info('\nCustomerAgreement created on {} found: {}'.
                        format(customer_agreement.created, customer_agreement.uuid))

        return customer_agreement

    def create_subscription_plan(self, customer_agreement, num_licenses=1, plan_type="Standard Paid"):
        """
        Creates a SubscriptionPlan for a customer.
        """
        timestamp = now()
        new_plan = SubscriptionPlan(
            title='Seed Generated Plan from {} {}'.format(customer_agreement, timestamp),
            customer_agreement=customer_agreement,
            enterprise_catalog_uuid = customer_agreement.default_enterprise_catalog_uuid,
            start_date=timestamp,
            expiration_date=timestamp+timedelta(days=365),
            is_active=True,
            salesforce_opportunity_id=123456789123456789,
            plan_type=PlanType.objects.get(label=plan_type),
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
        enterprise_customer_name = options['enterprise_customer_name']

        # Fetch enterprise customer
        self.enterprise_customer = self.get_enterprise_customer(
            enterprise_customer_name,
        )
        logger.info(self.enterprise_customer)
        customer_agreement = self.get_or_create_customer_agreement(self.enterprise_customer)
        new_plan = self.create_subscription_plan(customer_agreement, num_licenses=options['num_licenses'])
        logger.info(new_plan)
        logger.info('Licenses created: {}'.format(License.objects.filter(subscription_plan=new_plan)))
