#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2015, Maykel Moya <mmoya@mmoya.org>
# Sponsored by ShuttleCloud http://shuttlecloud.com/
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: couchdb_user
short_description: Add or remove CouchDB users.
description:
   - Add or remove CouchDB users from a remote host.
version_added: "2.2"
author: "Maykel Moya, @mmoya"
options:
  name:
    description:
      - name of the user to add or remove
    required: true
  password:
    description:
      - password of the user
    required: false
    default: null
  roles:
    description
      - list of roles of the user
    required: false
    default: []
  login_user:
    description:
      - The username used to authenticate to CouchDB
    required: false
    default: null
  login_password:
    description:
      - The password used to authenticate to CouchDB
    required: false
    default: null
  login_host:
    description:
      - Host of the CouchDB server
    required: false
    default: localhost
  login_port:
    description:
      - Port of the CouchDB server
    required: false
    default: 5984
  state:
    description:
      - The user state
    required: false
    default: present
    choices: [ "present", "absent" ]
notes:
   - Requires the passlib python library on the remote host. In Debian systems
     you can apt-get install python-passlib.
   - Both I(login_user) and I(login_password) are required if you pass one of
     them.
requirements: [ passlib ]
author: Maykel Moya
'''


EXAMPLES = '''
# Create a new user with name 'bob'
- couchdb_user: name=bob password=bar state=present

'''


from binascii import hexlify
import json
from passlib.utils.pbkdf2 import pbkdf2

from ansible.module_utils import urls


# ===========================================
# CouchDB module specific support methods.
#

def couchdb_user_url(host, username):
    """
    Return the REST url of the user account
    """

    return 'http://%s:%s/_users/org.couchdb.user:%s' % (host[0], host[1], username)


def couchdb_user_get(host, credentials, username):
    """
    Return the user object with given username
    """

    url = couchdb_user_url(host, username)

    try:
        r = urls.open_url(url,
                          url_username=credentials[0],
                          url_password=credentials[1])
    except urls.urllib2.HTTPError as e:
        if e.code == 404:
            return None
        else:
            raise

    obj = json.load(r)
    return obj


def couchdb_user_delete(host, credentials, userobj):
    """
    Delete the user account corresponding to userobj
    """

    url = couchdb_user_url(host, userobj['name'])
    url = '%s?rev=%s' % (url, userobj['_rev'])
    urls.open_url(url, method='DELETE',
                  url_username=credentials[0],
                  url_password=credentials[1])
    return True


def couchdb_user_create(host, credentials, username, password=None, roles=None,
                        rev=None, derived_key=None, salt=None,
                        iterations=None):
    """
    Create or update an user account
      - password: the user password.
      - roles: list of role names.
      - rev: if revision is None, a new account will be created, otherwise the
             account will be updated.
      - derived_key: hash of the password.
      - salt: salt used when hashing the password.
      - iterations: iterations of PBKDF2 run. CouchDB uses 10 by default.

      When password field is posted, CouchDB automatically updates derived_key.
      The plaintext is never stored.
    """

    # http://docs.couchdb.org/en/latest/intro/security.html#creating-new-user
    url = couchdb_user_url(host, username)

    if rev is not None:
        url = '%s?rev=%s' % (url, rev)

    if roles is None:
        roles = []

    if type(roles) not in (list, tuple):
        raise TypeError("roles should be a list or tuple")

    data = {
        'name': username,
        'roles': roles,
        'type': 'user',
    }

    if password is not None and derived_key is not None:
        raise ValueError("pass either password or derived_key")

    if iterations is None:
        iterations = 10

    authdata = (derived_key, salt)
    if any(authdata) and not all(authdata):
        raise ValueError("one of derived_key or salt is missing")

    if password is not None:
        data['password'] = password
    elif derived_key is not None:
        data['derived_key'] = derived_key
        data['salt'] = salt
        data['iterations'] = iterations

    urls.open_url(url, data=json.dumps(data), method='PUT',
                  url_username=credentials[0],
                  url_password=credentials[1])

    return True


def couchdb_user_valid_password(plaintext, salt, hash_, rounds=10):
    """
    Check if a given plaintext and salt corresponds to a given hash
    """

    if type(salt) == unicode:
        salt = salt.encode('utf-8')
    hashed = pbkdf2(plaintext, salt, rounds)
    return hexlify(hashed) == hash_


# ===========================================
# Module execution.
#


def main():
    module = AnsibleModule(
        argument_spec=dict(
            login_user=dict(default=None),
            login_password=dict(default=None, no_log=True),
            login_host=dict(default="localhost"),
            login_port=dict(type='int', default=5984),

            name=dict(required=True, aliases=['username']),
            password=dict(required=False, no_log=True),
            roles=dict(required=False, type='list', default=[]),
            state=dict(default="present", choices=["absent", "present"]),
        ),
        required_together=(('login_user', 'login_password'),),
    )

    username = module.params["name"]
    password = module.params["password"]
    roles = module.params["roles"]
    state = module.params["state"]

    if roles is None:
        roles = []

    # see https://github.com/ansible/ansible/issues/9254
    if roles == ['']:
        roles = list()

    login_password = module.params['login_password']
    login_user = module.params['login_user']

    host = (
        module.params['login_host'],
        module.params['login_port']
    )

    credentials = (
        login_user,
        login_password
    )

    changed = False

    try:
        userobj = couchdb_user_get(host, credentials, username)
    except Exception as e:
        module.fail_json(msg="error getting user: " + str(e))

    if userobj is not None:
        if state == "absent":
            try:
                changed = couchdb_user_delete(host, credentials, userobj)
            except Exception as e:
                module.fail_json(msg="error deleting user: " + str(e))
        else:
            # check password and roles
            create_args = {}

            password_scheme = userobj.get('password_scheme', None)
            if password_scheme and password_scheme != 'pbkdf2':
                msg = "unsupported password scheme %s" % password_scheme
                module.fail_json(msg=msg)

            if password is not None:
                if 'derived_key' in userobj:
                    valid_password = couchdb_user_valid_password(
                        password, userobj['salt'], userobj['derived_key'],
                        userobj['iterations'])
                    if not valid_password:
                        create_args['password'] = password
                else:
                    create_args['password'] = password
            else:
                if 'derived_key' in userobj:
                    create_args['password'] = None

            if roles is not None and set(userobj['roles']) != set(roles):
                create_args['roles'] = roles

                # if we sent roles we need to send password info as well,
                # otherwise the current password will be cleared
                if 'derived_key' in userobj and 'password' not in create_args:
                    create_args['derived_key'] = userobj['derived_key']
                    create_args['salt'] = userobj['salt']
                    create_args['iterations'] = userobj['iterations']

            if create_args:
                changed = couchdb_user_create(
                    host=host, credentials=credentials, username=username,
                    rev=userobj['_rev'], **create_args)
    else:
        if state == "present":
            try:
                changed = couchdb_user_create(
                    host, credentials, username, password, roles)
            except Exception as e:
                module.fail_json(msg="error creating user: " + str(e))

    module.exit_json(changed=changed, user=username)


# import module snippets
from ansible.module_utils.basic import *
main()
