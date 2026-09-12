from django.http import HttpResponse
from .models import Barcode, ProductFieldValue
import barcode
import base64
from barcode.writer import ImageWriter
from io import BytesIO
from django.template.loader import render_to_string


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.urls import reverse
from .models import (Product, Inventory, Place, ProductMovement, BarcodeSettings, Barcode, ProductField, Category, ProductFieldValue, CategoryAssignment, ProductPairing)
from django.utils import timezone
from django.db import models, transaction
from django.db.models import Sum
from decimal import Decimal, InvalidOperation

User = get_user_model()


def _product_fields_with_values(product):
    fields = list(
        ProductField.objects.filter(
            category__name=product.department,
        ).order_by("order", "id")
    )
    values = {
        item.field_id: item.value
        for item in product.custom_values.filter(
            field__category__name=product.department,
        )
    }

    for field in fields:
        field.current_value = values.get(field.id, "")
        if field.field_type == "dropdown":
            field.dropdown_options = [
                option.strip()
                for option in field.options.split(",")
                if option.strip()
            ]

    return fields


def _user_can_access_category(user, category):
    return user.is_staff or category is not None and CategoryAssignment.objects.filter(
        user=user,
        category=category,
    ).exists()


def _product_pairings(user, product):
    """Return the product at the other end of each pairing for display."""
    pairings = ProductPairing.objects.filter(
        models.Q(primary_product=product) | models.Q(paired_product=product)
    ).select_related("primary_product__barcode", "paired_product__barcode")
    permitted_departments = None
    if not user.is_staff:
        permitted_departments = set(CategoryAssignment.objects.filter(
            user=user,
        ).values_list("category__name", flat=True))

    visible_pairings = []
    for pairing in pairings:
        pairing.other_product = (
            pairing.paired_product
            if pairing.primary_product_id == product.id
            else pairing.primary_product
        )
        if permitted_departments is None or pairing.other_product.department in permitted_departments:
            visible_pairings.append(pairing)
    return visible_pairings


def _products_available_for_pairing(user, product):
    products = Product.objects.select_related("barcode").exclude(id=product.id)
    if not user.is_staff:
        permitted_departments = CategoryAssignment.objects.filter(
            user=user,
        ).values_list("category__name", flat=True)
        products = products.filter(department__in=permitted_departments)
    return products.order_by("product_name", "barcode__barcode_number")


def _product_details_context(request, product, **extra):
    context = {
        "product": product,
        "product_fields": _product_fields_with_values(product),
        "movements": product.movements.select_related(
            "moved_by", "from_place", "to_place",
        ).all(),
        "places": Place.objects.filter(enabled=True),
        "pairings": _product_pairings(request.user, product),
        "pairing_candidates": _products_available_for_pairing(request.user, product),
    }
    context.update(extra)
    return context


def _staff_only(user):
    return user.is_authenticated and user.is_staff


staff_only = user_passes_test(_staff_only, login_url="/admin-login/")


class InventoryLoginView(auth_views.LoginView):
    template_name = "registration/login.html"

    def get_success_url(self):
        if self.request.user.is_staff:
            return reverse("dashboard")

        assignment = self.request.user.category_assignments.select_related(
            "category"
        ).order_by(
            "category__order",
            "category__name",
        ).first()

        if assignment:
            return reverse(
                "category_dashboard",
                args=[assignment.category_id],
            )

        return reverse("dashboard")


