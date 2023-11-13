import re
import os
import sys
import os.path as op
import subprocess
import threading
import tempfile
import textwrap
import time

import sublime
import sublime_plugin


def which(executable):
    """Simulates 'which' program (probably) performing executable search."""

    def is_exe(filepath):
        return op.isfile(filepath) and os.access(filepath, os.X_OK)

    head, _ = op.split(executable)
    if head and is_exe(executable):
        return executable

    for path in os.environ['PATH'].split(os.pathsep):
        exe_file = op.join(path, executable)
        if is_exe(exe_file):
            return exe_file

        # Perform search for "program.exe" if executable is only "program".
        if sys.platform == 'win32':
            _, ext = op.splitext(exe_file)
            if not ext:
                for ext in os.environ['PATHEXT'].split(os.pathsep):
                    if is_exe(exe_file + ext):
                        return exe_file + ext

    return None


def snippet_to_vex(source):
    """
    Wrap code into a function.

    This allows to compile small VEX snippets without need to manually wrap
    them into functions and convert all attributes into argument bindings.
    """
    bound = set()  # Keeping track of bound attribute names.
    args = []

    comment_extract_pattern = r'(\/\*(?:.|\n)*?\*\/|\/\/.*?\n)'
    attribute_extract_pattern = r'((?:\b[\w\d](?:\[\])?)?@[\w\d_]+)'
    prototype_pattern = r'^(\b[\w\d]+)\s+@([\w\d_]+)(\s*\[\s*\])?(?=\s*.*;.*?$)'

    pieces = re.split(comment_extract_pattern, source)
    for i, piece in enumerate(pieces):

        # Skip comments.
        if piece.startswith('//') or piece.startswith('/*'):
            continue

        # Turn prototypes into function arguments.
        piece = piece.split('\n')
        for j, line in enumerate(piece):
            match = re.match(prototype_pattern, line)
            if match:
                name = match.group(2)
                if name not in bound:
                    args.append(match.group(0))
                    bound.add(name)
                piece[j] = '// Prototype for %s eluded.' % name

        piece = '\n'.join(piece)

        # Extract bindings like v@foo.
        piece = re.split(attribute_extract_pattern, piece)
        bindings = []
        for j, fragment in enumerate(piece):
            if '@' in fragment:
                type_, name = fragment.split('@')
                if not name.isidentifier():
                    raise ValueError('Bad attrubute name: ' + str(name))
                bindings.append((type_, name))
                piece[j] = '@' + name

        piece = ''.join(piece)

        # Turn bindings into function arguments.
        types = {
            'f': 'float', 'u': 'vector2', 'v': 'vector', 'p': 'vector4',
            '2': 'matrix2', '3': 'matrix3', '4': 'matrix', 'i': 'int',
            's': 'string'
        }

        # https://www.sidefx.com/docs/houdini/vex/snippets.html#known
        known_vector = 'P accel Cd N scale force rest torque up uv v center dPdx dPdy dPdz'.split()
        known_vector4 = 'backtrack orient rot'.split()
        known_int = 'id nextid pstate elemnum ptnum primnum vtxnum numelem numpt numprim numvtx ix iy iz resx resy resz'.split()
        known_string = 'name instance'.split()

        common = {}
        common.update({attr: 'v' for attr in known_vector})
        common.update({attr: 'p' for attr in known_vector4})
        common.update({attr: 'i' for attr in known_int})
        common.update({attr: 's' for attr in known_string})

        for type_, name in bindings:
            if name not in bound:
                prefix = type_.strip('[]')

                if not prefix:
                    name_noinput = re.sub(r'opinput\d_', r'', name)
                    if name_noinput in common:
                        prefix = common[name_noinput]
                    elif name.startswith('group_'):
                        prefix = 'i'
                    elif name.startswith('OpInput'):
                        prefix = 's'
                    else:
                        prefix = 'f'

                arg = '{} @{}{}'.format(
                    types[prefix], name,
                    '[]' if type_.endswith('[]') else ''
                )
                args.append(arg)
                bound.add(name)

        pieces[i] = piece

    # Collect everything into same string.
    args = '; '.join(args)
    source = ''.join(pieces)
    source = '#include <math.h>\nvoid vcc_build_from_sublime_text(%s)\n{\n%s\n}\n' % (args, source)
    source = source.replace('@', '_bound_')

    return source


