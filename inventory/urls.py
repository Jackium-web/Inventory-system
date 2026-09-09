from django.urls import path
from .views import (
    add_product_field,
    categories,
    category_fields,
    add_category,
    dashboard,
    edit_category,
    edit_product_field,
    generate_barcodes,
    barcode_image,
    print_barcodes,
    product_fields,
    scan_barcode,
    edit_product,
    product_details,
    add_product_movement,
    release_product,
    barcode_settings,
    toggle_product_field,
    edit_product_field,
    toggle_product_field,
    assigned_items,
    generate_barcode_pdf,
    delete_product_field,
    category_dashboard,
    delete_category,
    admin_users,
    admin_edit_user,
    places,
    delete_place,
)

urlpatterns = [
    path(
        "generate/",
        generate_barcodes,
        name="generate_barcodes"
    ),

    path(
        "barcode/<str:barcode_number>/",
        barcode_image,
        name="barcode_image"
    ),

    path(
        "print/",
        print_barcodes,
        name="print_barcodes"
    ),

    path(
        "scan/",
        scan_barcode,
        name="scan_barcode"
    ),

    path(
        "edit/<int:product_id>/",
        edit_product,
        name="edit_product"
    ),

    path(
        "product/<int:product_id>/",
        product_details,
        name="product_details"
    ),

    path(
        "product/<int:product_id>/movement/",
        add_product_movement,
        name="add_product_movement",
    ),

    path(
        "manage/users/",
        admin_users,
        name="admin_users",
    ),

    path(
        "manage/users/<int:user_id>/edit/",
        admin_edit_user,
        name="admin_edit_user",
    ),

    path(
        "manage/places/",
        places,
        name="places",
    ),

    path(
        "manage/places/<int:place_id>/delete/",
        delete_place,
        name="delete_place",
    ),

    path(
        "release/<int:product_id>/",
        release_product,
        name="release_product"
    ),

    path(
        "barcode-settings/",
        barcode_settings,
        name="barcode_settings"
    ),
    path(
        "assigned-items/", 
        assigned_items,
        name="assigned_items"
    ),

    path(
        "",
        dashboard,
        name="dashboard"
    ),

    path(
        "dashboard/",
        dashboard,
        name="dashboard_page"
    ),

    path(
        "product-fields/",
        product_fields,
        name="product_fields"
    ),

    path(
        "product-fields/add/",
        add_product_field,
        name="add_product_field"
    ),

    path(
        "product-fields/<int:field_id>/edit/",
        edit_product_field,
        name="edit_product_field"
    ),

    path(
        "product-fields/<int:field_id>/toggle/",
        toggle_product_field,
        name="toggle_product_field"
    ),

    path(
        "product-fields/<int:field_id>/delete/",
        delete_product_field,
        name="delete_product_field"
    ),

    path(
        "categories/",
        categories,
        name="categories"
    ),

    path(
        "categories/<int:category_id>/fields/",
        category_fields,
        name="category_fields"
    ),

    path(
        "categories/<int:category_id>/",
        category_dashboard,
        name="category_dashboard"
    ),

    path(
        "categories/add/",
        add_category,
        name="add_category"
    ),
    path(
        "categories/<int:category_id>/edit/",
        edit_category,
        name="edit_category"
    ),

    path(
        "categories/<int:category_id>/delete/",
        delete_category,
        name="delete_category"
    ),

    path(
        "print-barcodes/pdf/",
        generate_barcode_pdf,
        name="generate_barcode_pdf"
    ),
]