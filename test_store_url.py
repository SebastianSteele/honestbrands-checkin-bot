import os
import unittest


os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("CLICKUP_TOKEN", "test")
os.environ.setdefault("CLICKUP_LIST_ID", "test")

from bot import normalize_store_url


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
        for url in ("localhost/shop", "ftp://store.example.com/file", "https://user:pw@store.example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_store_url(url)


if __name__ == "__main__":
    unittest.main()
