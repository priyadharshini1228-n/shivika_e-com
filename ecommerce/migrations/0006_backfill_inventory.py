from django.db import migrations


def backfill_inventory(apps, schema_editor):
    Product = apps.get_model('ecommerce', 'Product')
    Inventory = apps.get_model('ecommerce', 'Inventory')
    for product in Product.objects.all():
        Inventory.objects.get_or_create(product=product, defaults={'quantity_on_hand': product.stock})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ecommerce', '0005_goodsreceipt_source_order_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_inventory, noop_reverse),
    ]