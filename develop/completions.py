#! python3.4

import collections
import itertools
import json
import os
import pickle
import re
import subprocess


HFS = "C:\Program Files\Side Effects Software\Houdini 14.0.335"


def vcc_sigs(vcc_path):
    """Collect functions from vcc output into a dictionary"""
    # Get a list of all VEX contexts.
    contexts = subprocess.check_output(
        [vcc_path, "--list-context"],
        universal_newlines=True
    )
    contexts = contexts.split()

    # Create a dictionary with function signatures as keys.
    sigs = dict()
    for context in contexts:
        # Get the full vcc output for this context.
        output = subprocess.check_output(
            [vcc_path, "--list-context", context],
            universal_newlines=True
        )
        print(output)
        # Skip lines to the beginning of the functions list.
        output = output.partition("Functions:\n")[2]

        for line in output.split("\n"):
            pattern = r"\s*(.+?) (.+)\( (.*) \)"
            match = re.match(pattern, line)
            if not match:
                continue

            type, name, args = match.group(1, 2, 3)
            args = args.split(";")
            args = [arg.strip() for arg in args]
            args = tuple(args)
            sig = (type, name, args)

            # Accumulate the signature's context in the value list.
            if sig in sigs:
                sigs[sig] += [context]
            else:
                sigs[sig] = [context]

    return sigs


def parse_sigs(docfiles_path, overrides_path):
    """Parse all function signatures from Houdini docs and overrides file."""

    def vex_type(string):
        """Return True if string is a valid VEX type name."""
        return string.strip("[]& ") in [
            "void", "int", "float", "string", "vector2", "vector", "vector4",
            "matrix2", "matrix3", "matrix", "bsdf", "light", "material"
        ]

    def parse_single_sig(string):
        """Parse a function's type, name, do the same for the arguments."""
        # Replace all substrings using a dictionary mapping.
        mapping = {
            ";"       : ",",
            "'"       : '"',
            "matrix4" : "matrix",
            "vector3" : "vector"
        }
        for item in mapping:
            if item in string:
                string = string.replace(item, mapping[item])

        # Lots of documented functions skips possible vararg arguments.
        # Therefore we always can reveal its presence from the VCC output.
        # And since "void" arguments is possible only with zero-argument
        # signatures, skip parsing "void"-arguments definitions too. On the
        # filling stage we can easily fill sigs with "(void)", "(...)" or
        # append "..." to arguments if varargs present.

        pattern = r"\(\s*(void|\.\.\.)?\s*\)"
        match = re.search(pattern, string)
        if match:
            return

        # Check if function arguments is useless list of unnamed types.
        pattern = r"\(\s*(.+)\s*\)"
        args = re.search(pattern, string)
        args = args.group(1)
        args = args.split(",")
        args = [x.strip("&[] ") for x in args]
        if all(vex_type(x) for x in args):
            return

        pattern = r"(\w+(?:\s?\[\])?)?\s*(\b\w+\b)\(\s*(.+)\s*\)"
        match = re.match(pattern, string)
        if not match:
            return
        type, name, args = match.group(1,2,3)

        if type == None:
            type = "void"
        elif not vex_type(type):
            return

        # Parse the arguments types and names.
        parsed_args = []
        for arg in args.split(","):
            if "..." not in arg:
                modifier = ""
                if "[]" in arg:
                    modifier += "[]"
                if "&" in arg:
                    modifier += " &"

                arg = arg.replace("const ", " ")
                arg = arg.replace("&", " ")
                arg = arg.replace("[]", " ")
                arg = [x.strip() for x in arg.split()]
                if len(arg) != 2:
                    return

                atype = arg[0]
                atype += modifier
                if not vex_type(atype):
                    return

                aname = arg[1]
                pattern = r"(\w+)(=(?:'|\")\w*?(?:'|\")|=[\d.]+)?$"
                match = re.match(pattern, aname)
                if not match:
                    return

                parsed_args.append((atype, aname))

        return type, name, parsed_args

    def parser(strings):
        """Run parse_single_sig() function on each string."""
        sigs = {}
        for string in strings:
            sig = parse_single_sig(string)
            if not sig:
                continue

            type, name, args = sig
            atypes, anames = zip(*args)
            sigs[(type, name, atypes)] = anames

            # "Default value" creates a second signature without an argument.
            if "=" in anames[-1]:
                atypes, anames = zip(*args[:-1])
                sigs[(type, name, atypes)] = anames

        return sigs

    # Get all strings appears to have a function signature example.
    sigs = []
    for docfile in os.listdir(docfiles_path):
        base, ext = os.path.splitext(docfile)
        if ext != ".txt":
            continue
        path = os.path.join(docfiles_path, docfile)
        with open(path, "r") as f:
            for line in f:
                pattern = r"# `((?:\w+\s*(?:\[\])?)?\s*(?:\b\w+\b)\(.*\))`"
                match = re.search(pattern, line)
                if not match:
                    continue
                if base in match.group(1):
                    sigs.append(match.group(1))
    sigs = parser(sigs)

    # Parse all stings from overrides, then update sigs dictionary.
    overrides = []
    with open(overrides_path, "r") as f:
        for line in f:
            pattern = r"^\s*\w+(?:\[\])?\s+\b\w+\b\(.+\)\s*$"
            match = re.match(pattern, line)
            if not match:
                continue
            overrides.append(match.group())
    sigs.update(parser(overrides))

    return sigs


