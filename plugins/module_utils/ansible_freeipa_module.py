#!/usr/bin/python
# -*- coding: utf-8 -*-

# Authors:
#   Sergio Oliveira Campos <seocam@redhat.com>
#   Thomas Woerner <twoerner@redhat.com>
#
# Copyright (C) 2019  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import os
import uuid
import tempfile
import shutil
import gssapi
from datetime import datetime
from pprint import pformat
from ipalib import api
from ipalib import errors as ipalib_errors  # noqa
from ipalib.config import Env
from ipalib.constants import DEFAULT_CONFIG, LDAP_GENERALIZED_TIME_FORMAT
try:
    from ipalib.install.kinit import kinit_password, kinit_keytab
except ImportError:
    from ipapython.ipautil import kinit_password, kinit_keytab
from ipapython.ipautil import run
from ipaplatform.paths import paths
from ipalib.krb_utils import get_credentials_if_valid
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_text
try:
    from ipalib.x509 import Encoding
except ImportError:
    from cryptography.hazmat.primitives.serialization import Encoding
import socket
import base64
import six


if six.PY3:
    unicode = str


def valid_creds(module, principal):  # noqa
    """
    Get valid credintials matching the princial, try GSSAPI first
    """
    if "KRB5CCNAME" in os.environ:
        ccache = os.environ["KRB5CCNAME"]
        module.debug('KRB5CCNAME set to %s' % ccache)

        try:
            cred = gssapi.Credentials(usage='initiate',
                                      store={'ccache': ccache})
        except gssapi.raw.misc.GSSError as e:
            module.fail_json(msg='Failed to find default ccache: %s' % e)
        else:
            module.debug("Using principal %s" % str(cred.name))
            return True

    elif "KRB5_CLIENT_KTNAME" in os.environ:
        keytab = os.environ.get('KRB5_CLIENT_KTNAME', None)
        module.debug('KRB5_CLIENT_KTNAME set to %s' % keytab)

        ccache_name = "MEMORY:%s" % str(uuid.uuid4())
        os.environ["KRB5CCNAME"] = ccache_name

        try:
            cred = kinit_keytab(principal, keytab, ccache_name)
        except gssapi.raw.misc.GSSError as e:
            module.fail_json(msg='Kerberos authentication failed : %s' % e)
        else:
            module.debug("Using principal %s" % str(cred.name))
            return True

    creds = get_credentials_if_valid()
    if creds and \
       creds.lifetime > 0 and \
       "%s@" % principal in creds.name.display_as(creds.name.name_type):
        return True
    return False


def temp_kinit(principal, password):
    """
    kinit with password using a temporary ccache
    """
    if not password:
        raise RuntimeError("The password is not set")
    if not principal:
        principal = "admin"

    ccache_dir = tempfile.mkdtemp(prefix='krbcc')
    ccache_name = os.path.join(ccache_dir, 'ccache')

    try:
        kinit_password(principal, password, ccache_name)
    except RuntimeError as e:
        raise RuntimeError("Kerberos authentication failed: {}".format(e))

    return ccache_dir, ccache_name


def temp_kdestroy(ccache_dir, ccache_name):
    """
    Destroy temporary ticket and remove temporary ccache
    """
    if ccache_name is not None:
        run([paths.KDESTROY, '-c', ccache_name], raiseonerr=False)
    if ccache_dir is not None:
        shutil.rmtree(ccache_dir, ignore_errors=True)


def api_connect(context=None):
    """
    Create environment, initialize api and connect to ldap2
    """
    env = Env()
    env._bootstrap()
    env._finalize_core(**dict(DEFAULT_CONFIG))

    # available contexts are 'server', 'ansible-freeipa' and 'cli_installer'
    if context is None:
        context = 'server'

    api.bootstrap(context=context, debug=env.debug, log=None)
    api.finalize()

    if api.env.in_server:
        backend = api.Backend.ldap2
    else:
        backend = api.Backend.rpcclient

    if not backend.isconnected():
        backend.connect()


def api_command(module, command, name, args):
    """
    Call ipa.Command
    """
    return api.Command[command](name, **args)


def api_command_no_name(module, command, args):
    """
    Call ipa.Command without a name.
    """
    return api.Command[command](**args)


def api_check_param(command, name):
    """
    Return if param exists in command param list
    """
    return name in api.Command[command].params


def execute_api_command(module, principal, password, command, name, args):
    """
    Get KRB ticket if not already there, initialize api, connect,
    execute command and destroy ticket again if it has been created also.
    """
    ccache_dir = None
    ccache_name = None
    try:
        if not valid_creds(module, principal):
            ccache_dir, ccache_name = temp_kinit(principal, password)
        api_connect()

        return api_command(module, command, name, args)
    except Exception as e:
        module.fail_json(msg=str(e))

    finally:
        temp_kdestroy(ccache_dir, ccache_name)


def date_format(value):
    accepted_date_formats = [
        LDAP_GENERALIZED_TIME_FORMAT,  # generalized time
        '%Y-%m-%dT%H:%M:%SZ',  # ISO 8601, second precision
        '%Y-%m-%dT%H:%MZ',     # ISO 8601, minute precision
        '%Y-%m-%dZ',           # ISO 8601, date only
        '%Y-%m-%d %H:%M:%SZ',  # non-ISO 8601, second precision
        '%Y-%m-%d %H:%MZ',     # non-ISO 8601, minute precision
    ]

    for date_format in accepted_date_formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            pass
    raise ValueError("Invalid date '%s'" % value)


