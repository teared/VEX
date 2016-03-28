
# coding: utf-8

# ### Generate VEX functions completions for Sublime Text 3

# In[1]:

import os
import re
import json
import copy
import random
import os.path
import subprocess
import collections
from pprint import pprint
from zipfile import ZipFile


HFS = 'C:\\Program Files\\Side Effects Software\\Houdini 15.0.404'

if not os.path.exists(HFS):
    print('Bad HFS variable. Edit script source.')


# #### Get functions from VCC
# Discard deprecated functions. Merge all contexts's unique functions and
# signatures into one dictionary. Resulting JSON structure:
# ```
# {
#     'primpoints': [
#       {
#         'args': [ 'const int', 'const int'],
#         'return': 'int[]'
#       },
#       ... (other signatures of "primpoints" function)
#     ],
#     ... (other functions)
# }
# ```

# In[2]:

# Path to the VCC executable.
vcc = os.path.join(HFS, 'bin', 'vcc')

# Context names.
contexts = json.loads(subprocess.check_output([vcc, '--list-context-json'], universal_newlines=True))

# Merge all contexts into one big dictionary.
functions = {}

for context in contexts:
    # Get functions from VCC.
    output = subprocess.check_output([vcc, '--list-context-json', context], universal_newlines=True)
    context_functions = json.loads(output)['functions']

    # Discard deprecated functions.
    context_functions = {f: [s for s in context_functions[f] if 'deprecated' not in s] for f in context_functions}

    # Add unique functions and signatures to common dictionary.
    for f in context_functions:
        # Function not exists.
        if f not in functions:
            functions[f] = context_functions[f]
            continue

        # Function exists. Search for unique signatures.
        for context_s in context_functions[f]:
            for s in functions[f]:

                # Non-unique signature found.
                if context_s['args'] == s['args'] and  context_s['return'] == s['return']:
                    # Exiting loop suppresses else clause.
                    break 

            # Non-unique signatures not found (= the signature is unique).
            else:
                functions[f].append(context_s)


# In[3]:

def debug_functions(functions):
    '''Print debug info about obtained functions.'''
    f = random.choice(list(functions.keys()))
    print(
        'Total functions: %d' %len(functions),
        '\nTotal signatures: %d' %sum(len(f) for f in functions),
        '\nRandom function: %s' %f,
        '\nSignatures: %d' %len(functions[f]),
        '\nData:')
    pprint(functions[f])

debug_functions(functions)


# #### Parse function examples from docs
# Open `vex.zip` containing various helpcards including functions. Open all function helpcards and find all function usage examples. Parse all raw strings into JSON-formatted data. Obtain signatures from the `overrides.vfl` file. Merge functions into a single dict.
# 
# Example raw string:
# 
#     int[] primpoints(int opinput, int primnum)
# 
# Obtained data follows `functions` structure:
# ```
# {
#     'primpoints': [
#         {
#             'argnames': ['opinput', 'primnum'],
#             'args': ['const int', 'const int'],
#             'return': 'int[]'
#         },
#         ... (other signatures of "primpoints" function)
#     ],
#     ... (other functions)
# }
# ```

# In[4]:

def is_vex_type(some_type):
    '''Return True if some_type is a valid VEX type name.'''
    return some_type.strip('&[] ') in ['void', 'int', 'float', 'string',
                                       'vector2', 'vector',  'vector4',
                                       'matrix2', 'matrix3', 'matrix',
                                       'bsdf', 'light', 'material']

def arg_data(raw_arg):
    '''
    Parse input string of argument type and name pair. Return argument's
    type and name obtained from the input string.

    Examples:
        'int foo'     -> 'const int', 'foo'
        'int bar&'    -> 'int', 'bar'
        'float baz[]' -> 'float[]', 'baz'
    '''
    # Simplify string.
    arg = raw_arg.replace('&', ' ')
    arg = arg.replace('[]', ' ')
    arg = arg.replace('const ', ' ')
    arg = arg.replace('export ', ' ')
    arg = [s.strip() for s in arg.split()]

    # Not a type and name pair.
    if len(arg) != 2:
        return

    # Not a valid type.
    if not is_vex_type(arg[0]):
        return

    # Not a valid name.
    if not re.match(r'^\w+(="\w*?"|=[\d.]+)?$', arg[1]):
        return

    # Return array modifier to the type.
    if '[]' in raw_arg:
        arg[0] += '[]'

    # Set const or export modifiers.
    if 'export' in raw_arg:
        arg[0] = 'export ' + arg[0]
    elif 'const ' in raw_arg or '&' not in raw_arg:
        arg[0] = 'const ' + arg[0]

    return arg

