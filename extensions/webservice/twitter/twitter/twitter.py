# Copyright (c) 2013 Martin Abente Lahaye. - tch@sugarlabs.org
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import json
import urllib
import time
import random
import hashlib
import hmac
import binascii
import pycurl

from gi.repository import GObject
from urlparse import parse_qsl


class TwrAccount:

    @classmethod
    def set_secrets(cls, c_key, c_secret, a_key, a_secret):
        cls._consumer_key = c_key
        cls._consumer_secret = c_secret
        cls._access_key = a_key
        cls._access_secret = a_secret

    @classmethod
    def _oauth_signature(cls, method, url, params):
        recipe = (
            method,
            TwrAccount._percent(url),
            TwrAccount._percent(TwrAccount._string_params(params)))

        raw = '&'.join(recipe)
        key = '%s&%s' % (TwrAccount._percent(cls._consumer_secret),
                         TwrAccount._percent(cls._access_secret))

        hashed = hmac.new(key, raw, hashlib.sha1)
        signature = binascii.b2a_base64(hashed.digest())[:-1]

        return signature

    @classmethod
    def authorization_header(cls, method, url, request_params):
        oauth_params = {
            'oauth_nonce': TwrAccount._nonce(),
            'oauth_timestamp': TwrAccount._timestamp(),
            'oauth_consumer_key': cls._consumer_key,
            'oauth_version': '1.0',
            'oauth_token': cls._access_key,
            'oauth_signature_method': 'HMAC-SHA1'}

        params = dict(oauth_params.items() + request_params)
        params['oauth_signature'] = cls._oauth_signature(method, url, params)

        header = 'OAuth %s' % ', '.join(['%s="%s"' % \
                              (k, TwrAccount._percent(v)) \
                              for k, v in sorted(params.iteritems())])

        return header

    @staticmethod
    def _percent(string):
        return urllib.quote(str(string), safe='~')

    @staticmethod
    def _utf8(string):
        return str(string).encode("utf-8")

    @staticmethod
    def _nonce(length=8):
        return ''.join([str(random.randint(0, 9)) for i in range(length)])

    @staticmethod
    def _timestamp():
        return int(time.time())

    @staticmethod
    def _string_params(params):
        key_values = [(TwrAccount._percent(TwrAccount._utf8(k)), \
                       TwrAccount._percent(TwrAccount._utf8(v))) \
                       for k, v in params.items()]
        key_values.sort()

        return '&'.join(['%s=%s' % (k, v) for k, v in key_values])


class TwrStatusNotCreated(Exception):
    pass


class TwrStatusAlreadyCreated(Exception):
    pass


class TwrStatusNotFound(Exception):
    pass


class TwrStatusError(Exception):
    pass


class TwrTimelineError(Exception):
    pass


class TwrOauthError(Exception):
    pass


class TwrSearchError(Exception):
    pass


class TwrOauth(GObject.GObject):

    REQUEST_TOKEN_URL = 'https://api.twitter.com/oauth/request_token'
    AUTHORIZATION_URL = 'https://api.twitter.com/oauth/'\
                        'authorize?oauth_token=%s'
    ACCESS_TOKEN_URL = 'https://api.twitter.com/oauth/access_token'

    __gsignals__ = {
        'request-downloaded':       (GObject.SignalFlags.RUN_FIRST,
                                    None, ([object])),
        'request-downloaded-failed': (GObject.SignalFlags.RUN_FIRST,
                                    None, ([str])),
        'access-downloaded':        (GObject.SignalFlags.RUN_FIRST,
                                    None, ([object])),
        'access-downloaded-failed': (GObject.SignalFlags.RUN_FIRST,
                                    None, ([str]))}

    def request_token(self):
        GObject.idle_add(self._get,
                        self.REQUEST_TOKEN_URL,
                        [],
                        self.__completed_cb,
                        self.__failed_cb,
                        'request-downloaded',
                        'request-downloaded-failed')

    def access_token(self, verifier):
        params = [('oauth_callback', ('oob')),
                  ('oauth_verifier', (verifier))]

        GObject.idle_add(self._post,
                        self.ACCESS_TOKEN_URL,
                        params,
                        None,
                        self.__completed_cb,
                        self.__failed_cb,
                        'access-downloaded',
                        'access-downloaded-failed')

    def _get(self, url, params,
            completed_cb, failed_cb, completed_data, failed_data):

        object = TwrObject()
        object.connect('transfer-completed', completed_cb, completed_data)
        object.connect('transfer-failed', failed_cb, failed_data)
        object.request('GET', url, params)

    def _post(self, url, params, filepath,
            completed_cb, failed_cb, completed_data, failed_data):

        object = TwrObject()
        object.connect('transfer-completed', completed_cb, completed_data)
        object.connect('transfer-failed', failed_cb, failed_data)
        object.request('POST', url, params, filepath)

    def __completed_cb(self, object, data, signal):
        try:
            info = dict(parse_qsl(data))

            if isinstance(info, dict) and ('errors' in info.keys()):
                raise TwrOauthError(str(info['errors']))

            self.emit(signal, info)
        except Exception, e:
            print 'TwrOauth.__completed_cb crashed with %s' % str(e)

    def __failed_cb(self, object, message, signal):
        self.emit(signal, message)


