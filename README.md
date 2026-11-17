# Shivika E-Commerce — existing project updated

This is the user's existing Django project (`E-Com`) extended according to the Shivika E-Commerce SDLC requirements. The original project structure, current catalogue/order models, initial migration, and SQLite development database are retained. The bundled Windows virtual environment was intentionally excluded; recreate it locally rather than committing a machine-specific `venv` directory.

## Implemented in this update

- Product SKU, cost price, reorder level, validation, and category/product admin screens.
- Supplier master data.
- Purchase orders with multiple product lines, draft/ordered/partially-received/received/cancelled states, cost snapshots, and a place-order admin action.
- Goods receipt service for partial/multiple deliveries; it rejects quantities over the remaining ordered amount.
- Receipt posting is transactional: receipt records, inventory increment, stock movement ledger, purchase-order status, and audit event commit or roll back together.
- Single-warehouse `Inventory` balance with on-hand, reserved, and available quantities.
- Stock adjustment service and admin screen with mandatory reason and immutable movement history.
- Audit log for purchasing, receipt posting, and stock adjustments.
- Modernized Django admin workspace with grouped navigation for catalogue, procurement, inventory, sales, and administration.
- Basic public product listing with search/category filtering and product detail page.
- Tests covering PO placement, partial receipt, over-receipt rollback, final receipt, and adjustment audit ledger.
- Environment-based database settings; no database password is hard-coded into settings.

## Windows setup (PowerShell)

Open PowerShell in the extracted project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For local development with the existing SQLite file, leave `DB_ENGINE` unset. To use MySQL, copy `.env.example` to `.env` and set the environment variables in your terminal or IDE Run Configuration. The settings load `.env` automatically when `python-dotenv` is installed (it is included in `requirements.txt`). Keep `.env` out of Git.

Create a MySQL database and a dedicated application account (do not use `root` for the web app). Example database creation:

```sql
CREATE DATABASE shivika_ecommerce
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Set:

```text
DB_ENGINE=django.db.backends.mysql
DB_NAME=shivika_ecommerce
DB_USER=shivika_app
DB_PASSWORD=your_actual_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

Then run:

```powershell
python manage.py check
python manage.py migrate
python manage.py createsuperuser
python manage.py test ecommerce
python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the public product listing and `http://127.0.0.1:8000/admin/` for operations.

## Purchasing / partial receipt workflow

1. In admin, create a category and a product with unique SKU, cost price, selling price, and reorder level.
2. Create an active supplier.
3. Create a draft purchase order, select the supplier, and add purchase lines with quantities and unit costs.
4. Save the PO, then use the admin action **Place selected draft purchase orders**. Placing a PO does not change stock.
5. From the purchase-order list, select **Receive goods**. Enter only the quantities physically received and post the receipt.
6. Review Inventory and Stock movements. For a 100-unit PO, receiving 60 sets the PO to `partially_received`; receiving the remaining 40 changes it to `received`.
7. Use the inventory **Adjust stock** screen for a controlled count correction, damage, opening balance, or return. A reason is mandatory.

## Important implementation notes / remaining work

- The existing project has a custom `ecommerce.User` table used by legacy address/order/cart tables. Django's built-in authentication user is used for privileged purchasing and audit actors. Before production, consolidate customer identity and authentication into one supported Django auth design; the legacy custom `User.password` field must never be used to store or verify raw passwords.
- The existing `Product.stock` integer field is retained for compatibility with the old project. New inventory workflows use `Inventory.quantity_on_hand` as the authoritative stock balance. Update any legacy screens that still read `Product.stock` before relying on them operationally.
- Customer checkout/reservation conversion, payment gateway callbacks, cancellation/release, shipping address snapshots, GST/tax, returns/refunds, and supplier invoice/payment flows are not fully implemented. The requirements document lists several of these as decisions or later scope.
- Test the MySQL backend and transaction/concurrency behavior on the target MySQL version before production. The automated tests in this archive were run against SQLite; they are not a substitute for MySQL concurrency tests.
- Set a strong `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, production `ALLOWED_HOSTS`, HTTPS/security settings, backups, and monitoring before deployment.