def fill_sigs(sigs, docsigs):
    """Generate plain list of signatures, fill argument names."""

    def fill_single_sig(inputsig, docsigs):
        """Complete signature definition with argument names."""

        def filler(info, anames=[]):
            """Return resulting signature with argument names."""
            args = itertools.zip_longest(inputsig[2], anames, fillvalue="")
            args = list(args)
            return inputsig[0], inputsig[1], args, info

        sig = (
            inputsig[0],
            inputsig[1],
            tuple(x for x in inputsig[2] if x not in ("...", "void"))
        )
        _, name, atypes = sig

        # No arguments - no need to guess.
        if len(atypes) == 0:
            return filler("+ NOARG")

        # No help function parsed - nothing to guess.
        if name not in docsigs:
            return filler("- NODOC")

        docsigs = docsigs[name]

        # Full match.
        if sig in docsigs:
            return filler("+ EXACT", docsigs[sig])

        # Guess for return type changes.
        # Docs:   int foo(string bar)
        # VCC:    float foo(string)
        # Result: float foo(string bar)
        for docsig in docsigs:
            doctypes = docsig[2]
            if atypes == doctypes:
                return filler("? RETRN", docsigs[docsig])

        # Guess for one of the arguments type changes.
        # Docs:   string foo(int bar)
        # VCC:    string foo(float)
        # Result: string foo(float bar)
        for docsig in docsigs:
            if sig[0] != docsig[0]:
                continue
            doctypes = docsig[2]
            if len(atypes) != len(doctypes):
                continue
            pairs = zip(atypes, doctypes)
            diffs = [True for x, y in pairs if x != y]
            if len(diffs) == 1:
                return filler("? ARGMT", docsigs[docsig])

        # Guess for a combination of return and argument type changes.
        # Docs:   int foo(int bar)
        # VCC:    float foo(float)
        # Result: float foo(float bar)
        for docsig in docsigs:
            doctypes = docsig[2]
            if len(atypes) != len(doctypes):
                continue

            pairs = zip(atypes, doctypes)
            diffs = [(x, y) for x, y in pairs if x != y]
            if len(diffs) == 1:
                return filler("? REARG", docsigs[docsig])

        # Guess for an array functions with type and two arguments changing.
        # Docs:   void foo(int value, int[] array)
        # VCC:    void foo(float, float[])
        # Result: float foo(float value, float[] array)
        for docsig in docsigs:
            names_scope = [
                "append", "find",
                "insert", "push",
                "removevalue", "select",
                "setcomp", "upush"
            ]
            if sig[1] not in names_scope:
                continue

            doctypes = docsig[2]
            if len(atypes) != len(doctypes):
                continue

            pairs = zip(atypes, doctypes)
            diffs = [(x, y) for x, y in pairs if x != y]
            if len(diffs) != 2:
                continue

            pairs = zip(*diffs)
            pairs = [(x.strip("[]& "), y.strip("[]& ")) for x, y in pairs]
            diffs = [True for x, y in pairs if x != y]
            if not diffs:
                return filler("? ARRAY", docsigs[docsig])

        return filler("- ERROR")

    # Group by name to reduce iterations.
    gdocsigs = docsigs.items()
    keyfunc = lambda x: x[0][1]
    gdocsigs = sorted(gdocsigs, key=keyfunc)
    gdocsigs = itertools.groupby(gdocsigs, keyfunc)
    gdocsigs = {key: dict(val) for key, val in gdocsigs}

    # Run parse_single_sig() function on each sig.
    sigs = [fill_single_sig(sig, gdocsigs) for sig in sigs]
    sigs = sorted(sigs, key=lambda x: x[1].lower())
    return sigs


