import os
import unittest


os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("CLICKUP_TOKEN", "test")
os.environ.setdefault("CLICKUP_LIST_ID", "test")

from bot import (
    is_checkin_member_status,
    is_checkin_program_value,
    normalize_store_url,
    program_name_from_value,
)


class StoreUrlTests(unittest.TestCase):
    def test_normalizes_store_product_url_to_origin(self):
        self.assertEqual(
            normalize_store_url(" ExampleStore.com/products/widget?ref=ad#details "),
            "https://examplestore.com/",
        )

    def test_preserves_explicit_http_and_port(self):
        self.assertEqual(
            normalize_store_url("http://shop.example.com:8080/collections/all"),
            "http://shop.example.com:8080/",
        )

    def test_blank_stays_missing(self):
        self.assertEqual(normalize_store_url("  "), "")

    def test_rejects_admin_and_supplier_urls(self):
        rejected = (
            "https://admin.shopify.com/store/example",
            "https://example.myshopify.com/admin/products",
            "https://www.aliexpress.com/item/123.html",
            "https://cjdropshipping.com/product/123",
            "https://www.amazon.co.uk/dp/123",
        )
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_store_url(url)

    def test_rejects_non_public_or_credential_urls(self):
        for url in (
            "localhost/shop",
            "http://127.0.0.1/store",
            "http://10.0.0.1/store",
            "http://169.254.169.254/store",
            "http://shop.local/store",
            "ftp://store.example.com/file",
            "https://user:pw@store.example.com",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_store_url(url)

    def test_trailing_dot_cannot_bypass_supplier_block(self):
        for url in ("https://admin.shopify.com./store/example", "https://www.aliexpress.com./item/123"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_store_url(url)


class ProgramEligibilityTests(unittest.TestCase):
    def test_accelerate_and_accelerate_plus_receive_checkins(self):
        self.assertTrue(is_checkin_program_value(1))
        self.assertTrue(is_checkin_program_value(4))
        self.assertEqual(program_name_from_value(1), "Accelerate")
        self.assertEqual(program_name_from_value(4), "Accelerate Plus")

    def test_other_and_invalid_programs_do_not_receive_checkins(self):
        for value in (None, "", 0, 2, 3, 99, "unknown"):
            with self.subTest(value=value):
                self.assertFalse(is_checkin_program_value(value))

    def test_active_member_statuses_receive_checkins(self):
        for status in ("active", "to do", "hand hold", "needs attention"):
            with self.subTest(status=status):
                self.assertTrue(is_checkin_member_status(status))

    def test_inactive_member_statuses_do_not_receive_checkins(self):
        for status in (
            None,
            "",
            "paused",
            "inactive",
            "refunded",
            "complete",
            "graduated",
            "cancelled",
            "canceled",
            "churned",
            "offboarding",
        ):
            with self.subTest(status=status):
                self.assertFalse(is_checkin_member_status(status))


if __name__ == "__main__":
    unittest.main()
