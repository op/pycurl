# Run a WSGI application in a daemon thread

import sys
import bottle
import threading
import socket
import time as _time

try:
    create_connection = socket.create_connection
except AttributeError:
    # python 2.5
    def create_connection(netloc, timeout=None):
        # XXX ipv4 only
        s = socket.socket()
        if timeout is not None:
            s.settimeout(timeout)
        s.connect(netloc)
        return s

global_stop = False

class Server(bottle.WSGIRefServer):
    def run(self, handler): # pragma: no cover
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        if self.quiet:
            base = self.options.get('handler_class', WSGIRequestHandler)
            class QuietHandler(base):
                def log_request(*args, **kw): pass
            self.options['handler_class'] = QuietHandler
        self.srv = make_server(self.host, self.port, handler, **self.options)
        if sys.version_info[0] == 2 and sys.version_info[1] < 6:
            # python 2.5 has no poll_interval
            # and thus no way to stop the server
            while not global_stop:
                self.srv.handle_request()
        else:
            self.srv.serve_forever(poll_interval=0.1)

def wait_for_network_service(netloc, check_interval, num_attempts):
    ok = False
    for i in range(num_attempts):
        try:
            conn = create_connection(netloc, check_interval)
        except socket.error:
            e = sys.exc_info()[1]
            _time.sleep(check_interval)
        else:
            conn.close()
            ok = True
            break
    return ok

def start_bottle_server(app, port, **kwargs):
    server_thread = ServerThread(app, port, kwargs)
    server_thread.daemon = True
    server_thread.start()
    
    ok = wait_for_network_service(('127.0.0.1', port), 0.1, 10)
    if not ok:
        import warnings
        warnings.warn('Server did not start after 1 second')
    
    return server_thread.server

class ServerThread(threading.Thread):
    def __init__(self, app, port, server_kwargs):
        threading.Thread.__init__(self)
        self.app = app
        self.port = port
        self.server_kwargs = server_kwargs
        self.server = Server(host='localhost', port=self.port, **self.server_kwargs)
    
    def run(self):
        bottle.run(self.app, server=self.server, quiet=True)

started_servers = {}

def app_runner_setup(*specs):
    '''Returns setup and teardown methods for running a list of WSGI
    applications in a daemon thread.
    
    Each argument is an (app, port) pair.
    
    Return value is a (setup, teardown) function pair.
    
    The setup and teardown functions expect to be called with an argument
    on which server state will be stored.
    
    Example usage with nose:
    
    >>> setup_module, teardown_module = \
        runwsgi.app_runner_setup((app_module.app, 8050))
    '''
    
    def setup(self):
        self.servers = []
        for spec in specs:
            if len(spec) == 2:
                app, port = spec
                kwargs = {}
            else:
                app, port, kwargs = spec
            if port in started_servers:
                assert started_servers[port] == (app, kwargs)
            else:
                self.servers.append(start_bottle_server(app, port, **kwargs))
            started_servers[port] = (app, kwargs)
    
    def teardown(self):
        return
        for server in self.servers:
            # if no tests from module were run, there is no server to shut down
            if hasattr(server, 'srv'):
                if hasattr(server.srv, 'shutdown'):
                    server.srv.shutdown()
                else:
                    # python 2.5
                    global global_stop
                    global_stop = True
    
    return [setup, teardown]
