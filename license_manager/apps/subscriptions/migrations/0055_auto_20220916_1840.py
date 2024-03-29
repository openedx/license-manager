# Generated by Django 3.2.15 on 2022-09-16 18:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0054_auto_20220908_1747'),
    ]

    operations = [
        migrations.AlterField(
            model_name='historicalproduct',
            name='netsuite_id',
            field=models.IntegerField(blank=True, help_text='(Deprecated) The Product ID field (numeric) of what was sold to the customer.', null=True),
        ),
        migrations.AlterField(
            model_name='product',
            name='netsuite_id',
            field=models.IntegerField(blank=True, help_text='(Deprecated) The Product ID field (numeric) of what was sold to the customer.', null=True),
        ),
    ]
