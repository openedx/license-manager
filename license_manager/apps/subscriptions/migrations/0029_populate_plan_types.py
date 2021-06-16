import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)

def save_plan(row, plan_label, apps):
    PlanType = apps.get_model("subscriptions", "PlanType")
    message = 'Assigned {} label to subscription plan \"{}\"'.format(plan_label, row.title)
    logger.info(message)
    return PlanType.objects.get(label=plan_label)

def populate_plan(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    for row in SubscriptionPlan.objects.all():
        if row.netsuite_product_id == 0:
            plan = save_plan(row, 'OCE', apps)
        elif row.netsuite_product_id == 106 or row.netsuite_product_id == 110:
            plan = save_plan(row, 'Standard Paid', apps)
        else:
            plan = save_plan(row, 'Test', apps)
        row.PlanType = plan
        row.save()

class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0028_plan_type_help_text'),
    ]

    operations = [
        migrations.RunPython(populate_plan),
    ]


