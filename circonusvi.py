#!/usr/bin/env python
import ConfigParser
import getopt
import json
import os
import subprocess
import sys
import tempfile

import circonusapi

config = ConfigParser.SafeConfigParser()
config.read(os.path.expanduser('~/.circusrc'))


account = config.get('general', 'default_account', None)
debug = False
opts, args = getopt.gnu_getopt(sys.argv[1:], "a:d")
for o,a in opts:
    if o == '-a':
        account = a
    if o == '-d':
        debug = not debug
token = config.get('tokens', account, None)

api = circonusapi.CirconusAPI(token)
if debug:
    api.debug = True

endpoints = args
if not endpoints:
    endpoints = ['broker', 'contact_group']

# Combined output to be serialized
data = {}

for t in endpoints:
    data.update(dict(((i['_cid'], i) for i in api.api_call("GET", t))))

tmp = tempfile.mkstemp()
fh = os.fdopen(tmp[0], 'w')
json.dump(data, fh, sort_keys=True, indent=4, separators=(',',': '))
fh.close()

subprocess.call(["vim", tmp[1]])

fh = open(tmp[1])
data_new = json.load(fh)
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
            print c['data']

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
    print "Making API Call: %s %s" % (c['action'], c['endpoint'])
    if c['action'] == 'DELETE':
        # We don't send any data along for deletions
        c['data'] = None
    api.api_call(c['action'], c['endpoint'], c['data'])
