# Generated by Django 3.2.9 on 2021-12-14 14:48

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0047_populate_subscription_product'),
    ]

    operations = [
        migrations.DeleteModel(
            name='PlanEmailTemplates',
        ),
    ]
