import collections
import json
import os
import re

if __name__ == '__main__':
    dir = os.path.dirname(__file__)
    path = os.path.join(dir, "expressions.cmd")

    with open(path, "r") as f:
        lines = f.readlines()

    comps = []
    for line in lines:
        match = re.match(r"(\w+) (\w+)\((.*)\)", line)
        type, name, args = match.group(1,2,3)

        args = args.split(",")
        args = [arg.strip() for arg in args]

        args_names = []
        for arg in args:
            aname = ""
            if arg != "":
                atype, aname = arg.split()
            args_names.append(aname)

        args_subs = []
        for i, arg in enumerate(args,1):
            if arg != "":
                arg = "${{{}:{}}}".format(i, arg)
            args_subs.append(arg)

        trigger = "{}({})".format(name, ", ".join(args_names))
        contents = "{}({})".format(name, ", ".join(args_subs))

        entry = collections.OrderedDict()
        entry["trigger"] = trigger
        entry["contents"] = contents
        comps.append(entry)

    comps_dict = collections.OrderedDict()
    comps_dict["scope"] = "source.hscript"
    comps_dict["completions"] = comps

    outpath = os.path.join(dir, "expressions.sublime-completions")
    with open(outpath, "w") as f:
        json.dump(comps_dict, f, indent=4)