class TwrObject(GObject.GObject):

    __gsignals__ = {
        'transfer-completed': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'transfer-progress': (GObject.SignalFlags.RUN_FIRST, None, \
                             ([float, float, str])),
        'transfer-failed': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'transfer-started': (GObject.SignalFlags.RUN_FIRST, None, ([]))}

    def _gen_header(self, method, url, params=[]):
        authorization = TwrAccount.authorization_header(method, url, params)
        headers = ['Host: api.twitter.com',
                   'Authorization: %s' % authorization]

        return headers

    def _update_cb(self, down_total, down_done, up_total, up_done, states):

        if 2 in states:
            return

        total = up_total
        done = up_done
        mode = 'upload'

        if 1 in states:
            total = down_total
            done = down_done
            mode = 'download'

        if total == 0:
            return

        if 0 not in states:
            self.emit('transfer-started')
            states.append(0)

        self.emit('transfer-progress', total, done, mode)

        state = states[-1]
        if total == done and state in states and len(states) == state + 1:
            states.append(state + 1)

    def request(self, method, url, params, filepath=None):
        c = pycurl.Curl()

        if method == 'POST':
            c.setopt(c.POST, 1)
            c.setopt(c.HTTPHEADER, self._gen_header(method, url))

            if filepath is not None:
                params += [("media", (c.FORM_FILE, filepath))]

            if params is not None:
                c.setopt(c.HTTPPOST, params)
            else:
                c.setopt(c.POSTFIELDS, '')
        else:
            c.setopt(c.HTTPGET, 1)
            c.setopt(c.HTTPHEADER, self._gen_header(method, url, params))
            url += '?%s' % urllib.urlencode(params)

        # XXX hack to trace transfer states
        states = []

        def pre_update_cb(*args):
            args = list(args) + [states]
            self._update_cb(*args)

        #XXX hack to write multiple responses
        buffer = []

        def __write_cb(data):
            buffer.append(data)

        c.setopt(c.URL, url)
        c.setopt(c.NOPROGRESS, 0)
        c.setopt(c.PROGRESSFUNCTION, pre_update_cb)
        c.setopt(c.WRITEFUNCTION, __write_cb)
        #c.setopt(c.VERBOSE, True)

        try:
            c.perform()
        except pycurl.error, e:
            self.emit('transfer-failed', str(e))
        else:
            code = c.getinfo(c.HTTP_CODE)
            if code != 200:
                self.emit('transfer-failed', 'HTTP code %s' % code)
        finally:
            self.emit('transfer-completed', ''.join(buffer))
            c.close()


