# Copyright (C) 2013, Walter Bender, Raul Gutierrez Segales, Martin Abente
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

import logging

from gi.repository import GConf
from gi.repository import Gtk
from gi.repository import WebKit
from gettext import gettext as _

from web.twitter.twitter.twr_oauth import TwrOauth
from web.twitter.twitter.twr_account import TwrAccount
from web.twitter.account import TwitterOnlineAccount as twr
from cpsection.webservices.web_service import WebService


class TwitterService(WebService):

    def __init__(self):
        self._client = GConf.Client.get_default()

        tokens = self._twr_tokens()
        self._consumer_token = tokens[0]
        self._consumer_secret = tokens[1]
        self._access_token = tokens[2]
        self._access_secret = tokens[3]

    def _twr_tokens(self):
        return (self._client.get_string(twr.CONSUMER_TOKEN_KEY),
                self._client.get_string(twr.CONSUMER_SECRET_KEY),
                self._client.get_string(twr.ACCESS_TOKEN_KEY),
                self._client.get_string(twr.ACCESS_SECRET_KEY))

    def _twr_save_access_cb(self, oauth, data, container):
        logging.debug('_twr_save_access_cb')

        self._access_token = data['oauth_token']
        self._access_secret = data['oauth_token_secret']

        # XXX update step 3
        TwrAccount.set_secrets(self._consumer_token, self._consumer_secret,
                           self._access_token, self._access_secret)

        self._client.set_string(twr.CONSUMER_TOKEN_KEY, self._consumer_token)
        self._client.set_string(twr.CONSUMER_SECRET_KEY, self._consumer_secret)
        self._client.set_string(twr.ACCESS_TOKEN_KEY, self._access_token)
        self._client.set_string(twr.ACCESS_SECRET_KEY, self._access_secret)

        self._twr_configured(container)

    def _twr_verify_cb(self, oauth, data, container):
        logging.debug('_twr_verify_cb')

        # XXX update step 2
        TwrAccount.set_secrets(self._consumer_token, self._consumer_secret,
                           data['oauth_token'], data['oauth_token_secret'])

        url = TwrOauth.AUTHORIZATION_URL % data['oauth_token']
        wkv = WebKit.WebView()
        wkv.load_uri(url)
        wkv.grab_focus()

        # XXX oh god greedy UI
        for c in container.get_children():
            container.remove(c)

        vbox = Gtk.VBox()
        hbox = Gtk.HBox()
        label = Gtk.Label()
        entry = Gtk.Entry()
        button = Gtk.Button()

        # XXX should I move it out?
        def _button_cb(button):
            verifier = entry.get_text()
            oauth = TwrOauth()
            oauth.connect('access-downloaded',
                            self._twr_save_access_cb, container)
            oauth.connect('access-downloaded-failed',
                            self._twr_failed_cb, container)
            oauth.access_token(verifier)

        label.set_text(_('Code:'))
        button.set_label(_('Verify'))
        button.connect('clicked', _button_cb)

        hbox.add(label)
        hbox.add(entry)
        hbox.add(button)
        vbox.add(hbox)
        vbox.add(wkv)

        container.add(vbox)
        container.show_all()

    def _twr_configured(self, container):
        logging.debug('_twr_configured')

        self._twr_show_msg(container, _('Your twitter account is configured.'))

    def _twr_failed_cb(self, oauth, message, container):
        logging.debug('_twr_failed_cb: %s', message)

        self._twr_show_msg(container, _('Your twitter account can not be '\
                          'configured at this moment.'))

    def _twr_show_msg(self, container, msg):

        for c in container.get_children():
            container.remove(c)

        vbox = Gtk.VBox()
        label = Gtk.Label()
        label.set_text(msg)

        vbox.add(label)
        container.add(vbox)
        container.show_all()

    def get_icon_name(self):
        return 'twitter-share'

    def config_service_cb(self, widget, event, container):
        logging.debug('config_service_cb in twr')

        tokens = self._twr_tokens()
        if None not in tokens and '' not in tokens:
            self._twr_configured(container)
            return

        # XXX update step 1
        TwrAccount.set_secrets(self._consumer_token, self._consumer_secret,
                           self._access_token, self._access_secret)
 
        oauth = TwrOauth()
        oauth.connect('request-downloaded', self._twr_verify_cb, container)
        oauth.connect('request-downloaded-failed',
                        self._twr_failed_cb, container)
        oauth.request_token()

def get_service():
    return TwitterService()
