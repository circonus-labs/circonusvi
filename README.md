# Circonusvi

Circonusvi is an interactive command line client for circonus that lets you
query the API, edit the results in a text editor, and apply the changes back
to the server.

## Requirements

 * circonusapi module

## Configuration

The API token is kept in .circonusapirc. Go to
https://circonus.com/user/tokens to set up a token.

    [general]
    account=foo

    [tokens]
    foo=12345678-9abc-def0-123456789abcdef01

## Usage

 * General usage is:

        ./circonusvi.py [options] [PATTERN]
 * Pattern should be of the form key=pattern, where key is what you want to
   match on (such as target), and pattern is a regular expression. If any
   returned piece of data doesn't have the key (e.g. rules don't have
   targets), then it doesn't match
 * Options are:
    * -a -- Specify which account to use
    * -d -- Enable debug mode
    * -e -- Specify endpoints to search (can be used multiple times for
      several endpoints at once)
    * -E -- Specify an alternate editor to use (default: $EDITOR)
    * -u -- include underscore entries (e.g. \_cid) in json output. By default
      they are hidden.
 * If you don't specify a pattern, then all entries are returned.
 * If you don't specify which endpoint to use, check_bundle is used by default.

## In the editor

 * To change a value, just edit it and save the file, the changes will be sent
   back to circonus
 * To delete an entry, just remove it completely from the file
 * To add a new entry, add it to the end of the file. The key should be the
   endpoint you want to add, such as '"/check_bundle": { ....'. Unlike with a
   regular json file, you can repeat the same key multiple times to add
   several entries at once.
 * Once you exit the editor, you are given the opportunity to review the
   changes you made and re-edit the file if necessary.

# Examples

 * View all check bundles on your account:

        ./circonusvi.py

 * Filter the check bundles returned by name:

        ./circonusvi.py 'name=(foo|bar|baz).com HTTP'

 * Look up rulesets instead (and filter only those that are for metrics with
   'duration' in the name:

        ./circonusvi.py -e rule_set metric_name=duration