def admin_login(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("dashboard")
        return render(
            request,
            "registration/admin_login.html",
            {"error": "This account does not have administrator access."},
        )

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_staff:
            login(request, user)
            return redirect("dashboard")

        return render(
            request,
            "registration/admin_login.html",
            {"error": "Use an administrator account to continue."},
        )

    return render(request, "registration/admin_login.html")


@staff_only
def admin_dashboard(request):
    return redirect("dashboard")

@staff_only
@transaction.atomic
def generate_barcodes(request):

    settings = BarcodeSettings.objects.first()

    if not settings:
        settings = BarcodeSettings.objects.create(
            prefix="DAV",
            next_number=1,
            digits=6
        )

    if request.method == "POST":

        quantity = request.POST.get("quantity", "").strip()

        try:
            quantity = int(quantity)

            if quantity <= 0:
                raise ValueError

        except (ValueError, TypeError):

            return render(
                request,
                "inventory/barcode_generator.html",
                {
                    "settings": settings,
                    "error": "Please enter a valid positive number."
                }
            )

        new_barcodes = []

        current_number = settings.next_number

        for _ in range(quantity):

            barcode_number = (
                f"{settings.prefix}"
                f"{current_number:0{settings.digits}d}"
            )

            while Barcode.objects.filter(
                barcode_number=barcode_number
            ).exists():

                current_number += 1

                barcode_number = (
                    f"{settings.prefix}"
                    f"{current_number:0{settings.digits}d}"
                )

            new_barcodes.append(
                Barcode(
                    barcode_number=barcode_number,
                    status="unassigned"
                )
            )

            current_number += 1

        Barcode.objects.bulk_create(new_barcodes)

        settings.next_number = current_number
        settings.save()

        return render(
            request,
            "inventory/barcode_generator.html",
            {
                "settings": settings,
                "success": (
                    f"{quantity} barcode"
                    f"{'s' if quantity != 1 else ''} "
                    "generated successfully."
                )
            }
        )

    return render(
        request,
        "inventory/barcode_generator.html",
        {
            "settings": settings
        }
    )

def barcode_image(request, barcode_number):
    try:
        barcode_record = Barcode.objects.get(
            barcode_number=barcode_number
        )
    except Barcode.DoesNotExist:
        return HttpResponse(
            "Barcode not found",
            status=404
        )

    code128 = barcode.get(
        "code128",
        barcode_record.barcode_number,
        writer=ImageWriter()
    )

    buffer = BytesIO()

    code128.write(
        buffer,
        options={
            "module_width": 0.25,
            "module_height": 18.0,
            "font_size": 3,
            "text_distance": 5,
            "quiet_zone": 4,
            "dpi": 300,
        }
    )

    return HttpResponse(
        buffer.getvalue(),
        content_type="image/png"
    )

def generate_barcode_pdf(request):
    from weasyprint import HTML

    quantity = request.GET.get("quantity", "").strip()

    try:
        quantity = int(quantity)

        if quantity <= 0:
            raise ValueError

    except (ValueError, TypeError):
        return HttpResponse(
            "Invalid barcode quantity.",
            status=400
        )

    # Get the requested unassigned barcodes
    barcodes = list(
        Barcode.objects.filter(
            status="unassigned"
        )
        .order_by("id")[:quantity]
    )

    if len(barcodes) < quantity:
        return HttpResponse(
            f"Only {len(barcodes)} unassigned barcodes are available.",
            status=400
        )

    barcode_data = []

    for barcode_record in barcodes:

        # Create Code 128 barcode
        code128 = barcode.get(
            "code128",
            barcode_record.barcode_number,
            writer=ImageWriter()
        )

        buffer = BytesIO()

        code128.write(
            buffer,
            options={
                "module_width": 0.25,
                "module_height": 18.0,

                # IMPORTANT:
                # Prevent python-barcode from printing
                # the number underneath the barcode.
                "font_size": 0,

                "text_distance": 0,

                "quiet_zone": 3,

                "dpi": 300,
            }
        )

        # Convert image to Base64
        image_base64 = base64.b64encode(
            buffer.getvalue()
        ).decode("utf-8")

        barcode_data.append({
            "number": barcode_record.barcode_number,
            "image": image_base64,
        })

    html_string = render_to_string(
        "inventory/barcode_pdf.html",
        {
            "barcodes": barcode_data,
        }
    )

    pdf = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/")
    ).write_pdf()

    response = HttpResponse(
        pdf,
        content_type="application/pdf"
    )

    response[
        "Content-Disposition"
    ] = 'inline; filename="barcodes.pdf"'

    return response

@staff_only
@transaction.atomic
def print_barcodes(request):
    quantity = request.GET.get("quantity")

    # Default: show available barcodes
    if not quantity:
        barcodes = Barcode.objects.filter(
            status="unassigned"
        ).order_by("id")

        return render(
            request,
            "inventory/print_barcodes.html",
            {
                "barcodes": barcodes,
                "total_available": barcodes.count(),
            }
        )

    try:
        quantity = int(quantity)

        if quantity <= 0:
            raise ValueError

    except (ValueError, TypeError):
        return render(
            request,
            "inventory/print_barcodes.html",
            {
                "barcodes": [],
                "total_available": Barcode.objects.filter(
                    status="unassigned"
                ).count(),
                "error": "Please enter a valid positive number.",
            }
        )

    # Count currently available barcodes
    available_count = Barcode.objects.filter(
        status="unassigned"
    ).count()

    # Generate additional barcodes if necessary
    if available_count < quantity:

        needed = quantity - available_count

        last_barcode = Barcode.objects.order_by("-id").first()

        if last_barcode:
            last_number = int(
                last_barcode.barcode_number.replace("CN", "")
            )
        else:
            last_number = 0

        new_barcodes = []

        for i in range(1, needed + 1):
            new_barcodes.append(
                Barcode(
                    barcode_number=f"CN{last_number + i:06d}",
                    status="unassigned"
                )
            )

        Barcode.objects.bulk_create(new_barcodes)

    # Get exactly the requested number
    barcodes = Barcode.objects.filter(
        status="unassigned"
    ).order_by("id")[:quantity]

    total_available = Barcode.objects.filter(
        status="unassigned"
    ).count()

    return render(
        request,
        "inventory/print_barcodes.html",
        {
            "barcodes": barcodes,
            "total_available": total_available,
            "selected_quantity": quantity,
        }
    )

