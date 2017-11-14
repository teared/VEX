import re
import os
import os.path as op
import subprocess
import threading
import tempfile
import textwrap
import time

import sublime
import sublime_plugin


class VexBuildCommand(sublime_plugin.WindowCommand):
    '''
    Compile VEX code in different ways.

    Note:
        Currently, this build command used only for syntax checking, with no
        compiled VEX output, since it is the most obvious motivation to use
        this command, and to avoid feature bloat.

    Supported customizations:
        special_mode == None (default)
            Run VCC on the current file and do only output formatting.

        special_mode == 'snippet'
            Parse attribute bindings and wrap the code into a "Snippet-style"
            function. Similar to what Snippet node does. Then run VCC over
            generated code.

            Since most Houdini coding is just editing wrangles with 5-10 lines
            of code, this provides convenient way to fix typos and compile
            errors without need to go back and forth between Houdini and
            Sublime.

        special_mode == 'library'
            Run VCC on the current file within CVEX context and do only output
            formatting. Best for arbitrary VEX code.
    '''

    # Track if VCC not finished or the command is broken. Mostly if broken.
    running = False

    def run(self, special_mode=None):
        if not self.window.active_view().file_name():
            sublime.status_message('Please, save the file before building')
            return

        if self.running:
            sublime.status_message('VCC is currently running...')
            return

        # Setup main variables.
        self.special_mode = special_mode
        view = self.window.active_view()
        self.src = view.substr(sublime.Region(0, view.size()))
        self.file = view.file_name()

        # Create and show output panel.
        self.output = self.window.create_output_panel('exec')
        self.output.assign_syntax('Packages/VEX/syntax/VEX Build.sublime-syntax')
        prefs = self.output.settings()
        prefs.set('result_base_dir', op.dirname(self.file))
        prefs.set('result_file_regex', r'^File "(.+)", line (\d+), columns? (\d+(?:-\d+)?): (.*)$')
        prefs.set('line_numbers', False)
        prefs.set('gutter', False)
        prefs.set('scroll_past_end', False)

        # Respect generic user preference about build window.
        prefs = sublime.load_settings('Preferences.sublime-settings')
        if prefs.get('show_panel_on_build', True):
            self.window.run_command('show_panel', {'panel': 'output.exec'})

        # Run VCC in other thread.
        t = threading.Thread(target=self.worker)
        t.start()

    def worker(self):
        self.running = True  # Track running VCC instances.
        self.started = time.time()
        sublime.status_message('Compiling VEX...')

        # Write generated code to temporary file.
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as f:
            self.tempfile = f.name

            self.generated_code = self.src
            if self.special_mode == 'snippet':
                self.generated_code = self.decorate_source(self.generated_code)

            f.write(self.generated_code)

        # Call VCC and check output.
        prefs = sublime.load_settings('VEX.sublime-settings')
        vcc_executable = prefs.get('vcc_executable', 'vcc')

        cmd = [
            vcc_executable, '--compile-all',
            '--vex-output', 'stdout',
            '--include-dir', op.dirname(self.file),
            '--include-dir', op.join(op.dirname(self.file), 'include'),
        ]

        if self.special_mode:
            cmd.extend(['--context', 'cvex'])

        # Specify input file.
        if self.special_mode == 'snippet':
            cmd.append(self.tempfile)
        else:
            cmd.append(self.file)

        proc = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE, universal_newlines=True)
        proc.wait()
        vcc = proc.stderr.read()

        self.output.run_command('append', {
            'characters': self.format_output(vcc),
            'force': True,
            'scroll_to_end': True
        })

        # Delete generated code file.
        if op.exists(self.tempfile):
            os.remove(self.tempfile)

        sublime.status_message('Finished compiling VEX')
        self.running = False

    @staticmethod
    def decorate_source(source):
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
            print(line)
            match = re.match(r'^(.+?):(?:(\d+):(\d+(?:-\d+)?):)?\s+(.+?):\s+(.+)$', line)
            file, row, cols, err, msg = match.groups()
            file = op.normpath(file)

            # Sometimes VCC don't output lines and columns.
            row = int(row) if row else 1
            cols = [int(n) for n in cols.split('-')] if cols else [0]
            parsed.append([file, row, cols, err, msg])

        messages = []
        for file, row, cols, err, msg in parsed:
            # Format messy function suggestions.
            if 'Candidates are:' in msg:
                msg, funs = msg.split(': ', 1)
                funs = '\n                '.join(funs.split(', '))
                msg = '%s:\n                %s\n' % (msg, funs)

            if file == self.tempfile:
                # Fix row and columns numbers.
                row = row - 2
                srclines = self.src.split('\n')
                srcline = srclines[min(row-1, len(srclines)-1)]  # Temp fix for Index errors.
                cols = self.match_columns(cols, self.generated_code.split('\n')[row+1], srcline)
                file = self.file
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

        show_generated_code_on_build = False  # Former user preference.
        if show_generated_code_on_build:
            output = '{}\nGenerated code:\n{}'.format(output, self.generated_code)

        return output
