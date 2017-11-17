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
    '''Simulates 'which' program (probably) performing executable search.'''

    def is_exe(path):
        return op.isfile(path) and os.access(path, os.X_OK)

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
    '''
    Wrap code into a function.

    This allow to compile small VEX snippets without need to manually wrap
    them into functions and convert all attributes into argument bindings.
    '''
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
                bindings.append((type_, name))
                piece[j] = '@' + name

        piece = ''.join(piece)

        # Turn bindings into function arguments.
        types = {
            'f': 'float', 'u': 'vector2', 'v': 'vector', 'p': 'vector4',
            '2': 'matrix2', '3': 'matrix3', '4': 'matrix', 'i': 'int',
            's': 'string'
        }
        common = {
            'accel': 'v', 'Cd': 'v', 'center': 'v', 'dPdx': 'v', 'dPdy': 'v',
            'dPdz': 'v', 'force': 'v', 'N': 'v', 'P': 'v', 'rest': 'v',
            'scale': 'v', 'torque': 'v', 'up': 'v', 'uv': 'v', 'v': 'v',
            'backtrack': 'p', 'orient': 'p', 'rot': 'p', 'id': 'i', 'ix': 'i',
            'iy': 'i', 'iz': 'i', 'nextid': 'i', 'numprim': 'i', 'numpt': 'i',
            'numvtx': 'i', 'primnum': 'i', 'pstate': 'i', 'ptnum': 'i',
            'resx': 'i', 'resy': 'i', 'resz': 'i', 'vtxnum': 'i',
            'instance': 's', 'name': 's'
        }
        for type_, name in bindings:
            if name not in bound:
                prefix = type_.strip('[]')

                if not prefix:
                    name_noinput = re.sub(r'opinput\d_', r'', name)
                    if name_noinput in common:
                        prefix = common[name_noinput]
                    elif name.startswith('group_'):
                        prefix = 'i'
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
    source = 'void vcc_build_from_sublime_text(%s)\n{\n%s\n}\n' % (args, source)
    source = source.replace('@', '_bound_')

    return source


