from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Barcode(models.Model):
    STATUS_CHOICES = [
        ("unassigned", "Unassigned"),
        ("assigned", "Assigned"),
        ("inactive", "Inactive"),
    ]

    barcode_number = models.CharField(
        max_length=50,
        unique=True
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="unassigned"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):

        return self.barcode_number
class Category(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True
    )

    description = models.TextField(
        blank=True
    )

    enabled = models.BooleanField(
        default=True
    )

    order = models.PositiveIntegerField(
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


class CategoryAssignment(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="category_assignments",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="user_assignments",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "category")
        ordering = ("category__name", "user__username")

    def __str__(self):
        return f"{self.user.username} - {self.category.name}"


class Product(models.Model):
    barcode = models.OneToOneField(
        Barcode,
        on_delete=models.PROTECT,
        related_name="product"
    )

    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True
    )

    product_name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    unit = models.CharField(max_length=50)

    purchase_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    supplier = models.CharField(
        max_length=200,
        blank=True
    )

    description = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.product_name

class ProductField(models.Model):

    FIELD_TYPES = [
        ("text", "Text"),
        ("number", "Number"),
        ("decimal", "Decimal"),
        ("date", "Date"),
        ("boolean", "Yes / No"),
        ("dropdown", "Dropdown"),
    ]

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="fields"
    )

    name = models.CharField(
        max_length=100
    )

    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPES,
        default="text"
    )

    required = models.BooleanField(
        default=False
    )

    enabled = models.BooleanField(
        default=True
    )

    order = models.PositiveIntegerField(
        default=0
    )

    options = models.TextField(
        blank=True,
        help_text="For dropdowns, separate options with commas."
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.category.name} - {self.name}"



class Inventory(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="inventory"
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    location = models.CharField(
        max_length=100,
        blank=True
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.product_name} - {self.quantity}"


class Place(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="places/", blank=True, null=True)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class ProductMovement(models.Model):
    MOVEMENT_TYPES = [
        ("receive", "Received"),
        ("transfer", "Transferred"),
        ("use", "Used"),
        ("return", "Returned"),
        ("adjustment", "Adjusted"),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="movements",
    )
    from_place = models.ForeignKey(
        Place,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departing_movements",
    )
    to_place = models.ForeignKey(
        Place,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="arriving_movements",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MOVEMENT_TYPES,
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )
    quantity_before = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )
    quantity_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )
    from_location = models.CharField(max_length=150, blank=True)
    to_location = models.CharField(max_length=150, blank=True)
    purpose = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    moved_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="product_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.product.product_name} - {self.get_movement_type_display()}"


class BarcodeSettings(models.Model):
    prefix = models.CharField(
        max_length=30,
        default="CN"
    )

    next_number = models.PositiveBigIntegerField(
        default=1
    )

    digits = models.PositiveIntegerField(
        default=6
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.prefix} / {self.next_number} / {self.digits}"

    def generate_code(self):
        return f"{self.prefix}{self.next_number:0{self.digits}d}"

class ProductFieldValue(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="custom_values"
    )

    field = models.ForeignKey(
        ProductField,
        on_delete=models.CASCADE,
        related_name="values"
    )

    value = models.TextField(
        blank=True
    )

    class Meta:
        unique_together = ("product", "field")

    def __str__(self):
        return f"{self.product.product_name} - {self.field.name}"