def scan_barcode(request):

    barcode_number = request.GET.get(
        "barcode",
        ""
    ).strip()

    if not barcode_number:

        return render(
            request,
            "inventory/scan_barcode.html"
        )

    try:

        barcode = Barcode.objects.get(
            barcode_number=barcode_number
        )

    except Barcode.DoesNotExist:

        return render(
            request,
            "inventory/scan_barcode.html",
            {
                "error":
                    "Barcode does not exist in the system."
            }
        )


    # =================================================
    # BARCODE ALREADY ASSIGNED
    # =================================================

    if barcode.status != "unassigned":

        product = get_object_or_404(
            Product,
            barcode=barcode
        )

        if not _user_can_access_category(
            request.user,
            Category.objects.filter(name=product.department).first(),
        ):
            return redirect("dashboard")

        return render(
            request,
            "inventory/product_details.html",
            _product_details_context(request, product),
        )


    # =================================================
    # GET DEPARTMENTS
    # =================================================

    departments = Category.objects.filter(
        enabled=True
    ).order_by(
        "order",
        "name"
    )

    if not request.user.is_staff:
        departments = departments.filter(
            user_assignments__user=request.user
        )


    # =================================================
    # NO DEPARTMENTS
    # =================================================

    if not departments.exists():

        return render(
            request,
            "inventory/select_department.html",
            {
                "barcode": barcode,
                "no_departments": True,
                "no_assigned_departments": not request.user.is_staff,
            }
        )


    # =================================================
    # SELECTED DEPARTMENT
    # =================================================

    department_id = request.GET.get("department")

    if not request.user.is_staff and departments.count() == 1:
        department_id = departments.values_list(
            "id",
            flat=True,
        ).first()


    if not department_id:

        return render(
            request,
            "inventory/select_department.html",
            {
                "barcode": barcode,
                "departments": departments,
            }
        )


    try:

        department = departments.get(
            id=department_id
        )

    except Category.DoesNotExist:

        return render(
            request,
            "inventory/select_department.html",
            {
                "barcode": barcode,
                "departments": departments,
                "error":
                    "Invalid department selected."
            }
        )

    if not _user_can_access_category(request.user, department):
        return redirect("dashboard")


    # =================================================
    # GET ENABLED FIELDS
    # =================================================

    fields = ProductField.objects.filter(
        category=department,
        enabled=True
    ).order_by(
        "order",
        "id"
    )

    for field in fields:

        if field.field_type == "dropdown":

            field.dropdown_options = [
                option.strip()
                for option in field.options.split(",")
                if option.strip()
            ]


    # =================================================
    # REGISTER PRODUCT
    # =================================================

    if request.method == "POST":
        product_name = request.POST.get("product_name", "").strip()
        description = request.POST.get("description", "").strip()
        quantity_input = request.POST.get("quantity", "0").strip()

        try:
            quantity = Decimal(quantity_input or "0")
            if quantity < 0:
                raise InvalidOperation
            quantity_error = ""
        except (InvalidOperation, ValueError):
            quantity = Decimal("0")
            quantity_error = "Current stock must be zero or greater."

        if not product_name or quantity_error:
            return render(
                request,
                "inventory/register_product.html",
                {
                    "barcode": barcode,
                    "department": department,
                    "fields": fields,
                    "product_name": product_name,
                    "description": description,
                    "quantity": quantity_input,
                    "error": quantity_error or "Product name is required.",
                },
            )

        # ---------------------------------------------
        # VALIDATE CUSTOM FIELDS
        # ---------------------------------------------

        for field in fields:

            value = request.POST.get(
                f"field_{field.id}",
                ""
            ).strip()

            if field.required and not value:

                return render(
                    request,
                    "inventory/register_product.html",
                    {
                        "barcode": barcode,
                        "department": department,
                        "fields": fields,
                        "product_name": product_name,
                        "description": description,
                        "error":
                            f"{field.name} is required."
                    }
                )


        # ---------------------------------------------
        # CREATE EVERYTHING ATOMICALLY
        # ---------------------------------------------

        with transaction.atomic():

            product = Product.objects.create(

                barcode=barcode,

                product_name=product_name,

                category=department.name,

                department=department.name,

                unit="unit",

                purchase_price=0,

                # selling_price=selling_price,

                # supplier=supplier,

                description=description,

                image=request.FILES.get("image"),
            )


            # -----------------------------------------
            # SAVE CUSTOM FIELD VALUES
            # -----------------------------------------

            for field in fields:

                value = request.POST.get(
                    f"field_{field.id}",
                    ""
                ).strip()

                ProductFieldValue.objects.create(

                    product=product,

                    field=field,

                    value=value,
                )


            # -----------------------------------------
            # ASSIGN BARCODE
            # -----------------------------------------

            barcode.status = "assigned"

            barcode.assigned_at = timezone.now()

            barcode.save(
                update_fields=[
                    "status",
                    "assigned_at"
                ]
            )


            # -----------------------------------------
            # CREATE INVENTORY
            # -----------------------------------------

            Inventory.objects.create(

                product=product,

                quantity=quantity
            )


        return render(
            request,
            "inventory/product_details.html",
            _product_details_context(
                request,
                product,
                success="Product registered successfully.",
            ),
        )


    # =================================================
    # SHOW REGISTRATION FORM
    # =================================================

    return render(
        request,
        "inventory/register_product.html",
        {
            "barcode": barcode,
            "department": department,
            "fields": fields,
        }
    )