def compare_args_ipa(module, args, ipa):  # noqa
    for key in args.keys():
        if key not in ipa:
            return False
        else:
            arg = args[key]
            ipa_arg = ipa[key]
            # If ipa_arg is a list and arg is not, replace arg
            # with list containing arg. Most args in a find result
            # are lists, but not all.
            if isinstance(ipa_arg, tuple):
                ipa_arg = list(ipa_arg)
            if isinstance(ipa_arg, list):
                if not isinstance(arg, list):
                    arg = [arg]
                if isinstance(ipa_arg[0], str) and isinstance(arg[0], int):
                    arg = [to_text(_arg) for _arg in arg]
                if isinstance(ipa_arg[0], unicode) and isinstance(arg[0], int):
                    arg = [to_text(_arg) for _arg in arg]
            # module.warn("%s <=> %s" % (repr(arg), repr(ipa_arg)))
            try:
                arg_set = set(arg)
                ipa_arg_set = set(ipa_arg)
            except TypeError:
                if arg != ipa_arg:
                    # module.warn("%s != %s" % (repr(arg), repr(ipa_arg)))
                    return False
            else:
                if arg_set != ipa_arg_set:
                    # module.warn("%s != %s" % (repr(arg), repr(ipa_arg)))
                    return False

        # module.warn("%s == %s" % (repr(arg), repr(ipa_arg)))

    return True


def _afm_convert(value):
    if value is not None:
        if isinstance(value, list):
            return [_afm_convert(x) for x in value]
        elif isinstance(value, dict):
            return {_afm_convert(k): _afm_convert(v) for k, v in value.items()}
        elif isinstance(value, str):
            return to_text(value)
        else:
            return value
    else:
        return value


def module_params_get(module, name):
    return _afm_convert(module.params.get(name))


def api_get_realm():
    return api.env.realm


def gen_add_del_lists(user_list, res_list):
    """
    Generate the lists for the addition and removal of members using the
    provided user and ipa settings
    """
    add_list = list(set(user_list or []) - set(res_list or []))
    del_list = list(set(res_list or []) - set(user_list or []))

    return add_list, del_list


def encode_certificate(cert):
    """
    Encode a certificate using base64 with also taking FreeIPA and Python
    versions into account
    """
    if isinstance(cert, (str, unicode, bytes)):
        encoded = base64.b64encode(cert)
    else:
        encoded = base64.b64encode(cert.public_bytes(Encoding.DER))
    if not six.PY2:
        encoded = encoded.decode('ascii')
    return encoded


def is_ipv4_addr(ipaddr):
    """
    Test if figen IP address is a valid IPv4 address
    """
    try:
        socket.inet_pton(socket.AF_INET, ipaddr)
    except socket.error:
        return False
    return True


def is_ipv6_addr(ipaddr):
    """
    Test if figen IP address is a valid IPv6 address
    """
    try:
        socket.inet_pton(socket.AF_INET6, ipaddr)
    except socket.error:
        return False
    return True


class AnsibleFreeIPAParams(object):
    def __init__(self, ansible_module):
        self.ansible_module = ansible_module

    @property
    def names(self):
        return self.name

    def __getattr__(self, name):
        param = self.ansible_module.params.get(name)
        if param:
            return _afm_convert(param)


class FreeIPABaseModule(AnsibleModule):
    def __init__(self, *args, **kwargs):
        super(FreeIPABaseModule, self).__init__(*args, **kwargs)

        self.ccache_dir = None
        self.ccache_name = None
        self.changed = False
        self.exit_args = {}
        self.ipa_connected = False
        self._debug = True

        self.ipa_params = AnsibleFreeIPAParams(self)
        self.ipa_commands = []

    def check_ipa_params(self):
        pass

    def define_ipa_commands(self):
        pass

    def api_command(self, command, name=None, args=None):
        if args is None:
            args = {}

        if name is None:
            return api_command_no_name(self, command, args)

        return api_command(self, command, name, args)

    def __enter__(self):
        principal = self.ipa_params.ipaadmin_principal
        password = self.ipa_params.ipaadmin_password

        try:
            if not valid_creds(self, principal):
                self.ccache_dir, self.ccache_name = temp_kinit(
                    principal, password,
                )

            api_connect()

        except Exception as excpt:
            self.fail_json(msg=str(excpt))
        else:
            self.ipa_connected = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.fail_json(msg=str(exc_val))

        # TODO: shouldn't we also disconnect from api backend?
        temp_kdestroy(self.ccache_dir, self.ccache_name)

        self.exit_json(changed=self.changed, user=self.exit_args)

    def get_command_errors(self, command, result):
        # Get all errors
        # All "already a member" and "not a member" failures in the
        # result are ignored. All others are reported.
        errors = []
        for item in result.get("failed", tuple()):
            failed_item = result["failed"][item]
            for member_type in failed_item:
                for member, failure in failed_item[member_type]:
                    if "already a member" in failure \
                       or "not a member" in failure:
                        continue
                    errors.append("%s: %s %s: %s" % (
                        command, member_type, member, failure))

        if len(errors) > 0:
            self.fail_json(", ".join("errors"))

    def _run_ipa_commands(self):
        result = None

        for name, command, args in self.ipa_commands:
            try:
                result = self.api_command(command, name, args)
            except Exception as excpt:
                self.fail_json(
                    msg="%s: %s: %s" % (command, name, str(excpt))
                )
            else:
                if "completed" in result:
                    if result["completed"] > 0:
                        self.changed = True
                else:
                    self.changed = True

            self.get_command_errors(command, result)

    def plog(self, value):
        self.log(pformat(value))

    def pdebug(self, value):
        self.debug(pformat(value))

    def ipa_run(self):
        with self:
            if not self.ipa_connected:
                return

            self.check_ipa_params()
            self.define_ipa_commands()
            self._run_ipa_commands()
