import os
import re
from http.client import HTTPSConnection
import socket
import ssl
import json



VALID_CONSENT_TO_TRACK_VALUES = ("yes", "no", "unchanged")


class CertificateError(ValueError):
    """
    Raised when an error occurs when attempting to verify an SSL certificate.
    """
    pass


def _dnsname_to_pat(dn):
    pats = []
    for frag in dn.split(r'.'):
        if frag == '*':
            # When '*' is a fragment by itself, it matches a non-empty dotless
            # fragment.
            pats.append('[^.]+')
        else:
            # Otherwise, '*' matches any dotless fragment.
            frag = re.escape(frag)
            pats.append(frag.replace(r'\*', '[^.]*'))
    return re.compile(r'\A' + r'\.'.join(pats) + r'\Z', re.IGNORECASE)


def match_hostname(cert, hostname):
    """
    This is a backport of the match_hostname() function from Python 3.2,
    essential when using SSL.
    Verifies that *cert* (in decoded format as returned by
    SSLSocket.getpeercert()) matches the *hostname*.  RFC 2818 rules
    are mostly followed, but IP addresses are not accepted for *hostname*.

    CertificateError is raised on failure. On success, the function
    returns nothing.
    """
    if not cert:
        raise ValueError("empty or no certificate")
    dnsnames = []
    san = cert.get('subjectAltName', ())
    for key, value in san:
        if key == 'DNS':
            if _dnsname_to_pat(value).match(hostname):
                return
            dnsnames.append(value)
    if not san:
        # The subject is only checked when subjectAltName is empty
        for sub in cert.get('subject', ()):
            for key, value in sub:
                # XXX according to RFC 2818, the most specific Common Name
                # must be used.
                if key == 'commonName':
                    if _dnsname_to_pat(value).match(hostname):
                        return
                    dnsnames.append(value)
    if len(dnsnames) > 1:
        raise CertificateError("hostname %r "
                               "doesn't match either of %s"
                               % (hostname, ', '.join(map(repr, dnsnames))))
    elif len(dnsnames) == 1:
        raise CertificateError("hostname %r "
                               "doesn't match %r"
                               % (hostname, dnsnames[0]))
    else:
        raise CertificateError("no appropriate commonName or "
                               "subjectAltName fields were found")


class VerifiedHTTPSConnection(HTTPSConnection):
    """
    A connection that includes SSL certificate verification.
    """

    def connect(self):
        self.connection_kwargs = {}
        self.connection_kwargs.update(timeout=self.timeout)
        self.connection_kwargs.update(source_address=self.source_address)

        sock = socket.create_connection(
            (self.host, self.port), **self.connection_kwargs)

        if self._tunnel_host:
            self._tunnel()

        cert_path = os.path.join(os.path.dirname(__file__), 'cacert.pem')

        context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cert_path)
        if hasattr(self, 'cert_file') and hasattr(self, 'key_file') and self.cert_file and self.key_file:
            context.load_cert_chain(certfile=self.cert_file, keyfile=self.key_file)
        self.sock = context.wrap_socket(sock, server_hostname=self.host)

        try:
            match_hostname(self.sock.getpeercert(), self.host)
        except CertificateError:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            raise


def json_to_py(o):
    if isinstance(o,bytes):
        o = json.loads(o.decode('utf-8'))
    if isinstance(o, dict):
        return dict_to_object(o)
    else:
        return dict_to_object({"response": o}).response


def dict_to_object(d):
    """Recursively converts a dict to an object"""
    top = type('CreateSendModel', (object,), d)
    seqs = tuple, list, set, frozenset
    for i, j in list(d.items()):
        if isinstance(j, dict):
            setattr(top, i, dict_to_object(j))
        elif isinstance(j, seqs):
            setattr(top, i, type(j)(dict_to_object(sj)
                                    if isinstance(sj, dict) else sj for sj in j))
        else:
            setattr(top, i, j)
    return top


def validate_consent_to_track(user_input):
    from createsend import ClientError
    if hasattr(user_input, 'lower'):
        user_input = user_input.lower()
    if user_input in VALID_CONSENT_TO_TRACK_VALUES:
        return
    raise ClientError(f"Consent to track value must be one of {VALID_CONSENT_TO_TRACK_VALUES}")


def get_faker(expected_url, filename, status=None, body=None):

    class Faker:
        """Represents a fake web request, including the expected URL, an open 
        function which reads the expected response from a fixture file, and the
        expected response status code."""

        def __init__(self, expected_url, filename, status, body=None):
            self.url = self.createsend_url(expected_url)
            self.filename = filename
            self.status = status
            self.body = body

        def open(self):
            if self.filename:
                return open(f"{os.path.dirname(os.path.dirname(__file__))}/../test/fixtures/{self.filename}", mode='rb').read()
            else:
                return ''

        def createsend_url(self, url):
            if url.startswith("http"):
                return url
            else:
                return "https://api.createsend.com/api/v3.3/%s" % url

    return Faker(expected_url, filename, status, body)