def edit_product(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    category = Category.objects.filter(name=product.department).first()
    if not _user_can_access_category(request.user, category):
        return redirect("dashboard")

    if request.method == "POST":
        product_fields = _product_fields_with_values(product)
        product_name = request.POST.get("product_name", "").strip()
        description = request.POST.get("description", "").strip()
        quantity_input = request.POST.get(
            "quantity",
            str(product.inventory.quantity),
        ).strip()

        try:
            quantity = Decimal(quantity_input or "0")
            if quantity < 0:
                raise InvalidOperation
            quantity_error = ""
        except (InvalidOperation, ValueError):
            quantity = product.inventory.quantity
            quantity_error = "Current stock must be zero or greater."

        if not product_name or quantity_error:
            return render(
                request,
                "inventory/edit_product.html",
                {
                    "product": product,
                    "product_fields": product_fields,
                    "product_name": product_name,
                    "description": description,
                    "quantity": quantity_input,
                    "error": quantity_error or "Product name is required.",
                },
            )

        for field in product_fields:
            value = request.POST.get(
                f"field_{field.id}",
                "",
            ).strip()

            if field.required and not value:
                return render(
                    request,
                    "inventory/edit_product.html",
                    {
                        "product": product,
                        "product_fields": product_fields,
                        "product_name": product_name,
                        "description": description,
                        "quantity": quantity_input,
                        "error": f"{field.name} is required.",
                    },
                )

        # Update image only when a new image was selected
        new_image = request.FILES.get("image")

        if new_image:
            product.image = new_image

        product.product_name = product_name
        product.description = description

        with transaction.atomic():
            product.save()
            product.inventory.quantity = quantity
            product.inventory.save(update_fields=["quantity", "updated_at"])

            for field in product_fields:
                ProductFieldValue.objects.update_or_create(
                    product=product,
                    field=field,
                    defaults={
                        "value": request.POST.get(
                            f"field_{field.id}",
                            "",
                        ).strip(),
                    },
                )

        return render(
            request,
            "inventory/product_details.html",
            _product_details_context(
                request,
                product,
                success="Product updated successfully.",
            ),
        )

    return render(
        request,
        "inventory/edit_product.html",
        {
            "product": product,
            "product_fields": _product_fields_with_values(product),
        }
    )


def product_details(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("barcode", "inventory"),
        id=product_id,
    )

    category = Category.objects.filter(name=product.department).first()
    if not _user_can_access_category(request.user, category):
        return redirect("dashboard")

    return render(
        request,
        "inventory/product_details.html",
        _product_details_context(request, product),
    )


def add_product_pairing(request, product_id):
    """Pair two registered products while keeping their barcodes independent."""
    product = get_object_or_404(Product.objects.select_related("barcode"), id=product_id)
    category = Category.objects.filter(name=product.department).first()
    if not _user_can_access_category(request.user, category):
        return redirect("dashboard")
    if request.method != "POST":
        return redirect("product_details", product_id=product.id)

    paired_product_id = request.POST.get("paired_product_id")
    relationship_type = request.POST.get("relationship_type", "").strip()
    paired_product = Product.objects.filter(id=paired_product_id).select_related("barcode").first()

    if not paired_product:
        error = "Choose a registered product to pair."
    elif not _user_can_access_category(
        request.user, Category.objects.filter(name=paired_product.department).first()
    ):
        error = "You do not have access to the selected product."
    elif paired_product.id == product.id:
        error = "A product cannot be paired with itself."
    elif ProductPairing.objects.filter(
        models.Q(primary_product=product, paired_product=paired_product)
        | models.Q(primary_product=paired_product, paired_product=product)
    ).exists():
        error = "These products are already paired."
    else:
        ProductPairing.objects.create(
            primary_product=product,
            paired_product=paired_product,
            relationship_type=relationship_type,
        )
        return redirect(f"{reverse('product_details', args=[product.id])}?pairing_success=added")

    return render(
        request,
        "inventory/product_details.html",
        _product_details_context(request, product, pairing_error=error),
    )


def remove_product_pairing(request, product_id, pairing_id):
    product = get_object_or_404(Product, id=product_id)
    pairing = get_object_or_404(
        ProductPairing.objects.select_related("primary_product", "paired_product"), id=pairing_id
    )
    if product.id not in (pairing.primary_product_id, pairing.paired_product_id):
        return redirect("product_details", product_id=product.id)

    other_product = (
        pairing.paired_product if pairing.primary_product_id == product.id else pairing.primary_product
    )
    if not _user_can_access_category(
        request.user, Category.objects.filter(name=product.department).first()
    ) or not _user_can_access_category(
        request.user, Category.objects.filter(name=other_product.department).first()
    ):
        return redirect("dashboard")
    if request.method == "POST":
        pairing.delete()
        return redirect(f"{reverse('product_details', args=[product.id])}?pairing_success=removed")
    return redirect("product_details", product_id=product.id)


def add_product_movement(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("inventory"),
        id=product_id,
    )
    category = Category.objects.filter(name=product.department).first()

    if not _user_can_access_category(request.user, category):
        return redirect("dashboard")

    if request.method != "POST":
        return redirect("product_details", product_id=product.id)

    movement_type = request.POST.get("movement_type", "").strip()
    quantity_input = request.POST.get("quantity", "").strip()
    from_location = request.POST.get("from_location", "").strip()
    to_location = request.POST.get("to_location", "").strip()
    from_place = get_object_or_404(
        Place,
        id=request.POST.get("from_place_id"),
        enabled=True,
    ) if request.POST.get("from_place_id") else None
    to_place = get_object_or_404(
        Place,
        id=request.POST.get("to_place_id"),
        enabled=True,
    ) if request.POST.get("to_place_id") else None
    purpose = request.POST.get("purpose", "").strip()
    notes = request.POST.get("notes", "").strip()

    if movement_type not in dict(ProductMovement.MOVEMENT_TYPES):
        return redirect("product_details", product_id=product.id)

    inventory = product.inventory
    quantity_before = inventory.quantity

    try:
        # A single usable item is always moved as one item; no quantity entry is needed.
        quantity = (
            Decimal("1")
            if movement_type == "use" and quantity_before == 1 and not quantity_input
            else Decimal(quantity_input)
        )
        if quantity <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return render(
            request,
            "inventory/product_details.html",
            _product_details_context(
                request, product, movement_error="Enter a quantity greater than zero."
            ),
        )

    if movement_type == "use":
        quantity_after = quantity_before - quantity
        if quantity_after < 0:
            return render(
                request,
                "inventory/product_details.html",
                _product_details_context(
                    request,
                    product,
                    movement_error="Used quantity cannot exceed current stock.",
                ),
            )
    elif movement_type == "adjustment":
        quantity_after = quantity
    else:
        quantity_after = quantity_before + quantity if movement_type in {"receive", "return"} else quantity_before

    if movement_type == "transfer" and not to_place:
        return render(
            request,
            "inventory/product_details.html",
            _product_details_context(
                request,
                product,
                movement_error="Destination is required for a transfer.",
            ),
        )

    with transaction.atomic():
        ProductMovement.objects.create(
            product=product,
            from_place=from_place,
            to_place=to_place,
            movement_type=movement_type,
            quantity=quantity,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            from_location=from_location or (from_place.name if from_place else inventory.location),
            to_location=to_location or (to_place.name if to_place else ""),
            purpose=purpose,
            notes=notes,
            moved_by=request.user,
        )
        inventory.quantity = quantity_after
        if to_location or to_place:
            inventory.location = to_location or to_place.name
        inventory.save(update_fields=["quantity", "location", "updated_at"])

    return redirect("product_details", product_id=product.id)


def download_movement_history_pdf(request, product_id):
    """Download a presentable movement-history report for one product."""
    from weasyprint import HTML

    product = get_object_or_404(Product.objects.select_related("barcode"), id=product_id)
    category = Category.objects.filter(name=product.department).first()
    if not _user_can_access_category(request.user, category):
        return redirect("dashboard")

    movements = product.movements.select_related(
        "moved_by", "from_place", "to_place",
    ).all()
    for movement in movements:
        movement.from_place_image_url = (
            request.build_absolute_uri(movement.from_place.image.url)
            if movement.from_place and movement.from_place.image else ""
        )
        movement.to_place_image_url = (
            request.build_absolute_uri(movement.to_place.image.url)
            if movement.to_place and movement.to_place.image else ""
        )

    html = render_to_string(
        "inventory/movement_history_pdf.html",
        {"product": product, "movements": movements},
    )
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{product.barcode.barcode_number}-movement-history.pdf"'
    )
    return response


