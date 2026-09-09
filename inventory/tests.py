from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import (
	Barcode,
	Category,
	Inventory,
	Product,
	ProductField,
	ProductFieldValue,
	ProductMovement,
	Place,
	CategoryAssignment,
)


class InventoryWorkflowTests(TestCase):

	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(
			username="inventory-user",
			password="test-password-123",
		)
		self.client.force_login(self.user)

		self.category = Category.objects.create(name="Kitchen")
		CategoryAssignment.objects.create(
			user=self.user,
			category=self.category,
		)
		self.barcode = Barcode.objects.create(
			barcode_number="DAV000001",
			status="assigned",
		)
		self.product = Product.objects.create(
			barcode=self.barcode,
			product_name="DAV000001",
			category="Kitchen",
			department="Kitchen",
			unit="unit",
		)
		Inventory.objects.create(product=self.product)

	def test_anonymous_users_are_redirected_to_login(self):
		self.client.logout()

		response = self.client.get(reverse("dashboard"))

		self.assertRedirects(
			response,
			f"{reverse('login')}?next={reverse('dashboard')}",
		)

	def test_authenticated_users_can_open_dashboard(self):
		response = self.client.get(reverse("dashboard"))

		self.assertRedirects(
			response,
			reverse("category_dashboard", args=[self.category.id]),
		)

	def test_assigned_user_home_url_opens_assigned_department(self):
		response = self.client.get("/")

		self.assertRedirects(
			response,
			reverse("category_dashboard", args=[self.category.id]),
		)

	def test_assigned_user_sign_in_opens_department_dashboard(self):
		self.client.logout()

		response = self.client.post(
			reverse("login"),
			{
				"username": "inventory-user",
				"password": "test-password-123",
			},
		)

		self.assertRedirects(
			response,
			reverse("category_dashboard", args=[self.category.id]),
		)

	def test_unassigned_user_sign_in_opens_main_dashboard(self):
		unassigned_user = get_user_model().objects.create_user(
			username="login-unassigned",
			password="test-password-123",
		)
		self.client.logout()

		response = self.client.post(
			reverse("login"),
			{
				"username": "login-unassigned",
				"password": "test-password-123",
			},
		)

		self.assertRedirects(response, reverse("dashboard"))

	def test_unassigned_user_sees_assignment_message(self):
		unassigned_user = get_user_model().objects.create_user(
			username="unassigned-user",
			password="test-password-123",
		)
		self.client.force_login(unassigned_user)

		response = self.client.get(reverse("dashboard"))

		self.assertContains(response, "not been assigned a department")

	def test_staff_can_create_and_assign_user_from_custom_page(self):
		staff_user = get_user_model().objects.create_user(
			username="admin-user",
			password="admin-password-123",
			is_staff=True,
		)
		self.client.force_login(staff_user)

		response = self.client.post(
			reverse("admin_users"),
			{
				"action": "create_user",
				"username": "kitchen-user",
				"password": "user-password-123",
			},
		)
		self.assertRedirects(response, reverse("admin_users"))

		created_user = get_user_model().objects.get(username="kitchen-user")
		response = self.client.post(
			reverse("admin_users"),
			{
				"action": "assign_category",
				"user_id": created_user.id,
				"category_id": self.category.id,
			},
		)
		self.assertRedirects(response, reverse("admin_users"))
		self.assertTrue(
			CategoryAssignment.objects.filter(
				user=created_user,
				category=self.category,
			).exists()
		)

	def test_staff_can_edit_user_details_and_password(self):
		staff_user = get_user_model().objects.create_user(
			username="admin-editor",
			password="admin-password-123",
			is_staff=True,
		)
		account = get_user_model().objects.create_user(
			username="old-username",
			password="old-password-123",
		)
		self.client.force_login(staff_user)

		response = self.client.post(
			reverse("admin_edit_user", args=[account.id]),
			{
				"username": "new-username",
				"first_name": "New",
				"last_name": "Name",
				"email": "new@example.com",
				"password": "new-password-123",
				"is_active": "on",
			},
		)

		self.assertRedirects(response, reverse("admin_users"))
		account.refresh_from_db()
		self.assertEqual(account.first_name, "New")
		self.assertEqual(account.email, "new@example.com")
		self.assertTrue(account.check_password("new-password-123"))
		self.assertTrue(
			self.client.login(
				username="new-username",
				password="new-password-123",
			)
		)

	def test_regular_user_cannot_generate_barcodes(self):
		response = self.client.get(reverse("generate_barcodes"))

		self.assertRedirects(
			response,
			f"{reverse('admin_login')}?next={reverse('generate_barcodes')}",
		)

	def test_user_can_open_an_assigned_category_dashboard(self):
		response = self.client.get(
			reverse("category_dashboard", args=[self.category.id])
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Kitchen")

	def test_assigned_user_scan_skips_department_selection(self):
		field = ProductField.objects.create(
			category=self.category,
			name="Asset Tag",
			required=True,
		)
		unassigned_barcode = Barcode.objects.create(
			barcode_number="DAV000002",
			status="unassigned",
		)

		response = self.client.get(
			reverse("scan_barcode"),
			{"barcode": unassigned_barcode.barcode_number},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Register Product")
		self.assertContains(response, f"field_{field.id}")
		self.assertNotContains(response, "Select Department")

	def test_user_is_redirected_from_unassigned_category_dashboard(self):
		other_category = Category.objects.create(name="Front Office")

		response = self.client.get(
			reverse("category_dashboard", args=[other_category.id])
		)

		self.assertRedirects(response, reverse("dashboard"))

	def test_regular_users_cannot_use_admin_dashboard(self):
		response = self.client.get(reverse("admin_dashboard"))

		self.assertRedirects(
			response,
			f"{reverse('admin_login')}?next={reverse('admin_dashboard')}",
		)
		response = self.client.get(reverse("admin_login"))
		self.assertContains(response, "does not have administrator access")

	def test_staff_users_can_sign_in_to_admin_dashboard(self):
		staff_user = get_user_model().objects.create_user(
			username="admin-user",
			password="admin-password-123",
			is_staff=True,
		)
		self.client.logout()

		response = self.client.post(
			reverse("admin_login"),
			{
				"username": "admin-user",
				"password": "admin-password-123",
			},
		)

		self.assertRedirects(response, reverse("dashboard"))
		response = self.client.get(reverse("dashboard"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Administrator Controls")

	def test_staff_user_can_open_main_dashboard_directly(self):
		staff_user = get_user_model().objects.create_user(
			username="direct-admin-user",
			password="admin-password-123",
			is_staff=True,
		)
		self.client.force_login(staff_user)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Administrator Controls")

		response = self.client.get(reverse("dashboard_page"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Administrator Controls")

	def test_product_details_show_dynamic_values(self):
		field = ProductField.objects.create(
			category=self.category,
			name="Brand",
			required=True,
		)
		ProductFieldValue.objects.create(
			product=self.product,
			field=field,
			value="Acme",
		)

		response = self.client.get(
			reverse("scan_barcode"),
			{
				"barcode": self.barcode.barcode_number,
				"department": self.category.id,
			},
		)

		self.assertContains(response, "Brand")
		self.assertContains(response, "Acme")

	def test_edit_product_updates_dynamic_values(self):
		field = ProductField.objects.create(
			category=self.category,
			name="Brand",
			required=True,
		)

		response = self.client.post(
			reverse("edit_product", args=[self.product.id]),
			{
				"product_name": "Updated Product",
				"description": "Updated description",
				f"field_{field.id}": "Acme",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Updated Product")
		self.assertContains(response, "Acme")
		self.product.refresh_from_db()
		self.assertEqual(self.product.product_name, "Updated Product")
		self.assertEqual(self.product.description, "Updated description")
		self.assertEqual(
			ProductFieldValue.objects.get(
				product=self.product,
				field=field,
			).value,
			"Acme",
		)

	def test_product_details_show_current_stock(self):
		response = self.client.post(
			reverse("edit_product", args=[self.product.id]),
			{
				"product_name": "Laptop",
				"description": "Hotel room laptop",
				"quantity": "20",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "20")

	def test_product_movement_updates_stock_and_location(self):
		response = self.client.post(
			reverse("add_product_movement", args=[self.product.id]),
			{
				"movement_type": "receive",
				"quantity": "20",
				"to_location": "Storage A",
				"purpose": "Replacement stock",
				"notes": "Received from supplier",
			},
		)

		self.assertRedirects(
			response,
			reverse("product_details", args=[self.product.id]),
		)
		self.product.inventory.refresh_from_db()
		self.assertEqual(str(self.product.inventory.quantity), "20.00")
		self.assertEqual(self.product.inventory.location, "Storage A")
		movement = ProductMovement.objects.get(product=self.product)
		self.assertEqual(movement.purpose, "Replacement stock")

		response = self.client.post(
			reverse("add_product_movement", args=[self.product.id]),
			{
				"movement_type": "use",
				"quantity": "3",
				"to_location": "Room 204",
				"purpose": "Guest room setup",
			},
		)
		self.assertRedirects(
			response,
			reverse("product_details", args=[self.product.id]),
		)
		self.product.inventory.refresh_from_db()
		self.assertEqual(str(self.product.inventory.quantity), "17.00")
		self.assertEqual(self.product.inventory.location, "Room 204")

	def test_admin_can_create_place_and_use_it_for_movement(self):
		staff_user = get_user_model().objects.create_user(
			username="place-admin",
			password="admin-password-123",
			is_staff=True,
		)
		self.client.force_login(staff_user)

		response = self.client.post(
			reverse("places"),
			{
				"name": "Main Store",
				"description": "Central hotel storage room",
			},
		)
		self.assertRedirects(response, reverse("places"))
		place = Place.objects.get(name="Main Store")

		self.client.force_login(self.user)
		response = self.client.post(
			reverse("add_product_movement", args=[self.product.id]),
			{
				"movement_type": "receive",
				"quantity": "4",
				"to_place_id": place.id,
				"purpose": "New hotel stock",
			},
		)
		self.assertRedirects(
			response,
			reverse("product_details", args=[self.product.id]),
		)
		movement = ProductMovement.objects.get(product=self.product)
		self.assertEqual(movement.to_place, place)
		self.assertEqual(movement.to_location, "Main Store")

	def test_admin_can_save_pinned_place_coordinates(self):
		staff_user = get_user_model().objects.create_user(
			username="gps-admin",
			password="admin-password-123",
			is_staff=True,
		)
		self.client.force_login(staff_user)

		response = self.client.post(
			reverse("places"),
			{
				"name": "Managers Office",
				"description": "Administration office",
				"latitude": "-1.286389",
				"longitude": "36.817223",
			},
		)

		self.assertRedirects(response, reverse("places"))
		place = Place.objects.get(name="Managers Office")
		self.assertEqual(str(place.latitude), "-1.286389")
		self.assertEqual(str(place.longitude), "36.817223")

	def test_deleting_field_removes_saved_values(self):
		self.user.is_staff = True
		self.user.save(update_fields=["is_staff"])
		field = ProductField.objects.create(
			category=self.category,
			name="Brand",
		)
		ProductFieldValue.objects.create(
			product=self.product,
			field=field,
			value="Acme",
		)

		response = self.client.post(
			reverse("delete_product_field", args=[field.id])
		)

		self.assertRedirects(response, reverse("product_fields"))
		self.assertFalse(ProductField.objects.filter(id=field.id).exists())
		self.assertFalse(
			ProductFieldValue.objects.filter(product=self.product).exists()
		)

	def test_releasing_product_makes_barcode_unassigned(self):
		self.user.is_staff = True
		self.user.save(update_fields=["is_staff"])
		self.barcode.status = "assigned"
		self.barcode.save(update_fields=["status"])

		response = self.client.post(
			reverse("release_product", args=[self.product.id])
		)

		self.assertRedirects(response, reverse("dashboard"))
		self.barcode.refresh_from_db()
		self.assertEqual(self.barcode.status, "unassigned")
		self.assertFalse(Product.objects.filter(id=self.product.id).exists())

	def test_category_deletion_is_blocked_when_products_exist(self):
		self.user.is_staff = True
		self.user.save(update_fields=["is_staff"])
		response = self.client.post(
			reverse("delete_category", args=[self.category.id])
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(Category.objects.filter(id=self.category.id).exists())
		self.assertContains(response, "Cannot delete Kitchen")

	def test_empty_category_can_be_deleted(self):
		self.user.is_staff = True
		self.user.save(update_fields=["is_staff"])
		empty_category = Category.objects.create(name="Front Office")

		response = self.client.post(
			reverse("delete_category", args=[empty_category.id])
		)

		self.assertRedirects(response, reverse("categories"))
		self.assertFalse(
			Category.objects.filter(id=empty_category.id).exists()
		)
