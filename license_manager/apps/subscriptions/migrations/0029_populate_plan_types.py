import logging

from django.db import migrations

logger = logging.getLogger(__name__)

def populate_plan(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    PlanType = apps.get_model("subscriptions", "PlanType")
    for row in SubscriptionPlan.objects.all():
        if row.netsuite_product_id == 0:
            plan = PlanType.objects.get(label='OCE')
        elif row.netsuite_product_id == 106 or row.netsuite_product_id == 110:
            plan = PlanType.objects.get(label='Standard Paid') 
        else:
            plan = PlanType.objects.get(label='Test')
        row.plan_type = plan
        row.save()

def depopulate_plan(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    PlanType = apps.get_model("subscriptions", "PlanType")
    for row in SubscriptionPlan.objects.all():
        row.plan_type = None
        row.save()

class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0028_plan_type_help_text'),
    ]

    operations = [
        migrations.RunPython(populate_plan, depopulate_plan),
    ]
