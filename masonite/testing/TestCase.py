import subprocess
import unittest

from orator.orm import Factory
from masonite import env
from contextlib import contextmanager
from .MockRoute import MockRoute
from masonite.testsuite import TestSuite, generate_wsgi
from masonite.helpers.routes import flatten_routes
from urllib.parse import urlencode


class TestCase(unittest.TestCase):

    sqlite = True
    transactions = True
    refreshes_database = False
    _has_setup_database = False

    def setUp(self):
        from wsgi import container
        self.container = container
        self.acting_user = False
        self.factory = Factory()
        self.without_exception_handling()

        if self.sqlite and env('DB_CONNECTION') != 'sqlite':
            raise Exception("Cannot run tests without using the 'sqlite' database.")

        if self._has_setup_database:
            self.setUpFactories()

            self.__class__._has_setup_database = False

        if not self.transactions and self.refreshes_database:
            self.refreshDatabase()

    @classmethod
    def setUpClass(cls):
        cls.staticSetUpDatabase()
        if hasattr(cls, 'setUpFactories'):
            cls._has_setup_database = True
        if not cls.refreshes_database and cls.transactions:
            from config.database import DB
            DB.begin_transaction()

    @classmethod
    def tearDownClass(cls):
        if not cls.refreshes_database and cls.transactions:
            from config.database import DB
            DB.rollback()
        else:
            cls.staticTearDownDatabase()

    def refreshDatabase(self):
        if not self.refreshes_database and self.transactions:
            from config.database import DB
            DB.rollback()
            DB.begin_transaction()
            if hasattr(self, 'setUpFactories'):
                self.setUpFactories()
        else:
            self.tearDownDatabase()
            self.setUpDatabase()

    def make(self, model, factory, amount=50):
        self.registerFactory(model, factory)
        self.makeFactory(model, amount)

    def makeFactory(self, model, amount):
        return self.factory(model, amount).create()

    def registerFactory(self, model, callable_factory):
        self.factory.register(model, callable_factory)

    def setUpDatabase(self):
        self.tearDownDatabase()
        subprocess.call(['craft', 'migrate'])
        if hasattr(self, 'setUpFactories'):
            self.setUpFactories()

    def tearDownDatabase(self):
        subprocess.call(['craft', 'migrate:reset'])

    @staticmethod
    def staticSetUpDatabase():
        subprocess.call(['craft', 'migrate'])

    @staticmethod
    def staticTearDownDatabase():
        subprocess.call(['craft', 'migrate:reset'])

    def tearDown(self):
        if not self.transactions and self.refreshes_database:
            self.tearDownDatabase()

    def get(self, url, params={}):
        self.run_container({
            'PATH_INFO': url,
            'REQUEST_METHOD': 'GET',
            'QUERY_STRING': urlencode(params)
        })
        return self.route(url, 'GET')

    def post(self, url, params={}):
        params.update({'__token': 'tok'})
        self.run_container({
            'PATH_INFO': url,
            'REQUEST_METHOD': 'POST',
            'QUERY_STRING': urlencode(params),
            'HTTP_COOKIE': 'csrf_token=tok',
        })

        self.container.make('Request').request_variables = params
        return self.route(url, 'POST')

    def acting_as(self, user):
        self.acting_user = user
        return self

    def route(self, url, method=False):
        for route in self.container.make('WebRoutes'):
            if route.route_url == url and (method in route.method_type or not method):
                return MockRoute(route, self.container)

    def routes(self, routes):
        self.container.bind('WebRoutes', flatten_routes(self.container.make('WebRoutes') + routes))

    @contextmanager
    def captureOutput(self):
        new_out, new_err = StringIO(), StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = new_out, new_err
            yield sys.stdout, sys.stderr
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def run_container(self, wsgi_values={}):
        wsgi = generate_wsgi()
        wsgi.update(wsgi_values)
        self.container.bind('Environ', wsgi)
        self.container.make('Request')._test_user = self.acting_user
        try:
            for provider in self.container.make('WSGIProviders'):
                self.container.resolve(provider.boot)
        except Exception as e:
            if self._exception_handling:
                self.container.make('ExceptionHandler').load_exception(e)
            else:
                raise e

    def with_exception_handling(self):
        self._exception_handling = True

    def without_exception_handling(self):
        self._exception_handling = False