class TwrSearch(GObject.GObject):

    TWEETS_URL = 'https://api.twitter.com/1.1/search/tweets.json'

    __gsignals__ = {
        'tweets-downloaded':        (GObject.SignalFlags.RUN_FIRST,
                                    None, ([object])),
        'tweets-downloaded-failed': (GObject.SignalFlags.RUN_FIRST,
                                    None, ([str]))}

    def tweets(self, q, count=None, since_id=None, max_id=None):
        params = [('q', (q))]

        if count is not None:
            params += [('count', (count))]
        if since_id is not None:
            params += [('since_id', (since_id))]
        if max_id is not None:
            params += [('max_id', (max_id))]

        GObject.idle_add(self._get,
                        self.TWEETS_URL,
                        params,
                        self.__completed_cb,
                        self.__failed_cb,
                        'tweets-downloaded',
                        'tweets-downloaded-failed')

    def _get(self, url, params, completed_cb, failed_cb,
            completed_data, failed_data):

        object = TwrObject()
        object.connect('transfer-completed', completed_cb, completed_data)
        object.connect('transfer-failed', failed_cb, failed_data)
        object.request('GET', url, params)

    def __completed_cb(self, object, data, signal):
        try:
            info = json.loads(data)

            if isinstance(info, dict) and ('errors' in info.keys()):
                raise TwrSearchError(str(info['errors']))

            self.emit(signal, info)
        except Exception, e:
            print 'TwrSearch.__completed_cb crashed with %s' % str(e)

    def __failed_cb(self, object, message, signal):
        self.emit(signal, message)


class TwrStatus(GObject.GObject):
    UPDATE_URL = 'https://api.twitter.com/1.1/statuses/update.json'
    UPDATE_WITH_MEDIA_URL = 'https://api.twitter.com/1.1/statuses/'\
                            'update_with_media.json'
    SHOW_URL = 'https://api.twitter.com/1.1/statuses/show.json'
    RETWEET_URL = 'https://api.twitter.com/1.1/statuses/retweet/%s.json'
    RETWEETS_URL = 'https://api.twitter.com/1.1/statuses/retweets/%s.json'
    DESTROY_URL = 'https://api.twitter.com/1.1/statuses/destroy/%s.json'

    __gsignals__ = {
        'status-updated':             (GObject.SignalFlags.RUN_FIRST,
                                      None, ([object])),
        'status-updated-failed':      (GObject.SignalFlags.RUN_FIRST,
                                      None, ([str])),
        'status-downloaded':          (GObject.SignalFlags.RUN_FIRST,
                                      None, ([object])),
        'status-downloaded-failed':   (GObject.SignalFlags.RUN_FIRST,
                                      None, ([str])),
        'status-destroyed':           (GObject.SignalFlags.RUN_FIRST,
                                      None, ([object])),
        'status-destroyed-failed':    (GObject.SignalFlags.RUN_FIRST,
                                      None, ([str])),
        'retweet-created':            (GObject.SignalFlags.RUN_FIRST,
                                      None, ([object])),
        'retweet-created-failed':     (GObject.SignalFlags.RUN_FIRST,
                                      None, ([str])),
        'retweets-downloaded':        (GObject.SignalFlags.RUN_FIRST,
                                      None, ([object])),
        'retweets-downloaded-failed': (GObject.SignalFlags.RUN_FIRST,
                                      None, ([str]))}

    def __init__(self, status_id=None):
        GObject.GObject.__init__(self)
        self._status_id = status_id

    def update(self, status, reply_status_id=None):
        self._update(self.UPDATE_URL,
                    status,
                    None,
                    reply_status_id)

    def update_with_media(self, status, filepath, reply_status_id=None):
        self._update(self.UPDATE_WITH_MEDIA_URL,
                    status,
                    filepath,
                    reply_status_id)

    def _update(self, url, status, filepath=None, reply_status_id=None):
        self._check_is_not_created()

        params = [('status', (status))]
        if reply_status_id is not None:
            params += [('in_reply_to_status_id', (reply_status_id))]

        GObject.idle_add(self._post,
                        url,
                        params,
                        filepath,
                        self.__completed_cb,
                        self.__failed_cb,
                        'status-updated',
                        'status-updated-failed')

    def show(self):
        self._check_is_created()
        GObject.idle_add(self._get,
                        self.SHOW_URL,
                        [('id', (self._status_id))],
                        self.__completed_cb,
                        self.__failed_cb,
                        'status-downloaded',
                        'status-downloaded-failed')

    def destroy(self):
        self._check_is_created()
        GObject.idle_add(self._post,
                        self.DESTROY_URL % self._status_id,
                        None,
                        None,
                        self.__completed_cb,
                        self.__failed_cb,
                        'status-destroyed',
                        'status-destroyed-failed')

    def retweet(self):
        self._check_is_created()
        GObject.idle_add(self._post,
                        self.RETWEET_URL % self._status_id,
                        None,
                        None,
                        self.__completed_cb,
                        self.__failed_cb,
                        'retweet-created',
                        'retweet-created-failed')

    def retweets(self):
        self._check_is_created()
        GObject.idle_add(self._get,
                        self.RETWEETS_URL % self._status_id,
                        [],
                        self.__completed_cb,
                        self.__failed_cb,
                        'retweets-downloaded',
                        'retweets-downloaded-failed')

    def _check_is_not_created(self):
        if self._status_id is not None:
            raise TwrStatusAlreadyCreated('Status already created')

    def _check_is_created(self):
        if self._status_id is None:
            raise TwrStatusNotCreated('Status not created')

    def _get(self, url, params,
            completed_cb, failed_cb, completed_data, failed_data):

        object = TwrObject()
        object.connect('transfer-completed', completed_cb, completed_data)
        object.connect('transfer-failed', failed_cb, failed_data)
        object.request('GET', url, params)

    def _post(self, url, params, filepath,
            completed_cb, failed_cb, completed_data, failed_data):

        object = TwrObject()
        object.connect('transfer-completed', completed_cb, completed_data)
        object.connect('transfer-failed', failed_cb, failed_data)
        object.request('POST', url, params, filepath)

    def __completed_cb(self, object, data, signal):
        try:
            info = json.loads(data)

            if 'errors' in info.keys():
                raise TwrStatusError(str(info['errors']))

            if self._status_id is None and 'id_str' in info.keys():
                self._status_id = str(info['id_str'])

            self.emit(signal, info)
        except Exception, e:
            print '__completed_cb crashed with %s' % str(e)

    def __failed_cb(self, object, message, signal):
        self.emit(signal, message)


