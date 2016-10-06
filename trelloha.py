#!/usr/bin/env python
import json
import logging
import netrc
import re

import defusedxml.ElementTree
import requests
import trello

TRELLO_APP_KEY = "ec65a98b933f15b1fdb63dd79ef281b3"

LOG = logging.getLogger(__name__)


class NoAuth(RuntimeError):
    def __init__(self, trello):
        super(NoAuth, self).__init__(
            """No authentication token found or token expired.\n
Go to:\n%s\n\nand add the following to your ~/.netrc file:\n
machine trello.com login <BOARD_ID> password <TOKEN>""" %
            trello.get_token_url("Trelloha",
                                 expires='30days',
                                 write_access=True))


class Trelloha(object):

    GERRIT_URL = "https://review.openstack.org"
    BUGZILLA_URL = "https://bugzilla.redhat.com"

    def __init__(self):
        self.trello = trello.TrelloApi(TRELLO_APP_KEY)
        self.board_id, token = self.get_board_token()
        self.trello.set_token(token)

    def get_board_token(self, site_name="trello.com", netrc_file=None):
        """Read a .netrc file and return login/password."""
        n = netrc.netrc(netrc_file)
        if site_name not in n.hosts:
            raise NoAuth(self.trello)
        return n.hosts[site_name][0], n.hosts[site_name][2]

    # TODO(jd) add that in trello.boards
    def checkitem_update_state(self, card_id, checklist_id, checkitem_id,
                               state):
        resp = requests.put(
            "https://trello.com/1/cards/%s/checklist/%s/checkItem/%s/state"
            % (card_id, checklist_id, checkitem_id),
            params=dict(key=self.trello._apikey, token=self.trello._token),
            data=dict(value=state))
        resp.raise_for_status()
        return json.loads(resp.content)

    def get_review(self, review_id):
        r = requests.get(
            "%s/changes/%d" % (self.GERRIT_URL, review_id))
        return json.loads(r.text[5:])

    def get_bugzilla(self, bug_id):
        r = requests.get(
            "%s/show_bug.cgi?ctype=xml&id=%s" % (
                self.BUGZILLA_URL, bug_id))
        return defusedxml.ElementTree.fromstring(r.content)

    def is_a_gerrit_review_merged(self, checklist_item):
        if self.GERRIT_URL not in checklist_item['name']:
            return False
        matched = re.search("%s/(#/c/)?(\d+)" % self.GERRIT_URL,
                            checklist_item['name'])
        if not matched:
            return False

        review = self.get_review(int(matched.group(2)))
        merged = review['status'] == "MERGED"
        if merged:
            LOG.info("Review %s is merged" % review['id'])
        return merged

    def is_a_bugzilla_modified(self, checklist_item):
        if self.BUGZILLA_URL not in checklist_item['name']:
            return False
        matched = re.search("%s/show_bug.cgi\?id=(\d+)" % self.BUGZILLA_URL,
                            checklist_item['name'])
        if not matched:
            return False
        bug_id = int(matched.group(1))
        bugzilla = self.get_bugzilla(bug_id)
        bug_status = bugzilla.find('bug/bug_status').text

        if bug_status in ["MODIFIED", "ON_QA", "VERIFIED", "RELEASING_PENDING",
                          "CLOSED"]:
            LOG.info("Buzgilla %s is %s" % (bug_id, bug_status))
            return True
        return False

    def update_trello_card_checklist_with_review(self):
        try:
            for checklist in self.trello.boards.get_checklist(self.board_id):
                for item in checklist['checkItems']:
                    completed = (item['state'] == "incomplete" and
                                 (self.is_a_gerrit_review_merged(item) or
                                  self.is_a_bugzilla_modified(item)))
                    if completed:
                        LOG.info("Setting %s to complete" % item['id'])
                        self.checkitem_update_state(checklist['idCard'],
                                                    checklist['id'],
                                                    item['id'],
                                                    "complete")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise NoAuth(self.trello)
            raise


def main():
    t = Trelloha()
    t.update_trello_card_checklist_with_review()


if __name__ == '__main__':
    main()
