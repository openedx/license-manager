# Generated by Django 3.2.9 on 2021-12-16 20:02

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0050_make_subscriptionplan_plan_type_nullable'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='historicalsubscriptionplan',
            name='netsuite_product_id',
        ),
        migrations.RemoveField(
            model_name='historicalsubscriptionplan',
            name='plan_type',
        ),
        migrations.RemoveField(
            model_name='subscriptionplan',
            name='netsuite_product_id',
        ),
        migrations.RemoveField(
            model_name='subscriptionplan',
            name='plan_type',
        ),
    ]
