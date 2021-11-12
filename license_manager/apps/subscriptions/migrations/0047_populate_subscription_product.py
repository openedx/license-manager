from django.db import migrations
from collections import defaultdict

def populate_product(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    Product = apps.get_model("subscriptions", "Product")

    product_by_ns_id = {}
    products_by_plan_type_id = defaultdict(list)

    for product in Product.objects.all():
        if product.netsuite_id:
            # Netsuite Id is unique amongst plans
            product_by_ns_id[product.netsuite_id] = product

        products_by_plan_type_id[product.plan_type_id].append(product)

    for plan in SubscriptionPlan.objects.all().iterator():
        plan_uuid = plan.uuid
        ns_id = plan.netsuite_product_id
        plan_type_id = plan.plan_type_id
        products_with_plan_type = products_by_plan_type_id.get(plan_type_id)

        if ns_id:
            # Netsuite Id must be correct for each plan before this migration is run
            product_to_associate = product_by_ns_id.get(ns_id)

            if not product_to_associate:
                product_to_associate = products_with_plan_type[0]
                print(f"Associated subscription plan {plan_uuid} to {product_to_associate}, Netsuite Id {ns_id} was ignored.")

            plan.product = product_to_associate
            plan.save()
        else:
            product_to_associate = products_with_plan_type[0]
            plan.product = product_to_associate
            plan.save()


def depopulate_product(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    for row in SubscriptionPlan.objects.all():
        row.product = None
        row.save()

class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0046_add_product_and_association_to_subscription_plan'),
    ]

    operations = [
        migrations.RunPython(populate_product, depopulate_product),
    ]