class TwrTimeline(TwrObject):

    MENTIONS_TIMELINE_URL = 'https://api.twitter.com/1.1/statuses/'\
                            'mentions_timeline.json'
    HOME_TIMELINE_URL = 'https://api.twitter.com/1.1/statuses/'\
                        'home_timeline.json'

    __gsignals__ = {
        'mentions-downloaded':          (GObject.SignalFlags.RUN_FIRST,
                                        None, ([object])),
        'mentions-downloaded-failed':   (GObject.SignalFlags.RUN_FIRST,
                                        None, ([str])),
        'timeline-downloaded':          (GObject.SignalFlags.RUN_FIRST,
                                        None, ([object])),
        'timeline-downloaded-failed':   (GObject.SignalFlags.RUN_FIRST,
                                        None, ([str]))}

    def mentions_timeline(self, count=None, since_id=None, max_id=None):
        params = self._params(count, since_id, max_id)

        GObject.idle_add(self._get,
                        self.MENTIONS_TIMELINE_URL,
                        params,
                        self.__completed_cb,
                        self.__failed_cb,
                        'mentions-downloaded',
                        'mentions-downloaded-failed')

    def home_timeline(self, count=None, since_id=None,
                      max_id=None, exclude_replies=None):
        params = self._params(count, since_id, max_id, exclude_replies)

        GObject.idle_add(self._get,
                        self.HOME_TIMELINE_URL,
                        params,
                        self.__completed_cb,
                        self.__failed_cb,
                        'timeline-downloaded',
                        'timeline-downloaded-failed')

    def _params(self, count=None, since_id=None,
                      max_id=None, exclude_replies=None):
        params = []

        if count is not None:
            params += [('count', (count))]
        if since_id is not None:
            params += [('since_id', (since_id))]
        if max_id is not None:
            params += [('max_id', (max_id))]
        if exclude_replies is not None:
            params += [('exclude_replies', (exclude_replies))]

        return params

    def _get(self, url, params, completed_cb, failed_cb,
            completed_data, failed_data):

        object = TwrObject()
        object.connect('transfer-completed', completed_cb, completed_data)
        object.connect('transfer-failed', failed_cb, failed_data)
        object.request('GET', url, params)

    def __completed_cb(self, object, data, signal):
        try:
            info = json.loads(data)

            if isinstance(info, dict) and ('errors' in info.keys()):
                raise TwrTimelineError(str(info['errors']))

            self.emit(signal, info)
        except Exception, e:
            print 'TwrTimeline.__completed_cb crashed with %s' % str(e)

    def __failed_cb(self, object, message, signal):
        self.emit(signal, message)