def write_sigs(out_path, sigs):
    """Write sigs to disc as a readable file."""
    with open(out_path, "w") as f:
        for type, name, args, info in sigs:
            args = ", ".join([" ".join(arg).strip() for arg in args])
            line = "{}{:>10} {}({})\n".format(info, type, name, args)
            if info in [
                "- ERROR",
                "- NODOC",
                "+ EXACT",
                "+ NOARG",
                "? ARGMT",
                "? ARRAY",
                "? REARG",
                "? RETRN",
            ]: f.write(line)


def write_comps(out_path, sigs):
    """Generate sublime-completions file for unique signatures."""

    # Accumulate a unique argument names sets per function.
    comps_dict = dict()
    for type, name, args, info in sigs:
        trigger = [t if t in ("...", "void") else n for t, n in args]
        contents = []
        for i, arg in enumerate(trigger, 1):
            string = "${{{}:{}}}".format(i, arg)
            contents.append(string)

        key = "{}({})".format(name, ", ".join(trigger))
        val = "{}({})".format(name, ", ".join(contents))

        if key not in comps_dict:
            comps_dict[key] = val

    # Turn entries into actual dictionaries as in completions.
    comps_list = []
    for trigger, contents in comps_dict.items():
        comp = collections.OrderedDict()
        comp["trigger"] = trigger
        comp["contents"] = contents
        comps_list.append(comp)

    # Replace void signatures with empty parentheses.
    for i, comp in enumerate(comps_list):
        if "(void)" in comp["trigger"]:
            trigger = comp["trigger"].replace("void", "")
            contents = comp["contents"].replace("${1:void}", "")
            comps_list[i]["trigger"] = trigger
            comps_list[i]["contents"] = contents

    comps_list.sort(key=lambda x: x["trigger"].lower())
    comps = collections.OrderedDict()
    comps["scope"] = "source.vex"
    comps["completions"] = comps_list

    with open(out_path, "w") as f:
        json.dump(comps, f, indent=4)


if __name__ == '__main__':
    """The main function."""
    data_dir = os.path.join(os.path.dirname(__file__))

    # Query VCC for all real functions from all contexts.
    vcc_dump = os.path.join(data_dir, "vcc_dump.p")
    if os.path.exists(vcc_dump):
        with open(vcc_dump, "rb") as f:
            sigs = pickle.load(f)
    else:
        # Create dump for time saving.
        vcc_path = os.path.join(HFS, "bin", "vcc")
        sigs = vcc_sigs(vcc_path)
        with open(vcc_dump, "wb") as f:
            pickle.dump(sigs, f)

    # Get signatures with argument names from help and overrides file.
    docfiles_path  = os.path.join(HFS, "houdini", "help", "vex", "functions")
    overrides_path = os.path.join(data_dir, "overrides.vfl")
    docsigs = parse_sigs(docfiles_path, overrides_path)

    # Fill real functions with argument names.
    sigs = fill_sigs(sigs, docsigs)

    # Write sigs to disc.
    sigs_out_path = os.path.join(data_dir, "signatures.vfl")
    write_sigs(sigs_out_path, sigs)

    # Generate completions file.
    comps_out_path = os.path.join(data_dir, "functions.sublime-completions")
    write_comps(comps_out_path, sigs)