@staff_only
def places(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        image = request.FILES.get("image")

        if not name:
            return render(
                request,
                "inventory/places.html",
                {
                    "places": Place.objects.all(),
                    "error": "Place name is required.",
                },
            )

        if Place.objects.filter(name__iexact=name).exists():
            return render(
                request,
                "inventory/places.html",
                {
                    "places": Place.objects.all(),
                    "error": "A place with this name already exists.",
                },
            )

        Place.objects.create(
            name=name,
            description=description,
            image=image,
        )
        return redirect("places")

    return render(
        request,
        "inventory/places.html",
        {"places": Place.objects.all()},
    )


@staff_only
def delete_place(request, place_id):
    if request.method == "POST":
        get_object_or_404(Place, id=place_id).delete()
    return redirect("places")


@staff_only
@transaction.atomic
def release_product(request, product_id):

    if request.method != "POST":
        return redirect("dashboard")

    product = get_object_or_404(
        Product.objects.select_related("barcode"),
        id=product_id
    )
    barcode = product.barcode

    product.delete()

    barcode.status = "unassigned"
    barcode.assigned_at = None
    barcode.save(update_fields=["status", "assigned_at"])

    return redirect("dashboard")


def delete_product_field(request, field_id):

    if request.method == "POST":
        field = get_object_or_404(ProductField, id=field_id)
        field.delete()

    return redirect("product_fields")


@staff_only
def barcode_settings(request):
    settings = BarcodeSettings.objects.first()

    if not settings:
        settings = BarcodeSettings.objects.create(
            prefix="CN",
            next_number=1,
            digits=6
        )

    if request.method == "POST":
        prefix = request.POST.get("prefix", "").strip()
        next_number = request.POST.get("next_number", "").strip()
        digits = request.POST.get("digits", "").strip()

        try:
            next_number = int(next_number)
            digits = int(digits)

            if not prefix:
                raise ValueError("Prefix cannot be empty.")

            if next_number < 1:
                raise ValueError("Starting number must be at least 1.")

            if digits < 1:
                raise ValueError("Digits must be at least 1.")

            settings.prefix = prefix
            settings.next_number = next_number
            settings.digits = digits
            settings.save()

            return render(
                request,
                "inventory/barcode_settings.html",
                {
                    "settings": settings,
                    "success": "Barcode settings saved successfully."
                }
            )

        except ValueError as error:
            return render(
                request,
                "inventory/barcode_settings.html",
                {
                    "settings": settings,
                    "error": str(error)
                }
            )

    return render(
        request,
        "inventory/barcode_settings.html",
        {
            "settings": settings
        }
    )


@staff_only
def assigned_items(request):
    products = Product.objects.select_related(
        "barcode",
        "inventory"
    ).prefetch_related(
        models.Prefetch(
            "pairings_as_primary",
            queryset=ProductPairing.objects.select_related("paired_product__barcode"),
            to_attr="primary_pairings",
        ),
        models.Prefetch(
            "pairings_as_paired",
            queryset=ProductPairing.objects.select_related("primary_product__barcode"),
            to_attr="paired_pairings",
        ),
    ).filter(
        barcode__status="assigned"
    ).order_by("-created_at")

    if not request.user.is_staff:
        products = products.filter(
            department__in=Category.objects.filter(
                user_assignments__user=request.user,
            ).values("name")
        )

    search = request.GET.get("search", "").strip()

    if search:
        products = products.filter(
            models.Q(product_name__icontains=search)
            | models.Q(category__icontains=search)
            | models.Q(department__icontains=search)
            | models.Q(barcode__barcode_number__icontains=search)
        )

    products = list(products)
    for product in products:
        product.paired_items = [
            {
                "product": pairing.paired_product,
                "relationship_type": pairing.relationship_type,
            }
            for pairing in product.primary_pairings
        ] + [
            {
                "product": pairing.primary_product,
                "relationship_type": pairing.relationship_type,
            }
            for pairing in product.paired_pairings
        ]

    return render(
        request,
        "inventory/assigned_items.html",
        {
            "products": products,
            "search": search,
        }
    )


def dashboard(request):
    if not request.user.is_staff:
        landing_assignment = request.user.category_assignments.select_related(
            "category"
        ).order_by(
            "category__order",
            "category__name",
        ).first()

        if landing_assignment:
            return redirect(
                "category_dashboard",
                landing_assignment.category_id,
            )

    departments = Category.objects.filter(
        enabled=True
    ).order_by(
        "order",
        "name"
    )

    product_scope = Product.objects.all()
    inventory_scope = Inventory.objects.all()
    barcode_scope = Barcode.objects.all()

    if not request.user.is_staff:
        departments = departments.filter(
            user_assignments__user=request.user
        )
        assigned_names = departments.values("name")
        product_scope = product_scope.filter(department__in=assigned_names)
        inventory_scope = inventory_scope.filter(product__department__in=assigned_names)
        barcode_scope = barcode_scope.filter(product__department__in=assigned_names)

    total_products = product_scope.count()
    assigned_barcodes = barcode_scope.filter(status="assigned").count()
    unassigned_barcodes = barcode_scope.filter(status="unassigned").count()
    total_stock = inventory_scope.aggregate(total=Sum("quantity"))["total"] or 0

    low_stock_items = inventory_scope.filter(
        quantity__lte=5
    ).select_related(
        "product",
        "product__barcode"
    ).order_by(
        "quantity"
    )[:10]

    recent_products = product_scope.select_related(
        "barcode",
        "inventory"
    ).order_by(
        "-created_at"
    )[:8]

    return render(
        request,
        "inventory/dashboard.html",
        {
            "total_products": total_products,
            "assigned_barcodes": assigned_barcodes,
            "unassigned_barcodes": unassigned_barcodes,
            "total_stock": total_stock,
            "low_stock_items": low_stock_items,
            "recent_products": recent_products,
            "departments": departments,
            "total_users": User.objects.count() if request.user.is_staff else None,
            "active_users": User.objects.filter(is_active=True).count() if request.user.is_staff else None,
            "total_categories": Category.objects.count() if request.user.is_staff else None,
            "total_fields": ProductField.objects.count() if request.user.is_staff else None,
        }
    )


def category_dashboard(request, category_id):

    category = get_object_or_404(Category, id=category_id)

    if (
        not request.user.is_staff
        and not CategoryAssignment.objects.filter(
            user=request.user,
            category=category,
        ).exists()
    ):
        return redirect("dashboard")
    products = Product.objects.select_related(
        "barcode",
        "inventory"
    ).filter(
        department=category.name,
        barcode__status="assigned"
    ).order_by("-created_at")

    total_stock = Inventory.objects.filter(
        product__department=category.name
    ).aggregate(total=Sum("quantity"))["total"] or 0

    low_stock_items = products.filter(
        inventory__quantity__lte=5
    ).order_by("inventory__quantity")[:10]

    return render(
        request,
        "inventory/category_dashboard.html",
        {
            "category": category,
            "products": products,
            "total_products": products.count(),
            "total_stock": total_stock,
            "low_stock_items": low_stock_items,
            "fields": category.fields.filter(enabled=True).order_by("order", "id"),
        }
    )

@staff_only
def product_fields(request):
    fields = ProductField.objects.select_related(
        "category"
    ).order_by(
        "category__order",
        "category__name",
        "order",
        "id",
    )

    return render(
        request,
        "inventory/product_fields.html",
        {
            "fields": fields
        }
    )

@staff_only
def add_product_field(request):
    categories = Category.objects.filter(
        enabled=True
    ).order_by("order", "name")

    if request.method == "POST":

        category_id = request.POST.get("category")
        name = request.POST.get("name", "").strip()
        field_type = request.POST.get("field_type", "text")
        required = request.POST.get("required") == "on"
        enabled = request.POST.get("enabled") == "on"
        options = request.POST.get("options", "").strip()

        # Validate category
        try:
            category = Category.objects.get(
                id=category_id,
                enabled=True
            )
        except (Category.DoesNotExist, TypeError, ValueError):
            return render(
                request,
                "inventory/add_product_field.html",
                {
                    "categories": categories,
                    "error": "Please select a valid category.",
                    "name": name,
                    "field_type": field_type,
                    "required": required,
                    "enabled": enabled,
                    "options": options,
                }
            )

        # Validate name
        if not name:
            return render(
                request,
                "inventory/add_product_field.html",
                {
                    "categories": categories,
                    "error": "Field name is required.",
                    "category_id": category.id,
                    "name": name,
                    "field_type": field_type,
                    "required": required,
                    "enabled": enabled,
                    "options": options,
                }
            )

        # Validate duplicate field within category
        if ProductField.objects.filter(
            category=category,
            name__iexact=name
        ).exists():

            return render(
                request,
                "inventory/add_product_field.html",
                {
                    "categories": categories,
                    "error": (
                        f"A field named '{name}' already exists "
                        f"in the {category.name} category."
                    ),
                    "category_id": category.id,
                    "name": name,
                    "field_type": field_type,
                    "required": required,
                    "enabled": enabled,
                    "options": options,
                }
            )

        # Validate field type
        valid_types = {
            "text",
            "number",
            "decimal",
            "date",
            "boolean",
            "dropdown",
        }

        if field_type not in valid_types:

            return render(
                request,
                "inventory/add_product_field.html",
                {
                    "categories": categories,
                    "error": "Invalid field type selected.",
                    "category_id": category.id,
                    "name": name,
                    "field_type": "text",
                    "required": required,
                    "enabled": enabled,
                    "options": options,
                }
            )

        # Dropdown requires options
        if field_type == "dropdown" and not options:

            return render(
                request,
                "inventory/add_product_field.html",
                {
                    "categories": categories,
                    "error": (
                        "Please provide at least one option "
                        "for the dropdown field."
                    ),
                    "category_id": category.id,
                    "name": name,
                    "field_type": field_type,
                    "required": required,
                    "enabled": enabled,
                    "options": options,
                }
            )

        # Determine display order within this category
        last_field = ProductField.objects.filter(
            category=category
        ).order_by("-order").first()

        next_order = (
            last_field.order + 1
            if last_field
            else 1
        )

        ProductField.objects.create(
            category=category,
            name=name,
            field_type=field_type,
            required=required,
            enabled=enabled,
            order=next_order,
            options=options,
        )

        return redirect("product_fields")

    return render(
        request,
        "inventory/add_product_field.html",
        {
            "categories": categories,
        }
    )

@staff_only
def edit_product_field(request, field_id):

    field = get_object_or_404(
        ProductField,
        id=field_id
    )

    categories = Category.objects.filter(
        enabled=True
    ).order_by("order", "name")

    if request.method == "POST":

        category_id = request.POST.get("category")
        name = request.POST.get("name", "").strip()
        field_type = request.POST.get("field_type", "text")
        required = request.POST.get("required") == "on"
        enabled = request.POST.get("enabled") == "on"
        options = request.POST.get("options", "").strip()

        try:
            category = Category.objects.get(
                id=category_id,
                enabled=True
            )
        except (Category.DoesNotExist, TypeError, ValueError):

            return render(
                request,
                "inventory/edit_product_field.html",
                {
                    "field": field,
                    "categories": categories,
                    "error": "Please select a valid category."
                }
            )

        if not name:

            return render(
                request,
                "inventory/edit_product_field.html",
                {
                    "field": field,
                    "categories": categories,
                    "error": "Field name is required."
                }
            )

        valid_types = {
            "text",
            "number",
            "decimal",
            "date",
            "boolean",
            "dropdown",
        }

        if field_type not in valid_types:

            return render(
                request,
                "inventory/edit_product_field.html",
                {
                    "field": field,
                    "categories": categories,
                    "error": "Invalid field type selected."
                }
            )

        if field_type == "dropdown" and not options:

            return render(
                request,
                "inventory/edit_product_field.html",
                {
                    "field": field,
                    "categories": categories,
                    "error": "Dropdown fields require options."
                }
            )

        duplicate = ProductField.objects.filter(
            category=category,
            name__iexact=name
        ).exclude(
            id=field.id
        ).exists()

        if duplicate:

            return render(
                request,
                "inventory/edit_product_field.html",
                {
                    "field": field,
                    "categories": categories,
                    "error": (
                        f"A field named '{name}' already exists "
                        f"in {category.name}."
                    )
                }
            )

        field.category = category
        field.name = name
        field.field_type = field_type
        field.required = required
        field.enabled = enabled
        field.options = options

        field.save()

        return redirect("product_fields")

    return render(
        request,
        "inventory/edit_product_field.html",
        {
            "field": field,
            "categories": categories,
        }
    )


@staff_only
def toggle_product_field(request, field_id):
    field = get_object_or_404(ProductField, id=field_id)

    if request.method == "POST":
        field.enabled = not field.enabled
        field.save(update_fields=["enabled"])

    return redirect("product_fields")


@staff_only
def delete_product_field(request, field_id):
    if request.method == "POST":
        field = get_object_or_404(ProductField, id=field_id)
        field.delete()

    return redirect("product_fields")


@staff_only
def categories(request):
    category_list = Category.objects.all().order_by("order", "id")

    return render(
        request,
        "inventory/categories.html",
        {
            "categories": category_list,
        }
    )


@staff_only
def delete_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)

    if request.method == "POST":
        has_products = Product.objects.filter(
            models.Q(department=category.name)
            | models.Q(category=category.name)
        ).exists()

        if has_products:
            category_list = Category.objects.all().order_by("order", "id")

            return render(
                request,
                "inventory/categories.html",
                {
                    "categories": category_list,
                    "error": (
                        f"Cannot delete {category.name} because products "
                        "are still assigned to it."
                    ),
                }
            )

        category.delete()

    return redirect("categories")