class VexBuildCommand(sublime_plugin.WindowCommand):
    '''
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
    '''

    # Track if VCC not finished or the command is broken. Mostly if broken.
    running = False

    def run(self,
            executable='vcc',
            context=None,
            compile_all=True,
            include_dirs=None,
            vex_output='stdout',
            snippet=False):

        if self.running:
            sublime.status_message('VCC is currently running...')
            return

        if not which(executable):
            sublime.status_message("Can't find VCC executable.")
            return

        if not self.window.active_view().file_name():
            sublime.status_message('Please, save the file before building')
            return

        self.executable = executable
        self.context = context
        self.compile_all = compile_all
        self.include_dirs = include_dirs
        self.vex_output = vex_output
        self.snippet = snippet

        # Setup main variables.
        window = self.window
        view = window.active_view()
        self.src = view.substr(sublime.Region(0, view.size()))
        self.vars = window.extract_variables()

        # Create and show output panel.
        self.output = window.create_output_panel('exec')
        settings = self.output.settings()
        settings.set(
            'result_file_regex',
            r'^File "(.+)", line (\d+), columns? (\d+(?:-\d+)?): (.*)$'
        )
        settings.set('line_numbers', False)
        settings.set('gutter', False)
        settings.set('scroll_past_end', False)
        settings.set('result_base_dir', self.vars['file_path'])
        self.output.assign_syntax('Packages/VEX/syntax/VEX Build.sublime-syntax')

        # Respect generic user preference about build window.
        if sublime.load_settings('Preferences.sublime-settings').get('show_panel_on_build', True):
            window.run_command('show_panel', {'panel': 'output.exec'})

        # Run VCC in other thread.
        threading.Thread(target=self.worker).start()

    def expand(self, value):
        return sublime.expand_variables(value, self.vars)

    def worker(self):
        self.running = True  # Track running VCC instances.
        self.started = time.time()
        sublime.status_message('Compiling VEX...')

        # In snippet mode, wrap source and save it to a temporary file.
        if self.snippet:
            self.generated_code = snippet_to_vex(self.src)
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as f:
                f.write(self.generated_code)
                self.tempfile = f.name

        # Call VCC and check output.
        cmd = [self.expand(self.executable)]

        if self.compile_all:
            cmd.append('--compile-all')

        if self.context:
            cmd.extend(['--context', self.context])

        if self.include_dirs:
            for d in self.include_dirs:
                cmd.extend(['--include-dir', self.expand(d)])

        if self.vex_output:
            cmd.extend(['--vex-output', self.expand(self.vex_output)])

        # Specify input file.
        if self.snippet:
            cmd.append(self.tempfile)
        else:
            cmd.append(self.vars['file'])

        proc = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE, universal_newlines=True)
        proc.wait()
        vcc = proc.stderr.read()

        self.output.run_command('append', {
            'characters': self.format_output(vcc),
            'force': True,
            'scroll_to_end': True
        })

        # Delete generated code file.
        if self.snippet:
            os.remove(self.tempfile)

        sublime.status_message('Finished compiling VEX')
        self.running = False

    @staticmethod
    def match_columns(cols, genline, srcline):
        '''
        Error lines and columns generated by wrapped code make no sense with
        actual, non-wrapped code.

        This function will fix columns comparing two lines and splitting them
        into lists with similar structure:

            _bound_|foo = 4.2; |_bound_|bar = {4, 2};
                  @|foo = 4.2; |   i[]@|bar = {4, 2};

        Then two simple counters will be used to match column numbers.
        '''
        parts = zip(re.split(r'((?:\b[\w\d](?:\[\])?)?@)(?=[\w\d_]+)', srcline),
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

    def format_output(self, output):
        '''
        Beautify output and fix issues caused by code wrapping.

        TODO: fix splitting the whole file inside for loop.
        '''

        output = output.strip()
        if not output:
            return 'Successfully compiled in %.02fs' % (time.time() - self.started)

        parsed = []
        for line in output.split('\n'):
            match = re.match(r'^(.+?):(?:(\d+):(\d+(?:-\d+)?):)?\s+(.+?):\s+(.+)$', line)
            file, row, cols, err, msg = match.groups()
            file = op.normpath(file)

            # Sometimes VCC don't output lines and columns.
            row = int(row) if row else 1
            cols = [int(n) for n in cols.split('-')] if cols else [0]
            parsed.append([file, row, cols, err, msg])

        messages = []

        if self.snippet:
            srclines = self.src.split('\n')
            genlines = self.generated_code.split('\n')

        for file, row, cols, err, msg in parsed:
            # Format messy function suggestions.
            if 'Candidates are:' in msg:
                msg, funs = msg.split(': ', 1)
                funs = '\n                '.join(funs.split(', '))
                msg = '%s:\n                %s\n' % (msg, funs)

            if self.snippet and file == self.tempfile:
                # Fix row and columns numbers.
                row = row - 2
                srcline = srclines[min(row-1, len(srclines)-1)]  # Temp fix for Index errors.
                cols = self.match_columns(cols, genlines[row+1], srcline)
                file = self.vars['file']
            else:
                with open(file, encoding='utf-8') as f:
                    srcline = f.readlines()[row-1].rstrip()

            # Add arrows under source code line pointing an error.
            arrows = ' ' * (cols[0]-1) + '^' * (cols[-1] - (cols[0]-1))

            # Format columns representation.
            col_or_cols = 'column' if len(cols) == 1 else 'columns'
            cols = '-'.join(str(c) for c in cols)

            message = '''\
            File "{file}", line {row}, {col_or_cols} {cols}: {err}: {msg}
                {srcline}
                {arrows}
            '''.format(**locals())

            messages.append(textwrap.dedent(message))

        output = '\n'.join(messages)

        # if self.snippet:
        #     output = '\n'.join([output, 'Generated code:', self.generated_code])

        return output