class VexBuildCommand(sublime_plugin.WindowCommand):
    """
    Compile VEX code in different ways.

    Currently, this build command used only for syntax checking, with no
    compiled VEX output, since it is the most obvious motivation to use this
    command, and to avoid feature bloat.

    Supported customizations:

    "snippet": true
        Parse attribute bindings and wrap the code into a "snippet-style"
        function. Similar to what Snippet node does. Then run VCC over
        generated code.

        Since most Houdini coding is just editing wrangles with 5-10 lines
        of code, this provides convenient way to fix typos and compile
        errors without need to go back and forth between Houdini and
        Sublime.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output = None  # Output panel instance.
        self.started = None  # Timestamp to track if VCC has not finished. Also used to display compile time.

    def run(self,
            executable='vcc',
            context=None,
            compile_all=True,
            include_dirs=None,
            vex_output='stdout',
            snippet=False):

        if self.started is not None:
            sublime.status_message('VCC is currently running...')
            return

        if not which(executable):
            sublime.status_message("Can't find VCC executable.")
            return

        if not self.window.active_view().file_name():
            sublime.status_message('Please, save the file before building')
            return

        # Setup main variables.
        window = self.window
        view = window.active_view()
        code = view.substr(sublime.Region(0, view.size()))
        variables = window.extract_variables()

        # Create and show output panel.
        self.output = window.create_output_panel('exec')
        settings = self.output.settings()
        settings.set(
            'result_file_regex',
            r'^File "(.+)"(?:, line (\d+), columns? (\d+(?:-\d+)?)): (.*)$'
        )
        settings.set('line_numbers', False)
        settings.set('gutter', False)
        settings.set('scroll_past_end', False)
        settings.set('result_base_dir', variables['file_path'])
        self.output.assign_syntax('Packages/VEX/syntax/VEX Build.sublime-syntax')

        # Respect generic user preference about build window.
        if sublime.load_settings('Preferences.sublime-settings').get('show_panel_on_build', True):
            window.run_command('show_panel', {'panel': 'output.exec'})

        # Run VCC in other thread.
        args = (executable, context, compile_all, include_dirs, vex_output, snippet, code, variables)
        threading.Thread(target=self.worker, args=args).start()

    def worker(self, executable, context, compile_all, include_dirs, vex_output, snippet, code, variables):
        self.started = time.time()  # Track running VCC instances.
        sublime.status_message('Compiling VEX...')

        # Call VCC and check output.
        cmd = [sublime.expand_variables(op.normpath(executable), variables)]

        if compile_all:
            cmd.append('--compile-all')

        if context:
            cmd.extend(['--context', context])

        if include_dirs:
            for include_dir in include_dirs:
                cmd.extend(['--include-dir', op.normpath(sublime.expand_variables(include_dir, variables))])

        if vex_output and vex_output != 'stdout':
            cmd.extend(['--vex-output', op.normpath(sublime.expand_variables(vex_output, variables))])
        else:
            cmd.extend(['--vex-output', 'stdout'])

        # Specify input file.
        if snippet:
            # In snippet mode, wrap source and save it to a temporary file.
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as f:
                try:
                    generated_code = snippet_to_vex(code)
                except (ValueError, KeyError) as e:
                    sublime.status_message('Cannot wrap code into a snippet function: ("%s") ' % e +
                                           'Usually due to erroneous @ usage.')
                    self.started = None
                    return
                file_path = f.name
                f.write(generated_code)
        else:
            code, generated_code = '', ''
            file_path = variables['file']
        cmd.append(file_path)

        # Avoid console window flashing on Windows.
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        proc = subprocess.Popen(cmd, startupinfo=startupinfo, stderr=subprocess.PIPE, universal_newlines=True)
        try:
            _, vcc_output = proc.communicate(timeout=30)
            vcc_output = vcc_output.strip()
            if vcc_output:
                try:
                    vcc_output = self.format_output(vcc_output, file_path, snippet, code, generated_code, variables['file'])
                except:  # Catch any errors during formatting.
                    vcc_output = "Add-on error: can't parse VCC output for this input"
            else:
                vcc_output = 'Successfully compiled in %.02fs' % (time.time() - self.started)
        except subprocess.TimeoutExpired:
            # The child process is not killed if the timeout expires,
            # so kill the child process and finish communication.
            proc.kill()
            proc.communicate()
            vcc_output = 'VCC execution timeout: compilation took longer than 30 seconds'

        # Delete generated code file.
        if snippet:
            os.remove(file_path)

        self.output.run_command('append', {
            'characters': vcc_output,
            'force': True,
            'scroll_to_end': True
        })

        sublime.status_message('Finished compiling VEX')
        self.started = None

    @staticmethod
    def match_columns(cols, genline, srcline):
        """
        Error lines and columns generated by wrapped code make no sense with
        actual, non-wrapped code.

        This function will fix columns comparing two lines and splitting them
        into lists with similar structure:

            _bound_|foo = 4.2; |_bound_|bar = {4, 2};
                  @|foo = 4.2; |   i[]@|bar = {4, 2};

        Then two simple counters will be used to match column numbers.
        """
        parts = zip(re.split(r'((?:\b\w(?:\[])?)?@)(?=[\w_]+)', srcline),
                    re.split(r'(\b_bound_)', genline))
        c1 = 0
        c2 = cols[0]
        for p1, p2 in parts:
            c1 += len(p1)
            c2 -= len(p2)
            if c2 <= 0:
                start = c1 + c2
                length = (cols[-1] - cols[0])
                end = start + length
                return [start, end] if start != end else [start]
        else:
            return cols

    def format_output(self, vcc_output, file_path='', snippet=False, code='', generated_code='', original_file_path=''):
        """
        Beautify output and fix issues caused by code wrapping.

        TODO: fix splitting the whole path inside for loop.
        """
        parsed = []
        for line in vcc_output.split('\n'):
            match = re.match(r'^(.+?):(?:(\d+):(\d+(?:-\d+)?):)?\s+(.+?):\s+(.+)$', line)
            path, row, cols, err, msg = match.groups()
            path = op.normpath(path)

            # Sometimes VCC don't output lines and columns.
            row = int(row) if row else None
            cols = [int(n) for n in cols.split('-')] if cols else [0]
            parsed.append([path, row, cols, err, msg])

        messages = []

        if snippet:
            srclines = code.split('\n')
            genlines = generated_code.split('\n')
        else:
            genlines = None
            srclines = None

        for path, row, cols, err, msg in parsed:
            if row:
                # Format messy function suggestions.
                if 'Candidates are:' in msg:
                    msg, funs = msg.split(': ', 1)
                    funs = '\n                '.join(funs.split(', '))
                    msg = '%s:\n                %s\n' % (msg, funs)

                if snippet and path == file_path:
                    # Fix row and columns numbers.
                    row = row - 3
                    srcline = srclines[min(row - 1, len(srclines) - 1)]  # Temp fix for Index errors.
                    cols = self.match_columns(cols, genlines[row + 2], srcline)
                    # Replace the Python tempfile with the Houdini-produced temp file.
                    path = original_file_path
                else:
                    with open(path, encoding='utf-8') as f:
                        srcline = f.readlines()[row - 1].rstrip()

                # Add arrows under source code line pointing an error.
                arrows = ' ' * (cols[0] - 1) + '^' * (cols[-1] - (cols[0] - 1))

                # Format columns representation.
                col_or_cols = 'column' if len(cols) == 1 else 'columns'
                cols = '-'.join(str(c) for c in cols)

                message = '''\
                File "{path}", line {row}, {col_or_cols} {cols}: {err}: {msg}
                    {srcline}
                    {arrows}
                '''.format(**locals())
            else:
                message = 'File "{path}": {err}: {msg}'.format(**locals())

            messages.append(textwrap.dedent(message))

        vcc_output = '\n'.join(messages)

        # # Debug generated code.
        # if snippet:
        #     vcc_output = '\n'.join([vcc_output, 'Generated code:', generated_code])

        return vcc_output
