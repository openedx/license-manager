# Generated by Django 2.2.24 on 2021-07-26 12:34

from django.db import migrations, models
import django.db.models.deletion

# currently rerunning the 0029_populate_plan_types to populate subscription plans 
# that were created since then with null plantypes

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
    for row in SubscriptionPlan.objects.all():
        row.plan_type = None
        row.save()

class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0032_populate_email_templates'),
    ]

    operations = [
        migrations.RunPython(populate_plan, depopulate_plan),
        migrations.AlterField(
            model_name='subscriptionplan',
            name='plan_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING,to='subscriptions.PlanType')
        )
    ]