def sig_data(raw_sig):
    '''
    Parse input string of function signature. Find function's type, name,
    function arguments's types and names. Return as dictionary with single
    item containing function name and single-item list of signature data.

    Example:
        'string foo(string bar, int baz[])'
        ->
        'foo': [{'argnames': ['bar', 'baz'],
                 'args': ['const string','const int[]'],
                 'return': 'string'}]
    '''
    #Replace common documentation flaws to make life easier.
    sig = raw_sig.replace(';', ',')
    sig = sig.replace("'", '"')
    sig = sig.replace('matrix4', 'matrix')
    sig = sig.replace('vector3', 'vector')
    sig = sig.replace(', ...', '')

    # Retrieve data.
    match = re.match(r'(\w+(?:\s?\[\])?)?\s*(\b\w+\b)\(\s*(.+)\s*\)', sig)
    if not match:
        return
    ret, name, args = match.groups()

    # Check return type.
    if ret is None:
        ret = 'void'
    ret = ret.replace(' ', '')
    if not is_vex_type(ret):
        return

    # Parse arguments.
    args = [arg_data(a) for a in args.split(',')]
    if not all(args):
        return

    atypes, anames = zip(*args)
    return {name : [{'return' : ret, 
                     'args' : list(atypes), 
                     'argnames' : list(anames)}]}

def parse_sigs(raw_sigs):
    '''
    Parse each signature string. Merge multiple signatures of same function
    into a dictionary of function names as keys and lists of signature datas
    as values. Same structure the VCC uses when outputs JSON files.
    '''
    sigs = {}
    for raw_sig in raw_sigs:
        data = sig_data(raw_sig)
        if not data:
            continue

        name, data = data.popitem()
        if name in sigs:
            sigs[name] += data
        else:
            sigs[name] = data

    return sigs


# In[5]:

def debug_parser():
    '''Check parse functions.'''
    pprint(parse_sigs(['a(string arg1 &, int arg2[])',
                       'string a(string arg1, int arg2[])',
                       'vector2 b(float arg1, float arg2)',
                       'foo bar(baz)']))

debug_parser()


# In[6]:

# Open vex.zip containing various helpcards including functions.
# Open all function helpcards and find all function usage examples.
# Parse all raw strings into JSON-formatted data.
sigs_docs = set()

with ZipFile(os.path.join(HFS, 'houdini', 'help', 'vex.zip')) as z:
    for path in z.namelist():
        if os.path.dirname(path) == 'functions':
            with z.open(path) as f:
                sigs_docs.update(re.findall(r'^\* `(.*)`$', f.read().decode(), re.M))

functions_docs = parse_sigs(sigs_docs)

# Obtain signatures from the overrides file, skipping commented lines.
with open('overrides.vfl') as f:
    sigs_overrides = {s for s in f.read().split('\n') if '//' not in s}

functions_overrides = parse_sigs(sigs_overrides)

# Merge parsed functions into a single dict.
functions_parsed = copy.deepcopy(functions_docs)

for f in copy.deepcopy(functions_overrides):
    # Function not exists.
    if f not in functions_parsed:
        functions_parsed[f] = functions_overrides[f]
        continue

    # Function exists. Search for unique signatures.
    for sig_new in functions_overrides[f]:
        for sig in copy.deepcopy(functions_parsed[f]):

            # Non-unique signature found. Override.
            if sig['args'] == sig_new['args']:
                functions_parsed[f].remove(sig)
                functions_parsed[f].insert(0, sig_new)

                # Exiting loop suppresses else clause.
                break 

        # Non-unique signatures not found (= the signature is unique).
        else:
            functions_parsed[f].insert(0, sig_new)


