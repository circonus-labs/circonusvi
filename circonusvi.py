#!/usr/bin/env python
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

def confirm(text="OK to continue?"):
    response = None
    while response not in ['Y', 'y', 'N', 'n']:
        response = raw_input("%s (y/n) " % text)
    if response in ['Y', 'y']:
        return True
    return False

account = config.get('general', 'default_account', None)
debug = False
endpoints = []
editor = os.environ.get('EDITOR', 'vi')
try:
    opts, args = getopt.gnu_getopt(sys.argv[1:], "a:de:E:?")
except getopt.GetoptError, err:
    # print help information and exit:
    print str(err) # will print something like "option -a not recognized"
    usage()
    sys.exit(2)

for o,a in opts:
    if o == '-a':
        account = a
    if o == '-d':
        debug = not debug
    if o == '-e':
        endpoints.append(a)
    if o == '-E':
        editor = a
    if o == '-?':
        usage()
        sys.exit(0)

token = config.get('tokens', account, None)
api = circonusapi.CirconusAPI(token)
if debug:
    api.debug = True

if not endpoints:
    # user, account are missing from here
    # TODO - it's probably a good idea to pick only commonly used endpoints by
    # default here, or perhaps make it configurable.
    endpoints = ['broker', 'check_bundle', 'contact_group', 'graph',
            'rule_set', 'template', 'worksheet']

# Combined output to be serialized
data = {}

for t in endpoints:
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
    matched = True
    for k, p in patterns:
        if k not in data[i]:
            break
        if not re.search(p, data[i][k]):
            break
    else:
        filtered_data[i] = data[i]
data = filtered_data

tmp = tempfile.mkstemp(suffix='.json')
fh = os.fdopen(tmp[0], 'w')
json.dump(data, fh, sort_keys=True, indent=4, separators=(',',': '))
fh.close()

ok = False
while not ok:
    subprocess.call([editor, tmp[1]])

    fh = open(tmp[1])
    try:
        data_new = json.load(fh)
        ok = True
    except ValueError, e:
        print "Error parsing JSON:", e
        if not confirm("Do you want to edit the file again?"):
            sys.exit(1)
    fh.close()

os.remove(tmp[1])

changes = []
additions = 0
deletions = 0
edits = 0
for i in data_new:
    if i not in data:
        # Addition
        # We need to make sure the endpoint doesn't contain an ID (just in
        # case the entry contains one)
        changes.append({'action': 'POST', 'data': data_new[i],
            'endpoint': re.sub("(?!^)/.*", "", i)})
        additions += 1
    elif data[i] != data_new[i]:
        # Edit
        changes.append({'action': 'PUT', 'data': data_new[i], 
            'data_old': data[i], 'endpoint': i})
        edits += 1
for i in data:
    if i not in data_new:
        # Delete
        changes.append({'action': 'DELETE', 'data': data[i], 'endpoint': i})
        deletions += 1

def show_changes():
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

if not changes:
    print "No Changes. Exiting."
    sys.exit(1)

print "%d additions, %d deletions, %d edits" % (additions, deletions, edits)
response = None
while True:
    response = raw_input("Do you want to proceed? (YyNnSs?) ")
    if response in ['Y', 'y']:
        break
    if response in ['N', 'n']:
        print "Exiting"
        sys.exit(1)
    if response in ['S', 's']:
        show_changes()
    if response in ['?']:
        print "Y - Proceed"
        print "N - Quit"
        print "S - Show changes"
        print "? - Help"

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