@staff_only
def category_fields(request, category_id):
    category = get_object_or_404(
        Category,
        id=category_id
    )

    fields = ProductField.objects.filter(
        category=category
    ).order_by(
        "order",
        "id"
    )

    return render(
        request,
        "inventory/category_fields.html",
        {
            "category": category,
            "fields": fields,
        }
    )

@staff_only
def add_category(request):

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        enabled = request.POST.get("enabled") == "on"

        if not name:
            return render(
                request,
                "inventory/add_category.html",
                {
                    "error": "Category name is required.",
                    "name": name,
                    "description": description,
                }
            )

        if Category.objects.filter(name__iexact=name).exists():
            return render(
                request,
                "inventory/add_category.html",
                {
                    "error": "A category with this name already exists.",
                    "name": name,
                    "description": description,
                }
            )

        last_category = Category.objects.order_by("-order").first()

        next_order = (
            last_category.order + 1
            if last_category
            else 1
        )

        Category.objects.create(
            name=name,
            description=description,
            enabled=enabled,
            order=next_order
        )

        return redirect("categories")

    return render(
        request,
        "inventory/add_category.html"
    )

@staff_only
def edit_category(request, category_id):
    category = get_object_or_404(
        Category,
        id=category_id
    )

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        enabled = request.POST.get("enabled") == "on"

        if not name:

            return render(
                request,
                "inventory/edit_category.html",
                {
                    "category": category,
                    "error": "Category name is required."
                }
            )

        duplicate = Category.objects.filter(
            name__iexact=name
        ).exclude(
            id=category.id
        ).exists()

        if duplicate:

            return render(
                request,
                "inventory/edit_category.html",
                {
                    "category": category,
                    "error": "A category with this name already exists."
                }
            )

        category.name = name
        category.description = description
        category.enabled = enabled

        category.save()

        return redirect("categories")

    return render(
        request,
        "inventory/edit_category.html",
        {
            "category": category
        }
    )


