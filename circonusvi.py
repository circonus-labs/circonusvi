#!/usr/bin/env python
import collections
import ConfigParser
import getopt
import json
import os
import subprocess
import re
import sys
import tempfile

import circonusapi

config = ConfigParser.SafeConfigParser()
config.read(os.path.expanduser('~/.circusrc'))

options = {
    'account': config.get('general', 'default_account', None),
    'debug': False,
    'endpoints': [],
    'editor': os.environ.get('EDITOR', 'vi'),
    'include_underscore': False
}

class Enum(set):
    def __getattr__(self, name):
        if name in self:
            return name
        raise AttributeError

actions = Enum(["REEDIT", "PROCEED", "EXIT"])

def usage():
    print "Usage:"
    print sys.argv[0], "[options] [PATTERN]"
    print
    print "Pattern should be of the form key=pattern, where key is what you"
    print "want to match on (such as target), and pattern is a regular"
    print "expression. If any returned piece of data doesn't have the key"
    print "(e.g. rules don't have targets), then it doesn't match"
    print
    print "  -a -- Specify which account to use"
    print "  -d -- Enable debug mode"
    print "  -e -- Specify endpoints to search (can be used multiple times)"
    print "  -E -- Specify an alternate editor to use (default: $EDITOR)"
    print "  -u -- include underscore entries (e.g. _cid) in json output"

def confirm(text="OK to continue?"):
    response = None
    while response not in ['Y', 'y', 'N', 'n']:
        response = raw_input("%s (y/n) " % text)
    if response in ['Y', 'y']:
        return True
    return False

def parse_options():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "a:de:E:u?")
    except getopt.GetoptError, err:
        # print help information and exit:
        print str(err) # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    for o,a in opts:
        if o == '-a':
            options['account'] = a
        if o == '-d':
            options['debug'] = not options['debug']
        if o == '-e':
            options['endpoints'].append(a)
        if o == '-E':
            options['editor'] = a
        if o == '-u':
            options['include_underscore'] = not options['include_underscore']
        if o == '-?':
            usage()
            sys.exit(0)
    return args

def get_api():
    token = config.get('tokens', options['account'], None)
    api = circonusapi.CirconusAPI(token)
    if options['debug']:
        api.debug = True
    return api

def get_circonus_data(api, args):
    if not options['endpoints']:
        # user, account are missing from here TODO - it's probably a good idea
        # to pick only commonly used endpoints by default here, or perhaps
        # make it configurable.
        options['endpoints'] = ['broker', 'check_bundle', 'contact_group',
                'graph', 'rule_set', 'template', 'worksheet']

    # Combined output to be serialized
    data = {}

    for t in options['endpoints']:
        data.update(dict(((i['_cid'], i) for i in api.api_call("GET", t))))

    # Filter based on the pattern
    patterns = []
    for p in args:
        parts = p.split('=', 1)
        if len(parts) != 2:
            print "Invalid pattern: %s" % p
            usage()
            sys.exit(2)
        patterns.append(parts)

    filtered_data = {}
    for i in data:
        for k, p in patterns:
            if k not in data[i]:
                break
            if not re.search(p, data[i][k]):
                break
        else:
            filtered_data[i] = data[i]
    return filtered_data

def create_json_file(data):
    tmp = tempfile.mkstemp(suffix='.json')
    fh = os.fdopen(tmp[0], 'w')
    json.dump(data, fh, sort_keys=True, indent=4, separators=(',',': '))
    fh.close()
    return tmp[1]

def edit_json_file(filename):
    ok = False
    while not ok:
        subprocess.call([options['editor'], filename])
        fh = open(filename)
        try:
            data_new = json.load(fh,
                    object_pairs_hook=json_pairs_hook_dedup_keys)
            ok = True
        except ValueError, e:
            print "Error parsing JSON:", e
            if not confirm("Do you want to edit the file again?"):
                sys.exit(1)
        fh.close()
    return data_new