# In[7]:

def debug_parsed_stuff():
    '''Print debug info about parsed signatures.'''
    print(
        'Docs functions:', len(functions_docs),
        '\nOverrides functions:', len(functions_overrides),
        '\nTotal:', len(functions_docs) + len(functions_overrides),
        '\nUnique:', len(functions_parsed),
    )

    lsdp = sum(len(functions_docs[f]) for f in functions_docs)
    lsd = len(sigs_docs)
    fd = random.choice(list(functions_docs.keys()))
    print(
        '\nSignatures parsed: {}/{} ({:.2%})'.format(lsdp, lsd, lsdp / lsd),
        '\nExample function:', fd
    )
    pprint(functions_docs[fd])

    lsop = sum(len(functions_overrides[f]) for f in functions_overrides)
    lso = len(sigs_overrides)
    fo = random.choice(list(functions_overrides.keys()))
    print(
        '\nOverrides parsed: {}/{} ({:.2%})'.format(lsop, lso, lsop / lso),
        '\nExample function:', fo
    )
    pprint(functions_overrides[fo])

debug_parsed_stuff()


# #### Fill function signatures with argument names
# Iterate over `functions` and find similar signatures in `functions_parsed`. Exact matches covers about one third of all existing signatures. Other signatures filled by trivial "guessing" operations:
# 
# 1. Return type changes:
# ```
#     Docs:   int foo(string bar)
#     VCC:    float foo(string)
#     Result: foo(string bar)
# ```
# 
# 2. An array functions with type and two arguments changing and limited names scope.
# ```
#     Docs:   void foo(int value, int[] array)
#     VCC:    void foo(float, float[])
#     Result: float foo(float value, float[] array)
# ```
# 
# 3. Of the arguments type changes.
# ```
#     Docs:   string foo(int bar)
#     VCC:    string foo(float)
#     Result: string foo(float bar)
# ```
# 
# 4. Return and argument types changes.
# ```
#     Docs:   int foo(int bar)
#     VCC:    float foo(float)
#     Result: float foo(float bar)
# ```
# 
# Although a lot more trivial guesses may be done, it just not worth to do it to get 5-10 extra functions fully defined. Better to define them in `overrides.vfl` file, which already contains couple of hundreds of non-trivial function signatures. We will update and re-read `overrides.vfl` until all functions are guessed. We also use `overrides.vfl` if we are not happy with guessed names (`foo(float N)` for example) and want to manually enter proper argument names (`foo(float roughness)` for same example).

# In[8]:

def simplify(t):
    '''Simplify real type names to make comparisons more robust.'''
    return t.replace('const ', '').replace('export ', '').strip()

functions_filled = copy.deepcopy(functions)

for name in functions_filled:
    for sig in functions_filled[name]:
        def fill():
            '''Wrapped into a scope function to utilize returning.'''
            # No arguments. Nothing to fill.
            if not sig['args']:
                return 'NOARG', []

            # Need to update overrides.vfl.
            if name not in functions_parsed:
                return 'NODOC', []

            # Shortcuts.
            rtrn = sig['return']
            args = [simplify(s) for s in sig['args']]

            # Exact match.
            for psig in functions_parsed[name]:
                pargs = [simplify(a) for a in psig['args']]
                if args == pargs and rtrn == psig['return']:
                    return 'EXACT', psig['argnames'][:]

            # Guess for an array functions with type and two arguments changing.
            for psig in functions_parsed[name]:
                pargs = [simplify(a) for a in psig['args']]
                scope = ['append', 'find', 'getcomp', 'insert', 'pop',
                         'push', 'removeindex', 'removevalue', 'reorder',
                         'reverse', 'select', 'setcomp', 'slice', 'upush']
                if name in scope and len(args) == len(pargs):
                    if sum(1 for x, y in zip(args, pargs) if x != y) == 2 or                             sum(1 for x, y in zip(args, pargs) if x != y) == 1 and rtrn != psig['return']:
                        return 'ARRAY', psig['argnames'][:]

            # Guess for return type changes.
            for psig in functions_parsed[name]:
                pargs = [simplify(a) for a in psig['args']]
                if args == pargs:
                    return 'RETRN', psig['argnames'][:]

            # Guess for one of the arguments type changes.
            for psig in functions_parsed[name]:
                pargs = [simplify(a) for a in psig['args']]
                if len(args) == len(pargs) and rtrn == psig['return']:
                    if sum(1 for x, y in zip(args, pargs) if x != y) == 1:
                        return 'ARGMT', psig['argnames'][:]

            # Guess for a combination of return and argument types changes.
            for psig in functions_parsed[name]:
                pargs = [simplify(a) for a in psig['args']]
                if len(args) == len(pargs):
                    if sum(1 for x, y in zip(args, pargs) if x != y) == 1:
                        return 'REARG', psig['argnames'][:]

            # Can't guess. Should update overrides.vfl.
            return 'ERROR', []

        sig['state'], sig['argnames'] = fill()