@staff_only
def admin_users(request):
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_user":
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()

            if not username or not password:
                error = "Username and password are required."
            elif User.objects.filter(username__iexact=username).exists():
                error = "That username is already in use."
            else:
                User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                return redirect("admin_users")

            return render(
                request,
                "inventory/admin_users.html",
                {
                    "users": User.objects.prefetch_related(
                        "category_assignments__category"
                    ).order_by("username"),
                    "categories": Category.objects.filter(enabled=True),
                    "error": error,
                },
            )

        if action == "assign_category":
            user = get_object_or_404(User, id=request.POST.get("user_id"))
            category = get_object_or_404(
                Category,
                id=request.POST.get("category_id"),
                enabled=True,
            )
            CategoryAssignment.objects.get_or_create(
                user=user,
                category=category,
            )
            return redirect("admin_users")

        if action == "remove_assignment":
            assignment = get_object_or_404(
                CategoryAssignment,
                id=request.POST.get("assignment_id"),
            )
            assignment.delete()
            return redirect("admin_users")

    return render(
        request,
        "inventory/admin_users.html",
        {
            "users": User.objects.prefetch_related(
                "category_assignments__category"
            ).order_by("username"),
            "categories": Category.objects.filter(enabled=True).order_by(
                "order", "name"
            ),
        },
    )


