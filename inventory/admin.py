from django.contrib import admin
from .models import (
	Barcode,
	BarcodeSettings,
	Category,
	CategoryAssignment,
	Inventory,
	Product,
	ProductMovement,
	Place,
	ProductField,
	ProductFieldValue,
)

admin.site.register(
	[
		Barcode,
		BarcodeSettings,
		Category,
		CategoryAssignment,
		Inventory,
		Product,
		ProductMovement,
		Place,
		ProductField,
		ProductFieldValue,
	]
)