def calculate_changes(data, data_new):
    changes = []
    for i in data_new:
        if i not in data:
            # Addition
            # We need to make sure the endpoint doesn't contain an ID (just in
            # case the entry contains one)
            changes.append({'action': 'POST', 'data': data_new[i],
                'endpoint': re.sub("(?!^)/.*", "", i)})
        elif data[i] != data_new[i]:
            # Edit
            changes.append({'action': 'PUT', 'data': data_new[i], 
                'data_old': data[i], 'endpoint': i})
    for i in data:
        if i not in data_new:
            # Delete
            changes.append({'action': 'DELETE', 'data': data[i], 'endpoint': i})
    return changes

def show_changes(changes):
    pretty_actions = {
        'DELETE': "Delete",
        'POST': "Addition",
        'PUT': "Edit"
    }
    for c in changes:
        print "Action: %s" % pretty_actions[c['action']]
        print "Endpoint: %s" % c['endpoint']
        if c['action'] == 'PUT':
            # We have an edit - show a diff
            print "Diff:"
            old_file = tempfile.mkstemp()
            new_file = tempfile.mkstemp()
            fh = os.fdopen(old_file[0], 'w')
            json.dump(c['data_old'], fh, sort_keys=True,
                    indent=4, separators=(',',': '))
            fh.close()
            fh = os.fdopen(new_file[0], 'w')
            json.dump(c['data'], fh, sort_keys=True,
                    indent=4, separators=(',',': '))
            fh.close()
            subprocess.call(["diff", "-u", old_file[1], new_file[1]])
            os.remove(old_file[1])
            os.remove(new_file[1])
        else:
            print "Data:"
            print json.dumps(c['data'], sort_keys=True,
                    indent=4, separators=(',',': '))

def confirm_changes(changes):
    if not changes:
        print "No Changes. Exiting."
        sys.exit(1)

    counts = collections.Counter((c['action'] for c in changes))

    print "%d additions, %d deletions, %d edits" % (
            counts['POST'], counts['DELETE'], counts['PUT'])
    response = None
    while True:
        response = raw_input("Do you want to proceed? (YyNnEeSs?) ")
        if response in ['Y', 'y']:
            return actions.PROCEED
        if response in ['N', 'n']:
            return actions.EXIT
        if response in ['E', 'e']:
            return actions.REEDIT
        if response in ['S', 's']:
            show_changes(changes)
        if response in ['?']:
            print "Y - Proceed"
            print "N - Quit"
            print "S - Show changes"
            print "E - Re-edit the file"
            print "? - Help"

def make_changes(changes):
    for c in changes:
        print "Making API Call: %s %s ..." % (c['action'], c['endpoint']),
        if c['action'] == 'DELETE':
            # We don't send any data along for deletions
            c['data'] = None
        try:
            api.api_call(c['action'], c['endpoint'], c['data'])
        except circonusapi.CirconusAPIError, e:
            print "Error"
            print "    %s" % e
            continue
        print "Success"

def strip_underscore_keys(data):
    for k in data.keys():
        for l in data[k].keys():
            if l[0] == '_':
                del data[k][l]

def json_pairs_hook_dedup_keys(data):
    # json decoder object_pairs_hook that allows duplicate keys, and makes
    # any duplicate keys unique by appending /x1, /x1 and so on to the end.
    # This is used when adding new items via the circonus api, you can just
    # specify /check_bundle multiple times as the endpoint and won't get an
    # error about duplicate keys when decoding the json. Separate code
    # elsewhere automatically strips off the /x1 when selecting the endpoint
    # to use for adding entries.
    d = {}
    ctr = 0
    for k,v in data:
        oldk = k
        while k in d:
            ctr += 1
            k = "%s/x%s" % (oldk, ctr)
        d[k] = v
    return d

if __name__ == '__main__':
    args = parse_options()
    api = get_api()
    data = get_circonus_data(api, args)
    if not options['include_underscore']:
        strip_underscore_keys(data)
    editing = True
    filename = create_json_file(data)
    while editing:
        data_new = edit_json_file(filename)
        editing = False
        changes = calculate_changes(data, data_new)
        next_action = confirm_changes(changes)
        if next_action == actions.REEDIT:
            editing = True
        elif next_action == actions.PROCEED:
            make_changes(changes)
        else:
            print "Not proceeding"
    os.remove(filename)
