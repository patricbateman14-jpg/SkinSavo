import unittest

from fastapi.testclient import TestClient

import main


class PageRouteTests(unittest.TestCase):
    def setUp(self):
        # The HTML shell does not require a database or a Telegram API call.
        # Keep lifespan disabled and never touch the user's local database.
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()

    def test_known_pages_and_deep_refresh_return_uncached_shell(self):
        routes = (
            '/', '/skins', '/skins/1', '/skins/999999999', '/profile',
            '/inventory', '/balance', '/balance/topup', '/history', '/faq', '/admin',
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn('text/html', response.headers['content-type'])
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertIn('data-auth="pending"', response.text)
                self.assertIn('/static/app.js', response.text)

    def test_trailing_slash_redirect_preserves_query(self):
        response = self.client.get('/balance/topup/?amount=25&currency=USD')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.url.path, '/balance/topup')
        self.assertEqual(response.url.params['amount'], '25')
        self.assertEqual(response.url.params['currency'], 'USD')

    def test_unknown_and_invalid_detail_paths_do_not_return_shell(self):
        for route in ('/unknown-page', '/profile/extra', '/skins/nope', '/skins/0', '/skins/-1', '/skins/1/extra'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('text/html', response.headers['content-type'])

    def test_private_api_remains_protected_and_does_not_fall_through(self):
        for route in ('/api/skins', '/api/skins/1', '/api/session', '/api/inventory', '/api/users/1', '/api/missing'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 401)
                self.assertIn('application/json', response.headers['content-type'])
                self.assertNotIn('<html', response.text)

    def test_static_missing_file_and_page_posts_do_not_return_shell(self):
        response = self.client.get('/static/not-a-real-file.js')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('text/html', response.headers['content-type'])
        self.assertEqual(self.client.post('/profile').status_code, 405)


if __name__ == '__main__':
    unittest.main()
