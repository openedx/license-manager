from django.db import migrations, models

from license_manager.apps.api_client.enterprise import EnterpriseApiClient


def create_relationships(apps, schema_editor):
    """
    Create new CustomerAgreements from all existing SubscriptionPlans with enterprise customers.
    """
    CustomerAgreement = apps.get_model('subscriptions', 'CustomerAgreement')
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')

    subscriptions_with_customers = SubscriptionPlan.objects.exclude(enterprise_customer_uuid=None)
    for plan in subscriptions_with_customers:
        customer_uuid = plan.enterprise_customer_uuid
        enterprise_slug = EnterpriseApiClient().get_enterprise_customer_data(customer_uuid).get('slug', None)
        customer_agreement, _ = CustomerAgreement.objects.get_or_create(
            enterprise_customer_uuid=customer_uuid,
            defaults={
                'enterprise_customer_slug': enterprise_slug,
            }
        )
        plan.customer_agreement = customer_agreement
        plan.save()


def delete_relationships(apps, schema_editor):
    """
    Delete every CustomerAgreement and any links from plans to CustomerAgreements.
    """
    # This step needs to happen first so that all subscriptions aren't removed by the cascading delete.
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    SubscriptionPlan.objects.all().update(customer_agreement=None)

    CustomerAgreement = apps.get_model('subscriptions', 'CustomerAgreement')
    CustomerAgreement.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0014_add_customer_agreement_and_renewals'),
    ]

    operations = [
        migrations.RunPython(create_relationships, delete_relationships),
    ]
