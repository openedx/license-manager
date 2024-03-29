# Generated by Django 3.2.21 on 2023-09-27 11:19

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0060_historicalsubscriptionlicensesource'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='historicalcustomeragreement',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical Customer Agreement', 'verbose_name_plural': 'historical Customer Agreements'},
        ),
        migrations.AlterModelOptions(
            name='historicallicense',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical license', 'verbose_name_plural': 'historical licenses'},
        ),
        migrations.AlterModelOptions(
            name='historicalnotification',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical notification', 'verbose_name_plural': 'historical notifications'},
        ),
        migrations.AlterModelOptions(
            name='historicalproduct',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical product', 'verbose_name_plural': 'historical products'},
        ),
        migrations.AlterModelOptions(
            name='historicalsubscriptionlicensesource',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical subscription license source', 'verbose_name_plural': 'historical subscription license sources'},
        ),
        migrations.AlterModelOptions(
            name='historicalsubscriptionplan',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical Subscription Plan', 'verbose_name_plural': 'historical Subscription Plans'},
        ),
        migrations.AlterModelOptions(
            name='historicalsubscriptionplanrenewal',
            options={'get_latest_by': ('history_date', 'history_id'), 'ordering': ('-history_date', '-history_id'), 'verbose_name': 'historical Subscription Plan Renewal', 'verbose_name_plural': 'historical Subscription Plan Renewals'},
        ),
    ]