# In[9]:

def debug_filled():
    '''Print debug info about filled signatures.'''
    for function in sorted(functions_filled):
        for sig in functions_filled[function]:
            def logsig(symbol):
                '''Print function info in console.'''
                def cleanup(raw_arg):
                    '''Cleanup visual representation of an argument.'''
                    arg = simplify(raw_arg)
                    if 'const' not in raw_arg:
                        arg += ' &'
                    return arg

                args = zip([cleanup(a) for a in sig['args']], sig['argnames'])
                args = ', '.join([' '.join(pair) for pair in args])
                if 'variadic' in sig:
                    args += ', ...' if args else '...'

                sigstr = '{} {} {:<10}{}({})'.format(symbol, sig['state'], sig['return'], function, args)
                print(sigstr)

            if sig['state'] == 'ERROR':
                raise Exception('Unfilled function: "%s".' %function)
            elif sig['state'] == 'NODOC':
                raise Exception('Unknown function: "%s". Update overrides.vfl.' %function)
            elif sig['state'] in 'EXACT':
    #             logsig('+')
                pass
            elif sig['state'] in 'NOARG':
    #             logsig('+')
                pass
            elif sig['state'] == 'RETRN':
    #             logsig('?')
                pass
            elif sig['state'] == 'ARGMT':
    #             logsig('?')
                pass
            elif sig['state'] == 'REARG':
    #             logsig('?')
                pass
            elif sig['state'] == 'ARRAY':
    #             logsig('?')
                pass
            else:
                raise Exception('Memory error: something forgotten.')

debug_filled()


# ##### Generate completions
# Generate sublime completions in JSON format. Write completions into a `functions.sublime-completions` file.

# In[10]:

# Make JSON structure of sublime completions.
comps = collections.OrderedDict()
comps['scope'] = 'source.vex'
comps['completions'] = []

# Keep track of existing completions.
unique_triggers = set()

for function in sorted(functions_filled, key=lambda x: x.lower()):
    for sig in functions_filled[function]:
        # Build trigger.
        args = sig['argnames'][:]
        # Add vararg ellipsis.
        if 'variadic' in sig:
            if args:
                args[-1] += ', ...'
            else:
                args = ['...']
        trigger = '%s(%s)' %(function, ', '.join(args))

        # Completion exists.
        if trigger in unique_triggers:
            continue
        # Completion not exists. Make a new one.
        unique_triggers |= {trigger}

        # Build contents.
        args = []
        counter = 1
        for i, arg in enumerate(sig['argnames'], 1):
            args.append('${%d:%s}' %(i, arg))
            counter = i + 1
        # Add vararg ellipsis.
        if 'variadic' in sig:
            if args:
                args[-1] += '${%d:, ...}' %counter
            else:
                args = ['${%d:...}' %counter]
        contents = '%s(%s)' %(function, ', '.join(args))

        # Add completion into the common dictionary.
        comp = collections.OrderedDict()
        comp['trigger'] = trigger
        comp['contents'] = contents
        comps['completions'].append(comp)

# Dump completions into completions file.
with open('functions.sublime-completions', 'w') as f:
    json.dump(comps, f, indent=4)


# In[11]:

def debug_comps():
    '''Print debug info about written completions.'''
    print('Written %d completions.' %len(unique_triggers))

debug_comps()