@staff_only
def admin_edit_user(request, user_id):
    account = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        duplicate = User.objects.filter(
            username__iexact=username
        ).exclude(
            id=account.id
        ).exists()

        if not username:
            error = "Username is required."
        elif duplicate:
            error = "That username is already in use."
        else:
            account.username = username
            account.first_name = request.POST.get("first_name", "").strip()
            account.last_name = request.POST.get("last_name", "").strip()
            account.email = request.POST.get("email", "").strip()
            account.is_active = request.POST.get("is_active") == "on"

            if account.id != request.user.id:
                account.is_staff = request.POST.get("is_staff") == "on"

            if password:
                try:
                    validate_password(password, account)
                except ValidationError as error:
                    return render(
                        request,
                        "inventory/admin_edit_user.html",
                        {
                            "account": account,
                            "categories": Category.objects.filter(
                                enabled=True
                            ).order_by("order", "name"),
                            "error": " ".join(error.messages),
                        },
                    )
                account.set_password(password)

            account.save()
            return redirect("admin_users")

        return render(
            request,
            "inventory/admin_edit_user.html",
            {
                "account": account,
                "categories": Category.objects.filter(
                    enabled=True
                ).order_by("order", "name"),
                "error": error,
            },
        )

    return render(
        request,
        "inventory/admin_edit_user.html",
        {
            "account": account,
            "categories": Category.objects.filter(
                enabled=True
            ).order_by("order", "name"),
        },
    )
