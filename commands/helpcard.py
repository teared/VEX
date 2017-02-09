import sublime
import sublime_plugin
import json
import os.path as op
import webbrowser
import zipfile


class HelpcardCommand(sublime_plugin.TextCommand):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load helpcards and CSS files.
        here = op.dirname(__file__)
        root = op.dirname(here)

        if op.basename(root) == 'VEX.sublime-package':
            with zipfile.ZipFile(root) as z:
                with z.open('commands/helpcard.css') as f:
                    self.style = f.read().decode()
                with z.open('commands/helpcards.json') as f:
                    self.helpcards = json.loads(f.read().decode())
        else:
            with open(op.join(here, 'helpcard.css')) as f:
                self.style = f.read()
            with open(op.join(here, 'helpcards.json')) as f:
                self.helpcards = json.load(f)

    def run(self, edit):
        first_sel = self.view.sel()[0].a
        scope = self.view.scope_name(first_sel)
        lang = scope.split(' ', 1)[0].split('.')[1]
        word = self.view.substr(self.view.word(first_sel))

        if word in self.helpcards[lang]:
            html = '<style>%s</style>%s' % (self.style, self.helpcards[lang][word])
        else:
            # Not sure if search on google CSE will always work.
            # Last cx parameter was: 001106583893786776783:4dnyszriw9c
            html = '''
            <style>{style}</style>

            <div id="helpcard">
                <h1>{term}</h1>
                <p class="summary">
                No popup help available for "{term}".
                </p>
                <p>Search online:
                    <a href="https://cse.google.com/cse?cx=001106583893786776783%3A4dnyszriw9c&q={term}">Docs</a> |
                    <a href="https://encrypted.google.com/search?&q=site%3Asidefx.com+OR+site%3Aodforce.net+{term}">Community</a> |
                    <a href="https://encrypted.google.com/search?&q={term}">Google</a>
                </p>
            </div>
            '''.format(term=word, style=self.style)

        s = sublime.load_settings('VEX (package settings).sublime-settings')
        self.view.show_popup(html, on_navigate=webbrowser.open,
                             max_width=s.get('popup_max_width'),
                             max_height=s.get('popup_max_height'))
